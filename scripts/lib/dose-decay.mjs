/*
  Readers for the nuclear decay data files of the ORNL Dosimetry Research
  Group, in the two generations dose_coefficients.html uses:

    ICRP38.NDX / .RAD / .BET   ICRP Publication 38, as distributed with DCAL
                               (ORNL/TM-2001/190, Appendix D). The data the
                               ICRP 56-72 dose coefficients were computed with.
    ICRP-07.NDX / .RAD / .BET  ICRP Publication 107 (Endo and Eckerman), the
                               data of the ICRP 103 system.

  Both are fixed-column files. The index (NDX) holds one record per nuclide:
  half-life, decay modes, up to three (ICRP 38) or four (ICRP 107) daughters
  with branching fractions, and pointers into the radiation file (RAD) and the
  beta-spectrum file (BET).

  What is returned is one plain object per nuclide:

      { name, el, A, meta, t: '29.12y', T: <half-life in days>, mode,
        d: [[daughter, branch], ...],      // 'SF' is not a daughter
        E: [alpha, electron, photon],      // MeV per decay, from the index
        rad: { p, b, e, a, ar, ff, n },    // [E, Y] lines, Y per decay
        bs: [[E...], [N...]] | null }      // beta spectrum, N per MeV per decay

  p photons (gamma, X, annihilation; prompt and delayed fission gammas),
  b beta lines with their mean energies (beta minus, beta plus, delayed
  betas), e discrete electrons (internal conversion and Auger), a alphas,
  ar alpha recoils (ICRP 107 lists them; for ICRP 38 the dosimetry computes
  them), ff fission fragments and n fission neutrons (ICRP 107), sf the
  ICRP 38 spontaneous-fission record [yield, energy] as given.
*/
import fs from 'node:fs';

const DAY = { us: 1 / 86400e6, ms: 1 / 86400e3, s: 1 / 86400, m: 1 / 1440, h: 1 / 24, d: 1, y: 365.25 };

/** A FORTRAN E-format field that may have a blank instead of '+' in the exponent ("1.0000E 00"). */
function num(s) {
  const t = s.trim().replace(/E\s+/i, 'E+').replace(/([0-9.])([-+]\d+)$/, '$1E$2');
  if (!t) return 0;
  const v = Number(t);
  if (!Number.isFinite(v)) throw new Error(`not a number: "${s}"`);
  return v;
}

/** "29.12" + "y" -> days; ICRP 38 writes 2.2m, 24065y, 1.405E10y. */
export function halfLifeDays(value, unit) {
  const u = unit.trim();
  if (!(u in DAY)) throw new Error(`unknown half-life unit "${unit}"`);
  return num(value) * DAY[u];
}

/** Element symbol, mass number and isomer tag from 'Am-242m', 'Eu-150a', 'Sb-124n'. */
export function splitName(name) {
  const m = /^([A-Z][a-z]?)-(\d+)([a-z]*)$/.exec(name);
  if (!m) throw new Error(`not a nuclide name: "${name}"`);
  return { el: m[1], A: Number(m[2]), meta: m[3] };
}

function readLines(file) {
  return fs.readFileSync(file, 'latin1').replace(/\r/g, '').split('\n');
}

/* --------------------------------------------------------------------------
   ICRP 38 (DCAL)
   FORMAT(a7,a8,a2,a8,i7,i5,i6,i4,3(i4,e11.0),f7.0,2f8.0,3i4,i5,i4,i3,e11.0,a10)
   Daughters are record numbers of the index itself; 9999 is fission.
   -------------------------------------------------------------------------- */
function readIndex38(file) {
  const lines = readLines(file);
  // The head record gives the first and last data records; a DOS end-of-file
  // mark (^Z) follows them.
  const [first, last] = lines[0].trim().split(/\s+/).map(Number);
  const recs = [];
  for (let r = first - 1; r < last; r++) {
    const l = lines[r];
    const f = (a, b) => l.slice(a, b);
    const rec = {
      record: r + 1,
      name: f(0, 7).trim(), half: f(7, 15), unit: f(15, 17), mode: f(17, 25).trim(),
      irad: Number(f(25, 32)), nrad: Number(f(32, 37)), ibet: Number(f(37, 43)), nbet: Number(f(43, 47)),
      dj: [], E: [num(f(92, 99)), num(f(99, 107)), num(f(107, 115))],
      mass: num(f(139, 150)),
    };
    for (let k = 0; k < 3; k++) {
      const j = Number(f(47 + 15 * k, 51 + 15 * k));
      if (j) rec.dj.push([j, num(f(51 + 15 * k, 62 + 15 * k))]);
    }
    recs.push(rec);
  }
  const byRecord = new Map(recs.map((r) => [r.record, r]));
  for (const r of recs) {
    r.d = [];
    for (const [j, b] of r.dj) {
      if (j === 9999) continue; // spontaneous fission: no single daughter
      const dn = byRecord.get(j);
      if (!dn) throw new Error(`${r.name}: daughter record ${j} not in the index`);
      r.d.push([dn.name, b]);
    }
  }
  return recs;
}

