/*
  S coefficients of the ICRP 103 system: the equivalent dose in a target
  region per nuclear transformation in a source region, for one radionuclide
  and one reference individual (ICRP 158 eq. 2.14; ICRP 133 and 155):

    S(rT <- rS) = sum over radiations R of  wR sum_i E_i Y_i SAF_R(rT <- rS, E_i)

  with the specific absorbed fractions of ICRP Publication 155 (whose adult
  files revise those of Publication 133) for photons, electrons and alpha
  particles at tabulated energies, interpolated by monotone piecewise cubic
  Hermite splines (PCHIP; Fritsch and Carlson 1980) as in the OIR and EIR
  series (ICRP 155 para 31). Beta particles enter through their spectra: the
  integral of E N(E) SAF(E), taken as that of the monotone cubic through the
  product at the spectrum's own energy points (spectrumOnGrid below).
  The recoiling nucleus after an alpha decay and fission fragments take the
  SAF of a 2.0 MeV alpha particle (local absorption; ICRP 155 paras 81, 84),
  with alpha particles weighted by wR = 20; neutrons from spontaneous fission
  use the nuclide's own spectrum-averaged SAF and wR (ICRP 155 Table 4.1).

  PCHIP is not linear in the data, but its slopes depend only on the data, so
  they are computed once for every target-source pair of a phantom. A
  nuclide's lines then reduce to four weights per energy interval, and the S
  of a pair is a short dot product with the pair's values and slopes. A beta
  spectrum is the exception: the cubic through its product with the SAF has
  slopes that depend on the pair, so it is integrated pair by pair, the SAF at
  each of the spectrum's energies from four multipliers worked out once.
*/
/* J per MeV as the ICRP's coefficients have it: 1.6e-13, the rounded factor
   of Publication 30 (H = 1.6e-10 U SEE), not the exact 1.602 176 634e-13.
   Read off the InMoP annex (2026-11): with the exact value every dose of the
   page was 1.00136 times the annex's -- the densest 0.004 % of the ratios of
   93,570 organ doses lies at 1.001354 to 1.001376 at each of the six ages,
   and 1.602176634 / 1.6 = 1.001360. */
export const MEV = 1.6e-13;
export const W_ALPHA = 20;
const RECOIL_E = 2.0; // MeV: the alpha energy whose SAF recoils and fission fragments take

/** PCHIP slopes at the nodes (as SciPy's PchipInterpolator and SLATEC PCHIM). */
export function pchipSlopes(x, y, out = new Float64Array(x.length), off = 0, n = x.length) {
  // x and y are read from position off on, n points; out receives n slopes.
  if (n === 1) { out[0] = 0; return out; }
  const h = (k) => x[off + k + 1] - x[off + k];
  const m = (k) => (y[k + 1] - y[k]) / h(k);
  if (n === 2) { out[0] = out[1] = m(0); return out; }
  for (let k = 1; k < n - 1; k++) {
    const m0 = m(k - 1), m1 = m(k);
    if (m0 === 0 || m1 === 0 || (m0 > 0) !== (m1 > 0)) { out[k] = 0; continue; }
    const h0 = h(k - 1), h1 = h(k);
    const w1 = 2 * h1 + h0, w2 = h1 + 2 * h0;
    out[k] = (w1 + w2) / (w1 / m0 + w2 / m1);
  }
  out[0] = pchipEdge(h(0), h(1), m(0), m(1));
  out[n - 1] = pchipEdge(h(n - 2), h(n - 3), m(n - 2), m(n - 3));
  return out;
}

/** The slope at an end of a PCHIP: the three-point formula, kept to the shape of the data. */
function pchipEdge(h0, h1, m0, m1) {
  let d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1);
  if (Math.sign(d) !== Math.sign(m0)) d = 0;
  else if (Math.sign(m0) !== Math.sign(m1) && Math.abs(d) > Math.abs(3 * m0)) d = 3 * m0;
  return d;
}

/**
 * Integral of the monotone cubic (PCHIP, with the slopes of pchipSlopes)
 * through n points: x read from position off on, g from its start. In one
 * pass, the slopes as it goes: it runs for every pair of regions of a nuclide.
 */
