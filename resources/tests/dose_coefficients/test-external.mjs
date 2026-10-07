#!/usr/bin/env node
/*
  dose_coefficients.html: external exposure (external.js), in Node.

      node resources/tests/dose_coefficients/test-external.mjs [--verbose]

  What needs no outside data:
    - the monoenergetic data: every geometry and age, positive where the
      reports give a value, the photon interpolant through its points
    - the effective dose's weights add up to one in both systems (and FGR 12's
      H_E's), so a uniform dose is the effective dose
    - a photon line at a tabulated energy gives the table's value; below
      10 keV nothing; electrons only to the skin
    - progeny in equilibrium: secular and transient ratios from the decay
      data, members that never are, and the parts and shares adding up
    - with ENSDF decay data the same nuclides come out close
    - pinned results, so that an unintended change shows

  What compares with the reports' own coefficients needs local/fgr15.json
  and local/fgr12.json (make-local-fixtures.py --fgr15 --fgr12): every
  nuclide, geometry, age and tissue, and the effective dose (FGR 15) or
  effective dose equivalent (FGR 12). Without them that part is skipped.

  Exit status is 0 when every check passes.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const DATA = path.join(ROOT, 'resources/data/dose');
const JS = path.join(ROOT, 'resources/js/dose');
const VERBOSE = process.argv.includes('--verbose');

const { External, effective, equilibrium, externalRun, externalForms, GEOMETRIES, PHANTOM_OF_AGE } = await import(path.join(JS, 'external.js'));
const { loadSystem, fetchIO } = await import(path.join(JS, 'data.js'));
const { buildChain } = await import(path.join(JS, 'chain.js'));
const { catalog60, catalog103 } = await import(path.join(JS, 'catalog.js'));

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok || !detail ? '' : `: ${detail}`}`);
  if (!ok) failures.push(label);
}
const near = (a, b, tol) => Math.abs(a / b - 1) <= tol;
const io = {
  json: async (p) => JSON.parse(fs.readFileSync(path.join(DATA, p), 'utf8')),
  bin: async (p) => { const b = fs.readFileSync(path.join(DATA, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); },
};
const folderIO = (dir) => ({ json: async (p) => JSON.parse(fs.readFileSync(path.join(dir, p), 'utf8')) });
const X = { 60: new External(await io.json('external/fgr12.json')), 103: new External(await io.json('external/fgr15.json')) };
const D = { 60: await loadSystem('60', io), 103: await loadSystem('103', io) };

/* ---- the data ------------------------------------------------------------------- */
for (const [sys, x] of Object.entries(X)) {
  const d = x.data;
  const bad = [];
  for (const g of GEOMETRIES) for (const a of d.ages) {
    const rows = d.photon[g]?.[a];
    if (!rows || rows.length !== d.tissues.length || rows.some((r) => r.length !== d.energies.length || r.some((v) => !(v >= 0)))) bad.push(`${g}/${a}`);
    else if (rows.some((r) => !(r[r.length - 1] > 0))) bad.push(`${g}/${a} zero at 5 MeV`);
  }
  check(`ICRP ${sys}: the ${sys === '60' ? 'FGR 12' : 'FGR 15'} data have every geometry and age, ${d.tissues.length} tissues at ${d.energies.length} energies`, !bad.length, bad.join(', '));
  // The interpolant passes through the table.
  const R = x.response('air', 'adult');
  const off = [];
  d.energies.forEach((E, k) => R.tissues.forEach((t, i) => { const v = d.photon.air.adult[i][k]; if (v > 0 && !near(t.photon.at(E), v, 1e-12)) off.push(`${d.tissues[i]} ${E}`); }));
  check(`ICRP ${sys}: the photon interpolant passes through every tabulated value`, !off.length, off.slice(0, 5).join(', '));
  // Weights: a uniform dose is the effective dose.
  const ones = new Float64Array(d.tissues.length).fill(1e-15);
  const eff = effective(sys, d.tissues, ones);
  check(`ICRP ${sys}: the tissue weighting factors add up to one`, near(eff.E, 1e-15, 1e-12) && (sys === '103' || near(eff.HE, 1e-15, 1e-12)), `E ${eff.E}, HE ${eff.HE}`);
  // A single photon of 1 MeV gives the table's 1 MeV values; one of 8 keV nothing.
  const k1 = d.energies.indexOf(1);
  const one = x.dose({ r: { p: [[1, 1]] } }, 'surface', 'adult');
  check(`ICRP ${sys}: one 1 MeV photon per decay gives the table's 1 MeV column`, d.tissues.every((t, i) => near(one.h[i], d.photon.surface.adult[i][k1], 1e-12)));
  const low = x.dose({ r: { p: [[0.008, 1]], e: [[0.05, 1]] } }, 'air', 'adult');
  const skin = d.tissues.indexOf('Skin');
  check(`ICRP ${sys}: photons under 10 keV and electrons under the skin curve's threshold give nothing`, low.h.every((v) => v === 0));
  const el = x.dose({ r: { e: [[1, 1]] } }, 'water', 'adult');
  check(`ICRP ${sys}: a 1 MeV conversion electron reaches the skin only (its bremsstrahlung is not counted)`, el.h.every((v, i) => (i === skin ? v > 0 : v === 0)));
}

