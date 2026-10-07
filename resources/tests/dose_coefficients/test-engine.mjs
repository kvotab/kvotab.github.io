#!/usr/bin/env node
/*
  dose_coefficients.html: the engines, in Node, without a browser.

      node resources/tests/dose_coefficients/test-engine.mjs          checks and a sample of cases
      node resources/tests/dose_coefficients/test-engine.mjs --all    every case of both systems (an hour)
          [--system 60|103] [--only REGEX]

  What needs no outside data:
    - decay data: every nuclide's lines add up to its index energies (ICRP 38
      and ICRP 107), beta spectra integrate to their mean energies
    - specific absorbed fractions: the S coefficients of see103.js equal a
      brute-force PCHIP evaluation of the original rows; the alpha self-dose
      of Pu-239 in the liver is E·wR/M
    - first-year weight, deposition, catalogues, decay chains
    - pinned results: a few coefficients as this page calculates them, so that
      an unintended change shows

  What compares with the ICRP's own coefficients needs local/icrp72.json,
  local/icrp119.json, local/icrp103.json and local/inmop.json
  (make-local-fixtures.py); without them those parts are skipped with a
  message. The annex of Publication 158 (the ICRP InMoP Electronic Annex) is
  acknowledged as the source of the reference values it gives.

  Exit status is 0 when every check passes.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const DATA = path.join(ROOT, 'resources/data/dose');
const JS = path.join(ROOT, 'resources/js/dose');
const args = process.argv.slice(2);
const ALL = args.includes('--all');
const SYSTEM = args.includes('--system') ? args[args.indexOf('--system') + 1] : null;
const ONLY = args.includes('--only') ? new RegExp(args[args.indexOf('--only') + 1]) : null;

const { loadSystem } = await import(path.join(JS, 'data.js'));
const { coefficients60, AGES_60 } = await import(path.join(JS, 'dose60.js'));
const { parentModelName, f1FileName, recipe60, assemble60 } = await import(path.join(JS, 'model60.js'));
const { coefficients103, AGES_103 } = await import(path.join(JS, 'dose103.js'));
const { emissionWeights, sAllRows, pchipSlopes, pchipEval, spectrumLines, MEV } = await import(path.join(JS, 'see103.js'));
const { firstYearWeight, dcalWeight } = await import(path.join(JS, 'solve.js'));
const { deposition103 } = await import(path.join(JS, 'model103.js'));
const { buildChain } = await import(path.join(JS, 'chain.js'));
const { catalog60, catalog103 } = await import(path.join(JS, 'catalog.js'));
const { detriment103, detriment60, nominalDetriment } = await import(path.join(JS, 'risk.js'));
const { radonCoefficients, radonDoses } = await import(path.join(JS, 'radon.js'));

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
  checks++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok || !detail ? '' : `: ${detail}`}`);
  if (!ok) failures.push(label);
}
const near = (a, b, rel) => Math.abs(a - b) <= rel * Math.abs(b);
const io = {
  json: async (p) => JSON.parse(fs.readFileSync(path.join(DATA, p), 'utf8')),
  bin: async (p) => { const b = fs.readFileSync(path.join(DATA, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); },
};
const local = (name) => { const f = path.join(HERE, 'local', name); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : null; };

/* ---- decay data ------------------------------------------------------------ */
for (const sys of ['icrp60', 'icrp103']) {
  const index = JSON.parse(fs.readFileSync(path.join(DATA, sys, 'decay/index.json'), 'utf8')).nuclides;
  const byEl = {};
  let bad = 0, spectra = 0, worstSpec = 0, n = 0, offSpec = 0;
  const offNames = [];
  for (const [name, x] of Object.entries(index)) {
    const el = name.split('-')[0];
    byEl[el] ||= JSON.parse(fs.readFileSync(path.join(DATA, sys, `decay/${el}.json`), 'utf8'));
    const em = byEl[el][name];
    const s = (k) => (em.r[k] || []).reduce((a, [e, y]) => a + e * y, 0);
    n++;
    // ICRP 38: the recoil is not listed; its alpha energy is the alphas'.
    const got = [s('a') + s('ar'), s('b') + s('e'), s('p')];
    if (!got.every((g, i) => Math.abs(g - x.E[i]) <= 2e-3 * x.E[i] + 1e-4)) bad++;
    if (em.bs && s('b') > 0) {
      spectra++;
      const I = spectrumLines(em.bs).reduce((a, [, w]) => a + w, 0);
      const off = Math.abs(I / s('b') - 1);
      if (off >= 0.01) { offSpec++; offNames.push(name); } else worstSpec = Math.max(worstSpec, off);
    }
  }
  check(`${sys}: the lines of all ${n} nuclides add up to the index energies`, bad === 0, `${bad} do not`);
  // ICRP 38's spectrum file covers only part of the beta emission of a few
  // nuclides (In-114, Br-80, Rb-84, Eu-152); ICRP 107's are all complete.
  const allowed = sys === 'icrp60' ? 6 : 0;
  check(`${sys}: ${spectra - offSpec} of ${spectra} beta spectra integrate to their mean energies within 1 %${offSpec ? ` (not: ${offNames.join(', ')})` : ''}`, offSpec <= allowed, `${offSpec} do not`);
}

