/*
  Committed equivalent and effective dose coefficients in the ICRP 60 system,
  for members of the public (ICRP Publications 56, 67, 69, 71 and 72, as
  compiled in Publication 119).

  For each age at intake: assemble the compartment system (model60.js), give
  every compartment the SEE column of its source region for each reference
  phantom (see60.js), integrate (solve.js, with DCAL's weights between the
  phantoms) to age 70 for children and over 50 years for adults, and combine
  the target doses:

    Lung    0.167 BB basal + 0.167 BB secretory + 0.333 bb + 0.333 AI +
            0.001 LN(TH)   (ICRP 66's thirds, the half of BB's to three
            figures as the ICRP's database of dose coefficients has it: its
            lung dose follows from the five parts it stores to 1e-5 for every
            inhaled intake; DCAL's LUNGAS.DAT has 0.333 of BB's mean)
    ET      0.001 ET1 + 0.998 ET2 + 0.001 LN(ET)
    Colon   0.568 ULI wall + 0.432 LLI wall          (ICRP 67's 0.57 and 0.43:
            the walls' 210 and 160 g, to the three figures of the ICRP's
            database of dose coefficients)
    Oesophagus  the thymus dose                      (SEECAL's surrogate)
    Gonads  the higher of testes and ovaries

  and the effective dose with the tissue weighting factors of ICRP 60 and the
  remainder of ICRP 66/68/72 as the ICRP's database of dose coefficients has
  it (NRPB's PLEIADES; README): adrenals, brain, extrathoracic airways, small
  intestine, kidneys, muscle, pancreas, spleen and uterus -- not the thymus,
  whose dose stands for the oesophagus's -- their committed doses averaged by
  the masses at the age of the intake, with the splitting rule: a remainder
  tissue whose committed dose exceeds that of every tissue with a weighting
  factor of its own takes half the remainder weight, the mass-weighted mean of
  the others the other half. The database compares the two doses as printed,
  to two figures (its help says so of Publication 72: so that the reader of
  two figures "would decide on the same formulation as the computer code").
  Its remainder follows from its own tissue doses by this
  bookkeeping to 1e-4 for every one of 15,054 intakes (five nuclides that it
  stores to two figures apart), its split for all of them, its effective dose
  to 1e-6 for 99.9 % (resources/tests/dose_coefficients/README.md).
*/
import { assemble60, BONE_IN_OTHER_60 } from './model60.js';
import { phantom60, TARGETS_60 } from './see60.js';
import { integrate } from './solve.js';
import { Z as ATOMIC } from './catalog.js';
import { printed38 } from './decay38.js';

export const AGES_60 = [100, 365, 1825, 3650, 5475, 7300];
export const AGE_LABELS = { 100: '3 months', 365: '1 year', 1825: '5 years', 3650: '10 years', 5475: '15 years', 7300: 'Adult', 9125: 'Adult' };
const PHANTOMS = ['A00', 'A01', 'A05', 'A10', 'A15', 'AM'];
export const PHANTOM_AGES_60 = [0, 365, 1825, 3650, 5475, 7300];

export const W_60 = {
  Gonads: 0.20, 'Red marrow': 0.12, Colon: 0.12, Lung: 0.12, Stomach: 0.12, Bladder: 0.05, Breast: 0.05,
  Liver: 0.05, Oesophagus: 0.05, Thyroid: 0.05, Skin: 0.01, 'Bone surface': 0.01,
};
/* The steps of an age-dependent calculation, as PLEIADES took them for
   Publications 67 to 72 (solve.js, dose.hold): [age below which a step
   starting there has this length, the length], days. Read off the ICRP's
   database of dose coefficients (README): with steps of these lengths, and
   the SEE and the rates as at each step's start, the doses of 36Cl, 87Rb,
   35S and 33P to 7 and 30 days and 1 year follow the adult's in time to
   1e-5 at 5 and 10 years (50 d), 2e-5 at 15 years (180 d), 2e-4 at 1 year
   (40 d) and 1e-3 at 3 months (9 d). */
export const HOLD_60 = [[365, 9], [1825, 40], [5475, 50], [Infinity, 180]];

