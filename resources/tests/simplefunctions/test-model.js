#!/usr/bin/env node
/* ==========================================================================
   THE SIMPLE FUNCTIONS, AGAINST WHAT THEY ARE SUPPOSED TO REPRODUCE

   Public references only, so this runs from a clean checkout:

   1. TR-10-61 (Grivé et al. 2010), table 3-2: the example water of table
      3-1 through Version A -- every solubility and controlling solid, the
      ranking of the constants that carry the uncertainty, and the quoted
      ±, which is the linearised 2σ divided by ln 10 (see the Help tab).
   2. TR-10-61, table B-1 (Forsmark) and B-3 (Grimsel): Version A for two
      waters of table A-1, with Ca + Mg and, for Forsmark, the free HCO3-
      of table 3-1 (1.77e-3 m, not the 2.2e-3 of table A-1).
   3. Closed forms and properties: the reactions balance and give the
      activity terms written by hand in the SR-Site workbooks except where
      sf-data.js says they differ; the normal quantile; the Latin hypercube;
      seeds and streams; the sulphate mass balance; the statistics; the
      file readers and the MAT writer.

   With the SR-Site files on the machine, `python3 make-local-fixtures.py
   <folder>` writes local/ (git-ignored) and this also checks the SR-Site
   workbooks' cached values and the PSAR solubility data.

       node resources/tests/simplefunctions/test-model.js [--verbose]

   Exit status is 0 when every check passes.
   ========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
const M = require(path.join(jsDir, 'sf-model.js'));
const D = require(path.join(jsDir, 'sf-data.js'));
const IO = require(path.join(jsDir, 'sf-io.js'));

const verbose = process.argv.includes('--verbose');
let checks = 0;
const failures = [];

function check(label, ok, detail) {
  checks++;
  const good = ok === true;
  if (!good || verbose) console.log(`${good ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!good) failures.push(label);
}
function near(label, got, want, tol) {
  const ok = Number.isFinite(got) && Math.abs(got - want) <= tol;
  check(label, ok, `${got} vs ${want} (±${tol})`);
}

const solidLog = (plan, res, el, id) => {
  const e = plan.elements.findIndex((E) => E.el === el);
  const k = plan.elements[e].solids.findIndex((s) => s.id === id);
  return Math.log10(res.elements[e].solids[k]);
};

/* ------------------------------------------------------------------------
   1. The dataset compiles, and the reactions balance
   ------------------------------------------------------------------------ */
{
  const plan = M.compile(D.SRSITE);
  check('the SR-Site dataset compiles without an issue', plan.issues.length === 0, JSON.stringify(plan.issues));
  check('20 elements', plan.elements.length === 20);
  const sampled = plan.params.filter((p, i) => plan.sigma[i] > 0).length;
  check('224 constants are sampled (magnetite and goethite are not)', sampled === 224, String(sampled));
  let unbalanced = [];
  for (const s of D.SRSITE.major) if (M.balanceIssues(M.parseReaction(s.rx)).length) unbalanced.push(s.id);
  for (const E of D.SRSITE.elements) for (const s of [...E.species, ...E.solids]) if (M.balanceIssues(M.parseReaction(s.rx)).length) unbalanced.push(`${E.el} ${s.id}`);
  check('every reaction balances in charge and elements', unbalanced.length === 0, unbalanced.join(', '));
  // The workbooks' hand-written terms differ from the reactions in exactly
  // these entries, and nowhere else.
  const overrides = [];
  for (const E of plan.elements) for (const s of [...E.species, ...E.solids]) if (s.override) overrides.push(`${E.el}:${s.id}`);
  check('the workbook terms override exactly four entries', JSON.stringify(overrides.sort()) === JSON.stringify(['Ni:NiCO3·5.5H2O(s)', 'Pa:PaO2OH(aq)', 'Sm:SmOHCO3(s)', 'U:(UO2)2CO3(OH)3-'].sort()), overrides.join(', '));
  const plan2 = M.compile(D.SRSITE, { reactionTerms: true });
  const left = [];
  for (const E of plan2.elements) for (const s of [...E.species, ...E.solids]) if (s.override || s.q.some((v, z) => v !== s.qDerived[z])) left.push(s.id);
  check('“every term from the reactions” drops them all', left.length === 0, left.join(', '));
  // A few terms written out by hand.
  const sp = (el, id) => plan.elements.find((E) => E.el === el).species.find((s) => s.id === id);
  const so = (el, id) => plan.elements.find((E) => E.el === el).solids.find((s) => s.id === id);
  check('CaOH+-type hydrolysis: q0 − 2 q1 + q2', JSON.stringify(sp('Sr', 'SrOH+').q) === JSON.stringify([1, -2, 1, 0, 0, 0, 0]));
  check('U(CO3)4-4: −1.5 q0 + 2 q1 + 5 q2 − q4', JSON.stringify(sp('U', 'U(CO3)4-4').q) === JSON.stringify([-1.5, 2, 5, 0, -1, 0, 0]));
  check('Fe1.04Se(s): 1.98 q0 + 0.08 q1 − 2.04 q2', JSON.stringify(so('Se', 'Fe1.04Se(s)').q) === JSON.stringify([1.98, 0.08, -2.04, 0, 0, 0, 0]));
  check('coffinite depends on [H+]^2 pO2^0.5 / [H4SiO4]', M.ligandText(so('U', 'Coffinite').lig) === '[H+]^2·pO2(g)^0.5 / [H4SiO4]', M.ligandText(so('U', 'Coffinite').lig));
  check('becquerelite releases six UO2+2', so('U', 'Becquerelite').m === 6);
  check('(UO2)3(OH)5+ is a trimer', sp('U', '(UO2)3(OH)5+').n === 3);
  check('AgOH(aq) divides by [H+]', M.ligandText(sp('Ag', 'AgOH(aq)').lig) === '1 / [H+]');
  check('Zr(OH)4(am,fresh) is out of the minimum', so('Zr', 'Zr(OH)4(am,fresh)').use === false);
  check('Pu(CO3)3-3 carries the corrected ΔlogK 1.4', plan.params[sp('Pu', 'Pu(CO3)3-3').index].dlogK === 1.4);
  check('Ra(OH)+ is sampled with √3 times the spread', Math.abs(plan.sigma[sp('Ra', 'RaOH+').index] - 0.125 * Math.sqrt(3)) < 1e-15);
  const plan3 = M.compile(D.SRSITE, { singleRaOH: true });
  check('…and once with the option', Math.abs(plan3.sigma[plan3.elements.find((E) => E.el === 'Ra').species[0].index] - 0.125) < 1e-15);
  // The parser.
  check('charges: UO2(CO3)3-4 −4, Fe(OH)4- −1, (UO2)3(OH)5+ +1, SrCO3(aq) 0', M.chargeOf('UO2(CO3)3-4') === -4 && M.chargeOf('Fe(OH)4-') === -1 && M.chargeOf('(UO2)3(OH)5+') === 1 && M.chargeOf('SrCO3(aq)') === 0);
  check('element counts of a hydrate', JSON.stringify(M.elementCounts('NaNpO2CO3·3.5H2O(s)')) === JSON.stringify({ Na: 1, Np: 1, O: 8.5, C: 1, H: 7 }), JSON.stringify(M.elementCounts('NaNpO2CO3·3.5H2O(s)')));
  check('an unbalanced reaction is reported', M.balanceIssues(M.parseReaction('Sm+3 + H2O = SmOH+2')).length === 2);
  let threw = '';
  try { M.compileSpecies({ id: 'x', rx: 'Sm+3 + Mg+2 = SmMg+5' }, 'Sm+3'); } catch (e) { threw = e.message; }
  check('a non-basis species on the left is refused with a reason', /neither Sm\+3 nor a basis species/.test(threw), threw);
}

