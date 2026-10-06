#!/usr/bin/env node
/*
  Build the ICRP 60 system's data for dose_coefficients.html from DCAL.

      node scripts/gen-dose-icrp60.mjs <DCAL app folder> <ICRP-07 data folder>

  DCAL (Eckerman and Leggett, ORNL/TM-2001/190) is the software the ICRP's
  age-dependent dose coefficients for members of the public were computed with
  (Publications 56, 67, 69, 71, 72; compiled in Publication 119). ORNL
  distributes it at https://www.ornl.gov/crpk/software as DCAL01_setup.zip,
  an Inno Setup installer: unpack it with `innoextract DCAL01_setup.exe` and
  pass the resulting app/ folder. The second argument is only for the energy
  grid of the beta spectra, which the ICRP 38 file leaves implicit and the
  ICRP 107 file (ICRP-07.BET, in ORNL's Radiological Toolbox) writes out.

  Writes resources/data/dose/icrp60/:

      decay/index.json   every ICRP 38 nuclide: half-life, decay mode,
                         daughters and branching, emitted energy by kind
      decay/<El>.json    the radiations of each element's nuclides: lines and
                         beta spectra, read only when a chain needs them
      saf.json           specific absorbed fractions for photons in the
                         Cristy-Eckerman phantoms (newborn, 1, 5, 10, 15 y,
                         adult male, adult female), region masses, the
                         absorbed fractions for electrons and alphas, and
                         the ICRP 66 respiratory-tract absorbed fractions
      models.json        the biokinetic models: every systemic model and f1
                         file of DCAL's FGR-13 library (the ICRP 72 models),
                         the assignment rules, the ICRP 66 respiratory tract
                         models for Types F, M and S and for gases and
                         vapours, the deposition fractions, the ICRP 30
                         gastrointestinal tract, the bladder voiding rates
      cases.json         the inhalation and ingestion cases DCAL's batch
                         files ran: chain length, kinetics of the progeny,
                         special model and f1 files, adult age

  The numbers are the files' own; nothing is fitted or rounded beyond the six
  significant figures the files carry.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { icrp38Nuclides, compactRad, compactSpectrum, sig } from './lib/dose-decay.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'resources/data/dose/icrp60');

const [appDir, icrp07Dir] = process.argv.slice(2);
if (!appDir || !icrp07Dir) {
  console.error('usage: node scripts/gen-dose-icrp60.mjs <DCAL app folder> <ICRP-07 data folder>');
  process.exit(2);
}
const DAT = path.join(appDir, 'DAT');
const read = (...p) => fs.readFileSync(path.join(...p), 'latin1').replace(/\r/g, '').replace(/\x1a/g, '');
const write = (rel, obj) => {
  const file = path.join(OUT, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(obj));
  return fs.statSync(file).size;
};

/* ==========================================================================
   Decay data
   ========================================================================== */

/* ICRP 38 tells isomer pairs apart by a and b, in order of half-life, where
   later publications (ICRP 72 and 119, and ICRP 107) write the ground state
   plainly and the excited state with m (or n): Eu-150a is the 12.62 h
   isomer, Eu-150m; Eu-150b the 34.2 y ground state, Eu-150. Two pairs are
   the other way round in ICRP 38 itself: its Rh-102 (2.9 y) and Ta-180
   (1.0E13 y) are the excited states that ICRP 72 lists as Rh-102m and
   Ta-180m. The page uses the later names throughout; the half-lives are
   ICRP 38's. */