/* ---- ICRP 103 dosimetry ------------------------------------------------------ */
const d103 = await loadSystem('103', io);
{
  const ph = d103.saf.phantoms.AM;
  const idx = d103.saf.index;
  // Brute force: PCHIP on the original rows as the binary file holds them.
  const raw = (key, r) => {
    const R = ph.radiation[key];
    const row = new Array(R.n).fill(0);
    for (let k = R.start[r]; k < R.n; k++) row[k] = R.vals[R.offset[r] + k - R.start[r]];
    return row;
  };
  let worst = 0;
  for (const name of ['Cs-137', 'Co-60', 'Pu-239', 'Y-90', 'I-131']) {
    await d103.prepare(name);
    const em = d103.emissions(name);
    const S = sAllRows(ph, emissionWeights(em, idx.energies, name));
    for (let r = 0; r < 3397; r += 13) {
      const val = (key, E) => { const x = idx.energies[key]; const y = raw(key, r); return pchipEval(x, y, pchipSlopes(x, y), E); };
      let s = 0;
      for (const [E, Y] of em.r.p || []) s += E * Y * val('photon', E);
      for (const [E, Y] of em.r.e || []) s += E * Y * val('electron', E);
      for (const [E, w] of em.bs ? spectrumLines(em.bs) : (em.r.b || []).map(([E, Y]) => [E, E * Y])) s += w * val('electron', E);
      for (const [E, Y] of em.r.a || []) s += 20 * E * Y * val('alpha', E);
      for (const [E, Y] of [...(em.r.ar || []), ...(em.r.ff || [])]) s += 20 * E * Y * val('alpha', 2.0);
      s *= MEV;
      if (s > 0) worst = Math.max(worst, Math.abs(S[r] / s - 1));
    }
  }
  check('see103: S of every sampled pair equals brute-force PCHIP (5 nuclides, adult male)', worst < 1e-6, `worst ${worst.toExponential(2)}`);
  const pu = d103.emissions('Pu-239');
  const Ea = [...(pu.r.a || []), ...(pu.r.ar || [])].reduce((a, [e, y]) => a + e * y, 0);
  const S = sAllRows(ph, emissionWeights(pu, idx.energies, 'Pu-239'));
  const t = idx.targets.indexOf('Liver'), s = idx.sources.indexOf('Liver');
  const want = 20 * Ea * MEV / ph.masses.targets[t];
  check('see103: Pu-239 alpha self-dose of the adult male liver is 20·E/M', near(S[s * idx.targets.length + t], want, 0.01), `${S[s * idx.targets.length + t]} vs ${want}`);
}
{
  // ICRP 158 eq. 2.16: t^(0.3 + 0.7(1-t)^10) below 100 d, t^(0.16 + 0.84(1-t)^5) from 100 d.
  const t = 100 / 365;
  const want = t ** (0.16 + 0.84 * (1 - t) ** 5);
  check('first-year weight at 100 d is the second branch of ICRP 158 eq. 2.16 (0.6528)', Math.abs(firstYearWeight(100) - want) < 1e-12 && Math.abs(want - 0.6528) < 1e-4, String(firstYearWeight(100)));
  check('first-year weight is 0 at birth and 1 at a year', firstYearWeight(0) === 0 && firstYearWeight(365) === 1);
  // DCAL's weights of the older phantom, as read off EPACAL's dose rates
  // (each rate rebuilt from DCAL's own activities and SEE files).
  const epacal = [[200, 0, 0.8348], [260, 0, 0.9032], [330, 0, 0.9702], [465, 1, 0.1024], [730, 1, 0.4243], [1065, 1, 0.6828], [1365, 1, 0.8272]];
  const offW = epacal.filter(([a, k, w]) => Math.abs(dcalWeight(a, k) - w) > 3e-4).map(([a, k, w]) => `${a} d: ${dcalWeight(a, k).toFixed(4)} not ${w}`);
  check('ICRP 60: DCAL\'s weights of the older phantom, first year and 1-5 years, as EPACAL\'s dose rates have them', !offW.length && dcalWeight(365, 0) === 1 && dcalWeight(365, 1) === 0 && dcalWeight(1825, 1) === 1, offW.join('; '));
}
{
  const dep = deposition103(d103.deposition, 5, 1);
  const tot = dep.ET1 + dep.ET2 + dep.BB + dep.bb + dep.AI;
  check('ICRP 158 Table A.1: adult 1 µm deposits 48.58 % (Table 2.4)', Math.abs(100 * tot - 48.58) < 0.02, (100 * tot).toFixed(3));
}

