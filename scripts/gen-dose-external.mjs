#!/usr/bin/env node
/*
  Build the monoenergetic data of external exposure for dose_coefficients.html.

      node scripts/gen-dose-external.mjs <DCAL app folder> <FGR 15 data folder>

  The page calculates the dose rate coefficients of every nuclide itself, from
  its decay data (resources/js/dose/external.js), the way Federal Guidance
  Reports 12 and 15 calculated theirs: the radiations' yields times the dose
  rate per photon or electron emitted at each energy. Those monoenergetic
  coefficients are what this script writes, as the reports' authors give them:

    FGR 12 (EPA-402-R-93-081, Eckerman and Ryman 1993), for the ICRP 60
      system: the organ dose rates of the adult hermaphrodite phantom for
      photons of 12 energies (10 keV to 5 MeV), in air (Table II.4), water
      (II.5), on the ground surface (II.6) and in soil 1, 5, 15 cm deep and
      infinitely deep (II.12-II.15), from DCAL's DAT/EXT folder, where ORNL
      distributes them with DCAL (unpack DCAL01_setup.exe with innoextract).
    FGR 15 (EPA-402-R-19-002, revision of July 2025), for the ICRP 103
      system: the equivalent dose rates of the 29 tissues of the newborn, 1,
      5, 10 and 15 year old and reference adult phantoms for photons of 13
      energies, in air, water, on the ground surface (3 mm deep, for ground
      roughness) and in soil to 1, 5, 15 cm and infinite depth: the
      Mono_Coefficients folder of fgr15_data_2025_05_28.zip from EPA's
      FGR 15 page, unzipped.

  Both reports take the electrons' dose to the skin and the bremsstrahlung
  they make from FGR 12's data, which go into both files:

    skin    FGR 12 Figs. II.24-II.26 (DOSFACTER, 70 um deep): the dose rate
            to skin per electron emitted at each energy, in water, air, soil
            and on the ground surface (FIGII24.DAT ... FIGII26B.DAT). They
            are written in mrem per year per uCi per m3 (per m2 on the
            ground surface; the air file's title says mCi, but its values are
            per uCi, as FGR 12's and FGR 15's skin doses show) and are
            converted here to Sv per s per Bq per m3 (m2), a year being
            365.25 days.
    brems   FGR 12 Tables C.1-C.3 (= FGR 15 Tables C-1-C-3): the scaled
            bremsstrahlung spectra 100 k/T S(k, T) of electrons of energy T
            (keV) slowing down in air, water and soil, at k/T from 0 to 0.95
            (BREMAIR.DAT, BREMWAT.DAT, BREMSOIL.DAT).

  Writes resources/data/dose/external/fgr12.json and fgr15.json:

      energies  photon energies, MeV
      tissues   the report's tissue names, in its order
      ages      the phantoms' ages: 'adult' (FGR 12), or 'newborn', '1',
                '5', '10', '15', 'adult' (FGR 15, whose adult is its
                reference adult: the adult phantom for the male, the 15
                year old's for the female)
      photon    for each geometry, for each age, for each tissue the dose
                rate per photon emitted at each energy: Sv s-1 per Bq m-3
                (per Bq m-2 on the ground surface), the report's own
                figures (FGR 12's four, FGR 15's three); zero where the
                report gives zero
      skin, brems   as above

  These are the reports' data, US Government works (EPA, ORNL).
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'resources/data/dose/external');

const [appDir, fgr15Dir] = process.argv.slice(2);
if (!appDir || !fgr15Dir) {
  console.error('usage: node scripts/gen-dose-external.mjs <DCAL app folder> <FGR 15 data folder>');
  process.exit(2);
}
const EXT = path.join(appDir, 'DAT', 'EXT');
const MONO = fs.existsSync(path.join(fgr15Dir, 'Mono_Coefficients')) ? path.join(fgr15Dir, 'Mono_Coefficients') : fgr15Dir;
const lines = (file) => fs.readFileSync(file, 'latin1').replace(/\r\n?/g, '\n').split('\n');
const sig = (x, n) => (x === 0 ? 0 : Number(x.toPrecision(n)));

/* ---- FGR 12 ----------------------------------------------------------------- */
/* A table of DCAL's EXT folder: the organs' rows over the photon energies. */
function table12(name) {
  const L = lines(path.join(EXT, `${name}.DAT`));
  const hi = L.findIndex((l) => /^\s*Organ\/Tissue/.test(l));
  const energies = L[hi].trim().split(/\s+/).slice(1).map(Number);
  const rows = new Map();
  for (const l of L.slice(hi + 2)) {
    const m = /^\s(\S.{15})\s*(\S.*)$/.exec(l);
    if (!m) continue;
    const v = m[2].trim().split(/\s+/);
    if (v.length !== energies.length) continue;
    // Table II.5 writes the skin as "Skine".
    rows.set(m[1].trim() === 'Skine' ? 'Skin' : m[1].trim(), v.map(Number));
  }
  return { energies, rows };
}
// The 25 organs FGR 12 gives for nuclides (its DFFUL files' columns); the
// tables' other rows (whole body, skeleton, H_E, E, kerma) are not needed.
const ORGANS_12 = ['R_Marrow', 'Adrenals', 'Bone_Sur', 'Brain', 'Breasts', 'GB_Wall', 'Esophagus', 'St_Wall', 'SI_Wall', 'ULI_Wall', 'LLI_Wall',
  'Ht_Wall', 'Kidneys', 'Liver', 'Lng_Tiss', 'Ovaries', 'Pancreas', 'Skin', 'Spleen', 'Testes', 'Thymus', 'Thyroid', 'UB_Wall', 'Uterus', 'Muscle'];
