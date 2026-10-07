/*
  External exposure: dose rate coefficients for a person in contaminated air,
  water or soil, from the nuclide's decay data, as Federal Guidance Reports 12
  (ICRP 60 system) and 15 (ICRP 103 system) calculate theirs. The dose rate to
  tissue T per unit concentration is the sum over the radiations emitted per
  decay of their yield times the dose rate per particle of that energy
  (FGR 15 eq. 13, FGR 12 eq. 21):

    photons          each line of 10 keV or more: the report's monoenergetic
                     coefficient, interpolated in energy by a monotone cubic
                     (PCHIP, Fritsch and Carlson 1980) in ln h against ln E,
                     zeros taken as 1E-100 (the cubic of the end interval
                     beyond 5 MeV);
    bremsstrahlung   the beta spectrum's electrons slowing down in the medium
                     (soil for the ground), FGR 12/15 Appendix C eq. C-2: per
                     electron of energy T, (T/100) ∫ S'(x, T) h(xT) dx/x over
                     x = k/T from 10 keV/T to 1, S' the scaled spectra of
                     Tables C-1-C-3 interpolated by PCHIP in x and then in ln T;
    electrons        to the skin only (70 um deep), the beta spectrum and the
                     conversion and Auger electrons: FGR 12's DOSFACTER curves,
                     interpolated as the photons; zero below each curve's first
                     energy (an electron that does not reach 70 um, or 1 m
                     above the ground).

  The beta spectrum is integrated as a PCHIP of its tabulated values; on the
  ground surface the electrons start at the surface, the photons and the
  bremsstrahlung 3 mm deep in FGR 15 (FGR 15 Appendix C, ORNL/SPR-2025/3803
  section 2.3). These reproduce FGR 15's 1252 nuclides (2025 revision) and
  FGR 12's 826 within 1 % for 99 % of the values of every tissue, geometry
  and age (resources/tests/dose_coefficients/README.md).

  With the progeny: each member in equilibrium with the parent (shorter-lived,
  and formed only from members that are) counts with its activity per becquerel
  of the parent, λi/(λi − λP) times what feeds it.
*/

/* ---- monotone cubic interpolation ------------------------------------------ */
/* The slopes of the PCHIP through (x, y): Fritsch and Carlson's monotone
   cubic with the weighted harmonic mean inside and the three-point ends of
   SLATEC's PCHIM (as SciPy's PchipInterpolator). */
function pchipSlopes(x, y) {
  const n = x.length, d = new Float64Array(n);
  if (n < 2) return d;
  const h = new Float64Array(n - 1), m = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) { h[i] = x[i + 1] - x[i]; m[i] = (y[i + 1] - y[i]) / h[i]; }
  if (n === 2) { d[0] = d[1] = m[0]; return d; }
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) continue;
    const w1 = 2 * h[i] + h[i - 1], w2 = h[i] + 2 * h[i - 1];
    d[i] = (w1 + w2) / (w1 / m[i - 1] + w2 / m[i]);
  }
  const end = (h0, h1, m0, m1) => {
    let s = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1);
    if (Math.sign(s) !== Math.sign(m0)) s = 0;
    else if (Math.sign(m0) !== Math.sign(m1) && Math.abs(s) > 3 * Math.abs(m0)) s = 3 * m0;
    return s;
  };
  d[0] = end(h[0], h[1], m[0], m[1]);
  d[n - 1] = end(h[n - 2], h[n - 3], m[n - 2], m[n - 3]);
  return d;
}
/* The interval of t in x (the end ones beyond the ends) and the Hermite basis
   there: value = b[0] y[i] + b[1] d[i] + b[2] y[i+1] + b[3] d[i+1]. */
