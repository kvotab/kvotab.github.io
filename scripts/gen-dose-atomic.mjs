#!/usr/bin/env node
/*
  Build the atomic relaxation tables that resources/js/dose/atomic-relax.js
  reads: per element, the binding energies of its subshells and the
  probabilities of the radiative (X-ray) and non-radiative (Auger,
  Coster-Kronig) transitions that fill a vacancy in each of them.

      node scripts/gen-dose-atomic.mjs <atomic_relax.zip> [out-dir]

  The zip is an ENDF-6 atomic relaxation sub-library as NNDC distributes it,
  one atom-ZZZ_Xx_000.endf per element (Z = 1-100), each with one section
  MF28/MT533:

    HEAD  [ZA, AWR, 0, 0, NSS, 0]
    NSS × LIST [SUBI, 0, 0, 0, NW, NTR]
          EBI (binding energy, eV), ELN (electrons), 0, 0, 0, 0,
          NTR × (SUBJ, SUBK, ETR (eV), FTR (probability), 0, 0)

  SUBK = 0 makes a radiative transition. Subshells are numbered as the
  photo-ionisation MTs 534-572 less 533: 1 K, 2-4 L1-L3, 5-9 M1-M5,
  10-16 N1-N7, 17-25 O1-O9, 26-36 P1-P11, 37-39 Q1-Q3 (tellurium has
  1-14 and 17-19, uranium 1-23, 26-30 and 37; the binding energies say so).
  Numbers are written as ENDF does ("1.00000-5"), or with a D or E exponent
  ("3.86150D-4" in ENDF/B-VIII.0), or plainly (".252440000").

  ETR is not kept. ENDF/B-VIII.0 (EPICS2017) took new binding energies but
  kept the 1991 transition energies, so its ETR no longer equal the
  differences of its own binding energies (Te K-L3: ETR 27465.3 eV, new
  K - L3 = 27473 eV); the module takes every line energy from the binding
  energies, which is also what keeps the emitted energy equal to the
  vacancy's. In the 1991 library ETR and the differences agree to 0.05 eV,
  except for transitions EADL lists with ETR = 0 because its binding
  energies put them below threshold; those stay in the tables (the module
  moves their vacancies on without emitting an electron, as EDISTR04 did).

  Writes <out-dir>/<symbol>.json for each element and <out-dir>/index.json.
  The default out-dir is resources/data/dose/atomic/, for ENDF/B-VIII.0; the
  1991 library (ENDF/B-VII.1, what ICRP 107 used) is for comparisons and
  goes elsewhere. Each element file:

    { Z, symbol,
      shells: ["K", "L1", ...]   subshells in designator order
      E:      [eV, ...]          binding energies
      n:      [...]              electrons in the subshell (ground state)
      x:      [[j, p, ...], ...] per subshell: radiative transitions as
                                 pairs (position of the subshell the vacancy
                                 moves to, probability)
      a:      [[j, k, p, ...]]   per subshell: non-radiative transitions as
                                 triples (the two new vacancies, probability)
    }

  Numbers are rounded to 6 significant figures (the libraries' own
  precision). The script checks that every designator is a subshell of the
  element, that each subshell's probabilities add up to 1, that vacancies
  only ever move to less bound subshells (so the cascade has an order), and
  that each transition falls in one of EDISTR04's line groups (JAERI 1347
  Appendix A), and fails otherwise.
*/
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { SUBSHELLS, xIndex, augerIndex } from '../resources/js/dose/atomic-relax.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const { zipEntries } = require(path.join(ROOT, 'resources/js/ensdf-parse.js'));

const [zipPath, outArg] = process.argv.slice(2);
if (!zipPath) {
  console.error('usage: node scripts/gen-dose-atomic.mjs <atomic_relax.zip> [out-dir]');
  process.exit(2);
}
const OUT = path.resolve(outArg || path.join(ROOT, 'resources/data/dose/atomic'));

/** An ENDF number: "1.00000-5", "3.86150D-4", ".252440000", blank -> 0. */
function num(s) {
  const t = s.trim().replace(/[dD]/, 'e');
  if (!t) return 0;
  const m = /^([-+]?[0-9.]+)([-+]\d+)$/.exec(t);
  const v = m ? Number(`${m[1]}e${m[2]}`) : Number(t);
  if (!Number.isFinite(v)) throw new Error(`not a number: "${s}"`);
  return v;
}

/** The MF28/MT533 section of one ENDF file. */
function readMF28(text) {
  const rows = [];
  for (const l of text.split(/\r?\n/)) {
    if (l.length >= 75 && Number(l.slice(70, 72)) === 28 && Number(l.slice(72, 75)) === 533) {
      rows.push([0, 1, 2, 3, 4, 5].map((k) => l.slice(11 * k, 11 * k + 11)));
    }
  }
  if (!rows.length) throw new Error('no MF28/MT533 section');
  let r = 0;
  const head = rows[r++].map(num);
  const shells = [];
  for (let s = 0; s < head[4]; s++) {
    const c = rows[r++].map(num);
    const [subi, nw, ntr] = [c[0], c[4], c[5]];
    const v = [];
    while (v.length < nw) for (const f of rows[r++]) if (v.length < nw) v.push(num(f));
    const tr = [];
    for (let t = 0; t < ntr; t++) tr.push({ j: v[6 + 6 * t], k: v[7 + 6 * t], p: v[9 + 6 * t] });
    shells.push({ subi, E: v[0], n: v[1], tr });
  }
  return { Z: Math.round(head[0] / 1000), shells };
}

