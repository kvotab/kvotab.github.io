#!/usr/bin/env node
/* ==========================================================================
   THE EROSION/CORROSION MODEL, AGAINST WHAT IT IS SUPPOSED TO REPRODUCE

   Three independent references:

   1. The code documentation, SKBdoc 1895157 section 5: a hydro test file
      (TestCaseHydro_2_0, SKBdoc 1895160) built so that the answers can be
      checked by hand -- 35 failure times at stated values, 17 rejected
      holes for stated reasons, the key outputs of sheet "Info", and the
      erosion and sedimentation rates of TR-16-11 read off its figures.

   2. Closed forms for the special functions and for single holes.

       node resources/tests/erosion_corrosion/test-model.js [--verbose]

   The test file is SKB's and not in the repository: make-local-fixtures.py
   writes a copy into ./local/ (git-ignored); without it the checks that
   need it are skipped, and say so.

   Exit status is 0 when every check passes.
   ========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
const ECModel = require(path.join(jsDir, 'ec-model.js'));
const ECHS = require(path.join(jsDir, 'ec-hsdata.js'));
const ECHydro = require(path.join(jsDir, 'ec-hydro.js'));

const verbose = process.argv.includes('--verbose');
let checks = 0;
const failures = [];

function check(label, ok, detail) {
  checks++;
  const good = ok === true;
  if (!good || verbose) console.log(`${good ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!good) failures.push(label);
}
function close(label, got, want, rtol, atol = 0) {
  const err = Math.abs(got - want);
  const ok = err <= atol + rtol * Math.abs(want);
  check(label, ok, `${got} vs ${want} (${(err / Math.max(Math.abs(want), 1e-300)).toExponential(2)} relative, allowed ${rtol})`);
}

// SKB's code test case, from the local copy that make-local-fixtures.py writes.
const testCaseFile = path.join(__dirname, 'local', 'TestCaseHydro_2_0.csv');
const haveTestCase = fs.existsSync(testCaseFile);
const readTestCase = () => ECHydro.parseText(fs.readFileSync(testCaseFile, 'utf8'), 'TestCaseHydro_2_0.csv');
function skipped(what) {
  console.log(`skip  ${what}: no local copy of the test file (python3 make-local-fixtures.py <folder>)`);
}

/* ======================================================================
   1. Special functions
   ====================================================================== */
console.log('\n--- special functions ---');
{
  const W = ECModel.lambertW;
  close('W(1) = Ω', W(1), 0.5671432904097838, 1e-14);
  close('W(e) = 1', W(Math.E), 1, 1e-14);
  close('W(10)', W(10), 1.7455280027406994, 1e-14);
  close('W(1e6)', W(1e6), 11.383358086140052, 1e-13);
  close('W(1e-6) ≈ x − x²', W(1e-6), 1e-6 - 1e-12 + 1.5e-18, 1e-12);
  close('W(−0.3)', W(-0.3), -0.4894022271802149, 1e-12);
  check('W(−1/e) = −1', W(-1 / Math.E) === -1, String(W(-1 / Math.E)));
  check('W below −1/e is NaN', Number.isNaN(W(-0.4)));
  // The workbook's own VBA gets W to 1e-3; ours must satisfy w·e^w = x exactly.
  for (const x of [0.01, 0.5, 2, 37, 1e4]) close(`w·e^w = x at x = ${x}`, W(x) * Math.exp(W(x)), x, 1e-14);

  const N = ECModel.normInv;
  check('Φ⁻¹(0.5) = 0', N(0.5) === 0, String(N(0.5)));
  close('Φ⁻¹(0.975) = 1.95996…', N(0.975), 1.959963984540054, 2e-9);
  close('Φ⁻¹(0.001)', N(0.001), -3.090232306167813, 2e-9);
  close('Φ⁻¹(1 − 1e-9)', N(1 - 1e-9), 5.997807015008182, 2e-9);
  check('Φ⁻¹ is odd', Math.abs(N(0.2) + N(0.8)) < 1e-12);

  close('DR(2 mM) from the fit', ECModel.dCionRim(2), Math.pow(10, -9.42911 - 1.5309 * Math.log10(2) - 1.88737 * Math.log10(2) ** 2 - 0.783596 * Math.log10(2) ** 3), 1e-15);
}

/* ======================================================================
   2. Derived constants against the workbook's green cells
   ====================================================================== */
console.log('\n--- derived constants ---');
{
  const p = ECModel.defaults();
  const k = ECModel.derived(p);
  close('dBuffer = 0.35 m', k.dBuffer, 0.35, 1e-15);
  // qLim = 1/DiffConst² with DiffConst = sqrt(dBuffer/(1.13²·DWater·π·(r²−rc²)/2))
  const diffConst = Math.sqrt(0.35 / (1.13 ** 2 * 0.0315 * Math.PI * (0.875 ** 2 - 0.525 ** 2) / 2));
  close('qLim = 1/DiffConst² (workbook Info!C60)', k.qLim, 1 / diffConst ** 2, 1e-14);
  close('qLim ≈ 0.08845 m³/yr (SKBdoc 1895157, 5.2)', k.qLim, 0.08845, 2e-4);
  // CorrHoleFact = dCan·π·rCan·hCorr·RhoCu/(fHS·MoMassCu)
  close('CorrHoleFact (Info!C54)', k.corrHoleFact, 0.047 * Math.PI * 0.525 * 0.35 * 8920 / (2 * 63.55), 1e-14);
  // Effective DR from the temperate and glacial values
  const dr = (c) => ECModel.dCionRim(c);
  close('effective DR (Info!C119)', k.dR, (0.5 * Math.sqrt(dr(3)) + 0.5 * Math.sqrt(dr(0.1))) ** 2, 1e-14);
  const p2 = { ...p, effectiveDR: false, cIon: 2 };
  close('DR(cIon) when not effective', ECModel.derived(p2).dR, dr(2), 1e-14);
  // rRSS for sedimentation: forced, and solved
  close('rRSS_Sed forced', k.rRssSed, 0.925, 1e-15);
  const k3 = ECModel.derived({ ...p, forceRrss: false });
  const fExp = 1e-9 * 31536000 * (0.574 - 0.015) * 2700 / 1000;
  close('rRSS_Sed = FExp/W(FExp/r) (Info!C100)', k3.rRssSed, fExp / ECModel.lambertW(fExp / 0.875), 1e-13);
  // SpallingFactor = sqrt(4/π·Dp·WZone·LZone·epsZone/DZone), Dp in m²/yr
  close('SpallingFactor (Info!C72)', k.spallingFact, Math.sqrt(4 / Math.PI * 1e-11 * 31536000 * 0.5 * 8 * 0.02 / 0.1), 1e-14);
  close('QeqGeo (Info!C76)', k.qeqGeo, 5.5 / 3.1 * 1e-10 * 31536000, 1e-14);
  close('CorrRateBuffOnly (Info!C75)', k.corrRateBuffOnly, 1e-5 * 2 * 63.55 / 8920 * 1e-10 * 31536000 / 0.35, 1e-14);
  close('CorrosionFactor (Info!C65)', k.corrosionFactor, 1e-5 * 2 * 63.55 * 7 / (2 * Math.PI * 0.525 * 5 * 8920), 1e-14);
  check('hCorr pessimistic = dCan·π/2', ECModel.derived({ ...p, pessCorrGeo: true }).hCorr === 0.047 * Math.PI / 2);
}

/* ======================================================================
   3. The parameter catalogue
   ====================================================================== */