function hermiteAt(x, t) {
  const n = x.length;
  let i = 0;
  if (t >= x[n - 1]) i = n - 2;
  else if (t > x[0]) { let hi = n - 1; while (hi - i > 1) { const k = (i + hi) >> 1; if (x[k] <= t) i = k; else hi = k; } }
  const h = x[i + 1] - x[i], s = (t - x[i]) / h, s2 = s * s, s3 = s2 * s;
  return { i, b: [2 * s3 - 3 * s2 + 1, (s3 - 2 * s2 + s) * h, -2 * s3 + 3 * s2, (s3 - s2) * h] };
}
const hermite = (y, d, { i, b }) => b[0] * y[i] + b[1] * d[i] + b[2] * y[i + 1] + b[3] * d[i + 1];
function pchip(x, y) {
  const d = pchipSlopes(x, y);
  return (t) => hermite(y, d, hermiteAt(x, t));
}

/* Values of a quantity at energies, interpolated by PCHIP in ln-ln (zeros as
   1E-100, as FGR 15 took them): its ln values and their slopes, so that one
   basis serves every tissue at an energy. */
const FLOOR = 1e-100;
class LogLog {
  constructor(E, v) {
    this.lx = Float64Array.from(E, Math.log);
    this.ly = Float64Array.from(v, (y) => Math.log(Math.max(y, FLOOR)));
    this.d = pchipSlopes(this.lx, this.ly);
  }
  basis(e) { return hermiteAt(this.lx, Math.log(e)); }
  at(e) { return Math.exp(hermite(this.ly, this.d, this.basis(e))); }
  atBasis(bs) { return Math.exp(hermite(this.ly, this.d, bs)); }
}

/* ---- geometries -------------------------------------------------------------- */
export const GEOMETRIES = ['air', 'water', 'surface', 'soil1', 'soil5', 'soil15', 'soilInf'];
/* Each geometry: its unit of concentration, the medium the electrons slow
   down in, and the skin curve of its electrons. */
export const GEOMETRY = {
  air: { per: 'm3', medium: 'air', skin: 'air' },
  water: { per: 'm3', medium: 'water', skin: 'water' },
  surface: { per: 'm2', medium: 'soil', skin: 'surface' },
  soil1: { per: 'm3', medium: 'soil', skin: 'soil' },
  soil5: { per: 'm3', medium: 'soil', skin: 'soil' },
  soil15: { per: 'm3', medium: 'soil', skin: 'soil' },
  soilInf: { per: 'm3', medium: 'soil', skin: 'soil' },
};
/* The geometries of external exposure, as the route's forms: the reports'
   (FGR 12 for the ICRP 60 system, FGR 15 for the ICRP 103 one). FGR 15 puts
   the ground's activity 3 mm deep, for its roughness; FGR 12 at the surface. */
export function externalForms(system) {
  return [
    ['air', 'Submersion in air (a semi-infinite cloud)'],
    ['water', 'Immersion in water'],
    ['surface', system === '60' ? 'Ground surface (a smooth plane)' : 'Ground surface (3 mm deep, for its roughness)'],
    ['soil1', 'Soil, to 1 cm deep'],
    ['soil5', 'Soil, to 5 cm deep'],
    ['soil15', 'Soil, to 15 cm deep'],
    ['soilInf', 'Soil, infinitely deep'],
  ].map(([key, label], i) => ({ key, label, default: i === 0, spec: { geometry: key } }));
}

/* The page's ages (days) and the reports' phantoms. */
export const PHANTOM_OF_AGE = { 100: 'newborn', 365: '1', 1825: '5', 3650: '10', 5475: '15', 7300: 'adult' };

/* ---- bremsstrahlung -------------------------------------------------------- */
/* Photons of 10 keV and more count (the reports' lowest energy); the grid of
   photon and electron energies, the same in ln for both, from 10 keV to 20 MeV
   in steps of 1/600 of the range, so that every k = xT of the integral over x
   is a point of the grid. */
const KMIN = 0.01, KMAX = 20, NGRID = 600;
const DLN = Math.log(KMAX / KMIN) / NGRID;
const GRID = Float64Array.from({ length: NGRID + 1 }, (_, j) => KMIN * Math.exp(j * DLN));

/* For a slowing-down medium: W[t][i], the weight of h(k_i) in the bremsstrahlung
   dose of an electron of energy T_t, (T/100) S'(k_i/T, T) Δln x with the
   trapezoid's halves at the ends; S' by PCHIP in k/T within each row of the
   table (0 at k/T = 1), then by PCHIP in ln T across the rows (held at the
   table's ends, 1 keV and 10 MeV). */