/* ------------------------------------------------------------------------
   2. TR-10-61 table 3-2: Version A for the example water
   ------------------------------------------------------------------------ */
{
  const plan = M.compile(D.SRSITE, { version: 'A' });
  const A = M.analyse(plan, D.TR1061_EXAMPLE);
  // element: [log S, ±, controlling solid, top contributor]
  const T = {
    Sr: [-3.16, 0.13, 'Celestite', 'Celestite'], Ra: [-6.76, 0.05, 'RaSO4(s)', 'RaSO4(s)'],
    Sn: [-7.28, 0.43, 'SnO2(am)', 'SnO2(am)'], Se: [-9.48, 0.64, 'FeSe2(s)', 'FeSe2(s)'],
    Ag: [-5.08, 0.16, 'AgCl(cr)', 'AgCl4-3'], U: [-8.13, 0.54, 'UO2·2H2O(am)', 'UO2·2H2O(am)'],
    Zr: [-7.75, 0.74, 'Zr(OH)4(am,aged)', 'Zr(OH)4(aq)'], Nb: [-4.78, 0.02, 'Nb2O5(s)', null],
    Pa: [-6.47, 0.44, 'Pa2O5(s)', 'Pa2O5(s)'], Np: [-8.86, 0.41, 'NpO2·2H2O(am)', 'Np(OH)4(aq)'],
    Pu: [-3.54, 0.65, 'Pu(OH)4(s)', 'Pu(OH)4(s)'], Am: [-4.51, 0.48, 'Am2(CO3)3(s)', 'Am2(CO3)3(s)'],
    Cm: [-4.51, 0.48, 'Cm2(CO3)3(s)', 'Cm2(CO3)3(s)'], Tc: [-8.13, 0.23, 'TcO2·1.63H2O(s)', 'TcO2·1.63H2O(s)'],
    Pd: [-5.00, 0.57, 'Pd(OH)2(s)', 'Pd(OH)2(s)'], Sm: [-5.15, 0.14, 'SmOHCO3(s)', 'SmOHCO3(s)'],
    Ho: [-4.76, 0.23, 'Ho2(CO3)3(s)', 'Ho2(CO3)3(s)'], Th: [-8.04, 0.43, 'ThO2·2H2O(am,aged)', 'ThO2·2H2O(am,aged)'],
    Pb: [-5.16, 0.31, 'Cerussite', 'Cerussite'],
  };
  for (const r of A.elements) {
    const E = plan.elements.find((x) => x.el === r.el);
    const t = T[r.el];
    if (!t) { check('Ni is “not solubility limited” in table 3-2 (above 0.01 m)', r.S > 0.01, String(r.S)); continue; }
    near(`table 3-2 ${r.el}: log S`, Number(r.logS.toFixed(2)), t[0], 0.005);
    check(`table 3-2 ${r.el}: ${t[2]} controls`, E.solids[r.control].id === t[2], E.solids[r.control].id);
    // The report's ±: its workbooks' ΔK = K·ΔlogK and 0.434·ΔS/S come to
    // our 2σ over ln 10. Nb, Pa and Pd have their own derivative slips.
    if (!['Nb', 'Pa', 'Pd'].includes(r.el)) near(`table 3-2 ${r.el}: ± in the report's convention`, Number((2 * r.sigma / Math.LN10).toFixed(2)), t[1], 0.015);
    if (t[3]) check(`table 3-2 ${r.el}: ${t[3]} carries most of the uncertainty`, r.terms[0].id === t[3], r.terms[0].id);
  }
}