console.log('\n--- catalogue ---');
{
  const keys = new Set();
  let dup = false;
  for (const d of ECModel.PARAMS) { if (keys.has(d.key)) dup = true; keys.add(d.key); }
  check('no duplicate parameter keys', !dup);
  check('every parameter is in a group', ECModel.PARAMS.every((d) => ECModel.GROUPS.some((g) => g.id === d.group)));
  const { params, unknown } = ECModel.normalise({ mBuffAdv: '600', fpcFiltering: 'false', buffModel: 'Nonsense', efpcNumber: 4.6, bogus: 1 });
  check('normalise coerces numbers', params.mBuffAdv === 600);
  check('normalise coerces booleans', params.fpcFiltering === false);
  check('normalise refuses an unknown option', params.buffModel === 'NewKTH');
  check('normalise rounds integers', params.efpcNumber === 5);
  check('normalise reports unknown keys', unknown.length === 1 && unknown[0] === 'bogus');
}

/* ======================================================================
   4. The code documentation's test case (SKBdoc 1895157, section 5)
   ====================================================================== */
console.log('\n--- TestCaseHydro_2_0 with the SR-Site settings ---');
if (!haveTestCase) skipped('the code test case');
else {
  const hydro = readTestCase();
  check('the test file has 6017 positions', hydro.n === 6017, String(hydro.n));
  check('and no warnings', hydro.warnings.length === 0, hydro.warnings.join(' | '));
  // "SR-Site default settings": the OldKTH erosion model with ftDilute 0.25.
  const p = { ...ECModel.defaults(), buffModel: 'OldKTH', fTDilute: 0.25, hsTable: 'HSTest' };
  const r = ECModel.evaluate(hydro, ECHS.HS_TEST, p);
  const k = r.key;
  check('35 failure times', r.failures.length === 35, String(r.failures.length));
  const per = (id) => r.failures.filter((f) => f.id === id).map((f) => f.tFail);
  check('10 for hole 1, 10 for 2, 10 for 3, 5 for 4', [1, 2, 3, 4].map((id) => per(id).length).join(',') === '10,10,10,5',
    [1, 2, 3, 4].map((id) => per(id).length).join(','));
  // Row 1: qeb < qlim, 850,000 .. 940,000 in steps of 10,000 (tAdv negligible)
  const t1 = per(1);
  check('hole 1: qeb below qlim', r.columns.qEb[0] < k.qLim, `${r.columns.qEb[0]} vs ${k.qLim}`);
  close('hole 1 first failure 850,000 yr', t1[0], 850000, 2e-4);
  close('hole 1 last failure 940,000 yr', t1[9], 940000, 2e-4);
  check('hole 1 steps of 10,000 yr', t1.every((t, j) => Math.abs(t - 850000 - 10000 * j) < 200), t1.map((t) => Math.round(t)).join(' '));
  // Row 2: qeb > qlim, 85,000 .. 94,000
  const t2 = per(2);
  check('hole 2: qeb above qlim', r.columns.qEb[1] > k.qLim);
  close('hole 2 first failure 85,000 yr', t2[0], 85000, 2e-4);
  close('hole 2 last failure 94,000 yr', t2[9], 94000, 2e-4);
  // Row 3: tAdv 50,000 with the SR-Site erosion model
  close('hole 3: tAdv = 50,000 yr', r.columns.tAdv[2], 50000, 2e-4);
  close('hole 3 first failure 900,000 yr', per(3)[0], 900000, 2e-4);
  close('hole 3 last failure 990,000 yr', per(3)[9], 990000, 2e-4);
  // Row 4: tAdv 100,000, only five sulphide values fail in time
  close('hole 4: tAdv = 100,000 yr', r.columns.tAdv[3], 100000, 2e-4);
  close('hole 4 first failure 950,000 yr', per(4)[0], 950000, 2e-4);
  close('hole 4 last failure 990,000 yr', per(4)[4], 990000, 2e-4);

  // Rejections: rows are IDs + 1 in the documentation.
  const rejected = [];
  for (let i = 0; i < r.n; i++) if (r.columns.reject[i]) rejected.push(r.id[i]);
  check('17 rejected positions', k.nReject === 17, String(k.nReject));
  check('ID 11 rejected by FPC', r.columns.rejectBits[10] === ECModel.REJECT.FPC);
  check('IDs 12–16 rejected by EFPC', [11, 12, 13, 14, 15].every((i) => r.columns.rejectBits[i] === ECModel.REJECT.EFPC));
  check('ID 17 rejected by fracture length', r.columns.rejectBits[16] === ECModel.REJECT.FLEN);
  check('ID 18 rejected by T/L', r.columns.rejectBits[17] === ECModel.REJECT.TL);
  check('IDs 19–24 escape every criterion', [18, 19, 20, 21, 22, 23].every((i) => r.columns.reject[i] === 0));
  check('IDs 25–33 rejected by EFPC', [24, 25, 26, 27, 28, 29, 30, 31, 32].every((i) => r.columns.rejectBits[i] === ECModel.REJECT.EFPC));
  check('the rejected set is exactly those', rejected.join(',') === '11,12,13,14,15,16,17,18,25,26,27,28,29,30,31,32,33', rejected.join(','));

  // Key outputs, Info!C27–C38.
  close('mean number of failed canisters = 3.5', k.meanFailed, 3.5, 1e-12);
  close('corrected = 3.5 (6000/(6017 − 17) = 1)', k.meanFailedCorrected, 3.5, 1e-12);
  check('failed at highest sulphide = 4', k.nFailedHighestHs === 4, String(k.nFailedHighestHs));
  close('mean failed at 100,000 years, corrected = 1', k.meanFailed1e5Corrected, 1, 1e-12);
  close('earliest failure 85,000 yr', k.earliestFailure, 85000, 2e-4);
  check('total positions 6017', k.nTot === 6017);
  check('advective positions at 1e6 = 4', k.nAdvAtLim === 4, String(k.nAdvAtLim));
  check('advective positions at 1e5 = 3', k.nAdv1e5 === 3, String(k.nAdv1e5));
  // Rows 1 and 2 have δ = 1E+99, which makes tAdv about 1e-56 rather than 0;
  // the workbook displays that as 0.
  check('earliest advective time 0 (to display)', k.earliestAdvection < 1e-6, String(k.earliestAdvection));
  check('no edge positions', k.anyEdge === false);
  check('check sum 0', k.checkSum === 0);
  check('rows carry F and tw of their hole', r.failures[0].f === 100001 && r.failures[0].tw === 101);

  // The order of the table: hole by hole, highest sulphide first.
  check('table ordered by hole then descending sulphide',
    r.failures.every((f, i) => i === 0 || f.hole > r.failures[i - 1].hole || (f.hole === r.failures[i - 1].hole && f.hs < r.failures[i - 1].hs)));
}

/* ======================================================================
   5. The TR-16-11 models on the test file (SKBdoc 1895157, section 5.7)
   ====================================================================== */
console.log('\n--- TR-16-11 erosion and sedimentation on the test file ---');
if (!haveTestCase) skipped('the TR-16-11 rates on the test file');
else {
  const hydro = readTestCase();
  // "ion concentration 2 mM, force RRSS disabled": and no effective DR.
  const p = { ...ECModel.defaults(), buffModel: 'NewKTH', cIon: 2, forceRrss: false, effectiveDR: false, jExp: 1000 };
  const r = ECModel.evaluate(hydro, ECHS.HS_TEST, p);
  // Rows 26–29 (IDs 25–28): δ = 1e-4 m, v = 1e-7 .. 1e-4 m/s
  const want = [8.3e-3, 1.3e-2, 2.5e-2, 5.7e-2];
  [24, 25, 26, 27].forEach((i, j) => {
    close(`hole ${i + 1}: v = 1e-${7 - j} m/s`, r.columns.v[i] / 31536000, Math.pow(10, -7 + j), 1e-9);
    close(`hole ${i + 1}: NErosion = ${want[j]} kg/yr (figure 4-5)`, r.columns.nErosion[i], want[j], 0.04);
  });
  // Rows 30–34 (IDs 29–33): apertures 1e-6 .. 1e-4, JExp = 1000, vertical
  const ap = [1e-6, 5e-6, 1e-5, 5e-5, 1e-4];
  const loss = [5.8e-3, 2.9e-2, 5.8e-2, 0.29, 0.58];
  const sed = [3.3e-5, 4.1e-3, 3.3e-2, 4.1, 33];
  ap.forEach((d, j) => {
    const i = 28 + j;
    check(`hole ${i + 1}: aperture ${d}`, r.columns.trapp[i] === d);
    close(`hole ${i + 1}: max loss rate at rim ${loss[j]} kg/yr (figure 4-7)`, r.columns.nMaxLoss[i], loss[j], 0.02);
    close(`hole ${i + 1}: max sedimentation rate ${sed[j]} kg/yr (figure 4-7)`, r.columns.nMaxSed[i], sed[j], 0.02);
  });
  // These holes are EFPC-rejected on purpose, so they produce no failures.
  check('the TR-16-11 rows produce no failures', r.failures.every((f) => f.hole < 24 || f.hole > 33));
}