export function pchipIntegral(x, g, n = x.length, off = 0) {
  if (n < 2) return 0;
  let h0 = x[off + 1] - x[off], m0 = (g[1] - g[0]) / h0;
  if (n === 2) return h0 * (g[0] + g[1]) / 2;
  let h1 = x[off + 2] - x[off + 1], m1 = (g[2] - g[1]) / h1;
  let dLeft = pchipEdge(h0, h1, m0, m1);
  let sum = 0;
  for (let k = 1; ; k++) {
    // h0, m0: the interval before node k; h1, m1: the one after; dLeft: the slope at node k - 1.
    let d = 0;
    if (!(m0 === 0 || m1 === 0 || (m0 > 0) !== (m1 > 0))) {
      const w1 = 2 * h1 + h0, w2 = h1 + 2 * h0;
      d = (w1 + w2) / (w1 / m0 + w2 / m1);
    }
    sum += h0 * (g[k - 1] + g[k]) / 2 + h0 * h0 * (dLeft - d) / 12;
    dLeft = d;
    if (k === n - 2) break;
    h0 = h1; m0 = m1;
    h1 = x[off + k + 2] - x[off + k + 1]; m1 = (g[k + 2] - g[k + 1]) / h1;
  }
  return sum + h1 * (g[n - 2] + g[n - 1]) / 2 + h1 * h1 * (dLeft - pchipEdge(h1, h0, m1, m0)) / 12;
}

/** PCHIP value at xi from nodes x, values y and slopes d. */
export function pchipEval(x, y, d, xi) {
  const n = x.length;
  if (xi <= x[0]) return y[0];
  if (xi >= x[n - 1]) return y[n - 1];
  let k = 0;
  while (xi > x[k + 1]) k++;
  const h = x[k + 1] - x[k], t = (xi - x[k]) / h;
  const t2 = t * t, t3 = t2 * t;
  return (2 * t3 - 3 * t2 + 1) * y[k] + (t3 - 2 * t2 + t) * h * d[k] + (-2 * t3 + 3 * t2) * y[k + 1] + (t3 - t2) * h * d[k + 1];
}

/* ---------------------------------------------------------------------------
   The SAF data of one reference individual
   --------------------------------------------------------------------------- */
function view(buf, part) {
  const T = { Uint8: Uint8Array, Uint16: Uint16Array, Float32: Float32Array }[part.type];
  return new T(buf, part.offset, part.length);
}

/** One phantom's SAFs, from its binary file and the index. */
export class SafPhantom {
  constructor(index, id, buffer, neutronBuffer = null) {
    const ph = index.phantoms.find((p) => p.id === id);
    if (!ph) throw new Error(`no phantom ${id}`);
    this.id = id; this.sex = ph.sex; this.age = ph.age;
    this.targets = index.targets; this.sources = index.sources;
    this.nT = index.targets.length; this.nS = index.sources.length;
    this.masses = ph.masses;
    this.other = index.other[ph.sex];
    this.energies = index.energies;
    this.neutronNuclides = index.neutron.nuclides;
    this.neutronWR = index.neutron.wR;
    const L = ph.layout;
    const nR = this.nT * this.nS;
    // Photons and electrons: rows kept from their first non-zero energy on.
    this.radiation = {};
    for (const [key, startKey] of [['photon', 'photonStart'], ['electron', 'electronStart']]) {
      const start = view(buffer, L[startKey]);
      const vals = view(buffer, L[key]);
      const n = this.energies[key].length;
      const offset = new Int32Array(nR + 1);
      for (let r = 0; r < nR; r++) offset[r + 1] = offset[r] + (n - start[r]);
      if (offset[nR] !== vals.length) throw new Error(`${id} ${key}: ${vals.length} values, rows want ${offset[nR]}`);
      this.radiation[key] = { start, vals, offset, n, slopes: null };
    }
    const aRows = view(buffer, L.alphaRows);
    const aVals = view(buffer, L.alpha);
    const na = this.energies.alpha.length;
    const at = new Int32Array(nR).fill(-1);
    aRows.forEach((r, k) => { at[r] = k; });
    const aStart = new Uint8Array(nR).fill(na);
    const aOffset = new Int32Array(nR + 1);
    // Stored densely (every energy) for the rows that have any alpha SAF.
    for (let r = 0; r < nR; r++) { aStart[r] = at[r] < 0 ? na : 0; aOffset[r + 1] = aOffset[r] + (at[r] < 0 ? 0 : na); }
    const aDense = new Float32Array(aOffset[nR]);
    for (let r = 0; r < nR; r++) if (at[r] >= 0) aDense.set(aVals.subarray(at[r] * na, at[r] * na + na), aOffset[r]);
    this.radiation.alpha = { start: aStart, vals: aDense, offset: aOffset, n: na, slopes: null };
    this.neutron = neutronBuffer ? new Float32Array(neutronBuffer) : null;
  }

