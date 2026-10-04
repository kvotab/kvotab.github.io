/*
  The Model tab's boxes as buckets: every member's activity in the body, and
  the effective dose from it, must be in a box the tab draws, or in a place it
  lists beside them (the respiratory tract by region, the mouth and the
  oesophagus, and where a progeny is formed in a part of another member's
  model that its own lacks); and the dose by place must add up to e(t).
  This runs the page's worker (worker.js) in Node over one nuclide of every
  element and a few long chains, each route, in both systems, and keys the
  boxes as ui.js does (nodePlaces) from what renderModel draws.

    node resources/tests/dose_coefficients/test-buckets.mjs [--system 60|103] [--quick]

  --quick runs a dozen cases (about 20 s); the whole sweep is about 520 runs
  (about five minutes).
*/
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const JS = path.resolve(HERE, '../../js/dose');
const args = process.argv.slice(2);
const SYSTEM = args.includes('--system') ? args[args.indexOf('--system') + 1] : null;
const QUICK = args.includes('--quick');

// The worker fetches its data by URL: from the files here.
const realFetch = globalThis.fetch;
globalThis.fetch = async (u) => {
  const s = String(u);
  if (!s.startsWith('file:')) return realFetch(u);
  const p = fileURLToPath(s);
  return fs.existsSync(p) ? new Response(fs.readFileSync(p)) : new Response(null, { status: 404 });
};
const pending = new Map();
let nextId = 1;
globalThis.self = {
  postMessage: (m) => {
    const p = pending.get(m.id);
    if (!p || m.type === 'progress') return;
    pending.delete(m.id);
    if (m.type === 'result') p.resolve(m.result); else p.reject(new Error(m.message));
  },
};
await import(pathToFileURL(path.join(JS, 'worker.js')).href);
const ask = (msg) => new Promise((resolve, reject) => { const id = nextId++; pending.set(id, { resolve, reject }); self.onmessage({ data: { id, ...msg } }); });
const { laneOf } = await import(pathToFileURL(path.join(JS, 'diagram.js')).href);
const { key } = await import(pathToFileURL(path.join(JS, 'regions.js')).href);

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok || !detail ? '' : `: ${detail}`}`);
  if (!ok) failures.push(label);
}

/* As ui.js: the output times, and the places a drawn box holds. */
function outputTimes(intakeAges) {
  const tEnd = Math.max(...intakeAges.map((a) => (a < 7300 ? 25550 - a : 18250)));
  const out = [];
  for (let e = -3; ; e += 1 / 10) { const t = 10 ** e; if (t >= tEnd) break; out.push(+t.toPrecision(6)); }
  return out;
}
function drawnPlaces(model) {
  const known = new Set(model.compartments.map((c) => c.name));
  const all = [...model.compartments];
  const add = (name, region) => { if (!known.has(name) && laneOf(region, name) !== 'sink') { known.add(name); all.push({ name, region }); } };
  for (const t of model.onward || []) { add(t.from, t.fromRegion); add(t.to, t.toRegion); }
  for (const c of model.tract || []) add(c.name, c.region);
  const keys = new Set();
  for (const c of all) {
    const lane = laneOf(c.region, c.name);
    if (lane === 'sink') continue;
    keys.add(`n:${key(c.name)}`);
    if (lane === 'content') keys.add(`r:${String(c.region).replace(/_/g, '-').toLowerCase()}`);
  }
  return keys;
}
// Listed beside the boxes, not drawn.
const LISTED = (k) => k.startsWith('l:') || k.startsWith('s:') || /^r:(o-cavity|oesophag-[fs])$/.test(k);
const FLOOR = 1e-10; // ui.js BUCKET_FLOOR
const QUICK_CASES = new Set(['103 Cs-137 ingestion', '103 Pu-239 inhalation', '103 Ra-226 ingestion', '103 U-238 injection', '103 Fe-52 injection',
  '103 Rn-222 inhalation', '103 H-3 ingestion', '60 Cs-137 ingestion', '60 Sr-90 inhalation', '60 Th-232 ingestion', '60 Ac-224 ingestion', '60 Am-241 ingestion']);

let cases = 0, members = 0, worst = { share: 0 }, sumOff = 0, doseOff = 0, doseWorst = 0;
const missed = [], errors = [];
for (const system of ['103', '60']) {
  if (SYSTEM && SYSTEM !== system) continue;
  const cat = await ask({ type: 'catalog', system });
  const byEl = new Map();
  for (const e of cat.nuclides) { const el = e.name.split('-')[0]; if (!byEl.has(el)) byEl.set(el, e); }
  const extra = ['Ra-226', 'Th-232', 'U-238', 'Pu-239', 'Pu-241', 'Am-241', 'Cs-137', 'Sr-90', 'I-131', 'Pb-210', 'Po-210', 'Rn-222', 'Te-132', 'Ce-144', 'Ru-106', 'Fe-52'];
  const picks = [...byEl.values(), ...cat.nuclides.filter((e) => extra.includes(e.name) && byEl.get(e.name.split('-')[0]) !== e)];
  for (const e of picks) {
    for (const route of ['ingestion', 'inhalation', 'injection']) {
      const forms = e[route] || [];
      if (!forms.length || (QUICK && !QUICK_CASES.has(`${system} ${e.name} ${route}`))) continue;
      const f = forms.find((x) => x.default) || forms[0];
      const spec = { nuclide: e.name, route, ...f.spec, cutoff: 1e-4 };
      if (route === 'inhalation') spec.amad = system === '103' ? 5 : 1;
      cases++;
      let o;
      try { [o] = await ask({ type: 'run', system, spec, ages: [7300], outputs: outputTimes([7300]), rtol: 1e-6 }); }
      catch (err) { errors.push(`${system} ${e.name} ${route}: ${err.message}`); continue; }
      const ser = o.series;
      // The dose by place, every member, adds up to e(t), and to the coefficient at the end.
      ser.times.forEach((t, k) => {
        const sum = ser.dosePlaces.reduce((a, D) => a + Object.values(D).reduce((b, ys) => b + ys[k], 0), 0);
        if (ser.E[k] > 0) doseOff = Math.max(doseOff, Math.abs(sum - ser.E[k]) / ser.E[k]);
        if (k === ser.times.length - 1) doseOff = Math.max(doseOff, Math.abs(sum - o.E) / o.E);
      });
      o.models.forEach((model, m) => {
        if (!model.compartments.length) return;
        members++;
        const keys = drawnPlaces(model);
        const P = ser.places[m] || {};
        ser.times.forEach((t, k) => {
          // The places make up the member's whole body, value for value.
          const sum = Object.values(P).reduce((a, ys) => a + ys[k], 0);
          const total = Object.values(P).reduce((a, ys) => a + Math.max(0, ys[k]), 0);
          sumOff = Math.max(sumOff, Math.abs(sum - ser.byMember[m][k]) / (Math.abs(ser.byMember[m][k]) || 1));
          if (!(total >= FLOOR)) return;
          const out = Object.entries(P).filter(([x, ys]) => !keys.has(x) && !LISTED(x) && ys[k] > 0);
          const share = out.reduce((a, [, ys]) => a + ys[k], 0) / total;
          if (share > worst.share) worst = { share, what: `${system} ${e.name} ${route}, ${model.member} at ${t} d`, places: out.map(([x]) => x) };
          if (share > 1e-6 && !missed.some((x) => x.startsWith(`${system} ${e.name} ${route} ${model.member}`))) missed.push(`${system} ${e.name} ${route} ${model.member}: ${(share * 100).toPrecision(3)} % at ${t} d in ${out.map(([x]) => x).join(', ')}`);
          // The member's dose by place, as the tab keys it for the member alone.
          const D = ser.dosePlaces[m] || {};
          const own = {};
          for (const [x, ys] of Object.entries(D)) { const o2 = ser.placeKey[m]?.[x] ?? x; own[o2] = (own[o2] || 0) + ys[k]; }
          const dTotal = Object.values(own).reduce((a, v) => a + v, 0);
          if (dTotal > 0) {
            const dOut = Object.entries(own).filter(([x, v]) => !keys.has(x) && !LISTED(x) && v > 0);
            const dShare = dOut.reduce((a, [, v]) => a + v, 0) / dTotal;
            doseWorst = Math.max(doseWorst, dShare);
            if (dShare > 1e-6 && !missed.some((x) => x.startsWith(`dose ${system} ${e.name} ${route} ${model.member}`))) missed.push(`dose ${system} ${e.name} ${route} ${model.member}: ${(dShare * 100).toPrecision(3)} % at ${t} d in ${dOut.map(([x]) => x).join(', ')}`);
          }
        });
      });
    }
  }
}
check(`${cases} calculations run without an error`, errors.length === 0, errors.slice(0, 5).join('; '));
check(`the places of each member add up to its whole-body activity (largest difference ${sumOff.toExponential(1)} of it)`, sumOff < 1e-9);
check(`the dose by place, every member, adds up to e(t) at every output time and to the coefficient at the end (largest difference ${doseOff.toExponential(1)} of it)`, doseOff < 1e-9);
check(`in ${members} member models, no activity above ${FLOOR} Bq per Bq, and no dose from a member, is in a place neither drawn nor listed (largest shares ${worst.share.toExponential(1)}, ${doseWorst.toExponential(1)})`,
  missed.length === 0, missed.slice(0, 5).join('; '));
console.log(`\n${checks - failures.length} of ${checks} checks passed`);
process.exit(failures.length ? 1 : 0);
