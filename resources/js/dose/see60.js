/*
  Specific effective energies in the ICRP 60 system: SEE(T<-S), the equivalent
  dose in target T per nuclear transformation in source S, Sv. The method is
  SEECAL's (Cristy and Eckerman, ORNL/TM-12351; ORNL/TM-2001/190; FGR 13
  chapter 5 and appendix B):

    SEE(T<-S) = sum_i wR_i Y_i E_i SAF_i(T<-S)

  Photons of 10 keV and more take the specific absorbed fractions of the
  Cristy-Eckerman phantoms, interpolated linearly in energy. Electrons
  (beta particles at the mean energy of each transition, conversion and Auger
  electrons), photons under 10 keV, alpha particles and alpha recoil nuclei
  are absorbed where they are emitted, except:

    - in bone, where the absorbed fractions of ICRP 30 hold, by the energy of
      each electron (under or over 0.2 MeV) and for alphas;
    - in the contents of walled organs: the wall takes half the equilibrium
      dose of the contents, a hundredth of that for alphas, none for recoils;
    - in the respiratory tract, where the absorbed fractions of ICRP 66 Annex
      H hold, against the beta spectrum for beta emitters;
    - from Body Tissues and Blood, which irradiate every target alike;
    - from Other, the body tissues not named in the biokinetic model,
      computed by SEECAL's equation (9).

  Spontaneous fission is not addressed (SEECAL leaves it out with a warning;
  so does this). wR is 20 for alphas and recoils, 1 otherwise.
*/
import { WALL_OF, BONE_SOURCES, LUNG_REGIONS, CONTENTS } from './regions.js';

export const MEV = 1.602176634e-13; // J
export const TARGETS_60 = ['Adrenals', 'UB_Wall', 'Bone_Sur', 'Brain', 'Breasts', 'St_Wall', 'SI_Wall', 'ULI_Wall',
  'LLI_Wall', 'Kidneys', 'Liver', 'ET1-bas', 'ET2-bas', 'LN-ET', 'BBi-bas', 'BBi-sec', 'bbe-sec', 'AI', 'LN-Th',
  'Muscle', 'Ovaries', 'Pancreas', 'R_Marrow', 'Skin', 'Spleen', 'Testes', 'Thymus', 'Thyroid', 'GB_Wall',
  'Ht_Wall', 'Uterus'];

/* ICRP 30 Part 1 absorbed fractions in bone (FGR 13 table B.2), by radiation:
   alpha, electrons under 0.2 MeV, electrons of 0.2 MeV and over. */
const BONE_AF = {
  'C_Bone-S': { R_Marrow: [0, 0, 0], Bone_Sur: [0.25, 0.25, 0.015] },
  'C_Bone-V': { R_Marrow: [0, 0, 0], Bone_Sur: [0.01, 0.015, 0.015] },
  'T_Bone-S': { R_Marrow: [0.5, 0.5, 0.5], Bone_Sur: [0.25, 0.25, 0.025] },
  'T_Bone-V': { R_Marrow: [0.05, 0.35, 0.35], Bone_Sur: [0.025, 0.025, 0.025] },
};
/* Fraction of the endosteal tissue that lies in the red marrow: newborn, 1, 5,
   10, 15 y, adult (SEECAL table 2, note b). */
const ENDOSTEAL_IN_MARROW = { A00: 1.0, A01: 0.83, A05: 0.65, A10: 0.65, A15: 0.65, AM: 0.5, AF: 0.5 };

const ALPHA = 0, E_LO = 1, E_HI = 2;

/** Linear interpolation in x over a table, held flat beyond its ends. */
export function lerp(xs, ys, x) {
  if (x <= xs[0]) return ys[0];
  const n = xs.length;
  if (x >= xs[n - 1]) return ys[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= x) lo = m; else hi = m; }
  return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo]);
}

/**
 * The SEE calculator for one phantom of the ICRP 60 system.
 *
 * @param {object} saf     saf.json
 * @param {string} phantom 'A00' ... 'AM'
 */
