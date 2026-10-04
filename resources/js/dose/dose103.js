/*
  Committed equivalent and effective dose coefficients in the ICRP 103
  system for members of the public (ICRP Publication 158 section 2.7).

  For each age at intake: assemble the compartment system (model103.js), give
  every compartment the S coefficients of its source region in each of the
  twelve reference individuals (newborn, 1, 5, 10, 15 y and adult, male and
  female; see103.js), integrate (solve.js) to age 70 for children and over 50
  years for adults, with S interpolated in age as ICRP 158 paras 174-176 say,
  and combine the target regions into tissues (Table 2.12):

    Lung (thoracic airways)  1/3 BB (basal and secretory cells equally),
                             1/3 bb, 1/3 AI
    Extrathoracic region     0.001 ET1 + 0.999 ET2
    Colon                    0.4 right + 0.4 left colon + 0.2 rectosigmoid
    Lymphatic nodes          0.08 LN(ET) + 0.08 LN(TH) + 0.84 systemic
    Gonads                   testes (male), ovaries (female)

  The effective dose is sex-averaged (ICRP 103; ICRP 158 eq. 2.13):
  E = sum over T of wT (H_T,male + H_T,female) / 2, the remainder of each sex
  the arithmetic mean of its 13 remainder tissues (prostate for males, uterus
  for females).
*/
import { assemble103, sexSpecific103 } from './model103.js';
import { emissionWeights, sAllRows, sForRegions } from './see103.js';
import { integrate } from './solve.js';

export const AGES_103 = [100, 365, 1825, 3650, 5475, 7300];
export const PHANTOMS_103 = { M: ['00M', '01M', '05M', '10M', '15M', 'AM'], F: ['00F', '01F', '05F', '10F', '15F', 'AF'] };
export const PHANTOM_AGES_103 = [0, 365, 1825, 3650, 5475, 7300];

export const W_103 = {
  'Red marrow': 0.12, Colon: 0.12, Lung: 0.12, Stomach: 0.12, Breast: 0.12, Gonads: 0.08, Bladder: 0.04,
  Oesophagus: 0.04, Liver: 0.04, Thyroid: 0.04, 'Bone surface': 0.01, Brain: 0.01, 'Salivary glands': 0.01, Skin: 0.01,
};
export const W_REMAINDER_103 = 0.12;

/* Tissues as combinations of target regions; a function of sex where it differs. */
export const TISSUES_103 = {
  'Red marrow': [['R-marrow', 1]],
  Colon: [['RC-stem', 0.4], ['LC-stem', 0.4], ['RS-stem', 0.2]],
  Lung: [['Bronch-bas', 1 / 6], ['Bronch-sec', 1 / 6], ['Bchiol-sec', 1 / 3], ['AI', 1 / 3]],
  Stomach: [['St-stem', 1]],
  Breast: [['Breast', 1]],
  Gonads: (sex) => [[sex === 'M' ? 'Testes' : 'Ovaries', 1]],
  Bladder: [['UB-wall', 1]],
  Oesophagus: [['Oesophagus', 1]],
  Liver: [['Liver', 1]],
  Thyroid: [['Thyroid', 1]],
  'Bone surface': [['Endost-BS', 1]],
  Brain: [['Brain', 1]],
  'Salivary glands': [['S-glands', 1]],
  Skin: [['Skin', 1]],
  // Remainder tissues
  Adrenals: [['Adrenals', 1]],
  'Extrathoracic region': [['ET1-bas', 0.001], ['ET2-bas', 0.999]],
  Gallbladder: [['GB-wall', 1]],
  Heart: [['Ht-wall', 1]],
  Kidneys: [['Kidneys', 1]],
  'Lymphatic nodes': [['LN-ET', 0.08], ['LN-Th', 0.08], ['LN-Sys', 0.84]],
  Muscle: [['Muscle', 1]],
  'Oral mucosa': [['O-mucosa', 1]],
  Pancreas: [['Pancreas', 1]],
  'Prostate/uterus': (sex) => [[sex === 'M' ? 'Prostate' : 'Uterus', 1]],
  'Small intestine': [['SI-stem', 1]],
  Spleen: [['Spleen', 1]],
  Thymus: [['Thymus', 1]],
  // Not in the effective dose
  'Eye lens': [['Eye-lens', 1]],
  Ureters: [['Ureters', 1]],
};
export const REMAINDER_103 = ['Adrenals', 'Extrathoracic region', 'Gallbladder', 'Heart', 'Kidneys', 'Lymphatic nodes',
  'Muscle', 'Oral mucosa', 'Pancreas', 'Prostate/uterus', 'Small intestine', 'Spleen', 'Thymus'];

