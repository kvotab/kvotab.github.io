#!/usr/bin/env node
/*
  Build the ICRP 103 system's data for dose_coefficients.html.

      node scripts/gen-dose-icrp103.mjs <ICRP-07 data folder> <ICRP 155 SAF folder> [model folder] [--models-only]

  The first folder holds the ICRP Publication 107 data files of the ICRP's
  supplementary data (p107jaicrp_38_3_nuclear_decay_data_suppl_data.zip,
  https://www.icrp.org/publication.asp?id=ICRP%20Publication%20107):
  ICRP-07.RAD, ICRP-07.BET and LICENSE.TXT, with ICRP-07.NDX and
  License_DECDATA.TXT from the corrigenda of Publication 107 (2021; the
  corrected index differs only in the atomic masses, which are not read).
  ORNL's Radiological Toolbox installs the same RAD and BET files. The second is the
  unpacked supplement of ICRP Publication 155 (paed_saf.zip from icrp.org):
  folders alpha/, electron/, photon/ and neutron/ with one file per reference
  individual (newborn, 1, 5, 10 and 15 y and adult, male and female), and the
  index files Sregions_Male.NDX, Sregions_Female.NDX, Torgans_Male.NDX and
  Torgans_Female.NDX. Its adult files supersede those of Publication 133 for
  electrons and alphas. The third, optional, is the folder of the transcribed
  biokinetic models: elements/<El>.json, one per element, progeny.json (the
  OIR sections' models of progeny, see resources/js/dose/progeny103.js) and
  deposition.json (see buildModels below).

  Writes resources/data/dose/icrp103/:

      decay/index.json   every ICRP 107 nuclide: half-life, decay mode,
                         daughters and branching, emitted energy by kind
      decay/<El>.json    the radiations of each element's nuclides
      decay/LICENSE.TXT, decay/LICENSE_DECDATA.TXT
                         the ICRP-07 copyright notices (2008, and the
                         corrigenda's of 2021), which must accompany every
                         copy of the data
      saf/index.json     targets, source regions (and which may form "Other"),
                         energy grids, masses, and where each phantom's
                         numbers are in its binary file
      saf/<id>.bin       specific absorbed fractions of one reference
                         individual: photons and electrons from the first
                         non-zero energy of each target-source pair on, the
                         pairs with a non-zero alpha SAF, little-endian
                         float32
      saf/<id>-n.bin     its neutron SAFs for the 28 spontaneously fissioning
                         nuclides, read only when a chain has one
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { icrp107Nuclides, compactRad, compactSpectrum, sig, fileIn } from './lib/dose-decay.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'resources/data/dose/icrp103');

const [icrp07Dir, safDir, modelDir] = process.argv.slice(2).filter((a) => !a.startsWith('--'));
if (!icrp07Dir || !safDir) {
  console.error('usage: node scripts/gen-dose-icrp103.mjs <ICRP-07 data folder> <ICRP 155 SAF folder> [model folder]');
  process.exit(2);
}
const read = (...p) => fs.readFileSync(path.join(...p), 'latin1').replace(/\r/g, '');
const writeFile = (rel, data) => {
  const file = path.join(OUT, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
  return fs.statSync(file).size;
};
const write = (rel, obj) => writeFile(rel, JSON.stringify(obj));

/* ==========================================================================
   Decay data, ICRP Publication 107
   ========================================================================== */
function buildDecay() {
  const nucs = icrp107Nuclides(icrp07Dir);
  const index = {};
  const byEl = {};
  let mismatch = 0;
  for (const n of nucs) {
    index[n.name] = { t: n.t, T: sig(n.T, 8), m: n.mode, d: n.d.map(([d, b]) => [d, sig(b)]), E: n.E };
    (byEl[n.el] ||= {})[n.name] = { r: compactRad(n.rad), bs: compactSpectrum(n.bs) };
    // The index's energies per decay against the lines: alpha (with the
    // recoil, without fission fragments), electrons (beta, conversion,
    // Auger), photons. The index has four or five decimals.
    const sum = (k) => (n.rad[k] || []).reduce((a, [e, y]) => a + e * y, 0);
    const got = [sum('a') + sum('ar'), sum('b') + sum('e'), sum('p')];
    const ok = got.every((g, i) => Math.abs(g - n.E[i]) <= 2e-3 * n.E[i] + 1e-4);
    if (!ok) { mismatch++; if (mismatch <= 5) console.warn(`  ${n.name}: index E ${n.E} lines ${got.map((g) => g.toPrecision(5))}`); }
  }
  let bytes = write('decay/index.json', {
    source: 'ICRP Publication 107 (Endo and Eckerman), the ICRP\'s supplementary data files ICRP-07.RAD and ICRP-07.BET, with ICRP-07.NDX of the corrigenda of Publication 107 (2021); see LICENSE.TXT and LICENSE_DECDATA.TXT',
    nuclides: index,
  });
  for (const [el, obj] of Object.entries(byEl)) bytes += write(`decay/${el}.json`, obj);
  // Each notice asks that its own file go with every copy of the data.
  bytes += writeFile('decay/LICENSE.TXT', read(fileIn(icrp07Dir, 'LICENSE.TXT')));
  bytes += writeFile('decay/LICENSE_DECDATA.TXT', read(fileIn(icrp07Dir, 'License_DECDATA.TXT')));
  console.log(`decay: ${nucs.length} nuclides of ${Object.keys(byEl).length} elements, ${(bytes / 1e6).toFixed(2)} MB; ${mismatch} with index energies that the lines do not add up to`);
}