function bremsWeights(tab) {
  const xs = [...tab.kt, 1];
  const rows = tab.S.map((r) => { const y = [...r, 0]; return { y, d: pchipSlopes(xs, y) }; });
  const lT = tab.T.map((t) => Math.log(t / 1000));
  // x = k_i/T_t = exp(-(t - i) Δ) takes NGRID + 1 values: S' of the rows at
  // each, and the PCHIP across the rows through them, once.
  const cols = [];
  for (let m = 0; m <= NGRID; m++) {
    const bx = hermiteAt(xs, Math.exp(-m * DLN));
    const y = rows.map((r) => hermite(r.y, r.d, bx));
    cols.push({ y, d: pchipSlopes(lT, y) });
  }
  const W = [];
  for (let t = 0; t <= NGRID; t++) {
    const T = GRID[t], w = new Float64Array(t + 1);
    const bT = hermiteAt(lT, Math.min(Math.max(Math.log(T), lT[0]), lT[lT.length - 1]));
    for (let i = 0; i <= t && t > 0; i++) {
      const c = cols[t - i];
      w[i] = (T / 100) * Math.max(hermite(c.y, c.d, bT), 0) * DLN * (i === 0 || i === t ? 0.5 : 1);
    }
    W.push(w);
  }
  return W;
}

/* ---- the reports' data ------------------------------------------------------- */
export class External {
  /** @param {object} data  fgr12.json or fgr15.json (scripts/gen-dose-external.mjs) */
  constructor(data) {
    this.data = data;
    this.tissues = data.tissues;
    this.ages = data.ages;
    this.cache = new Map();
    this.brems = new Map();
    this.skins = new Map();
  }
  /** What a geometry and phantom give: per tissue the photon interpolant and
      the bremsstrahlung dose per electron on the grid. */
  response(geometry, age) {
    const key = `${geometry}|${age}`;
    if (this.cache.has(key)) return this.cache.get(key);
    const G = GEOMETRY[geometry], rows = this.data.photon[geometry]?.[age];
    if (!G || !rows) throw new Error(`no external exposure data for ${geometry} at age ${age}`);
    const W = this.bremsOf(G.medium);
    const tissues = rows.map((v) => {
      const ph = new LogLog(this.data.energies, v);
      const hk = Float64Array.from(GRID, (k) => ph.at(k));
      const B = new Float64Array(NGRID + 1);
      for (let t = 1; t <= NGRID; t++) { const w = W[t]; let s = 0; for (let i = 0; i <= t; i++) s += w[i] * hk[i]; B[t] = s; }
      return { photon: ph, B };
    });
    const r = { geometry, age, per: G.per, tissues, skin: this.skinOf(G.skin), skinIndex: this.tissues.indexOf('Skin') };
    this.cache.set(key, r);
    return r;
  }
  bremsOf(medium) {
    if (!this.brems.has(medium)) this.brems.set(medium, bremsWeights(this.data.brems[medium]));
    return this.brems.get(medium);
  }
  skinOf(name) {
    if (!this.skins.has(name)) {
      const c = this.data.skin[name];
      const f = new LogLog(c.E, c.h);
      const lo = c.E[0];
      this.skins.set(name, (e) => (e < lo ? 0 : f.at(e)));
    }
    return this.skins.get(name);
  }

