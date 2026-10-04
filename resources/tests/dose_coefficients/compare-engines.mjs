#!/usr/bin/env node
/*
  dose_coefficients.html: two versions of the engines, value for value.

  For a change to how the engine calculates. Copy the engine as it was first
  (resources/js/dose and resources/js/ode, side by side in one folder), make
  the change, then

      node resources/tests/dose_coefficients/compare-engines.mjs OLD/dose [SHARD NSHARDS [EVERY]] [--tol X]

  runs every EVERYth nuclide of the ICRP 103 catalogue (11 by default; every
  form of every route) and every third of that in the ICRP 60 one, at the six
  ages, with both, and compares E, the dose to every target and tissue and the
  transformations in every source region. Shards split the cases among
  processes (node ... OLD/dose 0 4 & node ... OLD/dose 1 4 & ...).

  The last line counts the values that differ at all and gives the largest
  relative differences: of E; of the tissue doses that are at least 10^-3 of
  the largest one; of the numbers of transformations that are at least 10^-6
  of all. A change for speed alone should differ nowhere (the faster matrix of
  solve.js, 2026-10-03: 708,294 values in 544 cases, none differing); a change
  to how the dose is integrated, by about the tolerance of the integrator
  (rtol 1e-6) -- --tol sets how much E may differ for the exit status to be 0.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const DATA = path.join(ROOT, 'resources/data/dose');
const NEW = path.join(ROOT, 'resources/js/dose');
const args = process.argv.slice(2);
const tolAt = args.indexOf('--tol');
const TOL = tolAt >= 0 ? Number(args[tolAt + 1]) : 0;
if (tolAt >= 0) args.splice(tolAt, 2);
const [OLD, shardArg, nArg, everyArg] = args;
if (!OLD) {
  console.error('usage: compare-engines.mjs OLD/dose [SHARD NSHARDS [EVERY]] [--tol X]');
  process.exit(2);
}
const shard = Number(shardArg || 0), nShards = Number(nArg || 1), every = Number(everyArg || 11);
const io = {
  json: async (p) => JSON.parse(fs.readFileSync(path.join(DATA, p), 'utf8')),
  bin: async (p) => { const b = fs.readFileSync(path.join(DATA, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); },
};
async function engine(dir) {
  const m = {};
  for (const f of ['data', 'dose103', 'dose60', 'model60', 'catalog']) Object.assign(m, await import(path.join(path.resolve(dir), `${f}.js`)));
  m.d103 = await m.loadSystem('103', io);
  m.d60 = await m.loadSystem('60', io);
  return m;
}
const A = await engine(OLD), B = await engine(NEW);

// Every number a result holds, by name.
function values(r) {
  const out = [['E', r.E]];
  for (const [sex, v] of Object.entries(r.Ht || {})) {
    if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) if (typeof x === 'number') out.push([`Ht.${sex}.${k}`, x]);
  }
  for (const [s, v] of Object.entries(r.H || {})) {
    if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) if (typeof x === 'number') out.push([`H.${s}.${k}`, x]);
    else if (typeof v === 'number') out.push([`H.${s}`, v]);
  }
  (r.transformations || []).forEach((t, i) => out.push([`U${i}.${t.member}.${t.region}`, t.n]));
  return out;
}
const rel = (a, b) => (a === b ? 0 : Math.abs(b - a) / Math.max(Math.abs(a), 1e-300));
// The tissue doses that weigh: those of the average (ICRP 103) or the tissues (ICRP 60).
const tissues = (r) => Object.entries(r.H.avg || r.H).filter(([, x]) => typeof x === 'number');

const cases = [];
A.catalog103(A.d103).nuclides.forEach((e, i) => {
  if (i % every) return;
  for (const route of ['ingestion', 'inhalation', 'injection']) for (const f of e[route] || []) cases.push({ sys: '103', nuclide: e.name, route, spec: f.spec, label: f.key });
});
A.catalog60(A.d60).nuclides.forEach((e, i) => {
  if (i % (every * 3)) return;
  for (const route of ['ingestion', 'inhalation']) {
    const f = (e[route] || [])[0];
    if (f) cases.push({ sys: '60', nuclide: e.name, route, spec: f.spec, label: f.key });
  }
});

async function run(m, c) {
  const t = performance.now();
  let res;
  if (c.sys === '103') {
    await m.d103.prepare(c.nuclide);
    res = m.coefficients103(m.d103, { nuclide: c.nuclide, route: c.route, ...c.spec, cutoff: 1e-4 }, m.AGES_103);
  } else {
    await m.d60.prepare(c.nuclide);
    const s = m.recipe60(m.d60.cases, c.route, { nuclide: c.nuclide, bio: c.spec.bio, f1file: c.spec.f1file, type: c.spec.type ?? undefined, lung: c.route === 'inhalation' ? (c.spec.lung ?? null) : undefined });
    res = m.coefficients60(m.d60, s, m.AGES_60);
  }
  return [res, performance.now() - t];
}

let n = 0, differ = 0, tA = 0, tB = 0, runs = 0;
const worst = { E: [0, ''], H: [0, ''], U: [0, ''] };
const note = (k, d, where) => { if (d > worst[k][0]) worst[k] = [d, where]; };
const allE = [];
for (let k = shard; k < cases.length; k += nShards) {
  const c = cases[k];
  let ra, rb, ta, tb;
  try { [ra, ta] = await run(A, c); } catch (e) { console.log(`skip  ${c.sys} ${c.nuclide} ${c.route} ${c.label}: ${e.message}`); continue; }
  [rb, tb] = await run(B, c);
  tA += ta; tB += tb; runs++;
  let caseDiff = 0, cE = 0, cH = 0, cU = 0;
  ra.forEach((x, a) => {
    const y = rb[a], where = `${c.sys} ${c.nuclide} ${c.route} ${c.label} age ${x.age}`;
    const other = new Map(values(y));
    for (const [key, v] of values(x)) { n++; if (other.get(key) !== v) caseDiff++; }
    const dE = rel(x.E, y.E);
    cE = Math.max(cE, dE); note('E', dE, where); allE.push(dE);
    const hs = tissues(x), hy = new Map(tissues(y)), top = Math.max(...hs.map(([, v]) => v));
    for (const [t, v] of hs) if (v >= 1e-3 * top) { const d = rel(v, hy.get(t)); cH = Math.max(cH, d); note('H', d, `${where} ${t}`); }
    const us = x.transformations || [], total = us.reduce((s, u) => s + u.n, 0);
    us.forEach((u, i) => { if (u.n >= 1e-6 * total) { const d = rel(u.n, y.transformations[i].n); cU = Math.max(cU, d); note('U', d, `${where} ${u.member} ${u.region}`); } });
  });
  differ += caseDiff;
  console.log(`${caseDiff ? (cE > TOL ? 'DIFF' : 'near') : 'same'}  ${c.sys} ${c.nuclide.padEnd(8)} ${c.route.padEnd(10)} ${String(c.label).slice(0, 24).padEnd(24)} `
    + `${(ta / 1000).toFixed(2)} s -> ${(tb / 1000).toFixed(2)} s${caseDiff ? `  E ${cE.toExponential(1)}, tissues ${cH.toExponential(1)}, transformations ${cU.toExponential(1)}` : ''}`);
}
allE.sort((p, q) => p - q);
const pct = (q) => (allE.length ? allE[Math.min(allE.length - 1, Math.floor(q * allE.length))] : 0);
console.log(`shard ${shard} of ${nShards}: ${runs} cases, ${n} values, ${differ} differ; largest relative difference of E ${worst.E[0].toExponential(2)} (${worst.E[1]}), `
  + `median ${pct(0.5).toExponential(1)}, 99th percentile ${pct(0.99).toExponential(1)}; of a tissue dose ${worst.H[0].toExponential(2)} (${worst.H[1]}); `
  + `of transformations ${worst.U[0].toExponential(2)} (${worst.U[1]}); ${(tA / 1000).toFixed(1)} s before, ${(tB / 1000).toFixed(1)} s now`);
process.exit((TOL ? worst.E[0] > TOL : differ > 0) ? 1 : 0);