export const RENAME_38 = {
  'Eu-150a': 'Eu-150m', 'Eu-150b': 'Eu-150', 'In-110a': 'In-110m', 'In-110b': 'In-110',
  'Ir-186a': 'Ir-186', 'Ir-186b': 'Ir-186m', 'Ir-192m': 'Ir-192n', 'Nb-89a': 'Nb-89m', 'Nb-89b': 'Nb-89',
  'Nb-98': 'Nb-98m', 'Np-236a': 'Np-236', 'Np-236b': 'Np-236m', 'Re-182a': 'Re-182m', 'Re-182b': 'Re-182',
  'Sb-120a': 'Sb-120', 'Sb-120b': 'Sb-120m', 'Sb-128a': 'Sb-128m', 'Sb-128b': 'Sb-128',
  'Ta-178a': 'Ta-178', 'Ta-178b': 'Ta-178m', 'Rh-102': 'Rh-102m', 'Rh-102m': 'Rh-102',
  'Ta-180': 'Ta-180m', 'Ta-180m': 'Ta-180', 'Es-250': 'Es-250m',
};
const rename38 = (n) => RENAME_38[n] || n;

function buildDecay() {
  const nucs = icrp38Nuclides(path.join(DAT, 'nuc'), path.join(icrp07Dir, 'icrp-07.bet'));
  const index = {};
  const byEl = {};
  for (const n of nucs) {
    const name = rename38(n.name);
    index[name] = { t: n.t, T: sig(n.T, 8), m: n.mode, d: n.d.map(([d, b]) => [rename38(d), sig(b)]), E: n.E };
    if (name !== n.name) index[name].icrp38 = n.name;
    (byEl[n.el] ||= {})[name] = { r: compactRad(n.rad), bs: compactSpectrum(n.bs) };
  }
  let bytes = write('decay/index.json', { source: 'ICRP Publication 38, from DCAL (ICRP38.NDX, .RAD, .BET)', nuclides: index });
  for (const [el, obj] of Object.entries(byEl)) bytes += write(`decay/${el}.json`, obj);
  console.log(`decay: ${nucs.length} nuclides of ${Object.keys(byEl).length} elements, ${(bytes / 1e6).toFixed(2)} MB`);
}

/* ==========================================================================
   Specific absorbed fractions, masses, absorbed fractions
   ========================================================================== */
const PHANTOMS = [['A00', 'Newborn', 0], ['A01', 'Age 1', 365], ['A05', 'Age 5', 1825], ['A10', 'Age 10', 3650],
  ['A15', 'Age 15', 5475], ['AM', 'Adult male', 7300], ['AF', 'Adult female', 7300]];
const PHOTON_E = [0.01, 0.015, 0.02, 0.03, 0.05, 0.1, 0.2, 0.5, 1.0, 1.5, 2.0, 4.0];

function readSafFile(ext) {
  const rx = /^(.{8})<-(.{8})((?:\s+[-+0-9.Ee]+){12})\s*$/;
  const out = { targets: [], sources: [], saf: {} };
  for (const l of read(DAT, 'saf', `PSAFTX66.${ext}`).split('\n')) {
    const m = rx.exec(l);
    if (!m) continue;
    const t = m[1].trim(), s = m[2].trim();
    const v = m[3].trim().split(/\s+/).map(Number);
    if (!out.targets.includes(t)) out.targets.push(t);
    if (!out.sources.includes(s)) out.sources.push(s);
    out.saf[`${t}<-${s}`] = v.every((x) => x === 0) ? 0 : v;
  }
  return out;
}

function readMasses(ext) {
  const out = { targets: {}, sources: {} };
  let block = null;
  for (const l of read(DAT, 'saf', `REGMASS.${ext}`).split('\n')) {
    if (/^MASS TARGET/.test(l)) { block = 'targets'; continue; }
    if (/^MASS SOURCE/.test(l)) { block = 'sources'; continue; }
    if (/^END/.test(l)) { block = null; continue; }
    if (!block) continue;
    const m = /^(\S+)\s+([-+0-9.Ee]+)/.exec(l);
    if (m) out[block][m[1]] = Number(m[2]);
  }
  return out;
}