/* ==========================================================================
   Specific absorbed fractions, ICRP Publications 133 and 155
   ========================================================================== */
const PHANTOMS = [
  ['00M', 'M', 0], ['00F', 'F', 0], ['01M', 'M', 365], ['01F', 'F', 365], ['05M', 'M', 1825], ['05F', 'F', 1825],
  ['10M', 'M', 3650], ['10F', 'F', 3650], ['15M', 'M', 5475], ['15F', 'F', 5475], ['AM', 'M', 7300], ['AF', 'F', 7300],
];
const fileId = (id) => (id.startsWith('A') ? id.toLowerCase() : id);

/* A SAF file: five head records (the fourth with the energies or, for
   neutrons, the nuclides and their spectrum-weighted wR), then one record per
   target-source pair, source by source: target A10, '<-', source A10, then
   E10.0 fields. */
function readSafFile(type, id) {
  const lines = read(safDir, type, `rcp-${fileId(id)}_${type}.SAF`).split('\n');
  const n = type === 'alpha' ? 24 : 28;
  const head = lines[3];
  const fields = (l, k) => l.slice(22 + 10 * k, 32 + 10 * k);
  let energies = null, nuclides = null, wR = null;
  if (type === 'neutron') {
    nuclides = lines[2].slice(22).trim().split(/\s+/);
    wR = head.slice(head.indexOf('=') + 1).trim().split(/\s+/).map(Number);
  } else {
    energies = [];
    for (let k = 0; k < n; k++) energies.push(Number(fields(head, k)));
  }
  const pairs = [], values = [];
  for (const l of lines.slice(5)) {
    if (l.slice(10, 12) !== '<-') continue;
    pairs.push([l.slice(0, 10).trim(), l.slice(12, 22).trim()]);
    const v = new Float64Array(n);
    for (let k = 0; k < n; k++) {
      const x = Number(fields(l, k));
      if (!Number.isFinite(x)) throw new Error(`${type} ${id}: "${fields(l, k)}" in "${l.slice(0, 22)}"`);
      v[k] = x;
    }
    values.push(v);
  }
  return { energies, nuclides, wR, pairs, values };
}

/* Sregions_<Sex>.NDX: name, ID (1 = may be part of Other), masses (kg) at the
   six ages. Torgans_<Sex>.NDX: name and masses. */
function readMassFile(file, withId) {
  const out = [];
  for (const l of read(safDir, file).split('\n').slice(3)) {
    if (!l.trim() || /^-{5}/.test(l)) continue;
    const t = l.trim().split(/\s+/);
    const name = t.shift();
    const id = withId ? Number(t.shift()) : null;
    if (t.length !== 6) throw new Error(`${file}: "${l}"`);
    out.push({ name, id, m: t.map(Number) });
  }
  return out;
}

/* Pack a list of typed arrays into one buffer, each at a 4-byte boundary,
   and say where each one is. */
function pack(parts) {
  let off = 0;
  const layout = {};
  const placed = [];
  for (const [name, arr] of parts) {
    off = (off + 3) & ~3;
    layout[name] = { type: arr.constructor.name.replace('Array', ''), offset: off, length: arr.length };
    placed.push([off, arr]);
    off += arr.byteLength;
  }
  const buf = Buffer.alloc(off);
  for (const [o, arr] of placed) Buffer.from(arr.buffer, arr.byteOffset, arr.byteLength).copy(buf, o);
  return { buf, layout };
}