/* ---- catalogues and chains ------------------------------------------------------- */
const d60 = await loadSystem('60', io);
{
  const c60 = catalog60(d60), c103 = catalog103(d103);
  check(`catalogue ICRP 60: ${c60.nuclides.length} nuclides of ICRP 72`, c60.nuclides.length > 700);
  check(`catalogue ICRP 103: ${c103.nuclides.length} nuclides of ${c103.elements.length} elements`, c103.elements.length >= 91);
  // An element missing from catalog.js's ELEMENTS gets Z 0 and sorts before
  // hydrogen (ICRP 72's Md-257 and Md-258 did).
  const noZ = [...c60.nuclides, ...c103.nuclides].filter((n) => !n.Z).map((n) => n.name);
  check('catalogues: every nuclide has its atomic number; ICRP 60 runs from H-3 to Md', !noZ.length && c60.nuclides[0].name === 'H-3' && /^Md-/.test(c60.nuclides.at(-1).name), noZ.join(', '));
  // FGR13ING.INP runs Pu-238 twice more at its head, once with an f1 file of
  // DCAL's library for workers (gen-dose-icrp60.mjs, keepCases).
  const twice = c60.nuclides.flatMap((n) => ['ingestion', 'inhalation'].flatMap((r) => n[r].filter((f, i, all) => all.findIndex((g) => g.key === f.key) < i).map((f) => `${n.name} ${r} ${f.key}`)));
  check('catalogue ICRP 60: no nuclide lists a form twice', !twice.length, twice.join(', '));
  const lacking = ['ingestion', 'inhalation'].flatMap((r) => d60.cases[r].filter((c) => (c.bio && !d60.models.systemic[c.bio]) || (c.f1 && !d60.models.f1[c.f1]) || (c.lung && !d60.models.lung[c.lung])).map((c) => `${r} ${c.nuclide}`));
  check('cases ICRP 60: every model, f1 and lung file a case names is in the library', !lacking.length, lacking.join(', '));
  const pu = c60.nuclides.find((n) => n.name === 'Pu-238');
  check('catalogue ICRP 60: Pu-238 by ingestion once, f1 5E-4 (ICRP 72; FGR 13 Table 2.2a)', pu.ingestion.length === 1 && pu.ingestion[0].f1 === 5e-4, pu.ingestion.map((f) => f.label).join(', '));
  let threw = '';
  try { coefficients60(d60, recipe60(d60.cases, 'ingestion', { nuclide: 'Pu-238', bio: null, f1file: 'PU_2' }), [7300]); } catch (e) { threw = e.message; }
  check('ICRP 60: an f1 file not in the library is an error, not f1 = 0', /no f1 file PU_2\.GF1/.test(threw), threw);
  const th = buildChain(d103.index, 'Th-232', { cutoff: 0 });
  check('Th-232 chain (ICRP 107) runs through Ra-228, Ac-228, Th-228, Ra-224, Rn-220 to Pb-212', ['Ra-228', 'Ac-228', 'Th-228', 'Ra-224', 'Rn-220', 'Pb-212'].every((n) => th.members.some((m) => m.name === n)));
  const cs = buildChain(d103.index, 'Cs-137', { cutoff: 1e-4 });
  check('Cs-137 chain keeps Ba-137m (94.4 %)', cs.members.map((m) => m.name).join() === 'Cs-137,Ba-137m' && near(cs.branches[0].b, 0.944, 0.001));
}

/* ---- detriment-adjusted nominal risk coefficients (risk.js) ----------------------------- */
{
  const r1 = (x) => Math.round(10 * x) / 10;
  const w = detriment103('whole'), a = detriment103('adult');
  const worst = (d) => Math.max(...d.rows.map((r) => Math.abs(r.D / r.published.D - 1)));
  check('ICRP 103 Table A.4.1a: each tissue’s detriment within 1 % of the printed, total 574.3', worst(w) < 0.01 && Math.abs(w.total.D - 574.3) < 0.05, `worst ${(100 * worst(w)).toFixed(2)} %, total ${w.total.D.toFixed(2)}`);
  check('ICRP 103 Table A.4.1b (whole-number risks): total 422, each tissue within 8 %', Math.abs(a.total.D - 422) < 0.5 && worst(a) < 0.08, `worst ${(100 * worst(a)).toFixed(1)} %, total ${a.total.D.toFixed(2)}`);
  check('ICRP 103 Table 1: 5.5, 0.2 and 5.7 for the whole population, 4.1, 0.1 and 4.2 for adults',
    [w, a].every((d) => ['cancer', 'heritable', 'total'].every((k) => r1(d.table1[k]) === d.published.table1[k])), JSON.stringify([w.table1, a.table1]));
  const p = detriment60('whole'), q = detriment60('adult');
  check('ICRP 60 Table B-20: each product as printed, total 725.3', p.rows.every((r) => Math.abs(r.D - r.published.product) <= 0.051) && Math.abs(p.gonads.D - 133.3) < 0.05 && Math.abs(p.total - 725.3) < 0.05, p.total.toFixed(2));
  check('ICRP 60 Table 3: 5.0, 1.0, 1.3 and 7.3 for the whole population, 4.0, 0.8, 0.8 and 5.6 for workers',
    [p, q].every((d) => ['fatal', 'nonfatal', 'hereditary', 'total'].every((k) => r1(d.table3[k]) === d.published.table3[k])), JSON.stringify([p.table3, q.table3]));
  const t4off = [p, q].flatMap((d) => d.rows.filter((r) => Math.abs(r.D / 100 - r.published.table4) > 0.0051).map((r) => `${d.pop} ${r.organ}`));
  check('ICRP 60 Table 4: aggregated detriments as printed, except the workers’ bone surface (0.06 printed, 0.05 calculated)', t4off.join() === 'adult Bone surface', t4off.join(', '));
  // Applied to an intake: a uniform 1 Sv to every tissue gives, tissue by tissue, the total coefficient.
  const names = ['Oesophagus', 'Stomach', 'Colon', 'Liver', 'Lung', 'Bone surface', 'Skin', 'Breast', 'Gonads', 'Bladder', 'Thyroid', 'Red marrow', 'Remainder'];
  const H = Object.fromEntries(names.map((t) => [t, 1]));
  const H60 = Object.fromEntries([...names.filter((t) => t !== 'Gonads'), 'Testes', 'Ovaries'].map((t) => [t, 1]));
  const u103 = nominalDetriment('103', 'whole', [{ age: 7300, E: 1, H: { avg: H, M: H, F: H } }]).ages[0];
  const u60 = nominalDetriment('60', 'adult', [{ age: 7300, E: 1, H: H60 }]).ages[0];
  check('a uniform 1 Sv gives tissue by tissue the total detriment (ICRP 103 whole 5.74, ICRP 60 workers 5.54 × 10⁻² Sv⁻¹) and e × the printed 5.7 and 5.6',
    Math.abs(u103.organ - w.total.D / 1e4) < 1e-12 && Math.abs(u60.organ - q.total / 1e4) < 1e-12 && Math.abs(u103.fromE - 0.057) < 1e-12 && Math.abs(u60.fromE - 0.056) < 1e-12 && Math.abs(u60.risk - 0.04) < 1e-12,
    `${u103.organ} ${u60.organ} ${u60.risk}`);
}

