/*
  S coefficients of the ICRP 103 system: the equivalent dose in a target
  region per nuclear transformation in a source region, for one radionuclide
  and one reference individual (ICRP 158 eq. 2.14; ICRP 133 and 155):

    S(rT <- rS) = sum over radiations R of  wR sum_i E_i Y_i SAF_R(rT <- rS, E_i)

  with the specific absorbed fractions of ICRP Publication 155 (whose adult
  files revise those of Publication 133) for photons, electrons and alpha
  particles at tabulated energies, interpolated by monotone piecewise cubic
  Hermite splines (PCHIP; Fritsch and Carlson 1980) as in the OIR and EIR
  series (ICRP 155 para 31). Beta particles enter through their spectra,
  integrated by the trapezoidal rule over the spectrum's own energy points.
  The recoiling nucleus after an alpha decay and fission fragments take the
  SAF of a 2.0 MeV alpha particle (local absorption; ICRP 155 paras 81, 84),
  with alpha particles weighted by wR = 20; neutrons from spontaneous fission
  use the nuclide's own spectrum-averaged SAF and wR (ICRP 155 Table 4.1).

  PCHIP is not linear in the data, but its slopes depend only on the data, so
  they are computed once for every target-source pair of a phantom. A
  nuclide's lines then reduce to four weights per energy interval, and the S
  of a pair is a short dot product with the pair's values and slopes.
*/
export const MEV = 1.602176634e-13; // J per MeV
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
  const edge = (h0, h1, m0, m1) => {
    let d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1);
    if (Math.sign(d) !== Math.sign(m0)) d = 0;
    else if (Math.sign(m0) !== Math.sign(m1) && Math.abs(d) > Math.abs(3 * m0)) d = 3 * m0;
    return d;
  };
  out[0] = edge(h(0), h(1), m(0), m(1));
  out[n - 1] = edge(h(n - 2), h(n - 3), m(n - 2), m(n - 3));
  return out;
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
 * @param {object} em  {r: {p, b, e, a, ar, ff, n}, bs}: lines [E (MeV), Y per decay]
 * @param {object} energies  the SAF energy grids {photon, electron, alpha}
 * @param {string} name  the nuclide (for its neutron SAFs)
 */
export function emissionWeights(em, energies, name) {
  const r = em.r || {};
  const ey = (list) => (list || []).map(([e, y]) => [e, e * y]);
  const electrons = [...ey(r.e)];
  // Beta particles through their spectra; the mean-energy lines only if there is none.
  if (em.bs) electrons.push(...spectrumLines(em.bs));
  else electrons.push(...ey(r.b));
  const local = [...ey(r.ar), ...ey(r.ff)].reduce((a, [, x]) => a + x, 0);
  return {
    name,
    photon: gridWeights(energies.photon, ey(r.p)),
    electron: gridWeights(energies.electron, electrons),
    alpha: gridWeights(energies.alpha, [...ey(r.a), ...(local > 0 ? [[RECOIL_E, local]] : [])]),
    neutronEY: (r.n || []).reduce((a, [e, y]) => a + e * y, 0),
  };
}

/**
 * S coefficients [Sv per (Bq s)] of every target-source pair, row = source *
 * nT + target, for a nuclide's weights in a phantom.
 */
export function sAllRows(ph, w) {
  const nR = ph.nT * ph.nS;
  const S = new Float64Array(nR);
  const add = (key, W, factor) => {
    const R = ph.radiation[key];
    const d = ph.slopes(key);
    const dPrev = R.dPrev;
    const nI = R.n - 1;
    let any = false;
    for (let i = 0; i < W.length; i++) if (W[i]) { any = true; break; }
    if (!any) return;
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
      S[r] += factor * acc;
    }
  };
  add('photon', w.photon, MEV);
  add('electron', w.electron, MEV);
  add('alpha', w.alpha, MEV * W_ALPHA);
  if (w.neutronEY > 0) {
    const k = ph.neutronNuclides.indexOf(w.name);
    if (k >= 0) {
      if (!ph.neutron) throw new Error(`${w.name}: the neutron SAFs of ${ph.id} are not loaded`);
      const f = MEV * ph.neutronWR[k] * w.neutronEY;
      for (let r = 0; r < nR; r++) S[r] += f * ph.neutron[k * nR + r];
    }
  }
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