/* ------------------------------------------------------------------------
   3. TR-10-61 tables B-1 and B-3: Forsmark and Grimsel, Version A
   ------------------------------------------------------------------------ */
{
  const plan = M.compile(D.SRSITE, { version: 'A' });
  const wf = D.TR1061_WATERS.find((w) => w.id === 'Forsmark');
  const forsmark = { ...wf, Ca: wf.Ca + wf.Mg, HCO3: 1.77e-3 };
  const rf = M.evaluateWater(plan, forsmark, plan.nominal, false);
  const B1 = [['Ag', 'AgCl(cr)', -5.08], ['Am', 'NaAm(CO3)2·5H2O(s)', -5.76], ['Cm', 'Cm2(CO3)3(s)', -5.53], ['Ho', 'Ho2(CO3)3(s)', -5.69],
    ['Nb', 'Nb2O5(s)', -4.46], ['Ni', 'Ni(OH)2(s)', -3.09], ['Np', 'NpO2·2H2O(am)', -8.96], ['Pa', 'Pa2O5(s)', -6.48], ['Pb', 'Cerussite', -6.03],
    ['Pd', 'Pd(OH)2(s)', -5.41], ['Pu', 'Pu(OH)4(s)', -7.86], ['Ra', 'RaSO4(s)', -6.63], ['Se', 'FeSe2(s)', -10.73], ['Se', 'Se(s)', -9.83],
    ['Sm', 'SmOHCO3(s)', -6.86], ['Sn', 'SnO2(am)', -7.18], ['Sr', 'Celestite', -3.01], ['Tc', 'TcO2·1.63H2O(s)', -8.39],
    ['Th', 'ThO2·2H2O(am,aged)', -8.06], ['U', 'UO2·2H2O(am)', -6.17], ['Zr', 'Zr(OH)4(am,aged)', -7.75]];
  for (const [el, id, want] of B1) near(`table B-1 Forsmark ${el} ${id}`, solidLog(plan, rf, el, id), want, 0.03);
  const wg = D.TR1061_WATERS.find((w) => w.id.startsWith('Grimsel'));
  const rg = M.evaluateWater(plan, { ...wg, Ca: wg.Ca + wg.Mg }, plan.nominal, false);
  const B3 = [['Ag', 'AgCl(cr)', -5.81], ['Am', 'Am(OH)3(am)', -7.03], ['Ho', 'Ho(OH)3(am)', -5.57], ['Nb', 'Nb2O5(s)', -2.53], ['Ni', 'Ni(OH)2(s)', -6.87],
    ['Np', 'NpO2·2H2O(am)', -8.99], ['Pb', 'Hydrocerussite', -6.58], ['Pu', 'Pu(OH)4(s)', -9.30], ['Ra', 'RaSO4(s)', -5.87], ['Se', 'FeSe2(s)', -10.04],
    ['Se', 'Se(s)', -10.42], ['Sm', 'SmOHCO3(s)', -8.50], ['Sn', 'SnO2(am)', -5.58], ['Sr', 'Strontianite', -5.10], ['Tc', 'TcO2·1.63H2O(s)', -8.34],
    ['Th', 'ThO2·2H2O(am,aged)', -8.57], ['U', 'Becquerelite', -7.01], ['Zr', 'Zr(OH)4(am,aged)', -7.74]];
  for (const [el, id, want] of B3) near(`table B-3 Grimsel ${el} ${id}`, solidLog(plan, rg, el, id), want, 0.006);
}