/* RAD records: "icode yield(%) energy(MeV)"; the nuclide's head record is at irad. */
const CODE38 = { 1: 'p', 2: 'p', 3: 'p', 4: 'b', 5: 'b', 6: 'e', 7: 'e', 8: 'a', 9: 'sf' };

function readRad38(lines, rec) {
  const rad = { p: [], b: [], e: [], a: [], sf: [] };
  const head = lines[rec.irad - 1] || '';
  if (!head.startsWith(rec.name)) throw new Error(`${rec.name}: RAD record ${rec.irad} is "${head.slice(0, 20)}"`);
  for (let i = 0; i < rec.nrad; i++) {
    const l = lines[rec.irad + i];
    const code = Number(l.slice(0, 1));
    const y = num(l.slice(1, 13)) / 100;
    const e = num(l.slice(13, 25));
    const key = CODE38[code];
    if (!key) throw new Error(`${rec.name}: radiation code ${code}`);
    if (key === 'sf') rad.sf.push([y, e]);
    else rad[key].push([e, y]);
  }
  return rad;
}

/* The fixed energy grid of the beta spectra, shared by both generations: read
   from the ICRP 107 file, where every point carries its energy. */
function betaGrid07(lines) {
  let longest = [];
  for (let i = 0; i < lines.length;) {
    const h = lines[i].trim().split(/\s+/);
    if (h.length < 2) { i++; continue; }
    const n = Number(h[1]);
    const es = [];
    for (let k = 1; k <= n; k++) es.push(Number(lines[i + k].slice(0, 8)));
    if (es.length > longest.length) longest = es;
    i += n + 1;
  }
  return longest.slice(0, -1); // the last point is that nuclide's own end point
}

function readBeta38(lines, rec, grid) {
  if (!rec.nbet) return null;
  const head = lines[rec.ibet - 1] || '';
  if (!head.startsWith(rec.name)) throw new Error(`${rec.name}: BET record ${rec.ibet} is "${head}"`);
  // Head record, the end-point energy, then nbet values of N(E): one per grid
  // point below the end point and the last at the end point itself.
  const emax = num(lines[rec.ibet]);
  const vals = [];
  for (let i = 0; i < rec.nbet; i++) vals.push(num(lines[rec.ibet + 1 + i]));
  // The end point is written to five decimals, so one that falls on a grid
  // point is ambiguous: Sn-127's 3.20000 lists the grid point 3.2 and then the
  // end point, Pt-200's 0.70000 only the end point. The count decides.
  let es = grid.filter((e) => e < emax);
  if (es.length + 2 === vals.length) es = grid.filter((e) => e <= emax + 1e-9);
  if (es.length + 1 !== vals.length) throw new Error(`${rec.name}: ${vals.length} spectrum values for ${es.length + 1} grid points`);
  es.push(emax);
  return [es, vals];
}

export function readIcrp38(dir) {
  const recs = readIndex38(`${dir}/ICRP38.NDX`);
  const rad = readLines(`${dir}/ICRP38.RAD`);
  const bet = readLines(`${dir}/ICRP38.BET`);
  return { recs, rad, bet };
}

export function icrp38Nuclides(dir, gridFrom07) {
  const { recs, rad, bet } = readIcrp38(dir);
  const grid = betaGrid07(readLines(gridFrom07));
  return recs.map((r) => {
    const { el, A, meta } = splitName(r.name);
    return {
      name: r.name, el, A, meta, t: r.half.trim() + r.unit.trim(), T: halfLifeDays(r.half, r.unit), mode: r.mode,
      d: r.d, E: r.E, mass: r.mass, rad: readRad38(rad, r), bs: readBeta38(bet, r, grid),
    };
  });
}

/* --------------------------------------------------------------------------
   ICRP 107 (ICRP-07)
   format(a7,a8,a2,a8,3i7,i6,1x,3(a7,i6,e11.0,1x),a7,i6,e11.0,f7.0,2f8.0,
          3i4,i5,i4,e11.0,e10.0,e9.0)
   Daughters are named; the record numbers beside them are not needed.
   -------------------------------------------------------------------------- */