// Geometry: the table, and the factor to Gy s-1 per Bq m-3 (m-2): Table II.6
// is per photon cm-2, Tables II.12-II.15 per Bq cm-3.
const GEOMETRIES_12 = { air: ['TABLEII4', 1], water: ['TABLEII5', 1], surface: ['TABLEII6', 1e-4],
  soil1: ['TABLII12', 1e-6], soil5: ['TABLII13', 1e-6], soil15: ['TABLII14', 1e-6], soilInf: ['TABLII15', 1e-6] };

function fgr12() {
  let energies = null;
  const photon = {};
  for (const [geo, [name, f]] of Object.entries(GEOMETRIES_12)) {
    const t = table12(name);
    if (energies && t.energies.join() !== energies.join()) throw new Error(`${name}: other energies`);
    energies = t.energies;
    photon[geo] = { adult: ORGANS_12.map((o) => {
      if (!t.rows.has(o)) throw new Error(`${name}: no row ${o}`);
      return t.rows.get(o).map((v) => sig(v * f, 4));
    }) };
  }
  return { energies, tissues: ORGANS_12, ages: ['adult'], photon };
}

/* ---- FGR 15 ----------------------------------------------------------------- */
/* A monoenergetic file of FGR 15: the tissues' rows over the energies. */
function table15(file) {
  const L = lines(file);
  const hi = L.findIndex((l) => /^Tissue\s/.test(l));
  const energies = L[hi].trim().split(/\s+/).slice(1).map(Number);
  const rows = new Map();
  for (const l of L.slice(hi + 1)) {
    const t = l.trim().split(/\s+/);
    if (t.length === energies.length + 1 && /^[A-Za-z]/.test(t[0])) rows.set(t[0], t.slice(1).map(Number));
  }
  return { energies, rows };
}
// The ages in order (an object would put the numeric ones first), with the
// files' names for them: the surface, air and water files', the soil files'.
const AGES_15 = [['newborn', ['newborn', 'Newborn']], ['1', ['01yr', '01yr']], ['5', ['05yr', '05yr']], ['10', ['10yr', '10yr']],
  ['15', ['15yr', '15yr']], ['adult', ['RefAdult', 'RefAdult']]];