/* ------------------------------------------------------------------------
   4. The water: the sulphate balance holds, Version B is what it says
   ------------------------------------------------------------------------ */
{
  const plan = M.compile(D.SRSITE);
  const w = { pH: 7.3, I: 0.19, HCO3: 1.25e-3, SO4: 5.7e-3, Cl: 0.152, Ca: 0.018, Na: 0.109, Si: 1.3e-4 };
  const gw = M.groundwater(plan, w, plan.nominal);
  const L = gw.lig;
  const q = gw.q;
  const K = (id) => Math.pow(10, plan.nominal[plan.major[id].index] + plan.major[id].q.reduce((a, c, z) => a + c * q[z], 0));
  const H = Math.pow(10, -w.pH);
  const S = L[M.LIG.SO4] * (1 + K('HSO4-') * H + K('CaSO4(aq)') * L[M.LIG.Ca] + K('NaSO4-') * L[M.LIG.Na] + (K('FeSO4(aq)') + K('FeHSO4+') * H) * L[M.LIG.Fe]);
  near('Version B: the sulphate mass balance closes', S / w.SO4, 1, 1e-13);
  const Ca = L[M.LIG.Ca] * (1 + K('CaOH+') / H + K('CaCO3(aq)') * L[M.LIG.CO3] + K('CaHCO3+') * L[M.LIG.CO3] * H + K('CaSO4(aq)') * L[M.LIG.SO4]);
  near('Version B: and so does calcium', Ca / w.Ca, 1, 1e-13);
  near('Version B: Eh = 0.059/4 (0.06 − 4 pH) V', gw.Eh, 0.059 / 4 * ((-4 * (-5.49 + 3 * 8.75)) + 83.1 - 4 * w.pH) * 1000, 1e-9);
  const planA = M.compile(D.SRSITE, { version: 'A' });
  const wa = { ...w, Eh: -250, Fe: 3e-5 };
  const ga = M.groundwater(planA, wa, planA.nominal);
  const o = Math.pow(10, ga.logPO2 * 0.25);
  const Ka = (id) => Math.pow(10, planA.nominal[planA.major[id].index] + planA.major[id].q.reduce((a, c, z) => a + c * ga.q[z], 0));
  const La = ga.lig;
  const fe = La[M.LIG.Fe] * (1 + Ka('FeOH+') / H + Ka('Fe(OH)3(aq)') * o / (H * H) + Ka('Fe(OH)4-') * o / (H * H * H) + Ka('FeCO3(aq)') * La[M.LIG.CO3] + Ka('FeHCO3+') * La[M.LIG.CO3] * H
    + (Ka('FeSO4(aq)') + Ka('FeHSO4+') * H) * La[M.LIG.SO4] + Ka('FeCl+') * La[M.LIG.Cl]);
  near('Version A: the iron mass balance closes', fe / wa.Fe, 1, 1e-12);
  near('Version A: pO2 from the Eh', ga.logPO2, -83.1 + 4 * w.pH + 4 * (-250 / 59.16), 1e-12);
  let threw = '';
  try { M.groundwater(planA, w, planA.nominal); } catch (e) { threw = e.message; }
  check('Version A without Eh is refused', /needs Eh/.test(threw), threw);
}