  /**
   * The dose rate coefficients of one nuclide alone, per tissue of the report:
   * Sv s-1 per Bq m-3 (m-2 on the ground surface).
   * @param {{r: object, bs: Array}} em  its emissions (decay data: r.p photon lines [E MeV, yield], r.e electron lines, bs the beta spectrum [E, N])
   */
  dose(em, geometry, age) {
    const R = this.response(geometry, age);
    const n = R.tissues.length;
    const photon = new Float64Array(n), brems = new Float64Array(n);
    // Photons: the basis at each line's energy serves every tissue.
    for (const [E, y] of em?.r?.p || []) {
      if (!(E >= KMIN) || !(y > 0)) continue;
      const bs = R.tissues[0].photon.basis(E);
      for (let t = 0; t < n; t++) photon[t] += y * R.tissues[t].photon.atBasis(bs);
    }
    // The beta spectrum: one set of quadrature points for every tissue.
    const q = spectrumPoints(em?.bs);
    for (const [T, w] of q) {
      if (!(T > KMIN)) continue;
      const u = Math.log(T / KMIN) / DLN, j = Math.min(Math.floor(u), NGRID - 1), f = Math.min(u - j, 1);
      for (let t = 0; t < n; t++) { const B = R.tissues[t].B; brems[t] += w * ((1 - f) * B[j] + f * B[j + 1]); }
    }
    // Electrons, to the skin.
    let electron = 0;
    for (const [T, w] of q) electron += w * R.skin(T);
    for (const [E, y] of em?.r?.e || []) if (y > 0) electron += y * R.skin(E);
    const h = new Float64Array(n);
    for (let t = 0; t < n; t++) h[t] = photon[t] + brems[t] + (t === R.skinIndex ? electron : 0);
    return { h, photon, brems, electron, per: R.per };
  }
}

/* The beta spectrum (per MeV per decay at the tabulated energies) as a PCHIP,
   integrated by the trapezoid on each tabulated interval cut in SUB: the
   points and weights of the integral, the same for every tissue. A PCHIP of
   the spectrum, not its straight lines, is what reproduces FGR 15 where a
   spectrum ends just above the first energy of a skin curve. */
const SUB = 20;
function spectrumPoints(bs) {
  if (!bs || !bs[0] || bs[0].length < 2) return [];
  const [E, N] = bs;
  const d = pchipSlopes(E, N);
  const out = [];
  for (let i = 1; i < E.length; i++) {
    const a = E[i - 1], b = E[i], hstep = (b - a) / SUB;
    if (!(hstep > 0)) continue;
    for (let k = 0; k <= SUB; k++) {
      const e = a + k * hstep;
      const v = k === 0 ? N[i - 1] : k === SUB ? N[i] : Math.max(0, hermite(N, d, hermiteAt(E, e)));
      const w = hstep * (k === 0 || k === SUB ? 0.5 : 1) * v;
      if (w > 0) out.push([e, w]);
    }
  }
  return out;
}

/* ---- tissues and effective dose ------------------------------------------------ */
/* FGR 15: the page's tissues of the ICRP 103 system from the report's; the
   gonads and prostate/uterus the mean of the hermaphrodite phantom's two. */
const OF_15 = {
  'Red marrow': ['R-Marrow'], Colon: ['Colon'], Lung: ['Lung'], Stomach: ['St-wall'], Breast: ['Breast'], Gonads: ['Testes', 'Ovaries'],
  Bladder: ['UB-wall'], Oesophagus: ['Esophagus'], Liver: ['Liver'], Thyroid: ['Thyroid'], 'Bone surface': ['B-Surface'], Brain: ['Brain'],
  'Salivary glands': ['S-glands'], Skin: ['Skin'],
  Adrenals: ['Adrenals'], 'Extrathoracic region': ['ET-region'], Gallbladder: ['GB-wall'], Heart: ['Ht-wall'], Kidneys: ['Kidneys'],
  'Lymphatic nodes': ['Lymph'], Muscle: ['Muscle'], 'Oral mucosa': ['O-mucosa'], Pancreas: ['Pancreas'], 'Prostate/uterus': ['Prostate', 'Uterus'],
  'Small intestine': ['SI-wall'], Spleen: ['Spleen'], Thymus: ['Thymus'],
  Testes: ['Testes'], Ovaries: ['Ovaries'], Prostate: ['Prostate'], Uterus: ['Uterus'],
};
export const W_15 = {
  'Red marrow': 0.12, Colon: 0.12, Lung: 0.12, Stomach: 0.12, Breast: 0.12, Gonads: 0.08, Bladder: 0.04, Oesophagus: 0.04, Liver: 0.04,
  Thyroid: 0.04, 'Bone surface': 0.01, Brain: 0.01, 'Salivary glands': 0.01, Skin: 0.01,
};
export const REMAINDER_15 = ['Adrenals', 'Extrathoracic region', 'Gallbladder', 'Heart', 'Kidneys', 'Lymphatic nodes', 'Muscle', 'Oral mucosa',
  'Pancreas', 'Prostate/uterus', 'Small intestine', 'Spleen', 'Thymus'];