const partsOf = (name, sex) => (typeof TISSUES_103[name] === 'function' ? TISSUES_103[name](sex) : TISSUES_103[name]);

/**
 * @param {object} data  {index, elements, deposition, emissions: (name) => {r, bs},
 *                        saf: {index, phantoms: {id: SafPhantom}}}
 * @param {object} spec  {nuclide, route, form, amad, cutoff}
 * @param {number[]} [ages]
 */
export function coefficients103(data, spec, ages = AGES_103, opt = {}) {
  const saf = data.saf;
  const ids = [...PHANTOMS_103.M, ...PHANTOMS_103.F];
  const nT = saf.index.targets.length;
  const T = Object.fromEntries(saf.index.targets.map((t, i) => [t, i]));
  // S of every pair, per nuclide and phantom: the same for all ages at intake.
  const sCache = data.sCache || (data.sCache = new Map());
  const sRows = (name, id) => {
    const key = `${name}|${id}`;
    if (!sCache.has(key)) {
      const ph = saf.phantoms[id];
      const w = emissionWeights(data.emissions(name), saf.index.energies, name);
      sCache.set(key, sAllRows(ph, w));
    }
    return sCache.get(key);
  };
  return ages.map((age0) => {
    const adultAge = data.elements[spec.nuclide.split('-')[0]]?.adultAge || 7300;
    const intakeAge = age0 === 7300 ? adultAge : age0;
    // One system for both sexes, or one per sex where the model differs (radon).
    const sexes = sexSpecific103(data, spec) ? ['M', 'F'] : [null];
    const Ht = { M: {}, F: {} };
    const runs = [];
    for (const sex of sexes) {
      const sys = assemble103(data, { ...spec, intakeAge, sex: sex || undefined });
      const which = sex ? [sex] : ['M', 'F'];
      // S columns: per compartment, per reference age, the targets of each sex in turn.
      const colCache = new Map();
      const columns = sys.comps.map((c) => {
        const m = sys.members[c.member];
        const otherOf = c.region === 'Other' ? (c.otherOf ?? c.member) : -1;
        const key = `${c.member}|${c.region}|${otherOf}`;
        if (colCache.has(key)) return colCache.get(key);
        const named = new Set(otherOf >= 0 ? sys.members[otherOf].named : []);
        const cols = PHANTOM_AGES_103.map((pa, p) => {
          const col = new Float64Array(which.length * nT);
          which.forEach((x, k) => {
            const id = PHANTOMS_103[x][p];
            const S = sForRegions(saf.phantoms[id], sRows(m.name, id), [c.region], named)[c.region];
            col.set(S, k * nT);
          });
          return col;
        });
        colCache.set(key, cols);
        return cols;
      });
      // Numbers of transformations per member and source region.
      const groupKeys = [], groups = [];
      sys.comps.forEach((c, i) => {
        const k = `${c.member}|${c.region}`;
        let g = groupKeys.indexOf(k);
        if (g < 0) { g = groupKeys.length; groupKeys.push(k); groups.push([]); }
        groups[g].push(i);
      });
      const period = intakeAge < 7300 ? 25550 - intakeAge : 18250;
      // With a time series, the effective dose's share of each dose group as
      // well, a group for each compartment (the Model tab's boxes), each
      // described by its compartment: what it is and where it was formed.
      const functionals = opt.outputs ? [effectiveWeights103(T, nT, which)] : undefined;
      const kindOf = (g) => {
        const c = sys.comps[g.comps[0]];
        let b = c;
        while (b.kind === 'mirror' && sys.comps[b.of]) b = sys.comps[b.of];
        return { ...g, kind: c.kind, base: b.kind, name: c.name, place: c.place || null };
      };
      const res = integrate(sys, { phantomAges: PHANTOM_AGES_103, columns, nTargets: which.length * nT, groups, interp: 'icrp103', functionals, byCompartment: !!opt.outputs },
        { intakeAge, period, outputs: opt.outputs, rtol: opt.rtol });
      which.forEach((x, k) => saf.index.targets.forEach((t, i) => { Ht[x][t] = res.H[k * nT + i]; }));
      runs.push({ sys, res, groupKeys, which, doseGroups: opt.outputs ? res.doseGroups.map(kindOf) : null });
    }
    const H = { M: {}, F: {}, avg: {} };
    for (const name of Object.keys(TISSUES_103)) {
      for (const sex of ['M', 'F']) H[sex][name] = partsOf(name, sex).reduce((a, [t, w]) => a + w * Ht[sex][t], 0);
      H.avg[name] = (H.M[name] + H.F[name]) / 2;
    }
    for (const sex of ['M', 'F']) H[sex].Remainder = REMAINDER_103.reduce((a, r) => a + H[sex][r], 0) / REMAINDER_103.length;
    H.avg.Remainder = (H.M.Remainder + H.F.Remainder) / 2;
    let E = W_REMAINDER_103 * H.avg.Remainder;
    for (const [k, w] of Object.entries(W_103)) E += w * H.avg[k];
    const { sys, res, groupKeys, which } = runs[0];
    const { series, doseGroups, sexesInSeries } = opt.outputs ? seriesOf(runs, nT) : {};
    return {
      age: age0, intakeAge, E, H, Ht, sexSpecific: sexes.length > 1, sexesInSeries,
      transformations: groupKeys.map((k, g) => ({ member: sys.members[Number(k.split('|')[0])].name, region: k.split('|')[1], n: res.U[g] })),
      system: sys, stats: res.stats, series: series || null, doseGroups: doseGroups || null,
    };
  });
}

