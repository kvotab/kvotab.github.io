/*
  Committed equivalent and effective dose coefficients in the ICRP 60 system,
  for members of the public (ICRP Publications 56, 67, 69, 71 and 72, as
  compiled in Publication 119).

  For each age at intake: assemble the compartment system (model60.js), give
  every compartment the SEE column of its source region for each reference
  phantom (see60.js), integrate (solve.js, with DCAL's weights between the
  phantoms) to age 70 for children and over 50 years for adults, and combine
  the target doses:

    Lung    0.333 BB + 0.333 bb + 0.333 AI + 0.001 LN(TH), BB the mean of the
            basal and secretory cell doses           (ICRP 66; DCAL LUNGAS.DAT)
    ET      0.001 ET1 + 0.998 ET2 + 0.001 LN(ET)
    Colon   0.57 ULI wall + 0.43 LLI wall            (ICRP 67)
    Oesophagus  the thymus dose                      (SEECAL's surrogate)
    Gonads  the higher of testes and ovaries

  and the effective dose with the tissue weighting factors of ICRP 60 and the
  remainder of ICRP 66/68/72: adrenals, brain, extrathoracic airways, small
  intestine, kidneys, muscle, pancreas, spleen, thymus and uterus, averaged by
  mass, with the splitting rule -- a remainder tissue whose committed dose
  exceeds that of every tissue with a weighting factor of its own takes half
  the remainder weight, the mass-weighted mean of the others the other half.
  The ICRP 72 values were checked against this bookkeeping from their own
  organ doses (resources/tests/dose_coefficients/README.md).
*/
import { assemble60 } from './model60.js';
import { phantom60, TARGETS_60 } from './see60.js';
import { integrate } from './solve.js';

export const AGES_60 = [100, 365, 1825, 3650, 5475, 7300];
export const AGE_LABELS = { 100: '3 months', 365: '1 year', 1825: '5 years', 3650: '10 years', 5475: '15 years', 7300: 'Adult', 9125: 'Adult' };
const PHANTOMS = ['A00', 'A01', 'A05', 'A10', 'A15', 'AM'];
export const PHANTOM_AGES_60 = [0, 365, 1825, 3650, 5475, 7300];

export const W_60 = {
  Gonads: 0.20, 'Red marrow': 0.12, Colon: 0.12, Lung: 0.12, Stomach: 0.12, Bladder: 0.05, Breast: 0.05,
  Liver: 0.05, Oesophagus: 0.05, Thyroid: 0.05, Skin: 0.01, 'Bone surface': 0.01,
};
/* Remainder tissues and their masses in grams at the reference ages (ICRP 72's
   organ masses: the phantoms', ICRP 23's for the adult, and the ET airways). */
export const REMAINDER_60 = {
  Adrenals: [5.83, 3.52, 5.27, 7.22, 10.5, 14], Brain: [352, 884, 1260, 1360, 1410, 1400],
  ET: [1.3, 2.15, 4.3, 7.08, 12.1, 15.5], 'Small intestine': [32.6, 84.9, 169, 286, 516, 640],
  Kidneys: [22.9, 62.9, 116, 173, 248, 310], Muscle: [760, 2500, 5000, 11000, 22000, 28000],
  Pancreas: [2.8, 10.3, 23.6, 30, 64.9, 100], Spleen: [9.11, 25.5, 48.3, 77.4, 123, 180],
  Thymus: [11.3, 22.9, 29.6, 31.4, 28.4, 20], Uterus: [3.85, 1.45, 2.7, 4.16, 80, 80],
};

/* Each reported tissue as a combination of targets. */
const T = Object.fromEntries(TARGETS_60.map((t, i) => [t, i]));
export const TISSUES_60 = {
  Adrenals: [['Adrenals', 1]], Bladder: [['UB_Wall', 1]], 'Bone surface': [['Bone_Sur', 1]], Brain: [['Brain', 1]],
  Breast: [['Breasts', 1]], Oesophagus: [['Thymus', 1]], Stomach: [['St_Wall', 1]], 'Small intestine': [['SI_Wall', 1]],
  'Upper large intestine': [['ULI_Wall', 1]], 'Lower large intestine': [['LLI_Wall', 1]],
  Colon: [['ULI_Wall', 0.57], ['LLI_Wall', 0.43]], Kidneys: [['Kidneys', 1]], Liver: [['Liver', 1]],
  Muscle: [['Muscle', 1]], Ovaries: [['Ovaries', 1]], Pancreas: [['Pancreas', 1]], 'Red marrow': [['R_Marrow', 1]],
  ET: [['ET1-bas', 0.001], ['ET2-bas', 0.998], ['LN-ET', 0.001]],
  Lung: [['BBi-bas', 0.1665], ['BBi-sec', 0.1665], ['bbe-sec', 0.333], ['AI', 0.333], ['LN-Th', 0.001]],
  Skin: [['Skin', 1]], Spleen: [['Spleen', 1]], Testes: [['Testes', 1]], Thymus: [['Thymus', 1]],
  Thyroid: [['Thyroid', 1]], Uterus: [['Uterus', 1]],
};
const REM_KEYS = Object.keys(REMAINDER_60);
const R = REM_KEYS.length;
/* The virtual targets after the real ones: [0] the remainder; [1 + k] the
   remainder without tissue k (the splitting rule); [1 + R + k] tissue k's
   share of the remainder; [1 + 2R + kR + i] tissue i's share of the
   remainder without tissue k. The remainder's masses change as a child grows,
   so these shares, which add up to the remainder's dose whichever way it is
   taken, have to be integrated: each tissue's part of e (the tissue table's
   bars) follows from them. */