/* ======================================================================
   7. Single-hole closed forms, and the options that change a formula
   ====================================================================== */
console.log('\n--- single holes ---');
{
  const one = (over) => {
    const h = { name: 'one', format: 'test', n: 1, id: [1], warnings: [], meta: {} };
    for (const c of ECHydro.COLUMNS) h[c] = Float64Array.from([over[c] ?? 0]);
    return h;
  };
  const p = ECModel.defaults();
  const k = ECModel.derived(p);
  const year = p.secPerYear;
  // A hole with U0 = 1e-3 m/yr and δ = 1e-4 m, NewKTH with forced rRSS.
  const h = one({ u0: 1e-3, trapp: 1e-4, tw: 100, f: 1e6, flen: 10 });
  const r = ECModel.evaluate(h, [1e-3, 1e-4], p);
  const v = 1e-3 * 5 / 1e-4;
  close('v = U0·w/δ', r.columns.v[0], v, 1e-15);
  const nEro = 2700 * 1e-4 * 0.015 * 4 * Math.sqrt(k.dR * 0.925 * v / year) * year;
  close('NErosion with rRSS = 0.925', r.columns.nErosion[0], nEro, 1e-14);
  close('tAdv = MBuffAdv/(N·ftDilute)', r.columns.tAdv[0], 1200 / (nEro * 0.5), 1e-14);
  const q = 2 * v * 1e-4 * 2 * 0.875;
  close('q = fconc·v·δ·2·r', r.columns.qEb[0], q, 1e-14);
  close('Qeq = min(1.13·sqrt(q·Dw·Vzone)/dBuffer, q)', r.columns.qeqEb[0], Math.min(1.13 * Math.sqrt(q * 0.0315 * k.vZone) / 0.35, q), 1e-14);
  check('the 1e-3 M value fails in time, the 1e-4 M value does not', r.failures.length === 1 && r.failures[0].hs === 1e-3);
  close('tCorr = CorrHoleFact/(Qeq·[HS])', r.failures[0].tCorr, k.corrHoleFact / (r.columns.qeqEb[0] * 1e-3), 1e-14);
  close('tFail = tAdv + tCorr', r.failures[0].tFail, r.columns.tAdv[0] + r.failures[0].tCorr, 1e-15);
  check('HSMin lies between the two', r.columns.hsMin[0] > 1e-4 && r.columns.hsMin[0] < 1e-3);
  check('nHsPoints = 1', r.columns.nHsPoints[0] === 1);
  close('HSMin = CorrHoleFact/Qeq/(tLim − tAdv)', r.columns.hsMin[0], k.corrHoleFact / r.columns.qeqEb[0] / (1e6 - r.columns.tAdv[0]), 1e-14);
  check('gradient = v·δ/(T·SecpYr)', Math.abs(r.columns.gradient[0] - v * 1e-4 / ((1e-4 / 0.5) ** 2 * year)) < 1e-20);
  close('Qeq_dz = SpallingFactor·sqrt(v·δ·min(16, FLEN))', r.columns.qeqDz[0], k.spallingFact * Math.sqrt(v * 1e-4 * 10), 1e-14);
  close('tFreshWater', r.columns.tFresh[0], 100 + (1e6) ** 2 * 1.26e-6 * 0.0037 / 0.088856 ** 2 / 4, 1e-14);

  // The unforced rRSS goes through the Lambert W function.
  const r2 = ECModel.evaluate(h, [1e-4], { ...p, forceRrss: false });
  const g2 = 0.5 * 1e-9 * Math.PI * (0.574 - 0.015) / (2 * 0.015 * Math.sqrt(k.dR * 0.875 * v / year));
  close('rRSS = r·(G/2 / W(G/2))²', r2.columns.rRss[0], 0.875 * (g2 / ECModel.lambertW(g2)) ** 2, 1e-13);

  // OldKTH: Aero·v^0.41·δ
  const r3 = ECModel.evaluate(h, [1e-4], { ...p, buffModel: 'OldKTH' });
  close('RErosion = Aero·v^0.41·δ', r3.columns.lossRate[0], 27.210847987074 * v ** 0.41 * 1e-4, 1e-14);
  // Sediment and Ero+Sed
  const r4 = ECModel.evaluate(h, [1e-4], { ...p, buffModel: 'Sediment' });
  const nLoss = 1000 * 1e-4 * 2 * Math.PI * 0.925;
  const nSedMax = (1e-4) ** 3 / (12 * 0.001) * 17 * 9.81 * 0.015 * 2700 * 2 * 0.925 * year;
  close('NSedimentation = min(loss, sedimentation)', r4.columns.lossRate[0], Math.min(nLoss, nSedMax), 1e-13);
  const r5 = ECModel.evaluate(h, [1e-4], { ...p, buffModel: 'Ero+Sed' });
  close('Ero+Sed adds the two', r5.columns.lossRate[0], nEro + Math.min(nLoss, nSedMax), 1e-13);
  // Amphos
  const r6 = ECModel.evaluate(h, [1e-4], { ...p, buffModel: 'Amphos2023' });
  close('Amphos2023: 1.993e13/1000·(v/yr)^1.0484·δ^2.0156', r6.columns.lossRate[0], 1.993e13 / 1000 * (v / year) ** 1.0484 * (1e-4) ** 2.0156, 1e-13);
  const r7 = ECModel.evaluate(h, [1e-4], { ...p, buffModel: 'Amphos2025' });
  const a25 = (c) => 7.03e3 / 1000 * 1.75 * Math.sqrt(v / year) * (0.1) ** 1.2 * c ** -0.7;
  close('Amphos2025: temperate/glacial weighted', r7.columns.lossRate[0], 0.5 * a25(3) + 0.5 * a25(0.1), 1e-13);
  // Initial advection
  const r8 = ECModel.evaluate(h, [1e-4], { ...p, initialAdvection: true });
  check('initial advection: tAdv = 0', r8.columns.tAdv[0] === 0);
  // Pessimistic aperture: v changes, q does not.
  const r9 = ECModel.evaluate(h, [1e-4], { ...p, pessAperture: true });
  const dPess = 0.275 * (1e-4 / 0.5) ** (2 * 0.297);
  close('pessimistic aperture', r9.columns.aperture[0], dPess, 1e-14);
  close('v uses the pessimistic aperture', r9.columns.v[0], 1e-3 * 5 / dPess, 1e-14);
  close('q is still U0·w·2·r·fconc', r9.columns.qEb[0], q, 1e-12);
  // Pessimistic corrosion geometry
  const r10 = ECModel.evaluate(h, [1e-4], { ...p, pessCorrGeo: true });
  close('pessimistic geometry: CorrHoleFact with hCorr = dCan·π/2', r10.key.corrHoleFact, k.corrHoleFact * (0.047 * Math.PI / 2) / 0.35, 1e-14);
  // Flow averaging
  const r11 = ECModel.evaluate(h, [1e-4], { ...p, averageFlow: true, averageFlowFactor: 4 });
  close('flow averaging divides CorrHoleFact', r11.key.corrHoleFact, k.corrHoleFact / 4, 1e-14);
  // Cubic transmissivity law and T/L
  const hTL = one({ u0: 1e-3, trapp: 1e-3, flen: 500 });
  const rDoe = ECModel.evaluate(hTL, [1e-4], p);
  check('Doe: (1e-3/0.5)² = 4e-6 > 1e-6 with FLEN 500 → T/L rejects', rDoe.columns.rejectBits[0] === ECModel.REJECT.TL);
  const rCub = ECModel.evaluate(hTL, [1e-4], { ...p, transmissivityLaw: 'Cubic', cubicRefAperture: 0.01 });
  check('cubic with a = 0.01: (0.1)³ = 1e-3 → T/L rejects too', rCub.columns.rejectBits[0] === ECModel.REJECT.TL);
  const rCub2 = ECModel.evaluate(hTL, [1e-4], { ...p, transmissivityLaw: 'Cubic', cubicRefAperture: 0.2 });
  check('cubic with a = 0.2: (5e-3)³ = 1.25e-7 is below the limit → accepted', rCub2.columns.reject[0] === 0);
  // Darcy and inflow criteria
  const rD = ECModel.evaluate(one({ u0: 0.02, trapp: 1e-4 }), [1e-4], { ...p, highDarcyFiltering: true });
  check('Darcy criterion', rD.columns.rejectBits[0] === ECModel.REJECT.DARCY);
  const hI = one({ u0: 1e-3, trapp: 1e-4 }); hI.inflowReject = Float64Array.from([1]);
  check('inflow criterion, off by default', ECModel.evaluate(hI, [1e-4], p).columns.reject[0] === 0);
  check('inflow criterion, on', ECModel.evaluate(hI, [1e-4], { ...p, highFlowFiltering: true }).columns.rejectBits[0] === ECModel.REJECT.INFLOW);
  // OKFLAG skips without rejecting
  const rO = ECModel.evaluate(one({ u0: 1e-3, trapp: 1e-4, okflag: 1 }), [1e-4], p);
  check('OKFLAG ≠ 0 skips the hole', rO.columns.skip[0] === 1 && rO.columns.reject[0] === 0 && rO.failures.length === 0);
  check('and it still counts in the total', rO.key.nAccepted === 1);
  // No sulphide value fails: an empty table is not an error.
  const rNone = ECModel.evaluate(one({ u0: 1e-9, trapp: 1e-4 }), [1e-4], p);
  check('a hole that cannot fail yields no rows', rNone.failures.length === 0 && rNone.key.earliestFailure === null);
  check('the sulphide table must have positive values', (() => { try { ECModel.evaluate(h, [0, -1], p); return false; } catch (e) { return /positive/.test(e.message); } })());
  // The reasons string
  check('rejectReasons names the bits', ECModel.rejectReasons(ECModel.REJECT.FPC | ECModel.REJECT.TL).join(',') === 'FPC,T/L');
}

