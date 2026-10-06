/*
  Electron capture by atomic subshell: where the vacancies of an
  electron-capture branch are made, for the X-rays and Auger electrons that
  follow (atomic-relax.js).

  ENSDF gives the K, L and M+ capture fractions of most branches (CK, CL,
  CM+ on the EC record's continuation, computed by the evaluators' program
  LOGFT). Where it does not, they follow Behrens and Jänecke's theory as
  Dillman (ORNL/TM-6689, 1980, eq. 23) wrote it: for a branch of
  transition energy E and shape order n, capture from a j = 1/2 subshell X
  goes as

      lambda_X  ~  (E - B_X)^(2(n+1)) beta_X^2 N_X B_X

  with the bound-electron amplitude beta_X, occupancy N_X and exchange and
  overlap factor B_X. Divided out of LOGFT's own values, those factors
  relative to the K shell are smooth functions of Z (capture.json, made by
  scripts/gen-dose-capture.mjs from an ENSDF release: rL and rM+ to 0.5 %).

  ENSDF stops at L and M+; the vacancies are wanted by subshell:
    L  -> L1 and L2 (2s1/2 and 2p1/2; 2p3/2 only for unique transitions,
          left out here) in the ratio of the Dirac amplitudes at the nucleus
          of a hydrogen-like atom of charge Z - 3.5;
    M+ -> M and N+ by Dillman's Table 4 (N+/M from Robinson 1965) with the
          two shells' neutrino energies, M into M1 and M2 and N+ into N1
          and N2 the same way as L, a fifth of N+ to O1.
  Vacancies further out give radiations of a few hundred eV at most.

  Where a branch gives its total only, or no intensity at all, the share of
  positrons in it comes from the rate functions of the two modes
  (positronFraction).
*/
import { betaShape, lnAbsGamma, ME as ME_MEV } from './beta-spectrum.js';

const ALPHA = 1 / 137.035999;
const ME_KEV = 510.99895;

/* Dillman 1980, Table 4: N+/M capture ratios by Z (0 up to Z = 18). */
const NPLUS_M = (() => {
  const t = new Float64Array(105);
  const set = (a, b, v) => { for (let z = a; z <= b; z++) t[z] = v; };
  set(19, 19, 0.016); set(20, 23, 0.032); set(24, 24, 0.016); set(25, 28, 0.032); set(29, 29, 0.016);
  [[30, 0.032], [31, 0.048], [32, 0.064], [33, 0.080], [34, 0.096], [35, 0.112]].forEach(([z, v]) => { t[z] = v; });
  set(36, 38, 0.128);
  [[39, 0.144], [40, 0.160], [41, 0.165], [42, 0.170], [43, 0.176], [44, 0.182], [45, 0.188], [46, 0.195], [47, 0.201], [48, 0.207],
    [49, 0.213], [50, 0.219], [51, 0.225], [52, 0.232], [53, 0.238], [54, 0.244], [55, 0.250], [56, 0.255], [57, 0.260], [58, 0.264]].forEach(([z, v]) => { t[z] = v; });
  set(59, 69, 0.269);
  [[70, 0.272], [71, 0.274], [72, 0.277], [73, 0.280], [74, 0.283], [75, 0.285], [76, 0.288], [77, 0.291], [78, 0.294], [79, 0.296], [80, 0.299],
    [81, 0.302], [82, 0.305], [83, 0.307], [84, 0.308], [85, 0.309], [86, 0.311], [87, 0.313], [88, 0.314], [89, 0.315], [90, 0.316], [91, 0.317],
    [92, 0.318], [93, 0.319], [94, 0.321], [95, 0.322], [96, 0.323], [97, 0.324], [98, 0.325], [99, 0.326], [100, 0.327], [101, 0.328],
    [102, 0.329], [103, 0.330], [104, 0.331]].forEach(([z, v]) => { t[z] = v; });
  return t;
})();

