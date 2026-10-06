/*
  Beta spectra and mean beta energies as EDISTR04 computes them (Endo,
  Yamaguchi and Eckerman, JAERI 1347, 2005), the code that made the beta data
  of ICRP Publication 107 from ENSDF. EDISTR04 kept the beta-decay theory of
  Dillman's EDISTR (ORNL/TM-6689, 1980, pp. 7-10), which is that of Gove and
  Martin (Nucl. Data Tables 10, 205, 1971). Equation numbers below are
  Dillman's.

  In units of the electron rest energy, with W the total energy, p = (W^2-1)^1/2
  and W0 the end point, the number of betas per unit W is (Eq 7)

    P(W) = p W (W0 - W)^2 S_n(Z, W)
    S_n  = sum_k=1..n+1 lambda_k p^2(k-1) (W0 - W)^2(n-k+1) / [(2k-1)! (2(n-k+1)+1)!]   (8)
    lambda_k = (g_-k^2 + f_k^2) / 2p^2 [(2k-1)!! / (pR)^(k-1)]^2                         (9)

  for the allowed shape (n = 0) and the n-th unique forbidden shape; f_k and
  g_-k are the Dirac Coulomb functions of a point nucleus at the nuclear
  radius R (Eqs 10-19, with the confluent hypergeometric function as a power
  series and |Gamma| of complex argument from Stirling's series), Z the atomic
  number of the daughter. On top of that:

  - Screening (Rose): W and p are replaced by W' = W -/+ V0 and p' everywhere
    except in W0 - W. V0(beta-) is Eq 21. For beta+ EDISTR04 uses
    V0(beta+) = V0(beta-) exp(a1/p + a2/p^2), with a1, a2 of Eq 22 and the
    unscreened p: ORNL/TM-6689 prints Eq 22 without the exponential, but the
    printed form makes W' < 1 below a few keV and puts every beta+ mean off by
    up to 6 %, while the exponential reproduces EDISTR04's beta+ spectra point
    by point down to 0.1 keV and its mean energies to the printed digits.
  - Finite nuclear size: lambda_1 is multiplied by 1 + dlambda_1(Z, W'), the
    two expressions on p. 10, for Z > 50 (beta-) and Z > 80 (beta+).
  - Near p' = 0 a beta- spectrum stays finite, and the asymptotic form Eq 20
    (at W', with the finite-size factor on its k = 1 term) is used where W' <= 1
    and, as EDISTR04 also does, where y' = alpha Z W'/p' > 10.
  - The two integrals of the mean (Eq 6) and the normalisation of the spectrum
    are, as in EDISTR's SIMCON (ORNL/TM-6689 p. 60), Simpson's rule on [1, W0]
    in W from 2 intervals on, halving until both int P and int P W change by
    less than 0.1 %. That leaves a quadrature error in the mean of typically
    1e-4 to 3e-4 and up to 2e-3, which ICRP 107 carries; {exact: true}
    integrates to about 1e-9 instead (Gauss-Legendre in p', split where Eq 20
    takes over).

  The electron rest energy is 0.5110034 MeV (CODATA 1973), which fits
  EDISTR04's printed means best (0.511 and 0.51099895 MeV fit worse), and
  alpha = 1/137.036 as printed. Unique forbidden shapes are what the caller
  asks for: EDISTR gives first, second and third forbidden non-unique
  transitions the allowed, first and second unique shapes (n = 0, 1, 2).

  Checked against EDISTR04's own output for ICRP 107 (9 845 allowed and first
  unique beta lines): the mean energies agree to a median of 8e-7, 99 % within
  5e-6 and all but 4 within 5e-5, that is to the printed six digits or within
  one unit of the last for 95 % of the lines; the composite spectra agree with
  ICRP-07.BET to its four printed digits. Two things the caller should know:
  EDISTR04's beta+ spectra belong to end points 2.2 eV above the ones it
  prints, i.e. to Q - E - 2 x 0.5109989 MeV rather than Q - E - 1.022 MeV;
  and the second and third unique shapes (n = 2, 3) differ
  from EDISTR04's by up to 2e-3 in the mean (median 2e-4), a difference in its
  k = 3 term (LOGFT's mean energies in ENSDF show it too) that the printed
  equations do not reproduce.
*/