/* ======================================================================
   8. Several realisations, distributions, the time history
   ====================================================================== */
console.log('\n--- realisations and series ---');
if (!haveTestCase) skipped('the realisations, distributions and time history of the test file');
else {
  const hydro = readTestCase();
  const p = { ...ECModel.defaults(), buffModel: 'OldKTH', fTDilute: 0.25 };
  const many = ECModel.evaluateMany([hydro, hydro], ECHS.HS_TEST, p);
  const one = ECModel.evaluate(hydro, ECHS.HS_TEST, p);
  check('two identical realisations give twice the rows', many.table.length === 2 * one.failures.length);
  check('with the realisation number on each row', many.table.slice(0, one.failures.length).every((r) => r.dfn === 1) && many.table.slice(one.failures.length).every((r) => r.dfn === 2));
  check('and running index', many.table.every((r, i) => r.index === i + 1));
  close('the corrected mean is the mean over realisations', many.summary.meanFailedCorrected.mean, one.key.meanFailedCorrected, 1e-15);
  check('min = max for identical realisations', many.summary.nReject.min === many.summary.nReject.max);
  check('the highest-sulphide count is summed', many.summary.nFailedHighestHsTotal === 2 * one.key.nFailedHighestHs);

  const d = ECModel.distributions(one);
  check('eight distributions', Object.keys(d).filter((k) => !k.startsWith('_')).length === 8);
  for (const [name, dist] of Object.entries(d)) {
    if (name.startsWith('_')) continue;
    check(`${name}: every series has one value per hole`, dist.series.every((s) => s.values.length === one.n));
  }
  // Zeros for deformation-zone holes and, in the "after rejection" series, for rejected ones.
  const fpc2 = Array.from(one.columns.fpc).findIndex((x) => x === 2);
  if (fpc2 >= 0) check('deformation-zone holes are zero in the Qeq series', d.qeq.series[0].values[fpc2] === 0);
  const rej = Array.from(one.columns.reject).findIndex((x, i) => x === 1 && one.columns.fpc[i] !== 2 && one.columns.qeqHydro[i] > 0);
  if (rej >= 0) check('a rejected hole is kept in "all" and zeroed "after rejection"', d.qeq.series[2].values[rej] > 0 && d.qeq.series[3].values[rej] === 0);
  // The corrosion rate for advective conditions is 1e6·C·dCan/CorrHoleFact·Qeq
  const i0 = Array.from(one.columns.qeqEb).findIndex((x) => x > 0);
  close('CorrAdv = 1e6·[HS]·dCan·Qeq/CorrHoleFact', d.corrAdv.series[0].values[i0], 1e6 * 1e-5 * 0.047 / one.key.corrHoleFact * one.columns.qeqEb[i0], 1e-14);
  const th = ECModel.timeHistory([one], 41, 100);
  check('time history spans 100 yr to the assessment time', th.t[0] === 100 && Math.abs(th.t[40] - 1e6) < 1e-6);
  check('advective count reaches the key output', th.nAdv[40] === one.key.nAdvAtLim, `${th.nAdv[40]} vs ${one.key.nAdvAtLim}`);
  close('failed count reaches the corrected mean', th.nFail[40], one.key.meanFailedCorrected, 1e-12);
  check('monotone in time', th.nFail.every((x, i) => i === 0 || x >= th.nFail[i - 1]) && th.nAdv.every((x, i) => i === 0 || x >= th.nAdv[i - 1]));

  const rem = ECModel.remainingThickness(one, 1e6, one.key.hsMax);
  check('remaining thickness: one value per accepted hole', rem.length === one.key.nAccepted);
  check('never below zero or above dCan', rem.every((x) => x >= 0 && x <= 0.047));
  const gone = Array.from(rem).filter((x) => x === 0).length;
  check('holes corroded through at 1e6 at the highest sulphide = the highest-sulphide count', gone === one.key.nFailedHighestHs, `${gone} vs ${one.key.nFailedHighestHs}`);
}
{
  // ECDF
  const e = ECModel.ecdf(Float64Array.from([0, 0, 1, 2, 3, 4]));
  check('ecdf drops zeros and keeps their share', e.zeroFraction === 2 / 6 && e.x[0] === 1 && Math.abs(e.y[0] - 3 / 6) < 1e-15 && e.y[e.y.length - 1] === 1);
  check('ecdf is monotone', e.x.every((x, i) => i === 0 || x >= e.x[i - 1]) && e.y.every((y, i) => i === 0 || y >= e.y[i - 1]));
  const big = ECModel.ecdf(Float64Array.from({ length: 10000 }, (_, i) => i + 1), 100);
  check('ecdf thins long arrays and ends at the maximum', big.x.length <= 102 && big.x[big.x.length - 1] === 10000 && big.y[big.y.length - 1] === 1);
}

/* ======================================================================
   9. Reading hydro files
   ====================================================================== */