/* ------------------------------------------------------------------------
   5. Sampling
   ------------------------------------------------------------------------ */
{
  const P = [[0.5, 0], [0.975, 1.959963984540054], [0.025, -1.959963984540054], [0.999, 3.090232306167813], [1e-10, -6.361340902404056], [0.84134474606854293, 1.0000000000000000]];
  for (const [p, z] of P) near(`normInv(${p})`, M.normInv(p), z, 2e-14);
  const rng = M.makeRng(M.streamSeed(7, 'x'));
  const u = M.uniforms(rng, 1000, true);
  const strata = new Set(Array.from(u, (x) => Math.floor(x * 1000)));
  check('the Latin hypercube puts one draw in each of the 1000 strata', strata.size === 1000);
  const plan = M.compile(D.SRSITE);
  const waters = D.TR1061_WATERS.filter((w) => w.I <= 0.2).map((w) => ({ ...w, Ca: w.Ca + w.Mg }));
  const a = M.run(plan, waters, { n: 2000, seed: 5 });
  const b = M.run(plan, waters, { n: 2000, seed: 5 });
  check('the same seed gives the same realisations', a.S.every((col, e) => col.every((x, i) => x === b.S[e][i])));
  const c = M.run(plan, waters, { n: 2000, seed: 6 });
  check('another seed gives others', a.S[12].some((x, i) => x !== c.S[12][i]));
  // Editing one constant leaves the draws of every other constant alone.
  const data2 = D.clone(D.SRSITE);
  data2.elements.find((E) => E.el === 'U').species[0].logK = -5.0;
  const plan2 = M.compile(data2);
  const s1 = M.sampleParams(plan, { n: 500, seed: 5, lhs: true, varyTD: true });
  const s2 = M.sampleParams(plan2, { n: 500, seed: 5, lhs: true, varyTD: true });
  const moved = s1.map((col, p) => (col && s2[p] && col.some((x, i) => x !== s2[p][i]) ? plan.params[p].key : null)).filter(Boolean);
  check('editing one constant moves only its own draws', JSON.stringify(moved) === JSON.stringify(['U:UO2OH+']), moved.join(', '));
  const col = s1[plan.elements.find((E) => E.el === 'U').solids.find((s) => s.id === 'Coffinite').index];
  const d = M.describe(Array.from(col, (x) => Math.pow(10, x)));
  near('a sampled constant has mean logK', d.mean, 31.02, 0.03);
  near('…and standard deviation ΔlogK/2', d.sd, 6.57 / 2, 0.03);
  // Cm's constants are Am's by analogy; with the option they take Am's draws.
  const planAn = M.compile(D.SRSITE, { analogueDraws: true });
  const sA = M.sampleParams(planAn, { n: 200, seed: 9, lhs: true, varyTD: true });
  const pAm = planAn.params.findIndex((p) => p.key === 'Am:Am2(CO3)3(s)');
  const pCm = planAn.params.findIndex((p) => p.key === 'Cm:Cm2(CO3)3(s)');
  check('with analogue draws Cm2(CO3)3(s) is drawn as Am2(CO3)3(s)', sA[pAm].every((x, i) => x === sA[pCm][i]));
  const sB = M.sampleParams(plan, { n: 200, seed: 9, lhs: true, varyTD: true });
  check('…and without them independently', sB[pAm].some((x, i) => x !== sB[pCm][i]));
  const nr = M.drawWaters(10, { n: 10, seed: 1, draw: 'randnorep', lhs: true });
  check('without replacement every water once', new Set(nr).size === 10);
  let threw = '';
  try { M.drawWaters(10, { n: 11, seed: 1, draw: 'randnorep' }); } catch (e) { threw = e.message; }
  check('…and not more realisations than waters', /at least as many waters/.test(threw), threw);
  const fixed = M.run(plan, waters, { n: 300, seed: 2, draw: 'fixed', fixedWater: 1 });
  check('one water only draws that water throughout', fixed.waterIndex.every((i) => i === 1));
  const noTD = M.run(plan, waters, { n: 50, seed: 2, varyTD: false, draw: 'inorder' });
  const det = M.evaluateWater(plan, waters[3], plan.nominal, false);
  check('with the constants fixed a realisation is the deterministic answer', plan.elements.every((E, e) => noTD.S[e][3] === det.elements[e].S));
}

