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
const { coefficients60, AGES_60, TISSUES_60, W_60, REMAINDER_60, remainder60 } = await import(path.join(JS, 'dose60.js'));
const { TARGETS_60: TARGETS_60_ALL } = await import(path.join(JS, 'see60.js'));
const { parentModelName, f1FileName, recipe60, assemble60 } = await import(path.join(JS, 'model60.js'));
const { coefficients103, AGES_103 } = await import(path.join(JS, 'dose103.js'));
const { emissionWeights, sAllRows, pchipSlopes, pchipEval, pchipIntegral, spectrumLines, MEV } = await import(path.join(JS, 'see103.js'));
const { firstYearWeight, dcalWeight } = await import(path.join(JS, 'solve.js'));
const { deposition103, assemble103, OPTIONS103, chainOptions103 } = await import(path.join(JS, 'model103.js'));
const { buildChain, carriedMembers } = await import(path.join(JS, 'chain.js'));
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
  const cubic = { n: 0, sum2: 0, worst: 0 }, trap = { sum2: 0 };
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
      // the same integral by the cubic through E N at the tabulated energies (see103.js spectrumOnGrid)
      const x = Float64Array.from(em.bs[0]), g = Float64Array.from(em.bs[0], (e, k) => e * em.bs[1][k]);
      const offC = pchipIntegral(x, g) / s('b') - 1;
      cubic.n++; cubic.sum2 += offC * offC; cubic.worst = Math.max(cubic.worst, Math.abs(offC)); trap.sum2 += (I / s('b') - 1) ** 2;
    }
  }
  if (sys === 'icrp103') {
    const rms = (v) => 100 * Math.sqrt(v.sum2 / cubic.n);
    check(`${sys}: the cubic through E N integrates the ${cubic.n} beta spectra to their listed mean energies within 0.3 % each, 0.05 % in the root mean square (the trapezoidal rule 0.14 %)`,
      cubic.worst < 0.003 && rms(cubic) < 0.05 && rms(trap) > 0.13 && rms(trap) < 0.16, `worst ${(100 * cubic.worst).toFixed(3)} %, rms ${rms(cubic).toFixed(4)} %, trapezoid ${rms(trap).toFixed(4)} %`);
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
      if (em.bs) {
        // a beta spectrum: E N SAF at its tabulated energies, the integral of the monotone cubic through them
        // (slopes first, then the Hermite sums: not the engine's one pass)
        const x = Float64Array.from(em.bs[0]), g = Float64Array.from(em.bs[0], (E, k) => E * em.bs[1][k] * val('electron', E)), dg = pchipSlopes(x, g);
        for (let k = 0; k + 1 < x.length; k++) { const h = x[k + 1] - x[k]; s += h * (g[k] + g[k + 1]) / 2 + h * h * (dg[k] - dg[k + 1]) / 12; }
      } else for (const [E, Y] of em.r.b || []) s += E * Y * val('electron', E);
      for (const [E, Y] of em.r.a || []) s += 20 * E * Y * val('alpha', E);
      for (const [E, Y] of [...(em.r.ar || []), ...(em.r.ff || [])]) s += 20 * E * Y * val('alpha', 2.0);
      s *= MEV;
      if (s > 0) worst = Math.max(worst, Math.abs(S[r] / s - 1));
    }
  }
  check('see103: S of every sampled pair equals brute-force PCHIP (5 nuclides, adult male)', worst < 1e-6, `worst ${worst.toExponential(2)}`);
  {
    // The integral of the monotone cubic in one pass against slopes and Hermite sums, on data of every shape
    // (zeros, plateaux, changes of sign), read from a position on as the engine reads the spectra.
    let seed = 12345, off = 0;
    const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    for (let trial = 0; trial < 5000; trial++) {
      const n = 2 + Math.floor(rnd() * 9), from = Math.floor(rnd() * 3);
      const x = new Float64Array(n + 3), g = new Float64Array(n);
      let t = rnd();
      for (let k = 0; k < n + 3; k++) { x[k] = t; t += 0.01 + rnd(); }
      for (let k = 0; k < n; k++) { const u = rnd(); g[k] = u < 0.25 ? 0 : u < 0.5 ? Math.round(rnd() * 3) : rnd() * 10 - 3; }
      const xs = x.slice(from, from + n), d = pchipSlopes(xs, g);
      let ref = 0;
      for (let k = 0; k + 1 < n; k++) { const h = xs[k + 1] - xs[k]; ref += h * (g[k] + g[k + 1]) / 2 + h * h * (d[k] - d[k + 1]) / 12; }
      off = Math.max(off, Math.abs(pchipIntegral(x, g, n, from) - ref) / (1 + Math.abs(ref)));
    }
    check('see103: the one-pass integral of the monotone cubic equals its slopes and Hermite sums (5,000 random series)', off < 1e-13, `worst ${off.toExponential(2)}`);
    // The rule of the beta spectra (OPTIONS103.betaSpectrum). Tritium's particles held under the lining of the
    // nose and throat reach its basal cells only with the top of the spectrum, where the SAF rises from nothing
    // (0 at 10 keV, 0.08 kg-1 at 15 keV, 2.4 at 20 keV; the spectrum ends at 18.6 keV): there the two rules differ
    // most, and the annex of Publication 158 has the cubic's value.
    await d103.prepare('H-3');
    const h3 = d103.emissions('H-3');
    const cub = sAllRows(ph, emissionWeights(h3, idx.energies, 'H-3')), tra = sAllRows(ph, emissionWeights(h3, idx.energies, 'H-3', 'trapezoid'));
    const row = (T, S) => idx.sources.indexOf(S) * idx.targets.length + idx.targets.indexOf(T);
    const top = cub[row('ET2-bas', 'ET2-seq')] / tra[row('ET2-bas', 'ET2-seq')], self = cub[row('Liver', 'Liver')] / tra[row('Liver', 'Liver')];
    check('see103: tritium by the cubic rule -- 1.037 of the trapezoidal rule\'s S from the particles held in ET2 to its basal cells, 0.9985 of it within the liver',
      near(top, 1.0366, 5e-4) && near(self, 0.9985, 1e-4), `${top.toFixed(4)}, ${self.toFixed(4)}`);
    let threw = false;
    try { emissionWeights(h3, idx.energies, 'H-3', 'simpson'); } catch { threw = true; }
    check('see103: a beta rule that is not known is refused', threw);
  }
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
  // The four strong fissioners DCAL's batch files leave out (gen-dose-icrp60.mjs,
  // addLeftOut) have the forms of their elements' other isotopes.
  const formsOf = (name) => { const n = c60.nuclides.find((x) => x.name === name); return n ? `${n.ingestion.map((f) => f.key).join(' ')} / ${n.inhalation.map((f) => f.key).join(' ')}` : 'none'; };
  const fis = [['Cm-248', 'Cm-246'], ['Cm-250', 'Cm-246'], ['Cf-252', 'Cf-250'], ['Cf-254', 'Cf-250']].filter(([n, like]) => formsOf(n) !== formsOf(like) || !/F\|.*M\|.*S\|/.test(formsOf(n)));
  check('catalogue ICRP 60: 248Cm, 250Cm, 252Cf and 254Cf, which DCAL\'s batch files leave out, by ingestion and Types F, M and S as 246Cm and 250Cf',
    !fis.length, fis.map(([n]) => `${n}: ${formsOf(n)}`).join('; '));
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
    ['103', { nuclide: 'Cs-137', route: 'ingestion', form: 'soluble' }, 7300, 1.3554e-8],
    ['103', { nuclide: 'Sr-90', route: 'inhalation', form: 'F' }, 100, 2.3703e-7],
    ['103', { nuclide: 'Pb-212', route: 'ingestion', form: 'all' }, 7300, 5.5951e-9],
    ['103', { nuclide: 'Pb-210', route: 'injection' }, 7300, 1.5786e-6],
    // caesium formed in barium's bone volume: that bone volume is not part of its "Other" (9 % low at 3 months otherwise)
    ['103', { nuclide: 'Ba-129', route: 'injection' }, 100, 1.0210e-10],
    // thallium formed in lead's red cells stays in red cells (Publication 137 para 481; 7 % low otherwise)
    ['103', { nuclide: 'Pb-198', route: 'injection' }, 7300, 4.1326e-11],
    // lanthanum formed on barium's bone surfaces is on its own (Publication 137 para 354; 2.8 % low at 3 months otherwise)
    ['103', { nuclide: 'Ba-140', route: 'injection' }, 100, 3.2391e-8],
    // iodine formed from tellurium: one compartment for inorganic iodide in other tissue (Publication 137 para 135; 3.7 % high otherwise)
    ['103', { nuclide: 'Te-134', route: 'injection' }, 7300, 6.6726e-11],
    // saliva passes the oesophagus by the slow transit (ICRP 158 section 2.3.2.3; 17 % low otherwise): the male's oesophagus
    ['103', { nuclide: 'I-134', route: 'injection' }, 7300, 3.8671e-11, 'Oesophagus'],
    // gallium formed in zinc's kidneys is in gallium's kidneys, which empty to the bladder (Publication 134 para 437; 2 % high otherwise)
    ['103', { nuclide: 'Zn-72', route: 'injection' }, 7300, 1.4078e-9],
    // rubidium formed from strontium on rubidium's own model, kidneys explicit (Publication 151 Table 22.3; 0.26 of this with para 484's)
    ['103', { nuclide: 'Sr-80', route: 'injection' }, 365, 1.1952e-9, 'Kidneys'],
    ['103', { nuclide: 'Ra-226', route: 'ingestion', form: 'all' }, 7300, 1.2611e-7],
    // the steps of the published calculation (OPTIONS103.ageStep): rates and S held over 1/40 year; continuous
    // in age, a 3-month-old's 110mAg is 1.0 % lower and its 90Sr 1.3 %
    ['103', { nuclide: 'Ag-110m', route: 'injection' }, 100, 1.0627e-7],
    ['103', { nuclide: 'Ag-110m', route: 'injection', rules: { ageStep: 0 } }, 100, 1.0516e-7],
    ['103', { nuclide: 'Sr-90', route: 'injection' }, 100, 6.1098e-7],
    ['103', { nuclide: 'Sr-90', route: 'injection', rules: { ageStep: 0 } }, 100, 6.0323e-7],
    // the rest of the body in a chain (OPTIONS103.otherShares): what 206Tl's model names takes the male's share of
    // 210mBi's; by her own masses the adult female's skin has 0.84 of this, and by the 10-year-old's own masses
    // all the way to 15 his testes 0.59
    ['103', { nuclide: 'Bi-210m', route: 'injection' }, 7300, 5.1894e-7, 'Skin', 'F'],
    ['103', { nuclide: 'Bi-210m', route: 'injection', rules: { otherShares: false } }, 7300, 4.3666e-7, 'Skin', 'F'],
    ['103', { nuclide: 'Bi-210m', route: 'injection' }, 3650, 1.1138e-6, 'Gonads'],
    ['103', { nuclide: 'Bi-210m', route: 'injection', rules: { otherShares: false } }, 3650, 6.5636e-7, 'Gonads'],
    // uranium's chains take the shares as every chain does: the adult female's skin after 238U, whose 234Th names
    // skin, has 0.83 of this without them. 234U's has none to take: its 230Th is not among the members the published
    // calculations carry (chain.js carriedMembers), nor is 238Pu's 234U: they are no members of the chain
    // (OPTIONS103.minorMembers); kept in it and their tissues counted, her skin would be 1.20 and 1.21 of these
    ['103', { nuclide: 'U-234', route: 'ingestion', form: 'soluble' }, 9125, 3.4690e-8],
    ['103', { nuclide: 'U-238', route: 'injection' }, 7300, 1.7316e-6, 'Skin', 'F'],
    ['103', { nuclide: 'U-238', route: 'injection', rules: { otherShares: false } }, 7300, 1.4406e-6, 'Skin', 'F'],
    ['103', { nuclide: 'U-234', route: 'injection' }, 7300, 1.6326e-6, 'Skin', 'F'],
    ['103', { nuclide: 'U-234', route: 'injection', rules: { carried: false, minorMembers: 'keep' } }, 7300, 1.9602e-6, 'Skin', 'F'],
    ['103', { nuclide: 'Pu-238', route: 'injection' }, 7300, 2.6767e-5, 'Skin', 'F'],
    ['103', { nuclide: 'Pu-238', route: 'injection', rules: { carried: false, minorMembers: 'keep' } }, 7300, 3.2436e-5, 'Skin', 'F'],
    // a progeny's adult rates from the adult age of the element taken in (OPTIONS103.chainAdult): niobium formed
    // from 93Mo from 20 years; from its own 25 the bone surface has 0.87 of this for adults and 0.86 at 15 years
    ['103', { nuclide: 'Mo-93', route: 'injection' }, 7300, 4.0676e-10, 'Bone surface'],
    ['103', { nuclide: 'Mo-93', route: 'injection', rules: { chainAdult: 'own' } }, 7300, 3.5464e-10, 'Bone surface'],
    ['103', { nuclide: 'Mo-93', route: 'injection' }, 5475, 3.8712e-10, 'Bone surface'],
    ['103', { nuclide: 'Mo-93', route: 'injection', rules: { chainAdult: 'own' } }, 5475, 3.3286e-10, 'Bone surface'],
    // radium formed in thorium's bone volume leaves as from non-exchangeable bone and stays where it was formed
    // (OPTIONS103.nonexchAt), so the 228Th it decays to is in thorium's bone volume and passes the marrow: joined
    // to radium's own compartment, the red marrow has 0.955 of this
    ['103', { nuclide: 'Th-232', route: 'injection' }, 7300, 3.6258e-4, 'Red marrow'],
    ['103', { nuclide: 'Th-232', route: 'injection', rules: { nonexchAt: 'own' } }, 7300, 3.4623e-4, 'Red marrow'],
    // polonium as a progeny names bone volume (OPTIONS103.progenyBoneVolume): with the mineral bone in its "Other",
    // the muscle after 210Bi has 0.93 of this for adults and 0.95 at 3 months
    ['103', { nuclide: 'Bi-210', route: 'injection' }, 7300, 2.5350e-9, 'Muscle'],
    ['103', { nuclide: 'Bi-210', route: 'injection', rules: { progenyBoneVolume: false } }, 7300, 2.3603e-9, 'Muscle'],
    ['103', { nuclide: 'Bi-210', route: 'injection' }, 100, 2.7903e-8, 'Muscle'],
    ['103', { nuclide: 'Bi-210', route: 'injection', rules: { progenyBoneVolume: false } }, 100, 2.6510e-8, 'Muscle'],
    // a model with trabecular and cortical marrow has no marrow in its "Other" (OPTIONS103.marrowNamed): counted
    // twice, 241Am's e is 1.4 % higher and the muscle after 225Ra, whose 225Ac has such a model, 5 % lower
    ['103', { nuclide: 'Am-241', route: 'injection' }, 7300, 1.1801e-4],
    ['103', { nuclide: 'Am-241', route: 'injection', rules: { marrowNamed: false } }, 7300, 1.1969e-4],
    ['103', { nuclide: 'Ra-225', route: 'injection' }, 7300, 7.0882e-9, 'Muscle'],
    ['103', { nuclide: 'Ra-225', route: 'injection', rules: { marrowNamed: false } }, 7300, 6.7366e-9, 'Muscle'],
    // progeny.json and elements.json as they stand: a lanthanide formed from another follows its own model (thulium
    // from 167Yb: the liver had 3.2 times this with lanthanum's; 148Tb, whose 148Gd is an alpha emitter: e 1.46 times),
    // gadolinium's adult liver takes 15 % (3.49 d-1), plutonium's added spleen leaves as its ST1 does, to Blood 2
    // (238Np: 12 times this without a way out), gallium formed from zinc takes half as much again to bone surfaces
    // before adulthood, actinium formed in the pools of radium that grew in keeps its own (229Th: muscle 0.79 of
    // this otherwise), americium formed in plutonium's Liver 3 stays in the liver (241Pu: 0.88), and the actinides
    // formed in another progeny's pools keep theirs (241Np: 0.57); actinium's skin and spleen as radium's progeny
    ['103', { nuclide: 'Yb-167', route: 'injection' }, 7300, 2.5184e-12, 'Liver'],
    ['103', { nuclide: 'Tb-148', route: 'injection' }, 7300, 8.9667e-11],
    ['103', { nuclide: 'Gd-148', route: 'injection' }, 7300, 8.0939e-5, 'Liver'],
    ['103', { nuclide: 'Np-238', route: 'injection' }, 7300, 1.2249e-9, 'Spleen'],
    ['103', { nuclide: 'Zn-72', route: 'injection' }, 365, 1.1364e-8, 'Bone surface'],
    ['103', { nuclide: 'Th-229', route: 'injection' }, 7300, 4.2619e-5, 'Muscle'],
    ['103', { nuclide: 'Pu-241', route: 'injection' }, 7300, 1.4874e-5, 'Liver'],
    ['103', { nuclide: 'Np-241', route: 'injection' }, 7300, 1.8710e-12, 'Muscle'],
    ['103', { nuclide: 'Ra-225', route: 'injection' }, 7300, 2.1581e-8, 'Spleen'],
    ['103', { nuclide: 'Ra-227', route: 'injection' }, 5475, 1.1357e-10, 'Skin'],
    // radon's chains (progeny.json, the radon set): lead and bismuth formed in radon's liver and kidneys are in
    // their own (sent to blood, the adult's liver after the gas had 1.13 of this and a 3-month-old's 0.87, the adult's
    // kidneys 1.38), those formed in its yellow marrow leave as they leave fat (red marrow 0.78 otherwise, or 1.16
    // held there for good), and the progeny's uptake to breast follows the breast's share of the blood flow by age
    // (a 3-month-old's breast after thoron 1.12 with the adult's); what radon decays to in its arterial blood is in
    // the progeny's own blood at once (with the transfer at 1000 d-1 that its venous blood keeps, the adult's kidneys
    // after the gas have 0.974 of the value); bismuth as radon's progeny goes from blood to its fast soft tissue at
    // 279 d-1, not at its own model's 300 (with 300 the adult's kidneys after the gas have 0.987 of this, the liver
    // 0.993 and the muscle 1.005; a 3-month-old's kidneys after radon swallowed 0.980 and its muscle 1.019)
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 7300, 5.0020e-10],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 7300, 2.4655e-10, 'Liver'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 100, 8.7747e-10, 'Liver'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 7300, 7.7515e-10, 'Kidneys'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 7300, 5.8927e-10, 'Red marrow'],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 7300, 1.7681e-10],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 100, 3.0786e-11, 'Breast'],
    // lead formed in a soft tissue that is not in its model leaves at 7.39 d-1 at every age, the rate Publication 137
    // states, not at its ST0's rate of the age (5.28 d-1 at 3 months, 5.32 at 15 years): with those, the bone surface
    // after thoron had 0.980 of this at 3 months and 0.976 at 15 years, a 3-month-old's kidneys 1.023 and a
    // 15-year-old's muscle 1.010
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 100, 3.2607e-10, 'Bone surface'],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 100, 6.8613e-10, 'Kidneys'],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 5475, 4.4847e-11, 'Bone surface'],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 5475, 1.1730e-11, 'Muscle'],
    // 211Pb formed (by way of 215Po) from the radon in arterial blood is in lead's plasma at once (0.987 of this
    // when it is moved there at 1000 d-1)
    ['103', { nuclide: 'Rn-219', route: 'inhalation', form: 'gas' }, 7300, 4.5582e-13, 'Bone surface'],
    // progeny formed in the stomach move on with its contents, at radon's own rate (OPTIONS103.contentsTransit):
    // 15.2 d-1 in the female from 15 years; at the tract's 20.6 her stomach has 0.87 of this and her small intestine 1.11
    ['103', { nuclide: 'Rn-222', route: 'ingestion', form: 'gas' }, 5475, 1.8995e-9, 'Stomach', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'ingestion', form: 'gas', rules: { contentsTransit: 'own' } }, 5475, 1.6577e-9, 'Stomach', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'ingestion', form: 'gas' }, 5475, 4.0945e-10, 'Small intestine', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'ingestion', form: 'gas', rules: { contentsTransit: 'own' } }, 5475, 4.5420e-10, 'Small intestine', 'F'],
    // the female's shares where she has a model of her own (OPTIONS103.sexShares; "*sexShares" of the radon set):
    // by her own masses after 222Rn, by the male's after 220Rn, as the annex has each -- her own at the ages where
    // her model is her own: radon's two models are one up to 10 years, and at 5 years her skin has the male's
    // share (by her own masses there, 1.011 of this, as it was of the annex's)
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 1825, 1.3367e-10, 'Skin', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', rules: { sexShares: 'own-all' } }, 1825, 1.3520e-10, 'Skin', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', rules: { sexShares: 'own-all' } }, 7300, 1.3373e-10, 'Gonads', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 7300, 1.3368e-10, 'Gonads', 'F'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', rules: { sexShares: 'male' } }, 7300, 1.0611e-10, 'Gonads', 'F'],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas' }, 7300, 1.9268e-11, 'Gonads', 'F'],
    ['103', { nuclide: 'Rn-220', route: 'inhalation', form: 'gas', rules: { sexShares: 'own' } }, 7300, 2.3629e-11, 'Gonads', 'F'],
    // 218At, on a branch of 0.02 %, is no member of the chain: kept in it and astatine's thyroid counted, the members
    // after it leave the thyroid out of their rest of the body and a 3-month-old's thyroid has 0.90 of this
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas' }, 100, 4.2419e-10, 'Thyroid'],
    ['103', { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', rules: { carried: false, sidePaths: 'follow', minorMembers: 'keep' } }, 100, 3.8162e-10, 'Thyroid'],
    // antimony formed in the gut takes the fA of its forms other than in food (OPTIONS103.giProgenyFA); with the
    // highest, the brain has 1.5 times this
    ['103', { nuclide: 'Sb-124n', route: 'ingestion', form: 'food' }, 7300, 5.3939e-14, 'Brain'],
    ['103', { nuclide: 'Sb-124n', route: 'ingestion', form: 'food', rules: { giProgenyFA: 'own' } }, 7300, 8.2358e-14, 'Brain'],
    // radium's chains: thorium's spleen follows ST1 by age; lead-chain members formed in another progeny's soft tissue take their own pools
    ['103', { nuclide: 'Ra-228', route: 'injection' }, 365, 1.5242e-5, 'Spleen'],
    ['103', { nuclide: 'Ra-225', route: 'injection' }, 7300, 3.5647e-7, 'Kidneys'],
    // antimony formed in tellurium's red cells is in antimony's red cells (Publication 137 para 177 calls only the
    // liver and the other soft tissue ambiguous): sent to plasma, 118Sb (3.6 min) left the blood with the plasma's,
    // and the bladder had 1.10 to 1.19 times the annex's
    ['103', { nuclide: 'Te-118', route: 'injection' }, 7300, 1.3003e-9, 'Bladder'],
    ['103', { nuclide: 'Te-118', route: 'injection' }, 7300, 1.5494e-9],
    // lead's chains (progeny.json, the lead set): bismuth formed in the soft-tissue pools of lead that is itself a
    // progeny keeps bismuth's own pools (214Bi and 214Pb by ingestion: the testes had 0.89 and 0.93 of these with
    // the 210Bi sent to blood); and bone turnover is adult from the adult age of the element taken in
    // (OPTIONS103.chainAdult), bismuth's 20 years
    ['103', { nuclide: 'Bi-214', route: 'ingestion', form: 'all' }, 7300, 2.9552e-12, 'Gonads'],
    ['103', { nuclide: 'Pb-214', route: 'ingestion', form: 'all' }, 3650, 6.7321e-11, 'Gonads'],
    ['103', { nuclide: 'Bi-214', route: 'ingestion', form: 'all' }, 5475, 1.9256e-11, 'Bone surface'],
    ['103', { nuclide: 'Bi-214', route: 'ingestion', form: 'all', rules: { chainAdult: 'own' } }, 5475, 1.7948e-11, 'Bone surface'],
    // mercury formed after lead follows mercury's own model, with red marrow, skin and gonads added (197mPb inhaled
    // as Type F: the kidneys had 1.07 of this and the spleen 1.05 with the model of Publication 137 para 479), and
    // with a spleen and bone surfaces at a tenth of para 479's shares (with none the spleen had 0.991 of this at
    // 3 months and 0.995 for adults, as it had of the annex's; bone surface 0.998); gold formed in mercury's kidneys
    // is in its own
    ['103', { nuclide: 'Pb-197m', route: 'inhalation', form: 'F' }, 7300, 1.4206e-11, 'Kidneys'],
    ['103', { nuclide: 'Pb-197m', route: 'inhalation', form: 'F' }, 7300, 5.2546e-12, 'Spleen'],
    ['103', { nuclide: 'Pb-197m', route: 'inhalation', form: 'F' }, 100, 3.3453e-11, 'Spleen'],
    ['103', { nuclide: 'Pb-197m', route: 'inhalation', form: 'F' }, 100, 6.1112e-11, 'Bone surface'],
    // a minor member is no member of the chain (OPTIONS103.minorMembers): 195mHg after 195mPb, 0.34 % of 195Tl and
    // 0.0003 of the chain's energy, gave 0.7 % of a 3-month-old's kidney dose, what the page was above the annex's
    ['103', { nuclide: 'Pb-195m', route: 'injection' }, 7300, 1.7656e-11, 'Kidneys'],
    ['103', { nuclide: 'Pb-195m', route: 'inhalation', form: 'F' }, 100, 3.3292e-11, 'Kidneys'],
    ['103', { nuclide: 'Pb-195m', route: 'inhalation', form: 'F', rules: { minorMembers: 'keep' } }, 100, 3.3523e-11, 'Kidneys'],
    // and 216At after 228Pa is a member by the chain's first year (OPTIONS103.minorEarly): the male's bladder wall is
    // then within 0.1 % of the OIR Data Viewer's, by 50 years alone 0.45 % lower
    ['103', { nuclide: 'Pa-228', route: 'injection' }, 7300, 1.0616e-8, 'Bladder'],
    ['103', { nuclide: 'Pa-228', route: 'injection', rules: { minorEarly: 0 } }, 7300, 1.0568e-8, 'Bladder'],
    // arsenic formed after selenium has selenium's pancreas, spleen, testes and ovaries in its model, out of
    // Other 2, with an uptake from plasma of 0.004, 0.004, 0.0008 and 0.00028 d-1 (the selenium set; read off the
    // annex of Publication 158: with none the pancreas after 70Se had 0.997 of this and the spleen after 72Se 0.996,
    // the testes of a 10-year-old after 70Se swallowed 0.982; with a share of arsenic's Other by mass 1.04-1.07)
    ['103', { nuclide: 'Se-70', route: 'injection' }, 7300, 4.4429e-11, 'Pancreas'],
    ['103', { nuclide: 'Se-72', route: 'injection' }, 7300, 8.2062e-9, 'Spleen'],
    ['103', { nuclide: 'Se-70', route: 'ingestion', form: 'diet' }, 3650, 8.1984e-11, 'Gonads'],
    // a member's rest of the body leaves out the tissues that only the members before it name
    // (OPTIONS103.ancestorTissues): what barium and caesium spread after 129La does not go to lanthanum's liver,
    // kidneys, marrow and gonads (the OIR Data Viewer: salivary glands 0.77 and testes 1.09 of these with them
    // shared)
    ['103', { nuclide: 'La-129', route: 'injection' }, 7300, 1.5539e-12, 'Salivary glands'],
    ['103', { nuclide: 'La-129', route: 'injection', rules: { ancestorTissues: 'shared' } }, 7300, 1.2032e-12, 'Salivary glands'],
    ['103', { nuclide: 'La-129', route: 'injection' }, 7300, 1.4803e-12, 'Gonads'],
    ['103', { nuclide: 'La-129', route: 'injection', rules: { ancestorTissues: 'shared' } }, 7300, 1.6081e-12, 'Gonads'],
    // barium formed on lanthanum's bone surfaces is on barium's, and caesium formed there leaves as caesium does
    // (the bone surface after 129La had 0.81 of this with both sent to blood at once)
    ['103', { nuclide: 'La-129', route: 'injection' }, 7300, 7.4995e-12, 'Bone surface'],
    // 137mBa has a pool in adipose tissue with its 5 % of the blood flow (the adult female's breast after 137Cs had
    // 0.98 of this with adipose tissue left in barium's other soft tissue)
    ['103', { nuclide: 'Cs-137', route: 'injection' }, 7300, 5.8080e-9, 'Breast', 'F'],
    // nickel's two kidney compartments are cobalt's (56Ni: the kidneys had 1.03 of this with the 56Co sent to blood)
    ['103', { nuclide: 'Ni-56', route: 'injection' }, 7300, 1.0040e-9, 'Kidneys'],
    // scandium formed after calcium follows scandium's own model by age (47Ca at 3 months: the liver had 0.96 of
    // this with the adult's model at every age)
    ['103', { nuclide: 'Ca-47', route: 'injection' }, 100, 4.2247e-9, 'Liver'],
    // S by age, each radiation type on its own spline (OPTIONS103.ageSpline): from bone surfaces and marrow to the
    // endosteum the photons' SAFs rise from the newborn to 1 year where the electrons' fall; with one spline for
    // their sum the 1-year-old's bone surface has 0.954 of this after 133Ba and 1.047 after 91Nb
    ['103', { nuclide: 'Ba-133', route: 'injection' }, 365, 4.8624e-8, 'Bone surface'],
    ['103', { nuclide: 'Ba-133', route: 'injection', rules: { ageSpline: 'total' } }, 365, 4.6377e-8, 'Bone surface'],
    ['103', { nuclide: 'Nb-91', route: 'injection' }, 365, 2.9024e-8, 'Bone surface'],
    ['103', { nuclide: 'Nb-91', route: 'injection', rules: { ageSpline: 'total' } }, 365, 3.0397e-8, 'Bone surface'],
    // the marrow's share of another member's rest of the body, where a member has the marrow of trabecular and
    // cortical bone (OPTIONS103.marrowShare): as red and yellow marrow the bone surface after 238U has 0.973 of
    // this (thorium's marrow) and a 10-year-old's thymus after 72Zn 0.980 (gallium's)
    ['103', { nuclide: 'U-238', route: 'injection' }, 7300, 7.1746e-6, 'Bone surface'],
    ['103', { nuclide: 'U-238', route: 'injection', rules: { marrowShare: 'red-yellow' } }, 7300, 6.9839e-6, 'Bone surface'],
    ['103', { nuclide: 'Zn-72', route: 'injection' }, 3650, 1.0445e-9, 'Thymus'],
    ['103', { nuclide: 'Zn-72', route: 'injection', rules: { marrowShare: 'red-yellow' } }, 3650, 1.0236e-9, 'Thymus'],
    // the ground state formed from an isomer taken in is a progeny (OPTIONS103.sameElement): 235U after 235mU has
    // the skin of uranium as a progeny (the female's had 0.944 of this on the parent's kinetics), 242Am after
    // 242mAm finds the parent's soft-tissue pools foreign (the skin had 1.043 of this)
    ['103', { nuclide: 'U-235m', route: 'injection' }, 7300, 2.7685e-16, 'Skin', 'F'],
    ['103', { nuclide: 'U-235m', route: 'injection', rules: { sameElement: 'parent' } }, 7300, 2.6136e-16, 'Skin', 'F'],
    ['103', { nuclide: 'Am-242m', route: 'injection' }, 7300, 1.4694e-6, 'Skin'],
    ['103', { nuclide: 'Am-242m', route: 'injection', rules: { sameElement: 'parent' } }, 7300, 1.5318e-6, 'Skin'],
    // plutonium by the five-figure rates of Publication 141 Table 18.6 (with the draft's three figures red marrow
    // was 0.22 % above the OIR Data Viewer's 2.666E-4 and muscle 0.20 % below its 2.598E-5); as a progeny, what
    // leaves the tissues returns by Blood 1 alone (muscle after 238Np was 1.3 % above the viewer's 1.105E-9); and
    // the skin and spleen of americium and californium as progeny at the viewer's two-figure rates (the skin after
    // 241Pu was 1.3 % below its 1.250E-8, the spleen after 249Bk 0.7 % above its 1.145E-8)
    ['103', { nuclide: 'Pu-239', route: 'injection' }, 7300, 2.6664e-4, 'Red marrow'],
    ['103', { nuclide: 'Pu-239', route: 'injection' }, 7300, 2.5982e-5, 'Muscle'],
    ['103', { nuclide: 'Np-238', route: 'injection' }, 7300, 1.1053e-9, 'Muscle'],
    ['103', { nuclide: 'Pu-241', route: 'injection' }, 7300, 1.2496e-8, 'Skin'],
    ['103', { nuclide: 'Bk-249', route: 'injection' }, 7300, 1.1451e-8, 'Spleen'],
    // plutonium formed after uranium follows Publication 137 para 921 (the liver after 240U had 0.934 of this with
    // plutonium's own model)
    ['103', { nuclide: 'U-240', route: 'injection' }, 7300, 3.1962e-10, 'Liver'],
    // beta spectra by the cubic rule (OPTIONS103.betaSpectrum): the 3-month-old's nose and throat after tritium
    // inhaled as Type S has 0.986 of this by the trapezoidal rule
    ['103', { nuclide: 'H-3', route: 'inhalation', form: 'S' }, 100, 2.6333e-12, 'Extrathoracic region'],
    ['103', { nuclide: 'H-3', route: 'inhalation', form: 'S', rules: { betaSpectrum: 'trapezoid' } }, 100, 2.5955e-12, 'Extrathoracic region'],
    // steps of one day where the published calculation has them (OPTIONS103.shortSteps): calcium and polonium until
    // the child is 1 year old, zinc until 5, the steps of all after; in the steps of all throughout, e is 1.009,
    // 1.011 and (zinc at 1 year) 1.002 of these
    ['103', { nuclide: 'Ca-45', route: 'injection' }, 100, 1.1921e-8],
    ['103', { nuclide: 'Ca-45', route: 'injection', rules: { shortSteps: false } }, 100, 1.2033e-8],
    ['103', { nuclide: 'Po-210', route: 'injection' }, 100, 2.2661e-5],
    ['103', { nuclide: 'Po-210', route: 'injection', rules: { shortSteps: false } }, 100, 2.2906e-5],
    ['103', { nuclide: 'Zn-65', route: 'injection' }, 365, 2.9531e-8],
    // iodide to the urinary bladder at 11.84 d-1 and barium's adult colon rate 20.16, as Publication 137 has them
    ['103', { nuclide: 'I-131', route: 'injection' }, 7300, 3.6853e-7, 'Thyroid'],
    ['103', { nuclide: 'Ba-133', route: 'injection' }, 7300, 4.2019e-9],
    // a progeny formed from a noble gas in the gas's blood is in its own blood at once (OPTIONS103.gasBlood): the
    // 218Po formed from the radon that 226Ra leaves in blood is in polonium's Plasma 2, a fifth of which goes to
    // the kidneys; moved there at 1000 d-1, a quarter decays on the way and the kidneys of a 15-year-old have 0.959
    // of this (0.963 of the annex's)
    ['103', { nuclide: 'Ra-226', route: 'injection' }, 5475, 1.0140e-6, 'Kidneys'],
    ['103', { nuclide: 'Ra-226', route: 'injection', rules: { gasBlood: 'transfer' } }, 5475, 9.7286e-7, 'Kidneys'],
    // the rest of the body as one source: its regions' SAFs averaged at the tabulated energies, then interpolated
    // (OPTIONS103.otherSAF). 93Mo's X-rays of 16.5 to 18.6 keV: pair by pair, a 1-year-old's muscle has 0.987 of
    // this and a 15-year-old's prostate 0.989, as they had of the annex's; an adult's muscle is the same either way
    ['103', { nuclide: 'Mo-93', route: 'injection' }, 365, 5.3225e-10, 'Muscle'],
    ['103', { nuclide: 'Mo-93', route: 'injection', rules: { otherSAF: 'pairs' } }, 365, 5.2551e-10, 'Muscle'],
    ['103', { nuclide: 'Mo-93', route: 'injection' }, 5475, 8.5832e-11, 'Prostate/uterus'],
    ['103', { nuclide: 'Mo-93', route: 'injection', rules: { otherSAF: 'pairs' } }, 5475, 8.4848e-11, 'Prostate/uterus'],
    ['103', { nuclide: 'Mo-93', route: 'injection', rules: { otherSAF: 'pairs' } }, 7300, 7.5152e-11, 'Muscle'],
    // polonium formed in the ST1 of a bismuth that is itself a progeny is in polonium's own soft tissue (the lead
    // set's poolNames): moved to Plasma 2 instead, a fifth of it goes to the urinary path, and after 210Pb the
    // adult's kidneys have 1.004 of this and the muscle 0.994, as they had of the annex's
    ['103', { nuclide: 'Pb-210', route: 'injection' }, 7300, 5.1168e-6, 'Kidneys'],
    ['103', { nuclide: 'Pb-210', route: 'injection' }, 7300, 1.2758e-7, 'Muscle'],
    ['103', { nuclide: 'Bi-210', route: 'injection' }, 7300, 2.5322e-9, 'Muscle'],
    // indium formed from the cadmium in silver's liver leaves it at 2.37 d-1 (the silver set): held in indium's own
    // liver, the adult's liver after 115Ag has 1.008 of this and the red marrow 0.993, as they had of the annex's
    ['103', { nuclide: 'Ag-115', route: 'injection' }, 7300, 7.0937e-11, 'Liver'],
    ['103', { nuclide: 'Ag-115', route: 'injection' }, 7300, 9.4973e-12, 'Red marrow'],
    // a member made along two ways: the lesser way is not followed where it brings less than a thousandth of the
    // chain's energy (OPTIONS103.sidePaths). 209Pb after 213Bi by way of 209Tl (2.09 %): followed, the testes of
    // a 10-year-old after 213Bi swallowed have 1.022 of this and the adult's colon 1.004, as they had of the annex's
    ['103', { nuclide: 'Bi-213', route: 'ingestion', form: 'all' }, 3650, 1.1571e-11, 'Gonads'],
    ['103', { nuclide: 'Bi-213', route: 'ingestion', form: 'all', rules: { sidePaths: 'follow' } }, 3650, 1.1820e-11, 'Gonads'],
    ['103', { nuclide: 'Te-131m', route: 'injection', rules: { sidePaths: 'follow' } }, 7300, 3.2328e-8, 'Thyroid'],
    ['103', { nuclide: 'Te-131m', route: 'injection' }, 7300, 3.2328e-8, 'Thyroid'],
    // rubidium formed in strontium's soft tissue leaves at the rate of its own Other at each age (the strontium
    // set): at the 10.3 d-1 of the condensed model the kidneys after 82Sr had 0.985 of this at 3 months and 1.021
    // for adults, as they had of the annex's
    ['103', { nuclide: 'Sr-82', route: 'injection' }, 100, 3.2757e-8, 'Kidneys'],
    ['103', { nuclide: 'Sr-82', route: 'injection' }, 7300, 3.6206e-9, 'Kidneys'],
    // rates before adulthood worked out from the adult's, not taken with the three printed figures (elements.json;
    // the annex of Publication 158 asks it tissue by tissue): caesium's rates out of tissues (with the printed
    // figures e of 137Cs had 1.0030 of this at 3 months, of 134Cs 1.0023 at 1 year), radium's and barium's from
    // plasma to soft tissues and excretion (the liver after 226Ra 0.9975 of this at 10 years), barium's and lead's
    // to the bone surfaces at the halves the tables round from (e of 133Ba 1.0020 of this at 5 years)
    ['103', { nuclide: 'Cs-137', route: 'injection' }, 100, 2.1680e-8],
    ['103', { nuclide: 'Cs-134', route: 'injection' }, 365, 1.8794e-8],
    ['103', { nuclide: 'Ra-226', route: 'injection' }, 3650, 7.5729e-7, 'Liver'],
    ['103', { nuclide: 'Ba-133', route: 'injection' }, 1825, 6.3509e-9],
    ['103', { nuclide: 'Ba-140', route: 'injection' }, 5475, 2.1122e-8, 'Red marrow'],
    ['103', { nuclide: 'Pb-210', route: 'injection' }, 3650, 1.0439e-5, 'Kidneys'],
    // lead as progeny: the rates to its five added tissues before adulthood with two figures (the lead set; read off
    // the annex of Publication 158: scaled without rounding, a 1-year-old's ovaries had 1.005 of this after 214Bi
    // swallowed and after 224Ra)
    ['103', { nuclide: 'Bi-214', route: 'ingestion', form: 'all' }, 365, 6.8900e-11, 'Gonads', 'F'],
    ['103', { nuclide: 'Ra-224', route: 'injection' }, 365, 2.4514e-7, 'Gonads', 'F'],
    // iodine as tellurium's progeny: the organic iodine of other tissue in one compartment, its rates by age (the
    // tellurium set): with the characteristic model's two, the brain after 131Te swallowed had 1.007 of this at
    // 3 months and the liver after 133Te 1.004
    ['103', { nuclide: 'Te-131', route: 'ingestion', form: 'all' }, 100, 2.6822e-12, 'Brain'],
    ['103', { nuclide: 'Te-133', route: 'ingestion', form: 'all' }, 100, 2.3665e-11, 'Liver'],
    // indium as silver's progeny: muscle and pancreas taken out of ST0 (added on top, the red marrow of a
    // 3-month-old after 115Ag swallowed had 0.991 of this); rhodium formed in palladium's ST pools in its own (sent
    // to blood, the adult's testes after 101Ag inhaled as Type F had 0.991 of this)
    ['103', { nuclide: 'Ag-115', route: 'ingestion', form: 'all' }, 100, 1.2399e-11, 'Red marrow'],
    ['103', { nuclide: 'Ag-101', route: 'inhalation', form: 'F' }, 7300, 3.7859e-14, 'Gonads'],
    // the alimentary tract has its adult values, the absorbed fractions among them, from 20 years, also for lead,
    // whose systemic model has them from 25 (OPTIONS103.tractAdult): lead that the liver secretes is absorbed again
    // by 0.3 at 15 years and by 0.2 in adults, and with that change spread to 25 years every tissue after 202Pb,
    // 205Pb and 210Pb taken in at 15 years was 0.2 % above the annex's
    ['103', { nuclide: 'Pb-205', route: 'injection' }, 5475, 4.9310e-10],
    ['103', { nuclide: 'Pb-210', route: 'ingestion', form: 'all' }, 5475, 6.8737e-7],
    // calcium absorbed by 0.499 at 1 to 15 years (with the stated 0.5, 1.0020 of this, as it was of the annex's)
    ['103', { nuclide: 'Ca-45', route: 'ingestion', form: 'all' }, 1825, 1.3565e-9],
    ['60', { nuclide: 'Po-210', route: 'ingestion' }, 7300, 1.206e-6],
  ];
  for (const [sys, spec, age, want, tissue, sex = 'M'] of pins) {
    await (sys === '103' ? d103 : d60).prepare(spec.nuclide);
    const r = sys === '103'
      ? coefficients103(d103, { ...spec, cutoff: 1e-4 }, [age])[0]
      : coefficients60(d60, recipe60(d60.cases, spec.route, { nuclide: spec.nuclide, bio: null, f1file: null }), [age])[0];
    const got = tissue ? r.H[sex][tissue] : r.E;
    const how = spec.rules ? ` with ${JSON.stringify(spec.rules).replace(/"/g, '')}` : '';
    check(`pinned: ${sys} ${spec.nuclide} ${spec.route} ${spec.form || ''}${how} at ${age} d${tissue ? `, ${tissue} (${sex === 'F' ? 'female' : 'male'}),` : ''} is ${want.toExponential(3)}`, near(got, want, 0.002), got.toExponential(4));
  }
  // Rules whose effect is of the size the pins allow: each as the ratio of the rule switched off to the rule.
  const eOf = async (nuclide, age, rules) => { await d103.prepare(nuclide); return coefficients103(d103, { nuclide, route: 'injection', cutoff: 1e-4, rules }, [age])[0].E; };
  const ratio = async (nuclide, age, rules) => (await eOf(nuclide, age, rules)) / (await eOf(nuclide, age));
  const beta = [await ratio('H-3', 7300, { betaSpectrum: 'trapezoid' }), await ratio('Y-92', 7300, { betaSpectrum: 'trapezoid' }), await ratio('Ni-63', 7300, { betaSpectrum: 'trapezoid' })];
  check('103: by the trapezoidal rule e of 3H, 92Y and 63Ni by injection is 1.0015, 1.0028 and 1.0006 of the cubic rule\'s',
    near(beta[0], 1.0015, 2e-4) && near(beta[1], 1.0028, 2e-4) && near(beta[2], 1.0006, 2e-4), beta.map((x) => x.toFixed(4)).join(', '));
  const zn = await ratio('Zn-65', 365, { shortSteps: false });
  check('103: zinc at 1 year in the steps of all has e 1.0020 of the one-day steps\'', near(zn, 1.0020, 2e-4), zn.toFixed(4));
  const same = [await ratio('Zn-65', 1825, { shortSteps: false }), await ratio('Ca-45', 365, { shortSteps: false }), await ratio('Sr-90', 100, { shortSteps: false })];
  check('103: the one-day steps end where the table says -- zinc at 5 years, calcium at 1 year and strontium at 3 months are untouched', same.every((x) => x === 1), same.join(', '));
  check('103: OPTIONS103.shortSteps lists calcium and polonium before 1 year and zinc before 5, in steps of one day until that age',
    JSON.stringify(OPTIONS103.shortSteps) === JSON.stringify({ step: 1, before: { Ca: 365, Po: 365, Zn: 1825 }, until: 'age' }), JSON.stringify(OPTIONS103.shortSteps));
  // The one-day steps end at the age the table gives, the steps of all follow: with one-day steps to the end every
  // tissue of 41Ca at 3 months was 0.1 % below the annex of Publication 158.
  {
    const end = { shortSteps: { ...OPTIONS103.shortSteps, until: 'end' } };
    await d103.prepare('Ca-41');
    const at = (rules) => coefficients103(d103, { nuclide: 'Ca-41', route: 'injection', cutoff: 1e-4, rules }, [100])[0];
    const now = at(), old = at(end), e = old.E / now.E, mu = old.H.M.Muscle / now.H.M.Muscle;
    check('103: the one-day steps last until 1 year of age for calcium, then the steps of all: 41Ca at 3 months with one-day steps to the end has e 0.9990 and muscle 0.9989 of this',
      near(e, 0.9990, 1e-4) && near(mu, 0.9989, 1e-4), `${e.toFixed(5)} ${mu.toFixed(5)}`);
  }
  const pbTract = [await ratio('Pb-205', 5475, { tractAdult: 'element' }), await ratio('Pb-205', 3650, { tractAdult: 'element' }), await ratio('Pb-205', 9125, { tractAdult: 'element' }), await ratio('Cs-137', 5475, { tractAdult: 'element' })];
  await d103.prepare('Pb-205');
  const pbAges = (rules) => { const s = assemble103(d103, { nuclide: 'Pb-205', route: 'injection', cutoff: 1e-4, intakeAge: 5475, rules }); return [s.intake.ages.at(-1), s.spec.adultAge]; };
  check('103: the alimentary tract is adult from 20 years where lead\'s systemic model is from 25 -- with the tract adult from 25 too, e of 205Pb is 1.0021 of this at 15 years, 1.0004 at 10, the same for adults, and caesium (adult at 20) is untouched',
    near(pbTract[0], 1.0021, 2e-4) && near(pbTract[1], 1.0004, 2e-4) && pbTract[2] === 1 && pbTract[3] === 1
    && pbAges().join() === '7300,9125' && pbAges({ tractAdult: 'element' }).join() === '9125,9125' && OPTIONS103.tractAdult === 'twenty',
    `${pbTract.map((x) => x.toFixed(4)).join(' ')}; tract and systemic adult ages ${pbAges().join(' ')}`);
  // A half-life given in years has 365 days to the year (OPTIONS103.yearDays), as the 50 years of the dose have.
  const yr = [await ratio('Fe-55', 7300, { yearDays: 365.25 }), await ratio('Co-60', 7300, { yearDays: 365.25 }), await ratio('Tb-148', 7300, { yearDays: 365.25 }), await ratio('I-131', 7300, { yearDays: 365.25 })];
  await d103.prepare('Co-60');
  const coOf = (rules) => assemble103(d103, { nuclide: 'Co-60', route: 'injection', cutoff: 1e-4, intakeAge: 7300, rules }).members[0];
  check('103: a half-life given in years decays by 365 days to the year -- by the decay data\'s 365.25, e of 55Fe is 1.0005 of this and of 60Co 1.0002, of 148Tb, whose 148Gd lives 75 years, 0.9996; 131I, in days, is untouched, and T stays the data\'s',
    near(yr[0], 1.0005, 5e-5) && near(yr[1], 1.0002, 5e-5) && near(yr[2], 0.9996, 5e-5) && yr[3] === 1 && OPTIONS103.yearDays === 365
    && near(coOf().lambda, Math.LN2 / (5.2713 * 365), 1e-7) && near(coOf({ yearDays: 365.25 }).lambda, Math.LN2 / (5.2713 * 365.25), 1e-7) && near(coOf().T, 5.2713 * 365.25, 1e-7),
    `${yr.map((x) => x.toFixed(5)).join(' ')}; 60Co lambda ${coOf().lambda.toExponential(6)} and ${coOf({ yearDays: 365.25 }).lambda.toExponential(6)}, T ${coOf().T}`);
  const rate = (el, a, b) => d103.elements[el].systemic.default.transfers.find((x) => x[0] === a && x[1] === b)[2];
  check('103 data: iodide goes to the urinary bladder at 11.84 d-1 at every age, barium to the adult\'s colon at 20.16 (Publication 137)',
    rate('I', 'Blood iodide', 'UB contents').every((x) => x === 11.84) && rate('Ba', 'Blood', 'RC contents')[5] === 20.16 && rate('Ba', 'Blood', 'RC contents')[0] === 6.72,
    `${rate('I', 'Blood iodide', 'UB contents')}; ${rate('Ba', 'Blood', 'RC contents')}`);
  // Rates before adulthood that follow from the adult's by a stated rule are held as worked out, with seven figures,
  // where the ICRP's coefficients show it was done so; every one rounds to the three figures its table prints.
  const from = (el, a) => d103.elements[el].systemic.default.transfers.filter((x) => x[0] === a);
  const tissues = d103.elements.Cs.systemic.default.transfers.filter((x) => x[0] !== 'Blood');
  const g7 = (x) => Number(x.toPrecision(7));
  check('103 data: caesium\'s rates out of tissues before adulthood are the adult\'s times 4, 3.5, 2.5, 2 and 1.3 (Publication 158 para 448), all 37; plasma to Other 1 keeps the outflow from plasma the same at every age (19.06, 19.06, 13.06, 8.56, 9.71, 9.71)',
    tissues.length === 37 && tissues.every((t) => [4, 3.5, 2.5, 2, 1.3].every((f, a) => t[2][a] === g7(t[2][5] * f)))
    && rate('Cs', 'Blood', 'Other 1').join() === '19.06,19.06,13.06,8.56,9.71,9.71'
    && [0, 1, 2, 3, 4].every((a) => near(from('Cs', 'Blood').reduce((q, t) => q + t[2][a], 0), from('Cs', 'Blood').reduce((q, t) => q + t[2][5], 0), 1e-9)),
    `${tissues.length} rows; kidneys to blood ${rate('Cs', 'Kidneys', 'Blood')}; plasma to Other 1 ${rate('Cs', 'Blood', 'Other 1')}`);
  const share = [0.75, 0.45, 0.40, 0.56, 0.74], soft = (el) => from(el, 'Blood').filter((t) => !/bone surf/.test(t[1]));
  check('103 data: radium\'s, barium\'s and calcium\'s rates from plasma to soft tissues and excretion before adulthood are the adult\'s times (1 - B)/(1 - 0.25), B the bone\'s share 0.75, 0.45, 0.40, 0.56, 0.74; strontium keeps the printed figures (lead: see below)',
    soft('Ra').length === 7 && soft('Ba').length === 5 && soft('Ca').length === 5 && ['Ra', 'Ba', 'Ca'].every((el) => soft(el).every((t) => share.every((b, a) => t[2][a] === g7(t[2][5] * (1 - b) / 0.75))))
    && rate('Sr', 'Blood', 'UB contents').join() === '0.577,1.27,1.38,1.02,0.6,1.73' && rate('Sr', 'ST0', 'Blood').join() === '0.833,1.83,2,1.47,0.867,2.5',
    `radium to ST0 ${rate('Ra', 'Blood', 'ST0')}; barium to ST0 ${rate('Ba', 'Blood', 'ST0')}; calcium to ST0 ${rate('Ca', 'Blood', 'ST0')}`);
  check('103 data: barium\'s rates to the bone surfaces at 5, 10 and 15 years are the halves its table and radium\'s round from (6.225, 9.875, 14.45 and 21.775, 29.325, 37.35: 0.40, 0.56, 0.74 of 70 d-1), lead\'s half of them; radium\'s as printed',
    rate('Ba', 'Blood', 'Trab bone surf').join() === '10.5,6.3,6.225,9.875,14.45,9.72' && rate('Ba', 'Blood', 'Cort bone surf').join() === '42,25.2,21.775,29.325,37.35,7.78'
    && rate('Pb', 'Blood', 'Trab bone surf').join() === '5.25,3.15,3.1125,4.9375,7.225,4.86' && rate('Pb', 'Blood', 'Cort bone surf').join() === '21,12.6,10.8875,14.6625,18.675,3.89'
    && rate('Ra', 'Blood', 'Trab bone surf').join() === '10.5,6.3,6.23,9.87,14.4,9.72' && rate('Ra', 'Blood', 'Cort bone surf').join() === '42,25.2,21.8,29.3,37.4,7.78',
    `barium ${rate('Ba', 'Blood', 'Trab bone surf')} | ${rate('Ba', 'Blood', 'Cort bone surf')}; lead ${rate('Pb', 'Blood', 'Trab bone surf')} | ${rate('Pb', 'Blood', 'Cort bone surf')}`);
  // Calcium's absorbed fraction at 1 to 15 years: Publication 158 and the head of its annex state 0.5, the annex's
  // numbers are those of 0.499 (swallowed 1.0020 of them with 0.5 at each of the four ages, injected 1.0000).
  await d103.prepare('Ca-41');
  const caAges = [100, 365, 1825, 3650, 5475, 9125], ca = d103.elements.Ca;
  const caIn = coefficients103(d103, { nuclide: 'Ca-41', route: 'ingestion', form: 'all', cutoff: 1e-4 }, caAges), caInj = coefficients103(d103, { nuclide: 'Ca-41', route: 'injection', cutoff: 1e-4 }, caAges);
  const caShare = caAges.map((_, a) => caIn[a].H.M['Bone surface'] / caInj[a].H.M['Bone surface']);
  check('103 data: calcium is absorbed by 0.499 at 1 to 15 years (stated: 0.5), swallowed, cleared from the airways or secreted: the bone surface after 41Ca swallowed has 0.600, 0.499, 0.499, 0.499, 0.499 and 0.400 of an injection\'s',
    [ca.ingestion[0].fA, ca.fAinhaled, ca.fAmax].every((f) => f.join() === '0.6,0.499,0.499,0.499,0.499,0.4') && ca.ingestion.length === 1
    && [0.6, 0.499, 0.499, 0.499, 0.499, 0.4].every((f, a) => near(caShare[a], f, 5e-4)),
    caShare.map((x) => x.toFixed(4)).join(' '));
}