function readElAlpha(ext) {
  const out = { electron: {}, alpha: {} };
  let block = null;
  for (const l of read(DAT, 'saf', `ELALPHAF.${ext}`).split('\n')) {
    if (/^ELECTRON AFs/.test(l)) { block = 'electron'; continue; }
    if (/^ALPHA AFs/.test(l)) { block = 'alpha'; continue; }
    if (/^END/.test(l)) { block = null; continue; }
    if (!block) continue;
    const m = /^(\S+)\s*<-(\S+)\s+([-+0-9.Ee]+)/.exec(l);
    if (m) out[block][`${m[1]}<-${m[2]}`] = Number(m[3]);
  }
  return out;
}

/* AF_ELEC.LNG / AF_ALPHA.LNG: ICRP 66 Annex H, a column per source-target
   pair and a row per energy; "Cutoff energy" row below. */
function readLungAF(file) {
  const lines = read(DAT, 'saf', file).split('\n');
  const sources = lines[1].trim().split(/\s+/).slice(1);
  const targets = lines[2].trim().split(/\s+/).slice(1);
  const energies = [], values = sources.map(() => []);
  for (const l of lines.slice(3)) {
    if (/^-{5}/.test(l)) break;
    const t = l.trim().split(/\s+/);
    if (t.length !== sources.length + 1) continue;
    energies.push(Number(t[0]));
    t.slice(1).forEach((v, k) => values[k].push(Number(v)));
  }
  const cut = lines.find((l) => /^Cut ?off/.test(l) || /^Cutoff/.test(l));
  return { energies, pairs: sources.map((s, k) => ({ source: s, target: targets[k], af: values[k] })), note: lines.slice(lines.findIndex((l) => /^-{5}/.test(l)) + 1).join('\n').trim(), cutoffRow: cut || null };
}

function buildSaf() {
  const phantoms = {};
  for (const [ext, label, ageDays] of PHANTOMS) {
    const s = readSafFile(ext);
    phantoms[ext] = { label, ageDays, ...s, masses: readMasses(ext), af: readElAlpha(ext) };
  }
  const bytes = write('saf.json', {
    source: 'Cristy and Eckerman (1987, 1993), ORNL/TM-8381 and ORNL/TM-12351, as distributed with DCAL (PSAFTX66, REGMASS, ELALPHAF, AF_ELEC.LNG, AF_ALPHA.LNG)',
    photonEnergies: PHOTON_E,
    phantoms,
    lungAF: { electron: readLungAF('AF_ELEC.LNG'), alpha: readLungAF('AF_ALPHA.LNG') },
  });
  console.log(`saf: ${Object.keys(phantoms).length} phantoms, ${phantoms.AM.targets.length} targets x ${phantoms.AM.sources.length} sources, ${(bytes / 1e6).toFixed(2)} MB`);
}

/* ==========================================================================
   Biokinetic models
   ========================================================================== */

/* A DEF file: title, "  n : Number of age groups", three lines of text, n
   ages, then "From      ->To        r1 r2 ..." (A10, '->', A10, rates). */
function readDef(file) {
  const lines = read(file).split('\n');
  const nAge = Number(lines[1].split(':')[0].trim().split(/\s+/)[0]);
  const ages = [], ageNames = [];
  for (let i = 0; i < nAge; i++) {
    const m = /^\s*(\d+)\s*(.*)$/.exec(lines[5 + i]);
    ages.push(Number(m[1]));
    ageNames.push(m[2].trim());
  }
  const transfers = [];
  let i = 5 + nAge;
  for (; i < lines.length; i++) {
    const l = lines[i];
    if (/^EOF/.test(l)) break;
    if (!l.includes('->')) continue;
    const from = l.slice(0, 10).trim(), to = l.slice(12, 22).trim();
    const rates = l.slice(22).trim().split(/\s+/).filter(Boolean).map(Number);
    if (rates.length !== nAge) throw new Error(`${file}: ${rates.length} rates for ${nAge} ages in "${l}"`);
    transfers.push([from, to, rates]);
  }
  return { title: lines[0].trim(), text: lines.slice(2, 5).map((s) => s.trim()).filter((s) => s && !/^\*+$/.test(s)), ages, ageNames, transfers, notes: lines.slice(i + 1).join('\n').trim() };
}