console.log('\n--- hydro files ---');
{
  // A ConnectFlow CSV with the full 29 columns, a BOM and a decimal comma.
  const csv = '﻿NPOINT,XS,YS,ZS,XE,YE,ZE,OKFLAG,T0,U0,QEQ,TW,F,L,TRAPP,TW_TUN,L_TUN,TW_EDZ,L_EDZ,UR,LR_TUN,TW_CPM,L_CPM,F_CPM,TR_TUN,QEQR,FPC,EFPC,FLEN\n'
    + '1.000000000E+00,1,2,3,4,5,6,0,2000,6.336E-05,2.218E-05,366.9,2.65E+06,1171,1.868E-05,0,0,0,0,0,0,34.66,797.8,6.944E-07,0,0,1,0,230.017\n'
    + '2,1,2,3,4,5,6,1,2000,0,0,164.8,1.548E+06,827.9,0,0,0,0,0,0,0,3.381,82.82,6.763E-08,0,0,0,0,0\n\n';
  const h = ECHydro.parseText(csv, 'x.csv');
  check('CSV: two holes', h.n === 2 && h.format === 'ConnectFlow CSV');
  check('CSV: ids are integers', h.id[0] === 1 && h.id[1] === 2);
  check('CSV: columns read', h.u0[0] === 6.336e-5 && h.trapp[0] === 1.868e-5 && h.fpc[0] === 1 && h.flen[0] === 230.017 && h.okflag[1] === 1);
  check('CSV: no warnings', h.warnings.length === 0, h.warnings.join('|'));

  // PTB
  const ptb = '# PARAMETER TABLE FILE FROM CONNECTFLOW\n#\n# NUMBER OF COLUMNS DEFINED\n16\n# NUMBER OF TIMES THEY ARE USED\n     2     2\n# HOW MANY TIMES THEY COULD BE USED\n     2     2\n# THE PARAMETER TABLE:\n'
    + '# POINT    XS        YS         ZS         XE         YE         ZE     OKFLAG        T0         U0         QEQ         TW        F           L        TRAPP      TW_TUN     L_TUN      TW_EDZ      L_EDZ        UR      LR_TUN     TW_CPM      L_CPM      F_CPM      TR_TUN       QEQR     FPC EFPC   FLEN\n'
    + '    1 1631090.70 6700708.24    -472.23 1631550.69 6702314.42      -0.16       1       2.000E+03  0.000E+00  0.000E+00  1.318E+02  1.310E+06  1.301E+03  0.000E+00  6.088E+05  5.102E+00  1.010E+01  7.673E+01  0.000E+00  0.000E+00  6.412E+03  1.972E+03  6.372E+05  0.000E+00  0.000E+00   0   0    0.000\n'
    + '    2 1631085.79 6700712.33    -475.71 1631392.09 6700946.76      -3.13       0       2.000E+03  6.489E-05  2.248E-05  1.662E+02  2.410E+06  1.741E+03  1.868E-05  0.000E+00  0.000E+00  0.000E+00  0.000E+00  0.000E+00  0.000E+00  3.709E+02  4.020E+01  7.419E-06  0.000E+00  0.000E+00   1   0  230.017\n';
  const hp = ECHydro.parseText(ptb, 'x.ptb');
  check('PTB detected', hp.format === 'ConnectFlow PTB' && hp.n === 2);
  check('PTB: columns read', hp.u0[1] === 6.489e-5 && hp.trapp[1] === 1.868e-5 && hp.fpc[1] === 1 && hp.flen[1] === 230.017 && hp.okflag[0] === 1 && hp.tw[0] === 131.8);

  // Kemakta CSV (2.0 "pirouz"): three particle rows for two holes
  const kem = 'Name,CG-x,CG-y,CG-z,Transmissivity [m/s] sumover all fully crossing fractures,Number of fractures in contact with Deposition hole,Number of fractures fully crossing a Deposition hole,iFPC,iEFPC,Porosity (ECPM),U [m/year],Velocity (ECPM) [m/year],Qeq (ECPM) [m3/year],Path-length [m],tw [year],F [year/m],End location,X - End coordinate,Y - End coordinate,Z - End coordinate,particle ID (nop),U2D [m2/year],Ueq [m/year],Utot [m/year],Pe [-]\n'
    + 'DH-14,-1738,11103,-469,3.1e-09,2,1,-5904459,0,1.15e-05,2.89e-05,2.5,0.000109,6613,178.2,9367408,sea,-2928,14656,-16,1,0.00023,2.89e-05,2.5,69.5\n'
    + 'DH-14,-1738,11103,-469,3.1e-09,2,1,-5904459,0,1.15e-05,2.89e-05,2.5,0.000109,6613,180,9400000,sea,-2928,14656,-16,2,0.00023,2.89e-05,2.5,69.5\n'
    + 'DH-15,-1731,11104,-469,0,1,0,0,7,1.25e-06,1.88e-08,0.015,9.2e-07,2987,34.6,591570,sea,-1808,12352,-16,2,1.5e-07,1.88e-08,0.015,0.41\n';
  const hk = ECHydro.parseText(kem, 'pm.csv', { totalHoles: 5 });
  check('Kemakta CSV detected', hk.format === 'DarcyTools CSV' && hk.meta.variant === 'csv');
  check('first particle row per hole, padded to the layout', hk.n === 5 && hk.meta.holesInFile === 2 && hk.meta.padded === 3 && hk.tw[0] === 178.2);
  check('|iFPC| → FPC, |iEFPC| → EFPC', hk.fpc[0] === 5904459 && hk.efpc[1] === 7);
  close('TRAPP = 8·porosity/n', hk.trapp[0], 8 * 1.15e-5 / 2, 1e-15);
  close('U0 = U·8/w', hk.u0[0], 2.89e-05 * 8 / 5, 1e-15);
  check('velocity is not direct for this variant', hk.velocityIsDirect === false);
  check('warns about FLEN and padding', hk.warnings.some((w) => /FLEN/.test(w)) && hk.warnings.some((w) => /padded/.test(w)));

  // DarcyTools dtpm with T/F flags and a Total DHs line
  const dtpm = 'Some header\nTotal DHs: 4\nDHs intersected by fractures/ZFMs: 3\n'
    + 'Name,Collected,ZFMC,FPC,EFPC-5,Aperture [m],Utot [m/year],Qeq (ECPM) [m3/year],tw [year],F [year/m]\n'
    + 'DH-1,T,T,T,T,1e-4,3.2,1e-4,200,1e6\n'
    + 'DH-2,T,T,F,T,2e-4,1.1,2e-4,300,2e6\n'
    + 'DH-3,F,F,T,F,3e-4,0.5,3e-4,400,3e6\n';
  const hd = ECHydro.parseText(dtpm, 'pm.dtpm');
  check('dtpm detected with the layout size from the header', hd.format === 'DarcyTools dtpm' && hd.n === 4 && hd.meta.totalFromFile === 4);
  check('T/F flags: FPC=F → 1, ZFMC=F → 2, EFPC-5=F → 5, Collected=F → OKFLAG 1', hd.fpc[1] === 1 && hd.fpc[2] === 2 && hd.efpc[2] === 5 && hd.okflag[2] === 1 && hd.okflag[0] === 0);
  check('Utot is the velocity', hd.velocityIsDirect === true && hd.u0[0] === 3.2 && hd.trapp[0] === 1e-4);
  // and the model uses it as such
  const rd = ECModel.evaluate(hd, [1e-4], ECModel.defaults());
  check('the model takes v = Utot for a dtpm table', rd.columns.v[0] === 3.2);

  // Inflow list
  const set = ECHydro.parseInflowList('# ids\n1, 2\n5\n7,0\n8,1\n');
  check('inflow list parses ids and flags', set.has('1') && set.has('2') && set.has('5') && !set.has('7') && set.has('8'));
  const hh = ECHydro.parseText(csv, 'x.csv');
  check('applyInflowList marks matching holes', ECHydro.applyInflowList(hh, set) === 2 && hh.inflowReject[0] === 1 && hh.inflowReject[1] === 1);

  // Refusals
  check('a file without U0 is refused with the header quoted', (() => { try { ECHydro.parseText('a,b,c\n1,2,3\n', 'x.csv'); return false; } catch (e) { return /U0/.test(e.message) && /a, b, c/.test(e.message); } })());
  // Round trip through toCsv
  const back = ECHydro.parseText(ECHydro.toCsv(h), 'rt.csv');
  check('toCsv round-trips', back.n === 2 && back.u0[0] === h.u0[0] && back.flen[0] === h.flen[0] && back.id[1] === 2);
}

