#!/usr/bin/env node
/*
  Dose coefficients from processed decay data against those from the ICRP 107
  data the page has built in: every catalogue nuclide of a system (or every
  Nth), the default form of each route, all ages.

      node resources/tests/dose_coefficients/compare-ensdf-dose.mjs [--icrp107-inputs | --decay DIR]
           [--system 103|60] [--every N] [--jobs N] [--json FILE] [--top N]

  --icrp107-inputs  (the default) the records ensdf-icrp107.mjs makes from
                    ICRP 107's own inputs, EDISTR04's way, with ICRP 107's
                    records for the nuclides that have no archived input:
                    how closely the processor reproduces ICRP 107
  --decay DIR       a decay folder (DIR/decay/index.json and <El>.json), e.g.
                    one scripts/gen-dose-ensdf.mjs made from an ENSDF release:
                    how much the release changes the coefficients
  --base DIR        what to hold them against, if not the system's own
                    decay data: e.g. --system 60 --base resources/data/dose/icrp103
                    runs the ICRP 60 system on ICRP 107's data on both sides,
                    so that only the processing differs

  The folder is read as the page reads it (data.js with decay-names.js): its
  states take the names of the system's own by half-life (ENSDF 2026 calls
  ICRP 107's Ta-178m Ta-178 and its Ta-178 Ta-178m); the renames are printed.

  The rest of the data (models, SAFs) is the page's. Runs --jobs processes
  (default: the cores less one); the whole ICRP 103 catalogue takes about
  four minutes on ten cores.
*/
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fork } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const DATA = path.join(ROOT, 'resources/data/dose');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const system = opt('--system', '103');
const every = Number(opt('--every', 1));

/* ---------------------------------------------------------------------------
   A child: one shard of the cases against a decay folder
   --------------------------------------------------------------------------- */
if (args.includes('--child')) await child();
else await parent();

