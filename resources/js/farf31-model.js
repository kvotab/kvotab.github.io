/* ==========================================================================
   FARF31.HTML: THE MODEL

   Radionuclide transport along a stream tube in fractured rock: the model of
   SKB's far-field code FARF31 as published in Norman and Kjellbert 1990 (SKB
   TR 90-01) and summarised in SKB R-04-51, section 3, with sorption on the
   fracture surfaces added as an option.

   THE EQUATIONS

   In the flowing water, with zeta the distance measured as accumulated water
   travel time (0 ... tw):

     Rf_i dc_i/dt = -dc_i/dzeta + (tw/Pe) d2c_i/dzeta2 + aw De_i dcp_i/dx|x=0
                    - lambda_i Rf_i c_i + lambda_(i-1) Rf_(i-1) c_(i-1),
     Rf_i = 1 + Ka_i aw,

   Ka the surface sorption coefficient (m3 of water per m2 of fracture
   surface, i.e. m; Ka = 0, Rf = 1 is FARF31's model), and in the rock
   matrix, 0 <= x <= x0:

     R_i dcp_i/dt = De_i d2cp_i/dx2 - R_i lambda_i cp_i
                    + R_(i-1) lambda_(i-1) cp_(i-1),     R_i = eps + Kd_i rho

   with cp = c at x = 0, dcp/dx = 0 at x = x0, zero initial concentrations,
   the flux Q (c - (tw/Pe) dc/dzeta) given at zeta = 0, c -> 0 far downstream,
   and the output the same flux at zeta = tw. Sorbed nuclides decay, and
   their daughters take up their own equilibrium, in the fracture as in the
   matrix.

   THE SOLUTION IN THE LAPLACE DOMAIN, AS MATRIX FUNCTIONS

   Transforming in t (variable s) and writing the chain as vectors, the matrix
   equation is cp'' = M cp with the lower bidiagonal

     M = De^-1 (s I + Lambda) R,

   Lambda the decay matrix (lambda_i on the diagonal, -lambda_(i-1) below it)
   and De, R, Rf diagonal. With cp(0) = c and cp'(x0) = 0 the flux into the
   rock is tau(M) c, tau(z) = sqrt(z) tanh(x0 sqrt(z)) (sqrt(z) for an
   infinite matrix). The fracture equation becomes (tw/Pe) c'' - c' - G c = 0
   with

     G = (s I + Lambda) Rf + aw De tau(M),

   and the transfer matrix from inlet flux to outlet flux is

     T(s) = H(G),     H(g) = exp((Pe/2) (1 - sqrt(1 + 4 tw g/Pe))).

   T_ij is the transform of the unit response of nuclide i to a unit pulse of
   nuclide j at the inlet (TR 90-01's C_f^{i,j} at zeta = tw). For one nuclide
   this is exp(Pe/2 (1 - sqrt(1 + 4 tw g/Pe))) with
   g = Rf (s + lambda) + aw sqrt(De R (s + lambda)) tanh(...). TR 90-01 writes
   the same solution as sums over exponentials whose coefficients (its P_ijk
   and Q_ijkl) carry the factors 1/(F_i - F_k) and 1/(h_i^2 - h_l^2); written
   as matrix functions, those are divided differences of H and of tau, which
   are evaluated here without cancellation also when two nuclides of one
   element have close decay constants, or the same one.

   Both matrices are lower triangular. tau(M) of the bidiagonal M is a table of
   divided differences of tau at the diagonal of M; H(G) is either Parlett's
   recurrence (well separated diagonal) or the sum over paths of products of
   G's off-diagonal entries and divided differences of H. Divided differences
   of close points come from Taylor series about the cluster's centre (the
   coefficients by power-series arithmetic), others from the recurrence split
   at the farthest pair.

   INVERSION

   The default: for each response and time, the saddle point s* of
   e^(st) T_ij(s) on the real axis (-d ln T/ds is the mean of the
   exponentially tilted response, so it decreases and the saddle is unique),
   found on a grid of ln T_ij right of the rightmost singularity, and the
   parabola s = s* + iy - kappa y^2 through it, kappa = psi''(s*)/(2t): the
   path of steepest descent to second order. Trapezoidal in y, the step
   halved until two sums agree and kept inside the strip of analyticity set by
   the nearest singularity. The terms are of the size of the answer, before a
   front (where the transform behaves like a delay) as well as after it. In a
   long tail the saddle nears the rightmost singularity, a branch point: the
   vertex then stays 1.5/t right of it and the focus on it (Hankel's
   contour). The fracture's transform reaches e^(Pe/2) at its own branch
   point and stays large near the real axis beyond it: the parabola is
   flattened until no member's transform grows along it, and its step follows
   the fastest turning phase along it. Under plug flow two halvings in a row
   must agree. A sample whose path does not converge comes from de Hoog's
   method when that agrees with itself at twice its terms. Every response is
   held to its mass balance (massBalance), and a run that misses says so.
   Alternatives: Talbot's fixed contour s = r theta (cot theta + i) (Abate and
   Valko 2004), scaled out to the saddle before a front, and de Hoog, Knight
   and Stokes (1982) on the Bromwich line, which is also the independent
   check.

   ONE GLOBAL: Farf31Model. Runs in a page, a Worker and Node; no DOM.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.Farf31Model = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const LN2 = Math.LN2;
  const PI = Math.PI;
  /* The activity conversion of FARF31's output files. Read off the reference
     outputs (Bq/a over mol/a, 7 digits, seven nuclides): Avogadro's number
     6.022045e23 (CODATA 1973) and a year of 365.2422 days. */
  const AVOGADRO = 6.022045e23;
  const YEAR_S = 365.2422 * 86400;
  const DEFAULT_DENSITY = 2700;
  const MAX_CHAIN = 16;

  class Farf31Error extends Error {
    constructor(message) { super(message); this.name = 'Farf31Error'; }
  }

  /* ======================================================================
     1. Complex arithmetic on two registers (no allocation in the hot loops)
     ====================================================================== */

  let RE = 0, IM = 0;

  function cdiv(ar, ai, br, bi) {
    if (Math.abs(br) >= Math.abs(bi)) {
      const r = bi / br, d = br + bi * r;
      RE = (ar + ai * r) / d; IM = (ai - ar * r) / d;
    } else {
      const r = br / bi, d = bi + br * r;
      RE = (ar * r + ai) / d; IM = (ai * r - ar) / d;
    }
  }

  /** Principal square root; the cut is the negative real axis. */
  function csqrt(ar, ai) {
    if (ai === 0) {
      if (ar >= 0) { RE = Math.sqrt(ar); IM = 0; } else { RE = 0; IM = Math.sqrt(-ar); }
      return;
    }
    const m = Math.hypot(ar, ai);
    if (ar >= 0) {
      const t = Math.sqrt(0.5 * (m + ar));
      RE = t; IM = ai / (2 * t);
    } else {
      const t = Math.sqrt(0.5 * (m - ar));
      RE = Math.abs(ai) / (2 * t); IM = ai >= 0 ? t : -t;
    }
  }

  function cexp(ar, ai) {
    const e = Math.exp(ar);
    RE = e * Math.cos(ai); IM = e * Math.sin(ai);
  }

  /** tanh, accurate for small arguments and safe for large ones. */
  function ctanh(ar, ai) {
    let sg = 1;
    if (ar < 0) { ar = -ar; ai = -ai; sg = -1; }
    if (ar > 18) {
      const e = 2 * Math.exp(-2 * ar);
      RE = sg * (1 - e * Math.cos(2 * ai)); IM = sg * (e * Math.sin(2 * ai));
      return;
    }
    const d = Math.cosh(2 * ar) + Math.cos(2 * ai);
    RE = sg * Math.sinh(2 * ar) / d; IM = sg * Math.sin(2 * ai) / d;
  }

  /** sech^2 = 1 - tanh^2 without the cancellation near tanh = 1. */
  function csech2(ar, ai) {
    if (ar < 0) { ar = -ar; ai = -ai; }
    // sech z = 2 e^-z / (1 + e^-2z)
    const e1 = Math.exp(-ar), e2 = e1 * e1;
    const wr = e2 * Math.cos(2 * ai), wi = -e2 * Math.sin(2 * ai);   // e^-2z
    const nr = 2 * e1 * Math.cos(ai), ni = -2 * e1 * Math.sin(ai);    // 2 e^-z
    cdiv(nr, ni, 1 + wr, wi);
    const sr = RE, si = IM;
    RE = sr * sr - si * si; IM = 2 * sr * si;
  }

  /* ======================================================================
     2. The parameters, checked and turned into per-nuclide constants
     ====================================================================== */

  function num(v) { return typeof v === 'number' ? v : Number(v); }

  /**
   * p = { tw, Pe, aw, eps, x0, rho, nuclides: [{ name, thalf, kd, ka, de, daughter }] }
   * `daughter` true: the next nuclide in the list is this one's daughter.
   * ka, the surface sorption coefficient of the fracture (m), is 0 when left out.
   * Pe may be Infinity (plug flow). x0 may be Infinity.
   */
  function prepare(p) {
    const nucs = p.nuclides || [];
    const N = nucs.length;
    if (N === 0) throw new Farf31Error('There are no nuclides.');
    const tw = num(p.tw), Pe = num(p.Pe), aw = num(p.aw), eps = num(p.eps);
    const x0 = num(p.x0), rho = p.rho == null ? DEFAULT_DENSITY : num(p.rho);
    if (!(tw > 0) || !isFinite(tw)) throw new Farf31Error('The travel time tw must be a positive number.');
    if (!(Pe > 0)) throw new Farf31Error('The Peclet number must be positive.');
    if (!(aw >= 0) || !isFinite(aw)) throw new Farf31Error('The flow-wetted surface aw must be zero or positive.');
    if (!(eps >= 0) || !isFinite(eps)) throw new Farf31Error('The matrix porosity must be zero or positive.');
    if (!(x0 >= 0)) throw new Farf31Error('The penetration depth must be zero or positive (Infinity allowed).');
    if (!(rho >= 0) || !isFinite(rho)) throw new Farf31Error('The rock density must be zero or positive.');
    const lam = new Float64Array(N), R = new Float64Array(N), De = new Float64Array(N);
    const ka = new Float64Array(N), rf = new Float64Array(N);
    const link = new Uint8Array(N), chainStart = new Int32Array(N);
    const names = [];
    for (let i = 0; i < N; i++) {
      const n = nucs[i];
      const th = num(n.thalf), kd = num(n.kd), de = num(n.de), kf = n.ka == null ? 0 : num(n.ka);
      names.push(String(n.name));
      if (!(th > 0)) throw new Farf31Error(`${n.name}: the half-life must be positive.`);
      if (!(kd >= 0) || !isFinite(kd)) throw new Farf31Error(`${n.name}: Kd must be zero or positive.`);
      if (!(kf >= 0) || !isFinite(kf)) throw new Farf31Error(`${n.name}: Ka must be zero or positive.`);
      if (!(de >= 0) || !isFinite(de)) throw new Farf31Error(`${n.name}: De must be zero or positive.`);
      lam[i] = isFinite(th) ? LN2 / th : 0;
      R[i] = eps + kd * rho;
      De[i] = de;
      ka[i] = kf;
      rf[i] = 1 + kf * aw;
      link[i] = i > 0 && nucs[i - 1].daughter ? 1 : 0;
      chainStart[i] = link[i] ? chainStart[i - 1] : i;
    }
    for (let i = 0; i < N; i++) {
      if (i - chainStart[i] + 1 > MAX_CHAIN) throw new Farf31Error(`A chain may have at most ${MAX_CHAIN} members.`);
    }
    // Is there any exchange with the matrix at all? In a chain it is all or
    // none: a member that does not diffuse (De = 0) or has no capacity
    // (eps + Kd rho = 0) would still hold and feed its daughters in the
    // matrix, which the matrix-function solution does not describe.
    const matrix = new Uint8Array(N);
    for (let i = 0; i < N; i++) matrix[i] = aw > 0 && De[i] > 0 && x0 > 0 && R[i] > 0 ? 1 : 0;
    for (let i = 1; i < N; i++) {
      if (link[i] && matrix[i] !== matrix[i - 1]) {
        const bad = matrix[i] ? names[i - 1] : names[i];
        throw new Farf31Error(`${bad} has no exchange with the matrix (De = 0, or porosity and Kd both 0) while the rest of its chain has: give it a small De, or a porosity.`);
      }
    }
    if (!isFinite(Pe)) {
      for (let i = 0; i < N; i++) {
        if (!matrix[i]) throw new Farf31Error('Pe = infinity (plug flow) needs matrix diffusion for every nuclide: without it the response is a delta function.');
        // Under plug flow a chain moves with one delay, Rf tw, taken out of the
        // transform; members that the fracture holds back differently would
        // each have their own.
        if (link[i] && Math.abs(rf[i] - rf[i - 1]) > 1e-12 * rf[i]) {
          throw new Farf31Error(`Pe = infinity (plug flow) needs the same fracture retardation 1 + Ka aw for every member of a chain: ${names[i - 1]} and ${names[i]} differ. Give a finite Peclet number.`);
        }
      }
    }
    return {
      N, names, lam, R, De, ka, rf, link, chainStart, matrix,
      tw, Pe, aw, eps, x0, rho, infPe: !isFinite(Pe), infX0: !isFinite(x0),
    };
  }

  /* ======================================================================
     3. The two scalar functions, their Taylor series and length scales

     tau(z) = sqrt(z) tanh(x0 sqrt(z)): the flux into the matrix per unit
     concentration, times De. H(g) = exp(phi(g)), phi the fracture exponent.
     For divided differences each needs a scale: points closer than a fraction
     of it are treated as a cluster (Taylor series about the centre), since
     their difference quotients would cancel.
     ====================================================================== */

  /** tau at z (complex), into RE/IM. */
  function tauAt(ctx, zr, zi) {
    csqrt(zr, zi);
    if (ctx.infX0) return;
    const ur = RE, ui = IM;
    ctanh(ctx.x0 * ur, ctx.x0 * ui);
    const tr = RE, ti = IM;
    RE = ur * tr - ui * ti; IM = ur * ti + ui * tr;
  }

  /** Length scale for tau near z: distance to the sqrt branch point and to the
      nearest pole of tanh(x0 sqrt z), z_n = -((n + 1/2) pi / x0)^2. */
  function tauScale(ctx, zr, zi) {
    let sc = Math.hypot(zr, zi);
    if (!ctx.infX0 && ctx.x0 > 0) {
      const a = PI / ctx.x0;
      let n0 = 0;
      if (zr < 0) n0 = Math.max(0, Math.floor(Math.sqrt(-zr) / a - 0.5));
      for (let n = Math.max(0, n0 - 1); n <= n0 + 1; n++) {
        const zp = -((n + 0.5) * a) * ((n + 0.5) * a);
        const d = Math.hypot(zr - zp, zi);
        if (d < sc) sc = d;
      }
    }
    return sc;
  }

  /** phi(g) into RE/IM, phi = (Pe/2)(1 - sqrt(1 + 4 tw g/Pe)) written
      without cancellation; for Pe = infinity phi = -tw (g - Rf s), (sr, si)
      being Rf s (the delay e^(-Rf tw s) is taken out and applied as a time
      shift, see pairDelay). */
  function phiAt(ctx, gr, gi, sr, si) {
    const tw = ctx.tw;
    if (ctx.infPe) { RE = -tw * (gr - sr); IM = -tw * (gi - si); return; }
    const B = 4 * tw / ctx.Pe;
    csqrt(1 + B * gr, B * gi);
    cdiv(-2 * tw * gr, -2 * tw * gi, 1 + RE, IM);
  }

  /** Length scale for H near g: 1/|phi'| and the distance to the branch point
      g* = -Pe/(4 tw), whichever is smaller. */
  function hScale(ctx, gr, gi) {
    const tw = ctx.tw;
    if (ctx.infPe) return 1 / tw;
    const B = 4 * tw / ctx.Pe;
    const S = Math.sqrt(Math.hypot(1 + B * gr, B * gi));   // |sqrt(1 + B g)|
    return Math.min(S / tw, S * S / B);
  }

  const BINOM_HALF = (function () {
    const b = new Float64Array(260);
    b[0] = 1;
    for (let n = 1; n < b.length; n++) b[n] = b[n - 1] * (0.5 - (n - 1)) / n;
    return b;
  }());

  /** Taylor coefficients of sqrt(A + B w) about w = 0, into cr/ci[0..K]. */
  function sqrtSeries(Ar, Ai, Br, Bi, K, cr, ci) {
    csqrt(Ar, Ai);
    const s0r = RE, s0i = IM;
    cdiv(Br, Bi, Ar, Ai);
    const qr = RE, qi = IM;           // B/A
    let pr = s0r, pi = s0i;           // sqrt(A) (B/A)^n
    for (let n = 0; n <= K; n++) {
      cr[n] = BINOM_HALF[n] * pr; ci[n] = BINOM_HALF[n] * pi;
      const t = pr * qr - pi * qi; pi = pr * qi + pi * qr; pr = t;
    }
  }

  /** Taylor coefficients of tau(c + w). Scratch: u, v arrays of length K+1. */
  function tauSeries(ctx, cr0, ci0, K, outR, outI, s1r, s1i, s2r, s2i, s3r, s3i) {
    // u = sqrt(c + w)
    sqrtSeries(cr0, ci0, 1, 0, K, s1r, s1i);
    if (ctx.infX0) {
      for (let n = 0; n <= K; n++) { outR[n] = s1r[n]; outI[n] = s1i[n]; }
      return;
    }
    const x0 = ctx.x0;
    // T = tanh(x0 u): T' = (1 - T^2) x0 u'. s2 = T, s3 = Q = 1 - T^2.
    ctanh(x0 * s1r[0], x0 * s1i[0]);
    s2r[0] = RE; s2i[0] = IM;
    csech2(x0 * s1r[0], x0 * s1i[0]);
    s3r[0] = RE; s3i[0] = IM;
    for (let n = 1; n <= K; n++) {
      let ar = 0, ai = 0;
      for (let k = 1; k <= n; k++) {
        const vr = k * x0 * s1r[k], vi = k * x0 * s1i[k];
        const qr = s3r[n - k], qi = s3i[n - k];
        ar += vr * qr - vi * qi; ai += vr * qi + vi * qr;
      }
      s2r[n] = ar / n; s2i[n] = ai / n;
      // Q_n = -sum_{i=0..n} T_i T_(n-i)
      let br = 0, bi = 0;
      for (let k = 0; k <= n; k++) {
        br += s2r[k] * s2r[n - k] - s2i[k] * s2i[n - k];
        bi += s2r[k] * s2i[n - k] + s2i[k] * s2r[n - k];
      }
      s3r[n] = -br; s3i[n] = -bi;
    }
    // tau = u T
    for (let n = 0; n <= K; n++) {
      let ar = 0, ai = 0;
      for (let k = 0; k <= n; k++) {
        ar += s1r[k] * s2r[n - k] - s1i[k] * s2i[n - k];
        ai += s1r[k] * s2i[n - k] + s1i[k] * s2r[n - k];
      }
      outR[n] = ar; outI[n] = ai;
    }
  }

  /** Taylor coefficients of exp(phi(c + w) + E). */
  function hSeries(ctx, cr0, ci0, sr, si, E, K, outR, outI, s1r, s1i) {
    const tw = ctx.tw;
    // phi series into s1
    if (ctx.infPe) {
      for (let n = 0; n <= K; n++) { s1r[n] = 0; s1i[n] = 0; }
      s1r[0] = -tw * (cr0 - sr); s1i[0] = -tw * (ci0 - si);
      if (K >= 1) s1r[1] = -tw;
    } else {
      const B = 4 * tw / ctx.Pe, half = ctx.Pe / 2;
      sqrtSeries(1 + B * cr0, B * ci0, B, 0, K, s1r, s1i);
      for (let n = 1; n <= K; n++) { s1r[n] *= -half; s1i[n] *= -half; }
      phiAt(ctx, cr0, ci0, sr, si);
      s1r[0] = RE; s1i[0] = IM;
    }
    cexp(s1r[0] + E, s1i[0]);
    outR[0] = RE; outI[0] = IM;
    for (let n = 1; n <= K; n++) {
      let ar = 0, ai = 0;
      for (let k = 1; k <= n; k++) {
        const pr = k * s1r[k], pi = k * s1i[k];
        const hr = outR[n - k], hi = outI[n - k];
        ar += pr * hr - pi * hi; ai += pr * hi + pi * hr;
      }
      outR[n] = ar / n; outI[n] = ai / n;
    }
  }

  /* ======================================================================
     4. Divided differences over subsets of points, robust for clusters

     f[z_S] for a set S (a bit mask over the points). A set whose points all
     lie in one cluster uses the Taylor series about the cluster centre c:

        f[z_0..z_m] = sum_(n>=m) f_n h_(n-m)(z_0 - c, ..., z_m - c),

     h_k the complete homogeneous symmetric polynomial. Any other set is split
     at its farthest pair (a, b): f[S] = (f[S\a] - f[S\b]) / (z_b - z_a), a
     quotient of well separated points.
     ====================================================================== */

  const LINK_FRAC = 0.3;      // points closer than this times the scale are linked
  const TAYLOR_FRAC = 0.5;    // and a cluster must fit in this radius

  function makeDD(nmax) {
    const size = 1 << nmax;
    const dd = {
      n: 0, kind: 0, sr: 0, si: 0, E: 0,
      zr: new Float64Array(nmax), zi: new Float64Array(nmax),
      fr: new Float64Array(nmax), fi: new Float64Array(nmax),
      sc: new Float64Array(nmax), cl: new Int32Array(nmax), seen: new Int32Array(nmax),
      dist: new Float64Array(nmax * nmax),
      memoR: new Float64Array(size), memoI: new Float64Array(size), memoG: new Uint32Array(size),
      gen: 1,
      // cluster data
      ncl: 0, clMask: new Int32Array(nmax), clCr: new Float64Array(nmax), clCi: new Float64Array(nmax),
      clOk: new Uint8Array(nmax), clK: new Int32Array(nmax),
      clCoefR: [], clCoefI: [],
      // scratch for series
      s1r: new Float64Array(262), s1i: new Float64Array(262), s2r: new Float64Array(262), s2i: new Float64Array(262),
      s3r: new Float64Array(262), s3i: new Float64Array(262),
      hR: new Float64Array(262), hI: new Float64Array(262),
    };
    for (let k = 0; k < nmax; k++) { dd.clCoefR.push(new Float64Array(262)); dd.clCoefI.push(new Float64Array(262)); }
    return dd;
  }

  function ddScale(ctx, dd, zr, zi) {
    return dd.kind === 0 ? tauScale(ctx, zr, zi) : hScale(ctx, zr, zi);
  }

  function ddSeries(ctx, dd, cr, ci, K, outR, outI) {
    if (dd.kind === 0) tauSeries(ctx, cr, ci, K, outR, outI, dd.s1r, dd.s1i, dd.s2r, dd.s2i, dd.s3r, dd.s3i);
    else hSeries(ctx, cr, ci, dd.sr, dd.si, dd.E, K, outR, outI, dd.s1r, dd.s1i);
  }

  /** Set up the points (values fr/fi already filled by the caller) and find
      the clusters. Returns true when there is any cluster (else a plain
      Newton table or Parlett recurrence is safe). */
  function ddSetup(ctx, dd, n) {
    dd.n = n;
    dd.gen++;
    if (dd.gen > 4e9) { dd.memoG.fill(0); dd.gen = 1; }
    for (let k = 0; k < n; k++) { dd.sc[k] = ddScale(ctx, dd, dd.zr[k], dd.zi[k]); dd.cl[k] = k; }
    let any = false;
    for (let a = 0; a < n; a++) {
      for (let b = a + 1; b < n; b++) {
        const dx = dd.zr[a] - dd.zr[b], dy = dd.zi[a] - dd.zi[b];
        const d = Math.sqrt(dx * dx + dy * dy);
        dd.dist[a * n + b] = d; dd.dist[b * n + a] = d;
        if (d <= LINK_FRAC * Math.min(dd.sc[a], dd.sc[b])) {
          any = true;
          // union: relabel b's cluster to a's
          const ca = dd.cl[a], cb = dd.cl[b];
          if (ca !== cb) for (let k = 0; k < n; k++) if (dd.cl[k] === cb) dd.cl[k] = ca;
        }
      }
    }
    dd.ncl = 0;
    if (!any) return false;
    // cluster masks and centres
    const seen = dd.seen;
    for (let k = 0; k < n; k++) seen[k] = -1;
    for (let k = 0; k < n; k++) {
      const root = dd.cl[k];
      if (seen[root] < 0) { seen[root] = dd.ncl; dd.clMask[dd.ncl] = 0; dd.ncl++; }
      const c = seen[root];
      dd.cl[k] = c;
      dd.clMask[c] |= 1 << k;
    }
    for (let c = 0; c < dd.ncl; c++) { dd.clOk[c] = 0; dd.clK[c] = -1; }
    return true;
  }

  /** f[z_mask] into RE/IM. */
  function ddGet(ctx, dd, mask) {
    if (dd.memoG[mask] === dd.gen) { RE = dd.memoR[mask]; IM = dd.memoI[mask]; return; }
    const n = dd.n;
    const lo = 31 - Math.clz32(mask & -mask), hi = 31 - Math.clz32(mask);
    let vr, vi;
    if (lo === hi) {
      vr = dd.fr[lo]; vi = dd.fi[lo];
    } else {
      // one cluster: the Taylor form, if the cluster allows
      let c0 = dd.ncl ? dd.cl[lo] : -1, cnt = 0;
      for (let m = mask; m; m &= m - 1) { cnt++; if (c0 >= 0 && dd.cl[31 - Math.clz32(m & -m)] !== c0) c0 = -1; }
      if (c0 >= 0 && ddTaylor(ctx, dd, mask, cnt, c0)) { vr = RE; vi = IM; } else {
        // Otherwise split at two separated points: the ends of the set when
        // they are in different clusters (a range then splits into ranges,
        // the Newton table), else the end and the point farthest from it.
        let a = lo, b = hi;
        if (dd.ncl && dd.cl[a] === dd.cl[b]) {
          let bd = -1, bb = -1;
          for (let m = mask; m; m &= m - 1) {
            const k = 31 - Math.clz32(m & -m);
            if (dd.cl[k] !== dd.cl[a] && dd.dist[a * n + k] > bd) { bd = dd.dist[a * n + k]; bb = k; }
          }
          if (bb < 0) {
            // one wide cluster: its farthest pair
            for (let m = mask; m; m &= m - 1) {
              const p = 31 - Math.clz32(m & -m);
              for (let m2 = m & (m - 1); m2; m2 &= m2 - 1) {
                const q = 31 - Math.clz32(m2 & -m2);
                if (dd.dist[p * n + q] > bd) { bd = dd.dist[p * n + q]; a = p; bb = q; }
              }
            }
          }
          b = bb;
        }
        ddGet(ctx, dd, mask & ~(1 << a));
        const xr = RE, xi = IM;
        ddGet(ctx, dd, mask & ~(1 << b));
        cdiv(xr - RE, xi - IM, dd.zr[b] - dd.zr[a], dd.zi[b] - dd.zi[a]);
        vr = RE; vi = IM;
      }
    }
    dd.memoR[mask] = vr; dd.memoI[mask] = vi; dd.memoG[mask] = dd.gen;
    RE = vr; IM = vi;
  }

  /** Taylor form for a set inside cluster c. False if the cluster is too wide
      for its series (then the caller splits). */
  function ddTaylor(ctx, dd, mask, cnt, c) {
    const m = cnt - 1;
    if (dd.clK[c] < 0) {
      // centre, radius and the terms needed, once per cluster
      const cm = dd.clMask[c];
      let cr = 0, ci = 0, k0 = 0;
      for (let k = 0; k < dd.n; k++) if (cm & (1 << k)) { cr += dd.zr[k]; ci += dd.zi[k]; k0++; }
      cr /= k0; ci /= k0;
      let rad = 0;
      for (let k = 0; k < dd.n; k++) if (cm & (1 << k)) rad = Math.max(rad, Math.hypot(dd.zr[k] - cr, dd.zi[k] - ci));
      const sc = ddScale(ctx, dd, cr, ci);
      const q = rad / sc;
      dd.clCr[c] = cr; dd.clCi[c] = ci;
      if (!(q <= TAYLOR_FRAC)) { dd.clOk[c] = 0; dd.clK[c] = 0; return false; }
      dd.clOk[c] = 1;
      // terms beyond the order: q^j C(j+m, m) < 1e-17 for the largest m in the cluster
      const mmax = k0 - 1;
      let extra = 2;
      if (q > 0) {
        let term = 1;
        for (extra = 1; extra < 240; extra++) {
          term *= q * (extra + mmax) / extra;
          if (term < 1e-17 && extra > 2) break;
        }
      }
      const K = Math.min(255, mmax + extra + 2);
      dd.clK[c] = K;
      ddSeries(ctx, dd, cr, ci, K, dd.clCoefR[c], dd.clCoefI[c]);
    }
    if (!dd.clOk[c]) return false;
    const K = dd.clK[c];
    const cr = dd.clCr[c], ci = dd.clCi[c];
    const L = K - m;                 // h_0 .. h_L
    const hR = dd.hR, hI = dd.hI;
    hR[0] = 1; hI[0] = 0;
    for (let j = 1; j <= L; j++) { hR[j] = 0; hI[j] = 0; }
    for (let mm = mask; mm; mm &= mm - 1) {
      const k = 31 - Math.clz32(mm & -mm);
      const wr = dd.zr[k] - cr, wi = dd.zi[k] - ci;
      for (let j = 1; j <= L; j++) {
        const pr = hR[j - 1], pi = hI[j - 1];
        hR[j] += wr * pr - wi * pi; hI[j] += wr * pi + wi * pr;
      }
    }
    const fr = dd.clCoefR[c], fi = dd.clCoefI[c];
    let sr = 0, si = 0;
    for (let j = L; j >= 0; j--) {
      const ar = fr[m + j], ai = fi[m + j];
      sr += ar * hR[j] - ai * hI[j]; si += ar * hI[j] + ai * hR[j];
    }
    RE = sr; IM = si;
    return true;
  }

  /* ======================================================================
     5. T(s) on a block of one chain

     evalBlock fills ws.Fr/Fi (n x n, row-major, local indices 0..n-1 for the
     global nuclides j..i) with e^E T(s), and ws.E; the corner entry
     (n-1, 0) is T_ij, and when the diagonal clusters only that entry is
     computed. The scale E makes the largest |H| on the diagonal one, so that
     nothing overflows; the caller multiplies by e^(st - E).
     ====================================================================== */

  function makeWorkspace(ctx) {
    const N = ctx.N;
    const nmax = Math.min(N, MAX_CHAIN);
    const nn = nmax * nmax;
    return {
      mr: new Float64Array(nmax), mi: new Float64Array(nmax),
      tr: new Float64Array(nmax), ti: new Float64Array(nmax),
      gr: new Float64Array(nmax), gi: new Float64Array(nmax),
      Dr: new Float64Array(nn), Di: new Float64Array(nn),     // tau divided differences D[q*n+p]
      Gr: new Float64Array(nn), Gi: new Float64Array(nn),
      Fr: new Float64Array(nn), Fi: new Float64Array(nn),
      E: 0,
      dd: makeDD(nmax),
      clustered: 0, evaluations: 0,
    };
  }

  function evalBlock(ctx, ws, sr, si, j, i) {
    const n = i - j + 1;
    const aw = ctx.aw;
    const dd = ws.dd;
    ws.evaluations++;
    // with plug flow the delay Rf tw s is taken out of phi (one Rf per chain)
    const rfc = ctx.infPe ? ctx.rf[j] : 1, dsr = sr * rfc, dsi = si * rfc;
    // diagonal: m_k, tau(m_k), g_k = Rf_k (s + lambda_k) + aw De_k tau(m_k)
    let phiMax = -Infinity;
    for (let p = 0; p < n; p++) {
      const k = j + p;
      const f = ctx.R[k] / ctx.De[k];
      let gr = ctx.rf[k] * (sr + ctx.lam[k]), gi = ctx.rf[k] * si;
      if (ctx.matrix[k]) {
        const mr = f * (sr + ctx.lam[k]), mi = f * si;
        ws.mr[p] = mr; ws.mi[p] = mi;
        tauAt(ctx, mr, mi);
        ws.tr[p] = RE; ws.ti[p] = IM;
        gr += aw * ctx.De[k] * RE; gi += aw * ctx.De[k] * IM;
      } else {
        ws.mr[p] = 0; ws.mi[p] = 0; ws.tr[p] = 0; ws.ti[p] = 0;
      }
      ws.gr[p] = gr; ws.gi[p] = gi;
      phiAt(ctx, gr, gi, dsr, dsi);
      if (RE > phiMax) phiMax = RE;
    }
    const E = isFinite(phiMax) ? -phiMax : 0;
    ws.E = E;
    const Gr = ws.Gr, Gi = ws.Gi;
    for (let p = 0; p < n; p++) {
      Gr[p * n + p] = ws.gr[p]; Gi[p * n + p] = ws.gi[p];
      for (let q = 0; q < p; q++) { Gr[p * n + q] = 0; Gi[p * n + q] = 0; }
    }
    if (n > 1) {
      // decay of the parent, dissolved and sorbed on the fracture surfaces
      for (let p = 1; p < n; p++) Gr[p * n + p - 1] -= ctx.lam[j + p - 1] * ctx.rf[j + p - 1];
      // matrix coupling: aw De_p tau(M)_pq, tau(M)_pq = prod(sub) * tau[m_q..m_p]
      let anyMatrix = false;
      for (let p = 0; p < n; p++) if (ctx.matrix[j + p]) { anyMatrix = true; break; }
      if (anyMatrix) {
        const Dr = ws.Dr, Di = ws.Di;
        dd.kind = 0;
        for (let p = 0; p < n; p++) {
          dd.zr[p] = ws.mr[p]; dd.zi[p] = ws.mi[p]; dd.fr[p] = ws.tr[p]; dd.fi[p] = ws.ti[p];
        }
        const clustered = ddSetup(ctx, dd, n);
        if (clustered) ws.clustered++;
        for (let q = 0; q < n; q++) { Dr[q * n + q] = ws.tr[q]; Di[q * n + q] = ws.ti[q]; }
        for (let d = 1; d < n; d++) {
          for (let q = 0; q + d < n; q++) {
            const p = q + d;
            if (clustered) {
              let mask = 0;
              for (let k = q; k <= p; k++) mask |= 1 << k;
              ddGet(ctx, dd, mask);
            } else {
              cdiv(Dr[(q + 1) * n + p] - Dr[q * n + p - 1], Di[(q + 1) * n + p] - Di[q * n + p - 1],
                ws.mr[p] - ws.mr[q], ws.mi[p] - ws.mi[q]);
            }
            Dr[q * n + p] = RE; Di[q * n + p] = IM;
          }
        }
        for (let p = 1; p < n; p++) {
          const kp = j + p;
          if (!ctx.matrix[kp]) continue;
          let prod = aw * ctx.De[kp];
          for (let q = p - 1; q >= 0; q--) {
            const kl = j + q + 1;   // M_{kl, kl-1}
            prod *= -ctx.R[kl - 1] * ctx.lam[kl - 1] / ctx.De[kl];
            if (!ctx.matrix[j + q]) break;   // a member without matrix breaks the matrix chain
            Gr[p * n + q] += prod * Dr[q * n + p];
            Gi[p * n + q] += prod * Di[q * n + p];
          }
        }
      }
    }
    // F = H(G), scaled by e^E
    hMatrix(ctx, ws, n, dsr, dsi, E);
  }

  /** F = exp(phi(G) + E) for the lower-triangular n x n block in ws.G; (sr, si)
      is Rf s under plug flow (see phiAt), unused otherwise. */
  function hMatrix(ctx, ws, n, sr, si, E) {
    const Gr = ws.Gr, Gi = ws.Gi, Fr = ws.Fr, Fi = ws.Fi, dd = ws.dd;
    dd.kind = 1; dd.sr = sr; dd.si = si; dd.E = E;
    for (let p = 0; p < n; p++) {
      const gr = Gr[p * n + p], gi = Gi[p * n + p];
      dd.zr[p] = gr; dd.zi[p] = gi;
      phiAt(ctx, gr, gi, sr, si);
      cexp(RE + E, IM);
      dd.fr[p] = RE; dd.fi[p] = IM;
      Fr[p * n + p] = RE; Fi[p * n + p] = IM;
    }
    if (n === 1) return;
    const clustered = ddSetup(ctx, dd, n);
    if (!clustered) {
      // Parlett: F_pq (g_p - g_q) = G_pq (F_pp - F_qq) + sum_k (F_pk G_kq - G_pk F_kq)
      for (let d = 1; d < n; d++) {
        for (let q = 0; q + d < n; q++) {
          const p = q + d;
          let ar = Gr[p * n + q] * (Fr[p * n + p] - Fr[q * n + q]) - Gi[p * n + q] * (Fi[p * n + p] - Fi[q * n + q]);
          let ai = Gr[p * n + q] * (Fi[p * n + p] - Fi[q * n + q]) + Gi[p * n + q] * (Fr[p * n + p] - Fr[q * n + q]);
          for (let k = q + 1; k < p; k++) {
            const g1r = Gr[p * n + k], g1i = Gi[p * n + k], f1r = Fr[k * n + q], f1i = Fi[k * n + q];
            const f2r = Fr[p * n + k], f2i = Fi[p * n + k], g2r = Gr[k * n + q], g2i = Gi[k * n + q];
            ar += f2r * g2r - f2i * g2i - (g1r * f1r - g1i * f1i);
            ai += f2r * g2i + f2i * g2r - (g1r * f1i + g1i * f1r);
          }
          cdiv(ar, ai, Gr[p * n + p] - Gr[q * n + q], Gi[p * n + p] - Gi[q * n + q]);
          Fr[p * n + q] = RE; Fi[p * n + q] = IM;
        }
      }
      return;
    }
    ws.clustered++;
    // Sum over paths 0 = k0 < k1 < ... < km = n-1 of prod G_(k_(l+1), k_l) * H[g_k0..g_km]:
    // the corner entry, the only one the inversions use (the others are left unset).
    Fr[(n - 1) * n] = 0; Fi[(n - 1) * n] = 0;
    pathVisit(ctx, ws, n, 0, 1, 1, 0);
  }

  function pathVisit(ctx, ws, n, k, mask, pr, pi) {
    const Gr = ws.Gr, Gi = ws.Gi, Fr = ws.Fr, Fi = ws.Fi, dd = ws.dd;
    if (k === n - 1) {
      ddGet(ctx, dd, mask);
      Fr[k * n] += pr * RE - pi * IM;
      Fi[k * n] += pr * IM + pi * RE;
      return;
    }
    for (let l = k + 1; l < n; l++) {
      const er = Gr[l * n + k], ei = Gi[l * n + k];
      if (er === 0 && ei === 0) continue;
      pathVisit(ctx, ws, n, l, mask | (1 << l), pr * er - pi * ei, pr * ei + pi * er);
    }
  }

  /** T_ij(s) for real or complex s, unscaled, as [re, im] (for tests and the
      real-axis grid). */
  function transfer(ctx, ws, sr, si, i, j) {
    evalBlock(ctx, ws, sr, si, j, i);
    const n = i - j + 1;
    const f = Math.exp(-ws.E);
    return [ws.Fr[(n - 1) * n] * f, ws.Fi[(n - 1) * n] * f];
  }

  /* ======================================================================
     6. Numerical inversion

     A "pair" is (i, j): the response of nuclide i to a unit pulse of j. With
     Pe = infinity the transform lacks its delay e^(-Rf tw s) (see phiAt) and
     every time is shifted by Rf tw here.
     ====================================================================== */

  /** The delay taken out of T_ij: Rf tw under plug flow (one Rf per chain,
      see prepare), none otherwise. */
  function pairDelay(ctx, i, j) {
    return ctx.infPe ? ctx.tw * ctx.rf[j] : 0;
  }

  const M_DEFAULT = 28;        // Talbot nodes for the default contour
  const TALBOT_M_MAX = 96;    // the most nodes the fixed contour takes when scaled out to the saddle

  /** tau on the real axis, for real z (negative z: -|u| tan(x0 |u|)). */
  function tauReal(ctx, z) {
    if (z >= 0) { const u = Math.sqrt(z); return ctx.infX0 ? u : u * Math.tanh(ctx.x0 * u); }
    const u = Math.sqrt(-z);
    return ctx.infX0 ? NaN : -u * Math.tan(ctx.x0 * u);
  }

  /** The rightmost singularity of T_ij(s): every singularity of the block's
      transforms lies on the real axis at or left of it. Per member: the
      branch point s = -lambda of an infinite matrix, the first pole of
      tanh(x0 sqrt(m)) of a finite one, and the branch point of
      sqrt(1 + 4 tw g/Pe), g(s) = -Pe/(4 tw), whichever comes first. */
  function rightmostSingularity(ctx, j, i) {
    let s0 = -Infinity;
    for (let k = j; k <= i; k++) {
      const lam = ctx.lam[k];
      let sk;
      if (!ctx.matrix[k]) {
        // g = Rf (s + lambda) = -Pe/(4 tw)
        sk = ctx.infPe ? -Infinity : -lam - ctx.Pe / (4 * ctx.tw * ctx.rf[k]);
      } else if (ctx.infX0) {
        sk = -lam;
      } else {
        const f = ctx.R[k] / ctx.De[k];
        const pole = -lam - (PI / (2 * ctx.x0)) * (PI / (2 * ctx.x0)) / f;
        if (ctx.infPe) sk = pole;
        else {
          // g(s) = Rf (s + lam) + aw De tau(f (s + lam)) rises from -inf at the pole to 0 at -lam
          const gs = -ctx.Pe / (4 * ctx.tw);
          let a = pole, b = -lam;
          for (let it = 0; it < 200 && b - a > 1e-15 * Math.max(Math.abs(a), Math.abs(b)); it++) {
            const c = 0.5 * (a + b);
            const g = ctx.rf[k] * (c + lam) + ctx.aw * ctx.De[k] * tauReal(ctx, f * (c + lam));
            if (g > gs) b = c; else a = c;
          }
          sk = b;
        }
      }
      if (sk > s0) s0 = sk;
    }
    return s0;
  }

  /**
   * ln T_ij(s) on the real axis right of the rightmost singularity s0, on a
   * grid geometric in x = s - s0, from where T_ij underflows down toward s0
   * (see below for where the scan stops), refined where D changes faster than
   * the saddles' widths. D (at the midpoints) is the tilted mean, the mean
   * arrival time of e^(-st) h_ij(t); it falls with s, and the saddle for time
   * t is where D = t.
   */
  function realAxis(ctx, ws, i, j, tLo, tHi) {
    const n = i - j + 1, idx = (n - 1) * n;
    const s0 = rightmostSingularity(ctx, j, i);
    const fac = Math.pow(10, 1 / 8);
    const psiAt = (s) => {
      evalBlock(ctx, ws, s, 0, j, i);
      const F = ws.Fr[idx];
      return F > 0 && isFinite(F) ? Math.log(F) - ws.E : -Infinity;
    };
    const x0 = Math.max(Math.abs(s0), 0) + 1 / tHi;
    const up = [], dn = [];
    for (let x = x0, k = 0; k < 800; x *= fac, k++) {
      const p = psiAt(s0 + x);
      up.push([s0 + x, p]);
      if (p < -900 || x > 1e12 / tLo) break;
    }
    // Toward s0 the tilted mean D grows without bound. w = s D + psi(s) there
    // is the Chernoff bound: the part of h_ij after the time D is at most e^w
    // (s < 0), and w is largest, ln T_ij(0), at s = 0. The scan stops where
    // that part is negligible, where D passes 10 tHi, and where D no longer
    // grows: psi is convex (h_ij >= 0), so a D that does not grow is
    // rounding, s0 + x keeping few digits of x and the transform cancelling
    // next to its singularity. Such a D once stopped every saddle search.
    const Dof = (a, b) => -(b[1] - a[1]) / (b[0] - a[0]);
    let wmax = -Infinity;
    for (let k = 0; k + 1 < up.length; k++) {
      const w = 0.5 * (up[k][0] + up[k + 1][0]) * Dof(up[k], up[k + 1]) + 0.5 * (up[k][1] + up[k + 1][1]);
      if (w > wmax) wmax = w;
    }
    let prev = up[0], Dprev = up.length > 1 ? Dof(up[0], up[1]) : 0;
    for (let x = x0 / fac, k = 0; k < 800; x /= fac, k++) {
      const s = s0 + x;
      if (!(s > s0)) break;
      const p = psiAt(s);
      if (!isFinite(p)) break;
      const D = Dof([s, p], prev);
      if (!(D > Dprev)) break;
      dn.push([s, p]);
      const w = 0.5 * (s + prev[0]) * D + 0.5 * (p + prev[1]);
      if (w > wmax) wmax = w;
      prev = [s, p]; Dprev = D;
      if (D > 10 * tHi || x < 1e-13 * Math.max(Math.abs(s0), 1 / tHi) || w < wmax - 120) break;
    }
    let pts = dn.reverse().concat(up);
    // A grid geometric in s - s0 steps by about |s0|/3 near s = 0: when the
    // singularity lies far out (under plug flow, the first pole of tanh at
    // -1e5 and more) the saddles of every time the response lives at fall
    // between two of its points. Add s = +-e, e geometric from 1/tHi, on
    // either side of 0 (on the left no nearer s0 than half way).
    {
      const extra = [];
      const eHi = Math.max(pts[pts.length - 1][0], 0), eLeft = 0.5 * Math.abs(s0);
      for (let e = 1 / tHi; e < Math.max(eHi, eLeft); e *= fac) {
        if (e < eHi) extra.push(e);
        if (e < eLeft) extra.push(-e);
      }
      if (extra.length) {
        const have = pts.map((q) => q[0]);
        const lo0 = have[0], step = (a, b) => Math.abs(a - b) < 1e-6 * Math.max(Math.abs(a), Math.abs(b), 1 / tHi);
        for (const e of extra) {
          if (!(e > lo0) || have.some((h) => step(h, e))) continue;
          const pv = psiAt(e);
          if (isFinite(pv)) pts.push([e, pv]);
        }
        pts.sort((a, b) => a[0] - b[0]);
        // keep the tilted mean positive and falling (rounding next to s0, or
        // a point too close to its neighbour, would stop every saddle search)
        const kept = [pts[0]];
        for (let k = 1; k < pts.length; k++) {
          const Dn = Dof(kept[kept.length - 1], pts[k]);
          if (!(Dn > 0) || (kept.length >= 2 && !(Dn < Dof(kept[kept.length - 2], kept[kept.length - 1])))) continue;
          kept.push(pts[k]);
        }
        pts = kept;
      }
    }
    // Resolve the saddles: where D falls from one interval to the next by
    // more than the tilted spread allows (psi'' span^2 > 1, the span wider
    // than the Gaussian's width in s), put a node between, as far as the
    // response matters (w within 80 of its top). A broad response would
    // otherwise have its saddles placed far off, with terms e^10 and more
    // larger than the answer.
    for (let pass = 0; pass < 14 && pts.length < 4000; pass++) {
      const out = [pts[0]];
      let added = false;
      for (let k = 0; k + 1 < pts.length; k++) {
        const a = pts[k], b = pts[k + 1];
        const Dk = Dof(a, b);
        const Dl = k > 0 ? Dof(pts[k - 1], a) : NaN, Dr = k + 2 < pts.length ? Dof(b, pts[k + 2]) : NaN;
        const drop = Math.max(isFinite(Dl) ? Dl - Dk : 0, isFinite(Dr) ? Dk - Dr : 0);
        const w = 0.5 * (a[0] + b[0]) * Dk + 0.5 * (a[1] + b[1]);
        if (drop * (b[0] - a[0]) > 1 && w > wmax - 80) {
          const sMid = s0 + Math.sqrt((a[0] - s0) * (b[0] - s0));
          if (sMid > a[0] && sMid < b[0]) {
            const p = psiAt(sMid);
            if (isFinite(p)) { out.push([sMid, p]); added = true; }
          }
        }
        out.push(b);
      }
      pts = out;
      if (!added) break;
    }
    const K = pts.length;
    const s = new Float64Array(K), psi = new Float64Array(K);
    for (let k = 0; k < K; k++) { s[k] = pts[k][0]; psi[k] = pts[k][1]; }
    const sm = new Float64Array(Math.max(0, K - 1)), D = new Float64Array(Math.max(0, K - 1));
    for (let k = 0; k + 1 < K; k++) {
      sm[k] = s0 + Math.sqrt((s[k] - s0) * (s[k + 1] - s0));
      D[k] = isFinite(psi[k + 1]) && isFinite(psi[k]) ? -(psi[k + 1] - psi[k]) / (s[k + 1] - s[k]) : NaN;
    }
    return { i, j, s0, s, psi, sm, D };
  }

  /** The saddle of e^(st) T_ij(s) for time t: s with D(s) = t, psi'' there and
      w = s t + psi(s), the estimate of ln h(t). `beyond`: the saddle lies
      where T_ij underflows (h negligible). `edge`: t exceeds the tilted mean
      at the grid's first point, the saddle is taken there. */
  function saddleAt(ax, t) {
    const D = ax.D, sm = ax.sm, K = D.length, s0 = ax.s0;
    if (K < 2) return null;
    let k = 0;
    while (k < K && !(D[k] <= t)) {
      if (!isFinite(D[k]) && k > 0) break;
      k++;
    }
    if (k === 0) {
      const psi2 = (D[0] - D[1]) / (sm[1] - sm[0]);
      return { s: sm[0], psi2, w: sm[0] * t + ax.psi[0], edge: true, beyond: false };
    }
    if (k >= K || !isFinite(D[k])) return { s: sm[Math.min(k, K) - 1], psi2: NaN, w: -Infinity, edge: false, beyond: true };
    const a = k - 1, b = k;
    const la = Math.log(D[a]), lb = Math.log(D[b]);
    const f = (la - Math.log(t)) / (la - lb);
    const xa = sm[a] - s0, xb = sm[b] - s0;
    const ss = s0 + xa * Math.pow(xb / xa, f);
    const psi2 = (D[a] - D[b]) / (sm[b] - sm[a]);
    // psi(ss): from node b (between sm[a] and sm[b]), trapezoid on D
    const psi = ax.psi[b] + (ax.s[b] - ss) * 0.5 * (t + D[b]);
    return { s: ss, psi2, w: ss * t + psi, edge: false, beyond: false };
  }

  /** psi = ln T_ij on the real axis at s (NaN where T_ij is not positive). */
  function psiReal(ctx, ws, ax, s) {
    const n = ax.i - ax.j + 1, idx = (n - 1) * n;
    evalBlock(ctx, ws, s, 0, ax.j, ax.i);
    const F = ws.Fr[idx];
    return F > 0 && isFinite(F) ? Math.log(F) - ws.E : NaN;
  }

  /** psi, the tilted mean D = -psi' and psi'' at s, by central differences
      a thousandth of s - s0 apart, or a tenth of `scale` (the saddle's own
      width) when that is less. */
  function localAxis(ctx, ws, ax, s, scale) {
    const dl = Math.min(1e-3 * (s - ax.s0), scale > 0 ? 0.1 * scale : Infinity);
    const pm = psiReal(ctx, ws, ax, s - dl), p0 = psiReal(ctx, ws, ax, s), pp = psiReal(ctx, ws, ax, s + dl);
    return { psi: p0, D: (pm - pp) / (2 * dl), psi2: (pp - 2 * p0 + pm) / (dl * dl) };
  }

  /** ln |H(g_k(s))|, the size of member k's own transform at s. */
  function lnHk(ctx, k, sr, si, rfc) {
    let gr = ctx.rf[k] * (sr + ctx.lam[k]), gi = ctx.rf[k] * si;
    if (ctx.matrix[k]) {
      const f = ctx.R[k] / ctx.De[k];
      tauAt(ctx, f * (sr + ctx.lam[k]), f * si);
      gr += ctx.aw * ctx.De[k] * RE; gi += ctx.aw * ctx.De[k] * IM;
    }
    phiAt(ctx, gr, gi, rfc * sr, rfc * si);
    return RE;
  }

  /** Whether, along s = v + iY - kappa Y^2, no member's own transform times
      e^(st) grows above lev[k]. The fracture's transform reaches e^(Pe/2) at
      its branch point, g = -Pe/(4 tw), and is large near the real axis on
      the far side of it; a parabola that bends too fast passes there low, and
      its terms, far larger than the answer, cancel to rounding. */
  function clearsRidge(ctx, ax, v, t, kappa, lev, levMin) {
    let ymax;
    if (ctx.infPe) {
      // plug flow: the transform exp(-tw aw De tau) has essential
      // singularities at the poles of tanh, large just right of each; look
      // as far as e^(st) takes 80 off the vertex
      ymax = Math.sqrt(80 / (t * kappa));
    } else {
      // |H| <= e^(Pe/2): where t Re s + Pe/2 stays below the levels nothing
      // can grow, and beyond ymax, t Re s + Pe/2 < levMin - 40
      if (t * v + ctx.Pe / 2 <= levMin) return true;
      ymax = Math.sqrt((t * v + ctx.Pe / 2 - levMin + 40) / (t * kappa));
    }
    const rfc = ctx.infPe ? ctx.rf[ax.j] : 1;
    for (let q = 1; q <= 96; q++) {
      const Y = ymax * q / 96, sr = v - kappa * Y * Y;
      for (let k = ax.j; k <= ax.i; k++) if (t * sr + lnHk(ctx, k, sr, Y, rfc) > lev[k - ax.j]) return false;
    }
    return true;
  }

  /** How fast, at most, the phase of any member's own transform times e^(st)
      turns along s = v + iY - kappa Y^2 (per unit Y), over the stretch where
      its size is above e^floor. Next to the fracture's branch point the
      transform turns at (Pe/2) |d sqrt(1 + 4 tw g/Pe)/ds|, fast when Pe is
      large, and a member that the saddle of a daughter's response does not
      hold still turns at |t - D_k|: the trapezoidal step must follow both,
      or its sums alias them, two halvings agreeing on the wrong value. */
  function pathFrequency(ctx, ax, v, t, kappa, floor) {
    const rfc = ctx.infPe ? ctx.rf[ax.j] : 1;
    const ymax = Math.sqrt(Math.max(0, (t * v - floor + (ctx.infPe ? 40 : ctx.Pe / 2 + 40)) / (t * kappa)));
    let wmax = 0;
    for (let q = 0; q <= 96; q++) {
      const Y = ymax * q / 96, sr = v - kappa * Y * Y, si = Y;
      for (let k = ax.j; k <= ax.i; k++) {
        const zr0 = sr + ctx.lam[k];
        let gr = ctx.rf[k] * zr0, gi = ctx.rf[k] * si, dgr = ctx.rf[k], dgi = 0;
        if (ctx.matrix[k]) {
          const f = ctx.R[k] / ctx.De[k], c = ctx.aw * ctx.De[k];
          const zr = f * zr0, zi = f * si;
          csqrt(zr, zi);
          const ur = RE, ui = IM;
          let tr = ur, ti = ui, dr, di;          // tau and tau'
          cdiv(0.5, 0, ur, ui);                   // 1/(2 sqrt z)
          const hr = RE, hi = IM;
          if (ctx.infX0) { dr = hr; di = hi; } else {
            ctanh(ctx.x0 * ur, ctx.x0 * ui);
            const thr = RE, thi = IM;
            tr = ur * thr - ui * thi; ti = ur * thi + ui * thr;
            csech2(ctx.x0 * ur, ctx.x0 * ui);
            dr = thr * hr - thi * hi + 0.5 * ctx.x0 * RE; di = thr * hi + thi * hr + 0.5 * ctx.x0 * IM;
          }
          gr += c * tr; gi += c * ti; dgr += c * f * dr; dgi += c * f * di;
        }
        phiAt(ctx, gr, gi, rfc * sr, rfc * si);
        if (t * sr + RE < floor) continue;
        // phi'(s) = dphi/dg g'(s): -tw/sqrt(1 + 4 tw g/Pe), or -tw (g' - Rf) under plug flow
        let pr, pi;
        if (ctx.infPe) { pr = -ctx.tw * (dgr - rfc); pi = -ctx.tw * dgi; } else {
          const B = 4 * ctx.tw / ctx.Pe;
          csqrt(1 + B * gr, B * gi);
          cdiv(-ctx.tw, 0, RE, IM);
          pr = RE * dgr - IM * dgi; pi = RE * dgi + IM * dgr;
        }
        // d(phase)/dY = Im[(t + phi'(s)) (i - 2 kappa Y)]
        const w = Math.abs((t + pr) - 2 * kappa * Y * pi);
        if (w > wmax) wmax = w;
      }
    }
    return wmax;
  }

  /** One term of the parabola sum at Y: returns the modulus, adds to acc. */
  function parabolaTerm(ctx, ws, i, j, t, ss, kappa, Y, wgt, acc) {
    const n = i - j + 1, idx = (n - 1) * n;
    const sr = ss - kappa * Y * Y, si = Y;
    evalBlock(ctx, ws, sr, si, j, i);
    const Fr = ws.Fr[idx], Fi = ws.Fi[idx];
    const ex = t * sr - ws.E;
    if (ex > 700) { acc.bad = true; return Infinity; }
    if (ex < -740 || (Fr === 0 && Fi === 0)) return 0;
    cexp(ex, t * si);
    const er = RE, ei = IM;
    const ar = er * Fr - ei * Fi, ai = er * Fi + ei * Fr;
    const q = 2 * kappa * Y;                       // (1 + i q)
    const zr = ar - ai * q, zi = ai + ar * q;
    acc.h += wgt * zr;
    const yr = sr * zr - si * zi, yi = sr * zi + si * zr;   // s z
    acc.dh += wgt * yr;
    acc.d2 += wgt * (sr * yr - si * yi);
    acc.abs += wgt * Math.hypot(zr, zi);
    return Math.hypot(zr, zi);
  }

  /** Trapezoidal sum over Y = off, off + 2 step, ... (off = 0 or step), until
      the terms die out. Terms that grow back, after they have fallen away,
      to within 1e-3 of the largest, or past it, mean the path runs into a
      region where the transform is large: `regrow`. The terms' envelope is
      the largest of the last seven, so that a dip (the transform passing
      near a zero) is not taken for a fall. */
  function parabolaSweep(ctx, ws, i, j, t, ss, kappa, step, off, acc) {
    let maxMod = 0, minEnv = Infinity, small = 0;
    const last = [0, 0, 0, 0, 0, 0, 0];
    for (let k = 0; k < 20000; k++) {
      const Y = off + k * (off ? 2 * step : step);
      if (Y === 0) {
        const m = parabolaTerm(ctx, ws, i, j, t, ss, kappa, 0, 0.5, acc);
        maxMod = Math.max(maxMod, m);
        continue;
      }
      const m = parabolaTerm(ctx, ws, i, j, t, ss, kappa, Y, 1, acc);
      if (k > 3 && (m > 100 * maxMod || (minEnv < 1e-6 * maxMod && m > 1e-3 * maxMod))) { acc.regrow = true; break; }
      if (m > maxMod) maxMod = m;
      last[k % 7] = m;
      if (k >= 7) minEnv = Math.min(minEnv, Math.max(...last));
      if (m <= 1e-18 * maxMod) { if (++small >= 3 && k > 3) return; } else small = 0;
      if (acc.bad) return;
      if (ws.evaluations > acc.stop) break;
    }
    // out of nodes or budget before the terms died out: the sum is cut short
    acc.cut = true;
  }

  const VERTEX_BETA = 1.5;    // the vertex at least 1.5/t right of the rightmost singularity

  /**
   * h_ij(t), h_ij'(t) and h_ij''(t) on a parabola s(Y) = v + iY - kappa Y^2.
   *
   * The vertex v is the saddle s* of e^(st) T_ij(s) on the real axis
   * (polished by Newton's method on D(s) = t), or 1.5/t right of the
   * rightmost singularity s0 when the saddle lies closer to it: next to a
   * branch point the integrand is then at most e^1.5 larger, and the step
   * can be of the order of 1/t rather than the saddle's distance to s0.
   *
   * kappa = psi''(v)/(2t) makes the path the steepest descent to second
   * order (exact for advection and dispersion alone, whose integrand it
   * turns into a Gaussian in Y). It is at least 1/(4(v - s0)), which puts
   * the parabola's focus at s0 so that the path wraps a branch point there
   * as Hankel's contour does. It is reduced until no member's transform
   * grows along the path (see clearsRidge), and again should the terms,
   * once fallen away, grow on.
   *
   * Trapezoidal in Y, the step halved until two sums agree.
   * Returns { h, dh, d2, err, cond, nodes, s, kappa }.
   */
  function invertParabola(ctx, ws, ax, t, opt) {
    let tt = t;
    if (ctx.infPe) { tt = t - pairDelay(ctx, ax.i, ax.j); if (!(tt > 0)) return { h: 0, dh: 0, d2: 0, err: 0, cond: 1, nodes: 0 }; }
    const rtol = (opt && opt.rtol) || 1e-10;
    const atol = (opt && opt.atol) || 0;
    const maxEval = (opt && opt.maxEval) || 6000;
    const sad = saddleAt(ax, tt);
    if (!sad || sad.beyond || sad.w < -720) return { h: 0, dh: 0, d2: 0, err: 0, cond: 1, nodes: 0, negligible: true };
    const n0 = ws.evaluations;
    const vMin = ax.s0 + VERTEX_BETA / tt;
    let v = Math.max(sad.s, vMin);
    // the differences on the scale of the saddle's own width (the distance to
    // s0 can be 1e5 times larger, under plug flow with a finite matrix)
    const scale = Math.min(1 / tt, isFinite(sad.psi2) && sad.psi2 > 0 ? 1 / Math.sqrt(sad.psi2) : Infinity);
    let loc = localAxis(ctx, ws, ax, v, scale);
    for (let it = 0; it < 3 && v > vMin && loc.psi2 > 0 && Math.abs(loc.D - tt) > 0.5 * Math.sqrt(loc.psi2); it++) {
      const vn = Math.max(v + (loc.D - tt) / loc.psi2, vMin);
      const ln = localAxis(ctx, ws, ax, vn, scale);
      if (!(Math.abs(ln.D - tt) < Math.abs(loc.D - tt)) || !(ln.psi2 > 0)) break;
      v = vn; loc = ln;
    }
    let psi2 = loc.psi2;
    if (!(psi2 > 0) || !isFinite(psi2)) psi2 = isFinite(sad.psi2) && sad.psi2 > 0 ? sad.psi2 : tt * tt;
    const wv = isFinite(loc.psi) ? tt * v + loc.psi : sad.w;
    const omega = isFinite(loc.D) ? Math.abs(tt - loc.D) : 0;
    let kappa = Math.max(psi2 / (2 * tt), 0.25 / (v - ax.s0));
    if (!ctx.infPe || !ctx.infX0) {
      // each member may grow along the path to its own size at the vertex or
      // to the answer's, whichever is larger (under plug flow with an
      // infinite matrix nothing grows: exp(-tw aw sqrt(De R s)))
      const lev = [];
      let levMin = Infinity;
      const rfc = ctx.infPe ? ctx.rf[ax.j] : 1;
      for (let k = ax.j; k <= ax.i; k++) {
        const L = Math.max(tt * v + lnHk(ctx, k, v, 0, rfc), wv) + 2;
        lev.push(L); levMin = Math.min(levMin, L);
      }
      for (let k = 0; k < 16 && !clearsRidge(ctx, ax, v, tt, kappa, lev, levMin); k++) kappa /= 4;
    }
    let res = null;
    for (let attempt = 0; attempt < 4; attempt++) {
      const wPath = ctx.infPe ? omega : Math.max(omega, pathFrequency(ctx, ax, v, tt, kappa, wv - 25));
      res = parabolaSums(ctx, ws, ax, tt, v, kappa, psi2, wPath, rtol, atol, n0 + maxEval);
      if (!res.regrow) break;
      kappa /= 8;
    }
    if (res.regrow) return { h: NaN, dh: NaN, d2: NaN, err: Infinity, cond: Infinity, nodes: ws.evaluations - n0 };
    res.nodes = ws.evaluations - n0;
    return res;
  }

  /** The trapezoidal sums of invertParabola for one parabola. */
  function parabolaSums(ctx, ws, ax, tt, ss, kappa, psi2, omega, rtol, atol, stop) {
    // A Gaussian e^(-psi'' Y^2/2) is integrated to about 1e-7 at this step and
    // to rounding at half of it (the error goes as exp(-2 pi^2/(psi'' step^2)));
    // four nodes to a turn of the fastest phase along the path (a vertex off
    // the saddle turns at |t - D|; see pathFrequency).
    let step = 1.5 * PI / Math.sqrt(18.5 * psi2);
    if (omega > 0) step = Math.min(step, 0.5 * PI / omega);
    // The rightmost singularity s0 maps to Y = (i +- sqrt(4 kappa d - 1))/(2 kappa),
    // d = v - s0: the integrand is analytic in the strip |Im Y| < w, and the
    // trapezoidal rule converges like exp(-2 pi w/step). Start inside that,
    // or two coarse sums can agree while both miss the feature.
    const dist = ss - ax.s0;
    let strip = Infinity;
    if (dist > 0 && isFinite(dist)) strip = kappa * dist < 1e-12 ? dist : 4 * kappa * dist >= 1 ? 1 / (2 * kappa) : (1 - Math.sqrt(1 - 4 * kappa * dist)) / (2 * kappa);
    if (!(strip > 0)) strip = dist > 0 ? dist : Infinity;
    step = Math.min(step, 0.5 * strip);
    const acc = { h: 0, dh: 0, d2: 0, abs: 0, bad: false, regrow: false, cut: false, stop };
    parabolaSweep(ctx, ws, ax.i, ax.j, tt, ss, kappa, step, 0, acc);
    if (acc.regrow) return { regrow: true };
    let h = acc.h * step / PI, dh = acc.dh * step / PI, d2 = acc.d2 * step / PI, err = Infinity, agreed = 0;
    for (let level = 0; level < 12 && !acc.bad; level++) {
      if (ws.evaluations > stop) break;     // out of budget: err stays the last difference
      const half = step / 2;
      const a2 = { h: 0, dh: 0, d2: 0, abs: 0, bad: false, regrow: false, cut: false, stop };
      parabolaSweep(ctx, ws, ax.i, ax.j, tt, ss, kappa, half, half, a2);
      if (a2.regrow) return { regrow: true };
      if (a2.bad) { acc.bad = true; break; }
      if (a2.cut) acc.cut = true;
      acc.h += a2.h; acc.dh += a2.dh; acc.d2 += a2.d2; acc.abs += a2.abs;
      step = half;
      const h2 = acc.h * step / PI;
      // the trapezoidal error squares with each halving: the difference of
      // the last two sums bounds the error of the one before, and its square
      // (relative) that of the new one
      err = Math.abs(h2 - h);
      h = h2; dh = acc.dh * step / PI; d2 = acc.d2 * step / PI;
      const floor = 1e-15 * acc.abs * step / PI + atol;
      const rel = err / Math.max(Math.abs(h), 1e-300);
      // squaring alone can promise too much next to a singularity: bound the
      // new error also by what a pole at the strip's edge, with a residue the
      // size of the answer, leaves at this step
      const next = Math.max(rel * rel, 2 * Math.exp(-2 * PI * strip / step));
      // under plug flow the step does not follow the phase along the path
      // (pathFrequency), and an oscillation a whole number of steps long
      // gives two sums that agree and are both wrong: there, two agreements
      // in a row
      const ok = err <= floor || (level >= 1 && err <= rtol * Math.abs(h) && next <= rtol) || (step <= 0.3 * strip && next <= rtol * 1e-2);
      agreed = ok ? agreed + 1 : 0;
      if (ok && (agreed >= 2 || !ctx.infPe)) {
        err = Math.min(err, next * Math.abs(h) + floor);
        break;
      }
    }
    const cond = acc.abs * step / PI / Math.max(Math.abs(h), 1e-300);
    if (acc.bad) return { h: NaN, dh: NaN, d2: NaN, err: Infinity, cond: Infinity };
    // a sum cut short can agree with the next one and still be wrong
    if (acc.cut) err = Infinity;
    return { h, dh, d2, err, cond, s: ss, kappa };
  }

  /** Fixed-Talbot sum for h(t) and h'(t) with scale r and M nodes. */
  function talbotSum(ctx, ws, i, j, t, r, M) {
    const n = i - j + 1, idx = (n - 1) * n;
    let sh = 0, sd = 0, s2 = 0, bad = false;
    for (let k = 0; k < M; k++) {
      let sr, si, sig;
      if (k === 0) { sr = r; si = 0; sig = 0; } else {
        const th = k * PI / M, cot = Math.cos(th) / Math.sin(th);
        sr = r * th * cot; si = r * th; sig = th + (th * cot - 1) * cot;
      }
      evalBlock(ctx, ws, sr, si, j, i);
      const Fr = ws.Fr[idx], Fi = ws.Fi[idx];
      if (Fr === 0 && Fi === 0) continue;
      const ex = t * sr - ws.E;
      if (ex < -740) continue;
      if (ex > 700) { bad = true; continue; }
      cexp(ex, t * si);
      const er = RE, ei = IM;
      const ar = er * Fr - ei * Fi, ai = er * Fi + ei * Fr;
      const tr = ar - ai * sig, ti = ai + ar * sig;
      const w = k === 0 ? 0.5 : 1;
      const yr = sr * tr - si * ti, yi = sr * ti + si * tr;
      sh += w * tr; sd += w * yr; s2 += w * (sr * yr - si * yi);
    }
    const c = r / M;
    return bad ? [NaN, NaN, NaN] : [c * sh, c * sd, c * s2];
  }

  /** h_ij(t) by the fixed Talbot contour (Abate and Valko), scaled out to the
      saddle when that lies right of 2M/(5t). */
  function invertTalbot(ctx, ws, ax, t, opt) {
    const i = ax.i, j = ax.j;
    const M0 = (opt && opt.M) || M_DEFAULT;
    let tt = t;
    if (ctx.infPe) { tt = t - pairDelay(ctx, i, j); if (!(tt > 0)) return { h: 0, dh: 0, d2: 0, r: 0, M: 0, saddle: false }; }
    const rdef = 2 * M0 / (5 * tt);
    const sad = saddleAt(ax, tt);
    let r = rdef, M = M0, useSad = false;
    if (sad && sad.s > rdef) {
      if (sad.beyond || sad.w < -720) return { h: 0, dh: 0, d2: 0, r: sad.s, M: 0, saddle: true };
      useSad = true;
      r = sad.s;
      const need = isFinite(sad.psi2) && sad.psi2 > 0 ? 2.2 * r * Math.sqrt(sad.psi2) : 0;
      M = Math.min(TALBOT_M_MAX, Math.max(M0, Math.ceil(need + 0.6 * M0)));
    }
    const [h, dh, d2] = talbotSum(ctx, ws, i, j, tt, r, M);
    return { h, dh, d2, r, M, saddle: useSad };
  }

  /** De Hoog's M for this case: a front as sharp as dispersion makes it
      (width about tw sqrt(2/Pe)) needs about 1.2 sqrt(Pe) terms, 24 to 160;
      with the axis and a time, also 1.7 t/sigma, sigma = sqrt(psi'') the
      spread of the response tilted to its saddle there (under plug flow, a
      matrix that fills at once makes a spike that Pe says nothing of). */
  function deHoogTerms(ctx, ax, t) {
    let m = ctx.infPe ? 24 : Math.max(24, Math.ceil(1.2 * Math.sqrt(ctx.Pe)));
    if (ax) {
      const tt = ctx.infPe ? t - pairDelay(ctx, ax.i, ax.j) : t;
      const sad = tt > 0 ? saddleAt(ax, tt) : null;
      if (sad && !sad.beyond && sad.psi2 > 0) m = Math.max(m, Math.ceil(1.7 * tt / Math.sqrt(sad.psi2)));
    }
    return Math.min(160, m);
  }

  /**
   * De Hoog, Knight and Stokes (1982): the trapezoidal rule on the Bromwich
   * line Re s = gamma with period 2T, accelerated by the quotient-difference
   * continued fraction. The independent check on the contour methods.
   * opt.deriv inverts s^deriv T instead: 1 and 2 the derivatives of h_ij,
   * -1 its integral from 0 to t.
   */
  function invertDeHoog(ctx, ws, i, j, t, opt) {
    let tt = t;
    if (ctx.infPe) { tt = t - pairDelay(ctx, i, j); if (!(tt > 0)) return 0; }
    const M = (opt && opt.M) || 24;
    const tol = (opt && opt.tol) || 1e-12;
    const deriv = (opt && opt.deriv) ? (opt.deriv === true ? 1 : opt.deriv) : 0;
    const T = ((opt && opt.Tfac) || 2) * tt;
    const gamma = -Math.log(tol) / (2 * T);
    const n = i - j + 1, idx = (n - 1) * n;
    const K = 2 * M;
    const ar = new Float64Array(K + 1), ai = new Float64Array(K + 1);
    let E0 = 0;
    let Kuse = K;
    for (let k = 0; k <= K; k++) {
      evalBlock(ctx, ws, gamma, k * PI / T, j, i);
      if (k === 0) E0 = ws.E;
      const sc = Math.exp(E0 - ws.E);
      ar[k] = ws.Fr[idx] * sc; ai[k] = ws.Fi[idx] * sc;
      for (let q = 0; q < deriv; q++) { const sr = gamma, si = k * PI / T, xr = ar[k], xi = ai[k]; ar[k] = sr * xr - si * xi; ai[k] = sr * xi + si * xr; }
      for (let q = 0; q > deriv; q--) { cdiv(ar[k], ai[k], gamma, k * PI / T); ar[k] = RE; ai[k] = IM; }
      if (!(ar[k] !== 0 || ai[k] !== 0) || !isFinite(ar[k]) || !isFinite(ai[k])) { Kuse = k - 1; break; }
    }
    if (Kuse % 2 === 1) Kuse--;
    if (Kuse < 2) return NaN;
    const Mu = Kuse / 2;
    ar[0] *= 0.5; ai[0] *= 0.5;
    // quotient-difference table
    const qr = new Float64Array(Kuse), qi = new Float64Array(Kuse);
    const er = new Float64Array(Kuse + 1), ei = new Float64Array(Kuse + 1);
    const dr = new Float64Array(Kuse + 1), di = new Float64Array(Kuse + 1);
    for (let k = 0; k < Kuse; k++) { cdiv(ar[k + 1], ai[k + 1], ar[k], ai[k]); qr[k] = RE; qi[k] = IM; }
    for (let k = 0; k <= Kuse; k++) { er[k] = 0; ei[k] = 0; }
    dr[0] = ar[0]; di[0] = ai[0];
    for (let r = 1; r <= Mu; r++) {
      for (let k = 0; k <= Kuse - 2 * r; k++) {
        er[k] = qr[k + 1] - qr[k] + er[k + 1];
        ei[k] = qi[k + 1] - qi[k] + ei[k + 1];
      }
      dr[2 * r - 1] = -qr[0]; di[2 * r - 1] = -qi[0];
      dr[2 * r] = -er[0]; di[2 * r] = -ei[0];
      if (r < Mu) {
        for (let k = 0; k < Kuse - 2 * r; k++) {
          const xr = qr[k + 1] * er[k + 1] - qi[k + 1] * ei[k + 1];
          const xi = qr[k + 1] * ei[k + 1] + qi[k + 1] * er[k + 1];
          cdiv(xr, xi, er[k], ei[k]); qr[k] = RE; qi[k] = IM;
        }
      }
    }
    // continued fraction at z = exp(i pi t/T)
    const zr = Math.cos(PI * tt / T), zi = Math.sin(PI * tt / T);
    let A2r = 0, A2i = 0, A1r = dr[0], A1i = di[0];
    let B2r = 1, B2i = 0, B1r = 1, B1i = 0;
    for (let k = 1; k <= Kuse; k++) {
      const cr = dr[k] * zr - di[k] * zi, ci = dr[k] * zi + di[k] * zr;
      let Ar, Ai, Br, Bi;
      if (k < Kuse) {
        Ar = A1r + cr * A2r - ci * A2i; Ai = A1i + cr * A2i + ci * A2r;
        Br = B1r + cr * B2r - ci * B2i; Bi = B1i + cr * B2i + ci * B2r;
      } else {
        // the remainder estimate of de Hoog et al.
        const d1r = dr[Kuse - 1] - dr[Kuse], d1i = di[Kuse - 1] - di[Kuse];
        const hr = 0.5 * (1 + d1r * zr - d1i * zi), hi = 0.5 * (d1r * zi + d1i * zr);
        const h2r = hr * hr - hi * hi, h2i = 2 * hr * hi;
        cdiv(cr, ci, h2r, h2i);
        csqrt(1 + RE, IM);
        const Rr = -(hr * (1 - RE) - hi * (-IM)), Ri = -(hr * (-IM) + hi * (1 - RE));
        Ar = A1r + Rr * A2r - Ri * A2i; Ai = A1i + Rr * A2i + Ri * A2r;
        Br = B1r + Rr * B2r - Ri * B2i; Bi = B1i + Rr * B2i + Ri * B2r;
      }
      A2r = A1r; A2i = A1i; A1r = Ar; A1i = Ai;
      B2r = B1r; B2i = B1i; B1r = Br; B1i = Bi;
    }
    cdiv(A1r, A1i, B1r, B1i);
    return Math.exp(gamma * tt - E0) / T * RE;
  }

  /* ======================================================================
     7. Unit response functions on adaptive grids

     Each response h_ij is sampled with its first and second derivatives
     (the inversions of s T(s) and s^2 T(s) come free with that of T), so a
     quintic Hermite interpolant represents it between samples. The grid
     starts from the saddle-point estimate of where h_ij matters and is
     refined until the interpolant predicts every new midpoint.
     ====================================================================== */

  const RESP_PER_DECADE = 10;
  const RESP_RTOL = 2e-8;
  const RESP_ATOL = 1e-13;
  const RESP_MAXPTS = 6000;
  const T_CAP = 1e12;

  /** Saddle-point estimate of ln h_ij(t): w - ln(2 pi psi'')/2. */
  function logEstimate(ctx, ax, t) {
    let tt = t;
    if (ctx.infPe) { tt = t - pairDelay(ctx, ax.i, ax.j); if (!(tt > 0)) return -Infinity; }
    const sad = saddleAt(ax, tt);
    if (!sad || sad.beyond || !isFinite(sad.w)) return -Infinity;
    const c = isFinite(sad.psi2) && sad.psi2 > 0 ? -0.5 * Math.log(2 * PI * sad.psi2) : 0;
    return sad.w + c;
  }

  /** Where h_ij is worth computing, from the estimate on a log grid:
      tLo (e^-62 below the peak), tHi (e^-72 below, or tMax), tSig (1e-10)
      and tTail (the last time above 1e-9 of the peak, for the end time). */
  function responseSupport(ctx, ax, tMin, tMax) {
    // under plug flow nothing arrives before the delay d: the grid is
    // logarithmic in t - d, or a response far narrower than d (a matrix that
    // fills at once) falls between its points
    const d = ctx.infPe ? pairDelay(ctx, ax.i, ax.j) : 0, uMin = tMin - d, uMax = tMax - d;
    const per = 16;
    const n = Math.max(2, Math.ceil(Math.log10(uMax / uMin) * per) + 1);
    const ts = new Float64Array(n), est = new Float64Array(n);
    let wmax = -Infinity, kmax = -1;
    for (let k = 0; k < n; k++) {
      ts[k] = d + uMin * Math.pow(uMax / uMin, k / (n - 1));
      est[k] = logEstimate(ctx, ax, ts[k]);
      if (est[k] > wmax) { wmax = est[k]; kmax = k; }
    }
    if (!isFinite(wmax)) return null;
    let kLo = 0; while (kLo < n && !(est[kLo] > wmax - 62)) kLo++;
    let kHi = n - 1; while (kHi > kmax && !(est[kHi] > wmax - 72)) kHi--;
    let kTail = n - 1; while (kTail > kmax && !(est[kTail] > wmax - 20.7)) kTail--;
    return {
      tLo: ts[Math.max(0, kLo - 1)], tHi: kHi >= n - 1 ? tMax : ts[Math.min(n - 1, kHi + 1)],
      tPeak: ts[kmax], logPeak: wmax,
      tTail: kTail >= n - 1 ? tMax : ts[Math.min(n - 1, kTail + 1)],
    };
  }

  /** One sample of h_ij, h_ij' and h_ij'' by the chosen method. */
  function sample(ctx, ws, ax, t, method, atol, hint) {
    if (method === 'talbot') {
      const r = invertTalbot(ctx, ws, ax, t);
      if (isFinite(r.h) && isFinite(r.dh) && isFinite(r.d2)) return [r.h, r.dh, r.d2, 1];
    } else if (method === 'dehoog') {
      const mH = deHoogTerms(ctx, ax, t);
      const v = [invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: mH }), invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: mH, deriv: 1 }),
        invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: mH, deriv: 2 }), 1];
      if (isFinite(v[0]) && isFinite(v[1]) && isFinite(v[2])) return v;
    }
    // the default, and where the other two break down (an overflowing term,
    // a quotient-difference table that divides by zero). A response whose
    // samples mostly fell back to de Hoog (below) goes there first.
    if (hint) hint.tries++;
    const direct = hint && hint.tries > 16 && hint.fails > 0.75 * hint.tries;
    const r = direct ? { h: NaN, err: Infinity } : invertParabola(ctx, ws, ax, t, { atol });
    if (isFinite(r.h) && !(r.err > 1e-6 * Math.abs(r.h) + atol)) return [r.h, r.dh, r.d2, r.cond || 1, r.err];
    if (hint) hint.fails++;
    // a path that found no clear way, or did not converge within its budget:
    // de Hoog's Bromwich line (where |T| stays below T(Re s), so no sum of
    // huge terms), with twice the terms the spread asks for; the parabola
    // only when it has an error estimate below de Hoog's
    const m1 = deHoogTerms(ctx, ax, t), m2 = Math.min(2 * m1, 320);
    const a = invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: m1 }), b = invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: m2 });
    const eH = Math.abs(a - b);
    if (isFinite(b) && (!isFinite(r.h) || !isFinite(r.err) || eH < r.err)) {
      const d1 = invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: m2, deriv: 1 }), d2 = invertDeHoog(ctx, ws, ax.i, ax.j, t, { M: m2, deriv: 2 });
      if (isFinite(d1) && isFinite(d2)) return [b, d1, d2, 1, eH + atol];
    }
    if (isFinite(r.h)) return [r.h, r.dh, r.d2, r.cond || 1, r.err];
    if (direct) {
      const s2 = invertParabola(ctx, ws, ax, t, { atol });
      if (isFinite(s2.h)) return [s2.h, s2.dh, s2.d2, s2.cond || 1, s2.err];
    }
    return [0, 0, 0, Infinity, Infinity];
  }

  /** Quintic Hermite from values, first and second derivatives at the ends. */
  function hermite5(ta, ya, da, ea, tb, yb, db, eb, t) {
    const d = tb - ta, x = (t - ta) / d, x2 = x * x, x3 = x2 * x, x4 = x3 * x, x5 = x4 * x;
    const h0 = 1 - 10 * x3 + 15 * x4 - 6 * x5, h1 = x - 6 * x3 + 8 * x4 - 3 * x5, h2 = 0.5 * (x2 - 3 * x3 + 3 * x4 - x5);
    const h4 = -4 * x3 + 7 * x4 - 3 * x5, h5 = 0.5 * (x3 - 2 * x4 + x5);
    return h0 * ya + d * h1 * da + d * d * h2 * ea + (1 - h0) * yb + d * h4 * db + d * d * h5 * eb;
  }

  /**
   * The response of nuclide i to a unit pulse of j on [tA, tB]:
   * { i, j, t, h, dh, peak, tPeak, integral, T0, maxCond }.
   */
  function computeResponse(ctx, ws, ax, tA, tB, opt) {
    const method = (opt && opt.method) || 'parabola';
    const rtol = (opt && opt.rtol) || RESP_RTOL;
    // the absolute floor, relative to the peak, each method can hold in the tails
    const atolRel = method === 'parabola' ? RESP_ATOL : method === 'talbot' ? 1e-9 : 1e-8;
    const maxPts = (opt && opt.maxPts) || RESP_MAXPTS;
    const per = (opt && opt.perDecade) || RESP_PER_DECADE;
    // logarithmic in t - d, d the plug-flow delay (see responseSupport)
    const d = ctx.infPe ? pairDelay(ctx, ax.i, ax.j) : 0;
    const n0 = Math.max(16, Math.ceil(Math.log10((tB - d) / (tA - d)) * per) + 1);
    let T = [], H = [], D = [], D2 = [];
    let peak = 0, maxCond = 1, maxErr = 0;
    const atol = (opt && opt.peakEstimate > 0 ? 1e-3 * RESP_ATOL * opt.peakEstimate : 0);
    const hint = { tries: 0, fails: 0 };
    for (let k = 0; k < n0; k++) {
      const t = d + (tA - d) * Math.pow((tB - d) / (tA - d), k / (n0 - 1));
      const [h, dh, d2, c, e] = sample(ctx, ws, ax, t, method, atol, hint);
      if (e > maxErr) maxErr = e;
      T.push(t); H.push(h); D.push(dh); D2.push(d2);
      if (Math.abs(h) > peak) peak = Math.abs(h);
      if (c > maxCond) maxCond = c;
    }
    let flag = new Array(T.length - 1).fill(true);
    for (let pass = 0; pass < 30; pass++) {
      const nT = [T[0]], nH = [H[0]], nD = [D[0]], nD2 = [D2[0]], nF = [];
      let inserted = false;
      for (let k = 0; k + 1 < T.length; k++) {
        if (flag[k] && T.length + nT.length < 2 * maxPts && (T[k + 1] - d) / (T[k] - d) > 1 + 1e-9) {
          const tm = d + Math.sqrt((T[k] - d) * (T[k + 1] - d));
          const [h, dh, d2, c, e] = sample(ctx, ws, ax, tm, method, Math.max(atol, 1e-3 * RESP_ATOL * peak), hint);
          if (e > maxErr) maxErr = e;
          if (Math.abs(h) > peak) peak = Math.abs(h);
          if (c > maxCond) maxCond = c;
          const p = hermite5(T[k], H[k], D[k], D2[k], T[k + 1], H[k + 1], D[k + 1], D2[k + 1], tm);
          // where de Hoog made most samples, to what de Hoog can deliver
          const dh0 = hint.fails > 0.5 * hint.tries;
          const ok = Math.abs(h - p) <= (dh0 ? Math.max(rtol, 1e-7) : rtol) * Math.abs(h) + (dh0 ? Math.max(atolRel, 1e-10) : atolRel) * peak;
          nT.push(tm); nH.push(h); nD.push(dh); nD2.push(d2);
          nF.push(!ok, !ok);
          if (!ok) inserted = true;
        } else {
          nF.push(false);
        }
        nT.push(T[k + 1]); nH.push(H[k + 1]); nD.push(D[k + 1]); nD2.push(D2[k + 1]);
      }
      T = nT; H = nH; D = nD; D2 = nD2; flag = nF;
      if (!inserted || T.length >= maxPts) break;
    }
    const n = T.length;
    const t = Float64Array.from(T), h = Float64Array.from(H), dh = Float64Array.from(D), d2h = Float64Array.from(D2);
    let integral = 0, tPeak = t[0], pk = -Infinity;
    for (let k = 0; k < n; k++) if (h[k] > pk) { pk = h[k]; tPeak = t[k]; }
    for (let k = 0; k + 1 < n; k++) {
      const d = t[k + 1] - t[k];
      integral += d * (0.5 * (h[k] + h[k + 1]) + d * (dh[k] - dh[k + 1]) / 10 + d * d * (d2h[k] + d2h[k + 1]) / 120);
    }
    return { i: ax.i, j: ax.j, t, h, dh, d2h, peak: Math.max(pk, 0), tPeak, integral, maxCond, maxErr: maxErr / Math.max(pk, 1e-300) };
  }

  /** T_ij(0) = the integral of h_ij over all time (with decay): the mass
      balance a response must meet. */
  function transferAtZero(ctx, ws, i, j) {
    const v = transfer(ctx, ws, 0, 0, i, j)[0];
    return isFinite(v) ? v : transfer(ctx, ws, 1e-300, 0, i, j)[0];
  }

  /* ======================================================================
     8. Input series and the convolution

     A release series is piecewise linear between its points and zero before
     the first and after the last. A repeated time is a step. The convolution
     of such a series with a Hermite-interpolated response is exact: on every
     piece between the merged breakpoints the integrand is a polynomial of
     degree six, integrated by four-point Gauss-Legendre.
     ====================================================================== */

  function normaliseSeries(points, name) {
    const t = [], v = [];
    for (const p of points || []) {
      const a = num(p[0]), b = num(p[1]);
      if (!isFinite(a) || !isFinite(b)) throw new Farf31Error(`${name || 'Series'}: every point needs a finite time and rate.`);
      if (t.length && a < t[t.length - 1]) throw new Farf31Error(`${name || 'Series'}: the times must not decrease (${a} after ${t[t.length - 1]}).`);
      if (t.length && a === t[t.length - 1] && b === v[v.length - 1]) continue;
      t.push(a); v.push(b);
    }
    if (t.length < 2) throw new Farf31Error(`${name || 'Series'}: at least two points are needed.`);
    let first = -1, last = -1;
    for (let k = 0; k < t.length; k++) {
      const nz = v[k] !== 0 || (k + 1 < t.length && v[k + 1] !== 0 && t[k + 1] > t[k]) || (k > 0 && v[k - 1] !== 0 && t[k] > t[k - 1]);
      if (nz) { if (first < 0) first = k; last = k; }
    }
    let mass = 0;
    for (let k = 0; k + 1 < t.length; k++) mass += 0.5 * (t[k + 1] - t[k]) * (v[k] + v[k + 1]);
    return {
      t: Float64Array.from(t), v: Float64Array.from(v),
      tFirst: first < 0 ? NaN : t[first], tLast: last < 0 ? NaN : t[last], mass, empty: first < 0,
    };
  }

  // four-point Gauss-Legendre: exact for the quintic response times a line
  const GL_X1 = 0.3399810435848563, GL_X2 = 0.8611363115940526;
  const GL_W1 = 0.6521451548625461, GL_W2 = 0.3478548451374538;

  function hAt(resp, k, u) {
    return hermite5(resp.t[k], resp.h[k], resp.dh[k], resp.d2h[k], resp.t[k + 1], resp.h[k + 1], resp.dh[k + 1], resp.d2h[k + 1], u);
  }

  /** (h * F)(t) = integral over u of h(u) F(t - u). */
  /** The release series at time x: linear between its points, zero outside,
      the later value at a repeated time. */
  function seriesAt(ser, x) {
    const st = ser.t, sv = ser.v, ns = st.length;
    if (ser.empty || !(x >= st[0]) || !(x <= st[ns - 1])) return 0;
    let lo = 0, hi = ns - 1;
    while (hi - lo > 1) { const c = (lo + hi) >> 1; if (st[c] <= x) lo = c; else hi = c; }
    const d = st[hi] - st[lo];
    return d > 0 ? sv[lo] + (sv[hi] - sv[lo]) * (x - st[lo]) / d : sv[hi];
  }

  function convolveAt(resp, ser, t) {
    const rt = resp.t, nr = rt.length, st = ser.t, sv = ser.v, ns = st.length;
    if (nr < 2 || ser.empty) return 0;
    // the part of the response before its first time (under plug flow, what
    // arrives within a hair of the delay), as a point mass there
    const lump = resp.m0 > 0 ? resp.m0 * seriesAt(ser, t - rt[0]) : 0;
    const uLo = Math.max(rt[0], t - st[ns - 1]), uHi = Math.min(rt[nr - 1], t - st[0], t);
    if (!(uHi > uLo)) return lump;
    // response interval containing uLo
    let k = 0, a = 0, b = nr - 1;
    while (b - a > 1) { const c = (a + b) >> 1; if (rt[c] <= uLo) a = c; else b = c; }
    k = a;
    // input segment containing x = t - uLo (x decreasing as u grows): largest m with st[m] < x
    let m = ns - 2;
    const x0 = t - uLo;
    { let lo = 0, hi = ns - 1; while (hi - lo > 1) { const c = (lo + hi) >> 1; if (st[c] < x0) lo = c; else hi = c; } m = lo; }
    let sum = 0, u = uLo;
    while (u < uHi) {
      while (k + 1 < nr - 1 && rt[k + 1] <= u) k++;
      while (m > 0 && t - st[m] <= u) m--;
      // next breakpoint
      let next = uHi;
      if (rt[k + 1] < next && rt[k + 1] > u) next = rt[k + 1];
      const um = t - st[m];
      if (um < next && um > u) next = um;
      if (next <= u) break;
      const tm0 = st[m], tm1 = st[m + 1];
      const dseg = tm1 - tm0;
      if (dseg > 0) {
        const vm0 = sv[m], slope = (sv[m + 1] - vm0) / dseg;
        const c = 0.5 * (u + next), hw = 0.5 * (next - u);
        let q = 0;
        for (let g = 0; g < 4; g++) {
          const uu = c + (g < 2 ? (g ? GL_X1 : -GL_X1) : (g === 2 ? -GL_X2 : GL_X2)) * hw;
          q += (g < 2 ? GL_W1 : GL_W2) * hAt(resp, k, uu) * (vm0 + slope * (t - uu - tm0));
        }
        sum += hw * q;
      }
      u = next;
    }
    return sum + lump;
  }

  /** Series from shapes: constant from t1 to t2, a rectangular pulse of an
      amount over a duration, an exponential decline from t1. */
  function seriesFromShapes(shapes) {
    const pts = [];
    const bps = new Set();
    for (const sh of shapes) {
      if (sh.kind === 'constant') { bps.add(num(sh.t1)); bps.add(num(sh.t2)); }
      else if (sh.kind === 'pulse') { bps.add(num(sh.t1)); bps.add(num(sh.t1) + num(sh.duration)); }
      else if (sh.kind === 'exponential') {
        const t1 = num(sh.t1), t2 = num(sh.t2), th = num(sh.halfTime);
        const k = LN2 / th;
        // log-spaced in time since t1 so that linear interpolation is within 1e-4
        const npts = Math.max(8, Math.min(2000, Math.ceil((t2 - t1) * k / 0.02) + 1));
        for (let q = 0; q < npts; q++) bps.add(t1 + (t2 - t1) * q / (npts - 1));
      }
    }
    const times = Array.from(bps).filter(isFinite).sort((a, b) => a - b);
    const rateAt = (t, side) => {
      let r = 0;
      for (const sh of shapes) {
        if (sh.kind === 'constant') {
          const t1 = num(sh.t1), t2 = num(sh.t2);
          if ((side < 0 ? t > t1 && t <= t2 : t >= t1 && t < t2)) r += num(sh.rate);
        } else if (sh.kind === 'pulse') {
          const t1 = num(sh.t1), t2 = t1 + num(sh.duration);
          if ((side < 0 ? t > t1 && t <= t2 : t >= t1 && t < t2)) r += num(sh.amount) / num(sh.duration);
        } else if (sh.kind === 'exponential') {
          const t1 = num(sh.t1), t2 = num(sh.t2);
          if ((side < 0 ? t > t1 && t <= t2 : t >= t1 && t < t2)) r += num(sh.rate) * Math.exp(-LN2 * (t - t1) / num(sh.halfTime));
        }
      }
      return r;
    };
    for (const t of times) {
      const l = rateAt(t, -1), r = rateAt(t, 1);
      if (l !== r) { pts.push([t, l], [t, r]); } else pts.push([t, r]);
    }
    return pts;
  }

  /* ======================================================================
     9. A whole run

     input = {
       params: { tw, Pe, aw, eps, x0, rho },
       nuclides: [{ name, thalf, kd, ka, de, daughter, source }],   ka optional, 0
       series: { <name>: [[t, rate], ...] },     for every source
       settings: { method, tStart, tEnd, perDecade, relint, npMin, npMax,
                   bqMin, allResponses, check, respRtol, respPerDecade,
                   respMaxPts }
     }
     ====================================================================== */

  const OUT_PER_DECADE = 20;
  const OUT_RELINT = 1e-3;
  const OUT_NPMAX = 2500;

  function now() { return typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now(); }

  /** Activity per mole per year -> Bq: lambda [1/s] * Avogadro. */
  function bqPerMol(thalfYears) {
    return isFinite(thalfYears) ? LN2 / (thalfYears * YEAR_S) * AVOGADRO : 0;
  }

  /** Under plug flow a response starts at the delay, and a daughter born
      near the outlet, or a nuclide the matrix barely holds, arrives within a
      hair of it: what arrives before the response's first time (de Hoog's
      inversion of T_ij/s there) is kept as m0, added to the integral and
      released as a point mass (convolveAt). */
  function addEarlyMass(ctx, ws, resp) {
    resp.m0 = 0;
    if (!ctx.infPe || resp.t.length < 2) return;
    const S = invertDeHoog(ctx, ws, resp.i, resp.j, resp.t[0], { M: deHoogTerms(ctx), deriv: -1 });
    if (S > 0 && isFinite(S)) { resp.m0 = S; resp.integral += S; }
  }

  function emptyResponse(i, j) {
    return { i, j, t: new Float64Array(0), h: new Float64Array(0), dh: new Float64Array(0), d2h: new Float64Array(0), peak: 0, tPeak: NaN, integral: 0, maxCond: 1 };
  }

  /**
   * A response's mass balance: its integral against what leaves the tube by
   * its last time, T_ij(0) when the rest is negligible and otherwise the
   * integral of h_ij from 0 to that time (de Hoog's inversion of T_ij/s).
   * The rest after time t is at most e^w, w = s t + psi(s) with the saddle
   * s < 0 for t (the Chernoff bound). Nothing is checked when T_ij(0) is
   * below 1e-30, and the difference is taken relative to T_ij(0) or 1e-10,
   * whichever is larger: a daughter's T_ij(0) of 1e-13 comes out of a sum
   * of terms of order one, good to about 1e-16. Returns { ok, checked,
   * expected, rel }.
   */
  function massBalance(ctx, ws, ax, resp, tol) {
    const T0 = resp.T0;
    if (!(Math.abs(T0) > 1e-30)) return { ok: true, checked: false, expected: T0, rel: 0 };
    let expected = T0;
    const n = resp.t.length;
    if (n) {
      const tl = resp.t[n - 1];
      const tt = ctx.infPe ? tl - pairDelay(ctx, resp.i, resp.j) : tl;
      const sad = tt > 0 ? saddleAt(ax, tt) : null;
      const rest = sad && !sad.beyond && sad.s <= 0 ? Math.exp(sad.w) : Infinity;
      if (!(rest <= 1e-10 * Math.abs(T0))) {
        const S = invertDeHoog(ctx, ws, resp.i, resp.j, tl, { M: deHoogTerms(ctx), deriv: -1 });
        if (isFinite(S)) expected = S;
      }
    }
    const rel = Math.abs(resp.integral - expected) / Math.max(Math.abs(T0), 1e-10);
    return { ok: rel <= tol, checked: true, expected, rel };
  }

  function run(input, onProgress) {
    const t0 = now();
    const settings = Object.assign({}, input.settings || {});
    const method = settings.method || 'parabola';
    const p = input.params || {};
    const nucs = input.nuclides || [];
    const N = nucs.length;
    const names = nucs.map((n) => String(n.name));
    const result = {
      names, thalf: nucs.map((n) => num(n.thalf)), times: new Float64Array(0), out: [], bq: [],
      responses: [], peaks: [], notes: [], check: null, timing: {}, empty: false,
    };
    if (num(p.tw) < 0) {
      // FARF31: a negative travel time gives an empty output
      result.empty = true;
      result.notes.push('The travel time is negative: the output is empty, as in FARF31.');
      for (let i = 0; i < N; i++) { result.out.push(new Float64Array(0)); result.bq.push(new Float64Array(0)); }
      return result;
    }
    const ctx = prepare({ tw: p.tw, Pe: p.Pe, aw: p.aw, eps: p.eps, x0: p.x0, rho: p.rho, nuclides: nucs });
    const ws = makeWorkspace(ctx);
    // the release series
    const series = new Array(N).fill(null);
    for (let j = 0; j < N; j++) {
      if (!nucs[j].source) continue;
      const pts = input.series ? input.series[names[j]] : null;
      if (!pts) throw new Farf31Error(`${names[j]} is marked as a source but has no release series.`);
      series[j] = normaliseSeries(pts, names[j]);
    }
    const sources = [];
    for (let j = 0; j < N; j++) if (series[j] && !series[j].empty) sources.push(j);
    // pairs: every nuclide of the chain below a source
    const chainEnd = new Int32Array(N);
    for (let i = N - 1; i >= 0; i--) chainEnd[i] = i + 1 < N && ctx.link[i + 1] ? chainEnd[i + 1] : i;
    const pairs = [];
    for (const j of sources) for (let i = j; i <= chainEnd[j]; i++) pairs.push([i, j]);
    if (settings.allResponses) {
      for (let j = 0; j < N; j++) {
        if (sources.includes(j)) continue;
        for (let i = j; i <= chainEnd[j]; i++) pairs.push([i, j]);
      }
    }
    let tLast = 0, tFirst = Infinity;
    for (const j of sources) { tLast = Math.max(tLast, series[j].tLast); tFirst = Math.min(tFirst, series[j].tFirst); }
    if (!sources.length) { tFirst = 0; tLast = 0; }
    // 1. the real axis and the support of every response (under plug flow
    //    nothing arrives before the delay Rf tw)
    const tScanHi = T_CAP;
    const info = pairs.map(([i, j]) => {
      const lo = ctx.infPe ? pairDelay(ctx, i, j) * (1 + 1e-9) : ctx.tw * 1e-6;
      const ax = realAxis(ctx, ws, i, j, lo, tScanHi);
      const sup = responseSupport(ctx, ax, lo, tScanHi);
      return { i, j, ax, sup, lo };
    });
    // 2. the end time: where the last response a release goes through has
    //    fallen to 1e-9 of its peak after the last of that release, up to the
    //    page's limit T_CAP (the end of the real-axis scan); the Summary says
    //    when the limit cuts a release short
    let tEnd = num(settings.tEnd), tEndCut = 0;
    if (!(tEnd > 0)) {
      tEnd = 0;
      for (const q of info) {
        if (!q.sup || !series[q.j]) continue;
        tEnd = Math.max(tEnd, series[q.j].tLast + q.sup.tTail);
      }
      if (!(tEnd > 0)) tEnd = Math.max(10 * ctx.tw * Math.max(...ctx.rf), tLast * 2, 1);
      if (tEnd > T_CAP) { tEndCut = tEnd; tEnd = T_CAP; }
    }
    result.tEnd = tEnd;
    // 3. the responses, each held to its mass balance
    const t1 = now();
    let done = 0;
    const balance = { checked: 0, failed: [] };
    for (const q of info) {
      const ser = series[q.j];
      const tMax = tEnd - (ser ? ser.tFirst : 0);
      const tA = q.sup ? q.sup.tLo : NaN;
      const tB = q.sup ? Math.min(q.sup.tHi, tMax) : NaN;
      let resp;
      // a response no release goes through is only drawn: a coarser grid does
      const base = method === 'parabola' ? RESP_RTOL : method === 'talbot' ? 2e-6 : 1e-5;   // what each inversion can deliver
      const rtol = settings.respRtol || (ser ? base : Math.max(base, 1e-6));
      const ropt = { method, perDecade: settings.respPerDecade, maxPts: settings.respMaxPts, rtol, peakEstimate: q.sup ? Math.exp(q.sup.logPeak) : 0 };
      if (q.sup && tB > tA * (1 + 1e-9)) resp = computeResponse(ctx, ws, q.ax, tA, tB, ropt);
      else resp = emptyResponse(q.i, q.j);
      addEarlyMass(ctx, ws, resp);
      resp.T0 = transferAtZero(ctx, ws, q.i, q.j);
      const tol = Math.max(1e-5, 50 * rtol);   // a check for failures, not for the last digits
      let bal = massBalance(ctx, ws, q.ax, resp, tol);
      if (!bal.ok) {
        // once more, from far earlier and with a finer grid (an estimate of
        // where the response lies that missed part of it)
        const tA2 = Math.max(q.lo, (q.sup ? q.sup.tLo : q.lo) / 1e3), tB2 = q.sup ? tB : Math.min(T_CAP, tMax);
        if (tB2 > tA2 * (1 + 1e-9)) {
          const r2 = computeResponse(ctx, ws, q.ax, tA2, tB2, Object.assign({}, ropt, { perDecade: 2 * (settings.respPerDecade || RESP_PER_DECADE), maxPts: 2 * (settings.respMaxPts || RESP_MAXPTS) }));
          addEarlyMass(ctx, ws, r2);
          r2.T0 = resp.T0;
          const b2 = massBalance(ctx, ws, q.ax, r2, tol);
          if (b2.rel < bal.rel) { resp = r2; bal = b2; }
        }
      }
      resp.expected = bal.expected;
      resp.balanced = bal.ok;
      if (bal.checked) balance.checked++;
      if (!bal.ok) {
        balance.failed.push({ i: q.i, j: q.j, integral: resp.integral, expected: bal.expected, rel: bal.rel });
        const p4 = (x) => Number(x).toPrecision(4);
        result.notes.push(`The unit response of ${names[q.i]} to ${names[q.j]} integrates to ${p4(resp.integral)}, but ${p4(bal.expected)} of a pulse leaves the tube ${resp.t.length ? `by ${p4(resp.t[resp.t.length - 1])} a` : 'in all'} (T(0) = ${p4(resp.T0)}): the inversion failed there, and the release computed from it is not reliable.`);
      }
      resp.nameI = names[q.i]; resp.nameJ = names[q.j];
      resp.source = !!series[q.j];
      result.responses.push(resp);
      done++;
      if (onProgress) onProgress(done, info.length + 1, `response ${names[q.i]} from ${names[q.j]}`);
    }
    result.balance = balance;
    const t2 = now();
    // 4. the output grid
    const byNuclide = [];
    for (let i = 0; i < N; i++) byNuclide.push([]);
    for (const r of result.responses) if (r.source && r.t.length > 1) byNuclide[r.i].push(r);
    const outAt = (t, i) => {
      let s = 0;
      for (const r of byNuclide[i]) s += convolveAt(r, series[r.j], t);
      return s;
    };
    let tStart = num(settings.tStart);
    if (!(tStart > 0)) {
      tStart = Infinity;
      for (const r of result.responses) {
        if (!r.source || r.t.length < 2 || !(r.peak > 0)) continue;
        let k = 0; while (k < r.t.length && !(r.h[k] > 1e-10 * r.peak)) k++;
        if (k < r.t.length) tStart = Math.min(tStart, series[r.j].tFirst + r.t[k]);
      }
      if (!isFinite(tStart)) tStart = Math.max(tFirst, ctx.tw) || 1;
      tStart = Math.max(tStart, 1e-300);
    }
    if (!(tEnd > tStart)) tEnd = tStart * 10;
    const per = settings.perDecade || OUT_PER_DECADE;
    const npMin = settings.npMin || 0;
    const nBase = Math.max(npMin, 40, Math.ceil(Math.log10(tEnd / tStart) * per) + 1);
    const tset = new Set();
    for (let k = 0; k < nBase; k++) tset.add(tStart * Math.pow(tEnd / tStart, k / (nBase - 1)));
    // the input breakpoints, just after them, and moved by each response's peak time
    for (const j of sources) {
      const s = series[j];
      for (let k = 0; k < s.t.length; k++) {
        for (const r of result.responses) {
          if (r.j !== j || !r.source || !isFinite(r.tPeak)) continue;
          const tt = s.t[k] + r.tPeak;
          if (tt > tStart && tt < tEnd) tset.add(tt);
        }
        const tt = s.t[k];
        if (tt > tStart && tt < tEnd) { tset.add(tt); tset.add(tt * (1 + 1e-9)); }
      }
    }
    let T = Array.from(tset).sort((a, b) => a - b);
    let V = T.map((t) => { const row = new Float64Array(N); for (let i = 0; i < N; i++) row[i] = outAt(t, i); return row; });
    const relint = settings.relint || OUT_RELINT;
    const npMax = settings.npMax || OUT_NPMAX;
    const peakOf = () => { const pk = new Float64Array(N); for (const row of V) for (let i = 0; i < N; i++) pk[i] = Math.max(pk[i], row[i]); return pk; };
    let pk = peakOf();
    let flag = new Array(T.length - 1).fill(true);
    for (let pass = 0; pass < 24 && T.length < npMax; pass++) {
      const nT = [T[0]], nV = [V[0]], nF = [];
      let inserted = false;
      for (let k = 0; k + 1 < T.length; k++) {
        if (flag[k] && T.length + nT.length < 2 * npMax && T[k + 1] - T[k] > 1e-9 * T[k + 1]) {
          const tm = 0.5 * (T[k] + T[k + 1]) > 3 * T[k] ? Math.sqrt(T[k] * T[k + 1]) : 0.5 * (T[k] + T[k + 1]);
          const row = new Float64Array(N);
          let bad = false;
          const f = (tm - T[k]) / (T[k + 1] - T[k]);
          for (let i = 0; i < N; i++) {
            row[i] = outAt(tm, i);
            const lin = V[k][i] + f * (V[k + 1][i] - V[k][i]);
            if (Math.abs(row[i] - lin) > relint * Math.max(Math.abs(row[i]), 1e-6 * pk[i]) && pk[i] > 0) bad = true;
          }
          nT.push(tm); nV.push(row); nF.push(bad, bad);
          if (bad) inserted = true;
        } else nF.push(false);
        nT.push(T[k + 1]); nV.push(V[k + 1]);
      }
      T = nT; V = nV; flag = nF;
      pk = peakOf();
      if (!inserted) break;
      if (onProgress) onProgress(info.length, info.length + 1, 'output grid');
    }
    const nt = T.length;
    result.times = Float64Array.from(T);
    for (let i = 0; i < N; i++) {
      const o = new Float64Array(nt), b = new Float64Array(nt);
      const f = bqPerMol(result.thalf[i]);
      for (let k = 0; k < nt; k++) { o[k] = Math.max(0, V[k][i]); b[k] = o[k] * f; }
      result.out.push(o); result.bq.push(b);
    }
    // what the limit on the end leaves out: the release there, over its peak
    if (tEndCut) {
      const bits = [];
      for (let i = 0; i < N; i++) {
        const o = result.out[i];
        let pk = 0; for (const v of o) pk = Math.max(pk, v);
        if (pk > 0 && o[nt - 1] > 1e-9 * pk) bits.push(`${names[i]} at ${Number(o[nt - 1] / pk).toPrecision(2)} of its peak`);
      }
      if (bits.length) result.notes.push(`The output stops at ${Number(tEnd).toPrecision(3)} a, the page's limit, while the release goes on: ${bits.join(', ')} there.`);
    }
    result.tEndCut = tEndCut;
    // 5. peaks, refined by golden section in log t around the largest sample
    for (let i = 0; i < N; i++) {
      const o = result.out[i];
      let k = -1, best = 0;
      for (let q = 0; q < nt; q++) if (o[q] > best) { best = o[q]; k = q; }
      if (k < 0) { result.peaks.push({ name: names[i], t: NaN, rate: 0, bq: 0 }); continue; }
      let a = Math.log(T[Math.max(0, k - 1)]), b = Math.log(T[Math.min(nt - 1, k + 1)]);
      const g = (Math.sqrt(5) - 1) / 2;
      let c = b - g * (b - a), d = a + g * (b - a);
      let fc = outAt(Math.exp(c), i), fd = outAt(Math.exp(d), i);
      for (let it = 0; it < 40; it++) {
        if (fc > fd) { b = d; d = c; fd = fc; c = b - g * (b - a); fc = outAt(Math.exp(c), i); }
        else { a = c; c = d; fc = fd; d = a + g * (b - a); fd = outAt(Math.exp(d), i); }
      }
      let tp = Math.exp(0.5 * (a + b)), vp = outAt(tp, i);
      if (!(vp >= best)) { tp = T[k]; vp = best; }
      result.peaks.push({ name: names[i], t: tp, rate: vp, bq: vp * bqPerMol(result.thalf[i]) });
    }
    // extra times asked for (tests compare with a reference at its own times)
    if (settings.evalTimes && settings.evalTimes.length) {
      result.at = { times: Float64Array.from(settings.evalTimes), out: [] };
      for (let i = 0; i < N; i++) result.at.out.push(Float64Array.from(settings.evalTimes, (t) => outAt(num(t), i)));
    }
    const t3 = now();
    // 6. the check: de Hoog against the chosen method, on each response's samples
    if (settings.check !== false) result.check = checkResponses(ctx, ws, result.responses, method === 'dehoog' ? 'parabola' : 'dehoog', settings.checkPoints || 24);
    const t4 = now();
    result.timing = { setup: t1 - t0, responses: t2 - t1, output: t3 - t2, check: t4 - t3, total: t4 - t0, evaluations: ws.evaluations };
    result.tStart = tStart;
    result.infPe = ctx.infPe;
    result.rf = Array.from(ctx.rf);
    if (onProgress) onProgress(info.length + 1, info.length + 1, 'done');
    return result;
  }

  /** Recompute a spread of each response's samples by another method; the
      largest relative difference over samples above 1e-6 of the peak. */
  function checkResponses(ctx, ws, responses, other, npts) {
    let worst = 0, where = null, count = 0;
    for (const r of responses) {
      // a response that lets through less than 1e-30 of a pulse carries nothing (and no
      // method resolves it well): Am241 through strongly sorbing rock, Pb210's own
      if (r.t.length < 2 || !(r.peak > 0) || !(Math.abs(r.T0) > 1e-30)) continue;
      const idx = [];
      for (let k = 0; k < r.t.length; k++) if (r.h[k] > 1e-6 * r.peak) idx.push(k);
      if (!idx.length) continue;
      const step = Math.max(1, Math.floor(idx.length / npts));
      const ax = realAxis(ctx, ws, r.i, r.j, r.t[0], r.t[r.t.length - 1]);
      for (let q = 0; q < idx.length; q += step) {
        const k = idx[q];
        const mH = deHoogTerms(ctx, ax, r.t[k]);
        let v = other === 'dehoog' ? invertDeHoog(ctx, ws, r.i, r.j, r.t[k], { M: mH }) : invertParabola(ctx, ws, ax, r.t[k]).h;
        let d = Math.abs(v - r.h[k]) / Math.abs(r.h[k]);
        // de Hoog's series may be too short for a sharp front: twice the
        // terms decide, and what the two terms of de Hoog differ by among
        // themselves (its own noise, large far below a peak) is not counted
        // against the response
        if (other === 'dehoog' && !(d <= 1e-6)) {
          const v2 = invertDeHoog(ctx, ws, r.i, r.j, r.t[k], { M: Math.min(2 * mH, 320) });
          d = Math.max(0, Math.abs(v2 - r.h[k]) - Math.abs(v2 - v)) / Math.abs(r.h[k]);
          v = v2;
        }
        count++;
        if (d > worst || !isFinite(d)) { worst = isFinite(d) ? d : Infinity; where = { i: r.i, j: r.j, t: r.t[k] }; }
      }
    }
    return { method: other, worst, where, count };
  }

  return {
    LN2, AVOGADRO, YEAR_S, DEFAULT_DENSITY, MAX_CHAIN, Farf31Error,
    prepare, makeWorkspace, evalBlock, transfer, realAxis, saddleAt, rightmostSingularity, pairDelay, talbotSum, invertTalbot, invertParabola, invertDeHoog,
    logEstimate, responseSupport, computeResponse, transferAtZero, massBalance, deHoogTerms, normaliseSeries, convolveAt, seriesFromShapes,
    bqPerMol, run, checkResponses,
    _internal: { csqrt, ctanh, csech2, tauSeries, hSeries, makeDD, ddSetup, ddGet, get RE() { return RE; }, get IM() { return IM; } },
  };
}));