/* FGR 12: the page's tissues of the ICRP 60 system from the report's organs
   (its own oesophagus; colon 0.57 ULI + 0.43 LLI as in ICRP 72). */
const OF_12 = {
  'Red marrow': [['R_Marrow', 1]], Colon: [['ULI_Wall', 0.57], ['LLI_Wall', 0.43]], Lung: [['Lng_Tiss', 1]], Stomach: [['St_Wall', 1]],
  Bladder: [['UB_Wall', 1]], Breast: [['Breasts', 1]], Liver: [['Liver', 1]], Oesophagus: [['Esophagus', 1]], Thyroid: [['Thyroid', 1]],
  Skin: [['Skin', 1]], 'Bone surface': [['Bone_Sur', 1]], Adrenals: [['Adrenals', 1]], Brain: [['Brain', 1]], 'Small intestine': [['SI_Wall', 1]],
  Kidneys: [['Kidneys', 1]], Muscle: [['Muscle', 1]], Pancreas: [['Pancreas', 1]], Spleen: [['Spleen', 1]], Thymus: [['Thymus', 1]],
  Uterus: [['Uterus', 1]], Testes: [['Testes', 1]], Ovaries: [['Ovaries', 1]], 'Upper large intestine': [['ULI_Wall', 1]],
  'Lower large intestine': [['LLI_Wall', 1]], Gallbladder: [['GB_Wall', 1]], Heart: [['Ht_Wall', 1]],
};
export const W_60_EXTERNAL = {
  Gonads: 0.20, 'Red marrow': 0.12, Colon: 0.12, Lung: 0.12, Stomach: 0.12, Bladder: 0.05, Breast: 0.05, Liver: 0.05, Oesophagus: 0.05,
  Thyroid: 0.05, Skin: 0.01, 'Bone surface': 0.01,
};
/* The remainder of ICRP 72 without the extrathoracic airways, which the
   phantom has no dose for: mass-weighted with the adult masses of
   dose60.js's REMAINDER_60, and the splitting rule. */
export const REMAINDER_60_EXTERNAL = { Adrenals: 14, Brain: 1400, 'Small intestine': 640, Kidneys: 310, Muscle: 28000, Pancreas: 100, Spleen: 180, Thymus: 20, Uterus: 80 };
/* FGR 12's effective dose equivalent (ICRP 26): the gonads the higher of the
   two, the remainder the mean of the five highest of its organs, skin left out. */
const REMAINDER_26 = ['Adrenals', 'Brain', 'GB_Wall', 'Esophagus', 'St_Wall', 'SI_Wall', 'ULI_Wall', 'LLI_Wall', 'Ht_Wall', 'Kidneys', 'Liver',
  'Pancreas', 'Spleen', 'Thymus', 'UB_Wall', 'Uterus', 'Muscle'];

/**
 * The page's tissues, and the effective dose as weights of the report's
 * tissues: E = Σ wE·h, which a part of h (its photons, say) shares in the same
 * way. The ICRP 60 system's choices -- the gonad, the remainder's split, FGR
 * 12's five highest remainder organs -- are made on the h given.
 * @param {'60'|'103'} system
 * @param {string[]} names  the report's tissue names
 * @param {ArrayLike<number>} h  their values
 * @returns {{E: number, H: object, wE: Float64Array, remainderShares: object, HE?: number, wHE?: Float64Array, split?: string|null, gonads?: string}}
 *   remainderShares: each remainder tissue's part of H.Remainder (they add up to it)
 */