/* A GF1 file: title, "n : Number of age groups", three lines, then n lines
   of "f1 age" in free form. */
function readGf1(file) {
  const lines = read(file).split('\n');
  const n = Number(lines[1].split(':')[0].trim().split(/\s+/)[0]);
  const ages = [], f1 = [];
  for (let i = 0; i < n; i++) {
    const t = lines[5 + i].trim().split(/[\s,]+/);
    f1.push(Number(t[0]));
    ages.push(Number(t[1]));
  }
  return { title: lines[0].trim(), text: lines.slice(2, 5).map((s) => s.trim()).filter((s) => s && !/^\*+$/.test(s)), ages, f1 };
}

/* An LNG file (respiratory tract model): title, "n [m] : Number of
   compartments [and compartments with deposition]", two lines, n compartment
   names (a deposition fraction beside the first m for gases and vapours),
   then transfers as in a DEF file but with one rate. */
function readLng(file) {
  const lines = read(file).split('\n');
  const head = lines[1].split(':')[0].trim().split(/\s+/).map(Number);
  const n = head[0];
  const comps = [], deposition = {};
  let i = 4;
  for (let k = 0; k < n; k++, i++) {
    const t = lines[i].trim().split(/\s+/);
    comps.push(t[0]);
    if (t.length > 1) deposition[t[0]] = Number(t[1]);
  }
  const transfers = [];
  for (; i < lines.length; i++) {
    const l = lines[i];
    if (/^EOF/.test(l)) break;
    if (!l.includes('->')) continue;
    transfers.push([l.slice(0, 10).trim(), l.slice(12, 22).trim(), Number(l.slice(22).trim().split(/\s+/)[0])]);
  }
  return { title: lines[0].trim(), text: [lines[2].trim(), lines[3].trim()].filter(Boolean), compartments: comps, deposition, transfers, notes: lines.slice(i + 1).join('\n').trim() };
}

/*
  The systemic models ICRP 72 used for actinium and protactinium. ICRP 72
  took them from ICRP 30 Part 3 (its table of models says so), while DCAL's
  FGR-13 library -- like its ICRP 68 one -- carries updated models based on
  americium (Ac) and thorium (Pa), and FGR 13 says so (ORNL/TM-2001/190,
  3.3.1). These are ICRP 30 Part 3's metabolic data written the way DCAL
  writes its other ICRP 30 models (Ho, Bk, ...): blood clears with a half-time
  of 0.25 d; bone deposits go half to cortical, half to trabecular surfaces
  (every isotope of both elements is a bone-surface seeker there); what is
  excreted goes to urine and faeces equally (ICRP 68).

    Ac  0.45 to bone, 100 y; 0.45 to liver, 40 y; testes 3.5E-4 and ovaries
        1.1E-4 of what leaves blood, retained indefinitely; the rest excreted
    Pa  0.40 to bone, 100 y; 0.15 to liver, 0.7 of it with 10 d and 0.3 with
        60 d; 0.02 to kidneys, 0.2 with 10 d and 0.8 with 60 d; the rest
        excreted
*/
function icrp30Models() {
  const L = Math.LN2 / 0.25;
  const r = (half) => Math.LN2 / half;
  const Y = 365.25;
  const out = (from, rate) => [[from, 'UB_Cont', [rate / 2]], [from, 'ULI_Cont', [rate / 2]]];
  const ac = [
    ['Blood', 'C_Bone-S', [0.225 * L]], ['Blood', 'T_Bone-S', [0.225 * L]], ['Blood', 'Liver', [0.45 * L]],
    ['Blood', 'Testes', [3.5e-4 * L]], ['Blood', 'Ovaries', [1.1e-4 * L]],
    ...out('Blood', (1 - 0.9 - 4.6e-4) * L),
    ...out('C_Bone-S', r(100 * Y)), ...out('T_Bone-S', r(100 * Y)), ...out('Liver', r(40 * Y)),
    ['Testes', 'Excreta', [0]], ['Ovaries', 'Excreta', [0]],
  ];
  const pa = [
    ['Blood', 'C_Bone-S', [0.2 * L]], ['Blood', 'T_Bone-S', [0.2 * L]],
    ['Blood', 'Liver_a', [0.15 * 0.7 * L]], ['Blood', 'Liver_b', [0.15 * 0.3 * L]],
    ['Blood', 'Kidneys_a', [0.02 * 0.2 * L]], ['Blood', 'Kidneys_b', [0.02 * 0.8 * L]],
    ...out('Blood', (1 - 0.4 - 0.15 - 0.02) * L),
    ...out('C_Bone-S', r(100 * Y)), ...out('T_Bone-S', r(100 * Y)),
    ...out('Liver_a', r(10)), ...out('Liver_b', r(60)), ...out('Kidneys_a', r(10)), ...out('Kidneys_b', r(60)),
  ];
  const model = (title, transfers) => ({ title, text: ['ICRP Publication 30 Part 3, as used in ICRP Publication 72'], ages: [100], ageNames: ['All ages'], transfers, notes: '' });
  return { AC_I30: model('Actinium, ICRP 30 Part 3', ac), PA_I30: model('Protactinium, ICRP 30 Part 3', pa) };
}

