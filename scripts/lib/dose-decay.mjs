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
    else if (code === 2) rad[key].push([e, y, XRAY]);
    else if (code === 7) rad[key].push([e, y, AUGER]);
    else rad[key].push([e, y]);
  }
  return rad;
}

/* --------------------------------------------------------------------------
   The series of the L X-rays.

   Publication 38's tables list the K X-rays line by line and the L X-rays by
   series, L-alpha, L-beta, L-gamma, L-eta and L-l, one line each with the
   series' yield and mean energy (the unabridged file has every line). The
   page needs the series to make the tables' lines from the file's
   (resources/js/dose/decay38.js), so each L X-ray gets its series and the
   atomic number of its atom as a third item: [E, y, "a52"] is an L-alpha
   line of tellurium.

   A line is the transition of the daughter atom whose energy, the difference
   of two binding energies of resources/data/dose/atomic/, lies nearest, if
   within 1 % or 10 eV. The series by Siegbahn's names:

     L3 from M1          l  (L-l)       L2 from M1            h  (L-eta)
     L3 from M4, M5      a  (alpha2,1)  L2 from M2 ... M5     b  (beta1, 17)
     L3 from M2, M3      t  (Lt, Ls)    L2 from N, O, P       g  (gamma1, 5, 6, 8)
     L3 from N, O, P     b  (beta6, 2, 15, 7, 5)
     L1 from M           b  (beta4, 3, 10, 9)
     L1 from N, O, P     g  (gamma2, 3, 4)

   L-alpha2 (L3 from M4) and L-eta (L2 from M1) lie within a few eV of each
   other around europium, nearer than the two sets of energies agree; there
   L-alpha2 is the line whose yield is to L-alpha1's as the atom's two
   transition probabilities.
   -------------------------------------------------------------------------- */
const XRAY = 'x', AUGER = 'A';
const SERIES = {
  L3: (j) => (j === 'M1' ? 'l' : j === 'M4' || j === 'M5' ? 'a' : j === 'M2' || j === 'M3' ? 't' : 'b'),
  L2: (j) => (j === 'M1' ? 'h' : j[0] === 'M' ? 'b' : 'g'),
  L1: (j) => (j[0] === 'M' ? 'b' : 'g'),
};
/* Which atoms a nuclide's X-rays come from, by its decay modes. */
function xrayAtoms(Z, mode) {
  const out = new Set();
  if (/EC|B\+/.test(mode)) out.add(Z - 1);
  if (/B-/.test(mode)) out.add(Z + 1);
  if (/A/.test(mode)) out.add(Z - 2);
  if (/IT/.test(mode)) out.add(Z);
  return out.size ? [...out] : [Z - 2, Z - 1, Z, Z + 1];
}

/**
 * Mark the L X-rays of ICRP 38 nuclides with their series (see above).
 * @param {object[]} nucs    icrp38Nuclides()
 * @param {(Z: number) => object|null} atom  the element's table of resources/data/dose/atomic/
 * @param {(symbol: string) => number} zOf
 * @returns {{lines: number, nuclides: number}}  how many were marked
 */