/* ---- radon and thoron in homes (radon.js) against Publication 158 -------------------------- */
if (!SYSTEM || SYSTEM === '103') {
  const ref = local('radon.json');
  if (!ref) console.log('skip  radon and thoron in homes: no local/radon.json (make-local-fixtures.py)');
  else {
    const within = (x, y, t) => y != null && Math.abs(x / y - 1) <= t;
    const worstOf = (xs, ys) => Math.max(...xs.map((x, a) => (ys[a] ? Math.abs(x / ys[a] - 1) : 0)));
    const MODE = { Unattached: 'u', Nucleation: 'n', Accumulation: 'a' };
    const c8 = (co, series, tol) => ref.tableC8.filter((row) => row.series.startsWith(series) && row.e_Sv_per_Bq[0] != null)
      .map((row) => [row.nuclide, row.mode, worstOf(co.e[row.nuclide][MODE[row.mode]], row.e_Sv_per_Bq), tol(row)]);
    const radon = await radonCoefficients(d103, 'radon', coefficients103, AGES_103, buildChain);
    const r = radonDoses(d103, radon);
    const T7 = ref.table32_7;
    check('radon progeny in homes: dose per exposure within 2 % of Table 32.7 at every age', worstOf(r.progeny, T7.progeny_mSv_per_mJ_h_m3) <= 0.02, r.progeny.map((x) => x.toFixed(2)).join(' '));
    check('radon gas and progeny: within 3 % of Table 32.7 (mSv per Bq h m⁻³ at F = 0.4)', worstOf(r.total.map((x) => x * 1e3), T7.total_mSv_per_Bq_h_m3) <= 0.03, r.total.map((x) => (x * 1e3).toExponential(2)).join(' '));
    check('radon gas alone: Sv per Bq and per exposure within 5 % of Table C.7', worstOf(radon.gas, ref.tableC7.radon_Sv_per_Bq) <= 0.05 && worstOf(r.gas.map((x) => x * 1e3), ref.tableC7.radon_mSv_per_Bq_h_m3) <= 0.05);
    const rc8 = c8(radon, 'Radon', () => 0.05);
    check('radon progeny, each nuclide and mode within 5 % of Table C.8', rc8.every(([, , w, t]) => w <= t), rc8.filter(([, , w, t]) => w > t).map(([n, m, w]) => `${n} ${m} ${(100 * w).toFixed(1)} %`).join(', '));
    const C9 = ref.tableC9.mSv_per_mJ_h_m3;
    check('radon progeny by mode within 5 % of Table C.9 (a, b, c)', ['u', 'n', 'a'].every((m, i) => worstOf(r.D[m], C9['abc'[i]]) <= 0.05), ['u', 'n', 'a'].map((m) => r.D[m].map((x) => x.toFixed(1)).join(' ')).join(' | '));
    const thoron = await radonCoefficients(d103, 'thoron', coefficients103, AGES_103, buildChain);
    const t = radonDoses(d103, thoron);
    check('thoron progeny in homes: within 6 % of Table 32.8 (nSv per Bq h m⁻³ of EEC; the accumulation mode’s σg 1.8 is not in Table C.1)', worstOf(t.perEEC.map((x) => x * 1e9), ref.table32_8.progeny_nSv_per_Bq_h_m3_EEC) <= 0.06, t.perEEC.map((x) => (x * 1e9).toFixed(1)).join(' '));
    const tc8 = c8(thoron, 'Thoron', (row) => (row.mode === 'Accumulation' ? 0.12 : 0.06));
    check('thoron progeny, each nuclide and mode within 6 % of Table C.8 (accumulation 12 %)', tc8.every(([, , w, tol]) => w <= tol), tc8.map(([n, m, w]) => `${n} ${m} ${(100 * w).toFixed(1)} %`).join(', '));
    check('thoron gas alone within 5 % of Table C.7', worstOf(thoron.gas, ref.tableC7.thoron_Sv_per_Bq) <= 0.05 && worstOf(t.gas.map((x) => x * 1e3), ref.tableC7.thoron_mSv_per_Bq_h_m3) <= 0.05);
  }
}

