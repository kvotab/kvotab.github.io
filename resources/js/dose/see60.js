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
    - from Other, the body tissues not named in the biokinetic model: none to
      a named region and 1/M_Other to every other target, the bone surface
      and red marrow included (photons by SEECAL's equation (9));
    - from BT-Soft, the body tissues without the bone volumes: 1/M to every
      target, to the bone surface the share of it that lies in the marrow.

  wR is 20 for alphas and recoils, 1 otherwise.

  Spontaneous fission as SEECAL 8.4 has it (DCAL's; its routine SponFiss and
  the SEE routine after it, read from the program -- the manual of 1993 says
  SEECAL leaves fission out). Per fission of a nuclide of atomic number Z and
  mass number A, with nu the mean number of neutrons and X = 92 A/236 + 5.98
  - Z the beta decays of the fragments:

    - two fragments of 0.0698 Z^2/A^(1/3) - 10.988 MeV each, absorbed as
      alphas are, wR 20 (from the red marrow, Other or BT-Soft into the
      marrow or bone surface with an alpha's recoil, 4.0026/(A - 4) more);
    - nu neutrons of 0.75 + 0.65 sqrt(1 + nu) MeV (Terrell's mean energy),
      wR 10, spread through the body as photons of 0.03, 0.05 and 1 MeV in
      the proportions 5.37 : 6.94 : 1.81;
    - prompt gammas, 8.64 photons in 42 lines (7.65 MeV), and delayed gammas,
      28 lines (7.22 MeV at X = 5.98) times (X/5.98)^2;
    - X betas of 0.2058 X MeV, absorbed as electrons above 0.2 MeV are.

  The photon SAF of these lines is linear in energy between the tabulated
  ones, above 4 MeV the line through the 2 and 4 MeV values, nothing under
  10 keV or below zero, and at most 1/mass of the target. In the respiratory
  tract the fragments take the absorbed fractions of 2.5 MeV alpha particles,
  as ICRP 72's doses for 252Cf, 254Cf, 248Cm and 250Cm have them (SEECAL 8.4
  slips there, and in its photons from the bones on: README).
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

/* SEECAL's spectra of fission photons: [MeV, photons per fission]. */
const FISSION_PROMPT = [[0.0148, 0.0947], [0.0314, 0.247], [0.0453, 0.00716], [0.0553, 0.0102], [0.0753, 0.0208], [0.0853, 0.0295],
  [0.0953, 0.0421], [0.11, 0.14], [0.13, 0.14], [0.15, 0.14], [0.17, 0.14], [0.19, 0.14], [0.225, 0.351], [0.275, 0.351],
  [0.325, 0.351], [0.375, 0.351], [0.425, 0.351], [0.475, 0.351], [0.525, 0.351], [0.575, 0.351], [0.649, 0.676],
  [0.749, 0.565], [0.849, 0.474], [0.949, 0.396], [1.049, 0.332], [1.149, 0.277], [1.25, 0.232], [1.35, 0.194],
  [1.45, 0.162], [1.73, 0.575], [2.23, 0.334], [2.73, 0.193], [3.23, 0.112], [3.73, 0.065], [4.23, 0.0377],
  [4.73, 0.0218], [5.23, 0.0127], [5.91, 0.0116], [6.91, 0.0039], [7.91, 0.0013], [8.91, 0.00044], [9.91, 0.00015]];
const FISSION_DELAYED = [[0.03, 0.11], [0.05, 0.11], [0.07, 0.11], [0.09, 0.11], [0.11, 0.11], [0.13, 0.11], [0.15, 0.11],
  [0.17, 0.11], [0.19, 0.11], [0.225, 0.27], [0.275, 0.27], [0.325, 0.27], [0.375, 0.27], [0.44, 0.76], [0.54, 0.59],
  [0.64, 0.46], [0.74, 0.36], [0.84, 0.28], [1.1, 1.18], [1.56, 0.72], [2.0, 0.38], [2.4, 0.28], [2.8, 0.16],
  [3.25, 0.12], [3.75, 0.086], [4.25, 0.042], [4.75, 0.02], [5.25, 0.0095]];
/* Neutrons: photons of these energies, MeV, in these proportions. */
const FISSION_NEUTRON = [[0.03, 5.37], [0.05, 6.94], [1.0, 1.81]];

/**
 * What one spontaneous fission gives off, as SEECAL's SponFiss has it.
 * @param {number} nu  mean number of neutrons
 * @param {number} Z   atomic number
 * @param {number} A   mass number
 */
export function fission60(nu, Z, A) {
  const X = A * 92 / 236 + 5.98 - Z;
  return {
    X,
    fragment: 2 * (0.0698 * Z * Z / Math.cbrt(A) - 10.988), // MeV, both fragments
    neutron: nu * (0.75 + 0.65 * Math.sqrt(1 + nu)),           // MeV
    delayed: 0.02796 * X * X,                                  // times the delayed spectrum
    beta: [0.2058 * X, X],                                     // [MeV, betas]
  };
}

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
    // Recoils count from the marrow (FGR 13 leaves them out only for sources
    // in bone surface or volume).
    if (s === 'R_Marrow') {
      if (t === 'R_Marrow') return 1 / mT.R_Marrow;
      if (t === 'Bone_Sur') return ENDOSTEAL_IN_MARROW[phantom] / mT.R_Marrow;
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

  /* SEECAL's photon SAF for a fission line: see the head of this file. */
  const i2 = E.indexOf(2), i4 = E.indexOf(4);
  function fissionSaf(row, e, t) {
    if (e < 0.01) return 0;
    const v = e > 4 ? row[i2] + (row[i4] - row[i2]) * (e - 2) / 2 : lerp(E, row, e);
    if (!(v > 0)) return 0;
    return mT[t] > 0 ? Math.min(v, 1 / mT[t]) : v;
  }
  const lineSum = (row, lines, t) => lines.reduce((a, [e, y]) => a + e * y * fissionSaf(row, e, t), 0);

  /**
   * SEE matrix for one nuclide's emissions over the given sources.
   * @param {object} em      {r: {p, b, e, a, sf}, bs} of the decay data
   * @param {number} A       mass number (alpha recoil energy)
   * @param {string[]} sources  source regions (may include Other, Blood, Body_Tis, BT-Soft)
   * @param {Set<string>} explicit  the explicitly named systemic regions, for Other
   * @param {string[]} targets
   * @param {{Z?: number}} [opt]  the atomic number, for spontaneous fission
   * @returns {Float64Array[]}  see[t][s], Sv per transformation
   */
  function see(em, A, sources, explicit, targets = TARGETS_60, opt = {}) {
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

    // Spontaneous fission: [fraction of transformations, mean neutrons].
    const sf = (r.sf || []).find(([y]) => y > 0);
    const fis = sf && opt.Z ? fission60(sf[1], opt.Z, A) : null;
    // The photon SAF row of a source at the tabulated energies; Other and
    // BT-Soft by the mass balance of their parts.
    const zeros = E.map(() => 0);
    const rowOf = (t, s) => {
      if (s === 'Other' || s === 'BT-Soft') {
        const parts = s === 'Other' ? otherParts : ['C_Bone-V', 'T_Bone-V'];
        const M = s === 'Other' ? MOther : MWB - mS['C_Bone-V'] - mS['T_Bone-V'];
        const wb = rowOf(t, 'Body_Tis');
        return E.map((_, j) => (MWB * wb[j] - parts.reduce((a, x) => a + mS[x] * rowOf(t, x)[j], 0)) / M);
      }
      const v = tab(t, s);
      return v === 0 ? zeros : v;
    };

    const out = targets.map(() => new Float64Array(sources.length));
    sources.forEach((s, k) => {
      targets.forEach((t, i) => {
        let ph = 0, np = 0, al = 0;
        // Fission: fragments and betas by their non-penetrating fraction
        // (set below with the other radiations), neutrons and gammas here.
        let ffAf = 0, fbAf = 0;
        if (fis) {
          const row = rowOf(t, s);
          ph += sf[0] * (lineSum(row, FISSION_PROMPT, t) + fis.delayed * lineSum(row, FISSION_DELAYED, t));
          ph += 10 * sf[0] * fis.neutron * lineSum(row, FISSION_NEUTRON, t);
        }
        if (s === 'Other') {
          ph += photons.length ? (MWB * phSum(t, 'Body_Tis') - otherParts.reduce((acc, x) => acc + mS[x] * phSum(t, x), 0)) / MOther : 0;
          // Electrons, alphas and their recoils from Other: none to a region
          // the model names, 1/M_Other to every other target, the bone
          // surface and red marrow too (as SEECAL has it; equation (9) taken
          // to the bone targets gives them less, and below zero where the
          // model names the red marrow).
          const npOther = explicit.has(t) ? 0 : 1 / MOther;
          np = (eLo + eHi) * npOther;
          al = (alphaE + recoilE) * npOther;
          if (fis) { ffAf = npOther; fbAf = npOther; }
        } else if (s === 'BT-Soft') {
          const MB = mS['C_Bone-V'] + mS['T_Bone-V'];
          const M = MWB - MB;
          ph += photons.length ? (MWB * phSum(t, 'Body_Tis') - mS['C_Bone-V'] * phSum(t, 'C_Bone-V') - mS['T_Bone-V'] * phSum(t, 'T_Bone-V')) / M : 0;
          // From the soft tissues, the bone volumes left out: 1/M to every
          // target, the bone surface the part of it that lies in the marrow
          // (as SEECAL has it).
          const f = t === 'Bone_Sur' ? ENDOSTEAL_IN_MARROW[phantom] / M : 1 / M;
          np = (eLo + eHi) * f;
          al = (alphaE + recoilE) * f;
          if (fis) { ffAf = f; fbAf = f; }
        } else if (LUNG_REGIONS.has(s)) {
          ph += photons.length ? phSum(t, s) : 0;
          const l = lungNp(t, s);
          np = mT[t] ? l.e / mT[t] : 0;
          al = mT[t] ? l.a / mT[t] : 0;
          if (fis && mT[t]) { ffAf = lungAf(t, s, 2.5, ALPHA, false) / mT[t]; fbAf = lungAf(t, s, fis.beta[0], E_LO, false) / mT[t]; }
        } else {
          ph += photons.length ? phSum(t, s) : 0;
          np = eLo * npSaf(t, s, E_LO, false) + eHi * npSaf(t, s, E_HI, false);
          al = alphaE * npSaf(t, s, ALPHA, false) + recoilE * npSaf(t, s, ALPHA, true);
          if (fis) { ffAf = npSaf(t, s, ALPHA, false); fbAf = npSaf(t, s, E_HI, false); }
        }
        if (fis) {
          // Red marrow, Other and BT-Soft to the marrow and bone surface: the
          // fragments go through SEECAL's alpha routine, which adds the
          // recoil of an alpha.
          if ((s === 'R_Marrow' || s === 'Other' || s === 'BT-Soft') && (t === 'R_Marrow' || t === 'Bone_Sur')) ffAf *= 1 + 4.0026 / (A - 4);
          al += sf[0] * fis.fragment * ffAf;
          np += sf[0] * fis.beta[0] * fis.beta[1] * fbAf;
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