const FILES_15 = {
  air: (a) => `Submersion/${a[0]}_Air.DAT`, water: (a) => `Immersion/${a[0]}_Water.DAT`, surface: (a) => `GRD_Surface/${a[0]}_3mm.DAT`,
  soil1: (a) => `GRD_Volume/${a[1]}_01.DAT`, soil5: (a) => `GRD_Volume/${a[1]}_05.DAT`, soil15: (a) => `GRD_Volume/${a[1]}_15.DAT`, soilInf: (a) => `GRD_Volume/${a[1]}_00.DAT`,
};
function fgr15() {
  let energies = null, tissues = null;
  const photon = {};
  for (const [geo, file] of Object.entries(FILES_15)) {
    photon[geo] = {};
    for (const [age, names] of AGES_15) {
      const t = table15(path.join(MONO, file(names)));
      if (energies && t.energies.join() !== energies.join()) throw new Error(`${file(names)}: other energies`);
      if (tissues && [...t.rows.keys()].join() !== tissues.join()) throw new Error(`${file(names)}: other tissues`);
      energies = t.energies;
      tissues = [...t.rows.keys()];
      photon[geo][age] = tissues.map((k) => t.rows.get(k).map((v) => sig(v, 3)));
    }
  }
  return { energies, tissues, ages: AGES_15.map(([a]) => a), photon };
}

/* ---- electrons: skin and bremsstrahlung (FGR 12, used by both) -------------- */
const YEAR = 365.25 * 86400;
const PER_UCI = 1e-5 / YEAR / 3.7e4; // mrem per year per uCi -> Sv per s per Bq
function curve(name) {
  const L = lines(path.join(EXT, `${name}.DAT`)).filter((l) => l.trim());
  const n = Number(L[1]);
  const pts = L.slice(2, 2 + n).map((l) => l.trim().split(/\s+/).map(Number));
  if (pts.length !== n || pts.some((p) => p.length !== 2 || !p.every(Number.isFinite))) throw new Error(`${name}: unreadable`);
  return { E: pts.map((p) => p[0]), h: pts.map((p) => sig(p[1] * PER_UCI, 5)) };
}
function brems(name) {
  const L = lines(path.join(EXT, `${name}.DAT`));
  const kt = L.find((l) => /^\s*K\/T/.test(l)).trim().split(/\s+/).slice(1).map(Number);
  const T = [], S = [];
  for (const l of L) {
    const t = l.trim().split(/\s+/);
    if (t.length === kt.length + 1 && /^\d/.test(t[0])) { T.push(Number(t[0])); S.push(t.slice(1).map(Number)); }
  }
  if (T.length !== 27) throw new Error(`${name}: ${T.length} electron energies`);
  return { T, kt, S };
}
const electrons = () => ({
  skin: { water: curve('FIGII24'), air: curve('FIGII25'), soil: curve('FIGII26A'), surface: curve('FIGII26B') },
  brems: { air: brems('BREMAIR'), water: brems('BREMWAT'), soil: brems('BREMSOIL') },
});

/* ---- write ------------------------------------------------------------------ */
fs.mkdirSync(OUT, { recursive: true });
const write = (name, obj) => {
  const file = path.join(OUT, name);
  fs.writeFileSync(file, `${JSON.stringify(obj)}\n`);
  console.log(`${path.relative(ROOT, file)}: ${(fs.statSync(file).size / 1024).toFixed(0)} KB`);
};
const e = electrons();
write('fgr12.json', {
  source: 'Federal Guidance Report No. 12 (EPA-402-R-93-081, 1993), Tables II.4-II.6 and II.12-II.15, Figs. II.24-II.26 and Tables C.1-C.3, as distributed with DCAL (ORNL)',
  ...fgr12(), ...e,
});
write('fgr15.json', {
  source: 'Federal Guidance Report No. 15 (EPA-402-R-19-002, revised July 2025), monoenergetic dose rate coefficients of fgr15_data_2025_05_28.zip; electrons from Federal Guidance Report No. 12',
  ...fgr15(), ...e,
});