export function labelLSeries(nucs, atom, zOf) {
  const cache = new Map();
  const transitions = (Z) => {
    if (cache.has(Z)) return cache.get(Z);
    const t = atom(Z), list = [];
    if (t) {
      const B = Object.fromEntries(t.shells.map((s, i) => [s, t.E[i]]));
      const prob = (i, j) => { const x = t.x[t.shells.indexOf(i)] || []; for (let k = 0; k < x.length; k += 2) if (t.shells[x[k]] === j) return x[k + 1]; return 0; };
      for (const i of ['L1', 'L2', 'L3']) {
        if (!(B[i] > 0)) continue;
        for (const [j, b] of Object.entries(B)) if (/^[MNOP]/.test(j) && b < B[i]) list.push({ E: (B[i] - b) / 1e6, i, j, g: SERIES[i](j) + Z, Z });
      }
      list.alpha2 = prob('L3', 'M5') > 0 ? prob('L3', 'M4') / prob('L3', 'M5') : null;
    }
    cache.set(Z, list);
    return list;
  };
  let lines = 0, nuclides = 0;
  for (const n of nucs) {
    const X = n.rad.p.filter((l) => l[2] === XRAY);
    if (!X.length) continue;
    const cands = xrayAtoms(zOf(n.el), n.mode).filter((Z) => Z >= 3).flatMap(transitions);
    let any = false;
    for (const l of X) {
      let best = null, d = Infinity;
      for (const c of cands) { const dd = Math.abs(c.E - l[0]); if (dd < d) { d = dd; best = c; } }
      if (best && d <= Math.max(0.01 * l[0], 10e-6)) { l[2] = best.g; l.tr = best; lines++; any = true; }
    }
    // L-alpha2 or L-eta, where the two are nearer than the energies tell.
    for (const Z of new Set(X.filter((l) => l.tr).map((l) => l.tr.Z))) {
      const ratio = transitions(Z).alpha2;
      const a1 = X.find((l) => l.tr?.Z === Z && l.tr.i === 'L3' && l.tr.j === 'M5');
      const pair = X.filter((l) => l.tr?.Z === Z && ((l.tr.i === 'L3' && l.tr.j === 'M4') || (l.tr.i === 'L2' && l.tr.j === 'M1')));
      if (!a1 || ratio === null || pair.length !== 2 || Math.abs(pair[0][0] - pair[1][0]) > 0.004 * a1[0]) continue;
      const off = (l) => Math.abs(l[1] / a1[1] - ratio);
      const a2 = off(pair[0]) <= off(pair[1]) ? pair[0] : pair[1], eta = a2 === pair[0] ? pair[1] : pair[0];
      a2[2] = 'a' + Z; eta[2] = 'h' + Z;
    }
    if (any) nuclides++;
  }
  return { lines, nuclides };
}

/* --------------------------------------------------------------------------
   The groups of the Auger electrons.

   Publication 38's tables give the Auger electrons in groups, "Auger-KLL",
   "KLX", "KXY", "LMM", "LMX", "LXY", "MXY", each "a composite of several
   Auger transitions of similar energy" with one yield and a mean energy. The
   file has the lines the groups are made of: for a K vacancy six KLL lines
   (the two new vacancies in L1L1, L1L2, L1L3, L2L2, L2L3, L3L3), three KLX
   (one in L1, L2 or L3, one further out) and one KXY; for each L subshell
   one line LMM, one LMX and one LXY; and one line or two of the M shell and
   beyond. A line of a group of several gets the group and the atom as its
   third item: [E, y, "KLL52"].

   K lines: the nearest of the atom's ten, within 1 %, where
     KLiLj  B(K) - B(Li) - [B(Lj) + B'(Lj)] / 2   (B' of the next element:
            the second vacancy is made in an atom that has one already)
     KLiX   B(K) - B(Li) - m,   KXY  B(K) - 2 m,   m the mean of B(M2), B(M3)
   reproduce the file's lines within 0.7 % from manganese to mercury.

   L lines: the file's three lines of a kind lie below the three L binding
   energies by one and the same energy (tellurium: LMM 1.392, LMX 0.627, LXY
   0.095 keV below L3, L2 and L1 alike), so three lines, or two where the
   third is missing, that do so within 0.15 % of B(L3) + 2 eV are a group:
   LMM when that energy is over 1.7 B(M5), LXY under 0.6 B(M5), else LMX.
   Lines that find no partner stay single.
   -------------------------------------------------------------------------- */