const N_VIRTUAL = 1 + 2 * R + R * R;

/*
  The effective dose as weights of the target rows of an integration (the
  targets, the remainder, and the remainder with each of its tissues split
  off): E = base + 0.20 H_gonads + 0.05 remainder, where the gonads are the
  testes or the ovaries and the remainder follows the splitting rule, both
  decided on the committed doses. So the pieces: [0] base, the weighted
  tissues but the gonads; [1] testes; [2] ovaries; [3] the remainder; then
  for each remainder tissue its dose and the remainder without it.
*/
function effectivePieces60(nT) {
  const len = nT + 1 + REM_KEYS.length;
  const tissue = (name, w = 1, into = new Float64Array(len)) => { for (const [t, wp] of TISSUES_60[name]) into[T[t]] += w * wp; return into; };
  const row = (i) => { const v = new Float64Array(len); v[i] = 1; return v; };
  const base = new Float64Array(len);
  for (const [k, w] of Object.entries(W_60)) if (k !== 'Gonads') tissue(k, w, base);
  return [base, tissue('Testes'), tissue('Ovaries'), row(nT), ...REM_KEYS.flatMap((k, i) => [tissue(k), row(nT + 1 + i)])];
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
function otherTargets(j, members, common) {
  const own = new Set(members[j].explicit), parent = new Set(members[0].explicit);
  const out = [];
  for (const r of common) {
    if (isBone(r)) continue;
    if (parent.has(r)) { if (!own.has(r)) out.push([r, 'own']); continue; }
    const first = members.findIndex((m) => m.explicit.includes(r));
    out.push([r, j >= first ? 'parent' : 'own']);
  }
  if (![...own].some(isBone) && [...common].some(isBone)) for (const r of BONE_V) out.push([r, 'own']);
  return out;
}

/* The mass of the Other of a model naming these regions. */
function robMass(explicit, mS) {
  let rob = mS.Body_Tis - (mS.Ht_Cont || 0);
  for (const r of explicit) if (mS[r] && !isBone(r)) rob -= mS[r];
  if (explicit.some(isBone)) rob -= mS['C_Bone-V'] + mS['T_Bone-V'];
  return rob;
}

function otherShares(j, members, targets, mS) {
  const rob = { own: robMass(members[j].explicit, mS), parent: robMass(members[0].explicit, mS) };
  const shares = targets.filter(([r]) => mS[r] > 0).map(([r, of]) => [r, mS[r] / rob[of]]);
  if (!shares.length) return [['Other', 1]];
  return [['Other', 1 - shares.reduce((a, [, f]) => a + f, 0)], ...shares];
}

/** Interpolated remainder masses at an age, in the order of REMAINDER_60. */
function remainderMasses(age) {
  const ages = PHANTOM_AGES_60;
  let k = 0;
  while (k < ages.length - 2 && age > ages[k + 1]) k++;
  const w = Math.min(1, Math.max(0, (age - ages[k]) / (ages[k + 1] - ages[k])));
  return REM_KEYS.map((r) => REMAINDER_60[r][k] + w * (REMAINDER_60[r][k + 1] - REMAINDER_60[r][k]));
}

/**
 * Dose coefficients for one intake at the given ages.
 * @param {object} data  {index, models, saf, emissions: (nuclide) => {r, bs}}
 * @param {object} spec  {nuclide, route, type, lung, amad, bio, f1file, kinetics, last, adultAge}
 * @param {number[]} [ages]
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
    const targets = sys.members.map((m, j) => otherTargets(j, sys.members, common));
    const regionsOf = sys.members.map((m, j) => {
      const own = [...new Set(sys.comps.filter((c) => c.member === j).map((c) => c.region))];
      const extra = own.includes('Other') ? targets[j].map(([r]) => r) : [];
      return [...new Set([...own, ...extra])];
    });
    const seeOf = sys.members.map((m, j) => {
      const em = data.emissions(m.name);
      const A = Number(/-(\d+)/.exec(m.name)[1]);
      return phantoms.map((ph) => ph.see(em, A, regionsOf[j], common));
    });
    // Per member and phantom: how its Other activity divides among the regions.
    const otherSplit = sys.members.map((m, j) => phantoms.map((ph) => otherShares(j, sys.members, targets[j], ph.masses.sources)));
    // Virtual targets: the remainder, normal and with each tissue split off.
    const nT = TARGETS_60.length;
    const remRows = REM_KEYS.map((r) => TISSUES_60[r].map(([t, w]) => [T[t], w]));
    // One column per member and source region, shared by its compartments
    // (solve.js integrates them as one group): the SEE of the region at a
    // phantom, for Other with the shares of a phantom (the same one, or with
    // `pShare`, the other end of the interval: solve.js's cross columns).
    const column = (c, p, pShare = p) => {
      const col = new Float64Array(nT + N_VIRTUAL);
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
      const mass = remainderMasses(PHANTOM_AGES_60[p]);
      const tissue = remRows.map((row) => row.reduce((acc, [t, w]) => acc + w * col[t], 0));
      const M = mass.reduce((a, b) => a + b, 0);
      col[nT] = tissue.reduce((acc, h, i) => acc + mass[i] * h, 0) / M;
      for (let k = 0; k < R; k++) {
        col[nT + 1 + k] = tissue.reduce((acc, h, i) => (i === k ? acc : acc + mass[i] * h), 0) / (M - mass[k]);
        col[nT + 1 + R + k] = mass[k] * tissue[k] / M;
        for (let i = 0; i < R; i++) if (i !== k) col[nT + 1 + 2 * R + k * R + i] = mass[i] * tissue[i] / (M - mass[k]);
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
    const pieces = opt.outputs ? effectivePieces60(nT) : null;
    const res = integrate(sys, { phantomAges: PHANTOM_AGES_60, columns, nTargets: nT + N_VIRTUAL, groups, interp: 'linear', weights: 'dcal', cross: cross || undefined, functionals: pieces || undefined, byCompartment: !!opt.outputs },
      { intakeAge, period, outputs: opt.outputs, rtol: opt.rtol });
    const Ht = Object.fromEntries(TARGETS_60.map((t, i) => [t, res.H[i]]));
    const H = {};
    for (const [name, parts] of Object.entries(TISSUES_60)) H[name] = parts.reduce((acc, [t, w]) => acc + w * Ht[t], 0);
    H.Gonads = Math.max(H.Testes, H.Ovaries);
    // Remainder and the splitting rule, decided on the committed doses.
    const named = Math.max(...Object.keys(W_60).map((k) => H[k]));
    let kmax = 0;
    REM_KEYS.forEach((r, k) => { if (H[r] > H[REM_KEYS[kmax]]) kmax = k; });
    const split = H[REM_KEYS[kmax]] > named;
    const remainder = split ? 0.5 * H[REM_KEYS[kmax]] + 0.5 * res.H[nT + 1 + kmax] : res.H[nT];
    H.Remainder = remainder;
    // Each remainder tissue's part of it: by its mass, or, split, half the
    // remainder to the one and the rest by mass among the others.
    const remainderShares = Object.fromEntries(REM_KEYS.map((r, i) => [r, !split ? res.H[nT + 1 + R + i]
      : i === kmax ? 0.5 * H[r] : 0.5 * res.H[nT + 1 + 2 * R + kmax * R + i]]));
    let E = 0.05 * remainder;
    for (const [k, w] of Object.entries(W_60)) E += w * H[k];
    // The gonads' dose is the higher of the testes' and the ovaries' (as committed).
    const gonads = H.Testes >= H.Ovaries ? 'Testes' : 'Ovaries';
    if (pieces) {
      const K = pieces.length, splitAt = split ? REM_KEYS.indexOf(REM_KEYS[kmax]) : -1;
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
      age: age0, intakeAge, E, H, Ht, split: split ? REM_KEYS[kmax] : null, gonads, remainderShares,
      doseGroups: opt.outputs ? res.doseGroups.map((g) => ({ ...g, name: sys.comps[g.comps[0]].name })) : null,
      transformations: groupKeys.map((k, g) => ({ member: sys.members[Number(k.split('|')[0])].name, region: k.split('|')[1], n: res.U[g] })),
      system: sys, stats: res.stats, series: opt.outputs ? res.series : null,
    };
  });
}