export const ME = 0.5110034; // MeV
export const ALPHA = 1 / 137.036;

/** The energy grid (MeV) of the beta spectra in ICRP-07.BET. */
export const BETA_GRID = Object.freeze([
  0, 0.0001, 0.00011, 0.00012, 0.00013, 0.00014, 0.00015, 0.00016, 0.00018, 0.0002, 0.00022, 0.00024, 0.00026,
  0.00028, 0.0003, 0.00032, 0.00036, 0.0004, 0.00045, 0.0005, 0.00055, 0.0006, 0.00065, 0.0007, 0.00075, 0.0008,
  0.00085, 0.0009, 0.001, 0.0011, 0.0012, 0.0013, 0.0014, 0.0015, 0.0016, 0.0018, 0.002, 0.0022, 0.0024, 0.0026,
  0.0028, 0.003, 0.0032, 0.0036, 0.004, 0.0045, 0.005, 0.0055, 0.006, 0.0065, 0.007, 0.0075, 0.008, 0.0085, 0.009,
  0.01, 0.011, 0.012, 0.013, 0.014, 0.015, 0.016, 0.018, 0.02, 0.022, 0.024, 0.026, 0.028, 0.03, 0.032, 0.036,
  0.04, 0.045, 0.05, 0.055, 0.06, 0.065, 0.07, 0.075, 0.08, 0.085, 0.09, 0.1, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16,
  0.18, 0.2, 0.22, 0.24, 0.26, 0.28, 0.3, 0.32, 0.36, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9,
  1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2, 2.2, 2.4, 2.6, 2.8, 3, 3.2, 3.6, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8,
  8.5, 9, 10,
]);

const LN_SQRT_2PI = 0.9189385332046728;
const STIRLING = [1 / 12, -1 / 360, 1 / 1260, -1 / 1680, 1 / 1188, -691 / 360360, 1 / 156];

/** ln|Gamma(x + iy)| for x > 0 (Stirling's series after the recurrence up to |z| >= 15; about 1e-15). */
export function lnAbsGamma(x, y) {
  let prod = 1;
  while (x * x + y * y < 225) { prod *= x * x + y * y; x += 1; }
  const r2 = x * x + y * y;
  let re = (x - 0.5) * 0.5 * Math.log(r2) - y * Math.atan2(y, x) - x + LN_SQRT_2PI;
  const ir = x / r2, ii = -y / r2; // 1/z
  const qr = ir * ir - ii * ii, qi = 2 * ir * ii; // 1/z^2
  let sr = STIRLING[STIRLING.length - 1], si = 0;
  for (let j = STIRLING.length - 2; j >= 0; j--) {
    const tr = sr * qr - si * qi;
    si = sr * qi + si * qr;
    sr = tr + STIRLING[j];
  }
  return re + sr * ir - si * ii - 0.5 * Math.log(prod);
}

const fact = (n) => (n <= 1 ? 1 : n * fact(n - 1));
const dfact = (n) => (n <= 1 ? 1 : n * dfact(n - 2));

/* (g_-k^2 + f_k^2) / 2p^2 of Eq 9 at (screened) W and p, Eqs 10-18; sign = +1 for
   beta-, -1 for beta+. lnG2 = ln Gamma(2 gamma + 1). Only squares of f and g enter,
   so the branch of exp(i eta) does not matter. */