/* ======================================================================
   10. The sulphide tables
   ====================================================================== */
console.log('\n--- sulphide tables ---');
{
  const wb = JSON.parse(fs.readFileSync(path.join(__dirname, 'ref', 'hsdata-workbook.json'), 'utf8'));
  check('HSForsmark: 46 values as in the workbook', ECHS.HS_FORSMARK.length === 46 && wb.HSForsmark.every((x, i) => x === ECHS.HS_FORSMARK[i]));
  check('HSLaxemar: 51 values as in the workbook', ECHS.HS_LAXEMAR.length === 51 && wb.HSLaxemar.every((x, i) => x === ECHS.HS_LAXEMAR[i]));
  check('HSTest: 10 values as in the workbook', ECHS.HS_TEST.length === 10 && wb.HSTest.every((x, i) => Math.abs(x - ECHS.HS_TEST[i]) < 1e-20));
  check('tables are descending', ['HS_FORSMARK', 'HS_LAXEMAR', 'HS_TEST'].every((k) => ECHS[k].every((x, i) => i === 0 || x <= ECHS[k][i - 1])));
  close('HSForsmark mean (HSData!C5)', ECHS.describe(ECHS.HS_FORSMARK).mean, 5.079876016585353e-06, 1e-12);
  close('HSLaxemar mean (HSData!D5)', ECHS.describe(ECHS.HS_LAXEMAR).mean, 5.514973406564646e-06, 1e-12);
  // The generated distributions
  const g = ECHS.generic({ n: 20000 });
  const dg = ECHS.describe(g);
  check('shifted lognormal: descending, n values', g.length === 20000 && g.every((x, i) => i === 0 || x <= g[i - 1]));
  close('shifted lognormal: mean ≈ mean + shift', dg.mean, 6.29301e-6 + 1.2e-7, 0.03);
  check('shifted lognormal: nothing below the shift', dg.min > 1.2e-7);
  const l = ECHS.generic({ kind: 'log10-normal', n: 10001 });
  close('log10-normal: median = 10^mu', l[5000], Math.pow(10, -5.79757), 1e-8);
  // Midpoint quantiles: the value at cumulative probability P sits at index
  // n − 1 − (P·n − 0.5) of the descending array.
  close('log10-normal: 84.13th percentile = 10^(mu+sigma)', l[Math.round(10000 - (0.8413447 * 10001 - 0.5))], Math.pow(10, -5.79757 + 0.63849), 2e-4);
  const c = ECHS.parseCustom('1e-4 2e-5\n3,5e-6; abc 0.001');
  check('custom text: numbers out, descending, junk counted', c.values.length === 4 && c.values[0] === 1e-3 && c.values[3] === 3.5e-6 && c.dropped === 1);
}

/* ======================================================================
   11. The failure histogram: rows weighted by what they stand for
   ====================================================================== */
