/*
  Specific effective energies in the ICRP 60 system: SEE(T<-S), the equivalent
  dose in target T per nuclear transformation in source S, Sv. The method is
  SEECAL's (Cristy and Eckerman, ORNL/TM-12351; ORNL/TM-2001/190; FGR 13
  chapter 5 and appendix B):

    SEE(T<-S) = sum_i wR_i Y_i E_i SAF_i(T<-S)

  Photons of 10 keV and more take the specific absorbed fractions of the
  Cristy-Eckerman phantoms, tabulated at 12 energies; between them the energy
  a photon leaves per kilogram, E SAF(E), is linear in energy. That is how
  Publication 72's coefficients have it: with the SAF itself linear in energy,
  as DCAL's SEECAL interpolates (8.4, and that of 1993, whose printed example
  of 224Ra comes out to its four figures that way; FGR 13 and the manual say
  "linearly between energies"), 72 % of ICRP 72's organ doses round to
  its two figures; with E SAF 85 %, and the emitters of X-rays between the
  tabulated energies (145Pm's 37-43 keV, 165Er's 47-55 keV) from 3-7 % off
  to within them (README). Electrons
  (beta particles at the mean energy of each transition, conversion and Auger
  electrons), photons under 10 keV, alpha particles and alpha recoil nuclei
  are absorbed where they are emitted, except:

    - in bone, where the absorbed fractions of ICRP 30 hold, by the energy of
      each electron (under or over 0.2 MeV) and for alphas;
    - in the contents of walled organs: the wall takes half the equilibrium
      dose of the contents, a hundredth of that for alphas, none for recoils;
    - in the respiratory tract, where the absorbed fractions of ICRP 66 Annex
      H hold -- by its algebraic functions (af66), as the ICRP's coefficients
      have them -- against the beta spectrum for beta emitters (spectrumAf:
      the spectrum in groups, as the ICRP's coefficients have it);
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

/* J per MeV as the ICRP's coefficients have it: 1.6e-13, the rounded factor
   of Publication 30 (H = 1.6e-10 U SEE), as in the ICRP 103 system
   (see103.js). With the exact value the page's adult doses were 1.0019 times
   ICRP 72's, alike for alpha emitters and the others, short-lived and
   long-lived, swallowed and breathed in (README); 1.602176634 / 1.6 =
   1.00136. DCAL's SEECAL has the exact value (8.4, and that of 1993: the
   example of ORNL/TM-12351 to its four figures), MEV_DCAL. */
export const MEV = 1.6e-13;
export const MEV_DCAL = 1.602176634e-13;

/* The mass of the body's tissues, kg, by phantom: what a source spread through
   the whole body, or through the rest of it, is spread over. As the doses of
   the ICRP's database of dose coefficients have it (README): after 3H, 14C,
   36Cl, 135Cs and 211At, which go to the whole body, every tissue's dose over
   the first day is DCAL's Body_Tis over this mass, at each age to 6e-5, and
   after nuclides that go to the rest of the body beside named organs (33P,
   45Ca, 79Se, 210Po, 239Pu ...) within 0.05 %. DCAL's REGMASS files have
   3.5357, 9.5431, 19.458, 32.620, 55.825 and 68.831 kg, the body without the
   contents of the gall bladder, the urinary bladder and the alimentary tract.
   The adult's here is that with the 135 g of the lower large intestine's
   contents left in; for the children's no such account was found (72, 36, 60
   and 42 g more than DCAL's at 1, 5, 10 and 15 years). The newborn's is the
   one that makes the 3-month-old's so, between it and the 1-year-old's by
   DCAL's weights. */
export const BODY_TISSUES_60 = { A00: 3.5335, A01: 9.6155, A05: 19.4935, A10: 32.680, A15: 55.867, AM: 68.966 };
/* The mass of the newborn's alveolar region, kg, with the fourth figure the
   ICRP's database of dose coefficients shows: DCAL's file has 0.0514, with
   which the alveolar region's dose on the first day after an intake at 3
   months is 1.00059 of the database's at each of its ten particle sizes
   (alpha emitters, where it is from the region alone), the other parts of
   the airways 1.00000; 0.05145 makes it 1.00000. The other ages' masses,
   and the newborn's of the bronchi and bronchioles, are the database's as
   the file has them. */
