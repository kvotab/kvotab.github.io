/*
  Committed equivalent and effective dose coefficients in the ICRP 103
  system for members of the public (ICRP Publication 158 section 2.7).

  For each age at intake: assemble the compartment system (model103.js), give
  every compartment the S coefficients of its source region in each of the
  twelve reference individuals (newborn, 1, 5, 10, 15 y and adult, male and
  female; see103.js), integrate (solve.js) to age 70 for children and over 50
  years for adults, with S interpolated in age as ICRP 158 paras 174-176 say
  and, like the transfer rates, held over steps of 1/40 year as in the
  calculation behind the published coefficients (OPTIONS103.ageStep), and
  combine the target regions into tissues (Table 2.12):

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
import { assemble103, sexSpecific103, OPTIONS103 } from './model103.js';
import { emissionWeights, sAllRows, sRowsByType, sForRegions, otherPhantom, sOtherByType, S_TYPES } from './see103.js';
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

/*
  The source regions a chain's models name between them: those of the
  members the published calculations carry (model103.js `carried`, chain.js
  carriedMembers). A progeny model marked boneVolume in progeny.json
  (thallium, bismuth and polonium in lead's chains) names bone volume whether
  or not this chain puts anything there, and a model with the marrow of
  trabecular and cortical bone names red and yellow marrow with it (both in
  model103.js). Read off the InMoP annex (2026-11): 210mBi, whose one progeny
  206Tl names skin, spleen, red marrow and gonads, was in the adult female 16 %
  low in skin, 4.5 % high in spleen, 21 % high in ovaries and 2.4 % high in
  every tissue of the rest, and in the 10-year-old male 41 % low in testes;
  with the male's shares all of them are 1.000 at the six ages in both
  sexes. So are the chains whose progeny name muscle (82Sr's adult female
  muscle was 13 % low and her breast 20 % high; 113Ag's 21 % and 23 %).
*/
function chainRegions(sys) {
  const out = new Set();
  for (const m of sys.members) {
    if (m.carried === false) continue;
    for (const r of m.named) out.add(r);
  }
  return out;
}

/*
  The rest of the body of a member (the regions that may form Other and that
  its model does not name, `named`) in parts: each region another member of
  the chain names (`chainNamed`), with the share of the rest of the body's
  mass it has in the reference male at each phantom's age -- an organ only
  the female has by her mass over his rest of the body --, and what is left,
  spread over the remaining regions by the masses of the sex whose dose it
  is. For the male the parts add up to the whole at the phantoms' ages; the
  female's skin, say, holds the male's share. The regions in `apart` (those
  only the members before it name, namedBefore) are no part of it; marrow
  takes its share as the regions the chain names it by (marrowShare). Null
  where nothing of it is named by another member. colsFor(region, named)
  gives the S columns.
*/
/*
  The regions that the members a member descends from name and its own model
  does not (OPTIONS103.ancestorTissues): its rest of the body leaves them
  out. What is formed there stays where the progeny rules put it; what the
  member's own model spreads from blood does not go there. Publication 151
  describes progeny models so (Annex B: the characteristic model expanded by
  the compartments the linked models need), and the ICRP's coefficients show
  it: arsenic formed from 70Se and 72Se has no pancreas, spleen or gonads in
  its model, selenium has, and with arsenic's "Other" spread there too those
  tissues were 1.04-1.07 of the annex of Publication 158's (testes up to
  1.06), left out 0.995-0.998; 129La, whose barium and caesium lack
  lanthanum's liver, kidneys, marrow and gonads, had salivary glands at 0.84,
  thymus 0.88, breast 0.89 and testes 1.09 of the OIR Data Viewer's, and
  every tissue at 1.000-1.005 with them left out. Tissues that a later member
  names still take their share (chainRegions).
*/
function namedBefore(sys) {
  const anc = sys.members.map(() => new Set());
  for (let pass = 0; pass < sys.members.length; pass++) {
    for (const b of sys.chain.branches) { anc[b.to].add(b.from); for (const a of anc[b.from]) anc[b.to].add(a); }
  }
  return sys.members.map((m, j) => {
    const own = new Set(m.named), out = new Set();
    for (const i of anc[j]) { const a = sys.members[i]; if (a.carried !== false) for (const r of a.named) if (!own.has(r)) out.add(r); }
    return out;
  });
}