  /** PCHIP slopes of every row, computed on first use: at the stored nodes,
      and (dPrev) at the last leading zero, which is non-zero only when that
      zero is the first node. Slopes at the other leading zeros are zero. */
  slopes(key) {
    const R = this.radiation[key];
    if (R.slopes) return R.slopes;
    const x = this.energies[key];
    const d = new Float32Array(R.vals.length);
    const dPrev = new Float32Array(this.nT * this.nS);
    const y = new Float64Array(R.n), out = new Float64Array(R.n);
    const nR = this.nT * this.nS;
    for (let r = 0; r < nR; r++) {
      const s = R.start[r], o = R.offset[r], len = R.n - s;
      if (!len) continue;
      // The leading zeros take part in the spline: slopes over the whole row.
      y.fill(0);
      for (let k = 0; k < len; k++) y[s + k] = R.vals[o + k];
      pchipSlopes(x, y, out, 0, R.n);
      for (let k = 0; k < len; k++) d[o + k] = out[s + k];
      if (s > 0) dPrev[r] = out[s - 1];
    }
    R.slopes = d;
    R.dPrev = dPrev;
    return d;
  }
}

/* ---------------------------------------------------------------------------
   A nuclide's emissions, as weights on the SAF energy grids
   --------------------------------------------------------------------------- */

/** Hermite weights of lines [[E, EY]...] on grid x: per interval k the
    multipliers of y[k], d[k], y[k+1], d[k+1]. */
function gridWeights(x, lines) {
  const n = x.length;
  const W = new Float64Array(4 * (n - 1));
  for (const [E, ey] of lines) {
    if (!(ey > 0)) continue;
    if (E >= x[n - 1]) { W[4 * (n - 2) + 2] += ey; continue; } // above the grid: the last value
    let k = 0;
    while (E > x[k + 1]) k++;
    const h = x[k + 1] - x[k], t = (E - x[k]) / h;
    const t2 = t * t, t3 = t2 * t;
    W[4 * k] += ey * (2 * t3 - 3 * t2 + 1);
    W[4 * k + 1] += ey * (t3 - 2 * t2 + t) * h;
    W[4 * k + 2] += ey * (-2 * t3 + 3 * t2);
    W[4 * k + 3] += ey * (t3 - t2) * h;
  }
  return W;
}

/** Beta spectrum [[E...], [N per MeV...]] as lines [E, E N dE] (trapezoidal rule). */
export function spectrumLines(bs) {
  const [E, N] = bs;
  const out = [];
  for (let k = 0; k < E.length; k++) {
    const left = k > 0 ? E[k] - E[k - 1] : 0, right = k + 1 < E.length ? E[k + 1] - E[k] : 0;
    out.push([E[k], E[k] * N[k] * (left + right) / 2]);
  }
  return out;
}

/**
 * A beta spectrum [[E...], [N per MeV...]] made ready for the cubic rule
 * (sRowsByType): at each tabulated energy E N, and where the energy lies on
 * the SAF grid x -- the interval and the four Hermite multipliers of the SAF's
 * values and slopes at its ends.
 *
 * The energy a spectrum gives to a target is the integral of E N(E) SAF(E).
 * The tables have some 100 energies, few where a spectrum bends most. Summing
 * the product at the tabulated energies by the trapezoidal rule is up to
 * 0.5 % off in a spectrum's energy (0.14 % in the root mean square over the
 * 955 spectra of ICRP 107, against the mean energies the same data list);
 * the integral of the monotone cubic through the product is 0.05 % off, and
 * it is what the published coefficients have (model103.js
 * OPTIONS103.betaSpectrum).
 */