function readIndex07(file) {
  const lines = readLines(file);
  const recs = [];
  for (let r = 1; r < lines.length; r++) {
    const l = lines[r];
    if (!l.trim()) continue;
    const f = (a, b) => l.slice(a, b);
    const rec = {
      name: f(0, 7).trim(), half: f(7, 15), unit: f(15, 17), mode: f(17, 25).trim(),
      // Record numbers in the RAD and BET files; how many records follow is
      // in each file's own head record.
      irad: Number(f(25, 32)), ibet: Number(f(32, 39)),
      d: [],
    };
    let p = 53;
    for (let k = 0; k < 4; k++) {
      const dn = f(p, p + 7).trim();
      const b = num(f(p + 13, p + 24));
      if (dn) rec.d.push([dn, b]);
      p += 25;
    }
    p -= 1; // the fourth daughter has no trailing blank
    rec.E = [num(f(p, p + 7)), num(f(p + 7, p + 15)), num(f(p + 15, p + 23))];
    recs.push(rec);
  }
  return recs;
}

const CODE07 = { 1: 'p', 2: 'p', 3: 'p', 4: 'b', 5: 'b', 6: 'e', 7: 'e', 8: 'a', 9: 'ar', 10: 'ff', 11: 'n' };

function readRad07(lines, rec) {
  const rad = { p: [], b: [], e: [], a: [], ar: [], ff: [], n: [] };
  const head = (lines[rec.irad - 1] || '').trim().split(/\s+/);
  if (head[0] !== rec.name) throw new Error(`${rec.name}: RAD record ${rec.irad} is "${head.join(' ')}"`);
  const nrad = Number(head[2]);
  for (let i = 0; i < nrad; i++) {
    const t = lines[rec.irad + i].trim().split(/\s+/);
    const key = CODE07[Number(t[0])];
    if (!key) throw new Error(`${rec.name}: radiation code ${t[0]}`);
    rad[key].push([num(t[2]), num(t[1])]);
  }
  return rad;
}

function readBeta07(lines, rec) {
  if (!rec.ibet) return null;
  const head = (lines[rec.ibet - 1] || '').trim().split(/\s+/);
  if (head[0] !== rec.name) throw new Error(`${rec.name}: BET record ${rec.ibet} is "${head.join(' ')}"`);
  const n = Number(head[1]);
  const es = [], ns = [];
  for (let k = 0; k < n; k++) {
    const l = lines[rec.ibet + k];
    es.push(Number(l.slice(0, 8)));
    ns.push(num(l.slice(8)));
  }
  return [es, ns];
}

/** A file of `dir` by name, whatever its case: the ICRP's own files are
    ICRP-07.RAD and ICRP-07.BET, ORNL's copies icrp-07.rad and icrp-07.bet. */
export function fileIn(dir, name) {
  const hit = fs.readdirSync(dir).find((f) => f.toLowerCase() === name.toLowerCase());
  if (!hit) throw new Error(`no ${name} in ${dir}`);
  return `${dir}/${hit}`;
}

/* The radiation files (RAD, BET) of the ICRP's supplementary data and of
   ORNL's copies are the same; the index (NDX) exists in three versions that
   differ only in the atomic masses (2008; ORNL 2012; the ICRP's corrigenda,
   2021), which are not read here. */
export function icrp107Nuclides(dir, ndxFile = fileIn(dir, 'ICRP-07.NDX')) {
  const recs = readIndex07(ndxFile);
  const rad = readLines(fileIn(dir, 'ICRP-07.RAD'));
  const bet = readLines(fileIn(dir, 'ICRP-07.BET'));
  return recs.map((r) => {
    const { el, A, meta } = splitName(r.name);
    return {
      name: r.name, el, A, meta, t: r.half.trim() + r.unit.trim(), T: halfLifeDays(r.half, r.unit), mode: r.mode,
      d: r.d.filter(([dn]) => dn !== 'SF'), E: r.E, rad: readRad07(rad, r), bs: readBeta07(bet, r),
    };
  });
}

/* --------------------------------------------------------------------------
   Compact output: numbers to six significant figures, which is what the
   files carry, and one object per element so the page loads only the
   elements of the chain it needs.
   -------------------------------------------------------------------------- */
export const sig = (v, n = 6) => (v === 0 ? 0 : Number(v.toPrecision(n)));
const lines = (arr) => arr.map(([e, y]) => [sig(e), sig(y)]).sort((p, q) => p[0] - q[0]);

export function compactRad(rad) {
  const out = {};
  for (const [k, v] of Object.entries(rad)) {
    if (!v.length) continue;
    out[k] = k === 'sf' ? v.map(([y, e]) => [sig(y), sig(e)]) : lines(v);
  }
  return out;
}

export function compactSpectrum(bs) {
  if (!bs) return null;
  return [bs[0].map((e) => sig(e)), bs[1].map((n) => sig(n, 4))];
}