/* ------------------------------------------------------------------------
   6. Statistics
   ------------------------------------------------------------------------ */
{
  const x = Array.from({ length: 101 }, (_, i) => Math.pow(10, i / 10));
  const d = M.describe(x);
  near('the median of 0..10 in log', d.p50, 5, 1e-12);
  near('P5 interpolates as NumPy does', d.p5, 0.5, 1e-12);
  const k = M.ks2([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]);
  check('KS distance of a sample to itself is 0', k.D === 0);
  const k2 = M.ks2([1, 2, 3], [4, 5, 6]);
  check('and of disjoint samples 1', k2.D === 1);
  const r = M.spearman([[1, 2, 3, 4, 5], [5, 4, 3, 2, 1]], [1, 4, 9, 16, 25]);
  check('Spearman ρ of a monotone relation is ±1', Math.abs(r[0] - 1) < 1e-15 && Math.abs(r[1] + 1) < 1e-15);
  const rng = M.makeRng(M.streamSeed(1, 'fit'));
  const z = Array.from({ length: 4000 }, () => Math.pow(10, -6 + 0.7 * M.normInv(rng.uniform())));
  const f = M.fitDistribution(z);
  near('a normal sample fits μ', f.normal.mu, -6, 0.04);
  near('…and σ', f.normal.sigma, 0.7, 0.03);
  check('…and keeps the normal (skew-normal no better by AIC)', f.best === 'normal', `${f.best} ${f.normal.aic} ${f.skew.aic}`);
  const sk = Array.from({ length: 4000 }, () => Math.pow(10, Math.abs(M.normInv(rng.uniform()))));
  const g = M.fitDistribution(sk);
  check('a half-normal sample is fitted as skew-normal, α bounded', g.best === 'skew-normal' && g.skew.alpha > 3 && g.skew.alpha < 50, `${g.best} α=${g.skew.alpha}`);
}

/* ------------------------------------------------------------------------
   7. Files
   ------------------------------------------------------------------------ */