/* ---- pinned results (this page's own) ------------------------------------------------ */
{
  const pins = [
    ['103', { nuclide: 'Cs-137', route: 'ingestion', form: 'soluble' }, 7300, 1.3529e-8],
    ['103', { nuclide: 'Sr-90', route: 'inhalation', form: 'F' }, 100, 2.3426e-7],
    ['103', { nuclide: 'Pb-212', route: 'ingestion', form: 'all' }, 7300, 5.5916e-9],
    ['103', { nuclide: 'Pb-210', route: 'injection' }, 7300, 1.5710e-6],
    ['103', { nuclide: 'Ra-226', route: 'ingestion', form: 'all' }, 7300, 1.2646e-7],
    ['60', { nuclide: 'Po-210', route: 'ingestion' }, 7300, 1.206e-6],
  ];
  for (const [sys, spec, age, want] of pins) {
    await (sys === '103' ? d103 : d60).prepare(spec.nuclide);
    const r = sys === '103'
      ? coefficients103(d103, { ...spec, cutoff: 1e-4 }, [age])[0]
      : coefficients60(d60, recipe60(d60.cases, spec.route, { nuclide: spec.nuclide, bio: null, f1file: null }), [age])[0];
    check(`pinned: ${sys} ${spec.nuclide} ${spec.route} ${spec.form || ''} at ${age} d is ${want.toExponential(3)}`, near(r.E, want, 0.002), r.E.toExponential(4));
  }
}

/* ---- Other in chains with independent kinetics (ICRP 60; ORNL/TM-2001/190, 9.3.1) ---------- */
// A member's source regions are those its model carries it into: RAU gives
// radium formed in thorium's testes, kidneys and red marrow a way back to
// blood, which makes none of them radium's own (step 1).
{
  await d60.prepare('U-232');
  const sys = assemble60(d60, { ...recipe60(d60.cases, 'ingestion', { nuclide: 'U-232', bio: null, f1file: null }), intakeAge: 9125 });
  const of = (n) => sys.members.find((m) => m.name === n).explicit;
  check('ICRP 60 U-232 chain: testes and red marrow are 228Th\'s source regions, not 224Ra\'s (RAU only lets radium leave them)',
    of('Th-228').includes('Testes') && of('Th-228').includes('R_Marrow') && !of('Ra-224').includes('Testes') && !of('Ra-224').includes('R_Marrow') && !of('Ra-224').includes('Kidneys'),
    `228Th ${of('Th-228').join(' ')} | 224Ra ${of('Ra-224').join(' ')}`);
  // Type S: a member without a Type S f1 file of its own takes no more than the parent's.
  await d60.prepare('Pb-212');
  const s = assemble60(d60, { ...recipe60(d60.cases, 'inhalation', { nuclide: 'Pb-212', type: 'S' }), intakeAge: 9125 });
  const bi = s.members.find((m) => m.name === 'Bi-212'), po = s.members.find((m) => m.name === 'Po-212');
  check('ICRP 60 Pb-212 Type S: 212Bi absorbed from the gut at most as the parent (PB$S), 212Po by its own PO$S',
    bi.f1 === 'BI' && bi.f1cap === 'PB$S' && po.f1 === 'PO$S' && !po.f1cap, `Bi ${bi.f1}/${bi.f1cap} Po ${po.f1}/${po.f1cap}`);
}

/* ---- the effective dose split by dose group (the Retention tab) ---------------------------- */
// The shares of the dose groups add up to e at every output time; at the
// end to the coefficient itself, radon's (a model per sex) included.
{
  const cases = [
    ['103', { nuclide: 'Ra-226', route: 'ingestion', form: 'all' }],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }],
    ['60', { nuclide: 'Th-232', route: 'inhalation', type: 'S' }],
  ];
  const outputs = [0.01, 1, 100, 3650];
  let worst = 0, groups = true;
  for (const [sys, spec] of cases) {
    await (sys === '103' ? d103 : d60).prepare(spec.nuclide);
    const r = sys === '103'
      ? coefficients103(d103, { ...spec, cutoff: 1e-4 }, [100], { outputs })[0]
      : coefficients60(d60, recipe60(d60.cases, spec.route, { nuclide: spec.nuclide, bio: null, f1file: null, type: spec.type, lung: null }), [100], { outputs })[0];
    const last = r.series[r.series.length - 1];
    const sum = last.parts.reduce((a, v) => a + v, 0);
    worst = Math.max(worst, Math.abs(sum / r.E - 1));
    groups &&= r.doseGroups.length === last.parts.length && r.series.every((p) => p.parts.length === last.parts.length);
  }
  check(`the dose groups' shares add up to e (Ra-226, Rn-222 by sex, ICRP 60 Th-232): within ${worst.toExponential(1)}`, groups && worst < 1e-12);
}

/* ---- each remainder tissue's part of the remainder (ICRP 60; the tissue table's bars) ---------- */
// They add up to the remainder's dose whichever way it is taken: by mass, the
// masses changing as a child grows (Cs-137 at 3 months), or split (Si-31's
// small intestine, Gd-149's ET at 3 months), the split tissue taking half.
{
  const out = [];
  for (const [nuc, route, type] of [['Cs-137', 'ingestion'], ['Si-31', 'ingestion'], ['Gd-149', 'inhalation', 'F']]) {
    await d60.prepare(nuc);
    for (const r of coefficients60(d60, recipe60(d60.cases, route, { nuclide: nuc, bio: null, f1file: null, type, lung: null }), [100, 7300])) {
      const sum = Object.values(r.remainderShares).reduce((a, v) => a + v, 0);
      const half = !r.split || Math.abs(r.remainderShares[r.split] / (0.5 * r.H[r.split]) - 1) < 1e-12;
      out.push([`${nuc} ${r.age} d${r.split ? ` (split ${r.split})` : ''}`, Math.abs(sum / r.H.Remainder - 1), half]);
    }
  }
  check(`ICRP 60: the remainder tissues' parts add up to the remainder, by mass or split (${out.map(([k]) => k).join(', ')})`,
    out.every(([, dev, half]) => dev < 1e-12 && half) && out.some(([k]) => k.includes('split')), out.map(([k, dev]) => `${k} ${dev.toExponential(1)}`).join('; '));
}