export function effective(system, names, h) {
  const at = Object.fromEntries(names.map((n, i) => [n, i]));
  const wE = new Float64Array(names.length);
  const H = {};
  const dot = (w) => w.reduce((a, x, i) => a + x * h[i], 0);
  if (system === '103') {
    for (const [k, parts] of Object.entries(OF_15)) H[k] = parts.reduce((a, p) => a + h[at[p]], 0) / parts.length;
    H.Remainder = REMAINDER_15.reduce((a, k) => a + H[k], 0) / REMAINDER_15.length;
    const give = (k, w) => { for (const p of OF_15[k]) wE[at[p]] += w / OF_15[k].length; };
    for (const [k, w] of Object.entries(W_15)) give(k, w);
    for (const k of REMAINDER_15) give(k, 0.12 / REMAINDER_15.length);
    const remainderShares = Object.fromEntries(REMAINDER_15.map((k) => [k, H[k] / REMAINDER_15.length]));
    return { E: dot(wE), H, wE, remainderShares };
  }
  for (const [k, parts] of Object.entries(OF_12)) H[k] = parts.reduce((a, [p, w]) => a + w * h[at[p]], 0);
  const gonads = H.Testes >= H.Ovaries ? 'Testes' : 'Ovaries';
  H.Gonads = H[gonads];
  const give = (k, w) => { for (const [p, f] of OF_12[k]) wE[at[p]] += w * f; };
  for (const [k, w] of Object.entries(W_60_EXTERNAL)) give(k === 'Gonads' ? gonads : k, w);
  // The remainder: mass-weighted, or half to a tissue above every weighted one.
  const rem = Object.keys(REMAINDER_60_EXTERNAL);
  const named = Math.max(...Object.keys(W_60_EXTERNAL).map((k) => H[k]));
  const top = rem.reduce((a, k) => (H[k] > H[a] ? k : a), rem[0]);
  const split = H[top] > named ? top : null;
  const others = split ? rem.filter((k) => k !== split) : rem;
  const mass = others.reduce((a, k) => a + REMAINDER_60_EXTERNAL[k], 0);
  const wRem = Object.fromEntries(others.map((k) => [k, (split ? 0.5 : 1) * REMAINDER_60_EXTERNAL[k] / mass]));
  if (split) wRem[split] = 0.5;
  H.Remainder = Object.entries(wRem).reduce((a, [k, w]) => a + w * H[k], 0);
  for (const [k, w] of Object.entries(wRem)) give(k, 0.05 * w);
  // FGR 12's effective dose equivalent.
  const wHE = new Float64Array(names.length);
  const g26 = h[at.Testes] >= h[at.Ovaries] ? 'Testes' : 'Ovaries';
  for (const [p, w] of [[g26, 0.25], ['Breasts', 0.15], ['R_Marrow', 0.12], ['Lng_Tiss', 0.12], ['Thyroid', 0.03], ['Bone_Sur', 0.03]]) wHE[at[p]] += w;
  for (const p of [...REMAINDER_26].sort((a, b) => h[at[b]] - h[at[a]]).slice(0, 5)) wHE[at[p]] += 0.30 / 5;
  const remainderShares = Object.fromEntries(rem.map((k) => [k, (wRem[k] || 0) * H[k]]));
  return { E: dot(wE), H, wE, remainderShares, HE: dot(wHE), wHE, split, gonads };
}

/* ---- progeny in equilibrium ---------------------------------------------------- */
/**
 * Each chain member's activity per becquerel of the parent once the chain is
 * in equilibrium with it, or null for a member that never is: one that lives
 * as long as the parent or longer, or that is formed from such a one. Secular
 * equilibrium where the parent lives much longer (a ratio of the branching),
 * transient where not (more than the branching: λi/(λi − λP) at each step).
 * @param {{members: Array<{lambda: number}>, branches: Array<{from, to, b}>}} chain  buildChain()'s, members in decay order
 * @returns {{ratio: Array<number|null>, days: number}}  days: about when the slowest member comes within 1 % of it
 */
export function equilibrium(chain) {
  const m = chain.members, lP = m[0].lambda;
  const ratio = m.map(() => 0);
  ratio[0] = 1;
  const feeds = m.map(() => []);
  for (const b of chain.branches) if (b.b > 0) feeds[b.to].push(b);
  let slow = Infinity;
  for (let i = 1; i < m.length; i++) {
    const li = m[i].lambda;
    if (!(li > lP) || feeds[i].some((b) => ratio[b.from] == null)) { ratio[i] = null; continue; }
    ratio[i] = li / (li - lP) * feeds[i].reduce((a, b) => a + b.b * ratio[b.from], 0);
    slow = Math.min(slow, li - lP);
  }
  return { ratio, days: Number.isFinite(slow) ? Math.log(100) / slow : 0 };
}