function spectrumOnGrid(bs, x) {
  const [E, N] = bs;
  const n = E.length, nx = x.length;
  const e = Float64Array.from(E), en = new Float64Array(n), at = new Int32Array(n), b = new Float64Array(4 * n);
  for (let j = 0; j < n; j++) {
    en[j] = E[j] * N[j];
    if (E[j] >= x[nx - 1]) { at[j] = nx - 2; b[4 * j + 2] = 1; continue; } // above the grid: the last value
    let k = 0;
    while (E[j] > x[k + 1]) k++;
    const h = x[k + 1] - x[k], t = (E[j] - x[k]) / h, t2 = t * t, t3 = t2 * t;
    at[j] = k;
    b[4 * j] = 2 * t3 - 3 * t2 + 1; b[4 * j + 1] = (t3 - 2 * t2 + t) * h;
    b[4 * j + 2] = -2 * t3 + 3 * t2; b[4 * j + 3] = (t3 - t2) * h;
  }
  // first[k]: the first tabulated energy above the grid's node k (a SAF that is zero up to node k is zero below it)
  const first = new Int32Array(nx);
  for (let k = 0, j = 0; k < nx; k++) { while (j < n && E[j] <= x[k]) j++; first[k] = j; }
  return { n, e, en, at, b, first };
}

/**
 * @param {object} em  {r: {p, b, e, a, ar, ff, n}, bs}: lines [E (MeV), Y per decay]
 * @param {object} energies  the SAF energy grids {photon, electron, alpha}
 * @param {string} name  the nuclide (for its neutron SAFs)
 * @param {string} [betaSpectrum]  how a beta spectrum is integrated with the SAFs: 'cubic' = the monotone cubic
 *                        through E N(E) SAF(E) at the tabulated energies, 'trapezoid' = the trapezoidal rule there
 */
export function emissionWeights(em, energies, name, betaSpectrum = 'cubic') {
  const r = em.r || {};
  const ey = (list) => (list || []).map(([e, y]) => [e, e * y]);
  const electrons = [...ey(r.e)];
  if (betaSpectrum !== 'cubic' && betaSpectrum !== 'trapezoid') throw new Error(`beta spectrum rule ${betaSpectrum}`);
  // Beta particles through their spectra; the mean-energy lines only if there is none.
  let beta = null;
  if (em.bs && betaSpectrum === 'cubic') beta = spectrumOnGrid(em.bs, energies.electron);
  else if (em.bs) for (const line of spectrumLines(em.bs)) electrons.push(line);
  else electrons.push(...ey(r.b));
  const local = [...ey(r.ar), ...ey(r.ff)].reduce((a, [, x]) => a + x, 0);
  return {
    name,
    photon: gridWeights(energies.photon, ey(r.p)),
    electron: gridWeights(energies.electron, electrons),
    beta,
    alpha: gridWeights(energies.alpha, [...ey(r.a), ...(local > 0 ? [[RECOIL_E, local]] : [])]),
    neutronEY: (r.n || []).reduce((a, [e, y]) => a + e * y, 0),
  };
}

/** The radiation types whose S coefficients are kept apart (sRowsByType): each is interpolated in age on its own. */
export const S_TYPES = ['photon', 'electron', 'alpha', 'neutron'];

/**
 * S coefficients [Sv per (Bq s)] of every target-source pair, row = source *
 * nT + target, for a nuclide's weights in a phantom, one array per radiation
 * type of S_TYPES (null where the nuclide emits none of it): photons,
 * electrons (with beta particles), alpha particles (with recoils and fission
 * fragments) and the neutrons of spontaneous fission.
 */