function coulombK(k, g, lnG2, W, p, aZ, R, sign) {
  const y = sign * aZ * W / p;
  const Q = Math.exp(g * Math.log(2 * p * R) + Math.PI * y / 2 + lnAbsGamma(g, y) - Math.log(2 * R * Math.sqrt(W)) - lnG2);
  // 1F1(g + 1 + iy; 2g + 1; 2ipR), the series to 1e-17
  const zi = 2 * p * R, b = 2 * g + 1;
  let Fr = 1, Fi = 0, tr = 1, ti = 0;
  for (let m = 0; m < 100; m++) {
    const cr = -y * zi, ci = (g + 1 + m) * zi, d = (b + m) * (m + 1);
    const nr = (tr * cr - ti * ci) / d;
    ti = (tr * ci + ti * cr) / d;
    tr = nr;
    Fr += tr; Fi += ti;
    if (Math.abs(tr) + Math.abs(ti) <= 1e-17 * (Math.abs(Fr) + Math.abs(Fi))) break;
  }
  // exp(-ipR) (g + iy) 1F1
  const c = Math.cos(p * R), s = -Math.sin(p * R);
  const ur = g * Fr - y * Fi, ui = g * Fi + y * Fr;
  const br = c * ur - s * ui, bi = c * ui + s * ur;
  // exp(2i eta) = (-kappa + iy/W)/(g + iy): kappa = k for f_k, -k for g_-k (Eq 17)
  const phF = Math.atan2(g * y / W + k * y, -k * g + y * y / W) / 2;
  const phG = Math.atan2(g * y / W - k * y, k * g + y * y / W) / 2;
  const f = 2 * Math.sqrt(W - 1) * Q * (Math.sin(phF) * br + Math.cos(phF) * bi);
  const gg = 2 * Math.sqrt(W + 1) * Q * (Math.cos(phG) * br - Math.sin(phG) * bi);
  return (gg * gg + f * f) / (2 * p * p);
}

/* Gauss-Legendre nodes and weights on [-1, 1]. */
const GL = new Map();
function gaussLegendre(n) {
  if (GL.has(n)) return GL.get(n);
  const x = new Float64Array(n), w = new Float64Array(n);
  for (let i = 0; i < Math.ceil(n / 2); i++) {
    let z = Math.cos(Math.PI * (i + 0.75) / (n + 0.5)), dp = 1;
    for (let it = 0; it < 100; it++) {
      let p1 = 1, p2 = 0;
      for (let j = 1; j <= n; j++) { const p3 = p2; p2 = p1; p1 = ((2 * j - 1) * z * p2 - (j - 1) * p3) / j; }
      dp = n * (z * p1 - p2) / (z * z - 1);
      const dz = p1 / dp;
      z -= dz;
      if (Math.abs(dz) < 1e-15) break;
    }
    x[i] = -z; x[n - 1 - i] = z;
    w[i] = w[n - 1 - i] = 2 / ((1 - z * z) * dp * dp);
  }
  const r = { x, w };
  GL.set(n, r);
  return r;
}

/**
 * The spectrum shape of one beta transition.
 * @param {{Z: number, A: number, E0: number, n?: number, positron?: boolean}} t
 *   Z of the daughter, mass number A, end-point kinetic energy E0 (MeV), shape
 *   order n (0 allowed, 1-3 first to third unique forbidden), positron for beta+.
 * @param {{exact?: boolean}} [opt]  exact: accurate quadrature instead of EDISTR's Simpson rule.
 * @returns {{density: (E: number) => number, norm: number, mean: number, Z, A, E0, n, positron}}
 *   density(E): unnormalised dN/dE at kinetic energy E (MeV), zero at and beyond E0
 *   and below 0; finite at E = 0 for beta-, zero for beta+. norm: its integral over
 *   [0, E0] in MeV, so density(E)/norm is per MeV per beta. mean: mean kinetic energy (MeV).
 */
