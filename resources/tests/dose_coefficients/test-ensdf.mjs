#!/usr/bin/env node
/*
  The ENSDF processor against ICRP Publication 107, on ICRP 107's own
  inputs: every nuclide EDISTR04 made from the archived ENSDF data sets,
  made again by resources/js/dose/ensdf-*.js the way EDISTR04 made it
  (ensdf-icrp107.mjs), and held against ICRP-07.RAD, the index and
  EDISTR04's printout.

      node resources/tests/dose_coefficients/test-ensdf.mjs [--list]

  Needs your copy of ICRP 107's supplementary data (ICRP107=... if it is not
  in ~/Downloads/ICRP/icrp 107/) and the 1991 atomic tables in local/eadl1991
  (README); skipped without them. --list prints every nuclide outside the
  tolerances. About 10 s.
*/
import { have, emulate, PATHS } from './ensdf-icrp107.mjs';

if (!have()) {
  console.log(`skipped: needs ICRP 107's ARCHIVE (${PATHS.icrp107}) and the 1991 atomic tables (${PATHS.eadl1991}); see README.md`);
  process.exit(0);
}
const list = process.argv.includes('--list');
let pass = 0, fail = 0;
function check(label, ok, detail = '') {
  if (ok) { pass++; console.log(`ok    ${label}`); } else { fail++; console.log(`FAIL  ${label}${detail ? `\n      ${detail}` : ''}`); }
}

const t0 = Date.now();
const { results } = emulate();
console.log(`${results.length} parent states processed in ${Date.now() - t0} ms`);
// EDISTR04 made some outputs again in 2007-2008 from inputs revised after
// they were archived (F-17's has a gamma ray the archived input lacks): those
// are left out of the comparisons.
const run2005 = results.filter((r) => r.out?.date === '02-11-2005');

/* Beta branches: shape order and mean energy, against EDISTR04's own line for the same end point. */
{
  let same = 0, n = 0, worst = 0, within = 0;
  const off = [];
  for (const r of run2005) {
    const refs = r.out.seei.filter((l) => l.code === 4 || l.code === 5);
    for (const b of r.rec.betaLines) {
      const ref = refs.find((l) => l.code === (b.positron ? 4 : 5) && Math.abs(l.Emax - b.E0) <= Math.max(2e-5, 2e-4 * b.E0));
      if (!ref) continue;
      n++;
      if (b.n === ref.x) same++; else off.push(`${r.name} E0 ${b.E0.toFixed(4)} n ${b.n} vs ${ref.x}`);
      if (b.n <= 1) { const d = Math.abs(b.mean / ref.E - 1); worst = Math.max(worst, d); if (d <= 1e-4) within++; }
    }
  }
  check(`beta shapes: ${same} of ${n} branches take EDISTR04's (allowed, first, second or third unique)`, same === n, off.slice(0, 5).join('; '));
  check(`beta mean energies (allowed and first unique): ${within} within 1e-4 of EDISTR04's, worst ${worst.toExponential(1)}`, worst < 1e-3);
}