(async () => {
  const csv = 'X(km),Y(km),Z(km),pH,[Ca]tot (m),[Cl]tot (m),[Na]tot (m),[SO4-2]tot (m)**,[Si]tot (m),IS (mol/kg),[HCO3-] (m)*\n'
    + '1631.69,6700.83,-0.49,7.268,0.03274,0.1454,0.07807,0.003212,0.0001285,0.1917,0.0006949\n'
    + '1631.68,6699.84,-0.46,7.019,0.02953,0.1211,0.06259,,0.0001291,0.1618,0.001284\n';
  const g = await IO.readGroundwater({ name: 'gw.csv', text: csv }, { SFModel: M });
  check('the PSAR groundwater header is recognised', g.waters.length === 1 && g.waters[0].SO4 === 0.003212 && g.waters[0].HCO3 === 0.0006949 && g.waters[0].I === 0.1917, JSON.stringify(g.waters[0]));
  check('a row with a missing value is left out and counted', g.skipped.length === 1 && g.skipped[0].missing[0] === 'SO4');
  const semi = 'pH;Ca;Cl;Na;SO4;Si;I;HCO3;Eh (mV);Fe\n7,2;0,023;0,153;0,089;0,0052;1e-4;0,19;0,0022;-140;3,3e-5\n';
  const s = await IO.readGroundwater({ name: 'gw.txt', text: semi }, { SFModel: M });
  check('semicolons and decimal commas', s.waters.length === 1 && s.waters[0].pH === 7.2 && s.waters[0].Eh === -140 && s.waters[0].Fe === 3.3e-5, JSON.stringify(s.waters[0]));
  let threw = '';
  try { await IO.readGroundwater({ name: 'x.csv', text: 'pH,Ca,Cl\n7,1,1\n' }, { SFModel: M }); } catch (e) { threw = e.message; }
  check('a table without the needed columns is refused by name', /no column for Na, SO4, Si, I, HCO3/.test(threw), threw);
  const cols = [Float64Array.from([1e-9, 2e-9, 3e-9]), Float64Array.from([1e-5, 2e-5, 3e-5])];
  const bytes = IO.writeMatStructArray('CSOL', ['U', 'Np'], cols, 3);
  const back = IO.solubilitiesFromMat(await IO.readMat(bytes));
  check('a written CSOL MAT file reads back', Array.from(back.U).join() === '1e-9,2e-9,3e-9' && Array.from(back.Np).join() === '0.00001,0.00002,0.00003');
  const ref = IO.solubilitiesFromRows(IO.parseDelimited('Sr,U,foo\n1e-3,1e-9,5\n2e-3,2e-9,6\n'));
  check('reference columns by element name', Object.keys(ref).join() === 'Sr,U' && ref.U[1] === 2e-9);

  /* ----------------------------------------------------------------------
     8. With the SR-Site files on this machine (see make-local-fixtures.py)
     ---------------------------------------------------------------------- */
  const local = path.join(__dirname, 'local');
  if (fs.existsSync(path.join(local, 'workbook-cases.json'))) {
    const cases = JSON.parse(fs.readFileSync(path.join(local, 'workbook-cases.json'), 'utf8'));
    const plan = M.compile(D.SRSITE);
    for (const c of cases) {
      const r = M.evaluateWater(plan, c.water, plan.nominal, false);
      let worst = 0;
      for (const [el, S] of Object.entries(c.S)) {
        const e = plan.elements.findIndex((E) => E.el === el);
        worst = Math.max(worst, Math.abs(r.elements[e].S / S - 1));
      }
      check(`SR-Site workbook ${c.name}: every element to 1e-12`, worst < 1e-12, worst.toExponential(2));
      for (const [k, v] of Object.entries(c.ligands)) {
        const got = k === 'Eh' ? r.gw.Eh : r.gw.lig[M.LIG[k]];
        check(`SR-Site workbook ${c.name}: ${k}`, Math.abs(got / v - 1) < 1e-12, `${got} vs ${v}`);
      }
    }
  }
  if (fs.existsSync(path.join(local, 'psar.json'))) {
    const psar = JSON.parse(fs.readFileSync(path.join(local, 'psar.json'), 'utf8'));
    const plan = M.compile(D.SRSITE);
    const res = M.run(plan, psar.waters, { n: psar.waters.length, seed: 1 });
    for (const [e, E] of plan.elements.entries()) {
      const ks = M.ks2(Array.from(res.S[e], Math.log10), psar.CSOL[E.el].map(Math.log10));
      check(`PSAR ${E.el}: indistinguishable from the PSAR data (KS p > 0.01)`, ks.p > 0.01, `D ${ks.D.toFixed(4)} p ${ks.p.toFixed(3)}`);
    }
  }

  console.log(`${checks} checks, ${failures.length} failed${failures.length ? `: ${failures.join('; ')}` : ''}`);
  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