/* ICRP66.DEP: per reference individual, a fraction deposited in each
   compartment of the ICRP 66 model for 13 AMADs. */
function readDeposition() {
  const lines = read(DAT, 'mis', 'ICRP66.DEP').split('\n');
  // Records are 137 characters, some closed by a "|" in the last column.
  const amad = lines[2].replace(/\|.*$/, '').trim().split(/\s+/).map(Number);
  const groups = [];
  let cur = null;
  for (const l of lines.slice(4)) {
    if (/member of public|worker deposition/i.test(l)) {
      cur = { label: l.replace(/\|.*$/, '').trim(), fractions: {} };
      groups.push(cur);
      continue;
    }
    if (!cur || /^C\/AMAD/.test(l)) continue;
    const t = l.replace(/\|.*$/, '').trim().split(/\s+/);
    if (t.length === amad.length + 1 && /^[A-Za-z]/.test(t[0])) cur.fractions[t[0]] = t.slice(1).map(Number);
  }
  const ageOf = (label) => (/worker/i.test(label) ? 'worker' : Number(/^(\d+)/.exec(label)[1]));
  return { amad, groups: groups.map((g) => ({ age: ageOf(g.label), label: g.label, fractions: g.fractions })) };
}

/* ICRP30.GIT and ICRP67.BLD have the DEF layout. */
function readBlock(file) {
  const d = readDef(file);
  return { title: d.title, ages: d.ages, transfers: d.transfers };
}

/* LUNGAS.DAT: the apportionment of the regional doses into ET and Lung. */
function readLungas() {
  const lines = read(DAT, 'mis', 'LUNGAS.DAT').split('\n');
  const [ageTo, ageCut, period] = lines[1].trim().split(/\s+/).map(Number);
  const weights = [];
  for (const l of lines.slice(2)) {
    if (/^-{3}/.test(l)) break;
    const t = l.trim().split(/\s+/);
    if (t.length >= 2) weights.push([t[0], Number(t[1])]);
  }
  return { ageTo, ageCut, period, weights };
}

/* $BIODEF.DAT / $F1DEF.DAT / $LNGDEF.DAT: assignment blocks. */
function readAssignments(file) {
  const lines = read(file).split('\n');
  const blocks = {};
  let name = null;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const open = /^([A-Z][A-Z ]+?)\s+:<- Delimiter/.exec(l);
    if (open && !/^END/.test(open[1])) { name = open[1].trim(); blocks[name] = []; continue; }
    if (/^END /.test(l)) { name = null; continue; }
    if (name) blocks[name].push(l);
  }
  return blocks;
}