function buildSaf() {
  const ref = readSafFile('photon', 'AM');
  const targets = [...new Set(ref.pairs.map(([t]) => t))];
  const sources = [...new Set(ref.pairs.map(([, s]) => s))];
  const nT = targets.length, nS = sources.length, nR = nT * nS;
  ref.pairs.forEach(([t, s], r) => {
    if (r !== sources.indexOf(s) * nT + targets.indexOf(t)) throw new Error(`pair ${t}<-${s} out of order`);
  });
  const sameOrder = (f, what) => {
    if (f.pairs.length !== nR || f.pairs.some(([t, s], r) => t !== ref.pairs[r][0] || s !== ref.pairs[r][1])) throw new Error(`${what}: pairs differ from the adult male photon file`);
  };
  const masses = {
    M: { sources: readMassFile('Sregions_Male.NDX', true), targets: readMassFile('Torgans_Male.NDX', false) },
    F: { sources: readMassFile('Sregions_Female.NDX', true), targets: readMassFile('Torgans_Female.NDX', false) },
  };
  for (const sex of ['M', 'F']) {
    if (masses[sex].sources.map((x) => x.name).join() !== sources.join()) throw new Error(`Sregions ${sex}: names differ from the SAF files`);
    if (masses[sex].targets.map((x) => x.name).join() !== targets.join()) throw new Error(`Torgans ${sex}: names differ from the SAF files`);
  }
  const ages = [0, 365, 1825, 3650, 5475, 7300];
  const phantoms = [];
  let energies = null, neutron = null, bytes = 0;
  for (const [id, sex, age] of PHANTOMS) {
    const ph = readSafFile('photon', id), el = readSafFile('electron', id), al = readSafFile('alpha', id), ne = readSafFile('neutron', id);
    for (const [f, w] of [[ph, 'photon'], [el, 'electron'], [al, 'alpha'], [ne, 'neutron']]) sameOrder(f, `${w} ${id}`);
    energies ||= { photon: ph.energies, electron: el.energies, alpha: al.energies };
    if (ph.energies.join() !== energies.photon.join() || el.energies.join() !== energies.electron.join() || al.energies.join() !== energies.alpha.join()) throw new Error(`${id}: energy grid differs`);
    neutron ||= { nuclides: ne.nuclides, wR: ne.wR };
    if (ne.nuclides.join() !== neutron.nuclides.join() || ne.wR.join() !== neutron.wR.join()) throw new Error(`${id}: neutron nuclides or wR differ`);
    // Photons and electrons: every zero is a leading one (Ecut), so a row is
    // kept from its first non-zero energy.
    const dense = (f) => {
      const n = f.values[0].length;
      const start = new Uint8Array(nR);
      const vals = [];
      f.values.forEach((v, r) => {
        let k = 0;
        while (k < n && v[k] === 0) k++;
        for (let j = k; j < n; j++) if (v[j] === 0) throw new Error(`${id}: a zero after the first non-zero SAF in row ${r}`);
        start[r] = k;
        for (let j = k; j < n; j++) vals.push(v[j]);
      });
      return { start, vals: Float32Array.from(vals) };
    };
    const P = dense(ph), E = dense(el);
    const aRows = [], aVals = [];
    al.values.forEach((v, r) => { if (v.some((x) => x !== 0)) { aRows.push(r); aVals.push(...v); } });
    const { buf, layout } = pack([
      ['photonStart', P.start], ['electronStart', E.start], ['alphaRows', Uint16Array.from(aRows)],
      ['photon', P.vals], ['electron', E.vals], ['alpha', Float32Array.from(aVals)],
    ]);
    bytes += writeFile(`saf/${id}.bin`, buf);
    const nbuf = new Float32Array(neutron.nuclides.length * nR);
    ne.values.forEach((v, r) => { for (let k = 0; k < v.length; k++) nbuf[k * nR + r] = v[k]; });
    bytes += writeFile(`saf/${id}-n.bin`, Buffer.from(nbuf.buffer));
    const k = ages.indexOf(age);
    phantoms.push({
      id, sex, age, file: `${id}.bin`, neutronFile: `${id}-n.bin`, layout,
      masses: { sources: masses[sex].sources.map((x) => x.m[k]), targets: masses[sex].targets.map((x) => x.m[k]) },
    });
  }
  bytes += write('saf/index.json', {
    source: 'ICRP Publication 155 (supplement paed_saf.zip), whose adult files revise those of ICRP Publication 133; SAFs in kg-1, energies in MeV, masses in kg',
    targets, sources,
    other: { M: masses.M.sources.map((x) => x.id === 1), F: masses.F.sources.map((x) => x.id === 1) },
    energies, neutron, phantoms,
    order: 'row = source index * targets.length + target index',
  });
  console.log(`saf: ${phantoms.length} phantoms, ${nT} targets x ${nS} sources, ${(bytes / 1e6).toFixed(2)} MB`);
}

