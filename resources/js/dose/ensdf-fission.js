/*
  Radiations of spontaneous fission, per decay of the parent, which ENSDF
  does not give: it names the fission branch and nothing more. These are
  EDISTR04's formulas (Endo, Yamaguchi and Eckerman, JAERI 1347, 2005,
  section 3.2; ICRP Publication 107, Tables 2.4 and 2.5), in terms of the
  fission branch BF, the fissioning nucleus's Z and A, the prompt neutrons
  per fission nu-bar and the Watt parameters a and b of their spectrum:

    fission fragments  2 BF at 0.05945 Z^2/A^(1/3) + 3.65 MeV each (eq. 3.4,
                       Viola et al.'s kinetic energy shared equally)
    prompt neutrons    BF nu at 0.25 a^2 b + 1.5 a MeV (eqs 3.6-3.7, Watt)
    prompt gammas      E_total = (2.51 - 1.13e-5 Z^2 sqrt(A)) nu + 4.0 MeV
                       per fission, at -1.33 + 119.6 Z^(1/3)/A MeV each
                       (Valentine, eqs 3.11-3.14)
    delayed gammas     0.2102 (5.98 + 92A/236 - Z)^2 BF at 0.9578 MeV
                       (Dillman and Jones's chain length, eq. 3.17)
    delayed betas      (5.98 + 92A/236 - Z) BF at 0.2058 (5.98 + 92A/236 - Z)
                       MeV (eqs 3.19-3.20)

  ICRP 107 writes the prompt and delayed gammas as spectra; here they are
  lines at their mean energies, which the dose to tissue hardly tells
  apart from the spectra (they carry a few per cent of the fission energy;
  the fragments carry most of it). nu-bar, a and b are EDISTR04's for the
  28 nuclides of its Table 3.6; for others, nu-bar from a straight line in
  A through that table and a and b of its nearest element.
*/

/* JAERI 1347 Table 3.6 (ICRP 107 Table 2.5): nu-bar, Watt a (MeV), b (1/MeV). */
export const WATT = {
  'U-238': [2.010, 0.648318, 6.81057], 'Pu-236': [2.130, 0.988270, 3.10386], 'Pu-238': [2.220, 0.847833, 4.16933],
  'Pu-240': [2.160, 0.794930, 4.68927], 'Pu-242': [2.150, 0.819150, 4.36668], 'Pu-244': [2.300, 0.694716, 6.00370],
  'Cm-240': [2.390, 1.07168, 2.69829], 'Cm-242': [2.520, 0.887353, 3.89176], 'Cm-244': [2.690, 0.902523, 3.72033],
  'Cm-245': [2.870, 0.911919, 3.62393], 'Cm-246': [3.180, 0.878224, 3.88585], 'Cm-248': [3.110, 0.808387, 4.53623],
  'Cm-250': [3.310, 0.734482, 5.43559], 'Cf-246': [3.12, 1.0263, 2.933], 'Cf-248': [3.340, 1.027720, 2.93228],
  'Cf-249': [3.410, 1.0263, 2.933], 'Cf-250': [3.530, 1.0263, 2.933], 'Cf-252': [3.765, 1.0250, 2.926],
  'Cf-254': [3.890, 1.0263, 2.933], 'Es-253': [3.930, 0.825, 4.65], 'Es-254': [3.950, 0.825, 4.65],
  'Es-254m': [3.950, 0.825, 4.65], 'Es-255': [3.970, 0.825, 4.65], 'Fm-252': [3.96, 0.825, 4.65],
  'Fm-254': [3.960, 0.825, 4.65], 'Fm-255': [3.730, 0.825, 4.65], 'Fm-256': [4.010, 0.825, 4.65], 'Fm-257': [3.850, 0.825, 4.65],
};

const ELEMENT_Z = { U: 92, Np: 93, Pu: 94, Am: 95, Cm: 96, Bk: 97, Cf: 98, Es: 99, Fm: 100, Md: 101, No: 102, Lr: 103 };

/** nu-bar, a and b for a fissioning nuclide, and whether they are EDISTR04's own or estimated. */
export function fissionParameters(name, Z, A) {
  if (WATT[name]) return { nu: WATT[name][0], a: WATT[name][1], b: WATT[name][2], estimated: false };
  // nu-bar: least squares through Table 3.6 in A; Watt parameters of the nearest element listed.
  const pts = Object.entries(WATT).map(([n, [nu]]) => [Number(/-(\d+)/.exec(n)[1]), nu]);
  const mA = pts.reduce((s, [a]) => s + a, 0) / pts.length, mN = pts.reduce((s, [, n]) => s + n, 0) / pts.length;
  const slope = pts.reduce((s, [a, n]) => s + (a - mA) * (n - mN), 0) / pts.reduce((s, [a]) => s + (a - mA) ** 2, 0);
  let best = null, dz = Infinity;
  for (const [n, v] of Object.entries(WATT)) {
    const z = ELEMENT_Z[/^([A-Z][a-z]?)-/.exec(n)[1]];
    const d = Math.abs(z - Z) + Math.abs(Number(/-(\d+)/.exec(n)[1]) - A) / 1000;
    if (d < dz) { dz = d; best = v; }
  }
  return { nu: Math.max(1.5, mN + slope * (A - mA)), a: best[1], b: best[2], estimated: true };
}

/**
 * Fission radiations per decay: lines [E (MeV), yield, kind] with kind 'FF',
 * 'N', 'PG', 'DG' or 'BD'.
 */
export function fissionRadiations(Z, A, BF, { nu, a, b }) {
  const z2a = Z * Z / Math.cbrt(A);
  const chain = 5.98 + 92 * A / 236 - Z;
  const Epg = -1.33 + 119.6 * Math.cbrt(Z) / A;
  const Etot = (2.51 - 1.13e-5 * Z * Z * Math.sqrt(A)) * nu + 4.0;
  return [
    [0.05945 * z2a + 3.65, 2 * BF, 'FF'],
    [0.25 * a * a * b + 1.5 * a, BF * nu, 'N'],
    [Epg, BF * Etot / Epg, 'PG'],
    [0.9578, 0.2102 * chain * chain * BF, 'DG'],
    [0.2058 * chain, chain * BF, 'BD'],
  ];
}

/*
  The delayed betas as a spectrum, for the dose to the walls of the airways
  and the gut: ICRP 107 synthesised theirs from first-forbidden unique
  transitions of fragments of Z 39 and 58 (para. 36), a shape its files show
  but no report describes. Here: half the delayed betas from each of those
  two fragments, Y-95 and Ce-140 as their nuclei, each with the first
  unique shape and the end point that gives the mean energy above. That
  shape ends near 3 MeV, ICRP 107's at 4 MeV; the energy is the same.
*/
export function delayedBetaBranches(Z, A, BF, betaShape) {
  const chain = 5.98 + 92 * A / 236 - Z;
  const mean = 0.2058 * chain, Y = chain * BF;
  if (!(Y > 0) || !(mean > 0)) return [];
  return [[39, 95], [58, 140]].map(([z, a]) => {
    let lo = mean, hi = 8 * mean;
    for (let i = 0; i < 50; i++) {
      const mid = (lo + hi) / 2;
      if (betaShape({ Z: z, A: a, E0: mid, n: 1 }).mean < mean) lo = mid; else hi = mid;
    }
    return { Z: z, A: a, E0: (lo + hi) / 2, n: 1, positron: false, yield: Y / 2 };
  });
}