/*
  The time series of a calculation: that of its one integration; or, where
  the sexes' models differ (radon), the male model's activities and both
  sexes' doses -- each point's target doses as [male, female], and the dose
  groups of both, whose shares then add up to the average of the sexes, as
  the coefficient is.
*/
function seriesOf(runs, nT) {
  const [a, b] = runs;
  if (!b) return { series: a.res.series, doseGroups: a.doseGroups, sexesInSeries: a.which };
  const nA = a.sys.comps.length, nB = b.sys.comps.length;
  const other = b.res.series;
  // The female point at a time of the male series (the same output times;
  // between two of its points, should a corner of a rate table differ).
  const at = (t) => {
    let i = other.findIndex((p) => p.t >= t);
    if (i < 0) i = other.length - 1;
    if (other[i].t === t || i === 0) return { h: other[i].y.subarray(nB, nB + nT), parts: other[i].parts, rates: other[i].rates };
    const p = other[i - 1], q = other[i], w = (t - p.t) / (q.t - p.t);
    const mix = (u, v) => Float64Array.from(u, (x, k) => x + w * (v[k] - x));
    return { h: mix(p.y.subarray(nB, nB + nT), q.y.subarray(nB, nB + nT)), parts: mix(p.parts, q.parts), rates: mix(p.rates, q.rates) };
  };
  const series = a.res.series.map((p) => {
    const f = at(p.t);
    const y = new Float64Array(nA + 2 * nT);
    y.set(p.y.subarray(0, nA));
    y.set(p.y.subarray(nA, nA + nT), nA);
    y.set(f.h, nA + nT);
    const join = (u, v) => { const out = new Float64Array(u.length + v.length); out.set(u); out.set(v, u.length); return out; };
    return { t: p.t, y, parts: join(p.parts, f.parts), rates: join(p.rates, f.rates) };
  });
  return { series, doseGroups: [...a.doseGroups, ...b.doseGroups], sexesInSeries: ['M', 'F'] };
}

/**
 * The effective dose as weights of the target doses of one integration
 * (the targets of each sex in `which`, in turn): E = Σ w_T (H_T^M + H_T^F)/2
 * + w_rem (H_rem^M + H_rem^F)/2, each tissue's dose a weighted sum of target
 * doses and the remainder's the mean of its tissues'. A sex-specific model
 * (radon) is an integration per sex, each with its half of E.
 */
export function effectiveWeights103(T, nT, which) {
  const f = new Float64Array(which.length * nT);
  const share = 1 / 2;
  which.forEach((sex, k) => {
    for (const [name, w] of Object.entries(W_103)) for (const [t, wp] of partsOf(name, sex)) f[k * nT + T[t]] += share * w * wp;
    for (const r of REMAINDER_103) for (const [t, wp] of partsOf(r, sex)) f[k * nT + T[t]] += share * W_REMAINDER_103 * wp / REMAINDER_103.length;
  });
  return f;
}