/* Remainder tissues and their masses in grams at the reference ages (newborn,
   1, 5, 10 and 15 years, adult), as the ICRP's database of dose coefficients
   weights them (read off its remainder and tissue doses; README): the
   phantoms' organ masses, ICRP 23's for the adult, but the muscle 40 % of a
   body of 3.4, 9.8, 19, 32, 52.5 and 70 kg (the phantoms' own: 0.76, 2.5, 5,
   11, 22 and 28 kg) and the ET airways 1.2 to 15 g. The 3-month-old's are
   100/365 of the way from the newborn's to the 1-year-old's. (A mean shows
   the ratios of its weights only: the newborn's muscle and airways are the
   ones that make the 3-month-old's ratios so.) No thymus: its dose is the
   oesophagus's, which has a weighting factor of its own. */
export const REMAINDER_60 = {
  Adrenals: [5.83, 3.52, 5.27, 7.22, 10.5, 14], Brain: [352, 884, 1260, 1360, 1410, 1400],
  ET: [1.2, 2.1, 4.1, 6.8, 11, 15], 'Small intestine': [32.6, 84.9, 169, 286, 516, 640],
  Kidneys: [22.9, 62.9, 116, 173, 248, 310], Muscle: [1360, 3920, 7600, 12800, 21000, 28000],
  Pancreas: [2.8, 10.3, 23.6, 30, 64.9, 100], Spleen: [9.11, 25.5, 48.3, 77.4, 123, 180],
  Uterus: [3.85, 1.45, 2.7, 4.16, 80, 80],
};

/* Each reported tissue as a combination of targets. */
const T = Object.fromEntries(TARGETS_60.map((t, i) => [t, i]));
export const TISSUES_60 = {
  Adrenals: [['Adrenals', 1]], Bladder: [['UB_Wall', 1]], 'Bone surface': [['Bone_Sur', 1]], Brain: [['Brain', 1]],
  Breast: [['Breasts', 1]], Oesophagus: [['Thymus', 1]], Stomach: [['St_Wall', 1]], 'Small intestine': [['SI_Wall', 1]],
  'Upper large intestine': [['ULI_Wall', 1]], 'Lower large intestine': [['LLI_Wall', 1]],
  Colon: [['ULI_Wall', 0.568], ['LLI_Wall', 0.432]], Kidneys: [['Kidneys', 1]], Liver: [['Liver', 1]],
  Muscle: [['Muscle', 1]], Ovaries: [['Ovaries', 1]], Pancreas: [['Pancreas', 1]], 'Red marrow': [['R_Marrow', 1]],
  ET: [['ET1-bas', 0.001], ['ET2-bas', 0.998], ['LN-ET', 0.001]],
  Lung: [['BBi-bas', 0.167], ['BBi-sec', 0.167], ['bbe-sec', 0.333], ['AI', 0.333], ['LN-Th', 0.001]],
  Skin: [['Skin', 1]], Spleen: [['Spleen', 1]], Testes: [['Testes', 1]], Thymus: [['Thymus', 1]],
  Thyroid: [['Thyroid', 1]], Uterus: [['Uterus', 1]],
};
const REM_KEYS = Object.keys(REMAINDER_60);

/** The remainder's masses at an age, in the order of REMAINDER_60: linear between the reference ages. */
function remainderMasses(age) {
  const ages = PHANTOM_AGES_60;
  let k = 0;
  while (k < ages.length - 2 && age > ages[k + 1]) k++;
  const w = Math.min(1, Math.max(0, (age - ages[k]) / (ages[k + 1] - ages[k])));
  return REM_KEYS.map((r) => REMAINDER_60[r][k] + w * (REMAINDER_60[r][k + 1] - REMAINDER_60[r][k]));
}

/* A dose as the database compares it for the splitting rule: to two figures. */
const twoFigures = (x) => Number(x.toPrecision(2));

/**
 * The remainder of an intake at an age from its tissues' doses: their mean by
 * the masses of that age, or, split, half of it the dose of the one tissue
 * and half the mean of the others.
 * @param {object} H  dose by tissue (TISSUES_60's names, with Gonads)
 * @param {number} intakeAge  days
 * @param {string|null} [split]  the tissue that takes half, or null for none; left out, the
 *   splitting rule decides it on these doses (the committed ones are the ones to give it)
 * @returns {{remainder: number, split: string|null, weights: object, shares: object}} weights: each
 *   tissue's weight in the remainder; shares: its part of the remainder's dose (they add up to it)
 */