function otherParts(saf, named, chainNamed, colsFor, sharesOf = 'M', apart = null, marrowShare = 'red-yellow') {
  // The individual whose masses give the shares: the reference male, or, where the model is the female's own (radon), her.
  const male = PHANTOMS_103[sharesOf].map((id) => saf.phantoms[id]), female = PHANTOMS_103[sharesOf === 'M' ? 'F' : 'M'].map((id) => saf.phantoms[id]);
  const src = male[0].sources;
  const mine = (ph, s) => ph.other[s] && !named.has(src[s]) && !(apart && apart.has(src[s]));
  let X = [];
  src.forEach((r, s) => { if (chainNamed.has(r) && (mine(male[0], s) || mine(female[0], s))) X.push(s); });
  // Marrow that the chain names as the marrow of trabecular and cortical bone
  // takes its share as those two regions, not as red and yellow marrow: the
  // same mass divided otherwise, with other S (OPTIONS103.marrowShare).
  const RY = ['R-marrow', 'Y-marrow'];
  const marrowTC = marrowShare === 'named' && (chainNamed.has('T-marrow') || chainNamed.has('C-marrow')) && X.some((s) => RY.includes(src[s]));
  if (marrowTC) X = [...X.filter((s) => !RY.includes(src[s])), src.indexOf('T-marrow'), src.indexOf('C-marrow')];
  // Left out: what the members before it name (either sex's organs).
  const cut = apart ? src.filter((r, s) => apart.has(r) && (male[0].other[s] || female[0].other[s]) && !named.has(r)) : [];
  if (!X.length && !cut.length) return null;
  const total = male.map((ph) => src.reduce((a, r, s) => a + (mine(ph, s) && ph.masses.sources[s] > 0 ? ph.masses.sources[s] : 0), 0));
  const parts = X.map((s) => ({
    region: src[s],
    mass: male.map((ph, p) => (ph.masses.sources[s] > 0 ? ph.masses.sources[s] : female[p].masses.sources[s] || 0)),
    cols: colsFor(src[s], named),
  }));
  const rest = new Set([...named, ...cut, ...X.map((s) => src[s]), ...(marrowTC ? RY : [])]);
  parts.push({ region: 'Other', mass: total.map((M, p) => M - parts.reduce((a, x) => a + x.mass[p], 0)), cols: colsFor('Other', rest) });
  for (const x of parts) x.total = total;
  return parts;
}

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
  // {all: the sum over the radiation types, types: each type's own (null where the nuclide emits none of it)}
  const sCache = data.sCache || (data.sCache = new Map());
  const betaSpectrum = spec.rules?.betaSpectrum ?? OPTIONS103.betaSpectrum;
  const wCache = data.wCache || (data.wCache = new Map());
  const weightsOf = (name) => {
    const key = betaSpectrum === OPTIONS103.betaSpectrum ? name : `${name}|${betaSpectrum}`;
    if (!wCache.has(key)) wCache.set(key, emissionWeights(data.emissions(name), saf.index.energies, name, betaSpectrum));
    return wCache.get(key);
  };
  const sOf = (name, id) => {
    const key = betaSpectrum === OPTIONS103.betaSpectrum ? `${name}|${id}` : `${name}|${id}|${betaSpectrum}`;
    if (!sCache.has(key)) {
      const ph = saf.phantoms[id];
      const w = weightsOf(name);
      const types = sRowsByType(ph, w);
      sCache.set(key, { all: sAllRows(ph, w, types), types });
    }
    return sCache.get(key);
  };
  // S from the rest of the body, the SAFs of its regions combined before they are interpolated in energy
  // (OPTIONS103.otherSAF): per nuclide, phantom and the set of regions that form it.
  const otherSAF = spec.rules?.otherSAF ?? OPTIONS103.otherSAF;
  const oCache = data.oCache || (data.oCache = new Map());
  const sOther = (name, id, named) => {
    const ph = saf.phantoms[id];
    const mini = otherPhantom(ph, named);
    const key = `${name}|${id}|${betaSpectrum}|${mini.key}`;
    if (!oCache.has(key)) {
      const types = sOtherByType(ph, weightsOf(name), mini);
      const all = new Float64Array(nT);
      for (const part of types) if (part) for (let t = 0; t < nT; t++) all[t] += part[t];
      oCache.set(key, { all, types });
    }
    return oCache.get(key);
  };
  const step = spec.rules?.ageStep ?? OPTIONS103.ageStep;
  // The step of an intake: one day where the published calculation of the element taken in has it at that age
  // (OPTIONS103.shortSteps), else the step of all. A step asked for by rule is taken as it is.
  const short = spec.rules?.ageStep == null ? (spec.rules?.shortSteps ?? OPTIONS103.shortSteps) : null;
  const shortBefore = (short && short.before[spec.nuclide.split('-')[0]]) || 0;
  const stepAt = (age0) => (step > 0 && age0 < shortBefore ? short.step : step);
  const ageSpline = spec.rules?.ageSpline ?? OPTIONS103.ageSpline;
  const marrowShare = spec.rules?.marrowShare ?? OPTIONS103.marrowShare;
  // Shares of the rest of the body need the steps: a share and an S each at
  // a step's start. A set of progeny.json may say that its parents' chains
  // do without ("*shares": false).
  const head = data.progeny?.sets?.[data.progeny?.parents?.[spec.nuclide.split('-')[0]]];
  const otherShares = step > 0 && (spec.rules?.otherShares ?? (head?.['*shares'] !== false && OPTIONS103.otherShares));
  // Where an element has a model for each sex (radon), whose masses give the
  // female's shares: the male's as everywhere, or her own for the nuclides the
  // set lists ("*sexShares": 222Rn, as the annex of Publication 158 has it).
  const sexShares = spec.rules?.sexShares ?? head?.['*sexShares']?.[spec.nuclide] ?? OPTIONS103.sexShares;
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
      const colCache = new Map(), splitCache = new Map();
      // (pick: the sum over the radiation types, or one type's own S)
      const colsOf = (pick) => (name, region, named) => PHANTOM_AGES_103.map((pa, p) => {
        const col = new Float64Array(which.length * nT);
        which.forEach((x, k) => {
          const id = PHANTOMS_103[x][p];
          if (region === 'Other' && otherSAF === 'combined') {
            const v = pick(sOther(name, id, named));
            if (v) col.set(v, k * nT);
            return;
          }
          const rows = pick(sOf(name, id));
          if (rows) col.set(sForRegions(saf.phantoms[id], rows, [region], named)[region], k * nT);
        });
        return col;
      });
      const colsAll = colsOf((e) => e.all);
      // S at the phantoms' ages, and with it each radiation type's own S
      // where S is interpolated in age type by type (ageSpline; solve.js
      // takes the slopes of the age spline from `byType`).
      const colsFor = (name, region, named) => {
        const cols = colsAll(name, region, named);
        if (ageSpline === 'types') {
          const present = S_TYPES.map((_, ty) => ty).filter((ty) => which.some((x) => PHANTOMS_103[x].some((id) => sOf(name, id).types[ty])));
          if (present.length > 1) cols.byType = present.map((ty) => colsOf((e) => e.types[ty])(name, region, named));
        }
        return cols;
      };
      const keyOf = (c) => `${c.member}|${c.region}|${c.region === 'Other' ? (c.otherOf ?? c.member) : -1}`;
      const columns = sys.comps.map((c) => {
        const key = keyOf(c);
        if (colCache.has(key)) return colCache.get(key);
        const named = new Set(c.region === 'Other' ? sys.members[c.otherOf ?? c.member].named : []);
        const cols = colsFor(sys.members[c.member].name, c.region, named);
        colCache.set(key, cols);
        return cols;
      });
      // The rest of the body in a chain (otherShares): the tissues another
      // member's model names take their share of it by the reference male's
      // masses, each with its own S; what is left is spread as before.
      const chainNamed = otherShares ? chainRegions(sys) : null;
      const before = otherShares && (spec.rules?.ancestorTissues ?? OPTIONS103.ancestorTissues) === 'apart' ? namedBefore(sys) : null;
      const split = otherShares ? sys.comps.map((c) => {
        if (c.region !== 'Other') return null;
        const key = keyOf(c);
        if (splitCache.has(key)) return splitCache.get(key);
        const named = new Set(sys.members[c.otherOf ?? c.member].named);
        const parts = otherParts(saf, named, chainNamed, (region, set) => colsFor(sys.members[c.member].name, region, set),
          sex === 'F' && sexShares === 'own' ? 'F' : 'M', before ? before[c.otherOf ?? c.member] : null, marrowShare);
        splitCache.set(key, parts);
        return parts;
      }) : undefined;
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
      const res = integrate(sys, { phantomAges: PHANTOM_AGES_103, columns, split, nTargets: which.length * nT, groups, interp: 'icrp103', step: stepAt(age0), functionals, byCompartment: !!opt.outputs },
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
