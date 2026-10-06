#!/usr/bin/env node
/*
  The electron-capture table of the ENSDF processor (resources/js/dose/
  ensdf-capture.js), from an ENSDF release:

      node scripts/gen-dose-capture.mjs ~/Downloads/ensdf_260901.zip

  ENSDF gives most capture branches' K, L and M+ fractions, computed by the
  evaluators' program LOGFT (CK, CL, CM+ on the EC record's continuation).
  For an allowed branch of transition energy E they go as

      P_X  ~  (E - B_X)^2 a_X(Z),

  so dividing the neutrino energies out of the release's own values leaves
  the atomic factors relative to the K shell,

      rL(Z) = (P_L / P_K) (q_K / q_L1)^2,   rM(Z) = (P_M+ / P_K) (q_K / q_M1)^2,

  which the processor uses for the branches that come without them. Only
  allowed branches (no uniqueness flag) at least 30 keV and 30 % above the K
  edge are used; per Z the median, with the spread kept for reference.
  Binding energies are those of resources/data/dose/atomic (gen-dose-atomic.mjs).
  Writes resources/data/dose/capture.json.
*/
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { readDatasets, family, num, SYMBOL } from '../resources/js/dose/ensdf-decay.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const ENSDF = require(path.join(ROOT, 'resources/js/ensdf-parse.js'));

const src = process.argv[2];
if (!src) {
  console.error('usage: node scripts/gen-dose-capture.mjs <ensdf_YYMMDD.zip | folder of ensdf.NNN>');
  process.exit(2);
}

/** The texts of a release, from its zip or from a folder of ensdf.NNN files. */
function releaseTexts(p) {
  if (fs.statSync(p).isDirectory()) {
    return fs.readdirSync(p).filter((f) => /^ensdf\.\d{3}$/i.test(f)).sort().map((f) => fs.readFileSync(path.join(p, f), 'latin1'));
  }
  const bytes = new Uint8Array(fs.readFileSync(p));
  return ENSDF.zipEntries(bytes).filter((e) => ENSDF.isEnsdfName(e.name)).sort((a, b) => a.name.localeCompare(b.name)).map((e) => {
    const raw = bytes.subarray(e.offset, e.offset + e.csize);
    return new TextDecoder('latin1').decode(e.method === 0 ? raw : zlib.inflateRawSync(raw));
  });
}

const binding = new Map();
function bindingOf(Z) {
  if (binding.has(Z)) return binding.get(Z);
  const f = path.join(ROOT, 'resources/data/dose/atomic', `${SYMBOL[Z]}.json`);
  let b = null;
  if (fs.existsSync(f)) {
    const t = JSON.parse(fs.readFileSync(f, 'utf8'));
    const at = (s) => { const i = t.shells.indexOf(s); return i >= 0 ? t.E[i] / 1000 : NaN; };
    b = { K: at('K'), L1: at('L1'), M1: at('M1') };
  }
  binding.set(Z, b);
  return b;
}

const perZ = new Map();
let used = 0;
for (const text of releaseTexts(src)) {
  for (const ds of readDatasets(text)) {
    if (family(ds.mode) !== 'EC') continue;
    const P = ds.parents[0];
    const b = bindingOf(ds.Z);
    if (!P || !Number.isFinite(P.Q) || !b || !(b.K > 0)) continue;
    for (const lv of ds.levels) {
      for (const e of lv.feeds) {
        if (e.kind !== 'E' || e.UN) continue;
        const CK = num(e.cont.CK), CL = num(e.cont.CL), CM = num(e.cont['CM+']);
        if (!(CK > 0) || !(CL > 0)) continue;
        const Et = P.Q + (P.E || 0) - lv.E;
        const qK = Et - b.K, qL = Et - b.L1, qM = Et - (b.M1 || 0);
        if (!(qK > Math.max(30, 0.3 * b.K))) continue;
        if (!perZ.has(ds.Z)) perZ.set(ds.Z, { rL: [], rM: [] });
        const s = perZ.get(ds.Z);
        s.rL.push((CL / CK) * (qK / qL) ** 2);
        if (CM > 0) s.rM.push((CM / CK) * (qK / qM) ** 2);
        used++;
      }
    }
  }
}
const sorted = (a) => [...a].sort((x, y) => x - y);
const median = (a) => { const s = sorted(a); return s.length ? s[Math.floor(s.length / 2)] : null; };
const pct = (a, q) => { const s = sorted(a); return s.length > 4 ? +s[Math.floor(q * (s.length - 1))].toPrecision(4) : null; };
const table = {};
for (const [Z, s] of [...perZ].sort((p, q) => p[0] - q[0])) {
  table[Z] = { n: s.rL.length, rL: +median(s.rL).toPrecision(5), rM: s.rM.length ? +median(s.rM).toPrecision(5) : null, rL10: pct(s.rL, 0.1), rL90: pct(s.rL, 0.9) };
}
const id = /(\d{6})/.exec(path.basename(src))?.[1] || path.basename(src);
const out = {
  source: `ENSDF release ${id}: the CK, CL and CM+ values (LOGFT) of ${used} allowed electron-capture branches, divided by the squared neutrino energies with the binding energies of resources/data/dose/atomic; median per Z (rL10/rL90: 10th and 90th percentiles)`,
  table,
};
const file = path.join(ROOT, 'resources/data/dose/capture.json');
fs.writeFileSync(file, JSON.stringify(out));
console.log(`capture: ${Object.keys(table).length} elements from ${used} branches -> ${path.relative(ROOT, file)} (${fs.statSync(file).size} bytes)`);