console.log('\n--- failure histogram ---');
{
  // A layout of our own: 60 holes whose fracture flow rises from 1e-4 to
  // 1e-1 m/yr through an aperture of 0.1 mm, so that the canisters fail
  // for more and more of the sulphide table; with two rejected, one
  // skipped by OKFLAG and one without a fracture.
  const synth = (n = 60, scale = 1) => {
    const h = { name: 'synth', format: 'test', n, id: Array.from({ length: n }, (_, i) => 1001 + i), warnings: [], meta: {} };
    for (const c of ECHydro.COLUMNS) h[c] = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      h.u0[i] = scale * Math.pow(10, -4 + 3 * i / (n - 1));
      h.trapp[i] = 1e-4;
      h.tw[i] = 100 + i;
      h.f[i] = 1e5 * (i + 1);
      h.flen[i] = 20;
    }
    h.fpc[n - 1] = 1;            // the strongest flow, rejected
    h.efpc[n - 2] = 5;           // and the next, by EFPC
    h.okflag[n - 3] = 1;         // skipped, not rejected
    h.trapp[n - 4] = 0;          // no fracture
    return h;
  };
  const p = ECModel.defaults();
  const relClose = (a, b, tol) => Math.abs(a - b) <= tol * Math.max(Math.abs(b), 1e-300);
  const hs10k = ECHS.generic({ n: 10000 });
  const r = ECModel.evaluate(synth(), hs10k, p);
  check('the synthetic layout fails canisters', r.failures.length > 100 && r.key.nFailedHighestHs >= 5, `${r.failures.length} rows from ${r.key.nFailedHighestHs} holes`);

  // The bars add up to the key outputs, however they are binned and coloured.
  const want = { corrected: r.key.meanFailedCorrected, uncorrected: r.key.meanFailed, rows: r.key.nFailRows };
  let sums = true; let groupsAddUp = true; let binsAddUp = true;
  for (const count of ['corrected', 'uncorrected', 'rows']) {
    for (const scale of ['log', 'linear']) {
      for (const bins of ['coarse', 'medium', 'fine']) {
        for (const by of ['hs', 'canister', 'none']) {
          const h = ECModel.failureHistogram([r], { count, scale, bins, by });
          if (!relClose(h.total, want[count], 1e-12)) sums = false;
          if (!relClose(h.groups.reduce((s, g) => s + g.total, 0), h.total, 1e-12)) groupsAddUp = false;
          if (!h.groups.every((g) => relClose(g.values.reduce((s, x) => s + x, 0), g.total, 1e-12))) binsAddUp = false;
        }
      }
    }
  }
  check('the bars add up to the corrected mean, the mean and the rows, in every binning and colouring', sums);
  check('the groups add up to the total', groupsAddUp);
  check('and each group’s bins to its total', binsAddUp);

  // Every row lands in the bin that holds its failure time.
  for (const scale of ['log', 'linear']) {
    const h = ECModel.failureHistogram([r], { scale, count: 'rows', by: 'none' });
    const e = h.edges;
    const counts = new Float64Array(e.length - 1);
    for (const f of r.failures) {
      let j = 0;
      while (j < e.length - 2 && f.tFail >= e[j + 1]) j++;
      counts[j]++;
    }
    check(`${scale} bins: every row in the bin of its failure time`, counts.every((c, j) => c === h.groups[0].values[j]),
      Array.from(counts).join(',') + ' vs ' + Array.from(h.groups[0].values).join(','));
    check(`${scale} bins end at the assessment time and start at or below the earliest failure`,
      e[e.length - 1] === r.key.tLim && e[0] <= r.key.earliestFailure);
  }
  const eLog = ECModel.timeEdges(52608, 1e6, 'log', 'medium');
  check('log bins: ten to a decade, whole decades of the assessment time', eLog.length === 21 && relClose(eLog[0], 1e4, 1e-14) && relClose(eLog[10], 1e5, 1e-14) && eLog[20] === 1e6);
  check('log bins: coarse and fine', ECModel.timeEdges(52608, 1e6, 'log', 'coarse').length === 11 && ECModel.timeEdges(52608, 1e6, 'log', 'fine').length === 41);
  const eLin = ECModel.timeEdges(52608, 1e6, 'linear', 'medium');
  check('linear bins: 50 from 0 to the assessment time', eLin.length === 51 && eLin[0] === 0 && eLin[50] === 1e6 && eLin[1] === 20000);
  check('a failure at exactly a tenth of the assessment time opens the first decade', ECModel.timeEdges(1e5, 1e6, 'log', 'medium')[0] === 1e5 * 1);

  // The canisters: one entry per hole, its rows its share of the table.
  const cans = ECModel.failingCanisters([r]);
  check('one canister per hole with rows', cans.length === new Set(r.failures.map((f) => f.hole)).size);
  check('their rows add up to the failure table', cans.reduce((s, c) => s + c.rows, 0) === r.failures.length);
  close('their shares of the corrected mean add up to it', cans.reduce((s, c) => s + c.corrected, 0), r.key.meanFailedCorrected, 1e-12);
  check('share = rows / sulphide values', cans.every((c) => c.share === c.rows / r.key.nHs));
  check('largest first', cans.every((c, i) => i === 0 || c.corrected <= cans[i - 1].corrected));
  check('earliest and latest are the first and last rows of the hole', cans.every((c) => {
    const ts = r.failures.filter((f) => f.hole === c.hole).map((f) => f.tFail);
    return c.earliest === ts[0] && c.latest === ts[ts.length - 1] && c.id === r.id[c.hole];
  }));
  check('no rejected or skipped hole among them', cans.every((c) => !r.columns.skip[c.hole]));

  // Coloured by canister: the eight largest on their own, the rest together.
  const hc = ECModel.failureHistogram([r], { by: 'canister' });
  check('eight canisters on their own and the rest as one', hc.groups.length === Math.min(9, cans.length + (cans.length > 8 ? 1 : 0))
    && hc.groups.slice(0, 8).every((g, i) => g.kind === 'canister' && g.canister.key === cans[i].key));
  if (cans.length > 8) {
    const other = hc.groups[8];
    close('the rest add up to the canisters left over', other.total, cans.slice(8).reduce((s, c) => s + c.corrected, 0), 1e-12);
    check('and say how many they are', other.kind === 'other' && other.canisters === cans.length - 8);
  }
  close('a canister’s bars add up to its share of the corrected mean', hc.groups[0].total, cans[0].corrected, 1e-12);

  // Coloured by sulphide: decade bands, every row in the band of its value.
  const hb = ECModel.failureHistogram([r], { by: 'hs', count: 'rows' });
  const bands = hb.bands;
  check('the bands hold every value of the table', bands.reduce((s, b) => s + b.n, 0) === r.key.nHs);
  check('highest first, no more than five', bands.length <= 5 && bands.every((b, i) => i === 0 || b.lo < bands[i - 1].lo || b.below));
  const rowsInBand = bands.map((b) => r.failures.filter((f) => f.hs >= b.lo && f.hs < b.hi).length);
  check('each band’s bars count the rows of its values', hb.groups.every((g, i) => g.total === rowsInBand[i]), `${hb.groups.map((g) => g.total)} vs ${rowsInBand}`);
  // What each band gives, whatever the colours: rows, part of the corrected
  // mean, canisters failing for one of its values.
  const bs = ECModel.failureHistogram([r], { by: 'canister', count: 'rows' }).bandStats;
  check('band by band, the rows of its values in any colouring', bs.every((b, i) => b.rows === rowsInBand[i]));
  close('their parts of the corrected mean add up to it', bs.reduce((s, b) => s + b.corrected, 0), r.key.meanFailedCorrected, 1e-12);
  check('and each band’s canisters are those with a row in it', bs.every((b, i) => b.canisters
    === new Set(r.failures.filter((f) => f.hs >= bands[i].lo && f.hs < bands[i].hi).map((f) => f.hole)).size));
  check('the highest band fails the most canisters, the lowest the fewest', bs[0].canisters >= bs[1].canisters && bs[1].canisters >= bs[bs.length - 1].canisters);

  // Equal shares of the failures: cuts at j/k of them, each at the nearest
  // boundary between two values; cuts that meet are one.
  const weights = (pairs) => new Map(pairs);
  const even = ECModel.equalShareSplit(weights(Array.from({ length: 100 }, (_, i) => [100 - i, 1])), 5);
  check('equal shares: a hundred values of one row each make five groups of twenty', even.length === 5 && even.every((g) => g.weight === 20 && g.values.length === 20));
  const dom = ECModel.equalShareSplit(weights([[9, 0.5], [8, 0.1], [7, 0.1], [6, 0.1], [5, 0.1], [4, 0.1]]), 5);
  check('a value with half the failures is a group of its own: the cuts at 20 and 40 % meet at it',
    dom.map((g) => `${g.values.join('/')}:${g.weight.toFixed(2)}`).join(' ') === '9:0.50 8:0.10 7/6:0.20 5/4:0.20');
  check('the groups hold every value once, highest first, each from its lowest to its highest',
    dom.flatMap((g) => g.values).join() === '9,8,7,6,5,4' && dom.every((g) => g.hi === g.values[0] && g.lo === g.values[g.values.length - 1]));
  check('one value makes one group', ECModel.equalShareSplit(weights([[1.2e-4, 4]]), 5).length === 1);
  check('three values for five divisions make three groups', ECModel.equalShareSplit(weights([[3, 0.5], [2, 0.3], [1, 0.2]]), 5).length === 3);
  let evenly = true;
  for (const k of [2, 3, 4, 5]) {
    const hq = ECModel.failureHistogram([r], { by: 'hsq', divisions: k });
    if (hq.groups.length !== k || !hq.groups.every((g) => Math.abs(g.total / hq.total - 1 / k) < 0.005)) evenly = false;
  }
  check('the synthetic layout with 10,000 values splits into 2, 3, 4 and 5 shares within half a per cent', evenly);
  const hq = ECModel.failureHistogram([r], { by: 'hsq', divisions: 5, count: 'rows' });
  check('the groups take every row, by the value behind it', hq.groups.every((g) => g.total === r.failures.filter((f) => f.hs >= g.interval.lo && f.hs <= g.interval.hi).length));
  check('their values and those that fail no canister make the whole table', hq.intervals.reduce((s, iv) => s + iv.n, 0) + hq.below.n === r.key.nHs
    && hq.below.hi < hq.intervals[hq.intervals.length - 1].lo);
  check('and they say what they give', hq.intervalStats.reduce((s, t) => s + t.rows, 0) === r.failures.length
    && Math.abs(hq.intervalStats.reduce((s, t) => s + t.corrected, 0) - r.key.meanFailedCorrected) < 1e-12 * r.key.meanFailedCorrected);
  // Percentiles of the table: the j-th highest of n at 100·(n − j)/n.
  const sizes = (n, cuts) => ECModel.percentileSplit(n, cuts).map((g) => Math.max(0, g.to - g.from + 1)).join(',');
  check('percentiles of 10,000 values at 50, 90, 99, 99.9: 10, 90, 900, 4000 and 5000 of them', sizes(10000, [50, 90, 99, 99.9]) === '10,90,900,4000,5000');
  check('of 46 values: the two highest groups empty, the highest value lying at P97.8', sizes(46, [50, 90, 99, 99.9]) === '0,0,4,19,23');
  check('quintiles of 46 values', sizes(46, [80, 60, 40, 20]) === '9,9,9,9,10');
  check('cuts outside (0, 100) and repeated ones are left out', sizes(1000, [99, 0, 100, 99, -5, 150]) === '10,990');
  const hp = ECModel.failureHistogram([r], { by: 'hsp', percentiles: [50, 90, 99, 99.9], count: 'rows' });
  check('by percentile, every row goes to the group of its place in the table', hp.groups.every((g) => g.total
    === r.failures.filter((f) => f.hsIndex >= g.interval.from && f.hsIndex <= g.interval.to).length));
  check('the groups hold 0.1, 0.9, 9, 40 and 50 % of the values', hp.intervals.map((iv) => iv.n / r.key.nHs).join(',') === '0.001,0.009,0.09,0.4,0.5');
  check('each from its lowest value to its highest', hp.intervals.every((iv) => iv.hi === r.hs[iv.from - 1] && iv.lo === r.hs[iv.to - 1]));
  check('their stats add up to the failure table', hp.intervalStats.reduce((s, t) => s + t.rows, 0) === r.failures.length
    && Math.abs(hp.intervalStats.reduce((s, t) => s + t.corrected, 0) - r.key.meanFailedCorrected) < 1e-12 * r.key.meanFailedCorrected);
  check('without percentiles given, the tail ones', ECModel.failureHistogram([r], { by: 'hsp' }).percentiles.join() === '50,90,99,99.9');

  const fewF = ECModel.failureHistogram([ECModel.evaluate(synth(), ECHS.HS_FORSMARK, p)], { by: 'hsq', divisions: 5 });
  const failingF = new Set(ECModel.evaluate(synth(), ECHS.HS_FORSMARK, p).failures.map((f) => f.hs)).size;
  check('HSForsmark: no more groups than failing values, their shares adding up to one',
    fewF.groups.length <= Math.min(5, failingF) && Math.abs(fewF.groups.reduce((s, g) => s + g.total, 0) / fewF.total - 1) < 1e-12, `${fewF.groups.length} groups of ${failingF} values`);
  check('decadeOf puts 1e-5 in its own decade', ECModel.decadeOf(1e-5) === -5 && ECModel.decadeOf(9.999999999999999e-6) === -6 && ECModel.decadeOf(0.000099999) === -5);
  const wide = ECModel.hsBands(ECModel.sortHs([3e-2, 2e-3, 4e-4, 5e-5, 6e-6, 7e-7, 8e-8]));
  check('six decades and more: the lowest merged into one band below', wide.length === 5 && wide[4].below && wide[4].hi === 1e-5 && wide[4].n === 3 && wide[0].lo === 1e-2);
  const forsmark = ECModel.hsBands(ECHS.HS_FORSMARK);
  check('HSForsmark: four decades, one value in the highest', forsmark.length === 4 && forsmark[0].lo === 1e-4 && forsmark[0].n === 1 && forsmark.every((b) => !b.below));

  // The share of the sulphide table at or above each value; at a
  // canister's HSmin it is the canister's share.
  const exF = ECModel.hsExceedance(ECHS.HS_FORSMARK);
  const distinct = new Set(ECHS.HS_FORSMARK).size;
  check('HSForsmark: a step at every distinct value, from 1/46 to all of them', exF.hs.length === distinct && exF.share[0] === 1 / 46 && exF.share[exF.share.length - 1] === 1);
  check('equal values make one step', exF.share[exF.hs.indexOf(1.2474271814382826e-07)] === 1 && exF.share.every((s, i) => i === 0 || s > exF.share[i - 1]));
  const ex = ECModel.hsExceedance(hs10k);
  check('a long table is thinned, keeping its ends', ex.hs.length < 2000 && ex.hs[0] === hs10k[0] && ex.share[0] === 1e-4 && ex.share[ex.share.length - 1] === 1);
  const shareAt = (e, c) => { let s = 0; for (let j = 0; j < e.hs.length; j++) if (e.hs[j] > c) s = e.share[j]; return s; };
  check('the share above a canister’s HSmin is its share', cans.slice(0, 8).every((cn) => Math.abs(shareAt(ECModel.hsExceedance(hs10k, 0), cn.hsMin) - cn.share) < 1e-12));

  // A canister's curve: from its earliest failure to the assessment time.
  const c0 = cans[0];
  const curve = ECModel.failureCurve(c0, r.key.hsMax, c0.hsMin, 30, [1e-4, 1e-5]);
  close('the curve starts at the earliest failure', curve.t[0], c0.earliest, 1e-12);
  close('and meets the assessment time at HSmin', curve.t[curve.t.length - 1], r.key.tLim, 1e-12);
  check('later as the sulphide falls', curve.t.every((t, i) => i === 0 || t > curve.t[i - 1]) && curve.hs.every((x, i) => i === 0 || x < curve.hs[i - 1]));

  // Resolution: twice the values, twice the rows, the same bars.
  const r20k = ECModel.evaluate(synth(), ECHS.generic({ n: 20000 }), p);
  check('twice the sulphide values give about twice the rows', relClose(r20k.failures.length, 2 * r.failures.length, 0.01), `${r20k.failures.length} vs ${r.failures.length}`);
  const h10 = ECModel.failureHistogram([r], {});
  const h20 = ECModel.failureHistogram([r20k], {});
  close('and the same corrected mean', h20.total, h10.total, 2e-3);
  const l1 = h10.groups.reduce((s, g, gi) => s + g.values.reduce((a, x, j) => a + Math.abs(x - h20.groups[gi].values[j]), 0), 0);
  check('bar by bar', h10.edges.length === h20.edges.length && l1 < 0.01 * h10.total, `L1 ${l1} of ${h10.total}`);
  const c20 = ECModel.failingCanisters([r20k]);
  check('each canister keeps its share', cans.every((c) => { const d = c20.find((x) => x.hole === c.hole); return d && Math.abs(d.share - c.share) < 2e-4; }));

  // Several realisations: the mean over them, as the summary's.
  const many = ECModel.evaluateMany([synth(), synth(60, 0.7)], hs10k, p);
  const hm = ECModel.failureHistogram(many.results, {});
  close('over realisations the bars add up to the mean corrected mean', hm.total, many.summary.meanFailedCorrected.mean, 1e-12);
  check('and count every row', ECModel.failureHistogram(many.results, { count: 'rows' }).total === many.summary.nFailRowsTotal);
  const cm = ECModel.failingCanisters(many.results);
  check('the same hole in two realisations is two canisters', new Set(cm.map((c) => c.key)).size === cm.length
    && cm.some((c) => c.real === 1) && cm.some((c) => c.real === 0));

  // Nothing fails: an empty histogram, not an error.
  const none = ECModel.failureHistogram([ECModel.evaluate(synth(), [1e-9], p)], {});
  check('no failures: no bins, no groups, nothing in total', none.nRows === 0 && none.groups.length === 0 && none.total === 0 && none.tMin === null);

  if (haveTestCase) {
    // The code test case: holes 1-3 fail for all ten values, hole 4 for five.
    const rt = ECModel.evaluate(readTestCase(), ECHS.HS_TEST, { ...ECModel.defaults(), buffModel: 'OldKTH', fTDilute: 0.25, nCanisters: 3000 });
    const ct = ECModel.failingCanisters([rt]);
    check('test case: four canisters, 10, 10, 10 and 5 rows', ct.map((c) => c.rows).sort((a, b) => b - a).join(',') === '10,10,10,5');
    check('shares 1, 1, 1 and ½', ct.map((c) => c.share).sort((a, b) => b - a).join(',') === '1,1,1,0.5');
    close('hole 2 fails first, at 85,000 years', ct.find((c) => c.id === 2).earliest, 85000, 2e-4);
    const ht = ECModel.failureHistogram([rt], {});
    close('the bars add up to the corrected mean (1.75 with 3000 canisters)', ht.total, 1.75, 1e-12);
    const ht2 = ECModel.failureHistogram([rt], { by: 'canister', count: 'rows', scale: 'linear' });
    const g2 = ht2.groups.find((g) => g.canister && g.canister.id === 2);
    const filled = Array.from(g2.values).map((v, j) => (v ? j : -1)).filter((j) => j >= 0);
    check('hole 2’s ten rows sit in the bins of 80,000 to 100,000 years', g2.total === 10
      && filled.every((j) => ht2.edges[j] >= 80000 && ht2.edges[j + 1] <= 100000), filled.join(','));
  } else skipped('the failure histogram of the code test case');
}

/* ====================================================================== */
console.log(`\n${checks} checks, ${failures.length} failed`);
if (failures.length) {
  console.log(failures.map((f) => `  - ${f}`).join('\n'));
  process.exit(1);
}