/* ---- against the ICRP's coefficients ---------------------------------------------------- */
const SAMPLE60 = /^(H-3|Co-60|Sr-90|I-131|Cs-137|Ra-226|U-238|Pu-239|Am-241|Th-232)$/;
const SAMPLE103 = /^(H-3|Co-60|Sr-90|I-131|Cs-137|Ra-226|U-238|Pu-239|Am-241|Ce-144|Pb-210|Po-210|Na-22|K-40|Ti-44|Sn-113|Hg-203|At-210|Fr-223)$/;
const stats = (ratios) => {
  const w = (t) => (100 * ratios.filter((x) => Math.abs(x - 1) <= t).length / ratios.length);
  return { n: ratios.length, w5: w(0.05), w10: w(0.10), w20: w(0.20) };
};

/* ICRP 119's row for a case at an age: by nuclide, absorption type and f1
   (the infant's or the older ages'; a footnote mark where the adult's
   differs), H-3 and S-35 by their compound. */
function row119(rows, c, age, bio, f1) {
  let r = rows.filter((x) => x.nuclide === c.nuclide && (x.type || null) === (c.type || null));
  if (c.nuclide === 'H-3' && !c.type) return r.filter((x) => x.mark.includes('*') === (bio === 'H_ORG'));
  if (c.nuclide === 'S-35' && !c.type) return r.filter((x) => (bio === 'S_ORG' ? x.mark.includes('à') : x.mark.includes('§')));
  if (f1 == null) return r;
  const close = (a) => Math.abs(a - f1) <= 1e-6 + 1e-3 * f1;
  const exact = r.filter((x) => (age === 100 ? close(x.f1inf) : close(x.f1)));
  if (exact.length || age !== 7300) return exact;
  const marked = r.filter((x) => x.mark.split('|')[1] !== '');
  return marked.length ? marked : r.length === 1 ? r : [];
}

if (!SYSTEM || SYSTEM === '60') {
  const ref = local('icrp72.json');
  const ref119 = local('icrp119.json');
  if (!ref119) console.log('skip  ICRP 60 vs ICRP 119: no local/icrp119.json (make-local-fixtures.py --icrp119)');
  if (!ref) console.log('skip  ICRP 60 vs ICRP 72: no local/icrp72.json (make-local-fixtures.py)');
  else {
    const models = d60.models;
    const f1At = (name, age) => { const f = models.f1[name]; if (!f) return null; let v = f.f1[0]; f.ages.forEach((a, i) => { if (a <= age) v = f.f1[i]; }); return v; };
    for (const route of ['ingestion', 'inhalation']) {
      const ratios = [], ratios119 = [];
      const rr = ref.filter((x) => x.route === route);
      for (const c of d60.cases[route]) {
        if (!(ALL ? (!ONLY || ONLY.test(c.nuclide)) : SAMPLE60.test(c.nuclide))) continue;
        if (!d60.index[c.nuclide] || (c.f1 && !models.f1[c.f1]) || c.type === 'V' || c.type === 'G') continue;
        await d60.prepare(c.nuclide);
        const spec = recipe60(d60.cases, route, { nuclide: c.nuclide, bio: c.bio, f1file: c.f1, type: c.type ?? undefined, lung: route === 'inhalation' ? c.lung : undefined });
        const res = coefficients60(d60, spec, AGES_60);
        const el = c.nuclide.split('-')[0];
        const bio = parentModelName(models, d60.index, c.nuclide, route, c.bio);
        const f1name = f1FileName(models, el, route, bio, route === 'inhalation' ? c.type : null, c.f1);
        for (const r of res) {
          const f1 = f1At(f1name, r.intakeAge);
          let cands = rr.filter((x) => x.nuclide === c.nuclide && x.age === r.age && (route === 'ingestion' || x.type === c.type));
          if (c.nuclide === 'H-3' && route === 'ingestion') cands = cands.filter((x) => (bio === 'H_ORG') === /OBT/.test(x.f1));
          else if (c.nuclide === 'S-35') cands = cands.sort((a, b) => (bio === 'S_ORG' ? b.H.E - a.H.E : a.H.E - b.H.E));
          else if (f1 != null) cands = cands.filter((x) => isNaN(Number(x.f1)) || Math.abs(Number(x.f1) - f1) <= 1e-6 + 1e-3 * f1);
          if (cands[0]) ratios.push(r.E / cands[0].H.E);
          if (ref119) {
            const t = row119(ref119[route], c, r.age, bio, f1);
            if (t.length === 1) ratios119.push(r.E / t[0].e[AGES_60.indexOf(r.age)]);
          }
        }
      }
      const s = stats(ratios);
      const min = ALL ? (route === 'ingestion' ? 99 : 97) : 95;
      check(`ICRP 60 ${route} vs ICRP 72: ${s.n} values, ${s.w5.toFixed(1)} % within 5 %, ${s.w10.toFixed(1)} % within 10 %`, s.n > 0 && s.w10 >= min, `want ${min} % within 10 %`);
      if (ref119) {
        const t = stats(ratios119);
        check(`ICRP 60 ${route} vs ICRP 119 (Table ${route === 'ingestion' ? 'F.1' : 'G.1'}): ${t.n} values, ${t.w5.toFixed(1)} % within 5 %, ${t.w10.toFixed(1)} % within 10 %`, t.n > 0 && t.w10 >= min, `want ${min} % within 10 %`);
      }
    }
    // Organ doses that hang on how a chain's Other is shared out (dose60.js
    // otherTargets) and on the f1 of Type S progeny (model60.js): within 10 %
    // of ICRP 72 at every age (Ra-225 from 1 year: DCAL itself gives the
    // 3-month-old's testes 1.18 times ICRP 72's, as this page does).
    const organs = [
      ['ingestion', 'U-232', null, ['Testes', 'Ovaries', 'Red marrow'], { Testes: 'Testes', Ovaries: 'Ovaries', 'Red marrow': 'Red Marrow' }],
      ['ingestion', 'Pb-210', null, ['Testes', 'Red marrow'], { Testes: 'Testes', 'Red marrow': 'Red Marrow' }],
      ['ingestion', 'Ra-225', null, ['Testes', 'Spleen'], { Testes: 'Testes', Spleen: 'Spleen' }, 365],
      ['ingestion', 'Th-232', null, ['Spleen'], { Spleen: 'Spleen' }],
      ['inhalation', 'Pb-212', 'S', ['Kidneys', 'Testes'], { Kidneys: 'Kidneys', Testes: 'Testes' }],
    ];
    for (const [route, nuclide, type, keys, name72, from = 0] of organs) {
      await d60.prepare(nuclide);
      const res = coefficients60(d60, recipe60(d60.cases, route, { nuclide, bio: null, f1file: null, type: type ?? undefined }), AGES_60.filter((a) => a >= from));
      const off = [];
      for (const r of res) {
        const R = ref.find((x) => x.route === route && x.nuclide === nuclide && x.age === r.age && (!type || x.type === type));
        for (const k of keys) if (R && Math.abs(r.H[k] / R.H[name72[k]] - 1) > 0.1) off.push(`${k} ${r.age} d ${(r.H[k] / R.H[name72[k]]).toFixed(2)}`);
      }
      check(`ICRP 60 ${nuclide} ${route}${type ? ` Type ${type}` : ''}: ${keys.join(', ')} within 10 % of ICRP 72 at every age${from ? ' from 1 year' : ''}`, !off.length, off.join('; '));
    }
  }
}