export const AI_NEWBORN_60 = 0.05145;
/* The absorbed fractions of the airways as the ICRP's coefficients have
   them: by the algebraic functions that Annex H of Publication 66 gives
   beside its tables (Table H.7), with the fitted parameters of Table H.8 for
   alpha particles and Table H.9 for electrons. A. Birchall and N. S. Jarvis
   of NRPB made them (para H28), and NRPB's code calculated Publication 72.
   They follow Tables H.1 and H.2 "to within about 1 %" (at the tabulated
   energies nine points in ten within 0.6 % for alphas and within 2.7 % for
   electrons up to 2 MeV; test-engine.mjs) but they are not the tables: they
   run smoothly through the energies at which a
   target comes within an alpha particle's range, where straight lines
   between the tables' points are far off. Measured on the parts of the
   airways that the ICRP's database of dose coefficients stores, committed
   doses of adults, this engine over the database (README):

                             functions    tables, straight lines
     63Ni  M   ET1           1.0000       0.810
     90Y   M   BB sec        0.999        1.018
     147Sm M   BB sec, bas   0.994        1.91, 2.43
     239Pu S   ET1           0.997        0.33
     244Cm M   ET1           0.999        1.40
     210Po M   BB bas        0.997        1.042

   A row: the function's number, then its parameters a1, a2, ... as printed.
   "Fast" mucus is the gel and "slow" the sol; x is the energy in MeV and the
   logarithms are to base 10 (so the functions reproduce the tables).

     1  AF = sum over k = 1, 4, 7, 10 of a[k] exp(a[k+1] (log(log x + a[k+2]))^2)
     2  AF = (1 - exp(-(x/a10)^20)) a1 (1 + a2 e^(a3 x) + a4 e^(a5 x) + a6 e^(a7 x) + a8 e^(a9 x))
     3  AF = G(a2, a3, a4) + G(a1 - a2, a5, a6) + a7 exp(-(a8 log(a9 x))^2),
        G(A, w, c) = A below x = 1/c and A exp(-(w log(c x))^2) from there on

   Alpha particles from AI reach no bronchial target (no rows). */