/* Energy per decay by kind of radiation, against ICRP-07.RAD. */
const KIND = { G: [1], X: [2], AQ: [3], 'B+': [4], 'B-': [5], IE: [6], AE: [7], A: [8], AR: [9] };
function sums(lines, ref) {
  const s = {};
  for (const l of lines) {
    let k = ref ? Object.keys(KIND).find((c) => KIND[c].includes(l.code)) : l.type;
    if (ref && ['PG', 'DG', 'DB'].includes(l.tag)) k = null;
    if (!k) continue;
    let E = ref ? l.E : l.E / 1000;
    // Conversion electrons in ICRP 107's way: M at E - B(M3), N+ at E.
    if (!ref && l.type === 'IE' && /^M/.test(l.shell) && l.BM3 > 0) E = (l.gamma - l.BM3) / 1000;
    else if (!ref && l.type === 'IE' && /^[NOPQ]/.test(l.shell)) E = l.gamma / 1000;
    (s[k] ||= { Y: 0, EY: 0 }).EY += l.Y * E;
    s[k].Y += l.Y;
  }
  return s;
}
const dev = {};
for (const r of run2005) {
  const a = sums(r.res.lines, false), b = sums(r.refRad, true);
  for (const k of ['G', 'A', 'AR', 'AQ', 'IE', 'X', 'AE']) {
    const x = a[k]?.EY || 0, y = b[k]?.EY || 0;
    if (!(x || y)) continue;
    (dev[k] ||= []).push([r.name, y ? x / y - 1 : Infinity]);
  }
}
const q = (arr, p) => { const s = arr.map(([, d]) => Math.abs(d)).sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
const share = (arr, t) => arr.filter(([, d]) => Math.abs(d) <= t).length;
const outside = (k, t) => dev[k].filter(([, d]) => Math.abs(d) > t).sort((p, r) => Math.abs(r[1]) - Math.abs(p[1])).map(([n, d]) => `${n} ${(d * 100).toFixed(2)} %`);
check(`alpha particles: all ${dev.A.length} within 1e-3`, share(dev.A, 1e-3) === dev.A.length, outside('A', 1e-3).join(', '));
check(`alpha recoils: all ${dev.AR.length} within 1e-3`, share(dev.AR, 1e-3) === dev.AR.length, outside('AR', 1e-3).join(', '));
check(`annihilation photons: all ${dev.AQ.length} within 1e-3`, share(dev.AQ, 1e-3) === dev.AQ.length, outside('AQ', 1e-3).join(', '));
check(`gamma rays: ${share(dev.G, 1e-3)} of ${dev.G.length} within 1e-3, ${share(dev.G, 1e-2)} within 1e-2`, share(dev.G, 1e-2) >= dev.G.length - 3, outside('G', 1e-2).join(', '));
check(`conversion electrons: ${share(dev.IE, 1e-3)} of ${dev.IE.length} within 1e-3, median ${q(dev.IE, 0.5).toExponential(1)}`, share(dev.IE, 1e-3) >= 0.97 * dev.IE.length);
check(`X-rays: median ${q(dev.X, 0.5).toExponential(1)}, 90th percentile ${q(dev.X, 0.9).toExponential(1)}, ${share(dev.X, 1e-2)} of ${dev.X.length} within 1e-2`, q(dev.X, 0.5) < 1e-3 && q(dev.X, 0.9) < 1e-2);
check(`Auger electrons: median ${q(dev.AE, 0.5).toExponential(1)}, 90th percentile ${q(dev.AE, 0.9).toExponential(1)}, ${share(dev.AE, 1e-2)} of ${dev.AE.length} within 1e-2`, q(dev.AE, 0.5) < 1e-3 && q(dev.AE, 0.9) < 1e-2);
if (list) for (const k of ['G', 'IE', 'X', 'AE']) console.log(`      ${k} beyond 1e-2: ${outside(k, 1e-2).join(', ')}`);

/* Where the decays go, against the index (ICRP's hand edits applied). */
{
  let n = 0, same = 0;
  const off = [];
  for (const r of run2005) {
    const mine = new Map(r.rec.d);
    let ok = true;
    for (const [d, b] of r.ref.d) {
      if (d === 'SF') continue;
      if (Math.abs((mine.get(d) || 0) - b) > 1e-3 * Math.max(1, b) + 1e-6) ok = false;
    }
    n++;
    if (ok) same++; else off.push(r.name);
  }
  // Isomers fed through cascades of incomplete schemes (Sb-131 to Te-131m, Ag-115 to Cd-115m: the latter's level is not in the archived input).
  check(`daughters and branching: ${same} of ${n} as the index has them, within 1e-3`, same >= n - 15, off.join(', '));
}
console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