export function remainder60(H, intakeAge, split) {
  const mass = remainderMasses(intakeAge);
  if (split === undefined) {
    const top = REM_KEYS.reduce((a, r) => (H[r] > H[a] ? r : a));
    const named = Math.max(...Object.keys(W_60).map((k) => H[k]));
    split = twoFigures(H[top]) > twoFigures(named) ? top : null;
  }
  const M = mass.reduce((a, m, k) => (REM_KEYS[k] === split ? a : a + m), 0);
  const weights = Object.fromEntries(REM_KEYS.map((r, k) => [r, r === split ? 0.5 : (split ? 0.5 : 1) * mass[k] / M]));
  const shares = Object.fromEntries(REM_KEYS.map((r) => [r, weights[r] * H[r]]));
  return { remainder: REM_KEYS.reduce((a, r) => a + shares[r], 0), split, weights, shares };
}

/*
  The effective dose as weights of the target rows of an integration:
  E = base + 0.20 H_gonads + 0.05 remainder, where the gonads are the testes
  or the ovaries and the remainder follows the splitting rule, both decided
  on the committed doses. So the pieces: [0] base, the weighted tissues but
  the gonads; [1] testes; [2] ovaries; [3] the remainder by mass; then for
  each remainder tissue its dose and the remainder without it.
*/
function effectivePieces60(nT, intakeAge) {
  const tissue = (name, w = 1, into = new Float64Array(nT)) => { for (const [t, wp] of TISSUES_60[name]) into[T[t]] += w * wp; return into; };
  const base = new Float64Array(nT);
  for (const [k, w] of Object.entries(W_60)) if (k !== 'Gonads') tissue(k, w, base);
  const mass = remainderMasses(intakeAge);
  const mean = (without) => {
    const M = mass.reduce((a, m, k) => (k === without ? a : a + m), 0), v = new Float64Array(nT);
    REM_KEYS.forEach((r, k) => { if (k !== without) tissue(r, mass[k] / M, v); });
    return v;
  };
  return [base, tissue('Testes'), tissue('Ovaries'), mean(-1), ...REM_KEYS.flatMap((r, k) => [tissue(r), mean(k)])];
}

const BONE_V = ['C_Bone-V', 'T_Bone-V'];
const isBone = (r) => /^[CT]_Bone-[SV]$/.test(r);

/*
  "Other" in a chain with independent kinetics, as DCAL's ACTACAL has it
  (ORNL/TM-2001/190, 9.3.1). The chain's source regions are those any member's
  own model carries it into (step 1; model60.js explicitRegions) and the
  chain's Other is the rest of the body tissues. A member's activity in the
  Other of its own model -- which takes in every chain region that model does
  not carry it into -- is then shared out, for the dose only, by mass:

    - a region the parent's model names, to which this member's model does
      not carry it: the region's share of the mass of this member's Other
      (step 5b);
    - a region the parent's model does not name: the members before the first
      whose model names it, by their own Other's mass as above; from that
      member on, every member, whether its own model names the region or not,
      by the region's share of the mass of the parent's Other, where the
      member was formed (step 5a).

  What is left stays in the chain's Other. Step 5a brings the testes of 232U
  from 0.85 to 1.0 of ICRP 72's doses and the red marrow of 210Pb from 0.95;
  taking it to members whose own model names the region (the manual's "each
  member C following B") does the same for the kidneys of 223Ra and the
  spleen of 228Th and 232Th, 0.75-0.94 of ICRP 72's otherwise. Bone surfaces
  have no mass; a member whose model names no bone region has the mineral
  bone in its Other, which goes to the bone volumes when any member names
  bone.
*/
function otherTargets(j, members, common, boneInOther) {
  const own = new Set(members[j].explicit), parent = new Set(members[0].explicit);
  const out = [];
  for (const r of common) {
    if (isBone(r)) continue;
    if (parent.has(r)) { if (!own.has(r)) out.push([r, 'own']); continue; }
    const first = members.findIndex((m) => m.explicit.includes(r));
    out.push([r, j >= first ? 'parent' : 'own']);
  }
  if (!boneInOther && ![...own].some(isBone) && [...common].some(isBone)) for (const r of BONE_V) out.push([r, 'own']);
  return out;
}

/* The mass of the Other of a model naming these regions; boneInOther: the
   mineral bone stays in it (model60.js BONE_IN_OTHER_60). */
function robMass(explicit, mS, boneInOther) {
  let rob = mS.Body_Tis - (mS.Ht_Cont || 0);
  for (const r of explicit) if (mS[r] && !isBone(r)) rob -= mS[r];
  if (!boneInOther && explicit.some(isBone)) rob -= mS['C_Bone-V'] + mS['T_Bone-V'];
  return rob;
}