export function sRowsByType(ph, w) {
  const nR = ph.nT * ph.nS;
  const one = (key, W, factor, spectrum = null) => {
    const R = ph.radiation[key];
    const nI = R.n - 1;
    let any = !!spectrum;
    for (let i = 0; i < W.length && !any; i++) if (W[i]) any = true;
    if (!any) return null;
    const d = ph.slopes(key);
    const dPrev = R.dPrev;
    const S = new Float64Array(nR);
    // A spectrum by the cubic rule: E N SAF at its tabulated energies, row by row.
    const g = spectrum ? new Float64Array(spectrum.n) : null;
    for (let r = 0; r < nR; r++) {
      const s = R.start[r], o = R.offset[r];
      if (s >= R.n) continue;
      let acc = 0;
      // Intervals left of s are zero at both ends with zero slopes, except
      // interval s-1, whose right end is the first stored value.
      for (let k = Math.max(0, s - 1); k < nI; k++) {
        const j = 4 * k;
        if (!W[j] && !W[j + 1] && !W[j + 2] && !W[j + 3]) continue;
        const y0 = k >= s ? R.vals[o + k - s] : 0, d0 = k >= s ? d[o + k - s] : dPrev[r];
        const y1 = R.vals[o + k + 1 - s], d1 = d[o + k + 1 - s];
        acc += W[j] * y0 + W[j + 1] * d0 + W[j + 2] * y1 + W[j + 3] * d1;
      }
      if (spectrum) {
        const { n, e, en, at, b, first } = spectrum;
        // The SAF is zero up to node s-1: the product is zero at the energies up to it, and the cubic
        // through zeros is zero. Two of them are kept in front, so that its slopes are those of the whole.
        const j0 = s > 0 ? first[s - 1] : 0;
        if (j0 < n) {
          const from = Math.max(0, j0 - 2), m = n - from;
          for (let j = from; j < n; j++) {
            const k = at[j];
            if (k < s - 1) { g[j - from] = 0; continue; }
            const y0 = k >= s ? R.vals[o + k - s] : 0, d0 = k >= s ? d[o + k - s] : dPrev[r];
            const y1 = R.vals[o + k + 1 - s], d1 = d[o + k + 1 - s];
            g[j - from] = en[j] * (b[4 * j] * y0 + b[4 * j + 1] * d0 + b[4 * j + 2] * y1 + b[4 * j + 3] * d1);
          }
          acc += pchipIntegral(e, g, m, from);
        }
      }
      S[r] = factor * acc;
    }
    return S;
  };
  let neutron = null;
  if (w.neutronEY > 0) {
    const k = ph.neutronNuclides.indexOf(w.name);
    if (k >= 0) {
      if (!ph.neutron) throw new Error(`${w.name}: the neutron SAFs of ${ph.id} are not loaded`);
      const f = MEV * ph.neutronWR[k] * w.neutronEY;
      neutron = new Float64Array(nR);
      for (let r = 0; r < nR; r++) neutron[r] = f * ph.neutron[k * nR + r];
    }
  }
  return [one('photon', w.photon, MEV), one('electron', w.electron, MEV, w.beta), one('alpha', w.alpha, MEV * W_ALPHA), neutron];
}

/**
 * S coefficients [Sv per (Bq s)] of every target-source pair, row = source *
 * nT + target, for a nuclide's weights in a phantom: the sum over the
 * radiation types. `parts` takes the result of sRowsByType where it is at hand.
 */
export function sAllRows(ph, w, parts = sRowsByType(ph, w)) {
  const S = new Float64Array(ph.nT * ph.nS);
  for (const part of parts) if (part) for (let r = 0; r < S.length; r++) S[r] += part[r];
  return S;
}

/**
 * The S coefficients for a member's source regions in one phantom:
 * {region: Float64Array(nT)}, with "Other" the mass-weighted mean over the
 * regions that may form Other and that the member's systemic model does not
 * name (ICRP 155 eq. 2.15).
 */
export function sForRegions(ph, S, regions, named) {
  const out = {};
  const nT = ph.nT;
  const col = (s) => S.subarray(s * nT, s * nT + nT);
  for (const reg of regions) {
    if (reg === 'Other') {
      const acc = new Float64Array(nT);
      let M = 0;
      ph.sources.forEach((src, s) => {
        if (!ph.other[s] || named.has(src)) return;
        const m = ph.masses.sources[s];
        if (!(m > 0)) return;
        M += m;
        const c = col(s);
        for (let t = 0; t < nT; t++) acc[t] += m * c[t];
      });
      if (M > 0) for (let t = 0; t < nT; t++) acc[t] /= M;
      out.Other = acc;
      continue;
    }
    const s = ph.sources.indexOf(reg);
    if (s < 0) throw new Error(`no source region ${reg}`);
    out[reg] = Float64Array.from(col(s));
  }
  return out;
}