if (!SYSTEM || SYSTEM === '103') {
  const ref = local('icrp103.json');
  if (!ref) console.log('skip  ICRP 103 vs Publication 158 and the Part 2 and 3 drafts: no local/icrp103.json (make-local-fixtures.py)');
  else {
    const ratios = [];
    const off = [];
    for (const row of ref) {
      if (!(ALL ? (!ONLY || ONLY.test(row.nuclide)) : SAMPLE103.test(row.nuclide))) continue;
      if (!d103.index[row.nuclide]) continue;
      let res;
      try {
        await d103.prepare(row.nuclide);
        res = coefficients103(d103, { nuclide: row.nuclide, route: row.route, form: row.form, cutoff: 1e-4 }, AGES_103);
      } catch (e) { off.push(`${row.nuclide} ${row.route} ${row.form}: ${e.message}`); continue; }
      res.forEach((r, k) => { if (row.e[k]) ratios.push(r.E / row.e[k]); });
      const worst = Math.max(...res.map((r, k) => (row.e[k] ? Math.abs(Math.log(r.E / row.e[k])) : 0)));
      if (worst > Math.log(1.1)) off.push(`${row.nuclide} ${row.route} ${row.form}: ${res.map((r, k) => (row.e[k] ? (r.E / row.e[k]).toFixed(2) : '-')).join(' ')}`);
    }
    const s = stats(ratios);
    const min = ALL ? 93 : 95;
    check(`ICRP 103 vs Publication 158 / Part 2 and 3 drafts: ${s.n} values, ${s.w5.toFixed(1)} % within 5 %, ${s.w10.toFixed(1)} % within 10 %`, s.n > 0 && s.w10 >= min, `want ${min} % within 10 %`);
    if (off.length) console.log(`      more than 10 % off somewhere:\n        ${off.join('\n        ')}`);
  }
}