/* ---- a calculation ---------------------------------------------------------------- */
/**
 * The dose rate coefficients of a nuclide in a geometry at each age: of the
 * nuclide alone (the reports' convention), with the parts its photons, its
 * bremsstrahlung and its electrons give; and with its progeny in equilibrium,
 * with each member's share. The shares and parts are those of the effective
 * dose's own weighting (in the ICRP 60 system its choice of gonad and of the
 * remainder's split), so that they add up to it.
 * @param {External} X  the report's data
 * @param {{emissions(name): object}} data  the system's (data.js), its chain's elements loaded
 * @param {{members: Array<{name, T, lambda}>, branches: Array}} chain  buildChain()'s, uncut
 * @param {'60'|'103'} system
 * @param {string} geometry
 * @param {number[]} ages  the page's ages (days)
 */
export function externalRun(X, data, chain, system, geometry, ages) {
  const eq = equilibrium(chain);
  const skin = X.tissues.indexOf('Skin');
  const dot = (w, h) => (w ? w.reduce((a, x, i) => a + x * h[i], 0) : undefined);
  return ages.map((age) => {
    const t0 = (typeof performance !== 'undefined' ? performance : Date).now();
    const phantom = PHANTOM_OF_AGE[age];
    if (!X.ages.includes(phantom)) throw new Error(system === '60' ? 'Federal Guidance Report 12 gives the adult only' : `no phantom of age ${age} d`);
    const n = X.tissues.length, sum = new Float64Array(n);
    const doses = chain.members.map((m, j) => {
      const ratio = eq.ratio[j];
      if (ratio == null || !(ratio > 0)) return null;
      const d = X.dose(data.emissions(m.name), geometry, phantom);
      for (let t = 0; t < n; t++) sum[t] += ratio * d.h[t];
      return d;
    });
    const own = doses[0];
    const a = effective(system, X.tissues, own.h), p = effective(system, X.tissues, sum);
    // The parent's photon lines that give the most of e: [E, yield, e].
    const R = X.response(geometry, phantom);
    const lines = (data.emissions(chain.members[0].name)?.r?.p || []).filter(([E, y]) => E >= KMIN && y > 0).map(([E, y]) => {
      const bs = R.tissues[0].photon.basis(E);
      return [E, y, y * R.tissues.reduce((acc, t, i) => acc + a.wE[i] * t.photon.atBasis(bs), 0)];
    }).sort((u, v) => v[2] - u[2]).slice(0, 12);
    const part = (h, isSkin) => ({ E: dot(a.wE, h), HE: dot(a.wHE, h), skin: isSkin ? h : h[skin] });
    const members = chain.members.map((m, j) => {
      const d = doses[j], ratio = eq.ratio[j];
      if (!d) return { name: m.name, T: m.T, ratio };
      const self = effective(system, X.tissues, d.h);
      const scaled = d.h.map((x) => ratio * x);
      return { name: m.name, T: m.T, ratio, E: self.E, HE: self.HE, skin: d.h[skin], share: { E: dot(p.wE, scaled), HE: dot(p.wHE, scaled), skin: ratio * d.h[skin] } };
    });
    return {
      age, phantom, external: true, geometry, per: own.per,
      E: a.E, H: a.H, HE: a.HE, split: a.split ?? null, gonads: a.gonads ?? null, remainderShares: a.remainderShares,
      parts: {
        photon: part(own.photon), brems: part(own.brems),
        electron: { E: a.wE[skin] * own.electron, HE: a.wHE ? 0 : undefined, skin: own.electron },
      },
      progeny: { E: p.E, H: p.H, HE: p.HE, split: p.split ?? null, gonads: p.gonads ?? null, remainderShares: p.remainderShares },
      members, days: eq.days, lines,
      ms: (typeof performance !== 'undefined' ? performance : Date).now() - t0,
    };
  });
}