export const AF66_ALPHA = {
  'ET1-bas<-ET1-sur': [1, 0.01796145, -3119.876, 0.1900499, 0.08115775, -332.282, -0.04370656, 0.0385861, -1773.797, 0.1467869, 0.05591718, -884.288, 0.08164135],
  'ET2-bas<-ET2-sur': [1, 0.001987374, -5601.585, 0.1983734, 0.06499644, -917.1186, -0.03310157, 0.02179814, -2029.563, 0.140741, 0.02757517, -1792.149, 0.07648437],
  'ET2-bas<-ET2-bnd': [3, 0.1818, 0.07177234, 2.16186, 0.4142823, 0.6751693, 0.9448594, 0.0116813, 7.590152, 0.1566737],
  'ET2-bas<-ET2-seq': [1, 0.004805373, -432.9348, 0.2460405, 0.06266583, -48.09133, 0.2673597, 0.05482465, -26.64634, 0.2542903, 0.03330228, -304.8436, 0.3973314],
  'BBi-bas<-BBi-gel': [1, 0.06983329, -1184.593, 0.08742065, 0.0240528, -2526.069, 0.1479149, 0.006534014, -12165.92, 0.2029002, 0.1142872, -416.8058, -0.03285549],
  'BBi-bas<-BBi-sol': [1, 0.06992142, -1036.153, 0.09166263, 0.0319672, -2478.645, 0.1784789, 0.00769929, -4477.944, 0.2313976, 0.1134538, -376.5693, -0.03556158],
  'BBi-bas<-BBi-bnd': [3, 0.25, 0.01563289, 6.835241, 0.3650127, 1.836431, 0.2704326, 0.03526641, 8.848307, 0.08170446],
  'BBi-bas<-BBi-seq': [1, 0.02216691, -394.8869, 0.1127097, 0.1350273, -169.1389, 0.2650755, 0.00726001, -470.5375, 0.4806218, 0.07464973, -133.0544, -0.05250502],
  'BBi-sec<-BBi-gel': [1, 0.1752043, -381.9491, 0.158163, 0.01589757, -1162.612, 0.3911134, 0.2871758, -111.7757, -0.0161215, 0.08175596, -528.7388, 0.2770516],
  'BBi-sec<-BBi-sol': [1, 0.09272864, -318.2638, 0.1371357, -0.01108624, -1824.432, 0.1549195, 0.2892277, -29.22377, 0.009140343, 0.02527141, -353.2921, 0.387492],
  'BBi-sec<-BBi-bnd': [3, 0.5, 0.2663222, 1.247913, 0.395056, 2.595532, 0.2349517, 0.09375073, 6.073588, 0.08536083],
  'BBi-sec<-BBi-seq': [1, 0.09811496, -390.2333, 0.1676271, 0.01968822, -859.2531, 0.2946132, 0.1328864, -163.7452, -8.938576e-3, 0.03513111, -3222.807, -0.0542812],
  'bbe-sec<-bbe-gel': [1, 0.04305129, -394.2624, 0.4336853, 0.07326854, -152.643, 0.3898331, 0.1704198, -44.87835, 0.2104057, 0.005133497, -741.4282, 0.2740834],
  'bbe-sec<-bbe-sol': [1, 0.007152097, -1449.924, 0.3744433, 0.1897075, -30.60365, 0.329908, 0.05060541, -113.7795, 0.3189578, -4.889305e-3, -580.5995, 0.1890273],
  'bbe-sec<-bbe-bnd': [3, 0.4, 0.2330375, 1.606937, 0.6944076, 1.617835, 0.2810387, -0.02880487, 7.887438, 0.240524],
  'bbe-sec<-bbe-seq': [1, 0.06082015, -217.5413, 0.4092593, 0.09193827, -25.71987, 0.1000563, 0.0118824, -1568.605, 0.1839267, 0.02114782, -417.2795, 0.1039428],
  'bbe-sec<-AI': [1, 9.583849e-5, -792.4591, 0.2191848, 9.621604e-4, -133.7145, -0.1589139, 3.212547e-4, -309.0881, 0.06662389, 1.811347e-5, -1487.62, 0.3003989],
};
export const AF66_ELECTRON = {
  'ET1-bas<-ET1-sur': [1, 0.065053, -354.406, 2.014387, 0.036335, -991.429, 2.125458, 0.019842, -24.6374, 1.580302, 0.046065, -100.628, 1.835525],
  'ET2-bas<-ET2-sur': [1, 0.009434, -18.2563, 1.521565, 0.010917, -1134.08, 2.108072, 0.030823, -80.0744, 1.78897, 0.039695, -234.006, 1.959684],
  'ET2-bas<-ET2-bnd': [3, 0.1818, 0.012801, 0.790806, 13.45734, 1.162724, 53.70593, -0.00902, 11.51802, 10.27388],
  'ET2-bas<-ET2-seq': [1, 0.036493, -17.099, 1.957065, 0.012268, -490.983, 2.372073, 0.013901, -80.9776, 1.766727, 0.121082, -89.8524, 2.286418],
  'BBi-bas<-BBi-gel': [1, 0.022208, -23.543, 1.526898, 0.055161, -678.604, 2.076011, 0.052048, -89.4917, 1.772334, 0.077509, -288.868, 1.957359],
  'BBi-bas<-BBi-sol': [1, 0.024444, -23.3706, 1.562825, 0.028798, -705.929, 2.123317, 0.057382, -87.789, 1.808263, 0.083806, -281.914, 1.99725],
  'BBi-bas<-BBi-bnd': [3, 0.25, 0.023337, 0.867548, 14.66598, 1.381178, 33.94687, -0.0168, 8.056959, 11.69128],
  'BBi-bas<-BBi-seq': [1, 0.084383, -43.1191, 1.918628, 0.117906, -169.24, 2.234064, 0.001411, -86.001, 1.263035, 0.009699, -16.5773, 1.414384],
  'BBi-bas<-AI': [2, 0.000393, -400.456, -1.80563, 777.7234, -1.732, 3.733329, -10.2482, -379.908, -1.66248, 0.287203],
  'BBi-sec<-BBi-gel': [1, 0.219072, -180.389, 2.123581, 0.072201, -21.9379, 1.724434, 0.010307, -1090.27, 2.323796, 0.165766, -67.5677, 1.939],
  'BBi-sec<-BBi-sol': [1, 0.190302, -131.282, 2.113636, 0.061225, -18.8215, 1.792023, 0.049712, -394.019, 2.350691, 0.15794, -46.6822, 1.963819],
  'BBi-sec<-BBi-bnd': [3, 0.5, 0.07042, 0.886749, 19.05802, 1.54244, 27.37533, -0.03274, 6.968345, 13.33513],
  'BBi-sec<-BBi-seq': [1, -0.20809, -572.72, 2.174599, 0.278314, -476.006, 2.168483, 0.125274, -69.2237, 1.918443, 0.058332, -21.8086, 1.689866],
  'BBi-sec<-AI': [2, 0.000786, -859.74, -1.61489, 1689.772, -1.57364, 124.4556, -25.1186, -832.213, -1.53368, 0.287178],
  'bbe-sec<-bbe-gel': [1, 0.112968, -358.216, 2.393708, 0.131671, -170.786, 2.268427, 0.015445, -18.7936, 1.870242, 0.101948, -60.4808, 2.088622],
  'bbe-sec<-bbe-sol': [1, 0.025629, -538.817, 2.535345, 0.175729, -48.4179, 2.257859, 0.018913, -16.7686, 2.055972, 0.071751, -189.165, 2.344306],
  'bbe-sec<-bbe-bnd': [3, 0.4, 0.048063, 0.711481, 149.3354, 1.621245, 45.538, -0.03676, 6.960692, 22.59052],
  'bbe-sec<-bbe-seq': [1, 0.059129, -139.756, 2.153796, 0.059699, -53.6711, 2.02631, 0.010356, -16.8711, 1.82904, 0.085985, -306.92, 2.369979],
  'bbe-sec<-AI': [2, 0.001772, -2.64463, -16.7712, 1.116624, -2.11559, 3.291514, -46.8517, -1.27588, -2.11622, 0.04],
};
/** One of Table H.7's functions at the energy x (MeV): row = [function, a1, a2, ...]. */
export function af66(row, x) {
  if (!(x > 0)) return 0;
  const a = row, L = Math.log10;
  let af;
  if (a[0] === 1) {
    af = 0;
    for (let k = 1; k <= 10; k += 3) {
      const u = L(x) + a[k + 2];
      if (u > 0) af += a[k] * Math.exp(a[k + 1] * L(u) ** 2); // below 10^-a[k+2] MeV the term has run out
    }
  } else if (a[0] === 2) {
    af = (1 - Math.exp(-((x / a[10]) ** 20))) * a[1] * (1 + a[2] * Math.exp(a[3] * x) + a[4] * Math.exp(a[5] * x) + a[6] * Math.exp(a[7] * x) + a[8] * Math.exp(a[9] * x));
  } else {
    const g = (amp, w, c) => (x < 1 / c ? amp : amp * Math.exp(-((w * L(c * x)) ** 2)));
    af = g(a[2], a[3], a[4]) + g(a[1] - a[2], a[5], a[6]) + a[7] * Math.exp(-((a[8] * L(a[9] * x)) ** 2));
  }
  return af > 0 ? af : 0;
}

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
  const mS = P.masses.sources;
  /* The targets' masses: the file's, with the newborn's alveolar region as
     the database has it (AI_NEWBORN_60) unless dcal; set by see(). */
  const fileTargets = P.masses.targets;
  const ownTargets = phantom === 'A00' ? { ...fileTargets, AI: AI_NEWBORN_60 } : fileTargets;
  let mT = ownTargets;
  /* The mass of the body's tissues: the database's (BODY_TISSUES_60), or with
     dcal the phantom file's own; set by see() for the SEE it computes. */
  const bodyTissues = (dcal) => (dcal ? mS.Body_Tis : BODY_TISSUES_60[phantom] ?? mS.Body_Tis);
  let MWB = bodyTissues(false);
  // The airways' tables of DCAL's library, used with `dcal` only (lungAf).
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

  /* Respiratory tract sources: ICRP 66's absorbed fractions by its algebraic
     functions (AF66_ALPHA, AF66_ELECTRON), and ELALPHAF's constant fractions
     for the pairs it lists.

     Electrons from a source in the wall of the bronchi or the bronchioles
     get the fraction from AI added. The calculation behind Annex H is of one
     airway in alveolar tissue, and what its electrons do to the other
     airways is "adequately approximated by adding the surrogate calculated
     value of AF(T<-AI)" (para H21); Table H.2 has the sum, the functions the
     one airway. Without it 90Y's bronchiolar dose is 0.934 of the ICRP's
     database of dose coefficients and its bronchial 0.983; with it 1.0002
     and 0.998-0.999.

     With `tables` (set by see() for dcal) the tables of DCAL's library as
     SEECAL takes them, straight lines between the tabulated energies. */
  let tables = false;
  const AIRWAY_WALL = /^(BBi|bbe)-/;
  function lungAf(t, s, energy, c, recoil) {
    if (recoil) return (t === s && (s === 'AI' || s === 'LN-Th' || s === 'LN-ET')) ? 1 : 0;
    let af = 0;
    if (tables) {
      const table = c === ALPHA ? lungA : lungE;
      const p = table.get(`${t}<-${s}`);
      if (p) af = lerp(table.energies, p, energy);
    } else {
      const rows = c === ALPHA ? AF66_ALPHA : AF66_ELECTRON;
      const row = rows[`${t}<-${s}`];
      if (row) {
        af = af66(row, energy);
        if (c !== ALPHA && AIRWAY_WALL.test(s)) af += af66(rows[`${t}<-AI`], energy);
      }
    }
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
   * @param {{Z?: number, dcal?: boolean, boneInOther?: boolean}} [opt]  the atomic number, for
   *   spontaneous fission; dcal: as DCAL's SEECAL has it, the photon SAF itself linear in
   *   energy (interpPhoton), the exact joules per MeV (MEV_DCAL) and the mass
   *   of the body's tissues of its REGMASS file, the airways' absorbed fractions
   *   from its tables, linear in energy, and beta spectra by the trapezoidal
   *   rule; boneInOther: the mineral bone
   *   stays in Other although the model names bone regions (tellurium:
   *   model60.js BONE_IN_OTHER_60)
   * @returns {Float64Array[]}  see[t][s], Sv per transformation
   */
  function see(em, A, sources, explicit, targets = TARGETS_60, opt = {}) {
    MWB = bodyTissues(!!opt.dcal);
    mT = opt.dcal ? fileTargets : ownTargets;
    tables = !!opt.dcal;
    const r = em.r || {};
    const photons = (r.p || []).filter(([e]) => e >= 0.01);
    const softPh = (r.p || []).filter(([e]) => e < 0.01).reduce((s, [e, y]) => s + e * y, 0);
    const betas = r.b || [], elec = r.e || [], alphas = r.a || [];
    const safLinear = !!opt.dcal, mev = opt.dcal ? MEV_DCAL : MEV;
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
      for (const [e, y] of photons) sum += y * e * interpPhoton(E, v, e, safLinear);
      return sum;
    };
    // Lung sources: electrons against the beta spectrum and the lines.
    const lungNp = (t, s) => {
      let sum = 0;
      for (const [e, y] of elec) sum += y * e * lungAf(t, s, e, E_LO, false);
      if (em.bs && betas.length) sum += spectrumAf(em.bs, (e) => lungAf(t, s, e, E_LO, false), !!opt.dcal);
      else for (const [e, y] of betas) sum += y * e * lungAf(t, s, e, E_LO, false);
      sum += softPh * lungAf(t, s, 0.005, E_LO, false);
      let a = 0;
      for (const [e, y] of alphas) a += y * e * lungAf(t, s, e, ALPHA, false);
      a += recoilE * lungAf(t, s, 0, ALPHA, true);
      return { e: sum, a };
    };

    // Other: equation (9) with the explicit regions; mineral bone left out of
    // Other as a whole when any bone region is named (but with boneInOther);
    // heart contents never in it.
    const boneNamed = !opt.boneInOther && [...explicit].some((x) => BONE_SOURCES.has(x));
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
        out[i][k] = mev * (ph + np + 20 * al);
      });
    });
    return out;
  }

  return { see, masses: P.masses, bodyTissues, phantom, targets: TARGETS_60 };
}