export function betaShape({ Z, A, E0, n = 0, positron = false }, opt = {}) {
  if (!(E0 > 0)) throw new Error(`beta end point ${E0} MeV`);
  if (!(Z >= 1) || !(A >= 1)) throw new Error(`beta transition with Z = ${Z}, A = ${A}`);
  if (!Number.isInteger(n) || n < 0 || n > 3) throw new Error(`beta shape order ${n}`);
  const sign = positron ? -1 : 1;
  const W0 = 1 + E0 / ME;
  const R = 0.002908 * Math.cbrt(A) - 0.002437 / Math.cbrt(A); // Eq 19, hbar/mc
  const aZ = ALPHA * Z;
  const K = n + 1;
  const gam = new Float64Array(K), lnG2 = new Float64Array(K), coef = new Float64Array(K), c20 = new Float64Array(K);
  for (let k = 1; k <= K; k++) {
    const g = Math.sqrt(k * k - aZ * aZ);
    const facts = fact(2 * k - 1) * fact(2 * (n - k + 1) + 1);
    gam[k - 1] = g;
    lnG2[k - 1] = lnAbsGamma(2 * g + 1, 0);
    coef[k - 1] = dfact(2 * k - 1) ** 2 / (facts * R ** (2 * (k - 1)));
    const x = 2 * aZ * R;
    c20[k - 1] = 2 * Math.PI * dfact(2 * k - 1) ** 2 * Math.pow(x, 2 * g - 1) / (facts * R ** (2 * k - 1) * Math.exp(2 * lnG2[k - 1]))
      * (g + k) * (k - (2 * k + 1) * x / (2 * g + 1));
  }
  const V0 = -9.45e-9 * Z ** 3 + 3.014e-6 * Z ** 2 + 1.881e-4 * Z - 5.116e-4; // Eq 21, for beta-
  const a1 = 1.11e-7 * Z ** 3 - 1.01e-5 * Z ** 2 - 2.38e-3 * Z + 0.102;
  const a2 = -2.42e-8 * Z ** 3 + 3.83e-6 * Z ** 2 + 3.60e-5 * Z - 0.0156;
  const finite = positron
    ? (Z > 80 ? (W) => 1 + (Z - 80) * (-17e-5 * W + 6.3e-4 / W - 8.8e-3 / (W * W)) : null)
    : (Z > 50 ? (W) => 1 + (Z - 50) * (-25e-4 - 4e-6 * W * (Z - 50)) : null);

  // Eq 20 at W' (beta- only)
  const asymptotic = (W, Ws) => {
    const q = W0 - W;
    let s = 0;
    for (let k = 1; k <= K; k++) s += c20[k - 1] * q ** (2 * (n - k + 2)) * (k === 1 && finite ? finite(Ws) : 1);
    return Ws * s;
  };
  // The switch to Eq 20 for beta-: W' <= 1, or y' > 10, i.e. p'/W' < alpha Z / 10.
  const vSwitch = aZ / 10;

  /** P(W) per unit W, Eq 7 with screening. */
  const P = (W) => {
    if (!(W >= 1 && W < W0)) return 0;
    const p = Math.sqrt(W * W - 1);
    let Ws;
    if (positron) {
      // Below this the Coulomb barrier factor exp(-2 pi |y|) underflows anyway.
      if (2 * Math.PI * aZ * W > 700 * p) return 0;
      // For Z >= 84 (a2 > 0) the fit turns up below p = a2/|a1| (0.011-0.018), under the
      // lowest point EDISTR evaluates (0.1 keV), and would push W' far above W + V0.
      const x = a1 / p + a2 / (p * p);
      Ws = W + V0 * Math.exp(a2 > 0 && x > 0 ? 0 : x);
      if (Ws <= 1) return 0;
    } else {
      Ws = W - V0;
      if (Ws <= 1) return asymptotic(W, Ws);
    }
    const ps = Math.sqrt(Ws * Ws - 1);
    if (!positron && ps < vSwitch * Ws) return asymptotic(W, Ws);
    const q = W0 - W;
    let s = 0;
    for (let k = 1; k <= K; k++) {
      let lam = coulombK(k, gam[k - 1], lnG2[k - 1], Ws, ps, aZ, R, sign);
      if (k === 1 && finite) lam *= finite(Ws);
      s += lam * coef[k - 1] * q ** (2 * (K - k));
    }
    return ps * Ws * q * q * s;
  };

  const [I0, I1] = opt.exact ? exactMoments() : simcon();

  // EDISTR's SIMCON: Simpson in W on [1, W0], halving from 2 intervals until int P and
  // int P W both change by less than 0.1 %.
  function simcon() {
    const a = 1, h0 = W0 - a;
    let N = 2, h = h0 / N;
    const pa = P(a); // P(W0) = 0
    let ends0 = pa, ends1 = pa * a, odd0 = P(a + h), odd1 = odd0 * (a + h), even0 = 0, even1 = 0;
    let S0 = h / 3 * (ends0 + 4 * odd0), S1 = h / 3 * (ends1 + 4 * odd1);
    for (let it = 0; it < 14; it++) {
      even0 += odd0; even1 += odd1; odd0 = 0; odd1 = 0;
      N *= 2; h = h0 / N;
      for (let i = 1; i < N; i += 2) { const W = a + i * h, v = P(W); odd0 += v; odd1 += v * W; }
      const T0 = h / 3 * (ends0 + 4 * odd0 + 2 * even0), T1 = h / 3 * (ends1 + 4 * odd1 + 2 * even1);
      const done = Math.abs(T0 - S0) <= 1e-3 * Math.abs(S0) && Math.abs(T1 - S1) <= 1e-3 * Math.abs(S1);
      S0 = T0; S1 = T1;
      if (done) break;
    }
    return [S0, S1 - S0];
  }

  // int P dW and int P (W - 1) dW to about 1e-10: Gauss-Legendre in W over the Eq 20 part
  // (a polynomial), in p' over the rest (smooth in p', not in W at p' = 0).
  function exactMoments() {
    let I0 = 0, I1 = 0;
    const add = (lo, hi, panels, nodes, f) => {
      const { x, w } = gaussLegendre(nodes);
      for (let j = 0; j < panels; j++) {
        const a = lo + (hi - lo) * j / panels, b = lo + (hi - lo) * (j + 1) / panels;
        const hh = (b - a) / 2, c = (a + b) / 2;
        for (let i = 0; i < nodes; i++) {
          const [v, W] = f(c + hh * x[i]);
          I0 += w[i] * hh * v; I1 += w[i] * hh * v * (W - 1);
        }
      }
    };
    if (positron) {
      add(0, Math.sqrt(W0 * W0 - 1), 8, 24, (p) => { const W = Math.sqrt(1 + p * p); return [P(W) * p / W, W]; });
    } else {
      const Wsw = Math.max(1, 1 / Math.sqrt(1 - vSwitch * vSwitch)); // W' where Eq 20 stops
      const Wb = Math.min(W0, Math.max(1, Wsw + V0));
      if (Wb > 1) add(1, Wb, 1, 12, (W) => [P(W), W]);
      if (Wb < W0) {
        const plo = Math.sqrt(Math.max(0, (Wb - V0) ** 2 - 1)), phi = Math.sqrt((W0 - V0) ** 2 - 1);
        add(plo, phi, 8, 24, (ps) => { const Ws = Math.sqrt(1 + ps * ps), W = Ws + V0; return [P(W) * ps / Ws, W]; });
      }
    }
    return [I0, I1];
  }

  return {
    Z, A, E0, n, positron,
    density: (E) => (E >= 0 && E < E0 ? P(1 + E / ME) : 0),
    norm: ME * I0,
    mean: ME * I1 / I0,
  };
}

/**
 * The composite beta spectrum of a nuclide in the representation of ICRP-07.BET:
 * the grid points below the largest end point, then that end point (where N = 0).
 * @param {Array<{Z, A, E0, n?, positron?, yield: number}>} branches  yield: betas per decay
 * @param {number[]} [grid]
 * @param {{exact?: boolean}} [opt]  passed to betaShape
 * @returns {[number[], number[]]}  [energies (MeV), N (betas per MeV per decay)]
 */
export function betaSpectrum(branches, grid = BETA_GRID, opt = {}) {
  const shapes = branches.filter((b) => b.yield > 0).map((b) => ({ s: betaShape(b, opt), y: b.yield }));
  if (!shapes.length) return [[], []];
  const Emax = Math.max(...shapes.map(({ s }) => s.E0));
  const E = Array.from(grid).filter((e) => e < Emax);
  const N = E.map((e) => shapes.reduce((sum, { s, y }) => sum + (e < s.E0 ? y * s.density(e) / s.norm : 0), 0));
  E.push(Emax);
  N.push(0);
  return [E, N];
}