/* ---- ICRP 103 chains: the members that count, and the models progeny follow --------------- */
// The members the published calculations carry (chain.js carriedMembers): a
// thousandth of the chain's energy over 50 years, with the alpha weighting or
// without. Only their models' tissues count as named by a chain.
{
  const carriedOf = (n) => carriedMembers(d103.index, buildChain(d103.index, n, { cutoff: 1e-4 }).members.map((m) => m.name));
  const c = { cm243: carriedOf('Cm-243'), u234: carriedOf('U-234'), pu238: carriedOf('Pu-238'), pu239: carriedOf('Pu-239'), u233: carriedOf('U-233'), u237: carriedOf('U-237'), ac225: carriedOf('Ac-225'), ac227: carriedOf('Ac-227'), rn222: carriedOf('Rn-222'), th232: carriedOf('Th-232') };
  check('carried members: 239Pu after 243Cm, 230Th after 234U, 234U after 238Pu and 235mU after 239Pu are not; 229Th after 233U, 237Np after 237U, 209Pb after 225Ac and 207Tl after 227Ac are',
    !c.cm243.has('Pu-239') && !c.u234.has('Th-230') && !c.pu238.has('U-234') && !c.pu239.has('U-235m')
    && c.u233.has('Th-229') && c.u237.has('Np-237') && c.ac225.has('Pb-209') && c.ac227.has('Tl-207'),
    Object.entries(c).map(([k, v]) => `${k}: ${[...v].join(' ')}`).join(' | '));
  check('carried members: 218At and 218Rn, on a branch of 0.02 % that joins 214Po again, and 210Tl are not, though 214Po and 210Pb below them are; 228Ra, which emits next to nothing, is',
    !c.rn222.has('At-218') && !c.rn222.has('Rn-218') && !c.rn222.has('Tl-210') && c.rn222.has('Po-214') && c.rn222.has('Pb-210') && c.rn222.has('Po-210') && c.th232.has('Ra-228') && c.th232.has('Tl-208'),
    `${[...c.rn222].join(' ')} | ${[...c.th232].join(' ')}`);
  // What a progeny's model is, as progeny.json and the element files give it.
  const modelOf = async (parent, member) => {
    await d103.prepare(parent);
    const sys = assemble103(d103, { nuclide: parent, route: 'injection', cutoff: 1e-4, intakeAge: d103.elements[parent.split('-')[0]].adultAge || 7300 });
    return sys.members.find((m) => m.name === member).progeny?.model;
  };
  const rate = (model, a, b) => { const t = model?.transfers.find(([x, y]) => x === a && y === b); return t ? t[2] : null; };
  const tm = await modelOf('Yb-167', 'Tm-167');
  check('thulium formed from 167Yb follows thulium\'s own model: blood to Liver 1 at 1.16 d-1 (lanthanum\'s is 11.6)',
    near(rate(tm, 'Blood', 'Liver 1')?.at(-1), 1.16, 1e-6), JSON.stringify(rate(tm, 'Blood', 'Liver 1')));
  const pu = await modelOf('Np-238', 'Pu-238');
  check('plutonium as a progeny: the added spleen and skin leave as ST1 does, to Blood 2 at 0.001386 d-1',
    near(rate(pu, 'Spleen', 'Blood 2')?.at(-1), 0.001386, 1e-6) && near(rate(pu, 'Skin', 'Blood 2')?.at(-1), 0.001386, 1e-6) && near(rate(pu, 'ST1', 'Blood 2')?.at(-1), 0.001386, 1e-6),
    `${JSON.stringify(rate(pu, 'Spleen', 'Blood 2'))} ${JSON.stringify(rate(pu, 'Spleen', 'Blood 1'))}`);
  check('plutonium as a progeny: what leaves the tissues returns by Blood 1 alone (Blood 2 to Blood 1 96.5 d-1, to the bladder 3.5, none to ST0, which Blood 1 feeds at 0.33), skin 0.0025 d-1 and spleen a third of it, out of ST1',
    rate(pu, 'Blood 2', 'ST0') === null && near(rate(pu, 'Blood 2', 'Blood 1')?.at(-1), 96.5, 1e-9) && near(rate(pu, 'Blood 2', 'UB cont')?.at(-1), 3.5, 1e-9) && near(rate(pu, 'Blood 1', 'ST0')?.at(-1), 0.33, 1e-9)
    && near(rate(pu, 'Blood 1', 'Skin')?.at(-1), 0.0025, 1e-9) && near(rate(pu, 'Blood 1', 'Spleen')?.at(-1), 0.000833, 1e-9) && near(rate(pu, 'Blood 1', 'ST1')?.at(-1), 0.018511 - 0.0025 - 0.000833, 1e-9) && !pu.compartments['Blood 0'],
    `${JSON.stringify(rate(pu, 'Blood 2', 'ST0'))} ${rate(pu, 'Blood 2', 'Blood 1')?.at(-1)} ${rate(pu, 'Blood 1', 'Skin')?.at(-1)} ${rate(pu, 'Blood 1', 'Spleen')?.at(-1)} ${rate(pu, 'Blood 1', 'ST1')?.at(-1)}`);
  {
    const own = d103.elements.Pu.systemic.default, r = (a, b) => rate(own, a, b);
    {
      // Silver's blood to its two soft-tissue pools at 12.84 d-1, 21.4 % of the 60 d-1 that leaves Blood 1, where the
      // tables print 12.8: with 12.8 the soft tissues after 111Ag were 0.2 % below the annex at every age.
      await d103.prepare('Ag-111');
      const ag = d103.elements.Ag.systemic.default.transfers.filter((x) => x[0] === 'Blood 1' && /^ST[01]$/.test(x[1]));
      const doses = () => { const r = coefficients103(d103, { nuclide: 'Ag-111', route: 'injection', cutoff: 1e-4 }, [7300])[0]; return [r.H.M.Muscle, r.H.M.Liver]; };
      const now = doses(), keep = ag.map((x) => x[2]); ag.forEach((x) => { x[2] = x[2].map(() => 12.8); }); const printed = doses(); ag.forEach((x, i) => { x[2] = keep[i]; });
      check('103 data: silver goes from blood to ST0 and ST1 at 12.84 d-1 (21.4 % of 60), not the printed 12.8 -- 111Ag\'s muscle 1.0022 of what 12.8 gives, its liver 0.9995',
        ag.length === 2 && ag.every((x) => x[2].every((v) => v === 12.84)) && near(now[0] / printed[0], 1.0022, 1e-4) && near(now[1] / printed[1], 0.9995, 1e-4),
        `${ag.map((x) => x[2][0])} | ${(now[0] / printed[0]).toFixed(5)} ${(now[1] / printed[1]).toFixed(5)}`);
    }
    {
      const y = (to) => d103.elements.Y.systemic.default.transfers.find((x) => x[0] === 'Blood 1' && x[1] === to)[2];
      const fits = (to) => { const v = y(to), a = v[5]; return [2 / 3, 5 / 6, 5 / 6, 5 / 6, 5 / 6, 1].every((f, k) => near(v[k], a * f, 1e-6)); };
      check('103 data: yttrium\'s rates out of blood before adulthood are the adult\'s x 2/3 at 3 months and x 5/6 from 1 to 15 years (to the liver 1.106667 and 1.383333 for the printed 1.11 and 1.38)',
        ['Blood 2', 'Liver 0', 'Kidneys', 'SI contents', 'UB contents', 'ST0', 'ST1'].every(fits) && near(y('Liver 0')[0], 1.106667, 1e-6), JSON.stringify(y('Liver 0')));
      // Zirconium and niobium by the same rule (Publication 158 paras 366-367, 373-374): to the bone surfaces the adult's x 1.5
      // and x 1.25, to every other place the adult's x (1-B)/(1-A), A = 0.15 and 0.03 of the outflow from Blood 1. With the
      // printed figures the kidneys after 93Zr were 0.26 % below the annex at 1 year.
      const zrnb = ['Zr', 'Nb'].map((el) => {
        const T = d103.elements[el].systemic.default.transfers.filter((x) => x[0] === 'Blood 1'), bone = (x) => /bone surf/.test(x[1]);
        const A = T.filter(bone).reduce((s, x) => s + x[2][5], 0) / T.reduce((s, x) => s + x[2][5], 0);
        return { A, ok: T.length === 9 && [1.5, 1.25, 1.25, 1.25, 1.25, 1].every((g, k) => T.every((x) => near(x[2][k], x[2][5] * (bone(x) ? g : (1 - g * A) / (1 - A)), 1e-6))) };
      });
      const zk = d103.elements.Zr.systemic.default.transfers.find((x) => x[0] === 'Blood 1' && x[1] === 'Kidneys')[2];
      check('103 data: zirconium\'s and niobium\'s rates out of blood before adulthood are the adult\'s x 1.5 and x 1.25 to the bone surfaces and x (1-B)/(1-A) elsewhere, A = 0.15 and 0.03 (zirconium\'s kidneys 0.01139706 and 0.01194853 for the printed 0.0114 and 0.0119)',
        zrnb.every((z) => z.ok) && near(zrnb[0].A, 0.15, 1e-9) && near(zrnb[1].A, 0.03, 1e-9) && near(zk[0], 0.01139706, 1e-7) && near(zk[1], 0.01194853, 1e-7),
        `${zrnb.map((z) => `${z.A} ${z.ok}`).join(' | ')} | ${JSON.stringify(zk)}`);
      // Carbon's rates from its tissues and bone surfaces to blood: the adult's x 4, 2.5, 2.5, 2 and 1.2 at every place
      // (Publication 158 para 254), the organic part's too; with Table 6.3's 0.0248 and 0.0119 from the long-term tissue
      // every tissue after organic 14C was 0.1 % below the annex at 1, 5 and 15 years.
      const ct = d103.elements.C.systemic.generic.transfers.filter((x) => !/^Blood|bone vol/.test(x[0]) && /^Blood/.test(x[1]));
      const lt = ct.find((x) => x[0] === 'Long-term tissue' && x[1] === 'Blood 1')?.[2];
      check('103 data: carbon\'s rates from its tissues and bone surfaces to blood before adulthood are the adult\'s x 4, 2.5, 2.5, 2 and 1.2, the organic part\'s too (from the long-term tissue 0.02475 and 0.01188 for the printed 0.0248 and 0.0119)',
        ct.length === 12 && ct.every((x) => [4, 2.5, 2.5, 2, 1.2, 1].every((f, k) => near(x[2][k], x[2][5] * f, 1e-9))) && lt?.[1] === 0.02475 && lt?.[4] === 0.01188,
        `${ct.length} ${JSON.stringify(lt)}`);
      // Calcium's rates from blood to its soft tissues and excretion, and from ST0 back to blood, are the adult's x (1-B)/(1-A),
      // A = 0.25 (1/3, 11/15, 4/5, 44/75, 26/75): with Table 9.2's 1.01 out of ST0 at 15 years (for 1.00533) every soft
      // tissue after 45Ca at 15 years was 0.1 % below the annex.
      const AE = [1 / 3, 11 / 15, 4 / 5, 44 / 75, 26 / 75, 1];
      const caT = d103.elements.Ca.systemic.default.transfers.filter((x) => (x[0] === 'Blood' && !/bone surf/.test(x[1])) || (x[0] === 'ST0' && x[1] === 'Blood'));
      const caST0 = caT.find((x) => x[0] === 'ST0')[2];
      check('103 data: calcium\'s rates from blood to the soft tissues and excretion and from ST0 back to blood are the adult\'s x (1-B)/(1-A) (out of ST0 1.005333 at 15 years for the printed 1.01)',
        caT.length === 6 && caT.every((x) => AE.every((f, k) => near(x[2][k], x[2][5] * f, 1e-6))) && near(caST0[4], 1.005333, 1e-6), JSON.stringify(caST0));
      // Phosphorus by para 269: its bone surfaces take calcium's deposition x 0.8 at each age (calcium's rates x 32/15 out of
      // phosphorus's 40 d-1), everything else from plasma the adult's x 0.5, 0.8, 0.85, 0.69, 0.51; the adult's as printed.
      const pT = d103.elements.P.systemic.default.transfers.filter((x) => x[0] === 'Plasma');
      const caBone = (to) => d103.elements.Ca.systemic.default.transfers.find((x) => x[0] === 'Blood' && x[1] === to)[2];
      const pCort = pT.find((x) => x[1] === 'Cort bone surf')[2];
      check('103 data: phosphorus\'s children\'s rates from plasma: to the bone surfaces calcium\'s x 32/15 (17.06667 to cortical surface at 15 years for the printed 17.1), elsewhere the adult\'s x 0.5, 0.8, 0.85, 0.69, 0.51',
        pT.length === 11 && pT.every((x) => (/bone surf/.test(x[1])
          ? [0, 1, 2, 3, 4].every((k) => near(x[2][k], caBone(x[1])[k] * 32 / 15, 1e-6))
          : [0.5, 0.8, 0.85, 0.69, 0.51, 1].every((f, k) => near(x[2][k], x[2][5] * f, 1e-6)))) && near(pCort[4], 17.06667, 1e-6) && pCort[5] === 3.56,
        JSON.stringify(pCort));
      // Lead's rates from blood to the red cells and to ST0 are the adult's x (1-B)/(1-A), A = 0.125, B = 0.375, 0.225, 0.20,
      // 0.28, 0.37; its other rates stay as Table 29.2 prints them, as the annex has them (with the kidneys' worked out,
      // 212Pb's kidneys at 10 and 15 years came out -0.11 and +0.14 %).
      const PBF = [0.375, 0.225, 0.2, 0.28, 0.37, 0.125].map((b) => (1 - b) / 0.875);
      const pb = (to) => d103.elements.Pb.systemic.default.transfers.find((x) => x[0] === 'Blood' && x[1] === to)[2];
      check('103 data: lead\'s rates from blood to the red cells and to ST0 are the adult\'s x (1-B)/(1-A) (23.04 and 18.23451 at 10 years for the printed 23.0 and 18.2); its kidneys keep the printed 2.02 and 1.76',
        ['Blood 1', 'ST0'].every((to) => PBF.every((f, k) => near(pb(to)[k], pb(to)[5] * f, 1e-6))) && near(pb('Blood 1')[3], 23.04, 1e-9) && near(pb('ST0')[3], 18.23451, 1e-6)
        && pb('Kidneys 1')[3] === 2.02 && pb('Kidneys 1')[4] === 1.76 && pb('ST2')[3] === 0.115,
        `${JSON.stringify(pb('Blood 1'))} ${JSON.stringify(pb('ST0'))} ${JSON.stringify(pb('Kidneys 1'))}`);
      // Methane's blood empties at the 100 d-1 Publication 134 para 139 states for its half-time of 10 min: with ln 2 / 10 min
      // (99.81) every organ dose of 11C inhaled as methane was 0.06-0.10 % above the annex.
      const ch4 = d103.elements.C.systemic.methane.transfers.filter((x) => x[0] === 'Blood (methane)');
      check('103 data: methane\'s blood compartment empties at 100 d-1 at every age, 70 to expired air and 30 to the short-term tissue (Publication 134 para 139)',
        ch4.length === 2 && ch4.every((x) => x[2].every((v) => v === (x[1] === 'Expired air' ? 70 : 30))), JSON.stringify(ch4));
    }
    check('103 data: plutonium has the rates of Publication 141 Table 18.6 -- the adult\'s to trabecular surface 0.12474, cortical surface 0.08778 and testes 0.0002695 (children as the draft has them), and at every age 0.0001266 out of ST2, 28.95 from Blood 2 to ST0 and 0.01155 to the right colon',
      r('Blood 1', 'Trab bone surf').join() === '0.26,0.26,0.208,0.208,0.208,0.12474' && r('Blood 1', 'Cort bone surf').at(-1) === 0.08778 && r('Blood 1', 'Testes').join() === '0.0000154,0.0000231,0.0000262,0.0000308,0.000246,0.0002695'
      && r('ST2', 'Blood 2').every((x) => x === 0.0001266) && r('Blood 2', 'ST0').every((x) => x === 28.95) && r('Blood 2', 'Blood 1').every((x) => x === 67.55) && r('Blood 1', 'RC cont').every((x) => x === 0.01155)
      && r('Blood 1', 'ST1').every((x) => x === 0.018511) && r('Blood 1', 'Liver 1').join() === '0.116,0.116,0.231,0.231,0.231,0.462',
      `${r('Blood 1', 'Trab bone surf')} | ${r('Blood 1', 'Testes')} | ${r('ST2', 'Blood 2')}`);
    const am = await modelOf('Pu-241', 'Am-241'), cm = await modelOf('Am-244', 'Cm-244'), cf = await modelOf('Bk-249', 'Cf-249'), bk = await modelOf('Cf-247', 'Bk-247');
    const two = (m) => [rate(m, 'Blood', 'Skin')?.at(-1), rate(m, 'Blood', 'Spleen')?.at(-1), rate(m, 'Blood', 'ST1')?.at(-1)];
    check('the skin and spleen of an actinide as a progeny: americium and curium at 0.13 and 0.043 d-1, californium at 0.07 and 0.023, out of ST1; berkelium at 0.06 and 0.02 of what its ST1 and ST2 take (0.004656 and 0.001552)',
      [am, cm].every((m) => near(two(m)[0], 0.13, 1e-9) && near(two(m)[1], 0.043, 1e-9) && near(two(m)[2], 1.67 - 0.173, 1e-9))
      && near(two(cf)[0], 0.07, 1e-9) && near(two(cf)[1], 0.023, 1e-9) && near(two(cf)[2], 0.926 - 0.093, 1e-9)
      && near(two(bk)[0], 0.06 * 0.0776, 1e-9) && near(two(bk)[1], 0.02 * 0.0776, 1e-9),
      `Am ${two(am)} | Cm ${two(cm)} | Cf ${two(cf)} | Bk ${two(bk)}`);
  }
  {
    // Radon formed in the body is in the generic model's one blood compartment; what it decays to there is in its
    // own blood (polonium: Plasma 2). Radon taken in has its own two blood compartments, and the rule is not theirs.
    await d103.prepare('Ra-226');
    const born = (rules) => {
      const sys = assemble103(d103, { nuclide: 'Ra-226', route: 'injection', cutoff: 1e-4, intakeAge: 9125, rules });
      const nm = (c) => `${sys.members[sys.comps[c].member].name}/${sys.comps[c].name}`;
      return sys.decays.filter((x) => nm(x.from) === 'Rn-222/Blood' && /^Po-218\//.test(nm(x.to))).map((x) => nm(x.to));
    };
    const own = born(), moved = born({ gasBlood: 'transfer' });
    check('226Ra: 218Po formed from radon in blood is in polonium\'s Plasma 2 at once; with the transfer it is in a compartment of its own there',
      own.length === 1 && own[0] === 'Po-218/Plasma 2' && moved.length === 1 && /\(Rn-222\)$/.test(moved[0]), `${own} | ${moved}`);
    await d103.prepare('Rn-222');
    const rn = (rules) => coefficients103(d103, { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', cutoff: 1e-4, rules }, [7300])[0].H.M.Kidneys;
    // (to the last digits: the 218Rn on a branch of 0.02 % is such a gas, and its 214Po decays where it is formed either way)
    check('222Rn taken in: the rule leaves the progeny formed in its arterial and venous blood as they were', near(rn(), rn({ gasBlood: 'transfer' }), 1e-9), `${rn()} ${rn({ gasBlood: 'transfer' })}`);
  }
  const puU = await modelOf('U-240', 'Pu-240');
  check('plutonium formed after uranium follows Publication 137 para 921: blood to Liver 1 at 0.42 d-1 and to the soft tissue ST0 at 0.3, the spleen and skin carved from ST1',
    near(rate(puU, 'Blood', 'Liver 1')?.at(-1), 0.42, 1e-9) && near(rate(puU, 'Blood', 'ST0')?.at(-1), 0.3, 1e-9)
    && near(rate(puU, 'Blood', 'Spleen')?.at(-1), 0.0007, 1e-9) && near(rate(puU, 'Blood', 'Skin')?.at(-1), 0.0021, 1e-9),
    JSON.stringify(puU?.transfers.filter(([x]) => x === 'Blood').map((t) => [t[1], t[2].at(-1)])));
  {
    // The ground state formed from the isomer taken in (OPTIONS103.sameElement).
    await d103.prepare('U-235m');
    const spec = { nuclide: 'U-235m', route: 'injection', cutoff: 1e-4, intakeAge: 9125 };
    const asProgeny = assemble103(d103, spec).members.find((m) => m.name === 'U-235');
    const asParent = assemble103(d103, { ...spec, rules: { sameElement: 'parent' } }).members.find((m) => m.name === 'U-235');
    check('235U formed from 235mU has the model of uranium as a progeny, with skin and marrow; on the parent\'s kinetics it mirrors the parent',
      asProgeny.kind === 'spec' && near(rate(asProgeny.progeny?.model, 'Plasma', 'Skin')?.at(-1) ?? rate(asProgeny.progeny?.model, 'Blood', 'Skin')?.at(-1), 0.09, 1e-9)
      && asParent.kind === 'mirror' && asParent.of === 0, `${asProgeny.kind}, ${asParent.kind} of ${asParent.of}`);
  }
  const ga = await modelOf('Zn-72', 'Ga-72');
  check('gallium formed from zinc: blood to the bone surfaces 0.75 d-1 before adulthood, 0.5 for adults, the total outflow 5 d-1 at every age',
    ga.ages.length === 6 && near(rate(ga, 'Blood', 'Trab bone surf')[0], 0.75, 1e-9) && near(rate(ga, 'Blood', 'Trab bone surf')[5], 0.5, 1e-9)
    && [0, 5].every((a) => near(ga.transfers.filter(([x]) => x === 'Blood').reduce((s, t) => s + t[2][a], 0), 5, 1e-9)),
    JSON.stringify(rate(ga, 'Blood', 'Trab bone surf')));
  const gd = d103.elements.Gd.systemic.default.transfers.find(([a, b]) => a === 'Blood' && b === 'Liver 1')[2];
  const out = d103.elements.Gd.systemic.default.transfers.filter(([a]) => a === 'Blood').reduce((s, t) => s + t[2].at(-1), 0);
  check('gadolinium: the adult\'s liver takes 15 % of what leaves the circulation (3.49 d-1), the outflow from blood 33.3 d-1 as for every lanthanide',
    near(gd.at(-1), 3.49, 1e-9) && near(out, 33.27, 2e-3), `${gd.at(-1)} of ${out.toFixed(3)}`);
  // Radon's progeny: the identifications of the lead set kept and radon's liver and kidneys added, the yellow marrow
  // left as fat is, the breast's inflow by the breast's share of the blood flow at each age.
  await d103.prepare('Rn-222');
  const rn = assemble103(d103, { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', cutoff: 1e-4, intakeAge: 7300, sex: 'M' });
  const pb = rn.members.find((m) => m.name === 'Pb-214'), bi = rn.members.find((m) => m.name === 'Bi-214');
  const comp = (member, name) => rn.comps.findIndex((x) => rn.members[x.member].name === member && x.name === name);
  const compLike = (member, start) => rn.comps.findIndex((x) => rn.members[x.member].name === member && x.name.startsWith(start));
  const outOf = (k) => rn.transfers.filter((t) => t.from === k).map((t) => t.rates.at(-1));
  check('radon\'s progeny: no compartment of lead\'s or bismuth\'s in radon\'s liver or kidneys but their own; in its yellow marrow they leave at 0.004161 and 0.034657 d-1',
    compLike('Pb-214', 'Liver (Rn-222)') < 0 && compLike('Bi-214', 'Kidneys (Rn-222)') < 0 && comp('Pb-214', 'Liver 1') >= 0 && compLike('Pb-214', 'Other (Rn-222)') >= 0
    && near(outOf(compLike('Pb-214', 'Y-marrow 1 (Rn-222)'))[0], 0.004161, 1e-9) && near(outOf(compLike('Bi-214', 'Y-marrow 2 (Rn-222)'))[0], 0.034657, 1e-9),
    `${compLike('Pb-214', 'Liver (Rn-222)')} ${compLike('Bi-214', 'Kidneys (Rn-222)')} ${JSON.stringify(outOf(compLike('Pb-214', 'Y-marrow 1 (Rn-222)')))} ${JSON.stringify(outOf(compLike('Bi-214', 'Y-marrow 2 (Rn-222)')))}`);
  {
    // Radon's arterial blood is the progeny's own blood (polonium: Plasma 2, lead: Blood); from its venous blood they
    // move there at 1000 d-1. Lead leaves radon's other tissue at 7.39 d-1 at every age.
    const at = (age) => {
      const sys = assemble103(d103, { nuclide: 'Rn-222', route: 'inhalation', form: 'gas', cutoff: 1e-4, intakeAge: age, sex: 'M' });
      const nm = (c) => `${sys.members[sys.comps[c].member].name}/${sys.comps[c].name}`;
      const born = (from) => sys.decays.filter((x) => nm(x.from) === from).map((x) => nm(x.to)).filter((x) => !x.startsWith('At-'));
      const out = (label) => sys.transfers.filter((t) => nm(t.from) === label).map((t) => [nm(t.to), t.rates]);
      return { born, out };
    };
    const a = at(7300), i = at(100);
    check('222Rn taken in: 218Po formed in arterial blood is in polonium\'s Plasma 2 and the 214Pb it leaves there in lead\'s blood; from venous blood 218Po moves to Plasma 2 at 1000 d-1, as 214Pb does from polonium\'s Plasma 1',
      String(a.born('Rn-222/Blood-A')) === 'Po-218/Plasma 2' && String(a.born('Po-218/Plasma 2')) === 'Pb-214/Blood' && String(a.born('Rn-222/Blood-V')) === 'Po-218/Blood-V (Rn-222)'
      && JSON.stringify(a.out('Po-218/Blood-V (Rn-222)')) === '[["Po-218/Plasma 2",[1000]]]' && JSON.stringify(a.out('Pb-214/Plasma 1 (Po-218)')) === '[["Pb-214/Blood",[1000]]]',
      `${a.born('Rn-222/Blood-A')} | ${a.born('Po-218/Plasma 2')} | ${a.born('Rn-222/Blood-V')} | ${JSON.stringify(a.out('Po-218/Blood-V (Rn-222)'))}`);
    check('lead formed in radon\'s other tissue leaves at 7.39 d-1 for an adult and for a 3-month-old (whose ST0 has 5.28 d-1), bismuth at its ST0\'s 66.54',
      [a, i].every((x) => JSON.stringify(x.out('Pb-214/Other (Rn-222) (Po-218)')) === '[["Pb-214/Blood",[7.39]]]' && x.out('Bi-214/Other (Rn-222) (Po-218) (Pb-214)')[0][1].every((r) => near(r, 66.54, 1e-9)))
      && near(rate(d103.elements.Pb.systemic.default, 'ST0', 'Blood')[0], 5.28, 1e-9),
      `${JSON.stringify(i.out('Pb-214/Other (Rn-222) (Po-218)'))} ${JSON.stringify(rate(d103.elements.Pb.systemic.default, 'ST0', 'Blood'))}`);
  }
  {
    // Bismuth as radon's progeny: 279 d-1 from blood to ST0 at every age; as lead's progeny its own 300.
    await d103.prepare('Pb-214');
    const biLead = assemble103(d103, { nuclide: 'Pb-214', route: 'injection', cutoff: 1e-4, intakeAge: 7300, sex: 'M' }).members.find((m) => m.name === 'Bi-214');
    check('bismuth from blood to its fast soft tissue: 279 d-1 at every age as radon\'s progeny, 300 as lead\'s; every other rate out of blood the same',
      rate(bi.progeny.model, 'Blood', 'ST0').every((x) => near(x, 279, 1e-9)) && rate(biLead.progeny.model, 'Blood', 'ST0').every((x) => near(x, 300, 1e-9))
      && ['Liver 1', 'Kidneys 1', 'Kidneys 2', 'UB contents', 'Red marrow', 'Skin'].every((to) => near(rate(bi.progeny.model, 'Blood', to).at(-1), rate(biLead.progeny.model, 'Blood', to).at(-1), 1e-12)),
      `${JSON.stringify(rate(bi.progeny.model, 'Blood', 'ST0'))} ${JSON.stringify(rate(biLead.progeny.model, 'Blood', 'ST0'))}`);
    // Radon's own rates: those that follow from cardiac output F, blood volume V and the air volume of the lungs
    // are held with six figures (Publication 158's tables print three).
    const F = { male: [0.83, 1.2, 3.4, 5.0, 6.1, 6.5], female: [0.83, 1.2, 3.4, 5.0, 6.1, 5.9] };
    const V100 = (290 + 240 * 2.5 / 6.5) / 1.06 / 1000;
    const V = { male: [V100, 0.5, 1.4, 2.4, 4.5, 5.3], female: [V100, 0.5, 1.4, 2.4, 3.3, 3.9] };
    const FRC = { male: [0.148, 0.244, 0.767, 1.484, 2.677, 3.301], female: [0.148, 0.244, 0.767, 1.484, 2.325, 2.681] };
    let worst = 0;
    for (const sex of ['male', 'female']) {
      const T = d103.elements.Rn.systemic[sex].transfers, get = (a, b) => T.find(([x, y]) => x === a && y === b)[2];
      for (let a = 0; a < 6; a++) {
        const flow = F[sex][a] * 1440, air = a === 5 && sex === 'male' ? 3.858 : FRC[sex][a] * 3.858 / 3.30;
        const outA = T.filter(([x]) => x === 'Blood-A').reduce((q, t) => q + t[2][a], 0);
        for (const [got, want] of [[outA, flow / (0.27 * V[sex][a])], [get('Blood-V', 'RT-air')[a], flow / (0.73 * V[sex][a])], [get('RT-air', 'Blood-A')[a], flow * 0.43 / air],
          [get('Blood-A', 'Kidneys')[a], (sex === 'female' && a >= 4 ? 0.17 : 0.19) * flow / (0.27 * V[sex][a])], [get('RT-air', 'Environment')[a], a === 5 ? 2600 : Math.LN2 / [4.5, 5, 8, 11, 17][a] * 86400]]) worst = Math.max(worst, Math.abs(got / want - 1));
      }
    }
    check(`radon's rates from cardiac output, blood volume and the air of the lungs, both sexes and six ages: what leaves arterial blood, venous blood to the air, the air to arterial blood, arterial blood to kidneys, the air to the environment by its half-time (the adult's 2600 d-1): within ${worst.toExponential(1)}`, worst < 2e-5);
  }
  {
    // Where a progeny is when it is formed in a pool of another name, or across a member between.
    const bornAt = async (nuclide, from, spec = {}) => {
      await d103.prepare(nuclide);
      const sys = assemble103(d103, { nuclide, route: 'injection', cutoff: 1e-4, intakeAge: 7300, ...spec });
      const nm = (c) => `${sys.members[sys.comps[c].member].name}/${sys.comps[c].name}`;
      return { to: sys.decays.filter((x) => nm(x.from) === from).map((x) => nm(x.to)), out: (label) => sys.transfers.filter((t) => nm(t.from) === label).map((t) => [nm(t.to), t.rates]) };
    };
    const a = await bornAt('Pb-210', 'Bi-210/ST1'), b = await bornAt('Pb-210', 'Bi-210/ST0'), c = await bornAt('Bi-210', 'Bi-210/ST1'), e = await bornAt('Bi-214', 'Po-214/Other');
    check('polonium formed in the ST1 of a bismuth that is a progeny is in its own soft tissue; in that bismuth\'s ST0, or in the ST1 of the bismuth taken in, in a compartment of its own there; lead formed from polonium in that soft tissue is in lead\'s ST1',
      String(a.to) === 'Po-210/Other' && String(b.to) === 'Po-210/ST0 (Bi-210)' && String(c.to) === 'Po-210/ST1 (Bi-210)' && String(e.to) === 'Pb-210/ST1', `${a.to} | ${b.to} | ${c.to} | ${e.to}`);
    const sr = await bornAt('Sr-82', 'Sr-82/ST0', { intakeAge: 100 });
    check('82Sr: rubidium formed in strontium\'s ST0 leaves for blood at the rate of its own Other at each age, 15.33 d-1 at 3 months and 7.3 for adults',
      String(sr.to) === 'Rb-82/ST0 (Sr-82)' && JSON.stringify(sr.out('Rb-82/ST0 (Sr-82)')) === '[["Rb-82/Blood",[15.33,13.87,11.68,10.22,8.03,7.3]]]', `${sr.to} ${JSON.stringify(sr.out('Rb-82/ST0 (Sr-82)'))}`);
    // Rubidium's children's rates are worked out by the rules of the Part 3 draft's paras 227-230 (Table 20.2 rounds them):
    // plasma to muscle x 0.5, 0.5, 0.7, 0.85, to the bone surfaces x 2 through 10 years, to Other what keeps the adult's
    // total 1087.2 d-1, the tissues' outflows x 2.1, 1.9, 1.6, 1.4, 1.1. 81Sr and 83Sr, its parents in the annex, come nearer.
    {
      const rb = d103.elements.Rb.systemic.default.transfers, rr = (a, b) => rb.find((x) => x[0] === a && x[1] === b)[2];
      const tot = [0, 1, 2, 3, 4, 5].map((k) => rb.filter((x) => x[0] === 'Blood').reduce((q, x) => q + x[2][k], 0));
      check('103 data: rubidium\'s children\'s rates by the rules of their section (to muscle 127.5 at 3 months for the printed 128, out of the liver 20.958 for 21; the outflow from plasma 1087.2 at every age)',
        rr('Blood', 'Muscle').join() === '127.5,127.5,178.5,216.75,255,255' && rr('Liver', 'Blood').join() === '20.958,18.962,15.968,13.972,10.978,9.98'
        && rr('Blood', 'Other').join() === '513.5,513.5,462.5,424.25,400,400' && tot.every((x) => near(x, 1087.2, 1e-9)), `${rr('Blood', 'Muscle')} | ${tot.map((x) => x.toFixed(2))}`);
    }
    const cutOf = (n) => JSON.stringify(buildChain(d103.index, n, { cutoff: 1e-4, horizonDays: 36525, sidePaths: 1e-3 }).cut);
    // The chain followed way by way: a way is followed if what comes by it is a thousandth of the chain's energy.
    const chainOf = (n, cutoff = 1e-4) => buildChain(d103.index, n, chainOptions103({ nuclide: n, cutoff }));
    const namesOf = (n, cutoff) => chainOf(n, cutoff).members.map((m) => m.name).join();
    for (const n of ['Pb-195m', 'Ra-223', 'Ag-104m', 'U-234', 'U-235', 'Pa-228', 'Pa-230', 'Ac-224']) await d103.prepare(n);
    const pb195 = chainOf('Pb-195m'), all195 = chainOf('Pb-195m', 0);
    check('a member no followed way reaches is no member of the chain: 195mHg after 195mPb, 211Po after 223Ra, 104Ag after 104mAg, 230Th after 234U, and 218At, 218Rn and 210Tl after 226Ra; with the cut-off at none they stay',
      namesOf('Pb-195m') === 'Pb-195m,Tl-195,Hg-195,Au-195' && pb195.minor.join() === 'Hg-195m' && pb195.dropped.length === 0
      && pb195.branches.every((x) => x.from < 4 && x.to < 4 && x.to > x.from) && all195.minor.length === 0 && all195.members.some((m) => m.name === 'Hg-195m')
      && chainOf('Ra-223').minor.join() === 'Po-211' && chainOf('Ag-104m').minor.join() === 'Ag-104' && namesOf('U-234') === 'U-234'
      && chainOf('Ra-226').minor.join() === 'At-218,Rn-218,Tl-210' && chainOf('Ra-226', 0).minor.length === 0,
      `${namesOf('Pb-195m')} | not followed ${pb195.minor} | 223Ra ${chainOf('Ra-223').minor} | 104mAg ${chainOf('Ag-104m').minor} | 234U ${namesOf('U-234')} | 226Ra ${chainOf('Ra-226').minor}`);
    check('a chain ends where too little is left, though members before it emit less: 235U down to 223Ra, without the 219Rn, 215Po, 211Pb and 211Bi after it; a lesser way stays cut and its member in (209Tl after 213Bi), ways that bring more are followed (131I after 131mTe, 95mNb after 95Zr); 228Pa keeps 220Fr',
      namesOf('U-235') === 'U-235,Th-231,Pa-231,Ac-227,Th-227,Ra-223' && ['Rn-219', 'Po-215', 'Pb-211', 'Bi-211'].every((n) => chainOf('U-235').minor.includes(n))
      && namesOf('Bi-213') === 'Bi-213,Po-213,Tl-209,Pb-209' && JSON.stringify(chainOf('Bi-213').cut) === '[["Tl-209","Pb-209"]]'
      && chainOf('Te-131m').members.some((m) => m.name === 'I-131') && namesOf('Zr-95') === 'Zr-95,Nb-95m,Nb-95' && chainOf('Zr-95').cut.length === 0
      && chainOf('Pa-228').members.some((m) => m.name === 'Fr-220'),
      `235U ${namesOf('U-235')} | 213Bi ${namesOf('Bi-213')} cut ${JSON.stringify(chainOf('Bi-213').cut)} | 228Pa not followed ${chainOf('Pa-228').minor}`);
    // A way also counts by what it brings over the chain's first year: from 14 days to 6 years only 228Pa's chain changes.
    const earlyOf = (n, days) => buildChain(d103.index, n, chainOptions103({ nuclide: n, cutoff: 1e-4 }, { ...OPTIONS103, minorEarly: days }));
    check('a way is followed also where it brings a thousandth of the chain\'s energy over its first year: 216At after 228Pa (0.0009 over 50 years, 0.003 over the first year), and 228Pa\'s alone of the chains changes; over a day 230Pa would gain 226Ac and over an hour 224Ac its 220Ra and 216Rn',
      OPTIONS103.minorEarly === 365.25 && chainOf('Pa-228').members.some((m) => m.name === 'At-216') && chainOf('Pa-228').minor.join() === 'Ra-220,Rn-216'
      && earlyOf('Pa-228', 0).minor.includes('At-216') && earlyOf('Pa-228', 14.5).minor.join() === 'Ra-220,Rn-216' && earlyOf('Pa-228', 6.1 * 365.25).minor.includes('At-216')
      && chainOf('Pa-230').minor.includes('Ac-226') && !earlyOf('Pa-230', 1).minor.includes('Ac-226') && earlyOf('Pa-230', 14.5).minor.includes('Ac-226')
      && chainOf('Ac-224').minor.join() === 'Ra-220,Rn-216' && earlyOf('Ac-224', 0.04).minor.length === 0,
      `228Pa ${chainOf('Pa-228').minor} (none: ${earlyOf('Pa-228', 0).minor}) | 230Pa ${chainOf('Pa-230').minor.includes('Ac-226')} | 224Ac ${chainOf('Ac-224').minor} (an hour: ${earlyOf('Ac-224', 0.04).minor})`);
    await d103.prepare('Te-131m'); await d103.prepare('Zr-95'); await d103.prepare('Ce-144');
    check('the lesser way to a chain member is cut where it brings less than a thousandth of the energy: 209Pb by way of 209Tl after 213Bi, 210Pb by way of 210Tl and 214Bi by way of 218At after 226Ra; 131I by way of 131Te, 95Nb by way of 95mNb and 144Pr by way of 144mPr are followed',
      cutOf('Bi-213') === '[["Tl-209","Pb-209"]]' && cutOf('Ra-226') === '[["At-218","Bi-214"],["Rn-218","Po-214"],["Tl-210","Pb-210"]]' && cutOf('Te-131m') === '[]' && cutOf('Zr-95') === '[]' && cutOf('Ce-144') === '[]',
      `${cutOf('Bi-213')} ${cutOf('Ra-226')} ${cutOf('Te-131m')} ${cutOf('Zr-95')} ${cutOf('Ce-144')}`);
    // A compartment of the progeny's own element is its own, whatever a set says of other elements' compartments of
    // that name: 91Y formed from 91mY in yttrium's ST1 stays there; from 91Sr in strontium's ST1 it goes to blood.
    const ySt = await bornAt('Sr-91', 'Y-91m/ST1'), ySr = await bornAt('Sr-91', 'Sr-91/ST1');
    check('91Y formed from 91mY in yttrium\'s ST1 is in its own ST1; formed in strontium\'s ST1 it goes to blood at 0.231 d-1 (Publication 134 para 483)',
      String(ySt.to) === 'Y-91/ST1' && ySr.to.includes('Y-91/ST1 (Sr-91)') && JSON.stringify(ySr.out('Y-91/ST1 (Sr-91)')) === '[["Y-91/Blood 1",[0.231]]]',
      `${ySt.to} | ${ySr.to} | ${JSON.stringify(ySr.out('Y-91/ST1 (Sr-91)'))}`);
    const rh = await bornAt('Ag-101', 'Pd-101/ST0'), rhAg = await bornAt('Ag-101', 'Pd-101/ST0 (Ag-101)');
    check('101Ag: rhodium formed in palladium\'s ST0 is in its own ST0 (one model structure, the same names); formed from the palladium that sits in silver\'s ST0, in a compartment of its own there',
      String(rh.to) === 'Rh-101m/ST0' && String(rhAg.to) === 'Rh-101m/ST0 (Ag-101) (Pd-101)' && d103.progeny.sets.silver.Rh.sameOther === 'progeny' && d103.progeny.sets.silver.Pd.sameOther === undefined,
      `${rh.to} | ${rhAg.to}`);
    const ag = await bornAt('Ag-115', 'Cd-115/Liver 1 (Ag-115)');
    check('115Ag: indium formed from the cadmium in silver\'s Liver 1 is in a compartment of its own there and leaves for plasma at 2.37 d-1, not in indium\'s Liver 1',
      String(ag.to) === 'In-115m/Liver 1 (Ag-115) (Cd-115)' && JSON.stringify(ag.out('In-115m/Liver 1 (Ag-115) (Cd-115)')) === '[["In-115m/Plasma",[2.37]]]', `${ag.to} ${JSON.stringify(ag.out('In-115m/Liver 1 (Ag-115) (Cd-115)'))}`);
  }
  const bg = rate(bi.progeny.model, 'Blood', 'Breast-g'), fat = rate(bi.progeny.model, 'Blood', 'Fat 1');
  const rnm = d103.elements.Rn.systemic.male;
  const shareAt = (a) => rnm.transfers.find(([x, y]) => x === 'Blood-A' && y === 'Breast-g')[2][a] / rnm.transfers.filter(([x]) => x === 'Blood-A').reduce((q, t) => q + t[2][a], 0);
  check('bismuth as radon\'s progeny: blood to glandular breast 0.0009 d-1 for adults and by the breast\'s share of radon\'s arterial flow before (0.018 of it at 3 months); to fat 0.2 d-1 at every age',
    near(bg[5], 0.0009, 1e-9) && near(bg[0], 0.0009 * shareAt(0) / shareAt(5), 1e-9) && bg[0] < 0.02 * bg[5] && fat.every((x) => near(x, 0.2, 1e-9)),
    `${JSON.stringify(bg.map((x) => +x.toPrecision(3)))} ${JSON.stringify(fat)}`);
  check('lead as radon\'s progeny keeps the identifications of the lead set beside radon\'s own',
    pb.progeny && (() => { const sp = d103.progeny.sets.radon.Pb.identify, lead = d103.progeny.sets.lead.Pb.identify; return sp['Rn:Liver'] === 'Liver 1' && lead.RBC === 'Blood 1'; })()
    && comp('Po-214', 'RBC') >= 0 && compLike('Po-214', 'Blood 1 (') < 0,
    `${comp('Po-214', 'RBC')} ${compLike('Po-214', 'Blood 1 (')}`);
  // Phosphorus too: its bone takes calcium's share x 0.8 (Publication 158 para 269); with 20 years 33P's bone surface at
  // 15 years was 0.13 % below the annex and its liver and kidneys as much above.
  const adult25 = ['Ac', 'Pa', 'Bk', 'Cf', 'Es', 'Fm', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Al', 'P'];
  check('adult rates from 25 years for actinium, protactinium, berkelium to fermium, the lanthanides, aluminium and phosphorus',
    adult25.every((el) => d103.elements[el].adultAge === 9125 && Object.values(d103.elements[el].systemic).every((m) => m.ages.at(-1) === 9125)),
    adult25.filter((el) => d103.elements[el].adultAge !== 9125).join(' '));
  // A progeny's model has its adult rates from the adult age of the element taken in.
  await d103.prepare('Mo-93');
  const mo = assemble103(d103, { nuclide: 'Mo-93', route: 'injection', cutoff: 1e-4, intakeAge: 7300 });
  const nbAges = mo.transfers.filter((t) => mo.comps[t.from].member === 1 && mo.comps[t.from].kind === 'sys' && t.ages.length === 6).map((t) => t.ages.at(-1));
  check('niobium formed from 93Mo: its rates by age end at 20 years, molybdenum\'s adult age (its own is 25)',
    nbAges.length > 0 && nbAges.every((a) => a === 7300) && d103.elements.Nb.adultAge === 9125, [...new Set(nbAges)].join(' '));
  // Lead's chains. The soft-tissue pools of a member that is itself a progeny are the next member's own pools; those
  // of the nuclide taken in are not. Bone turnover is adult from the adult age of the element taken in.
  const asm = async (n, rules) => { await d103.prepare(n); return assemble103(d103, { nuclide: n, route: 'injection', cutoff: 1e-4, intakeAge: d103.elements[n.split('-')[0]].adultAge || 7300, rules }); };
  const places = (sys, member) => sys.comps.filter((x) => sys.members[x.member].name === member && x.kind === 'shadow').map((x) => x.name);
  const bi214 = await asm('Bi-214'), pb210 = await asm('Pb-210');
  check('210Bi formed in the ST pools of 210Pb: a place of its own there where the lead was taken in, bismuth\'s own pools where the lead is a progeny (214Bi)',
    ['ST0', 'ST1', 'ST2'].every((q) => places(pb210, 'Bi-210').includes(`${q} (Pb-210)`)) && !places(bi214, 'Bi-210').some((x) => /^ST\d \(Pb-210\)/.test(x))
    && ['Tl', 'Pb', 'Bi', 'Po'].every((el) => d103.progeny.sets.lead[el].sameOther === 'progeny'),
    `${places(pb210, 'Bi-210').join(', ')} | ${places(bi214, 'Bi-210').join(', ')}`);
  const turnAges = (sys) => [...new Set(sys.transfers.filter((t) => /bone turnover/.test(t.origin || '')).map((t) => t.ages.at(-1)))];
  check('bone turnover for the progeny of 214Bi: adult from 20 years, bismuth\'s adult age; from 25 with chainAdult own',
    turnAges(bi214).join() === '7300' && turnAges(await asm('Bi-214', { chainAdult: 'own' })).join() === '9125', `${turnAges(bi214).join(' ')}`);
  const hg = await modelOf('Pb-197m', 'Hg-197');
  check('mercury formed after lead: mercury\'s own model (24 d-1 out of Plasma 1, 30 % of it to kidneys) without its brain, with red marrow, skin, testes and ovaries at para 479\'s shares and spleen and the two bone surfaces at a tenth of them (0.0144 and 0.024 d-1), all back with 20 d',
    near(hg.transfers.filter(([x]) => x === 'Plasma 1').reduce((q, t) => q + t[2].at(-1), 0), 24.004, 1e-6) && near(rate(hg, 'Plasma 1', 'Kidneys').at(-1), 7.2, 1e-9)
    && near(rate(hg, 'Plasma 1', 'Red marrow').at(-1), 0.72, 1e-9) && near(rate(hg, 'Red marrow', 'Plasma 1').at(-1), 0.03466, 1e-9)
    && ['Red marrow', 'Skin', 'Testes', 'Ovaries'].every((c) => c in hg.compartments) && !Object.values(hg.compartments).some((r) => r === 'Brain')
    && hg.compartments.Spleen === 'Spleen' && hg.compartments['Trab bone surf'] === 'T-bone-S' && hg.compartments['Cort bone surf'] === 'C-bone-S'
    && near(rate(hg, 'Plasma 1', 'Spleen').at(-1), 0.0144, 1e-9) && near(rate(hg, 'Plasma 1', 'Trab bone surf').at(-1), 0.024, 1e-9) && near(rate(hg, 'Plasma 1', 'Cort bone surf').at(-1), 0.024, 1e-9)
    && ['Spleen', 'Trab bone surf', 'Cort bone surf'].every((c) => near(rate(hg, c, 'Plasma 1').at(-1), 0.03466, 1e-9)),
    Object.keys(hg.compartments).join(' '));
  const pb212 = await modelOf('Ra-224', 'Pb-212'), jr = (m, a, b) => JSON.stringify(rate(m, a, b));
  check('lead as progeny: the rates to its added marrow, spleen, skin, testes and ovaries with two figures at each age before adulthood (skin and ovaries at 10 years as scaled), the outflow from blood as lead\'s own at each age; in radium\'s chains cortical marrow a third of trabecular',
    jr(pb212, 'Blood', 'Trab marrow') === '[0.3,0.37,0.38,0.35,0.3,0.42018]' && jr(pb212, 'Blood', 'Spleen') === '[0.015,0.019,0.019,0.017,0.015,0.021009]'
    && jr(pb212, 'Blood', 'Skin') === '[0.1,0.12,0.13,0.1152,0.1,0.14006]' && jr(pb212, 'Blood', 'Testes') === '[0.0025,0.0031,0.0032,0.0029,0.0025,0.0035015]'
    && jr(pb212, 'Blood', 'Ovaries') === '[0.001,0.0012,0.0013,0.001152,0.001,0.0014006]'
    && rate(pb212, 'Blood', 'Cort marrow').every((x, a) => near(x, rate(pb212, 'Blood', 'Trab marrow')[a] / 3, 1e-5))
    && [0, 1, 2, 3, 4, 5].every((a) => near(pb212.transfers.filter(([x]) => x === 'Blood').reduce((q, t) => q + t[2][a], 0),
      d103.elements.Pb.systemic.default.transfers.filter(([x]) => x === 'Blood').reduce((q, t) => q + t[2][a], 0), 1e-9)),
    `skin ${jr(pb212, 'Blood', 'Skin')}; out of blood ${[0, 1, 2, 3, 4, 5].map((a) => pb212.transfers.filter(([x]) => x === 'Blood').reduce((q, t) => q + t[2][a], 0).toFixed(4)).join(' ')}`);
  const i131 = await modelOf('Te-131', 'I-131');
  check('iodine formed after tellurium: the inorganic iodide of other tissue in one compartment (200 d-1 back) and the organic iodine in one, from Blood organic at 15 d-1, back at 9.0 and to blood iodide at 0.09 for the adult, all three by the age factor of iodine\'s own model (26.3 over 15 at 3 months)',
    !('Other 2' in i131.compartments) && !('Other 4' in i131.compartments) && rate(i131, 'Other 1', 'Blood iodide').every((x) => x === 200)
    && jr(i131, 'Blood organic', 'Other 3') === '[26.3,23.3,21,19.1,17.5,15]' && jr(i131, 'Other 3', 'Blood organic') === '[15.78,13.98,12.6,11.46,10.5,9]'
    && jr(i131, 'Other 3', 'Blood iodide') === '[0.1578,0.1398,0.126,0.1146,0.105,0.09]'
    && rate(i131, 'Other 3', 'Blood organic').every((x, a) => near(x / 9, rate(i131, 'Blood organic', 'Other 3')[a] / 15, 1e-9)),
    `${jr(i131, 'Other 3', 'Blood organic')} ${jr(i131, 'Other 3', 'Blood iodide')}`);
  const in115 = await modelOf('Ag-115', 'In-115m'), leaving = (m, from) => m.transfers.filter(([x]) => x === from).reduce((q, t) => q + t[2].at(-1), 0);
  const setTo = (set) => d103.progeny.sets[set].In.ops.find((o) => o.op === 'set' && o.from === 'TF' && o.to === 'Other 1')?.rate;
  check('indium formed after silver: muscle and pancreas (0.2 and 0.001 d-1 from transferrin) taken out of ST0, so that 1.582 d-1 leave transferrin as in indium\'s own model; the same in the cadmium and tin sets',
    near(rate(in115, 'Transferrin', 'ST0').at(-1), 0.226, 1e-9) && near(rate(in115, 'Transferrin', 'ST1').at(-1), 0.586, 1e-9) && near(rate(in115, 'Transferrin', 'Skeletal muscle').at(-1), 0.2, 1e-9)
    && near(rate(in115, 'Transferrin', 'Pancreas').at(-1), 0.001, 1e-9) && near(leaving(in115, 'Transferrin'), 1.582, 1e-9) && near(leaving(d103.elements.In.systemic.default, 'TF'), 1.582, 1e-9)
    && setTo('cadmium') === 0.226 && setTo('tin') === 0.226,
    `out of transferrin ${leaving(in115, 'Transferrin')}; to ST0 ${rate(in115, 'Transferrin', 'ST0')}; cadmium ${setTo('cadmium')}, tin ${setTo('tin')}`);
  const as = await modelOf('Se-70', 'As-70');
  check('arsenic formed after selenium: selenium\'s pancreas, spleen, testes and ovaries added to its model out of Other 2, with 0.004, 0.004, 0.0008 and 0.00028 d-1 from plasma and 0.08 d-1 back; 40 d-1 leave plasma as before',
    [['Pancreas', 0.004], ['Spleen', 0.004], ['Testes', 0.0008], ['Ovaries', 0.00028]].every(([c, r]) => as.compartments[c] === c && near(rate(as, 'Plasma', c).at(-1), r, 1e-12) && near(rate(as, c, 'Plasma').at(-1), 0.08, 1e-12))
    && near(rate(as, 'Plasma', 'Other 2').at(-1), 1.52 - 0.00908, 1e-12) && near(as.transfers.filter(([x]) => x === 'Plasma').reduce((q, t) => q + t[2].at(-1), 0), 40, 1e-12),
    `${Object.keys(as.compartments).join(' ')}; plasma to Other 2 ${rate(as, 'Plasma', 'Other 2').at(-1)}`);
  const ba137 = await modelOf('Cs-137', 'Ba-137m');
  check('137mBa formed from caesium: a pool in adipose tissue with 5 % of the flow to soft tissue (9.2 d-1) and 7 % to other soft tissue, 184 d-1 in all',
    ba137.compartments['Adipose ECF'] === 'Adipose' && near(rate(ba137, 'Blood', 'Adipose ECF').at(-1), 9.2, 1e-9) && near(rate(ba137, 'Blood', 'Other ECF').at(-1), 12.88, 1e-9)
    && near(ba137.transfers.filter(([x, y]) => x === 'Blood' && / ECF$/.test(y)).reduce((q, t) => q + t[2].at(-1), 0), 184, 1e-6),
    `${rate(ba137, 'Blood', 'Adipose ECF')} ${rate(ba137, 'Blood', 'Other ECF')}`);
  const la129 = await asm('La-129');
  check('barium formed on lanthanum\'s bone surfaces is on barium\'s own; caesium formed on barium\'s has a place of its own there',
    !places(la129, 'Ba-129').some((x) => /bone surf/.test(x)) && places(la129, 'Cs-129').some((x) => /^Trab bone surf \(Ba-129\)/.test(x)),
    `${places(la129, 'Ba-129').join(', ')} | ${places(la129, 'Cs-129').join(', ')}`);
  const ni56 = await asm('Ni-56');
  check('cobalt formed in nickel\'s kidneys is in cobalt\'s own kidneys: its places of its own are nickel\'s blood and soft tissue',
    !places(ni56, 'Co-56').some((x) => x.startsWith('Kidneys')) && places(ni56, 'Co-56').includes('ST1 (Ni-56)'), places(ni56, 'Co-56').join(', '));
  const sc = await modelOf('Ca-47', 'Sc-47');
  check('scandium formed after calcium: scandium\'s own model by age, 15 % of the outflow to each bone surface at 3 months and 10 % for adults, lost again at the bone turnover rate of the age',
    sc.ages.length === 6 && near(rate(sc, 'Blood 1', 'Trab surface')[0], 0.225, 1e-9) && near(rate(sc, 'Blood 1', 'Trab surface')[5], 0.15, 1e-9) && near(rate(sc, 'Trab surface', 'Blood 1')[0], 0.00822, 1e-9),
    JSON.stringify(rate(sc, 'Blood 1', 'Trab surface')));
  const te118 = await asm('Te-118');
  check('antimony formed in tellurium\'s red cells is in antimony\'s: its only places of its own are tellurium\'s liver and other tissue',
    places(te118, 'Sb-118').join() === 'Liver (Te-118),Other (Te-118)', places(te118, 'Sb-118').join(', '));
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
  // A noble gas born in the body escapes, but one followed by a radioactive
  // member that is no noble gas stays with the parent (ICRP 72's 125Cs).
  const gasComps = async (nuclide, route, type) => {
    await d60.prepare(nuclide);
    const g = assemble60(d60, { ...recipe60(d60.cases, route, { nuclide, type }), intakeAge: 7300 });
    const j = g.members.findIndex((m) => /^(Xe|Kr)-/.test(m.name));
    return { n: g.comps.filter((c) => c.member === j).length, moves: g.transfers.filter((t) => g.comps[t.from]?.member === j).length };
  };
  const xe125 = await gasComps('Cs-125', 'ingestion'), xe125h = await gasComps('Cs-125', 'inhalation', 'M'), xe127 = await gasComps('Cs-127', 'ingestion'), kr79 = await gasComps('Rb-79', 'ingestion');
  check('ICRP 60: 125Xe (followed by 125I) stays with caesium, in the body and the lungs; 127Xe and 79Kr escape and are never born',
    xe125.n > 5 && xe125.moves > 5 && xe125h.moves > xe125.moves && xe127.n === 0 && kr79.n === 0, JSON.stringify({ xe125, xe125h, xe127, kr79 }));
}

/* ---- spontaneous fission (ICRP 60; SEECAL 8.4's SponFiss, see60.js) ---------------------- */
// What a fission gives off, and the SEE of 244Pu against DCAL's own
// (Pu244HT.SEE, adult male, Sv per transformation) for pairs before SEECAL's
// photon slip (README): the liver's kidneys and brain take nothing but
// fission's photons and neutrons and 244Pu's own. Red marrow to bone surface
// counts the alpha recoil, as SEECAL does (FGR 13 leaves recoils out from bone
// only). The SEE as SEECAL has them (dcal: its photon SAFs and joules per MeV).
{
  const { phantom60, TARGETS_60, fission60 } = await import(path.join(JS, 'see60.js'));
  const f = fission60(3.89, 98, 254);
  check('ICRP 60 fission as SponFiss has it: 254Cf gives 2 fragments of 94.86 MeV, 3.89 neutrons of 2.187 MeV, 7.00 beta decays of 1.440 MeV and 1.369 times the delayed gammas',
    near(f.fragment, 189.7267, 1e-5) && near(f.neutron, 8.50886, 1e-5) && near(f.X, 6.99695, 1e-5) && near(f.beta[0], 1.43997, 1e-5) && near(f.delayed, 1.36885, 1e-5), JSON.stringify(f));
  await d60.prepare('Pu-244');
  const srcs = ['St_Cont', 'Liver', 'C_Bone-S', 'R_Marrow'];
  const explicit = new Set(['Liver', 'C_Bone-S', 'T_Bone-S', 'Kidneys', 'Testes', 'Ovaries', 'C_Bone-V', 'R_Marrow', 'T_Bone-V']);
  const see = phantom60(d60.saf, 'AM').see(d60.emissions('Pu-244'), 244, srcs, explicit, TARGETS_60, { Z: 94, dcal: true });
  const at = (s, t) => see[TARGETS_60.indexOf(t)][srcs.indexOf(s)];
  const dcal = [['Liver', 'Liver', 8.674e-12], ['Liver', 'Kidneys', 3.048e-16], ['Liver', 'Brain', 3.089e-18], ['C_Bone-S', 'Bone_Sur', 3.201e-11],
    ['R_Marrow', 'Bone_Sur', 5.208e-12], ['St_Cont', 'St_Wall', 3.188e-13]];
  const off = dcal.filter(([s, t, v]) => !near(at(s, t), v, 6e-4)).map(([s, t, v]) => `${s}->${t} ${at(s, t).toExponential(4)} vs ${v}`);
  check('ICRP 60 244Pu: SEE as DCAL\'s to its four figures -- liver to liver, kidneys and brain, bone surface from cortical bone and red marrow, stomach wall from contents',
    !off.length, off.join('; '));
}

/* ---- photon SAFs between the tabulated energies, joules per MeV (ICRP 60, see60.js) ------ */
// A 40 keV photon (between 30 and 50 keV) in the adult liver: by default the
// energy it leaves per kilogram, E SAF(E), is linear in energy and 1 MeV is
// 1.6e-13 J (Publication 30's rounded factor, as ICRP 72's coefficients have
// it); with dcal the SAF itself is linear and the joule exact (DCAL's SEECAL).
{
  const { phantom60, TARGETS_60, MEV, MEV_DCAL } = await import(path.join(JS, 'see60.js'));
  const row = d60.saf.phantoms.AM.saf['Liver<-Liver'], E = d60.saf.photonEnergies;
  const i30 = E.indexOf(0.03), i50 = E.indexOf(0.05);
  const em = { r: { p: [[0.04, 1]] } };
  const at = (opt) => phantom60(d60.saf, 'AM').see(em, 100, ['Liver'], new Set(['Liver']), TARGETS_60, opt)[TARGETS_60.indexOf('Liver')][0];
  const wantE = MEV * 0.04 * (0.5 * (0.03 * row[i30] + 0.05 * row[i50]) / 0.04);
  const wantS = MEV_DCAL * 0.04 * 0.5 * (row[i30] + row[i50]);
  check('ICRP 60 photon SAFs: E SAF linear in energy between the tabulated energies and 1 MeV = 1.6e-13 J (a 40 keV photon in the adult liver); with dcal the SAF itself and 1.602176634e-13',
    MEV === 1.6e-13 && MEV_DCAL === 1.602176634e-13 && near(at({}), wantE, 1e-12) && near(at({ dcal: true }), wantS, 1e-12) && !near(wantE, wantS, 1e-3), `${at({})} vs ${wantE}; ${at({ dcal: true })} vs ${wantS}`);
}

/* ---- SEECAL's own example of 1993 (ORNL/TM-12351, Figure 6: 224Ra) ---------------------- */
// The SEE the SEECAL manual prints for 224Ra (equivalent dose, Sv per
// transformation; newborn, 1 and 5 years), to its four figures with dcal:
// self-doses of alpha emitters (the joule per MeV), walls from contents, and
// photons from organ to organ (the 241 keV line between 200 and 500 keV: the
// SAF itself linear in energy; with E SAF linear these are up to 3 % off).
{
  const { phantom60, TARGETS_60 } = await import(path.join(JS, 'see60.js'));
  await d60.prepare('Ra-224');
  const srcs = ['LLI_Cont', 'SI_Cont', 'St_Cont', 'ULI_Cont', 'Kidneys', 'Liver', 'R_Marrow', 'C_Bone-S', 'C_Bone-V', 'T_Bone-S', 'T_Bone-V', 'Other'];
  const explicit = new Set(['Kidneys', 'Liver', 'R_Marrow', 'C_Bone-S', 'C_Bone-V', 'T_Bone-S', 'T_Bone-V']);
  const printed = [
    ['A00', 'Kidneys', 'Kidneys', 8.083e-10], ['A00', 'Liver', 'Liver', 1.530e-10], ['A00', 'St_Wall', 'St_Cont', 8.594e-12], ['A00', 'LLI_Wall', 'LLI_Cont', 1.305e-11],
    ['A00', 'Breasts', 'Liver', 7.435e-17], ['A00', 'Liver', 'Kidneys', 1.557e-16], ['A00', 'Thyroid', 'Liver', 2.011e-17], ['A00', 'Liver', 'LLI_Cont', 4.227e-17],
    ['A00', 'SI_Wall', 'Kidneys', 1.463e-16], ['A00', 'Testes', 'LLI_Cont', 1.576e-16], ['A00', 'R_Marrow', 'Liver', 3.867e-17], ['A00', 'Bone_Sur', 'Liver', 7.038e-17],
    ['A01', 'Kidneys', 'Kidneys', 2.943e-10], ['A01', 'Liver', 'Kidneys', 8.116e-17], ['A01', 'Breasts', 'Liver', 3.611e-17], ['A01', 'Kidneys', 'St_Cont', 5.753e-17], ['A01', 'Testes', 'LLI_Cont', 7.222e-17],
    ['A05', 'Liver', 'Liver', 3.170e-11], ['A05', 'Liver', 'Kidneys', 5.549e-17], ['A05', 'Breasts', 'Kidneys', 7.235e-18], ['A05', 'St_Wall', 'Liver', 4.763e-17], ['A05', 'ULI_Wall', 'SI_Cont', 2.624e-16],
  ];
  const off = [], far = [];
  for (const [phantom, t, src, v] of printed) {
    const P = phantom60(d60.saf, phantom), em = d60.emissions('Ra-224');
    const got = P.see(em, 224, srcs, explicit, TARGETS_60, { dcal: true })[TARGETS_60.indexOf(t)][srcs.indexOf(src)];
    if (!near(got, v, 5e-4)) off.push(`${phantom} ${t}<-${src} ${got.toExponential(4)} vs ${v}`);
    far.push(Math.abs(P.see(em, 224, srcs, explicit, TARGETS_60, {})[TARGETS_60.indexOf(t)][srcs.indexOf(src)] / v - 1));
  }
  check(`ICRP 60, dcal: the SEE of 224Ra as SEECAL's manual of 1993 prints them, ${printed.length} values to four figures (as the page computes for ICRP 72, up to ${(100 * Math.max(...far)).toFixed(1)} % off them)`,
    !off.length && Math.max(...far) > 0.02, off.join('; '));
}

/* ---- bone surfaces or bone volume (ICRP 60; model60.js parentModelName) ----------------------- */
// Ten elements have a surface-seeker and a volume-seeker file; a nuclide of
// 15 days or less takes the first, but 48V (16 d) and 95Nb (35 d) take it
// too, as the ICRP has them.
{
  const of = (n) => parentModelName(d60.models, d60.index, n, 'ingestion', null);
  const want = { 'V-47': 'V_SUR', 'V-48': 'V_SUR', 'V-49': 'V_VOL', 'Nb-95m': 'NB_SUR', 'Nb-95': 'NB_SUR', 'Nb-93m': 'NB_VOL', 'Nb-94': 'NB_VOL',
    'P-32': 'P_SUR', 'P-33': 'P_VOL', 'Pd-103': 'PD_VOL', 'W-178': 'W_VOL', 'Sn-117m': 'SN_SUR', 'Sn-113': 'SN_VOL', 'Ta-183': 'TA_SUR', 'Ta-182': 'TA_VOL', 'Cr-51': 'CR_VOL' };
  const got = Object.fromEntries(Object.keys(want).map((n) => [n, of(n)]));
  check('ICRP 60: 48V and 95Nb on bone surfaces, the other nuclides of the elements with a surface and a volume model by their half-lives (15 days)',
    Object.entries(want).every(([n, f]) => got[n] === f) && parentModelName(d60.models, d60.index, 'Nb-95', 'inhalation', null) === 'NB_SUR', JSON.stringify(got));
}

/* ---- ICRP 30's models as ICRP 72 has them (ICRP 60; the _I30 models of gen-dose-icrp60.mjs) ---- */
// Gold: DCAL's Au.DEF without its way from blood straight to the bladder
// contents, which the ICRP's coefficients do not have. And how blood is
// left: at once by gold, fluorine and thallium (1e7 d-1, where DCAL's files
// have 1000), with a half-time of 0.25 d by potassium. Taken for these
// elements as parents, as the _I30 models of actinium and protactinium are.
{
  const S = d60.models.systemic;
  const au = S.AU.transfers, i30 = S.AU_I30.transfers;
  const straight = au.filter(([from, to]) => from === 'Blood' && to === 'UB_Cont');
  // the rates out of blood of a parent as the engine assembles it: [to, d-1]
  const blood = async (nuclide) => {
    await d60.prepare(nuclide);
    const sys = assemble60(d60, { ...recipe60(d60.cases, 'ingestion', { nuclide }), intakeAge: 7300 });
    return sys.transfers.filter((t) => sys.comps[t.from].name === 'Blood' && t.to >= 0).map((t) => [sys.comps[t.to].name, t.rates ? t.rates[t.rates.length - 1] : t.rate]);
  };
  const sum = (l) => l.reduce((a, [, r]) => a + r, 0);
  const gold = await blood('Au-198');
  check('ICRP 60: gold leaves blood for the body tissues only (Au.DEF sends 2.78 % straight to the bladder contents; AU_I30 is Au.DEF without it), and at once',
    straight.length === 1 && near(straight[0][2][0] / au.filter(([from]) => from === 'Blood').reduce((a, t) => a + t[2][0], 0), 0.0278, 2e-3)
    && JSON.stringify(i30) === JSON.stringify(au.filter((t) => t !== straight[0]).map(([a, b, r]) => (a === 'Blood' ? [a, b, [1e7]] : [a, b, r])))
    && gold.length === 1 && gold[0][0] === 'Body_Tis' && gold[0][1] === 1e7, JSON.stringify({ i30, gold }));
  const k = await blood('K-40'), f = await blood('F-18'), tl = await blood('Tl-201');
  const sameButBlood = (a, b) => JSON.stringify(a.filter(([from]) => from !== 'Blood')) === JSON.stringify(b.filter(([from]) => from !== 'Blood'));
  check('ICRP 60: potassium leaves blood with a half-time of 0.25 d, fluorine and thallium at once (1e7 d-1 in the proportions of their files), the models otherwise DCAL\'s',
    near(sum(k), Math.LN2 / 0.25, 1e-12) && k.length === 1 && k[0][0] === 'Body_Tis'
    && near(sum(f), 1e7, 1e-12) && f.length === 2 && near(f[0][1], f[1][1], 1e-12)
    && near(sum(tl), 1e7, 1e-12) && near(tl.find(([n]) => n === 'Kidneys')[1] / sum(tl), 0.03, 1e-12)
    && sameButBlood(S.K.transfers, S.K_I30.transfers) && sameButBlood(S.F.transfers, S.F_I30.transfers) && sameButBlood(S.TL.transfers, S.TL_I30.transfers),
    JSON.stringify({ k, f, tl }));
}

/* ---- nickel's "all organs (including kidneys)" (ICRP 60; the NI_I72 model of gen-dose-icrp60.mjs) */
// ICRP 67's 30 % with 1200 d: DCAL's Ni.DEF has it in the whole body; the
// ICRP's coefficients have the kidneys' share of it, their mass over the
// body's, in a second kidney compartment and the rest in the other tissues.
{
  const S = d60.models.systemic, ni = S.NI.transfers, n72 = S.NI_I72;
  const rate = (from, to) => n72.transfers.find(([a, b]) => a === from && b === to)[2];
  const whole = ni.find(([a, b]) => a === 'Blood' && b === 'Body_Tis')[2][0];
  const share = [22.9 / 3535.7, 62.9 / 9543.1, 116 / 19458, 173 / 32620, 248 / 55825, 0.00451];
  const outOfBlood = (t) => t.filter(([a]) => a === 'Blood').reduce((u, [, , r]) => u + r[r.length - 1], 0);
  await d60.prepare('Ni-63');
  const sysOf = (opt) => assemble60(d60, { ...recipe60(d60.cases, 'ingestion', { nuclide: 'Ni-63' }), intakeAge: 3650, ...opt });
  const names = (sys) => sys.comps.filter((c) => c.member === 0 && !/Cont$/.test(c.name)).map((c) => c.name).join(' ');
  const as72 = sysOf({}), asDcal = sysOf({ icrp72: false });
  check('ICRP 60: nickel\'s 30 % to all organs goes to a second kidney compartment by the kidneys\' share of the body (0.0065 at 3 months to 0.0045 in the adult) and to Other, with Ni.DEF\'s rates otherwise',
    JSON.stringify(n72.ages) === '[100,365,1825,3650,5475,7300]' && share.every((k, i) => near(rate('Blood', 'Kidneys_b')[i], whole * k, 1e-12) && near(rate('Blood', 'Other')[i], whole * (1 - k), 1e-12))
    && near(outOfBlood(n72.transfers), outOfBlood(ni), 1e-12) && rate('Other', 'UB_Cont')[5] === ni.find(([a, b]) => a === 'Body_Tis' && b === 'UB_Cont')[2][0]
    && rate('Kidneys_b', 'UB_Cont')[0] === rate('Other', 'UB_Cont')[0] && rate('Kidneys_a', 'UB_Cont')[2] === ni.find(([a, b]) => a === 'Kidneys' && b === 'UB_Cont')[2][0]
    && /Kidneys_a/.test(names(as72)) && /Kidneys_b/.test(names(as72)) && /Other/.test(names(as72)) && !/Body_Tis/.test(names(as72)) && /Body_Tis/.test(names(asDcal)) && !/Kidneys_b/.test(names(asDcal)),
    JSON.stringify({ as72: names(as72), asDcal: names(asDcal) }));
}

/* ---- beta spectra and the absorbed fractions of the airways (ICRP 60; see60.js spectrumAf, af66) */
// A beta spectrum as groups: each interval of the table with the mean of N
// at its ends, at the energy of its middle. Where the absorbed fraction is
// one (the alveolar region from itself) that is 0.3-0.6 % more than the
// decay data's mean energy; the trapezoidal rule (dcal) gives the mean.
// And the absorbed fractions by Publication 66's algebraic functions
// (Tables H.7-H.9), the tables of DCAL's library with dcal.
{
  const { spectrumAf, phantom60, TARGETS_60, MEV: MEV60, MEV_DCAL, AF66_ALPHA, AF66_ELECTRON, af66 } = await import(path.join(JS, 'see60.js'));
  const over = {};
  for (const n of ['Ni-63', 'C-14', 'Ca-45', 'P-32', 'Y-90']) {
    await d60.prepare(n);
    const em = d60.emissions(n), mean = em.r.b.reduce((u, [e, y]) => u + e * y, 0);
    over[n] = [spectrumAf(em.bs, () => 1) / mean, spectrumAf(em.bs, () => 1, true) / mean];
  }
  const [es, ns] = d60.emissions('C-14').bs;
  let byHand = 0;
  for (let i = 1; i < es.length; i++) byHand += 0.5 * (ns[i] + ns[i - 1]) * (es[i] - es[i - 1]) * 0.5 * (es[i] + es[i - 1]) * (0.5 * (es[i] + es[i - 1]) > 0.05 ? 1 : 0);
  const P = phantom60(d60.saf, 'AM'), mAI = d60.saf.phantoms.AM.masses.targets.AI;
  const ai = (opt) => P.see(d60.emissions('C-14'), 14, ['AI'], new Set(), TARGETS_60, opt)[TARGETS_60.indexOf('AI')][0];
  const mean14 = d60.emissions('C-14').r.b.reduce((u, [e, y]) => u + e * y, 0);
  check(`ICRP 60: a beta spectrum in the airways as groups at the middle of each interval -- with an absorbed fraction of one ${Object.entries(over).map(([n, [g]]) => `${n} ${g.toFixed(4)}`).join(', ')} of the mean energy (the trapezoidal rule ${Object.values(over).map(([, t]) => t.toFixed(4)).join(', ')})`,
    near(over['Ni-63'][0], 1.0056, 2e-4) && near(over['C-14'][0], 1.0035, 2e-4) && near(over['Ca-45'][0], 1.0051, 2e-4) && near(over['P-32'][0], 1.0027, 2e-4) && near(over['Y-90'][0], 1.0034, 2e-4)
    && Object.values(over).every(([, t]) => Math.abs(t - 1) < 0.0016) && near(spectrumAf([es, ns], (e) => (e > 0.05 ? 1 : 0)), byHand, 1e-12)
    && near(ai({}), MEV60 * mean14 * over['C-14'][0] / mAI, 1e-9) && near(ai({ dcal: true }), MEV_DCAL * mean14 * over['C-14'][1] / mAI, 1e-9), JSON.stringify(over));
  // The three functions, each worked out here on its own from Table H.7.
  const L = Math.log10;
  const f1 = (a, x) => [0, 3, 6, 9].reduce((u, k) => u + a[k] * Math.exp(a[k + 1] * L(L(x) + a[k + 2]) ** 2), 0);
  const eET1 = AF66_ELECTRON['ET1-bas<-ET1-sur'], aET1 = AF66_ALPHA['ET1-bas<-ET1-sur'], bnd = AF66_ELECTRON['BBi-bas<-BBi-bnd'], fromAI = AF66_ELECTRON['BBi-sec<-AI'];
  const f2 = (a, x) => (1 - Math.exp(-((x / a[9]) ** 20))) * a[0] * (1 + a[1] * Math.exp(a[2] * x) + a[3] * Math.exp(a[4] * x) + a[5] * Math.exp(a[6] * x) + a[7] * Math.exp(a[8] * x));
  const f3 = (a, x) => a[1] * Math.exp(-((a[2] * L(a[3] * x)) ** 2)) + (a[0] - a[1]) * Math.exp(-((a[4] * L(a[5] * x)) ** 2)) + a[6] * Math.exp(-((a[7] * L(a[8] * x)) ** 2));
  const mAM = d60.saf.phantoms.AM.masses.targets;
  check('ICRP 60: Publication 66\'s algebraic functions (Table H.7) -- the sum of four terms for the surface of ET1 (an electron of 1 MeV 0.00754, an alpha particle of 6 MeV 0.0162), the bound source\'s constant at low energy (0.25 of an electron of 10 keV in the bronchial basal cells), AI\'s electrons reaching the secretory cells from 0.29 MeV up and tending to the cells\' share of the lungs\' mass',
    near(af66(eET1, 1), f1(eET1.slice(1), 1), 1e-12) && near(af66(eET1, 1), 0.00754, 5e-3) && near(af66(aET1, 6), f1(aET1.slice(1), 6), 1e-12) && near(af66(aET1, 6), 0.0162, 5e-3)
    && af66(eET1, 0.005) === 0 && af66(aET1, 0) === 0 && af66(aET1, 3) < 1e-15
    && near(af66(bnd, 0.01), 0.25, 1e-12) && near(af66(bnd, 0.5), f3(bnd.slice(1), 0.5), 1e-12) && af66(bnd, 0.5) < 0.03
    && near(af66(fromAI, 1), f2(fromAI.slice(1), 1), 1e-12) && af66(fromAI, 0.2) < 1e-6 && near(af66(fromAI, 4), mAM['BBi-sec'] / mAM.AI, 0.04)
    && Object.values(AF66_ALPHA).length === 17 && Object.values(AF66_ELECTRON).length === 19
    && [...Object.values(AF66_ALPHA), ...Object.values(AF66_ELECTRON)].every((r) => r.length === (r[0] === 1 ? 13 : r[0] === 2 ? 11 : 10) && r.slice(1).every(Number.isFinite)),
    JSON.stringify({ e1: af66(eET1, 1), a6: af66(aET1, 6), bnd: af66(bnd, 0.01), ai4: af66(fromAI, 4) }));
  // Against the tables of DCAL's library (Tables H.1 and H.2 of Publication
  // 66), which the functions were fitted to: the same pairs, and at the
  // tabulated energies the same fractions within the fit -- electrons from
  // the airways' walls with AI's fraction added, as Table H.2 has them.
  {
    const far = (rows, t, lo, hi, add) => {
      const dev = [];
      for (const pr of t.pairs) {
        const k = `${pr.target}<-${pr.source}`, top = Math.max(...pr.af);
        t.energies.forEach((e, n) => {
          if (e < lo || e > hi || !(pr.af[n] > 0.02 * top)) return;
          dev.push(Math.abs((af66(rows[k], e) + (add && /^(BBi|bbe)-/.test(pr.source) ? af66(rows[`${pr.target}<-AI`], e) : 0)) / pr.af[n] - 1));
        });
      }
      dev.sort((a, b) => a - b);
      return { n: dev.length, median: dev[dev.length >> 1], p90: dev[Math.floor(0.9 * dev.length)] };
    };
    const same = (rows, t) => JSON.stringify(t.pairs.map((x) => `${x.target}<-${x.source}`).sort()) === JSON.stringify(Object.keys(rows).sort());
    const al = far(AF66_ALPHA, d60.saf.lungAF.alpha, 0, 99, false), el = far(AF66_ELECTRON, d60.saf.lungAF.electron, 0.05, 2, true), local = far(AF66_ELECTRON, d60.saf.lungAF.electron, 0.05, 2, false);
    check(`ICRP 60: the functions against the tables they were fitted to -- alpha particles at ${al.n} tabulated points at the median ${(100 * al.median).toFixed(2)} % and nine in ten within ${(100 * al.p90).toFixed(2)} % of Table H.1; electrons of 0.05-2 MeV at ${el.n} points ${(100 * el.median).toFixed(2)} % and ${(100 * el.p90).toFixed(1)} % of Table H.2 with AI's fraction added for sources in the airways' walls (${(100 * local.p90).toFixed(1)} % without)`,
      same(AF66_ALPHA, d60.saf.lungAF.alpha) && same(AF66_ELECTRON, d60.saf.lungAF.electron) && al.median < 0.003 && al.p90 < 0.008 && el.median < 0.01 && el.p90 < 0.035 && local.p90 > 1.5 * el.p90,
      JSON.stringify({ al, el, local }));
  }
  // In the SEE: an electron of 1 MeV in the slow mucus of the bronchi and an
  // alpha particle of 5.15 MeV on the surface of ET1; with dcal the tables.
  const sec = TARGETS_60.indexOf('BBi-sec'), et1 = TARGETS_60.indexOf('ET1-bas');
  const one = (em, src, opt) => P.see(em, 239, [src], new Set(), TARGETS_60, opt);
  const eLine = { r: { e: [[1, 1]] } }, aLine = { r: { a: [[5.15, 1]] } };
  const eTab = d60.saf.lungAF.electron, aTab = d60.saf.lungAF.alpha;
  const eRow = eTab.pairs.find((x) => x.target === 'BBi-sec' && x.source === 'BBi-sol').af[eTab.energies.indexOf(1)];
  const aRow = aTab.pairs.find((x) => x.target === 'ET1-bas' && x.source === 'ET1-sur').af[aTab.energies.indexOf(5.15)];
  const wR = 20, eWant = af66(AF66_ELECTRON['BBi-sec<-BBi-sol'], 1) + af66(AF66_ELECTRON['BBi-sec<-AI'], 1), aWant = af66(aET1, 5.15);
  check(`ICRP 60: in the SEE, an electron of 1 MeV from the slow mucus gives the bronchial secretory cells ${eWant.toFixed(5)} of its energy (its own function and AI's; the table's ${eRow} with dcal) and an alpha particle of 5.15 MeV on the surface of ET1 gives the basal cells ${aWant.toExponential(2)} (the table's ${aRow} with dcal)`,
    near(one(eLine, 'BBi-sol', {})[sec][0], MEV60 * eWant / mAM['BBi-sec'], 1e-12) && near(one(eLine, 'BBi-sol', { dcal: true })[sec][0], MEV_DCAL * eRow / mAM['BBi-sec'], 1e-12)
    && near(one(aLine, 'ET1-sur', {})[et1][0], wR * MEV60 * 5.15 * aWant / mAM['ET1-bas'], 1e-12) && near(one(aLine, 'ET1-sur', { dcal: true })[et1][0], wR * MEV_DCAL * 5.15 * aRow / mAM['ET1-bas'], 1e-12)
    && aRow === 0 && aWant > 1e-6 && eRow === 0.0247 && near(eWant, 0.0214, 0.03),
    JSON.stringify({ eWant, eRow, aWant, aRow, page: one(aLine, 'ET1-sur', {})[et1][0], dcal: one(aLine, 'ET1-sur', { dcal: true })[et1][0] }));
}

/* ---- iron's other soft tissues (ICRP 60; the FE_I72 model of gen-dose-icrp60.mjs) -------------- */
// DCAL's Fe.DEF has them in BT-Soft, the body's tissues without the mineral
// bone, which irradiate the liver, spleen and red marrow that the model
// names too; the ICRP's coefficients have them in the rest of the body.
{
  const S = d60.models.systemic;
  const renamed = S.FE.transfers.map(([a, b, r]) => [a.replace(/^BT-Soft/, 'Other'), b.replace(/^BT-Soft/, 'Other'), r]);
  await d60.prepare('Fe-59');
  const regions = (opt) => [...new Set(assemble60(d60, { ...recipe60(d60.cases, 'ingestion', { nuclide: 'Fe-59' }), intakeAge: 7300, ...opt }).comps.filter((c) => c.member === 0).map((c) => c.region))];
  const as72 = regions({}), asDcal = regions({ icrp72: false });
  check('ICRP 60: iron\'s other soft tissues are the rest of the body (FE_I72: Fe.DEF with BT-Soft read as Other), which gives nothing to the liver, spleen and red marrow',
    JSON.stringify(S.FE_I72.transfers) === JSON.stringify(renamed) && S.FE.transfers.filter(([a, b]) => /^BT-Soft/.test(a) || /^BT-Soft/.test(b)).length === 5
    && JSON.stringify(S.FE_I72.ages) === JSON.stringify(S.FE.ages) && as72.includes('Other') && !as72.includes('BT-Soft') && asDcal.includes('BT-Soft') && !asDcal.includes('Other'),
    JSON.stringify({ as72, asDcal }));
}

/* ---- the mass of the body's tissues (ICRP 60; see60.js BODY_TISSUES_60) ------------------------ */
// What a source spread through the whole body is spread over: the database's
// masses, DCAL's with dcal. 3H in the body tissues of the adult: every
// target gets the beta's energy over that mass.
{
  const { BODY_TISSUES_60, phantom60, TARGETS_60, MEV: MEV60, MEV_DCAL } = await import(path.join(JS, 'see60.js'));
  await d60.prepare('H-3');
  const em = d60.emissions('H-3');
  const P = phantom60(d60.saf, 'AM');
  const at = (opt) => P.see(em, 3, ['Body_Tis'], new Set(), TARGETS_60, opt);
  const page = at({}), dcal = at({ dcal: true });
  const i = TARGETS_60.indexOf('Muscle'), j = TARGETS_60.indexOf('Thyroid');
  const dcalMass = d60.saf.phantoms.AM.masses.sources.Body_Tis;
  check('ICRP 60: a source in the whole body is spread over 68.966 kg in the adult (DCAL: 68.831, the 135 g of the lower large intestine\'s contents less), and 3.5335 to 55.867 kg in the children\'s phantoms',
    JSON.stringify(BODY_TISSUES_60) === '{"A00":3.5335,"A01":9.6155,"A05":19.4935,"A10":32.68,"A15":55.867,"AM":68.966}'
    && near(dcalMass, 68.831, 1e-12) && near(BODY_TISSUES_60.AM - dcalMass, d60.saf.phantoms.AM.masses.sources.LLI_Cont, 1e-9)
    && near(page[i][0] / dcal[i][0], (dcalMass / 68.966) * (MEV60 / MEV_DCAL), 1e-12) && near(page[i][0], page[j][0], 1e-12) && P.bodyTissues(false) === 68.966 && P.bodyTissues(true) === dcalMass,
    JSON.stringify({ page: page[i][0], dcal: dcal[i][0] }));
  // The rest of the body ("Other") of a model that names bone surfaces, the
  // thyroid and the kidneys (tellurium's): without the 5 kg of mineral bone,
  // or with boneInOther with it; the heart's contents never in it. 127mTe's
  // electrons to the brain go by one over that mass.
  const { BONE_IN_OTHER_60 } = await import(path.join(JS, 'model60.js'));
  await d60.prepare('Te-127m');
  const te = d60.emissions('Te-127m'), named = new Set(['C_Bone-S', 'T_Bone-S', 'Thyroid', 'Kidneys']), mS = d60.saf.phantoms.AM.masses.sources;
  const brain = TARGETS_60.indexOf('Brain');
  const rest = (opt) => P.see(te, 127, ['Other', 'Body_Tis'], named, TARGETS_60, opt)[brain];
  const out = rest({}), kept = rest({ boneInOther: true });
  const mOut = 68.966 - mS.Thyroid - mS.Kidneys - mS.Ht_Cont - mS['C_Bone-V'] - mS['T_Bone-V'], mIn = mOut + mS['C_Bone-V'] + mS['T_Bone-V'];
  // the photons' part differs too, a little: compare the two by the electrons' mass ratio within 1 %
  check('ICRP 60: tellurium\'s rest of the body takes in the mineral bone (BONE_IN_OTHER_60: TE alone); for other models that name bone it is 5 kg lighter in the adult',
    [...BONE_IN_OTHER_60].join() === 'TE' && near(mIn - mOut, 5, 1e-9) && near(out[0] / kept[0], mIn / mOut, 0.01) && out[0] > kept[0] && near(out[1], kept[1], 1e-12),
    JSON.stringify({ out: out[0], kept: kept[0], ratio: out[0] / kept[0], masses: mIn / mOut }));
}

/* ---- the remainder's bookkeeping (ICRP 60; dose60.js remainder60) ----------------------------- */
// As the ICRP's database of dose coefficients has it: nine tissues, without
// the thymus; the masses of the age of the intake (the 3-month-old's 100/365
// of the way from the newborn's to the 1-year-old's); split when the highest
// remainder tissue exceeds every weighted one with the doses to two figures.
{
  const keys = Object.keys(REMAINDER_60);
  const H0 = Object.fromEntries([...Object.keys(W_60), ...keys].map((k) => [k, 1e-9]));
  const mass = (age) => keys.map((k) => { const m = REMAINDER_60[k]; return age === 100 ? m[0] + (100 / 365) * (m[1] - m[0]) : m[[0, 365, 1825, 3650, 5475, 7300].indexOf(age)]; });
  const adult = remainder60({ ...H0, Kidneys: 0.5e-9 }, 7300), baby = remainder60({ ...H0, Muscle: 0.5e-9 }, 100);
  const sum = (m) => m.reduce((a, b) => a + b, 0);
  const byMass = near(adult.remainder, 1e-9 * (1 - 0.5 * 310 / sum(mass(7300))), 1e-12) && near(baby.remainder, 1e-9 * (1 - 0.5 * mass(100)[keys.indexOf('Muscle')] / sum(mass(100))), 1e-12)
    && near(sum(mass(7300)), 30739, 1e-12) && near(mass(100)[keys.indexOf('Muscle')], 1360 + (100 / 365) * 2560, 1e-12) && adult.split === null && near(sum(Object.values(adult.weights)), 1, 1e-12);
  // 1.04 of the highest weighted tissue but the same two figures: no split; 1.06 and another second figure: split.
  const tie = remainder60({ ...H0, Liver: 1.01e-9, Spleen: 1.049e-9 }, 7300), over = remainder60({ ...H0, Liver: 1.01e-9, Spleen: 1.07e-9 }, 7300);
  const others = (sum(mass(7300)) - 180);
  const split = tie.split === null && over.split === 'Spleen' && near(over.remainder, 0.5 * 1.07e-9 + 0.5 * 1e-9, 1e-12) && near(over.weights.Muscle, 0.5 * 28000 / others, 1e-12)
    && near(sum(Object.values(over.shares)), over.remainder, 1e-12) && remainder60({ ...H0, Spleen: 1.07e-9 }, 7300, null).split === null && remainder60(H0, 7300, 'Brain').weights.Brain === 0.5;
  check('ICRP 60: the remainder by the masses of the age of the intake, nine tissues without the thymus; split on doses to two figures (1.049 against 1.01: no; 1.07: yes)',
    byMass && split && !keys.includes('Thymus') && keys.length === 9, JSON.stringify({ adult: adult.remainder, baby: baby.remainder, tie: tie.split, over: over.split }));
  const colon = Object.fromEntries(TISSUES_60.Colon);
  check('ICRP 60: the colon 0.568 upper + 0.432 lower large intestine wall', colon.ULI_Wall === 0.568 && colon.LLI_Wall === 0.432);
  check('ICRP 60: the lungs 0.167 BB basal + 0.167 BB secretory + 0.333 bb + 0.333 AI + 0.001 LN(TH); ET 0.001 ET1 + 0.998 ET2 + 0.001 LN(ET)',
    JSON.stringify(TISSUES_60.Lung) === '[["BBi-bas",0.167],["BBi-sec",0.167],["bbe-sec",0.333],["AI",0.333],["LN-Th",0.001]]' && JSON.stringify(TISSUES_60.ET) === '[["ET1-bas",0.001],["ET2-bas",0.998],["LN-ET",0.001]]');
}

/* ---- the steps of an age-dependent calculation (ICRP 60; solve.js dose.hold, dose60.js HOLD_60) ---- */
// 36Cl swallowed at 5 years: all of it that reaches a soft tissue is in blood
// or the body tissues, so the muscle's dose per transformation there is the
// SEE of the whole body. Within the first step of 50 days it is that of the
// 5-year-old; in the second that of 5 years and 50 days, 50/1825 of the way
// to the 10-year-old's (the SEE of a pure beta emitter from the whole body
// goes as 1 over its mass). With dcal the SEE follows the age all the time.
{
  const { HOLD_60 } = await import(path.join(JS, 'dose60.js'));
  await d60.prepare('Cl-36');
  const spec = recipe60(d60.cases, 'ingestion', { nuclide: 'Cl-36' });
  const per = (opt) => {
    const r = coefficients60(d60, spec, [1825], { outputs: [30, 50, 100], ...opt })[0];
    const n = r.system.comps.length, nU = r.transformations.length, mu = n + TARGETS_60_ALL.indexOf('Muscle');
    const sys = r.transformations.map((x, g) => (x.region === 'Blood' || x.region === 'Body_Tis' ? g : -1)).filter((g) => g >= 0);
    const at = (t) => { const y = r.series.find((p) => Math.abs(p.t - t) < 1e-9).y; const u0 = y.length - nU; return [y[mu], sys.reduce((a, g) => a + y[u0 + g], 0)]; };
    const [d30, u30] = at(30), [d50, u50] = at(50), [d100, u100] = at(100);
    return [d30 / u30, d50 / u50, (d100 - d50) / (u100 - u50)];
  };
  const m5 = d60.saf.phantoms.A05.masses.sources.Body_Tis, m10 = d60.saf.phantoms.A10.masses.sources.Body_Tis;
  const want = ((1 - 50 / 1825) / m5 + (50 / 1825) / m10) * m5;
  const held = per({}), cont = per({ dcal: true });
  check('ICRP 60 in steps: 36Cl at 5 years, the muscle\'s dose per transformation in the body the same to 30 and to 50 days, and in the second step that of 5 years and 50 days; with dcal it falls all the time',
    JSON.stringify(HOLD_60) === JSON.stringify([[365, 9], [1825, 40], [5475, 50], [Infinity, 180]]) && near(held[0], held[1], 1e-7) && near(held[2] / held[1], want, 1e-6)
    && cont[1] < cont[0] * (1 - 1e-4) && cont[2] / cont[1] < want, `${held.join(' ')} want ${want}; dcal ${cont.join(' ')}`);
}

/* ---- Other and BT-Soft to the bone surface and red marrow (ICRP 60, see60.js) ---------- */
// As DCAL's SEECAL has it (SR90HT.SEE, AM241HT.SEE, FE55HT.SEE): from Other
// a named region gets no electrons or alphas and every other target 1/M_Other,
// the bone targets too; from BT-Soft the red marrow 1/M and the bone surface
// the share of it in the marrow. Equation (9) taken to the bone targets gave
// 90Sr's adult bone surface under a third of this and 241Am's red marrow
// below zero. The SEE as SEECAL has them (dcal).
{
  const { phantom60, TARGETS_60 } = await import(path.join(JS, 'see60.js'));
  const cases = [
    ['Sr-90', 'AM', 'Other', ['T_Bone-S', 'C_Bone-S', 'T_Bone-V', 'C_Bone-V'], [['Bone_Sur', 4.951e-16], ['R_Marrow', 4.951e-16]]],
    ['Am-241', 'AM', 'Other', ['Liver', 'C_Bone-S', 'T_Bone-S', 'Kidneys', 'Testes', 'Ovaries', 'C_Bone-V', 'R_Marrow', 'T_Bone-V'], [['Bone_Sur', 2.994e-13], ['R_Marrow', 1.913e-17]]],
    ['Fe-55', 'A05', 'BT-Soft', ['R_Marrow', 'Liver', 'Spleen'], [['Bone_Sur', 3.341e-17], ['R_Marrow', 5.140e-17]]],
  ];
  const off = [];
  for (const [nuclide, phantom, s, named, want] of cases) {
    await d60.prepare(nuclide);
    const see = phantom60(d60.saf, phantom).see(d60.emissions(nuclide), Number(nuclide.split('-')[1]), [s], new Set(named), TARGETS_60, { dcal: true });
    for (const [t, v] of want) { const got = see[TARGETS_60.indexOf(t)][0]; if (!near(got, v, 6e-4)) off.push(`${nuclide} ${s}->${t} ${got.toExponential(4)} vs ${v}`); }
  }
  check('ICRP 60: Other and BT-Soft to the bone surface and red marrow as DCAL\'s SEE to its four figures (90Sr, 241Am adult; 55Fe at 5 years)', !off.length, off.join('; '));
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
// They add up to the remainder's dose whichever way it is taken: by mass
// (Cs-137), or split (Si-31's small intestine, Gd-149's ET at 3 months),
// the split tissue taking half.
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
    // Spontaneous fission (see60.js). Without it 244Pu's organs were 0.92-0.98
    // of ICRP 72 and 250Cf's (Type M) kidneys 0.12-0.39, its brain 0.20-0.53.
    // The lungs and ET of the strong fissioners (248Cm, 250Cm, 252Cf and 254Cf,
    // which DCAL's batch files leave out) hang on the fragments taking the
    // absorbed fractions of 2.5 MeV alphas in the respiratory tract (254Cf's lungs 0.65-0.75 of ICRP 72 at 2 MeV, about
    // twice ICRP 72's at 4 MeV); within 5 %, the size of ICRP 72's two figures.
    const fis = [
      // and 125Cs, whose xenon stays in the body (model60.js keptGas): with it
      // escaping e was 0.85-0.97 of ICRP 72 and the thyroid 0.64-0.71
      ['ingestion', 'Cs-125', null, ['E', 'Thyroid', 'Muscle', 'Bone surface'], 0.05, 'noble gas kept'],
      ['inhalation', 'Cs-125', 'M', ['E', 'Thyroid', 'Lung'], 0.05, 'noble gas kept'],
      ['ingestion', 'Pu-244', null, ['Liver', 'Bone surface', 'Kidneys', 'Muscle', 'Brain'], 0.05],
      ['inhalation', 'Cf-250', 'M', ['Kidneys', 'Muscle', 'Brain', 'Thyroid'], 0.05],
      ['inhalation', 'Cf-254', 'M', ['E', 'Lung', 'ET'], 0.05],
      ['inhalation', 'Cf-252', 'M', ['E', 'Lung', 'ET'], 0.05],
      ['inhalation', 'Cm-248', 'S', ['E', 'Lung', 'ET'], 0.05],
    ];
    const N72 = { Liver: 'Liver', 'Bone surface': 'Bone Surface', Kidneys: 'Kidneys', Muscle: 'Muscle', Brain: 'Brain', Thyroid: 'Thyroid', Lung: 'Lungs', ET: 'ET' };
    for (const [route, nuclide, type, keys, tol, what = 'fission'] of fis) {
      await d60.prepare(nuclide);
      const res = coefficients60(d60, recipe60(d60.cases, route, { nuclide, bio: null, f1file: null, type: type ?? undefined }), AGES_60);
      const off = [];
      for (const r of res) {
        const R = ref.find((x) => x.route === route && x.nuclide === nuclide && x.age === r.age && (!type || x.type === type));
        for (const k of keys) {
          const q = k === 'E' ? r.E / R.H.E : r.H[k] / R.H[N72[k]];
          if (Math.abs(q - 1) > tol) off.push(`${k} ${r.age} d ${q.toFixed(3)}`);
        }
      }
      check(`ICRP 60 ${what}, ${nuclide} ${route}${type ? ` Type ${type}` : ''}: ${keys.join(', ')} within ${tol * 100} % of ICRP 72 at every age`, !off.length, off.join('; '));
    }
    // Photons between the tabulated energies (see60.js interpPhoton): with the
    // energy a photon leaves per kilogram, E SAF, linear in energy these X-ray
    // emitters come within 3.5 % of ICRP 72; with the SAF itself linear (DCAL)
    // their e was up to 1.066 of it, the ET 1.05-1.13, 181W's bone surface
    // 1.04-1.06 and 145Pm's liver 1.03-1.05.
    const xr = [
      ['ingestion', 'Pm-145', null, ['E', 'Liver']],
      ['inhalation', 'Er-165', 'M', ['E', 'ET']],
      ['inhalation', 'W-181', 'F', ['E', 'Bone surface']],
      ['inhalation', 'Sb-119', 'M', ['E', 'ET']],
      ['inhalation', 'Ce-137', 'S', ['E', 'ET']],
    ];
    const offX = [];
    for (const [route, nuclide, type, keys] of xr) {
      await d60.prepare(nuclide);
      const res = coefficients60(d60, recipe60(d60.cases, route, { nuclide, bio: null, f1file: null, type: type ?? undefined }), AGES_60);
      for (const r of res) {
        const R = ref.find((x) => x.route === route && x.nuclide === nuclide && x.age === r.age && (!type || x.type === type));
        for (const k of keys) {
          const q = k === 'E' ? r.E / R.H.E : r.H[k] / R.H[N72[k]];
          if (Math.abs(q - 1) > 0.035) offX.push(`${nuclide} ${k} ${r.age} d ${q.toFixed(3)}`);
        }
      }
    }
    check(`ICRP 60 photons between the tabulated energies: ${xr.map(([r, n, t]) => `${n}${t ? ` ${t}` : ' ingested'}`).join(', ')} -- e and the organ that hangs on them within 3.5 % of ICRP 72 at every age`, !offX.length, offX.join('; '));
    // 48V and 95Nb on bone surfaces (model60.js ON_BONE_SURFACES_60): with
    // the volume model, Type F, their e was 0.87-0.99 of ICRP 72, the bone
    // surface 0.2-0.9 and the red marrow 0.5-0.7.
    const offB = [];
    for (const nuclide of ['V-48', 'Nb-95']) {
      await d60.prepare(nuclide);
      const res = coefficients60(d60, recipe60(d60.cases, 'inhalation', { nuclide, bio: null, f1file: null, type: 'F' }), AGES_60);
      for (const r of res) {
        const R = ref.find((x) => x.route === 'inhalation' && x.nuclide === nuclide && x.age === r.age && x.type === 'F');
        for (const [k, k72] of [['E', 'E'], ['Bone surface', 'Bone Surface'], ['Red marrow', 'Red Marrow']]) {
          const q = (k === 'E' ? r.E : r.H[k]) / R.H[k72];
          if (!(Math.abs(q - 1) <= 0.05)) offB.push(`${nuclide} ${k} ${r.age} d ${q.toFixed(3)}`);
        }
      }
    }
    check('ICRP 60 on bone surfaces: 48V and 95Nb Type F -- e, bone surface and red marrow within 5 % of ICRP 72 at every age', !offB.length, offB.join('; '));
  }
  // The ICRP's database of dose coefficients (local/icrpdose.json): each
  // tissue's dose integrated to 1, 7 and 30 days, 1, 5, 10 ... years, to the
  // seven figures of a 4-byte real.
  const cd = local('icrpdose.json');
  if (!cd) console.log('skip  ICRP 60 vs the ICRP database: no local/icrpdose.json (make-local-fixtures.py --icrpdose)');
  else {
    const TIMES = [1, 7, 30, 365, 1825, 3650, 7300, 10950, 16425];
    // this page over the database at each stored time, for a tissue of an intake by ingestion
    const over = async (nuclide, age, tissue, opt = {}) => {
      const c = cd.rows.find((x) => x.nuclide === nuclide && x.route === 'ingestion' && x.age === age);
      await d60.prepare(nuclide);
      const r = coefficients60(d60, recipe60(d60.cases, 'ingestion', { nuclide }), [age], { outputs: TIMES, ...opt })[0];
      const n = r.system.comps.length;
      return c.H[tissue].map((v, i) => { const p = r.series.find((x) => Math.abs(x.t - TIMES[i]) < 1e-6);
        return (p ? TISSUES_60[tissue].reduce((u, [t, w]) => u + w * p.y[n + TARGETS_60_ALL.indexOf(t)], 0) : r.H[tissue]) / v; });
    };
    // The steps (HOLD_60). Pure beta emitters spread through the body, with
    // models that do not change with age: the muscle's dose over the
    // database's, relative to the first day, follows the adult's in time when
    // the steps are right, whatever constant the nuclide carries. In 1e-5.
    const tol = { 100: 150, 365: 30, 1825: 5, 3650: 10, 5475: 10 };
    const worst = {}, worstDcal = {};
    for (const nuclide of ['Cl-36', 'Rb-87', 'S-35', 'P-33']) {
      const adult = await over(nuclide, 7300, 'Muscle');
      for (const age of [100, 365, 1825, 3650, 5475]) for (const [opt, into] of [[{}, worst], [{ dcal: true }, worstDcal]]) {
        const r = await over(nuclide, age, 'Muscle', opt);
        for (let i = 1; i < Math.min(r.length, adult.length); i++) into[age] = Math.max(into[age] || 0, Math.abs(1e5 * Math.log((r[i] / r[0]) / (adult[i] / adult[0]))));
      }
    }
    check(`ICRP 60 in steps vs the ICRP database: 36Cl, 87Rb, 35S and 33P swallowed, the muscle's dose in time as the adult's -- off by at most ${[100, 365, 1825, 3650, 5475].map((a) => `${worst[a].toFixed(0)}`).join(', ')} in 1e-5 at 3 months, 1, 5, 10 and 15 years (${[100, 365, 1825, 3650, 5475].map((a) => worstDcal[a].toFixed(0)).join(', ')} without steps)`,
      Object.entries(tol).every(([a, t]) => worst[a] <= t && worstDcal[a] > 150), JSON.stringify({ worst, worstDcal }));
    // The rates held too: caesium's change with age, and at 10 years the
    // muscle's dose follows the database to 1e-4 at every time (0.5 % off by
    // a year with the rates following the age and the SEE alone in steps).
    const cs = await over('Cs-137', 3650, 'Muscle');
    check(`ICRP 60 in steps vs the ICRP database: 137Cs at 10 years, the muscle to 1 d, 7 d, 30 d and 1 y level within 1e-4 (${cs.map((x) => (x / cs[0]).toFixed(5)).join(', ')})`,
      cs.every((x) => Math.abs(x / cs[0] - 1) < 1e-4), cs.join(' '));
    // And the doses themselves, at every age and time.
    const offD = [];
    for (const [nuclide, tissue, lim] of [['Co-60', 'Liver', 1.5e-3], ['Co-60', 'Muscle', 1.5e-3], ['I-131', 'Thyroid', 1.5e-3], ['Sr-90', 'Red marrow', 3.5e-3], ['Pu-239', 'Bone surface', 2.5e-3]]) {
      for (const age of AGES_60) { const r = await over(nuclide, age, tissue); const far = r.reduce((m, x) => (Math.abs(x - 1) > Math.abs(m - 1) ? x : m), 1); if (Math.abs(far - 1) > lim) offD.push(`${nuclide} ${tissue} ${age} d ${far.toFixed(4)}`); }
    }
    check('ICRP 60 vs the ICRP database, every age and every time to which it integrates: 60Co liver and muscle and 131I thyroid within 0.15 %, 239Pu bone surface 0.25 %, 90Sr red marrow 0.35 %', !offD.length, offD.join('; '));
    // The bookkeeping of the effective dose, on the database's own committed
    // tissue doses (each series' last value): its remainder by remainder60,
    // its colon from the two walls, its lungs and ET airways from the parts
    // it stores (with this page's weights, in its order), its e from them
    // all. Five nuclides are stored to two figures only and left out.
    {
      const TWO = new Set(['Th-228', 'Th-231', 'Th-232', 'Ra-227', 'U-231']);
      const n = { rows: 0, rem: 0, split: 0, told: 0, colon: 0, colonOf: 0, e: 0, lung: 0, lungOf: 0, et: 0, etOf: 0 };
      const parts = (name, k) => TISSUES_60[name].map(([, w], i) => [`${k} part ${i + 1}`, w]);
      for (const c of cd.rows) {
        if (TWO.has(c.nuclide)) continue;
        const last = (k) => { const v = c.H[k]; return v && v.length ? v[v.length - 1] : NaN; };
        const H = Object.fromEntries(Object.keys(TISSUES_60).map((k) => [k, last(k === 'Oesophagus' ? 'Thymus' : k)]));
        H.Gonads = Math.max(H.Testes, H.Ovaries);
        const want = last('Remainder');
        if (![...Object.keys(W_60), ...Object.keys(REMAINDER_60)].every((k) => H[k] >= 0) || !(want > 0) || !(last('E') > 0)) continue;
        n.rows++;
        const got = remainder60(H, c.age), other = remainder60(H, c.age, got.split ? null : Object.keys(REMAINDER_60).reduce((a, k) => (H[k] > H[a] ? k : a)));
        if (near(got.remainder, want, 1e-4)) n.rem++;
        // where the two ways give different remainders, the database has the rule's
        if (!near(got.remainder, other.remainder, 1e-3)) { n.told++; if (near(got.remainder, want, 1e-4) || !near(other.remainder, want, 1e-4)) n.split++; }
        if (H.Colon > 0 && !near(H['Upper large intestine'], H['Lower large intestine'], 0.05)) { n.colonOf++; if (near(0.568 * H['Upper large intestine'] + 0.432 * H['Lower large intestine'], H.Colon, 1e-5)) n.colon++; }
        let e = 0.05 * want; for (const [k, w] of Object.entries(W_60)) e += w * H[k];
        if (near(e, last('E'), 1e-5)) n.e++;
        if (c.route === 'inhalation') for (const [name, k, of, ok] of [['Lung', 'Lung', 'lungOf', 'lung'], ['ET', 'ET', 'etOf', 'et']]) {
          const sum = parts(name, k).reduce((a, [key, w]) => a + w * last(key), 0);
          if (!(sum > 0)) continue;
          n[of]++; if (near(sum, H[name], 1e-5)) n[ok]++;
        }
      }
      const pc = (a, b) => (100 * a / b).toFixed(1);
      check(`ICRP 60 vs the ICRP database, its own bookkeeping on ${n.rows} intakes: the remainder from its tissues within 1e-4 for ${pc(n.rem, n.rows)} %, the split as the two-figure rule has it in ${n.split} of ${n.told}, the colon within 1e-5 for ${pc(n.colon, n.colonOf)} %, e within 1e-5 for ${pc(n.e, n.rows)} %; of ${n.lungOf} inhaled, the lungs from their five parts within 1e-5 for ${pc(n.lung, n.lungOf)} %, ET from its three for ${pc(n.et, n.etOf)} %`,
        n.rows > 14000 && n.rem / n.rows > 0.997 && n.split === n.told && n.colon / n.colonOf > 0.99 && n.e / n.rows > 0.998 && n.lungOf > 9000 && n.lung / n.lungOf > 0.995 && n.et / n.etOf > 0.995, JSON.stringify(n));
    }
    // Bone surfaces or bone volume, for every nuclide of the ten elements
    // with both models that the database holds by this name: swallowed by
    // the adult, the bone surface and red marrow within 2 % of the
    // database's on the model the page chooses (the other one is 0.1-0.9
    // or 1.2-14 times it). The tantalum-180 pair goes by other names there.
    {
      const offS = []; let count = 0;
      for (const n of Object.keys(d60.index)) {
        if (!['P', 'V', 'Cr', 'Zn', 'Nb', 'Mo', 'Pd', 'Sn', 'Ta', 'W'].includes(n.split('-')[0]) || /^Ta-180/.test(n)) continue;
        const c = cd.rows.filter((x) => x.nuclide === n && x.route === 'ingestion' && x.age === 7300);
        if (c.length !== 1) continue;
        await d60.prepare(n);
        const r = coefficients60(d60, recipe60(d60.cases, 'ingestion', { nuclide: n }), [7300])[0];
        count++;
        for (const k of ['Bone surface', 'Red marrow']) { const v = c[0].H[k], q = r.H[k] / v[v.length - 1]; if (!(Math.abs(q - 1) <= 0.02)) offS.push(`${n} ${k} ${q.toFixed(3)}`); }
      }
      check(`ICRP 60 vs the ICRP database, bone surfaces or bone volume: ${count} nuclides of P, V, Cr, Zn, Nb, Mo, Pd, Sn, Ta and W swallowed by the adult, bone surface and red marrow within 2 %`, count >= 60 && !offS.length, offS.join('; '));
    }
    // Gold breathed in as Type F: every tissue of the body within 0.7 % of
    // the database's, the bladder wall too (2.2-2.5 % low and 1.8 % high
    // with Au.DEF's way from blood straight to the bladder contents).
    {
      const offG = [];
      for (const [nuclide, age] of [['Au-198', 7300], ['Au-198', 365], ['Au-195', 7300], ['Au-199', 3650]]) {
        const c = cd.rows.find((x) => x.nuclide === nuclide && x.route === 'inhalation' && x.type === 'F' && x.age === age);
        await d60.prepare(nuclide);
        const r = coefficients60(d60, recipe60(d60.cases, 'inhalation', { nuclide, type: 'F' }), [age])[0];
        for (const k of ['Liver', 'Kidneys', 'Muscle', 'Red marrow', 'Testes', 'Bladder']) { const v = c.H[k], q = r.H[k] / v[v.length - 1]; if (!(Math.abs(q - 1) <= 0.007)) offG.push(`${nuclide} ${age} d ${k} ${q.toFixed(4)}`); }
      }
      check('ICRP 60 vs the ICRP database, gold Type F: liver, kidneys, muscle, red marrow, testes and bladder wall within 0.7 % (198Au adult and 1 year, 195Au adult, 199Au 10 years)', !offG.length, offG.join('; '));
    }
    // The mass of the body's tissues. Nuclides that go to the whole body,
    // swallowed: the muscle's dose over the first day within 1e-4 of the
    // database's at every age (0.07-0.76 % above it with DCAL's masses). And
    // nuclides that go to the rest of the body beside named organs: a tissue
    // their models do not name within 0.06 % (0.2-0.8 % above).
    {
      const worstB = { whole: 0, dcal: Infinity, rest: 0 };
      for (const nuclide of ['H-3', 'C-14', 'Cl-36', 'At-211', 'Cs-135']) for (const age of AGES_60) {
        worstB.whole = Math.max(worstB.whole, Math.abs((await over(nuclide, age, 'Muscle'))[0] - 1));
        if (nuclide === 'At-211') worstB.dcal = Math.min(worstB.dcal, (await over(nuclide, age, 'Muscle', { dcal: true }))[0] * (1.6e-13 / 1.602176634e-13) - 1);
      }
      for (const nuclide of ['P-33', 'Ca-45', 'Se-79', 'Po-210']) for (const age of AGES_60.slice(1)) worstB.rest = Math.max(worstB.rest, Math.abs((await over(nuclide, age, 'Brain'))[0] - 1));
      check(`ICRP 60 vs the ICRP database, the mass of the body's tissues: 3H, 14C, 36Cl, 135Cs and 211At swallowed, the muscle over the first day within ${(1e5 * worstB.whole).toFixed(0)}e-5 at every age (with DCAL's masses at least ${(1e5 * worstB.dcal).toFixed(0)}e-5 above); 33P, 45Ca, 79Se and 210Po, the brain within ${(1e5 * worstB.rest).toFixed(0)}e-5 from 1 year on`,
        worstB.whole < 1e-4 && worstB.dcal > 5e-4 && worstB.rest < 6e-4, JSON.stringify(worstB));
    }
    // Out of blood. 40K: with the quarter day in the transfer compartment the
    // muscle and the bladder wall follow the database at every time (0.9967
    // falling to 0.9934, and 1.07 at one day, without). 18F and 201Tl with no
    // time in blood: soft tissues to 1e-4, the bone surface and the kidneys
    // within 0.15 % (0.7 % off, and the bladder wall 1.5 %, at 1000 d-1).
    {
      const k = [...await over('K-40', 7300, 'Muscle'), ...await over('K-40', 7300, 'Bladder'), ...await over('K-42', 7300, 'Muscle')];
      const f = [...await over('F-18', 7300, 'Muscle'), ...await over('F-18', 7300, 'Liver'), ...await over('F-18', 7300, 'Bladder')];
      const fb = await over('F-18', 7300, 'Bone surface'), tl = await over('Tl-201', 7300, 'Kidneys');
      const far = (l) => l.reduce((m, x) => Math.max(m, Math.abs(x - 1)), 0);
      check(`ICRP 60 vs the ICRP database, out of blood: 40K and 42K, muscle and bladder wall at every time within ${(100 * far(k)).toFixed(2)} %; 18F muscle, liver and bladder wall within ${(1e5 * far(f)).toFixed(0)}e-5, its bone surface ${(100 * far(fb)).toFixed(2)} %; 201Tl kidneys ${(100 * far(tl)).toFixed(2)} %`,
        far(k) < 0.0025 && far(f) < 1e-4 && far(fb) < 0.0015 && far(tl) < 0.0015, JSON.stringify({ k, f, fb, tl }));
    }
    // Tellurium's rest of the body with the mineral bone in it: the muscle and
    // the brain at every time within 0.1 % (1.005 rising to 1.06 without).
    {
      const te = [];
      for (const nuclide of ['Te-125m', 'Te-127m', 'Te-129m']) for (const tissue of ['Muscle', 'Brain']) te.push(...await over(nuclide, 7300, tissue));
      const farT = te.reduce((m, x) => Math.max(m, Math.abs(x - 1)), 0);
      check(`ICRP 60 vs the ICRP database, tellurium: 125mTe, 127mTe and 129mTe, muscle and brain at every time within ${(100 * farT).toFixed(2)} %`, farT < 0.001, JSON.stringify(te));
    }
    // Nickel: 63Ni's muscle at every age and every time within 1.5e-4 (0.9927
    // to 0.9938 from a month on with Ni.DEF's whole body), its kidneys
    // within 0.15 % (0.92 to 0.96 for intakes in childhood); 59Ni, whose
    // X-rays and electrons give 0.03 % less here in every tissue, 0.05 %.
    {
      let farM = 0, farK = 0, far59 = 0;
      for (const age of AGES_60) {
        for (const x of await over('Ni-63', age, 'Muscle')) farM = Math.max(farM, Math.abs(x - 1));
        for (const x of await over('Ni-63', age, 'Kidneys')) farK = Math.max(farK, Math.abs(x - 1));
        for (const x of await over('Ni-59', age, 'Muscle')) far59 = Math.max(far59, Math.abs(x - 1));
      }
      check(`ICRP 60 vs the ICRP database, nickel at every age and time: 63Ni's muscle within ${(1e5 * farM).toFixed(0)}e-5 and kidneys within ${(100 * farK).toFixed(2)} %, 59Ni's muscle within ${(1e5 * far59).toFixed(0)}e-5`, farM < 1.5e-4 && farK < 0.0015 && far59 < 5e-4, JSON.stringify({ farM, farK, far59 }));
    }
    // Iron: with its other soft tissues in the rest of the body the muscle,
    // liver, spleen and red marrow of the adult follow the database at every
    // time within 0.15 % after 55Fe and 59Fe (the spleen 1.23 of it on the
    // first day, the liver 1.03 in the long run, in BT-Soft), 0.3 % at 10
    // years.
    {
      const fe = { adult: 0, ten: 0 };
      for (const nuclide of ['Fe-55', 'Fe-59']) for (const tissue of ['Muscle', 'Liver', 'Spleen', 'Red marrow']) {
        for (const x of await over(nuclide, 7300, tissue)) fe.adult = Math.max(fe.adult, Math.abs(x - 1));
        for (const x of await over(nuclide, 3650, tissue)) fe.ten = Math.max(fe.ten, Math.abs(x - 1));
      }
      check(`ICRP 60 vs the ICRP database, iron: 55Fe and 59Fe, muscle, liver, spleen and red marrow at every time within ${(100 * fe.adult).toFixed(2)} % for the adult and ${(100 * fe.ten).toFixed(2)} % at 10 years`, fe.adult < 0.0015 && fe.ten < 0.003, JSON.stringify(fe));
    }
    // The airways' parts that the database stores, after intakes by
    // inhalation as Type M by the adult. Beta emitters: the alveolar region
    // (its fourth lung part) within 5e-4 (0.3-0.5 % below it with the
    // trapezoidal rule), and with Publication 66's functions the basal cells
    // of ET1 and ET2 within 2e-4 (63Ni's ET1 a fifth below it by straight
    // lines through the tables), the bronchioles within 0.1 %, the bronchi
    // within 0.35 %. Alpha emitters from 2.2 to 6.1 MeV: ET1 within 0.2 % (239Pu a
    // fifth below it, 244Cm 40 % above by the tables), the bronchi within
    // 0.7 % (147Sm 1.9 and 2.4 times it by the tables).
    {
      const part = async (nuclide, pairs) => {
        const c = cd.rows.find((x) => x.nuclide === nuclide && x.route === 'inhalation' && x.type === 'M' && x.age === 7300);
        await d60.prepare(nuclide);
        const r = coefficients60(d60, recipe60(d60.cases, 'inhalation', { nuclide, type: 'M' }), [7300])[0];
        return pairs.map(([target, key]) => { const v = c.H[key]; return r.Ht[target] / v[v.length - 1]; });
      };
      const PARTS = [['AI', 'Lung part 4'], ['ET1-bas', 'ET part 1'], ['ET2-bas', 'ET part 2'], ['bbe-sec', 'Lung part 3'], ['BBi-sec', 'Lung part 1'], ['BBi-bas', 'Lung part 2']];
      const beta = { ai: [], et: [], bb: [], BB: [] }, alpha = { et1: [], et2: [], bb: [], BB: [] };
      for (const n of ['Ni-63', 'C-14', 'S-35', 'Ca-45', 'Pm-147', 'Cl-36', 'Sr-89', 'P-32', 'Y-90']) {
        const [ai, et1, et2, bb, sec, bas] = await part(n, PARTS);
        beta.ai.push(ai); beta.et.push(et1, et2); beta.bb.push(bb); beta.BB.push(sec, bas);
      }
      for (const n of ['Sm-147', 'Gd-148', 'U-234', 'Pu-239', 'Po-210', 'Am-241', 'Cm-244', 'Cm-242']) {
        const [, et1, et2, bb, sec, bas] = await part(n, PARTS);
        alpha.et1.push(et1); alpha.et2.push(et2); alpha.bb.push(bb); alpha.BB.push(sec, bas);
      }
      const farP = (l) => l.reduce((m, x) => Math.max(m, Math.abs(x - 1)), 0);
      check(`ICRP 60 vs the ICRP database, the airways' parts: after nine beta emitters the alveolar region within ${(1e5 * farP(beta.ai)).toFixed(0)}e-5, the basal cells of ET1 and ET2 within ${(1e5 * farP(beta.et)).toFixed(0)}e-5, the bronchioles within ${(100 * farP(beta.bb)).toFixed(2)} % and the bronchi within ${(100 * farP(beta.BB)).toFixed(2)} %; after eight alpha emitters of 2.2-6.1 MeV ET1 within ${(100 * farP(alpha.et1)).toFixed(2)} %, ET2 within ${(100 * farP(alpha.et2)).toFixed(2)} %, the bronchioles within ${(100 * farP(alpha.bb)).toFixed(2)} % and the bronchi within ${(100 * farP(alpha.BB)).toFixed(2)} %`,
        farP(beta.ai) < 5e-4 && farP(beta.et) < 3e-4 && farP(beta.bb) < 0.0015 && farP(beta.BB) < 0.004
        && farP(alpha.et1) < 0.003 && farP(alpha.et2) < 0.002 && farP(alpha.bb) < 0.002 && farP(alpha.BB) < 0.0075, JSON.stringify({ beta, alpha }));
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