function parseElementBlock(lines, parseLine) {
  const out = {};
  for (let i = 0; i < lines.length; i++) {
    const m = /^([A-Z][a-z]?)\s*(\d+)/.exec(lines[i]);
    if (!m) continue;
    const n = Number(m[2]);
    out[m[1]] = lines.slice(i + 1, i + 1 + n).map(parseLine);
    i += n;
  }
  return out;
}

function buildModels() {
  const bioDir = path.join(DAT, 'bio', 'f13');
  const systemic = {}, f1 = {};
  for (const f of fs.readdirSync(bioDir).sort()) {
    const m = /^(.+)\.(def|gf1)$/i.exec(f);
    if (!m) continue;
    const key = m[1].toUpperCase();
    if (m[2].toLowerCase() === 'def') systemic[key] = readDef(path.join(bioDir, f));
    else f1[key] = readGf1(path.join(bioDir, f));
  }

  const bio = readAssignments(path.join(bioDir, '$BIODEF.DAT'));
  const biodef = {
    nuclide: parseElementBlock(bio['NUCLIDE ASSIGNMENT'] || [], (l) => { const t = l.trim().split(/\s+/); return { nuclide: t[0], route: t[1], file: t[2].toUpperCase() }; }),
    intake: parseElementBlock(bio['INTAKE ASSIGNMENT'] || [], (l) => { const t = l.trim().split(/\s+/); return { file: t[0].toUpperCase(), route: t[1] }; }),
    prompts: parseElementBlock(bio['USER PROMPTS'] || [], (l) => ({ file: l.slice(3, 11).trim().toUpperCase(), route: l.slice(12, 13), text: l.slice(14).trim() })),
  };
  const f1b = readAssignments(path.join(bioDir, '$F1DEF.DAT'));
  const f1def = {
    biokinetic: (f1b['BIOKINETIC ASSIGNMENT'] || []).filter((l) => l.trim()).map((l) => { const t = l.trim().split(/\s+/); return { file: t[0].toUpperCase(), route: t[1], f1: t[2].toUpperCase() }; }),
    prompts: parseElementBlock(f1b['USER PROMPTS'] || [], (l) => ({ f1: l.slice(3, 11).trim().toUpperCase(), route: l.slice(12, 13), text: l.slice(14).trim() })),
  };
  const lngb = readAssignments(path.join(DAT, 'mis', '$LNGDEF.DAT'));
  const lungdef = parseElementBlock(lngb['ELEMENT ASSIGNMENT'] || [], (l) => ({ file: l.slice(3, 11).trim().toUpperCase(), text: l.slice(12).trim() }));

  Object.assign(systemic, icrp30Models());

  const lung = {};
  for (const f of fs.readdirSync(path.join(DAT, 'mis')).sort()) {
    if (!/\.lng$/i.test(f)) continue;
    lung[f.replace(/\.lng$/i, '').toUpperCase()] = readLng(path.join(DAT, 'mis', f));
  }

  const bytes = write('models.json', {
    source: 'DCAL biokinetic library for Federal Guidance Report 13 (folder DAT/BIO/F13), which with the exceptions noted in ORNL/TM-2001/190 section 3.3.1 holds the models of ICRP Publications 56, 67, 69, 71 and 72; DCAL DAT/MIS for the respiratory, gastrointestinal and bladder models',
    systemic, f1, biodef, f1def, lungdef, lung,
    deposition: readDeposition(),
    git: readBlock(path.join(DAT, 'mis', 'ICRP30.GIT')),
    bladder: readBlock(path.join(DAT, 'mis', 'ICRP67.BLD')),
    lungDose: readLungas(),
    intakeAges: read(DAT, 'mis', 'IntakExp.AGE').split('\n').slice(2).map((s) => Number(s.trim())).filter((x) => x > 0),
  });
  console.log(`models: ${Object.keys(systemic).length} systemic models, ${Object.keys(f1).length} f1 files, ${Object.keys(lung).length} respiratory models, ${(bytes / 1e3).toFixed(0)} kB`);
  return { systemic, f1, lung };
}