/* ---- catalogues ----------------------------------------------------------------- */
const cat = { 60: catalog60(D[60]), 103: catalog103(D[103]) };
check('the ICRP 60 catalogue has external exposure for every ICRP 38 radionuclide (838)', cat[60].nuclides.length === 838 && cat[60].nuclides.every((n) => n.external?.length === 7));
check('the ICRP 103 catalogue has it for every ICRP 107 radionuclide (1252), Kr-85 and N-16 by that route only',
  cat[103].nuclides.length === 1252 && cat[103].nuclides.every((n) => n.external?.length === 7)
  && ['Kr-85', 'N-16'].every((k) => { const n = cat[103].nuclides.find((x) => x.name === k); return n && !n.ingestion.length && !n.inhalation.length && !n.injection.length; }));
check('the geometries in order, air the default', externalForms('103').map((f) => f.key).join() === GEOMETRIES.join() && externalForms('103')[0].default);

/* ---- progeny in equilibrium --------------------------------------------------------- */
const idx = D[103].index;
const ratioOf = (parent, member) => { const c = buildChain(idx, parent, { cutoff: 0 }); return equilibrium(c).ratio[c.members.findIndex((m) => m.name === member)]; };
const lam = (n) => Math.LN2 / idx[n].T;
const br = (p, d) => idx[p].d.find(([x]) => x === d)[1];
check('Cs-137: Ba-137m at its branching times λ/(λ − λP), 0.944', near(ratioOf('Cs-137', 'Ba-137m'), br('Cs-137', 'Ba-137m') * lam('Ba-137m') / (lam('Ba-137m') - lam('Cs-137')), 1e-12)
  && near(ratioOf('Cs-137', 'Ba-137m'), 0.944, 1e-3));
check('Mo-99: Tc-99m in transient equilibrium, 0.965; Tc-99 (longer-lived) never', near(ratioOf('Mo-99', 'Tc-99m'), 0.9654, 1e-3) && ratioOf('Mo-99', 'Tc-99') === null);
check('Zr-95: Nb-95 in transient equilibrium at 2.2 Bq per Bq', near(ratioOf('Zr-95', 'Nb-95'), 2.205, 2e-3));
check('U-238: the whole series in secular equilibrium (Ra-226, Pb-210, Po-210 at 1)', ['Ra-226', 'Pb-210', 'Po-210'].every((m) => near(ratioOf('U-238', m), 1, 1e-4)));
check('Rn-222: Pb-210 (22 y) and what comes after it never', ['Pb-210', 'Bi-210', 'Po-210'].every((m) => ratioOf('Rn-222', m) === null) && near(ratioOf('Rn-222', 'Bi-214'), 1.009, 2e-3));
check('Pu-241: Am-241 (432 y) never, and what follows from it', ratioOf('Pu-241', 'Am-241') === null && ratioOf('Pu-241', 'Np-237') === null);