async function child() {
  const [shard, nShards] = opt('--child').split('/').map(Number);
  const decayRoot = opt('--decay');
  const baseRoot = opt('--base', null);
  const mk = (overlay) => ({
    json: async (p) => JSON.parse(fs.readFileSync(overlay && /^icrp(103|60)\/decay\//.test(p) ? path.join(overlay, p.replace(/^icrp(103|60)\//, '')) : path.join(DATA, p), 'utf8')),
    bin: async (p) => { const b = fs.readFileSync(path.join(DATA, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); },
  });
  const folder = (root) => ({ json: async (p) => JSON.parse(fs.readFileSync(path.join(root, p), 'utf8')) });
  const m = {};
  for (const f of ['data', 'dose103', 'dose60', 'model60', 'catalog']) Object.assign(m, await import(path.join(ROOT, 'resources/js/dose', `${f}.js`)));
  const A = await m.loadSystem(system, mk(baseRoot)), B = await m.loadSystem(system, mk(baseRoot), folder(decayRoot));
  if (shard === 0 && B.decaySource.renamed.length) console.log(`paired by half-life (folder name -> page name): ${B.decaySource.renamed.map(([a, b]) => `${a} -> ${b}`).join(', ')}`);
  const cat = system === '103' ? m.catalog103(A) : m.catalog60(A);
  const cases = [];
  cat.nuclides.forEach((e, i) => {
    if (i % every) return;
    for (const route of system === '103' ? ['ingestion', 'inhalation', 'injection'] : ['ingestion', 'inhalation']) {
      const forms = e[route] || [];
      const f = forms.find((x) => x.default) || forms[0];
      if (f) cases.push({ nuclide: e.name, route, spec: f.spec });
    }
  });
  const run = async (d, c) => {
    await d.prepare(c.nuclide);
    if (system === '103') return m.coefficients103(d, { nuclide: c.nuclide, route: c.route, ...c.spec, cutoff: 1e-4 }, m.AGES_103);
    const s = m.recipe60(d.cases, c.route, { nuclide: c.nuclide, bio: c.spec.bio, f1file: c.spec.f1file, type: c.spec.type ?? undefined, lung: c.route === 'inhalation' ? (c.spec.lung ?? null) : undefined });
    return m.coefficients60(d, s, m.AGES_60);
  };
  const rows = [];
  for (let k = shard; k < cases.length; k += nShards) {
    const c = cases[k];
    try {
      const ra = await run(A, c), rb = await run(B, c);
      rows.push({ nuclide: c.nuclide, route: c.route, ratio: ra.map((x, i) => rb[i].E / x.E) });
    } catch (e) { rows.push({ nuclide: c.nuclide, route: c.route, error: e.message }); }
  }
  // Exit only once the rows are sent: an exit right after send() can lose them.
  await new Promise((resolve) => process.send(rows, resolve));
  process.exit(0);
}

/* ---------------------------------------------------------------------------
   The parent: the decay folder, the shards, the summary
   --------------------------------------------------------------------------- */
async function parent() {
  let decayRoot = opt('--decay');
  const made = []; // temporary folders this run writes, removed at the end
  if (!decayRoot) {
    const { have, emulate, PATHS } = await import('./ensdf-icrp107.mjs');
    if (!have()) {
      console.log(`skipped: needs ICRP 107's ARCHIVE (${PATHS.icrp107}) and the 1991 atomic tables (${PATHS.eadl1991}); see README.md`);
      process.exit(0);
    }
    const { compactRad, compactSpectrum, sig } = await import(path.join(ROOT, 'scripts/lib/dose-decay.mjs'));
    const { results } = emulate();
    decayRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ensdf-icrp107-'));
    made.push(decayRoot);
    const index = JSON.parse(fs.readFileSync(path.join(DATA, 'icrp103/decay/index.json'), 'utf8'));
    const byEl = {};
    for (const name of Object.keys(index.nuclides)) {
      const el = /^([A-Z][a-z]?)-/.exec(name)[1];
      byEl[el] ||= JSON.parse(fs.readFileSync(path.join(DATA, `icrp103/decay/${el}.json`), 'utf8'));
    }
    for (const { name, rec } of results) {
      const el = /^([A-Z][a-z]?)-/.exec(name)[1];
      index.nuclides[name] = { ...index.nuclides[name], d: rec.d.map(([d, b]) => [d, sig(b)]), E: rec.E.map((x) => sig(x, 6)) };
      byEl[el][name] = { r: compactRad(rec.rad), bs: compactSpectrum(rec.bs) };
    }
    fs.mkdirSync(path.join(decayRoot, 'decay'));
    fs.writeFileSync(path.join(decayRoot, 'decay/index.json'), JSON.stringify(index));
    for (const [el, obj] of Object.entries(byEl)) fs.writeFileSync(path.join(decayRoot, `decay/${el}.json`), JSON.stringify(obj));
    console.log(`${results.length} records from ICRP 107's inputs written to ${decayRoot}`);
  }

  const jobs = Number(opt('--jobs', Math.max(1, os.cpus().length - 1)));
  const t0 = Date.now();
  let parts;
  try {
    parts = await Promise.all(Array.from({ length: jobs }, (_, k) => new Promise((resolve, reject) => {
      const base = opt('--base', null);
      const child = fork(fileURLToPath(import.meta.url), ['--child', `${k}/${jobs}`, '--decay', decayRoot, '--system', system, '--every', String(every), ...(base ? ['--base', base] : [])], { stdio: 'inherit' });
      let got = null;
      child.on('message', (rows) => { got = rows; });
      child.on('error', reject);
      child.on('exit', (code) => (got ? resolve(got) : reject(new Error(`shard ${k} ended (${code}) without its results`))));
    })));
  } finally {
    for (const d of made) fs.rmSync(d, { recursive: true, force: true });
  }
  const rows = parts.flat();
  const ok = rows.filter((r) => r.ratio);
  const worst = ok.map((r) => ({ r, d: Math.max(...r.ratio.map((x) => Math.abs(x - 1))) })).sort((a, b) => b.d - a.d);
  const within = (t) => worst.filter((x) => x.d <= t).length;
  const all = ok.flatMap((r) => r.ratio.map((x) => Math.abs(x - 1))).sort((a, b) => a - b);
  console.log(`ICRP ${system} system, ${ok.length} cases of ${new Set(ok.map((r) => r.nuclide)).size} nuclides (${rows.length - ok.length} errors) in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
  console.log(`worst age within 0.1 %: ${within(1e-3)}, 1 %: ${within(1e-2)}, 5 %: ${within(5e-2)}; every age: median ${all[all.length >> 1]?.toExponential(1)}, 99th percentile ${all[Math.floor(0.99 * all.length)]?.toExponential(1)}`);
  for (const { r, d } of worst.slice(0, Number(opt('--top', 20)))) console.log(`${(d * 100).toFixed(2).padStart(8)} %  ${r.nuclide.padEnd(8)} ${r.route.padEnd(10)} ${r.ratio.map((x) => x.toFixed(4)).join(' ')}`);
  for (const r of rows.filter((x) => x.error)) console.log(`ERROR ${r.nuclide} ${r.route}: ${r.error}`);
  if (opt('--json')) fs.writeFileSync(opt('--json'), JSON.stringify(rows));
}