/**
 * Mark the Auger electrons of ICRP 38 nuclides with their groups (see above).
 * @param {object[]} nucs    icrp38Nuclides()
 * @param {(Z: number) => object|null} atom  the element's table of resources/data/dose/atomic/
 * @param {(symbol: string) => number} zOf
 * @returns {{lines: number, nuclides: number, single: number}}  lines marked, nuclides with any, Auger lines left single
 */
export function labelAugerGroups(nucs, atom, zOf) {
  const cache = new Map();
  const binding = (Z) => {
    if (!cache.has(Z)) { const t = atom(Z); cache.set(Z, t ? Object.fromEntries(t.shells.map((s, i) => [s, t.E[i] / 1e6])) : null); }
    return cache.get(Z);
  };
  const L = ['L1', 'L2', 'L3'];
  let lines = 0, nuclides = 0, single = 0;
  for (const n of nucs) {
    const A = n.rad.e.filter((l) => l[2] === AUGER);
    if (!A.length) continue;
    const atoms = xrayAtoms(zOf(n.el), n.mode).filter((Z) => Z >= 3 && binding(Z));
    // K lines.
    const K = [];
    for (const Z of atoms) {
      const B = binding(Z), B1 = binding(Z + 1) || B;
      if (!(B.K > 0) || !L.every((i) => B[i] > 0)) continue;
      const m = ((B.M2 ?? B.M1 ?? 0) + (B.M3 ?? B.M2 ?? B.M1 ?? 0)) / 2;
      L.forEach((i, a) => L.slice(a).forEach((j) => K.push({ E: B.K - B[i] - (B[j] + (B1[j] ?? B[j])) / 2, g: `KLL${Z}` })));
      for (const i of L) K.push({ E: B.K - B[i] - m, g: `KLX${Z}` });
      K.push({ E: B.K - 2 * m, g: null }); // KXY is one line
    }
    const top = Math.max(0, ...atoms.map((Z) => binding(Z).L1 || 0));
    for (const l of A) {
      if (!(l[0] > 1.02 * top)) continue;
      let best = null, d = Infinity;
      for (const c of K) { const dd = Math.abs(c.E - l[0]); if (dd < d) { d = dd; best = c; } }
      if (best && d <= 0.01 * l[0]) l.g = best.g;
    }
    // L lines.
    for (const Z of atoms) {
      const B = binding(Z);
      if (!L.every((i) => B[i] > 0)) continue;
      const m5 = B.M5 ?? B.M4 ?? B.M3 ?? B.M1 ?? 0, tol = 0.0015 * B.L3 + 2e-6;
      const free = () => A.filter((l) => l.g === undefined && l[0] <= B.L1 + tol && l[0] > 0.3 * B.L3);
      const kind = (h) => (h > 1.7 * m5 ? 'LMM' : h < 0.6 * m5 ? 'LXY' : 'LMX');
      // three lines first, then two
      for (const need of [3, 2]) {
        for (const a of free()) {
          if (a.g !== undefined) continue;
          for (const i of L) {
            const h = B[i] - a[0];
            if (h < -tol) continue;
            const group = [a];
            for (const j of L) {
              if (j === i) continue;
              const b = free().find((l) => !group.includes(l) && Math.abs(B[j] - l[0] - h) <= tol);
              if (b) group.push(b);
            }
            if (group.length >= need) { for (const l of group) l.g = `${kind(Math.max(h, 0))}${Z}`; break; }
          }
        }
      }
    }
    let any = false;
    for (const l of A) {
      if (typeof l.g === 'string') { l[2] = l.g; lines++; any = true; } else { single++; }
    }
    if (any) nuclides++;
  }
  return { lines, nuclides, single };
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
// A line is [energy, yield]; an L X-ray of ICRP 38 also has its series and
// an Auger electron its group (labelLSeries, labelAugerGroups).
const lines = (arr) => arr.map(([e, y, g]) => (typeof g === 'string' && g !== XRAY && g !== AUGER ? [sig(e), sig(y), g] : [sig(e), sig(y)])).sort((p, q) => p[0] - q[0]);

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