/* ---- a calculation: parts and shares add up ---------------------------------------- */
async function run(sys, nuc, geo, ages, data = D[sys]) {
  const chain = await data.prepare(nuc);
  return externalRun(X[sys], data, chain, sys, geo, ages);
}
{
  const [o] = await run('103', 'Cs-137', 'surface', [7300]);
  const parts = o.parts.photon.E + o.parts.brems.E + o.parts.electron.E;
  const shares = o.members.reduce((a, m) => a + (m.share?.E || 0), 0);
  check('Cs-137 on the ground: photons, bremsstrahlung and electrons add up to e; the members’ shares to e with progeny', near(parts, o.E, 1e-12) && near(shares, o.progeny.E, 1e-12));
  const [b] = await run('103', 'Ba-137m', 'surface', [7300]);
  check('... and e with progeny is e(Cs-137) + 0.944 e(Ba-137m)', near(o.progeny.E, o.E + o.members[1].ratio * b.E, 1e-12));
  const [u] = await run('60', 'U-238', 'soil15', [7300]);
  const s60 = u.members.reduce((a, m) => a + (m.share?.E || 0), 0), h60 = u.members.reduce((a, m) => a + (m.share?.HE || 0), 0);
  check('U-238 in the ICRP 60 system: the shares add up to e and to H_E with the progeny, under the splitting rule', near(s60, u.progeny.E, 1e-12) && near(h60, u.progeny.HE, 1e-12));
  const rem = (x) => Object.values(x.remainderShares).reduce((a, v) => a + v, 0) / x.H.Remainder;
  check('... and the remainder tissues’ parts add up to the remainder, alone and with the progeny, in both systems',
    [u, u.progeny, o, o.progeny].every((x) => near(rem(x), 1, 1e-12)));
  let threw = '';
  try { await run('60', 'Co-60', 'air', [100]); } catch (e) { threw = e.message; }
  check('the ICRP 60 system has the adult only', /adult only/.test(threw), threw);
  const ages = await run('103', 'Co-60', 'air', [100, 365, 1825, 3650, 5475, 7300]);
  check('Co-60 in air: e falls with age, newborn to adult', ages.every((x, i) => i === 0 || x.E <= ages[i - 1].E * 1.001), ages.map((x) => x.E.toExponential(3)).join(' '));
  const soils = await Promise.all(['soil1', 'soil5', 'soil15', 'soilInf'].map(async (g) => (await run('103', 'Co-60', g, [7300]))[0].E));
  check('Co-60 in soil: e grows with the depth contaminated', soils.every((v, i) => i === 0 || v > soils[i - 1]), soils.map((v) => v.toExponential(3)).join(' '));
  const [y] = await run('103', 'Y-90', 'air', [7300]);
  check('Y-90 in air (a pure beta emitter): the skin’s dose is nearly all electrons, the other tissues’ bremsstrahlung', y.parts.electron.skin / y.H.Skin > 0.99 && y.parts.photon.E < 1e-3 * y.parts.brems.E,
    `skin ${(y.parts.electron.skin / y.H.Skin).toFixed(4)}, photons/bremsstrahlung ${(y.parts.photon.E / y.parts.brems.E).toExponential(2)}`);
}

/* ---- decay data from ENSDF ----------------------------------------------------------- */
{
  const dir = path.join(DATA, 'ensdf');
  const rel = JSON.parse(fs.readFileSync(path.join(dir, 'index.json'), 'utf8')).releases[0];
  const ens = await loadSystem('103', io, folderIO(path.join(dir, rel.id)));
  const out = [];
  for (const n of ['Cs-137', 'Co-60', 'I-131', 'Am-241', 'Kr-85']) {
    const [a] = await run('103', n, 'air', [7300]);
    const [b] = await run('103', n, 'air', [7300], ens);
    out.push([n, b.E / a.E]);
  }
  check(`with ${rel.label} the dose rates of Cs-137, Co-60, I-131, Am-241 and Kr-85 stay within 5 % of ICRP 107's`, out.every(([, q]) => near(q, 1, 0.05)), out.map(([n, q]) => `${n} ${q.toFixed(3)}`).join(', '));
}

/* ---- pinned ------------------------------------------------------------------------ */
// As this page calculates them (2026-10-07), so that a change shows: e of the
// nuclide alone, adult, Sv s-1 per Bq m-3 (m-2 on the ground).
const PINNED = [['103', 'Cs-137', 'surface', 3.0104e-18], ['103', 'Co-60', 'air', 1.1916e-13], ['103', 'Kr-85', 'air', 2.4001e-16], ['60', 'Co-60', 'soilInf', 8.2455e-17], ['60', 'I-131', 'water', 3.6761e-17]];
for (const [sys, n, g, want] of PINNED) {
  const [o] = await run(sys, n, g, [7300]);
  check(`pinned: ICRP ${sys} ${n} ${g} adult e = ${want}`, near(o.E, want, 1e-4), o.E.toPrecision(5));
}