/* ==========================================================================
   Biokinetic models: the transcribed element files and the deposition table
   ========================================================================== */
/* The model folder holds elements/<El>.json (format in
   resources/js/dose/README.md) and deposition.json (ICRP 158 Table A.1).
   The element files also carry the ICRP's own dose coefficients, which the
   tests compare with; those are the ICRP's results, not inputs, and stay out
   of the page's data. */
function buildModels() {
  if (!modelDir) return;
  const elements = {};
  const dir = path.join(modelDir, 'elements');
  for (const f of fs.readdirSync(dir).sort()) {
    if (!/^[A-Z][a-z]?\.json$/.test(f)) continue;
    const el = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    // The ICRP's own results stay out (tests read them from local copies),
    // and so do the transcriber's notes, which were written for this
    // program's author and quote the publications.
    for (const k of ['doses', 'radonExposure', 'notes', 'uncertain', 'progeny']) delete el[k];
    elements[f.replace(/\.json$/, '')] = el;
  }
  let bytes = write('elements.json', elements);
  // Progeny models of the OIR sections (resources/js/dose/progeny103.js); the
  // transcriber's notes and references stay out like the elements'.
  const strip = (x) => (Array.isArray(x) ? x.map(strip) : x && typeof x === 'object'
    ? Object.fromEntries(Object.entries(x).filter(([k]) => !k.startsWith('//') && k !== 'notes' && k !== 'ref').map(([k, v]) => [k, strip(v)])) : x);
  bytes += write('progeny.json', strip(JSON.parse(fs.readFileSync(path.join(modelDir, 'progeny.json'), 'utf8'))));
  const deposition = JSON.parse(fs.readFileSync(path.join(modelDir, 'deposition.json'), 'utf8'));
  bytes += write('hrtm.json', { deposition });
  // Radon and thoron progeny in homes (resources/js/dose/radon.js): the inputs
  // of Publication 158 Section 32 and Annex C, from the radonExposure block of
  // the radon file; its tables of results stay out like the elements' doses.
  const rx = JSON.parse(fs.readFileSync(path.join(dir, 'Rn.json'), 'utf8')).radonExposure;
  const EL = { Polonium: 'Po', Lead: 'Pb', Bismuth: 'Bi' };
  const KIND = (n) => (/thoron/i.test(n) ? 'thoron' : 'radon');
  bytes += write('radon.json', {
    source: 'ICRP Publication 158, Section 32 (Tables 32.1, 32.2, 32.3) and Annex C (Table C.1, lung-air volume of Table C.3)',
    absorption: Object.fromEntries(rx.progenyAbsorption.rows.map((r) => [EL[r.progeny], { fr: r.fr, sr: r.sr, ss: r.ss, fb: r.fb, sb: r.sb, fA: r.fA }])),
    aerosol: Object.fromEntries(rx.aerosol.rows.map((r) => [KIND(r.nuclides), { fp: r.fp, F: r.F, modes: r.modes.map((m) => ({ mode: m.mode, fpi: m.fpi, AMTD: m.AMTD_nm, sigma: m.sigma_g, hgf: m.hgf })) }])),
    breathing: rx.breathingAtHome.meanBreathingRate_m3_per_h,
    deposition: rx.annexC.depositionOfProgeny.byAge.map((a) => Object.fromEntries(a.rows.map((r) => [r.AMTD_nm, { ET1: r.ET1, ET2: r.ET2, BB: r.BB, bb: r.bb, AI: r.AI, total: r.Total }]))),
    lungAir: { columns: rx.annexC.lungAirVolume.columns, litres: rx.annexC.lungAirVolume.values },
    recommended: { radon: rx.recommended.radon_mSv_per_mJ_h_m3, thoron: rx.recommended.thoron_mSv_per_mJ_h_m3 },
  });
  console.log(`models: ${Object.keys(elements).length} elements, ${(bytes / 1e3).toFixed(0)} kB`);
}

// --models-only rebuilds elements.json, progeny.json, hrtm.json and radon.json alone.
if (!process.argv.includes('--models-only')) {
  buildDecay();
  buildSaf();
}
buildModels();