export function phantom60(saf, phantom) {
  const P = saf.phantoms[phantom];
  const E = saf.photonEnergies;
  const mT = P.masses.targets, mS = P.masses.sources;
  const MWB = mS.Body_Tis;
  const lungE = indexLungAF(saf.lungAF.electron), lungA = indexLungAF(saf.lungAF.alpha);

  const photonSaf = (t, s) => {
    const v = P.saf[`${t}<-${s}`];
    return v === undefined ? null : v;
  };
  /* Photon SAF of a region the file tabulates; Blood is Body Tissues. */
  const tab = (t, s) => {
    const v = photonSaf(t, s === 'Blood' ? 'Body_Tis' : s);
    if (v === null) throw new Error(`no photon SAF ${t}<-${s} for ${phantom}`);
    return v;
  };

  /* Non-penetrating SAF (kg^-1) from a named region, for radiation class c. */
  function npSaf(t, s, c, recoil) {
    if (s === 'Body_Tis' || s === 'Blood') return 1 / MWB;
    if (BONE_SOURCES.has(s)) {
      if (recoil) return 0;
      const af = BONE_AF[s][t];
      return af ? af[c] / mT[t] : 0;
    }
    if (s === 'R_Marrow') {
      if (t === 'R_Marrow') return 1 / mT.R_Marrow;
      if (t === 'Bone_Sur') return recoil ? 0 : ENDOSTEAL_IN_MARROW[phantom] / mT.R_Marrow;
      return 0;
    }
    if (WALL_OF[s]) {
      if (t !== WALL_OF[s] || recoil) return 0;
      const m = mS[s];
      return (c === ALPHA ? 0.005 : 0.5) / m;
    }
    if (CONTENTS.has(s)) return 0;
    if (s === 'Lng_Tiss') return t === 'Lng_Tiss' ? 1 / mT.Lng_Tiss : 0;
    return t === s && mT[t] ? 1 / mT[t] : 0;
  }

  /* Respiratory tract sources: ICRP 66 absorbed fractions, interpolated in
     energy; ELALPHAF's constant fractions for the pairs it lists. */
  function lungAf(t, s, energy, c, recoil) {
    if (recoil) return (t === s && (s === 'AI' || s === 'LN-Th' || s === 'LN-ET')) ? 1 : 0;
    const table = c === ALPHA ? lungA : lungE;
    const p = table.get(`${t}<-${s}`);
    let af = p ? lerp(table.energies, p, energy) : 0;
    const fixed = P.af[c === ALPHA ? 'alpha' : 'electron'][`${t}<-${s}`];
    if (fixed !== undefined) af += fixed;
    return af;
  }

  /**
   * SEE matrix for one nuclide's emissions over the given sources.
   * @param {object} em      {r: {p, b, e, a}, bs} of the decay data
   * @param {number} A       mass number (alpha recoil energy)
   * @param {string[]} sources  source regions (may include Other, Blood, Body_Tis, BT-Soft)
   * @param {Set<string>} explicit  the explicitly named systemic regions, for Other
   * @param {string[]} targets
   * @returns {Float64Array[]}  see[t][s], Sv per transformation
   */
  function see(em, A, sources, explicit, targets = TARGETS_60) {
    const r = em.r || {};
    const photons = (r.p || []).filter(([e]) => e >= 0.01);
    const softPh = (r.p || []).filter(([e]) => e < 0.01).reduce((s, [e, y]) => s + e * y, 0);
    const betas = r.b || [], elec = r.e || [], alphas = r.a || [];
    const recoilE = alphas.reduce((s, [e, y]) => s + y * e * 4.0026 / (A - 4), 0);
    const alphaE = alphas.reduce((s, [e, y]) => s + y * e, 0);
    // Electron energy by class: under / over 0.2 MeV, with soft photons in the
    // lower class (SEECAL treats them as electrons there).
    let eLo = softPh, eHi = 0;
    for (const [e, y] of [...betas, ...elec]) { if (e < 0.2) eLo += e * y; else eHi += e * y; }

    // Photon SAF row for a tabulated source, energy-weighted: sum Y E SAF(E).
    const phSum = (t, s) => {
      const v = tab(t, s);
      if (v === 0) return 0; // an all-zero row is stored as 0
      let sum = 0;
      for (const [e, y] of photons) sum += y * e * interpPhoton(E, v, e);
      return sum;
    };
    // Lung sources: electrons against the beta spectrum and the lines.
    const lungNp = (t, s) => {
      let sum = 0;
      for (const [e, y] of elec) sum += y * e * lungAf(t, s, e, E_LO, false);
      if (em.bs && betas.length) sum += spectrumAf(em.bs, (e) => lungAf(t, s, e, E_LO, false));
      else for (const [e, y] of betas) sum += y * e * lungAf(t, s, e, E_LO, false);
      sum += softPh * lungAf(t, s, 0.005, E_LO, false);
      let a = 0;
      for (const [e, y] of alphas) a += y * e * lungAf(t, s, e, ALPHA, false);
      a += recoilE * lungAf(t, s, 0, ALPHA, true);
      return { e: sum, a };
    };

    // Other: equation (9) with the explicit regions; mineral bone left out of
    // Other as a whole when any bone region is named; heart contents never in it.
    const boneNamed = [...explicit].some((x) => BONE_SOURCES.has(x));
    const otherParts = [];
    for (const x of explicit) {
      if (BONE_SOURCES.has(x) || CONTENTS.has(x) || LUNG_REGIONS.has(x)) continue;
      if (mS[x]) otherParts.push(x);
    }
    if (boneNamed) otherParts.push('C_Bone-V', 'T_Bone-V');
    otherParts.push('Ht_Cont');
    const MOther = MWB - otherParts.reduce((s, x) => s + mS[x], 0);

    const out = targets.map(() => new Float64Array(sources.length));
    sources.forEach((s, k) => {
      targets.forEach((t, i) => {
        let ph = 0, np = 0, al = 0;
        if (s === 'Other') {
          ph = photons.length ? (MWB * phSum(t, 'Body_Tis') - otherParts.reduce((acc, x) => acc + mS[x] * phSum(t, x), 0)) / MOther : 0;
          const npOther = (c, recoil) => {
            if (t !== 'R_Marrow' && t !== 'Bone_Sur') return explicit.has(t) ? 0 : 1 / MOther;
            return (MWB * (1 / MWB) - otherParts.reduce((acc, x) => acc + mS[x] * npSaf(t, x, c, recoil), 0)) / MOther;
          };
          np = eLo * npOther(E_LO, false) + eHi * npOther(E_HI, false);
          al = alphaE * npOther(ALPHA, false) + recoilE * npOther(ALPHA, true);
        } else if (s === 'BT-Soft') {
          const MB = mS['C_Bone-V'] + mS['T_Bone-V'];
          const M = MWB - MB;
          ph = photons.length ? (MWB * phSum(t, 'Body_Tis') - mS['C_Bone-V'] * phSum(t, 'C_Bone-V') - mS['T_Bone-V'] * phSum(t, 'T_Bone-V')) / M : 0;
          const f = (c, recoil) => (1 - mS['C_Bone-V'] * npSaf(t, 'C_Bone-V', c, recoil) - mS['T_Bone-V'] * npSaf(t, 'T_Bone-V', c, recoil)) / M;
          np = eLo * f(E_LO, false) + eHi * f(E_HI, false);
          al = alphaE * f(ALPHA, false) + recoilE * f(ALPHA, true);
        } else if (LUNG_REGIONS.has(s)) {
          ph = photons.length ? phSum(t, s) : 0;
          const l = lungNp(t, s);
          np = mT[t] ? l.e / mT[t] : 0;
          al = mT[t] ? l.a / mT[t] : 0;
        } else {
          ph = photons.length ? phSum(t, s) : 0;
          np = eLo * npSaf(t, s, E_LO, false) + eHi * npSaf(t, s, E_HI, false);
          al = alphaE * npSaf(t, s, ALPHA, false) + recoilE * npSaf(t, s, ALPHA, true);
        }
        out[i][k] = MEV * (ph + np + 20 * al);
      });
    });
    return out;
  }

  return { see, masses: P.masses, phantom, targets: TARGETS_60 };
}

/* Linear interpolation of a 12-point photon SAF row in energy; held at the
   end values outside 10 keV - 4 MeV. */
function interpPhoton(E, v, e) {
  return lerp(E, v, e);
}

function indexLungAF(t) {
  const m = new Map();
  for (const p of t.pairs) m.set(`${p.target}<-${p.source}`, p.af);
  m.energies = t.energies;
  return m;
}

/* integral of N(E) E AF(E) dE over a beta spectrum tabulated at points, by
   the trapezoidal rule on the tabulated grid. */
export function spectrumAf(bs, af) {
  const [es, ns] = bs;
  let sum = 0;
  for (let i = 1; i < es.length; i++) {
    const a = ns[i - 1] * es[i - 1] * af(es[i - 1]);
    const b = ns[i] * es[i] * af(es[i]);
    sum += 0.5 * (a + b) * (es[i] - es[i - 1]);
  }
  return sum;
}