/* ---- against the reports ---------------------------------------------------------------- */
const NUCCOL = { Esophagus: 'Esophagu', 'ET-region': 'ET-regio', 'B-Surface': 'B-Surfac' };
function compare(sys, ref) {
  const x = X[sys], data = D[sys];
  const stats = { all: [], E: [] }, worst = [];
  for (const g of GEOMETRIES) for (const a of x.ages) {
    const table = sys === '60' ? ref.geometries[g] : ref.geometries[g][a];
    const col = Object.fromEntries(table.columns.map((c, i) => [c, i]));
    for (const [nuc, vals] of Object.entries(table.rows)) {
      let em;
      try { em = data.emissions(nuc); } catch { em = null; }
      if (!em) continue;
      const d = x.dose(em, g, a);
      x.tissues.forEach((t, i) => {
        const v = vals[col[sys === '60' && t === 'Esophagus' ? 'Esophagu' : NUCCOL[t] || t]];
        if (v > 0) stats.all.push(d.h[i] / v);
      });
      const eff = effective(sys, x.tissues, d.h);
      const v = vals[col[sys === '60' ? 'H_E' : 'e']], mine = sys === '60' ? eff.HE : eff.E;
      if (v > 0) { stats.E.push(mine / v); worst.push([Math.abs(Math.log(mine / v)), `${nuc} ${g} ${a} ${(mine / v).toFixed(3)}`]); }
    }
  }
  const within = (qs, tol) => qs.filter((q) => Math.abs(q - 1) <= tol).length / qs.length;
  return { stats, within, worst: worst.sort((p, q) => q[0] - p[0]).slice(0, 8).map((w) => w[1]) };
}
for (const [sys, file, name, q] of [['103', 'fgr15.json', 'FGR 15', 'e'], ['60', 'fgr12.json', 'FGR 12', 'H_E']]) {
  const f = path.join(HERE, 'local', file);
  if (!fs.existsSync(f)) { console.log(`skip  ${name}: no local/${file} (make-local-fixtures.py --${file.slice(0, 5)})`); continue; }
  const ref = JSON.parse(fs.readFileSync(f, 'utf8'));
  // Every element of the reports' nuclides.
  const els = new Set(Object.keys((sys === '60' ? ref.geometries.air : ref.geometries.air.adult).rows).map((n) => n.split('-')[0]));
  for (const n of Object.keys(sys === '60' ? ref.geometries.air.rows : ref.geometries.air.adult.rows)) if (D[sys].index[n]) await D[sys].prepare(n).catch(() => {});
  const r = compare(sys, ref);
  const pct = (qs, tol) => `${(100 * r.within(qs, tol)).toFixed(2)} %`;
  console.log(`      ${name}: ${q} ${r.stats.E.length} values, within 1 % ${pct(r.stats.E, 0.01)}, 2 % ${pct(r.stats.E, 0.02)}, 5 % ${pct(r.stats.E, 0.05)}; `
    + `tissues ${r.stats.all.length} values, within 1 % ${pct(r.stats.all, 0.01)}, 2 % ${pct(r.stats.all, 0.02)}, 5 % ${pct(r.stats.all, 0.05)} (${els.size} elements)`);
  if (VERBOSE) console.log(`      worst ${q}: ${r.worst.join('; ')}`);
  const [minE, minAll] = sys === '103' ? [0.997, 0.995] : [0.995, 0.99];
  if (sys === '60' && ref.monoE) {
    // FGR 12's effective dose (ICRP 60) of single photon energies, by the page's weighting of its organs.
    const d = X[60].data, off = [];
    for (const g of GEOMETRIES) d.energies.forEach((E, k) => {
      const q = effective('60', d.tissues, d.tissues.map((t, i) => d.photon[g].adult[i][k])).E / ref.monoE[g][k];
      if (!near(q, 1, 0.01)) off.push(`${g} ${E} MeV ${q.toFixed(3)}`);
    });
    check('FGR 12’s effective dose per photon at its 12 energies in 7 geometries, from its organs by the page’s ICRP 60 weighting, within 1 %', !off.length, off.join(', '));
  }
  check(`${name}: ${q} of every nuclide, geometry and age within 1 % for ${100 * minE} % of them`, r.within(r.stats.E, 0.01) >= minE, pct(r.stats.E, 0.01));
  check(`${name}: every tissue's dose rate within 1 % for ${100 * minAll} % of the values`, r.within(r.stats.all, 0.01) >= minAll, pct(r.stats.all, 0.01));
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) { console.log('failed:', failures.join('; ')); process.exit(1); }