/**
 * Density at the nucleus of the p1/2 (small component) over the s1/2 (large
 * component) state of principal quantum number n in a hydrogen-like atom of
 * charge Zeff: [(1 - e)/(1 + e)] (N + 1)/(N - 1), e = E/mc^2, N the apparent
 * principal quantum number (Berestetskii, Lifshitz and Pitaevskii, sec. 36).
 */
export function p12OverS12(n, Zeff) {
  const aZ = ALPHA * Math.max(1, Zeff);
  const g = Math.sqrt(1 - aZ * aZ);
  const nr = n - 1;
  const N = Math.sqrt(n * n - 2 * nr * (1 - g));
  const e = 1 / Math.sqrt(1 + (aZ * aZ) / ((nr + g) * (nr + g)));
  return ((1 - e) / (1 + e)) * ((N + 1) / (N - 1));
}

/** rL or rM+ at Z from the table, interpolated in Z where the release has no branch to fit. */
function factor(table, key, Z) {
  const at = (z) => table[z]?.[key];
  if (at(Z) > 0) return at(Z);
  let lo = Z - 1, hi = Z + 1;
  while (lo > 0 && !(at(lo) > 0)) lo--;
  while (hi < 120 && !(at(hi) > 0)) hi++;
  if (at(lo) > 0 && at(hi) > 0) return at(lo) + (at(hi) - at(lo)) * (Z - lo) / (hi - lo);
  return at(lo) > 0 ? at(lo) : at(hi) > 0 ? at(hi) : 0;
}

/**
 * Capture fractions by subshell for one branch.
 *
 * @param {number} Z       daughter atomic number
 * @param {number} Et      transition energy (Q + E_parent - E_level), keV
 * @param {number} n       shape order (0 allowed, 1 first unique, ...)
 * @param {object} rec     the EC record (its continuation fields CK, CL, CM+ are used when given)
 * @param {object} atom    {binding: {K, L1, L2, M1, M2, N1, N2: keV}}
 * @param {object} table   capture.json's table {Z: {rL, rM}}
 * @param {object} [qAtom]  the atom whose binding energies set the neutrino
 *                          energies: the daughter's (the default, as LOGFT
 *                          and ENSDF take them) or the parent's, which is what
 *                          EDISTR04 took for ICRP 107 (Np-235's K X-rays are
 *                          a third of LOGFT's for that alone)
 * @returns {object|null} {K, L1, L2, M1, M2, N1, N2, O1} adding to 1
 */