/* The photon SAF of a 12-point row at energy e: the energy the photon leaves
   per kilogram, E SAF(E), linear in energy between the tabulated energies
   (Publication 72's coefficients have it so), or with `saf` the SAF itself
   linear in energy (DCAL's SEECAL, 8.4 and that of 1993); held at the end
   values outside 10 keV - 4 MeV. */
function interpPhoton(E, v, e, saf = false) {
  if (saf) return lerp(E, v, e);
  const n = E.length;
  if (e <= E[0]) return v[0];
  if (e >= E[n - 1]) return v[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (E[m] <= e) lo = m; else hi = m; }
  return (E[lo] * v[lo] + (E[hi] * v[hi] - E[lo] * v[lo]) * (e - E[lo]) / (E[hi] - E[lo])) / e;
}

function indexLungAF(t) {
  const m = new Map();
  for (const p of t.pairs) m.set(`${p.target}<-${p.source}`, p.af);
  m.energies = t.energies;
  return m;
}

/* A beta spectrum, tabulated at points, against an absorbed fraction that
   depends on the energy: MeV absorbed per transformation.

   As the ICRP's coefficients have it, the spectrum is a set of groups, one
   for each interval of the table: as many electrons as the interval's width
   times the mean of N at its two ends, all of the energy of its middle,
   with the absorbed fraction of that energy. Where the fraction is one that
   comes to 1.0025-1.0058 times the mean energy of the decay data, since the
   middle of an interval is not where its electrons' mean energy lies, and
   that is what the ICRP's database of dose coefficients gives the alveolar
   region and the lymph nodes of every beta emitter: 63Ni 1.0053, 14C
   1.0035, 45Ca 1.0052, 147Pm 1.0056, 36Cl 1.0027, 32P 1.0027, 90Y 1.0032 of
   the mean energy, and this sum 1.0056, 1.0035, 1.0051, 1.0058, 1.0028,
   1.0027, 1.0034 (README). The whole body's and the organs' doses, which go
   by the mean energy, show no such excess.

   With `trapezoid` (for `dcal`), the integral of N(E) E AF(E) dE by the
   trapezoidal rule on the tabulated grid, which gives the mean energy within
   0.15 %. */
export function spectrumAf(bs, af, trapezoid = false) {
  const [es, ns] = bs;
  let sum = 0;
  if (!trapezoid) {
    for (let i = 1; i < es.length; i++) {
      const mid = 0.5 * (es[i - 1] + es[i]);
      sum += 0.5 * (ns[i - 1] + ns[i]) * (es[i] - es[i - 1]) * mid * af(mid);
    }
    return sum;
  }
  for (let i = 1; i < es.length; i++) {
    const a = ns[i - 1] * es[i - 1] * af(es[i - 1]);
    const b = ns[i] * es[i] * af(es[i]);
    sum += 0.5 * (a + b) * (es[i] - es[i - 1]);
  }
  return sum;
}
