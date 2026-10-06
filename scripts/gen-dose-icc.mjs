#!/usr/bin/env node
/*
  The conversion-coefficient table of the ENSDF processor (resources/js/dose/
  ensdf-icc.js): internal-conversion coefficients by shell for pure
  multipolarities, made from the coefficients that EDISTR04 printed while it
  produced ICRP Publication 107:

      node scripts/gen-dose-icc.mjs <ARCHIVE> [--atomic DIR] [--out FILE] [--points FILE]

  ARCHIVE is the ARCHIVE folder of ICRP 107's supplementary data: OUTPUT/*.out
  are EDISTR04's printouts, INPUT/*.ens the ENSDF it read. --atomic is a
  folder of binding-energy tables (<symbol>.json as gen-dose-atomic.mjs writes
  them; default resources/data/dose/atomic). --points writes every printed
  gamma with what the fit made of it, for the checks. Writes
  resources/data/dose/icc/icc.json unless --out says otherwise. The table is
  fitted to numbers of ICRP 107's supplementary data, whose licence (Endo and
  Eckerman's LICENSE.TXT) goes with it in that folder.

  What EDISTR04 printed. Each parent state's INPUT DATA section lists every
  gamma transition with its multipolarity and the coefficients EDISTR04 used:

      I.C.E. + GAMMA   1   1.01E+00   3.549E-02   M1+E2 MULTIPOLE
                                                  MRS=0.000841  AK= 12.1
                                                  AL1=1.45      AL2=0.134
                                                  AL3=0.0543    AM= 0.330
                                                  AN+=0.0785

  (energy in MeV; MRS = delta squared; K, L1, L2, L3, all of M, N and beyond),
  to three figures, nothing below 0.001, "0.0" below a shell's edge. A line
  starting with '+' overprints the line before (Fortran carriage control):
  "ASSUMED", "MRS=" and "AK=" often come that way. The data sets of a state's
  decay modes follow one another, each its feeding transitions and then its
  gammas; the daughter is the parent's Z + 1 (beta minus), - 1 (capture),
  - 2 (alpha) or the same (no feeding: isomeric transition). The coefficients
  are those of Rösel et al. (1978) for E1-E4 and M1-M4 at 30 <= Z <= 103,
  of Band and Trzhaskovskaya for E5 and M5, and EDISTR's older bank (Hager
  and Seltzer, Band et al.: K and L only) below Z = 30, mixed by delta, and
  scaled to the evaluator's total CC where the two differed by more than 10 %
  (Dillman, ORNL/TM-6689, sec. 1.4; JAERI 1347 sec. 3.1.3). Those scaled
  values are not theory and are left out (below).

  The table. For each multipolarity E1-E4, M1-M4 and each shell group K, L1,
  L2, L3, M and N+, log10 alpha is a tensor-product cubic B-spline in
      x = ln Z, and
      y = log10(E / B) for K, L1, L2, L3, B that subshell's binding energy, so
          that every Z has its edge at y = 0 and the shapes near the edge line
          up; y = log10(E / keV) for M and N+, whose edges are low enough that
          the energy itself is the smoother variable.
  The coefficients come from penalised least squares on the printed values:
  sum of squared residuals in log10 alpha plus lambda times the thin-plate
  roughness int int (f_xx^2/s^4 + 2 f_xy^2/s^2 + f_yy^2) over the knot domain
  (O'Sullivan's penalty, right for unequal knot spacing); lambda and the
  anisotropy s are chosen per surface by leave-one-out cross-validation.
  E1, E2, M1 and M2 have thousands of points (hundreds for M2) and are fitted
  directly. E3, E4, M3 and M4 are fitted as a smooth difference to the
  linear extrapolation in the multipole order L of the two orders below them
  (E3 to 2 E2 - E1, E4 to 2 E3 - E2, likewise M), which varies far less than
  the coefficients do, so that tens of points can pin it. E5 and M5, with
  14 and 4 printed transitions, are that extrapolation (2 E4 - E3, 2 M4 - M3)
  times one factor per shell, the median of what their printed values leave;
  the module builds them so.
  Values not printed because they are below 0.001 are kept as an upper
  bound: where the fit would go above 0.001 they count as observations of
  0.001. Transitions printed more than once (one level fed by several
  parents) count once. Transitions whose printed values sit off the fit by
  more than 8 % (median over their shells) are taken for scaled and left out,
  when their printed total equals the CC of EDISTR04's input (the scaling's
  signature) or, for E1, E2, M1 and M2, which have the data to tell, also
  without it.
  Where nothing was printed - below Z = 30 (37 for N+) and above the energy
  where a shell falls under 0.001 - the spline only extrapolates, and goes
  astray by orders of magnitude far out: the module (ensdf-icc.js) does not
  use the table there but continues it by physics (Z_ANCHOR).

  Output, icc.json:
    { source, method, knots: {Z, w, u} (the interior knots; each end is
      extended by three knots at the end spacing), shells: {K: 'w', ...},
      binding: {source, K: [Z = 1..], L1, L2, L3, M1, N1} keV, the edges y
      is measured from (K, L) and the module's rule below Z_ANCHOR uses,
      lowZ: {anchor: {K: 30, ...}, occupancy: {K: [Z = 1..], ...}}: below
      the anchor the module carries the table down by physics; the electrons
      of each group's s and p subshells (EADL),
      surfaces: {E1: {K: {j0: [...], c: [[...], ...]}, ...}, ... M4}:
      row i of the coefficients (x basis function i) starts at y basis
      function j0[i]; log10 alpha to 0.001. Coefficients that no point with
      1 <= Z <= 110 and B / 1.3 <= E <= 10 MeV reaches are left out.
      derived: {E5: {from: [[2, 'E4'], [-1, 'E3']], offset: {K: ...}}, M5: ...}:
      coefficients sum(k * from) + offset (B-splines add up to one). }
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export const SHELLS = ['K', 'L1', 'L2', 'L3', 'M', 'N+'];
const LABEL = { K: 'AK', L1: 'AL1', L2: 'AL2', L3: 'AL3', M: 'AM', 'N+': 'AN+' };
/* The subshell each group's y is measured from, and its edge in the data. */
const EDGE = { K: 'K', L1: 'L1', L2: 'L2', L3: 'L3', M: 'M1', 'N+': 'N1' };
const IN_W = { K: true, L1: true, L2: true, L3: true, M: false, 'N+': false };
export const KNOTS = {
  Z: [1, 10, 20, 32, 44, 56, 68, 80, 92, 110],
  w: [-0.3, -0.1, 0, 0.06, 0.15, 0.28, 0.45, 0.7, 1.0, 1.4, 1.9, 2.6, 3.5, 5.5],
  u: [-1.5, -0.5, 0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.6, 4.3],
};
const E_MAX = 1e4; // keV: the highest transition energy the table is meant for
const MUL_ORDER = ['E1', 'E2', 'M1', 'M2', 'E3', 'M3', 'E4', 'M4', 'E5', 'M5'];
/* Fit plan: the base each multipolarity is a smooth difference to, and the
   penalties tried (the sparser, the stiffer). */