/* ==========================================================================
   The cases of DCAL's FGR-13 batch files
   "******* nn S ffffffff ffffffff aaaa  t 1.0E-02  ffffffff"
   nuclide, last chain member, (S)hared or (I)ndependent kinetics, special
   biokinetic file, special f1 file, adult age, absorption type, AMAD, lung
   file.
   ========================================================================== */
function readCases(file) {
  const lines = read(appDir, 'wrk', 'fgr13', file).split('\n');
  const start = lines.findIndex((l) => /^CASE INPUT DATA/.test(l));
  // FGR13ING.INP has a stray END CASE DATA after the cobalt cases, left from
  // running a subset; every case up to the last one is wanted.
  let end = lines.length;
  while (end > start && !/^END CASE/.test(lines[end - 1])) end--;
  const out = [];
  for (const l of lines.slice(start + 1, end - 1)) {
    if (/^END CASE/.test(l) || !l.trim()) continue;
    const f = (a, b) => l.slice(a, b).trim();
    out.push({
      nuclide: RENAME_38[f(0, 7).replace(/([0-9])([A-Z]+)$/, (m, d, x) => d + x.toLowerCase())]
        || f(0, 7).replace(/([0-9])([A-Z]+)$/, (m, d, x) => d + x.toLowerCase()),
      last: Number(f(8, 10)) || null,
      kinetics: f(11, 12) || 'S',
      bio: f(13, 21).toUpperCase() || null,
      f1: f(22, 30).toUpperCase() || null,
      adultAge: Number(f(31, 35)) || null,
      type: f(37, 38) || null,
      amad: Number(f(39, 46)) || null,
      lung: f(48, 56).toUpperCase() || null,
      note: f(56, 100).replace(/^''$/, '') || null,
    });
  }
  return out;
}

/* Two Pu-238 lines at the head of FGR13ING.INP, after Be-10, are no cases of
   FGR 13. One names Pu_2.GF1, the ICRP 68 f1 of 1E-4 for workers' intakes of
   plutonium nitrates, which is in DCAL's library for workers (DAT/BIO/I68)
   and not in the FGR-13 library the batch ran with (ini/DCALMENU.INI); the
   other repeats the Pu-238 case among the actinides. FGR 13 (Table 2.2a) and
   ICRP 72 give ingested Pu-238 once, with f1 5E-4. So a case naming a file
   the library does not have is left out, and so is a case run again later. */
function keepCases(file, cases, library) {
  const same = (c) => [c.nuclide, c.last, c.kinetics, c.bio, c.f1, c.adultAge, c.type, c.amad, c.lung].join('|');
  const last = new Map(cases.map((c, i) => [same(c), i]));
  return cases.filter((c, i) => {
    const missing = [[c.bio, library.systemic, 'DEF'], [c.f1, library.f1, 'GF1'], [c.lung, library.lung, 'LNG']]
      .filter(([name, files]) => name && !files[name]).map(([name, , ext]) => `${name}.${ext}`);
    const why = missing.length ? `no ${missing.join(', ')} in the library` : last.get(same(c)) !== i ? 'run again later' : null;
    if (why) console.log(`${file}: ${c.nuclide} left out, ${why}`);
    return !why;
  });
}

function buildCases(library) {
  const ingestion = keepCases('FGR13ING.INP', readCases('FGR13ING.INP'), library);
  const inhalation = keepCases('FGR13INH.INP', readCases('FGR13INH.INP'), library);
  const bytes = write('cases.json', { source: 'DCAL batch input files of Federal Guidance Report 13 (wrk/fgr13/FGR13ING.INP, FGR13INH.INP)', ingestion, inhalation });
  console.log(`cases: ${ingestion.length} ingestion, ${inhalation.length} inhalation, ${(bytes / 1e3).toFixed(0)} kB`);
}

buildDecay();
buildSaf();
buildCases(buildModels());