export function captureFractions(Z, Et, n, rec, atom, table, qAtom = atom) {
  const B = qAtom.binding;
  const q = (s) => (B[s] > 0 && Et > B[s] ? Et - B[s] : 0);
  const num = (s) => { const v = Number(String(s ?? '').trim()); return Number.isFinite(v) ? v : NaN; };
  let pK, pL, pM;
  const CK = num(rec?.cont?.CK), CL = num(rec?.cont?.CL), CM = num(rec?.cont?.['CM+'] ?? rec?.cont?.CM);
  if (CK >= 0 && CL >= 0 && (CK > 0 || CL > 0)) {
    pK = CK; pL = CL; pM = CM >= 0 ? CM : Math.max(0, 1 - CK - CL);
  } else {
    const pw = 2 * (n + 1);
    pK = q('K') ** pw;
    pL = factor(table, 'rL', Z) * q('L1') ** pw;
    pM = factor(table, 'rM', Z) * q('M1') ** pw;
    if (!(pK + pL + pM > 0)) {
      // Below every threshold the tables know: what is left is the outermost shells.
      return Et > 0 ? { N1: 1 } : null;
    }
  }
  const sum = pK + pL + pM;
  if (!(sum > 0)) return null;
  pK /= sum; pL /= sum; pM /= sum;
  const out = {};
  const put = (s, x) => { if (x > 0) out[s] = (out[s] || 0) + x; };
  put('K', pK);
  // L1 : L2 from the Dirac amplitudes, unless L2 is closed to the branch.
  const l2 = q('L2') > 0 ? p12OverS12(2, Z - 3.5) * (q('L2') / Math.max(q('L1'), 1e-9)) ** (2 * (n + 1)) : 0;
  put('L1', pL / (1 + l2)); put('L2', pL * l2 / (1 + l2));
  // Dillman's N+/M ratio takes the neutrino energies of the two shells as
  // equal (his eq. 25); near the threshold they are not (Ho-163 captures
  // 2.8 keV over the N1 edge and 0.8 keV over M1), so they are put back.
  const pw = 2 * (n + 1);
  const qM = q('M1'), qN = B.N1 > 0 ? q('N1') : qM;
  const nm = qM > 0 ? NPLUS_M[Math.min(104, Math.max(0, Math.round(Z)))] * (qN / qM) ** pw : (qN > 0 ? Infinity : 0);
  const pMM = Number.isFinite(nm) ? pM / (1 + nm) : 0, pN = pM - pMM;
  const m2 = B.M2 > 0 && q('M2') > 0 && qM > 0 ? p12OverS12(3, Z - 12) * (q('M2') / qM) ** pw : 0;
  put('M1', pMM / (1 + m2)); put('M2', pMM * m2 / (1 + m2));
  if (pN > 0) {
    const n2 = B.N2 > 0 && q('N2') > 0 && qN > 0 ? p12OverS12(4, Z - 30) * (q('N2') / qN) ** pw : 0;
    // N+ is N and the shells beyond: a fifth to O where the atom has one.
    const o = B.O1 > 0 && q('O1') > 0 ? 0.2 : 0;
    if (B.N1 > 0) { put('N1', pN * (1 - o) / (1 + n2)); put('N2', pN * (1 - o) * n2 / (1 + n2)); put('O1', pN * o); } else put('M1', pN);
  }
  return out;
}

const fact = (n) => (n <= 1 ? 1 : n * fact(n - 1));

/**
 * The share of positrons among the decays of one capture branch, from the
 * statistical rate functions of the two modes (Bambynek et al., Rev. Mod.
 * Phys. 49, 77, 1977, sec. II), in units of the electron mass and with the
 * same n-th unique shape for both:
 *
 *   f(beta+) = int p W (W0 - W)^2 S_n dW     (beta-spectrum.js, as the spectrum)
 *   f(EC)    = f_K / P_K,   f_K = (pi/2) q_K^(2n+2) g_K(R)^2 / (2n+1)!
 *
 * with q_K the neutrino energy of K capture, g_K the large component of a
 * hydrogen-like 1s state at the nuclear radius R of beta-spectrum.js (Eq
 * 19), for the charge Z - 0.3 (the other 1s electron's screening), and P_K
 * the K share of the capture (captureFractions).
 *
 * @param {number} Z    daughter atomic number
 * @param {number} A    mass number
 * @param {number} Et   transition energy (Q + E_parent - E_level), keV
 * @param {number} n    shape order
 * @param {number} pK   K share of the capture
 * @param {number} BK   K binding energy of the daughter, keV
 * @returns {number} positrons per decay of the branch, 0 below 1022 keV
 */
export function positronFraction(Z, A, Et, n, pK, BK) {
  const E0 = Et - 2 * ME_KEV;
  if (!(E0 > 0)) return 0;
  if (!(pK > 0) || !(Et > BK)) return 1;
  const fPlus = betaShape({ Z, A, E0: E0 / 1000, n, positron: true }, { exact: true }).norm / ME_MEV;
  const R = 0.002908 * Math.cbrt(A) - 0.002437 / Math.cbrt(A);
  const aZ = ALPHA * Z, g = Math.sqrt(1 - aZ * aZ);
  const gK2 = Math.exp((2 * g + 1) * Math.log(2 * ALPHA * (Z - 0.3)) + Math.log((1 + g) / 2) - lnAbsGamma(2 * g + 1, 0) + (2 * g - 2) * Math.log(R));
  const fK = (Math.PI / 2) * ((Et - BK) / ME_KEV) ** (2 * n + 2) * gK2 / fact(2 * n + 1);
  return fPlus / (fPlus + fK / pK);
}