/** 6 significant figures, written as briefly as JSON allows. */
function fmt(v) {
  if (v === 0) return '0';
  const x = Number(v.toPrecision(6));
  const a = String(x), b = x.toExponential().replace('e+', 'e');
  return b.length < a.length ? b : a;
}

function convert(raw, symbol) {
  const where = `${symbol} (Z ${raw.Z})`;
  const pos = new Map(raw.shells.map((s, i) => [s.subi, i]));
  const names = raw.shells.map((s) => {
    const name = SUBSHELLS[s.subi - 1];
    if (!name) throw new Error(`${where}: subshell designator ${s.subi}`);
    return name;
  });
  const x = [], a = [];
  let forbidden = 0;
  raw.shells.forEach((s, i) => {
    const xi = [], ai = [];
    let sum = 0;
    for (const t of s.tr) {
      const j = pos.get(t.j), k = t.k ? pos.get(t.k) : null;
      if (j === undefined || k === undefined) throw new Error(`${where}: ${names[i]} -> ${t.j}/${t.k}, not a subshell of the element`);
      const Ej = raw.shells[j].E, Ek = k === null ? 0 : raw.shells[k].E;
      // vacancies move outwards; equal binding energies (L2, L3 of Mg-Si in EPICS2017) are the limit
      if (Ej > s.E || Ek > s.E) throw new Error(`${where}: ${names[i]} -> ${names[j]} ${k === null ? '' : names[k]} moves a vacancy inwards`);
      if (s.E - Ej - Ek <= 0) forbidden++;
      if (k === null) {
        if (xIndex(names[i], names[j]) === undefined) throw new Error(`${where}: X-ray ${names[i]}-${names[j]} has no EDISTR04 index`);
        xi.push(j, t.p);
      } else {
        if (augerIndex(names[i], names[j], names[k]) === undefined) throw new Error(`${where}: Auger ${names[i]}-${names[j]}${names[k]} has no EDISTR04 group`);
        ai.push(j, k, t.p);
      }
      sum += t.p;
    }
    if (s.tr.length && Math.abs(sum - 1) > 1e-5) throw new Error(`${where}: ${names[i]} probabilities add up to ${sum}`);
    x.push(xi); a.push(ai);
  });
  const list = (arr, per) => `[${arr.map((v, q) => (q % per === per - 1 ? fmt(v) : String(v))).join(',')}]`;
  const json = `{"Z":${raw.Z},"symbol":${JSON.stringify(symbol)},`
    + `"shells":${JSON.stringify(names)},`
    + `"E":[${raw.shells.map((s) => fmt(s.E)).join(',')}],`
    + `"n":[${raw.shells.map((s) => fmt(s.n)).join(',')}],`
    + `"x":[${x.map((l) => list(l, 2)).join(',')}],`
    + `"a":[${a.map((l) => list(l, 3)).join(',')}]}\n`;
  const transitions = raw.shells.reduce((acc, s) => acc + s.tr.length, 0);
  return { json, transitions, forbidden };
}

const bytes = new Uint8Array(fs.readFileSync(zipPath));
const entries = zipEntries(bytes)
  .map((e) => ({ ...e, m: /atom-(\d{3})_([A-Za-z]{1,2})_\d+\.endf$/.exec(e.name) }))
  .filter((e) => e.m)
  .sort((p, q) => Number(p.m[1]) - Number(q.m[1]));
if (!entries.length) {
  console.error(`${zipPath}: no atom-ZZZ_Xx_000.endf files`);
  process.exit(1);
}
fs.mkdirSync(OUT, { recursive: true });
const elements = [];
let total = 0, nTr = 0, nForb = 0;
for (const e of entries) {
  const raw = e.method === 0 ? bytes.subarray(e.offset, e.offset + e.csize) : zlib.inflateRawSync(bytes.subarray(e.offset, e.offset + e.csize));
  const data = readMF28(new TextDecoder('latin1').decode(raw));
  const symbol = e.m[2];
  if (data.Z !== Number(e.m[1])) throw new Error(`${e.name}: ZA says Z ${data.Z}`);
  const { json, transitions, forbidden } = convert(data, symbol);
  fs.writeFileSync(path.join(OUT, `${symbol}.json`), json);
  elements.push(symbol);
  total += json.length; nTr += transitions; nForb += forbidden;
}
const index = {
  source: path.basename(zipPath),
  elements,
  note: 'MF28/MT533 of the ENDF-6 atomic relaxation sub-library; binding energies (eV), occupancies and transition probabilities, 6 significant figures',
};
fs.writeFileSync(path.join(OUT, 'index.json'), `${JSON.stringify(index)}\n`);
console.log(`${path.basename(zipPath)}: Z ${entries[0].m[1] * 1}-${entries[entries.length - 1].m[1] * 1}, ${nTr} transitions (${nForb} below threshold by the binding energies)`);
console.log(`wrote ${elements.length} element files to ${path.relative(process.cwd(), OUT) || '.'}: ${(total / 1e6).toFixed(2)} MB`);