/* ---- against the annex of Publication 158 (the ICRP InMoP Electronic Annex) ---------- */
/* Its tissues, as this page names them (sex where only one has it). */
const ANNEX_TISSUES = {
  R_marrow: 'Red marrow', Colon: 'Colon', Lungs: 'Lung', St_wall: 'Stomach', Breast: 'Breast', Ovaries: ['F', 'Gonads'],
  Testes: ['M', 'Gonads'], UB_wall: 'Bladder', Oesophagus: 'Oesophagus', Liver: 'Liver', Thyroid: 'Thyroid',
  Endost_BS: 'Bone surface', Brain: 'Brain', S_glands: 'Salivary glands', Skin: 'Skin', Adrenals: 'Adrenals',
  ET: 'Extrathoracic region', GB_wall: 'Gallbladder', Ht_wall: 'Heart', Kidneys: 'Kidneys', LN_Total: 'Lymphatic nodes',
  Muscle: 'Muscle', O_mucosa: 'Oral mucosa', Pancreas: 'Pancreas', Prostate: ['M', 'Prostate/uterus'],
  SI_wall: 'Small intestine', Spleen: 'Spleen', Thymus: 'Thymus', Uterus: ['F', 'Prostate/uterus'], Remainder: 'Remainder',
};
/* This page's form for one of the annex's materials, or null. */
function annexForm(el, E, route, m) {
  const n = m.name;
  if (route === 'injection') return '';
  if (el === 'Rn') return 'gas';
  if (route === 'inhalation') {
    const t = /^\((F|M|S)\)/.exec(n);
    return t ? t[1] : /BaCO3/.test(n) ? 'BaCO3' : /Bioorganic/.test(n) ? 'OBT' : null;
  }
  if (route === 'gas') {
    const ids = (E.inhalation?.gases || []).map((x) => x.id);
    const pick = (id) => (ids.includes(id) ? id : null);
    if (/CH3T|CH4/.test(n)) return pick('CH4');
    for (const [re, id] of [[/\(CO2\)/, 'CO2'], [/\(CO\)/, 'CO'], [/\(HTO\)/, 'HTO'], [/\(HT\)/, 'HT'], [/CH3I/, 'CH3I'], [/\(I2\)/, 'I2'],
      [/NICO4/i, 'carbonyl'], [/RuO4/, 'RuO4']]) if (re.test(n)) return pick(id);
    if (el === 'S') return pick(/Organic/.test(n) ? 'organic' : 'SO2');
    if (el === 'Te') return pick('vapour');
    return /Unspec/.test(n) ? pick('unspecified') : null;
  }
  // Ingestion: by fA (0.99 stands for 1), then by name.
  const same = (a, b) => a.every((x, k) => Math.abs(Math.min(x, 0.99) - Math.min(b[k], 0.99)) <= 1e-6 + 1e-4 * x);
  let c = (E.ingestion || []).filter((f) => same(f.fA, m.fA));
  if (c.length > 1) {
    const by = (re, id) => (re.test(n) ? c.filter((f) => f.id === id) : null);
    c = by(/Bioorganic/, 'obt') || by(/BaCO3|Bicarbonate/i, 'BaCO3')
      || by(/food|diet/i, c.some((f) => f.id === 'food') ? 'food' : c.some((f) => f.id === 'soluble') ? 'soluble' : 'diet')
      || by(/All chemical forms|soluble/i, c.some((f) => f.id === 'other') ? 'other' : 'soluble') || c;
  }
  return c[0]?.id ?? null;
}

if (!SYSTEM || SYSTEM === '103') {
  const ref = local('inmop.json');
  if (!ref) console.log('skip  ICRP 103 vs the annex of Publication 158: no local/inmop.json (make-local-fixtures.py --inmop)');
  else {
    const SAMPLE = /^(C-14|Nb-94|Cs-137|Pb-210|Ra-224|Rn-222)$/;
    const byRoute = {}, organ = [], off = [];
    for (const [nuclide, routes] of Object.entries(ref.nuclides)) {
      if (!(ALL ? (!ONLY || ONLY.test(nuclide)) : SAMPLE.test(nuclide))) continue;
      const el = nuclide.split('-')[0];
      const E = d103.elements[el];
      if (!E || !d103.index[nuclide]) continue;
      await d103.prepare(nuclide);
      for (const [route, mats] of Object.entries(routes)) for (const m of mats) {
        const form = annexForm(el, E, route, m);
        if (form == null) continue;
        let res;
        try {
          res = coefficients103(d103, { nuclide, route: route === 'gas' ? 'inhalation' : route, form: form || undefined, cutoff: 1e-4 }, AGES_103);
        } catch (e) { off.push(`${nuclide} ${route} ${form}: ${e.message}`); continue; }
        const q = res.map((r, a) => (m.e[a] ? r.E / m.e[a] : null));
        (byRoute[route] ||= []).push(...q.filter((x) => x != null));
        if (q.some((x) => x != null && Math.abs(Math.log(x)) > Math.log(1.1))) off.push(`${nuclide} ${route} ${form || ''}: ${q.map((x) => (x == null ? '-' : x.toFixed(2))).join(' ')}`);
        // Organ doses that matter to their sex's total (above 1/30 of a percent of it).
        ref.organs.forEach((o, i) => {
          const t = ANNEX_TISSUES[o];
          const [sexes, name] = Array.isArray(t) ? [[t[0]], t[1]] : [['M', 'F'], t];
          for (const sex of sexes) {
            const R = sex === 'M' ? m.hM : m.hF;
            res.forEach((r, a) => {
              const y = R[a]?.[i], tot = (R[a] || []).reduce((p, x) => p + (x || 0), 0);
              if (y > 0.01 * tot / 30) organ.push(r.H[sex][name] / y);
            });
          }
        });
      }
    }
    const all = Object.values(byRoute).flat();
    for (const [route, ratios] of Object.entries(byRoute)) {
      const t = stats(ratios);
      console.log(`      annex ${route}: ${t.n} values, ${t.w5.toFixed(1)} % within 5 %, ${t.w10.toFixed(1)} % within 10 %`);
    }
    const sE = stats(all), sH = stats(organ);
    const minE = ALL ? 97 : 98, minH = ALL ? 95 : 96;
    check(`ICRP 103 vs the annex of Publication 158, e: ${sE.n} values, ${sE.w5.toFixed(1)} % within 5 %, ${sE.w10.toFixed(1)} % within 10 %`, sE.n > 0 && sE.w5 >= minE, `want ${minE} % within 5 %`);
    check(`ICRP 103 vs the annex of Publication 158, organ doses: ${sH.n} values, ${sH.w5.toFixed(1)} % within 5 %, ${sH.w10.toFixed(1)} % within 10 %`, sH.n > 0 && sH.w10 >= minH, `want ${minH} % within 10 %`);
    if (off.length) console.log(`      more than 10 % off somewhere:\n        ${off.join('\n        ')}`);
  }
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
process.exit(failures.length ? 1 : 0);