const PLAN = {
  E1: { base: [], lambdas: [1e-5, 1e-4, 1e-3, 1e-2] },
  E2: { base: [], lambdas: [1e-5, 1e-4, 1e-3, 1e-2] },
  M1: { base: [], lambdas: [1e-5, 1e-4, 1e-3, 1e-2] },
  M2: { base: [], lambdas: [1e-5, 1e-4, 1e-3, 1e-2] },
  E3: { base: [[2, 'E2'], [-1, 'E1']], lambdas: [1e-3, 1e-2, 1e-1, 1] },
  M3: { base: [[2, 'M2'], [-1, 'M1']], lambdas: [1e-3, 1e-2, 1e-1, 1] },
  E4: { base: [[2, 'E3'], [-1, 'E2']], lambdas: [1e-2, 1e-1, 1, 10] },
  M4: { base: [[2, 'M3'], [-1, 'M2']], lambdas: [1e-3, 1e-2, 1e-1, 1] },
  // A handful of points each: the extrapolation times one factor per shell.
  E5: { base: [[2, 'E4'], [-1, 'E3']], offset: true },
  M5: { base: [[2, 'M4'], [-1, 'M3']], offset: true },
};
const DENSE = new Set(['E1', 'E2', 'M1', 'M2']);
const SPARSE = new Set(['E4', 'E5', 'M5']);
const SCALES = [0.5, 1, 2];
const SCALED_LOG = 0.035; // 8 %: EDISTR04 scaled only beyond 10 %
/* Where EDISTR04 printed nothing the fit only extrapolates, and goes astray
   far out: above the energy where a shell's coefficient falls under 0.001
   (nothing smaller was printed), and below Z = 30 (EDISTR04 had K and L
   there for some elements only, from its older bank, and no M; no N+ below
   37). The module continues the table there by physics instead (each shell
   keeping its ratio to the next inner one at high energy, Z scaling from
   Z_ANCHOR below it); icc.json
   holds what that needs besides the table: the binding energies and the
   electrons of each group's s and p subshells (OCC_SUBSHELLS). */
const Z_ANCHOR = { K: 30, L1: 30, L2: 30, L3: 30, M: 30, 'N+': 37 };
const OCC_SUBSHELLS = { K: ['K'], L1: ['L1'], L2: ['L2'], L3: ['L3'], M: ['M1', 'M2', 'M3'], 'N+': ['N1', 'N2', 'N3', 'O1', 'O2', 'O3', 'P1', 'P2', 'P3', 'Q1'] };

/* ---------------------------------------------------------------------------
   EDISTR04's printouts
   --------------------------------------------------------------------------- */

const num = (s) => { const t = String(s).trim().replace(/E\s+/i, 'E+'); return t ? Number(t) : NaN; };

/** Lines of a printout with the '+' overprint lines merged into the line before. */
function printedLines(text) {
  const out = [];
  for (const l of text.replace(/\r/g, '').split('\n')) {
    if (l.startsWith('+') && out.length) {
      const prev = out[out.length - 1];
      let merged = prev[0] || ' ';
      for (let i = 1; i < Math.max(prev.length, l.length); i++) merged += l[i] && l[i] !== ' ' ? l[i] : prev[i] || ' ';
      out[out.length - 1] = merged;
    } else out.push(l);
  }
  return out;
}

const DZ = { 'B-': 1, EC: -1, A: -2, IT: 0 };
const FEED = { 'BETA MINUS': 'B-', 'ELECT. CAPTURE': 'EC', 'BETA PLUS': 'EC', ALPHA: 'A' };
const COEF_RE = /(MRS|AK|AL1|AL2|AL3|AM|AN\+)=\s*([0-9.E+-]+)/g;