function otherShares(j, members, targets, mS, boneInOther) {
  const rob = { own: robMass(members[j].explicit, mS, boneInOther), parent: robMass(members[0].explicit, mS, boneInOther) };
  const shares = targets.filter(([r]) => mS[r] > 0).map(([r, of]) => [r, mS[r] / rob[of]]);
  if (!shares.length) return [['Other', 1]];
  return [['Other', 1 - shares.reduce((a, [, f]) => a + f, 0)], ...shares];
}

/**
 * Dose coefficients for one intake at the given ages.
 * @param {object} data  {index, models, saf, emissions: (nuclide) => {r, bs}}
 * @param {object} spec  {nuclide, route, type, lung, amad, bio, f1file, kinetics, last, adultAge}
 * @param {number[]} [ages]
 * @param {{outputs?: boolean, rtol?: number, dcal?: boolean}} [opt]  dcal: as DCAL computes, for
 *   comparing with it -- the SEE of its SEECAL (see60.js: its photon interpolation, joules per
 *   MeV and mass of the body's tissues) and rates and SEE that follow the age continuously, not in
 *   PLEIADES's steps (HOLD_60)
 */
export function coefficients60(data, spec, ages = AGES_60, opt = {}) {
  const phantoms = PHANTOMS.map((p) => phantom60(data.saf, p));
  return ages.map((age0) => {
    const intakeAge = age0 === 7300 && spec.adultAge ? spec.adultAge : age0;
    const sys = assemble60(data, { ...spec, intakeAge });
    // Source regions of each member, and its SEE matrices per phantom.
    /* "Other". With shared kinetics every member has the parent's model and
       Other is the body tissues the parent's model does not name; with
       independent kinetics, see otherTargets. */
    const common = new Set(sys.members.flatMap((m) => (sys.spec.kinetics === 'S' ? sys.members[0].explicit : m.explicit)));
    // Tellurium's Other takes in the mineral bone, and so does its chain's.
    const boneInOther = !opt.dcal && BONE_IN_OTHER_60.has(sys.members[0].bio);
    const targets = sys.members.map((m, j) => otherTargets(j, sys.members, common, boneInOther));
    const regionsOf = sys.members.map((m, j) => {
      const own = [...new Set(sys.comps.filter((c) => c.member === j).map((c) => c.region))];
      const extra = own.includes('Other') ? targets[j].map(([r]) => r) : [];
      return [...new Set([...own, ...extra])];
    });
    const seeOf = sys.members.map((m, j) => {
      const A = Number(/-(\d+)/.exec(m.name)[1]);
      // Publication 38's radiations as its tables printed them (decay38.js),
      // which is what Publication 72's coefficients were calculated from;
      // with dcal the whole file, as DCAL has it. Other decay data are taken
      // as they are.
      const em = !opt.dcal && data.decaySource?.own ? printed38(data.emissions(m.name), A) : data.emissions(m.name);
      // The atomic number, for spontaneous fission (see60.js); dcal for the
      // SEE as DCAL's SEECAL has them (its photon SAFs and joules per MeV).
      const Z = ATOMIC[/^([A-Z][a-z]?)-/.exec(m.name)[1]];
      return phantoms.map((ph) => ph.see(em, A, regionsOf[j], common, TARGETS_60, { Z, dcal: opt.dcal, boneInOther }));
    });
    // Per member and phantom: how its Other activity divides among the regions.
    const otherSplit = sys.members.map((m, j) => phantoms.map((ph) => otherShares(j, sys.members, targets[j], { ...ph.masses.sources, Body_Tis: ph.bodyTissues(!!opt.dcal) }, boneInOther)));
    const nT = TARGETS_60.length;
    // One column per member and source region, shared by its compartments
    // (solve.js integrates them as one group): the SEE of the region at a
    // phantom, for Other with the shares of a phantom (the same one, or with
    // `pShare`, the other end of the interval: solve.js's cross columns).
    const column = (c, p, pShare = p) => {
      const col = new Float64Array(nT);
      const m = seeOf[c.member][p];
      if (c.region === 'Other') {
        for (const [region, share] of otherSplit[c.member][pShare]) {
          const k = regionsOf[c.member].indexOf(region);
          for (let t = 0; t < nT; t++) col[t] += share * m[t][k];
        }
      } else {
        const s = regionsOf[c.member].indexOf(c.region);
        for (let t = 0; t < nT; t++) col[t] = m[t][s];
      }
      return col;
    };
    const colCache = new Map(), crossCache = new Map();
    const columns = sys.comps.map((c) => {
      const key = `${c.member}|${c.region}`;
      if (!colCache.has(key)) colCache.set(key, PHANTOM_AGES_60.map((pa, p) => column(c, p)));
      return colCache.get(key);
    });
    /* DCAL shares a member's Other activity out by fractions interpolated
       linearly in age (ACTACAL) and multiplies by SEE interpolated with its
       weights (EPACAL): with shares, the Other groups take solve.js's cross
       columns. Without, every group keeps two basis functions. */
    const shared = otherSplit.some((ph) => ph.some((split) => split.length > 1));
    const cross = shared ? sys.comps.map((c) => {
      if (c.region !== 'Other') return null;
      const key = `${c.member}|${c.region}`;
      if (!crossCache.has(key)) crossCache.set(key, PHANTOM_AGES_60.slice(1).map((pa, p) => [column(c, p + 1, p), column(c, p, p + 1)]));
      return crossCache.get(key);
    }) : null;
    const groupKeys = [];
    const groups = [];
    sys.comps.forEach((c, i) => {
      const k = `${c.member}|${c.region}`;
      let g = groupKeys.indexOf(k);
      if (g < 0) { g = groupKeys.length; groupKeys.push(k); groups.push([]); }
      groups[g].push(i);
    });
    const period = intakeAge < 7300 ? 25550 - intakeAge : 18250;
    // With a time series, the shares of each dose group in the pieces the
    // effective dose is made of (effectivePieces60), put together below; a
    // group for each compartment (the Model tab's boxes).
    const pieces = opt.outputs ? effectivePieces60(nT, intakeAge) : null;
    const res = integrate(sys, { phantomAges: PHANTOM_AGES_60, columns, nTargets: nT, groups, interp: 'linear', weights: 'dcal', hold: opt.dcal ? undefined : HOLD_60, cross: cross || undefined, functionals: pieces || undefined, byCompartment: !!opt.outputs },
      { intakeAge, period, outputs: opt.outputs, rtol: opt.rtol });
    const Ht = Object.fromEntries(TARGETS_60.map((t, i) => [t, res.H[i]]));
    const H = {};
    for (const [name, parts] of Object.entries(TISSUES_60)) H[name] = parts.reduce((acc, [t, w]) => acc + w * Ht[t], 0);
    H.Gonads = Math.max(H.Testes, H.Ovaries);
    // The remainder and the splitting rule, decided on the committed doses;
    // each remainder tissue's part of it: by its mass, or, split, half the
    // remainder to the one and the rest by mass among the others.
    const { remainder, split, shares: remainderShares } = remainder60(H, intakeAge);
    H.Remainder = remainder;
    let E = 0.05 * remainder;
    for (const [k, w] of Object.entries(W_60)) E += w * H[k];
    // The gonads' dose is the higher of the testes' and the ovaries' (as committed).
    const gonads = H.Testes >= H.Ovaries ? 'Testes' : 'Ovaries';
    if (pieces) {
      const K = pieces.length, splitAt = split ? REM_KEYS.indexOf(split) : -1;
      const combine = (parts) => {
        const out = new Float64Array(parts.length / K);
        for (let g = 0; g < out.length; g++) {
          const at = (i) => parts[g * K + i];
          const rem = splitAt >= 0 ? 0.5 * at(4 + 2 * splitAt) + 0.5 * at(5 + 2 * splitAt) : at(3);
          out[g] = at(0) + W_60.Gonads * at(gonads === 'Testes' ? 1 : 2) + 0.05 * rem;
        }
        return out;
      };
      for (const p of res.series) { p.parts = combine(p.parts); p.rates = combine(p.rates); }
    }
    return {
      age: age0, intakeAge, E, H, Ht, split, gonads, remainderShares,
      doseGroups: opt.outputs ? res.doseGroups.map((g) => ({ ...g, name: sys.comps[g.comps[0]].name })) : null,
      transformations: groupKeys.map((k, g) => ({ member: sys.members[Number(k.split('|')[0])].name, region: k.split('|')[1], n: res.U[g] })),
      system: sys, stats: res.stats, series: opt.outputs ? res.series : null,
    };
  });
}