/**
 * Every gamma transition in the INPUT DATA sections of one printout:
 * {id, E (keV), mul, assumed, unplaced, na, icc: {MRS, AK, ...}, e0: {K, L1, M, N+}, Z, mode, parent}.
 */
export function readPrintout(text, file = '') {
  const L = printedLines(text);
  const out = [];
  let head = null, blocks = [], block = null, cur = null, skip = false, modes = [];
  const flush = () => {
    for (const b of blocks) {
      // A data set without feeding transitions is the isomeric transition's.
      const mode = b.feed || 'IT';
      for (const g of b.gammas) out.push({ ...g, Z: head.Z + DZ[mode], mode, parent: { A: head.A, el: head.el, Z: head.Z, iso: head.iso }, file, modes });
    }
  };
  for (const l of L) {
    if (l.startsWith('%%%%')) {
      const tag = l.slice(-8).trim();
      if (tag === 'INPUSTAR') {
        const m = /^%%%%\s*(\d+)\s+([A-Z]+)\s+(\d+)\s+(M?)\s/.exec(l);
        head = { A: Number(m[1]), el: m[2], Z: Number(m[3]), iso: m[4] === 'M' };
        blocks = []; block = null; cur = null; skip = false; modes = [];
      } else if (tag === 'INPUEND' && head) { flush(); head = null; }
      continue;
    }
    if (!head) continue;
    const md = /MODES? OF DECAY:\s*(.*)$/.exec(l);
    if (md) { modes = md[1].split(',').map((s) => s.trim()); continue; }
    const t = /^\s{5,30}(I\.C\.E\. \+ GAMMA|ELECT\. CAPTURE|BETA PLUS|BETA MINUS|ALPHA)\s+(\d+)\s+([0-9.E+-]+)\s+([0-9.E+-]+)(\*?)\s*(.*)$/.exec(l);
    if (t) {
      const id = Number(t[2]);
      if (t[1].startsWith('I.C.E')) {
        // gamma numbers restart with each data set
        if (!block || (block.gammas.length && id <= block.gammas[block.gammas.length - 1].id)) { block = { feed: null, gammas: [] }; blocks.push(block); }
        const text = t[6].trim();
        const g = {
          id, E: num(t[4]) * 1000, I: num(t[3]), text,
          unplaced: /UNPLACED/.test(text), assumed: /ASSUMED/.test(text),
          mul: text.replace(/\s*(MULTIPOLE.*|UNPLACED GAMMA.*)$/, '').trim(), icc: {},
        };
        for (const m of l.matchAll(COEF_RE)) g.icc[m[1]] = num(m[2]);
        block.gammas.push(g); cur = g; skip = false;
      } else {
        const feed = FEED[t[1]];
        if (!block || block.gammas.length || (block.feed && block.feed !== feed)) { block = { feed, gammas: [] }; blocks.push(block); } else block.feed = feed;
        cur = null;
      }
      continue;
    }
    if (!cur) continue;
    // After "I.C.C. DATA NOT AVAILABLE" EDISTR04 reprints an earlier gamma's values.
    if (/I\.C\.C\. DATA NOT AVAILABLE/.test(l)) { cur.na = true; skip = true; continue; }
    if (skip) continue;
    // E0: the ratios of M1's K, L1, M and N+ coefficients EDISTR04 used, K = 100.
    const e0 = /(K(?:\/L1)?(?:\/M)?(?:\/N\+)?)\s*=\s*([0-9./]*)/.exec(l);
    if (e0 && /K\/L1/.test(l)) { cur.e0keys = e0[1]; if (e0[2]) cur.e0vals = e0[2]; continue; }
    if (cur.e0keys && !cur.e0vals && /^\s+[0-9.]+\//.test(l)) { cur.e0vals = l.trim(); continue; }
    for (const m of l.matchAll(COEF_RE)) cur.icc[m[1]] = num(m[2]);
  }
  for (const g of out) {
    if (g.e0keys) {
      const v = g.e0vals.split('/').map(Number);
      g.e0 = Object.fromEntries(g.e0keys.split('/').map((k, i) => [k, v[i]]));
    }
    delete g.e0keys; delete g.e0vals;
  }
  return out;
}

/** The G records of an ENSDF input file: [{Z, E (keV), CC}]. */
function readInputGammas(text) {
  const out = [];
  for (const raw of text.replace(/\r/g, '').split('\n')) {
    const l = raw.padEnd(80);
    if (l[7] !== 'G' || l[5] !== ' ' || l[6] !== ' ' || l[8] !== ' ') continue;
    const m = /^\s*(\d+)([A-Z]{1,2})\s*$/.exec(l.slice(0, 5));
    if (!m) continue;
    const Z = ELEMENTS.indexOf(m[2][0] + m[2].slice(1).toLowerCase());
    out.push({ Z, E: Number(l.slice(9, 19).trim().replace(/[^0-9.E+-].*$/, '')), CC: Number(l.slice(55, 62).trim()) || NaN });
  }
  return out;
}

const ELEMENTS = ['n', 'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti',
  'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag',
  'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
  'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am',
  'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr', 'Rf', 'Db'];

/** Every printed gamma of the archive, each with ccMatch: its printed total equals an input CC. */
export function readArchive(archive) {
  const dir = path.join(archive, 'OUTPUT');
  const all = [];
  for (const f of fs.readdirSync(dir).filter((n) => /\.out$/i.test(n)).sort()) {
    const gammas = readPrintout(fs.readFileSync(path.join(dir, f), 'latin1'), f);
    const ens = path.join(archive, 'INPUT', f.replace(/\.out$/i, '.ens'));
    const input = fs.existsSync(ens) ? readInputGammas(fs.readFileSync(ens, 'latin1')) : [];
    for (const g of gammas) {
      const S = SHELLS.reduce((s, k) => s + (g.icc[LABEL[k]] || 0), 0);
      const missing = SHELLS.filter((k) => !(LABEL[k] in g.icc)).length;
      // Coefficients under 0.001 are not printed, so the input CC may exceed the printed sum by that much each.
      g.ccMatch = S > 0 && input.some((r) => r.Z === g.Z && Math.abs(r.E - g.E) <= Math.max(0.006, 6e-4 * g.E)
        && r.CC >= S * 0.995 && r.CC <= S * 1.005 + 0.0011 * missing);
      g.printedTotal = S;
      all.push(g);
    }
  }
  return all;
}

/* ---------------------------------------------------------------------------
   Binding energies
   --------------------------------------------------------------------------- */

/**
 * {Z: {K: keV, L1: keV, ...}} from a folder of <symbol>.json (E in eV), and on
 * the side, as .occupancy, {Z: {K: electrons, ...}}.
 */
export function readBinding(dir) {
  const out = {}, occ = {};
  for (let Z = 1; Z < ELEMENTS.length; Z++) {
    const f = path.join(dir, `${ELEMENTS[Z]}.json`);
    if (!fs.existsSync(f)) continue;
    const t = JSON.parse(fs.readFileSync(f, 'utf8'));
    out[Z] = Object.fromEntries(t.shells.map((s, i) => [s, t.E[i] / 1000]));
    occ[Z] = Object.fromEntries(t.shells.map((s, i) => [s, t.n[i]]));
  }
  Object.defineProperty(out, 'occupancy', { value: occ });
  return out;
}

/* ---------------------------------------------------------------------------
   Cubic B-splines and penalised least squares
   --------------------------------------------------------------------------- */

/** Knots extended by three at each end with the end spacing. */
export function knotVector(k) {
  const a = k[1] - k[0], b = k[k.length - 1] - k[k.length - 2];
  return [k[0] - 3 * a, k[0] - 2 * a, k[0] - a, ...k, k[k.length - 1] + b, k[k.length - 1] + 2 * b, k[k.length - 1] + 3 * b];
}

/**
 * The four cubic B-splines that are non-zero at x (clamped into the domain),
 * into v[0..3], with first and second derivatives into d1, d2 if given.
 * Returns the index of the first. Cox-de Boor recursion.
 */
export function basis(t, x, v, d1, d2) {
  const n = t.length - 4;
  if (x < t[3]) x = t[3]; else if (x > t[n]) x = t[n];
  let k = 3, hi = n - 1;
  if (x >= t[hi]) k = hi;
  else while (hi - k > 1) { const m = (k + hi) >> 1; if (t[m] <= x) k = m; else hi = m; }
  const N = [1, 0, 0, 0], left = [0, 0, 0, 0], right = [0, 0, 0, 0], N1 = [0, 0], N2 = [0, 0, 0];
  for (let j = 1; j <= 3; j++) {
    left[j] = x - t[k + 1 - j]; right[j] = t[k + j] - x;
    let saved = 0;
    for (let r = 0; r < j; r++) { const tmp = N[r] / (right[r + 1] + left[j - r]); N[r] = saved + right[r + 1] * tmp; saved = left[j - r] * tmp; }
    N[j] = saved;
    if (j === 1) { N1[0] = N[0]; N1[1] = N[1]; }
    if (j === 2) { N2[0] = N[0]; N2[1] = N[1]; N2[2] = N[2]; }
  }
  v[0] = N[0]; v[1] = N[1]; v[2] = N[2]; v[3] = N[3];
  if (d1 || d2) {
    const D = (i, p) => t[i + p] - t[i];
    const q1 = (i) => { const r = i - (k - 1); return r >= 0 && r < 2 ? N1[r] : 0; };
    const q2 = (i) => { const r = i - (k - 2); return r >= 0 && r < 3 ? N2[r] : 0; };
    const dq2 = (i) => 2 * ((D(i, 2) > 0 ? q1(i) / D(i, 2) : 0) - (D(i + 1, 2) > 0 ? q1(i + 1) / D(i + 1, 2) : 0));
    for (let r = 0; r < 4; r++) {
      const i = k - 3 + r;
      if (d1) d1[r] = 3 * ((D(i, 3) > 0 ? q2(i) / D(i, 3) : 0) - (D(i + 1, 3) > 0 ? q2(i + 1) / D(i + 1, 3) : 0));
      if (d2) d2[r] = 3 * ((D(i, 3) > 0 ? dq2(i) / D(i, 3) : 0) - (D(i + 1, 3) > 0 ? dq2(i + 1) / D(i + 1, 3) : 0));
    }
  }
  return k - 3;
}

const GX = [-0.8611363115940526, -0.3399810435848563, 0.3399810435848563, 0.8611363115940526];
const GW = [0.3478548451374538, 0.6521451548625461, 0.6521451548625461, 0.3478548451374538];

/** int B_i B_j, int B'_i B'_j and int B''_i B''_j over the domain (4-point Gauss per interval: exact). */
function grams(t) {
  const n = t.length - 4;
  const G = [new Float64Array(n * n), new Float64Array(n * n), new Float64Array(n * n)];
  const v = [0, 0, 0, 0], d1 = [0, 0, 0, 0], d2 = [0, 0, 0, 0];
  for (let k = 3; k < n; k++) {
    const a = t[k], b = t[k + 1];
    for (let q = 0; q < 4; q++) {
      const x = (a + b) / 2 + (b - a) / 2 * GX[q], w = (b - a) / 2 * GW[q];
      const i0 = basis(t, x, v, d1, d2);
      for (let r = 0; r < 4; r++) for (let s = 0; s < 4; s++) {
        const ij = (i0 + r) * n + i0 + s;
        G[0][ij] += w * v[r] * v[s]; G[1][ij] += w * d1[r] * d1[s]; G[2][ij] += w * d2[r] * d2[s];
      }
    }
  }
  return { n, G };
}

function cholesky(A, n) {
  const L = new Float64Array(A);
  for (let j = 0; j < n; j++) {
    let s = L[j * n + j];
    for (let k = 0; k < j; k++) s -= L[j * n + k] * L[j * n + k];
    if (!(s > 0)) throw new Error(`normal equations not positive definite (${j})`);
    const d = Math.sqrt(s);
    L[j * n + j] = d;
    for (let i = j + 1; i < n; i++) {
      let u = L[i * n + j];
      for (let k = 0; k < j; k++) u -= L[i * n + k] * L[j * n + k];
      L[i * n + j] = u / d;
    }
    for (let i = 0; i < j; i++) L[i * n + j] = 0;
  }
  return L;
}
function cholSolve(L, n, b) {
  const y = Float64Array.from(b);
  for (let i = 0; i < n; i++) { let s = y[i]; for (let k = 0; k < i; k++) s -= L[i * n + k] * y[k]; y[i] = s / L[i * n + i]; }
  for (let i = n - 1; i >= 0; i--) { let s = y[i]; for (let k = i + 1; k < n; k++) s -= L[k * n + i] * y[k]; y[i] = s / L[i * n + i]; }
  return y;
}

/** A tensor-product spline space on knot vectors tx, ty (coefficient (i, j) at i * ny + j). */
export class Space {
  constructor(tx, ty) {
    this.tx = tx; this.ty = ty;
    this.gx = grams(tx); this.gy = grams(ty);
    this.nx = this.gx.n; this.ny = this.gy.n; this.p = this.nx * this.ny;
  }
  penalty(lambda, s) {
    const { nx, ny, p } = this, [X0, X1, X2] = this.gx.G, [Y0, Y1, Y2] = this.gy.G;
    const P = new Float64Array(p * p), s2 = 1 / (s * s), s4 = s2 * s2;
    for (let i = 0; i < nx; i++) for (let k = 0; k < nx; k++) {
      const a2 = X2[i * nx + k] * s4, a1 = 2 * X1[i * nx + k] * s2, a0 = X0[i * nx + k];
      if (!a2 && !a1 && !a0) continue;
      for (let j = 0; j < ny; j++) for (let l = 0; l < ny; l++) {
        const v = a2 * Y0[j * ny + l] + a1 * Y1[j * ny + l] + a0 * Y2[j * ny + l];
        if (v) P[(i * ny + j) * p + k * ny + l] += lambda * v;
      }
    }
    return P;
  }
  design(xs, ys) {
    const v = [0, 0, 0, 0], w = [0, 0, 0, 0], m = xs.length;
    const idx = new Int32Array(m * 16), val = new Float64Array(m * 16);
    for (let n = 0; n < m; n++) {
      const i0 = basis(this.tx, xs[n], v), j0 = basis(this.ty, ys[n], w);
      for (let r = 0, q = n * 16; r < 4; r++) for (let s = 0; s < 4; s++, q++) { idx[q] = (i0 + r) * this.ny + j0 + s; val[q] = v[r] * w[s]; }
    }
    return { idx, val, m };
  }
  solve(D, y, wts, P) {
    const { p } = this, A = Float64Array.from(P), b = new Float64Array(p);
    for (let n = 0; n < D.m; n++) {
      if (!wts[n]) continue;
      for (let a = 0, q0 = n * 16; a < 16; a++) {
        const ia = D.idx[q0 + a], va = D.val[q0 + a] * wts[n];
        b[ia] += va * y[n];
        for (let c = 0; c < 16; c++) A[ia * p + D.idx[q0 + c]] += va * D.val[q0 + c];
      }
    }
    for (let i = 0; i < p; i++) A[i * p + i] += 1e-10; // coefficients nothing reaches stay defined
    const L = cholesky(A, p);
    return { c: cholSolve(L, p, b), L };
  }
  predict(D, c) {
    const out = new Float64Array(D.m);
    for (let n = 0; n < D.m; n++) { let s = 0; for (let a = 0, q0 = n * 16; a < 16; a++) s += c[D.idx[q0 + a]] * D.val[q0 + a]; out[n] = s; }
    return out;
  }
  value(c, x, y) {
    const v = [0, 0, 0, 0], w = [0, 0, 0, 0];
    const i0 = basis(this.tx, x, v), j0 = basis(this.ty, y, w);
    let s = 0;
    for (let r = 0; r < 4; r++) for (let q = 0; q < 4; q++) s += v[r] * w[q] * c[(i0 + r) * this.ny + j0 + q];
    return s;
  }
  /** h_nn = w_n b_n' A^-1 b_n, the leverages (leave-one-out residual = r / (1 - h)). */
  leverage(D, wts, L) {
    const { p } = this, inv = new Float64Array(p * p), e = new Float64Array(p);
    for (let j = 0; j < p; j++) { e.fill(0); e[j] = 1; const x = cholSolve(L, p, e); for (let i = 0; i < p; i++) inv[i * p + j] = x[i]; }
    const h = new Float64Array(D.m);
    for (let n = 0; n < D.m; n++) {
      if (!wts[n]) continue;
      let s = 0;
      for (let a = 0, q0 = n * 16; a < 16; a++) for (let c = 0; c < 16; c++) s += D.val[q0 + a] * inv[D.idx[q0 + a] * p + D.idx[q0 + c]] * D.val[q0 + c];
      h[n] = wts[n] * s;
    }
    return h;
  }
}

/* ---------------------------------------------------------------------------
   The fit
   --------------------------------------------------------------------------- */

const median = (a) => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

/** y of a shell group at energy E (keV) for binding energies B. */
const yOf = (shell, E, B) => (IN_W[shell] ? Math.log10(E / B[EDGE[shell]]) : Math.log10(E));

/**
 * Fit every surface. points: readArchive() output; bind: readBinding().
 * Returns {coef: {'E1 K': Float64Array}, spaces, info: {key: {lambda, s, n, loo: [...]}}, transitions}.
 */
export function fitTable(points, bind, log = () => {}) {
  const tx = knotVector(KNOTS.Z.map(Math.log));
  const spaces = { w: new Space(tx, knotVector(KNOTS.w)), u: new Space(tx, knotVector(KNOTS.u)) };
  const spaceOf = (shell) => (IN_W[shell] ? spaces.w : spaces.u);

  // Pure transitions, placed, with data; one per (Z, multipolarity, energy, values).
  const seen = new Map();
  const T = [];
  for (const g of points) {
    if (g.unplaced || g.na || 'MRS' in g.icc || !(g.mul in PLAN) || !bind[g.Z]) continue;
    const key = `${g.Z}|${g.mul}|${g.E.toFixed(2)}|${SHELLS.map((s) => g.icc[LABEL[s]]).join(',')}`;
    if (seen.has(key)) { seen.get(key).copies.push(g); continue; }
    const t = { g, Z: g.Z, E: g.E, mul: g.mul, B: bind[g.Z], ccMatch: g.ccMatch, flag: false, res: {}, copies: [g] };
    seen.set(key, t);
    T.push(t);
  }
  for (const t of T) t.ccMatch = t.copies.some((g) => g.ccMatch);

  const dataFor = (mul, shell) => {
    const xs = [], ys = [], zs = [], cens = [], tr = [];
    for (const t of T) {
      if (t.mul !== mul) continue;
      const edge = t.B[EDGE[shell]];
      if (edge === undefined) continue;
      const v = t.g.icc[LABEL[shell]];
      if (v > 0) {
        if (t.E < edge) continue; // M and N+ of transitions of a few keV: below the reference edge
        xs.push(Math.log(t.Z)); ys.push(yOf(shell, t.E, t.B)); zs.push(Math.log10(v)); cens.push(false); tr.push(t);
      } else if (v === undefined && t.E > edge) {
        // not printed: under 0.001, where EDISTR04 had the shell at all
        if ((shell === 'M' && t.Z < 30) || (shell === 'N+' && (t.Z < 37 || /5$/.test(mul)))) continue;
        xs.push(Math.log(t.Z)); ys.push(yOf(shell, t.E, t.B)); zs.push(-3); cens.push(true); tr.push(t);
      }
    }
    return { xs, ys, zs, cens, tr };
  };

  const coef = {}, info = {};
  // d may end in rule points (tr null), which keep weight RULE_W
  const fitOne = (S, D, d, base, lambda, s) => {
    const P = S.penalty(lambda, s);
    const b0 = base ? S.predict(D, base) : new Float64Array(d.xs.length);
    const wts = new Float64Array(d.xs.length), y = new Float64Array(d.xs.length);
    let c, L, pred = null;
    for (let it = 0; it < 5; it++) {
      for (let n = 0; n < d.xs.length; n++) {
        // a censored value counts as 0.001 only while the fit puts it above
        wts[n] = !d.tr[n] ? RULE_W : d.tr[n].flag ? 0 : !d.cens[n] ? 1 : pred && pred[n] > -3 ? 1 : 0;
        y[n] = d.zs[n] - b0[n];
      }
      ({ c, L } = S.solve(D, y, wts, P));
      pred = S.predict(D, c).map((v, n) => v + b0[n]);
    }
    if (base) for (let i = 0; i < c.length; i++) c[i] += base[i];
    return { c, L, pred, wts };
  };


  for (let pass = 0; pass < 3; pass++) {
    const last = pass === 2;
    for (const t of T) t.res = {};
    for (const mul of MUL_ORDER) for (const shell of SHELLS) {
      const key = `${mul} ${shell}`, S = spaceOf(shell), plan = PLAN[mul];
      let base = null;
      if (plan.base.length) {
        base = new Float64Array(S.p);
        for (const [k, m] of plan.base) { const c = coef[`${m} ${shell}`]; for (let i = 0; i < S.p; i++) base[i] += k * c[i]; }
      }
      const d = dataFor(mul, shell);
      if (!d.xs.some((_, n) => !d.cens[n])) { coef[key] = base; info[key] = { n: 0, offset: plan.offset ? 0 : undefined, support: new Float64Array(S.p) }; continue; }
      const D = S.design(d.xs, d.ys);
      if (plan.offset) {
        // log10 alpha = extrapolation + one constant: the median of what the printed values leave
        const b0 = S.predict(D, base);
        const r = [];
        for (let n = 0; n < d.xs.length; n++) if (!d.cens[n] && !d.tr[n].flag) r.push([n, d.zs[n] - b0[n]]);
        const off = r.length ? median(r.map(([, v]) => v)) : 0;
        coef[key] = base.map((v) => v + off);
        const loo = [];
        for (let n = 0; n < d.xs.length; n++) {
          if (d.cens[n]) continue;
          d.tr[n].res[shell] = d.zs[n] - b0[n] - off;
          if (last && !d.tr[n].flag) {
            const others = r.filter(([m]) => m !== n).map(([, v]) => v);
            const o = others.length ? median(others) : 0;
            (d.tr[n].fit ||= {})[shell] = b0[n] + off;
            (d.tr[n].loo ||= {})[shell] = b0[n] + o;
            loo.push(d.zs[n] - b0[n] - o);
          }
        }
        info[key] = { offset: off, n: loo.length, loo };
        continue;
      }
      // Until the scaled values are out, one middling penalty; then the best by leave-one-out.
      const grid = last ? plan.lambdas.flatMap((l) => SCALES.map((s) => [l, s])) : [[plan.lambdas[1], 1]];
      let best = null;
      for (const [lambda, s] of grid) {
        const f = fitOne(S, D, d, base, lambda, s);
        const h = last ? S.leverage(D, f.wts, f.L) : null;
        let cv = 0;
        if (h) {
          let ss = 0, m = 0;
          for (let n = 0; n < d.xs.length; n++) {
            if (!f.wts[n] || d.cens[n]) continue;
            const r = (d.zs[n] - f.pred[n]) / (1 - h[n]);
            ss += Math.min(r * r, 0.01); m++; // capped: a few odd points must not choose the penalty
          }
          cv = m ? ss / m : 0;
        }
        if (!best || cv < best.cv) best = { ...f, lambda, s, cv, h };
      }
      coef[key] = best.c;
      const loo = [];
      for (let n = 0; n < d.xs.length; n++) {
        if (d.cens[n]) continue;
        d.tr[n].res[shell] = d.zs[n] - best.pred[n];
        if (best.h && best.wts[n]) {
          const r = d.zs[n] - best.pred[n], h = best.h[n];
          (d.tr[n].fit ||= {})[shell] = best.pred[n];
          (d.tr[n].loo ||= {})[shell] = best.pred[n] - r * h / (1 - h);
          loo.push(r / (1 - h));
        }
      }
      info[key] = { lambda: best.lambda, s: best.s, n: loo.length, loo };
    }
    let flagged = 0;
    for (const t of T) {
      const r = Object.values(t.res);
      if (!r.length) continue;
      t.med = median(r);
      const a = Math.abs(t.med);
      // the sparsest orders are not known well enough to tell 8 % apart
      t.flag = a > 0.3 || (SPARSE.has(t.mul) ? a > 0.1 && t.ccMatch : a > SCALED_LOG && (t.ccMatch || DENSE.has(t.mul)));
      if (t.flag) flagged++;
    }
    log(`pass ${pass + 1}: ${T.length} transitions, ${flagged} taken for scaled (${T.filter((t) => t.flag && t.ccMatch).length} with the input CC)`);
  }
  return { coef, spaces, info, transitions: T };
}

/* ---------------------------------------------------------------------------
   Output
   --------------------------------------------------------------------------- */

const r3 = (v) => Math.round(v * 1000) / 1000;
const sig4 = (v) => Number(v.toPrecision(4));

/** Rows of a surface's coefficients that some (Z, E) in range reaches, as {j0, c}. */
function trimmed(S, c, shell, Bref) {
  const { tx, ty, nx, ny } = S;
  const j0 = [], rows = [];
  const yLo = IN_W[shell] ? -Math.log10(1.3) : -Infinity;
  for (let i = 0; i < nx; i++) {
    // Z range of x basis function i, within 1..110
    const za = Math.max(1, Math.floor(Math.exp(tx[i]))), zb = Math.min(110, Math.ceil(Math.exp(tx[i + 4])));
    let yHi = -Infinity;
    if (za > 110 || zb < 1) { j0.push(0); rows.push([]); continue; }
    for (let Z = za; Z <= zb; Z++) yHi = Math.max(yHi, IN_W[shell] ? Math.log10(E_MAX / Bref(shell, Z)) : Math.log10(E_MAX));
    let a = ny, b = -1;
    for (let j = 0; j < ny; j++) {
      // support [ty[j], ty[j+4]] clamped to the domain
      const lo = Math.max(ty[j], ty[3]), hi = Math.min(ty[j + 4], ty[ny]);
      if (hi >= yLo && lo <= yHi) { a = Math.min(a, j); b = Math.max(b, j); }
    }
    j0.push(a <= b ? a : 0);
    rows.push(a <= b ? Array.from(c.slice(i * ny + a, i * ny + b + 1), r3) : []);
  }
  return { j0, c: rows };
}

function main() {
  const args = process.argv.slice(2);
  const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
  const archive = args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
  if (!archive) {
    console.error('usage: node scripts/gen-dose-icc.mjs <ICRP 107 ARCHIVE folder> [--atomic DIR] [--out FILE] [--points FILE]');
    process.exit(2);
  }
  const atomicDir = path.resolve(opt('--atomic', path.join(ROOT, 'resources/data/dose/atomic')));
  const out = path.resolve(opt('--out', path.join(ROOT, 'resources/data/dose/icc/icc.json')));
  const t0 = Date.now();
  const points = readArchive(archive);
  const bind = readBinding(atomicDir);
  console.log(`${points.length} gammas printed; binding energies for ${Object.keys(bind).length} elements from ${atomicDir}`);
  const fit = fitTable(points, bind, (s) => console.log(s));

  const pct = (x) => (100 * (10 ** x - 1)).toFixed(1);
  const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
  for (const mul of MUL_ORDER) {
    const row = SHELLS.map((s) => {
      const f = fit.info[`${mul} ${s}`];
      return f.n ? `${s} ${f.n}: ${pct(q(f.loo.map(Math.abs), 0.5))}/${pct(q(f.loo.map(Math.abs), 0.9))}%` : `${s} -`;
    });
    console.log(`${mul}  leave-one-out |error| median/90th: ${row.join('  ')}`);
  }

  // Edges y is measured from, K and L subshells, Z = 1..100 (beyond: the caller's own)
  const Zmax = Math.max(...Object.keys(bind).map(Number));
  // where the binding energies came from: the repository's folder, or a folder's name (no local paths in a public file)
  const binding = { source: path.relative(ROOT, atomicDir).startsWith('..') ? path.basename(atomicDir) : path.relative(ROOT, atomicDir) };
  for (const s of ['K', 'L1', 'L2', 'L3', 'M1', 'N1']) {
    binding[s] = [];
    for (let Z = 1; Z <= Zmax; Z++) binding[s].push(bind[Z]?.[s] !== undefined ? sig4(bind[Z][s]) : null);
  }
  // electrons in each group's s and p subshells, for the module's rule below Z_ANCHOR
  const occupancy = {};
  for (const g of SHELLS) {
    occupancy[g] = [];
    for (let Z = 1; Z <= Zmax; Z++) occupancy[g].push(Number(OCC_SUBSHELLS[g].reduce((n, s) => n + (bind.occupancy[Z]?.[s] || 0), 0).toFixed(3)));
  }
  const Bref = (shell, Z) => {
    const s = EDGE[shell];
    const v = binding[s][Math.min(Z, Zmax) - 1];
    if (v) return Z <= Zmax ? v : v * Math.exp(0.035 * (Z - Zmax));
    let z = Z; while (z <= Zmax && !binding[s][z - 1]) z++; // light atoms without the subshell: the first that has it
    return binding[s][z - 1];
  };
  const surfaces = {}, derived = {};
  for (const mul of MUL_ORDER) {
    if (PLAN[mul].offset) {
      derived[mul] = { from: PLAN[mul].base, offset: Object.fromEntries(SHELLS.map((s) => [s, r3(fit.info[`${mul} ${s}`].offset || 0)])) };
      continue;
    }
    surfaces[mul] = {};
    for (const shell of SHELLS) surfaces[mul][shell] = trimmed(IN_W[shell] ? fit.spaces.w : fit.spaces.u, fit.coef[`${mul} ${shell}`], shell, Bref);
  }
  const json = {
    source: 'Fitted to the internal-conversion coefficients EDISTR04 printed for every gamma transition of '
      + 'ICRP Publication 107 (supplementary data, ARCHIVE/OUTPUT): Rösel, Fries, Alder and Pauli (1978) for E1-E4 and M1-M4 '
      + 'at 30 <= Z <= 103, Band and Trzhaskovskaya for E5 and M5, Hager and Seltzer and Band et al. below Z = 30, as EDISTR04 applied them '
      + '(Endo, Yamaguchi and Eckerman, JAERI 1347, 2005). Made by scripts/gen-dose-icc.mjs.',
    method: 'log10 alpha = sum c[i][j] B_i(ln Z) B_j(y), cubic B-splines on the knots below extended by three at each end with the end spacing; '
      + 'y = log10(E / B_shell) for K, L1, L2, L3 (B from binding) and log10(E / keV) for M and N+. Penalised least squares on the printed '
      + 'values; E3, E4, M3, M4 as smooth differences to the linear extrapolation in multipole order of the two orders below, E5 and M5 '
      + 'as that extrapolation and a constant per shell (derived). Below lowZ.anchor and above the energies where a shell falls under '
      + '0.001 the module (resources/js/dose/ensdf-icc.js) continues the table by physics.',
    knots: KNOTS,
    shells: Object.fromEntries(SHELLS.map((s) => [s, IN_W[s] ? 'w' : 'u'])),
    binding,
    lowZ: { anchor: Z_ANCHOR, occupancy },
    surfaces,
    derived,
  };
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const text = JSON.stringify(json);
  fs.writeFileSync(out, text);
  console.log(`wrote ${out}: ${(text.length / 1024).toFixed(1)} kB, ${(Date.now() - t0) / 1000} s`);

  const pointsOut = opt('--points', null);
  if (pointsOut) {
    const inT = new Map();
    for (const t of fit.transitions) for (const g of t.copies) inT.set(g, t);
    fs.writeFileSync(pointsOut, JSON.stringify(points.map((g) => {
      const t = inT.get(g);
      return { ...g, fitted: !!t, scaled: t?.flag || false, med: t?.med, fit: t?.fit, loo: t?.loo, first: t ? t.copies[0] === g : undefined };
    })));
    console.log(`wrote ${pointsOut}`);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) main();
