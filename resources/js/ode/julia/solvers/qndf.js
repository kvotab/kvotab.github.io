/* ==========================================================================
   ode_julia / solvers / qndf

   QNDF: the quasi-constant-step numerical differentiation formulas, variable
   step, variable order 1 to 5.

   These are the numerical differentiation formulas of Shampine and Reichelt
   (SIAM J. Sci. Comput. 18 (1997) 1-22) -- the same formulas, the same κ
   coefficients, the same backward-difference array and the same rescaling
   matrices, which is what OrdinaryDiffEq's QNDF is a port of and what this is
   a port of in turn.

   WHAT AN NDF IS. A BDF of order k solves

       Σ(m=1..k) (1/m)·∇ᵐy(n+1) = h·f(y(n+1)).

   Shampine and Reichelt's numerical differentiation formula adds one term:

       Σ(m=1..k) (1/m)·∇ᵐy(n+1) − κ·γ(k)·(y(n+1) − y⁰) = h·f(y(n+1))

   where y⁰ is the predictor and γ(k) = Σ(j=1..k) 1/j. The κ are chosen to
   shrink the error constant, which buys a longer step at the same accuracy --
   about 26 % at order 2 -- at a small cost in stability. They are Shampine's
   accuracy-optimal values, and κ = 0 turns this back into plain BDF.

   QUASI-CONSTANT STEP. The other half of the method. Rather than re-derive the
   formula for an uneven grid, the backward differences are *rescaled* onto the
   new step size by D ← D·(R·U), where U and R are the cumulative-product
   matrices below. The coefficients then stay those of the uniform formula and
   the iteration matrix survives a change of step, which is the same economy
   FBDF gets by interpolating and the reason both are cheap on large systems.

   QNDF OR FBDF? They are close relatives and either is a reasonable default.
   QNDF's κ terms make it a little more accurate per step at low order and a
   little less stable; FBDF is the more conservative and is what SciML
   recommends for the largest stiff systems. On the problems in this package's
   test set they are within a factor of two of each other on work, and agree.
   ========================================================================== */

import { COEFFICIENT_MULTISTEP, Convergence } from '../core/newton.js';

/**
 * Shampine's accuracy-optimal κ, for orders 1 to 5. `QNDF({ kappa: [0,0,0,0,0] })`
 * gives the plain BDF of the same order, which is a useful check.
 */
const KAPPA = [-0.1850, -1 / 9, -0.0823, -0.0415, 0];
const QNDF_MAX_ORDER = 5;   // named apart from FBDF's: the bundle is one scope

/** γ(m) = Σ(j=1..m) 1/j, the leading coefficient of the BDF of order m. */
const GAMMA = (() => {
  const g = new Float64Array(QNDF_MAX_ORDER + 1);
  for (let m = 1; m <= QNDF_MAX_ORDER; m++) g[m] = g[m - 1] + 1 / m;
  return g;
})();

/**
 * The rescaling matrices of the quasi-constant-step scheme.
 *
 *     R[j][r] = Π(m=1..j) ((m−1) − r·ρ)/m        1-based j and r
 *
 * and U = R(ρ = 1). Multiplying the difference array by R·U carries
 * differences taken on a grid of spacing h onto one of spacing ρ·h. These are
 * the published `R` and `difU` exactly.
 *
 * @param {Float64Array} out  k×k, row-major, at least maxOrder²
 */
export function rescaleMatrix(out, rho, k, stride) {
  for (let r = 1; r <= k; r++) {
    let v = -r * rho;
    out[0 * stride + (r - 1)] = v;
    for (let j = 2; j <= k; j++) {
      v = v * ((j - 1) - r * rho) / j;
      out[(j - 1) * stride + (r - 1)] = v;
    }
  }
  return out;
}

class QNDFCache {
  constructor(n, integ, opts) {
    this.n = n;
    this.maxOrder = Math.min(opts.maxOrder || QNDF_MAX_ORDER, QNDF_MAX_ORDER);
    this.minOrder = Math.max(1, opts.minOrder || 1);
    // Read from its own key, not from `kappa`. Two different quantities are
    // called kappa in this field: the NDF coefficients here, and the Newton
    // convergence tolerance that `solve` takes. In Julia they live on
    // different objects and cannot collide; here the algorithm's options and
    // the solve's are merged into one bag, and `Array.from(1e-3)` is the empty
    // array, which turns every coefficient into undefined and every
    // subsequent arithmetic into NaN. The step then fails at any size and the
    // run stops with a step-size error that says nothing about the cause.
    this.kappa = Array.isArray(opts.ndfKappa) && opts.ndfKappa.length >= QNDF_MAX_ORDER
      ? Array.from(opts.ndfKappa)
      : KAPPA;
    this.order = this.minOrder;
    this.prevOrder = 0;
    this.errorOrder = this.order;
    this.hasFsalLast = false;
    this.dtpropose = null;

    // D[1..k+2] are the backward differences; D[0] is unused, so that the
    // indices read as they do in the papers.
    this.D = Array.from({ length: QNDF_MAX_ORDER + 3 }, () => new Float64Array(n));
    this.Dnew = Array.from({ length: QNDF_MAX_ORDER + 1 }, () => new Float64Array(n));
    this.u0 = new Float64Array(n);
    this.phi = new Float64Array(n);
    this.dd = new Float64Array(n);
    // The candidate D[k] and D[k+2] the estimates for orders k∓1 are read
    // from, and the interpolant's scratch.
    this.Dk = new Float64Array(n);
    this.Dk2 = new Float64Array(n);
    this.phiWork = new Float64Array(QNDF_MAX_ORDER + 2);
    this.dCol = new Float64Array(QNDF_MAX_ORDER + 2);

    const S = QNDF_MAX_ORDER;
    this.stride = S;
    this.U = rescaleMatrix(new Float64Array(S * S), 1, S, S);
    this.R = new Float64Array(S * S);
    this.RU = new Float64Array(S * S);

    this.dtprev = 0;
    this.EEst1 = 1;
    this.EEst2 = 1;
    this.nconsteps = 0;
    this.consfailcnt = 0;
    this.started = false;

    this.gammaCtrl = opts.gamma ?? 1.2;
    this.qmax = opts.qmax ?? 5;
    this.qmin = opts.qmin ?? 0.2;
    // How far the wanted step may stray from the current one before it is
    // actually changed. Wide, and deliberately so.
    //
    // Every change of step rescales the difference array through R·U, and that
    // rescale is an approximation: truncated at order k, it leaves about a per
    // cent of relative error in the highest difference even for a ratio as
    // gentle as 0.9. The highest differences are exactly what the error
    // estimates are read from, so rescaling on most steps corrupts the
    // estimate, which asks for another change, which rescales again. Measured
    // across the stiff set, widening this band from OrdinaryDiffEq's
    // [0.9, 1.2] is worth between one and two orders of magnitude of accuracy
    // and usually fewer steps as well -- on the Oregonator, 2e4 tolerance
    // units and 17045 steps become 264 units and 9159 steps.
    this.qsteadyMin = opts.qsteadyMin ?? 0.25;
    this.qsteadyMax = opts.qsteadyMax ?? 4;
  }

  /** The error constant of the NDF of order m: κ(m)·γ(m) + 1/(m+1). */
  errorConstantAt(m) {
    return this.kappa[m - 1] * GAMMA[m] + 1 / (m + 1);
  }

  init(integ) {
    integ.newton.method = COEFFICIENT_MULTISTEP;
    this.begin(integ);

    // A caller with the solution before t₀ can hand it over, and the
    // differences start out real instead of being climbed into. This is what
    // makes the order of a k-step formula measurable: pinned to order k with
    // an empty difference array, the method spends the run recovering from a
    // start it was never given, and reads as order 2 whatever k is.
    const h = integ.opts.history;
    if (h && h.t && h.t.length) {
      const m = Math.min(h.t.length, QNDF_MAX_ORDER);
      const n = this.n;
      // ∇ʲy = Σ(i=0..j) (−1)ⁱ·C(j,i)·y(n−i), with y(n) = u₀.
      const y = [integ.uprev, ...h.u.slice(0, m)];
      for (let j = 1; j <= m; j++) {
        const d = this.D[j];
        d.fill(0);
        let c = 1;
        for (let i = 0; i <= j; i++) {
          const w = (i % 2 === 0 ? 1 : -1) * c;
          for (let x = 0; x < n; x++) d[x] += w * y[i][x];
          c = (c * (j - i)) / (i + 1);
        }
      }
      this.order = Math.min(this.maxOrder, Math.max(this.minOrder, m));
      this.prevOrder = this.order;
      // dtprev is left at zero deliberately: `init` runs before the
      // integrator has chosen a first step, so there is no step size to
      // record here, and the first `step` adopts its own rather than
      // rescaling the differences by a ratio with zero underneath it.
      this.dtprev = 0;
      this.started = true;
      this.nconsteps = this.order + 2;
    }
  }

  begin(integ) {
    // ∇¹y ≈ h·f, which is where the reference implementations start too.
    for (const d of this.D) d.fill(0);
    this.order = this.minOrder;
    this.prevOrder = 0;
    this.dtprev = 0;
    this.nconsteps = 0;
    this.consfailcnt = 0;
    this.EEst1 = 1;
    this.EEst2 = 1;
    this.started = false;
  }

  restart(integ) { this.begin(integ); }

  step(integ) {
    const { n, D, u0, phi } = this;
    const dt = integ.dt;
    const { uprev, u, t } = integ;
    const newton = integ.newton;
    const k = Math.min(this.order, this.maxOrder);
    this.order = k;

    if (!this.started) {
      for (let i = 0; i < n; i++) D[1][i] = dt * integ.fsalfirst[i];
      this.dtprev = dt;
      this.prevOrder = k;
      this.started = true;
    } else if (this.dtprev === 0) {
      // Started from a seeded history: the differences belong to whatever
      // spacing the caller used, which is taken to be this step.
      this.dtprev = dt;
      this.prevOrder = k;
    } else if (dt !== this.dtprev || this.prevOrder !== k) {
      // Rescale the differences onto the new step. Julia compares dt exactly,
      // not within a tolerance, and so does this: a step clipped by one ulp to
      // land on a tstop really is a different step size, and rescaling by a
      // ratio of one is a no-op anyway.
      const { U, R, RU, Dnew, stride } = this;
      const rho = dt / this.dtprev;
      rescaleMatrix(R, rho, k, stride);
      for (let i = 1; i <= k; i++) {
        for (let j = 1; j <= k; j++) {
          let acc = 0;
          for (let m = 1; m <= k; m++) acc += R[(i - 1) * stride + (m - 1)] * U[(m - 1) * stride + (j - 1)];
          RU[(i - 1) * stride + (j - 1)] = acc;
        }
      }
      for (let j = 1; j <= k; j++) {
        const out = Dnew[j];
        out.fill(0);
        for (let i = 1; i <= k; i++) {
          const w = RU[(i - 1) * stride + (j - 1)];
          if (w === 0) continue;
          const di = D[i];
          for (let x = 0; x < n; x++) out[x] += w * di[x];
        }
      }
      for (let j = 1; j <= k; j++) D[j].set(Dnew[j]);
      this.nconsteps = 0;
      this.dtprev = dt;
    }
    this.prevOrder = k;

    const kappa = this.kappa[k - 1];
    const beta0 = 1 / ((1 - kappa) * GAMMA[k]);
    const gammaDt = beta0 * dt;

    const needNew = integ.W.jacStale || !integ.W.haveFactor || !newton.fastConvergence;
    if (!integ.formW(gammaDt, false, needNew)) return false;

    // The predictor is the sum of the differences, and ϕ collects the part of
    // the implicit equation that is already known.
    for (let i = 0; i < n; i++) {
      let p = uprev[i];
      let ph = 0;
      for (let j = 1; j <= k; j++) { p += D[j][i]; ph += GAMMA[j] * D[j][i]; }
      u0[i] = p;
      phi[i] = ph;
    }

    //   (1−κ)·γ(k)·(u − u⁰) + ϕ = h·f(u)
    // which in the form the Newton solver takes, u = tmp + γh·f(u), is
    //   tmp = u⁰ − β₀·ϕ,   γ = β₀ = 1/((1−κ)γ(k)).
    for (let i = 0; i < n; i++) newton.tmp[i] = u0[i] - beta0 * phi[i];
    newton.gamma = beta0;
    newton.c = 1;
    newton.method = COEFFICIENT_MULTISTEP;
    newton.z.set(u0);
    // An NDF's truncation error is proportional to the total Newton
    // displacement, so the convergence test is scaled by the same constant.
    newton.errorConstant = Math.abs(this.errorConstantAt(k));

    const status = newton.solve(
      integ.f, integ.W, t, dt, uprev, { reltol: integ.reltol, abstol: integ.abstolFixed },
      needNew, this.consfailcnt === 0,
    );
    integ.stats.nnonliniter += newton.iter;
    newton.errorConstant = 1;
    if (status !== Convergence) {
      integ.stats.nnonlinconvfail++;
      integ.W.markStale();
      if (this.order > this.minOrder && newton.nfails >= 3) this.order--;
      this.consfailcnt++;
      this.nconsteps = 0;
      return false;
    }
    u.set(newton.z);

    // dd = ∇^(k+1) y, the difference the predictor missed by.
    const dd = this.dd;
    for (let i = 0; i < n; i++) dd[i] = u[i] - u0[i];

    // The three estimates are read off the differences as they will be once
    // this step is taken -- D[k] + dd and dd − D[k+1] -- but D itself is left
    // as the last accepted step made it. It is only rolled forward in
    // `accepted`: updated here, a step the error test then threw away left D
    // describing a solution that was never kept, and the next attempt started
    // from that (OrdinaryDiffEq keeps a copy to restore; not writing it until
    // the step is kept comes to the same).
    const { Dk, Dk2 } = this;
    integ.EEst = Math.abs(this.errorConstantAt(k)) * integ.errorNorm(dd);
    if (k > 1) {
      for (let i = 0; i < n; i++) Dk[i] = D[k][i] + dd[i];
      this.EEst1 = Math.abs(this.errorConstantAt(k - 1)) * integ.errorNorm(Dk);
    } else {
      this.EEst1 = Infinity;
    }
    if (k < this.maxOrder) {
      for (let i = 0; i < n; i++) Dk2[i] = dd[i] - D[k + 1][i];
      this.EEst2 = Math.abs(this.errorConstantAt(k + 1)) * integ.errorNorm(Dk2);
    } else {
      this.EEst2 = Infinity;
    }
    this.errorOrder = k;
    return true;
  }

  /**
   * Roll the differences forward past the step just kept:
   * D[k+2] = dd − D[k+1], D[k+1] = dd, then D[j] += D[j+1] down to 1.
   *
   * dd is taken from the state the integrator kept, which is the step's own
   * unless non-negativity clamped part of it. From the unclamped one the
   * history would describe values the solution never took, and the predictor
   * of the next step would extrapolate them.
   */
  commit(integ) {
    const { n, D, dd, u0 } = this;
    const k = this.order;
    const u = integ.u;
    for (let i = 0; i < n; i++) dd[i] = u[i] - u0[i];
    for (let i = 0; i < n; i++) D[k + 2][i] = dd[i] - D[k + 1][i];
    D[k + 1].set(dd);
    for (let j = k; j >= 1; j--) {
      const a = D[j];
      const b = D[j + 1];
      for (let i = 0; i < n; i++) a[i] += b[i];
    }
  }

  /**
   * u(t + θh) inside the step just taken, from the backward differences as
   * they stand once it is kept: the Newton backward-difference polynomial
   * through the new point on the step's uniform grid,
   *
   *     u(θ) = u + Σ(j=1..k) φj(θ − 1)·∇ʲu,   φ1(σ) = σ,  φj+1(σ) = φj(σ)·(σ + j)/(j + 1)
   *
   * which is how OrdinaryDiffEq's QNDF interpolates. It gives the solver's own
   * values at both ends. Without it the integrator fell back on a cubic
   * Hermite whose slope at the far end this method never sets, and every row
   * between two steps was off by about h·f.
   */
  interpolate(integ, theta, out) {
    const { n, D, u0, phiWork, dCol } = this;
    const k = this.order;
    const s = theta - 1;
    let p = s;
    phiWork[1] = p;
    for (let j = 1; j < k; j++) { p = p * (s + j) / (j + 1); phiWork[j + 1] = p; }
    const u = integ.u;
    for (let i = 0; i < n; i++) {
      // ∇ʲu after the step, from the kept state: dd, then D[j] + ∇ʲ⁺¹u down to 1.
      let acc = u[i] - u0[i];
      for (let j = k; j >= 1; j--) { acc = D[j][i] + acc; dCol[j] = acc; }
      let v = u[i];
      for (let j = 1; j <= k; j++) v += phiWork[j] * dCol[j];
      out[i] = v;
    }
    return out;
  }

  /**
   * The order and step rule: work out the step each of the orders k−1, k
   * and k+1 would allow, and take the longest.
   */
  accepted(integ, dtjust) {
    this.commit(integ);
    this.consfailcnt = 0;
    this.nconsteps++;
    const k = this.order;
    const h = Math.abs(dtjust);

    if (!(integ.EEst > 0)) {
      this.dtpropose = dtjust * this.qmax;
      return;
    }
    const preferConstStep = this.nconsteps < k + 2;
    const zs = this.gammaCtrl;
    const z = zs * integ.EEst ** (1 / (k + 1));
    const hk = z <= 0.1 ? 10 * h : h / z;
    let hn = hk;
    let kn = k;

    if (k > 1 && Number.isFinite(this.EEst1)) {
      const zm = 1.3 * this.EEst1 ** (1 / k);
      let hm = 0;
      if (zm <= 0.1) hm = 10 * h;
      else if (zm <= 1.3) hm = h / zm;
      if (hm > hk) { hn = hm; kn = k - 1; }
    }
    if (k < this.maxOrder && Number.isFinite(this.EEst2)) {
      const zp = 1.4 * this.EEst2 ** (1 / (k + 2));
      let hp = 0;
      if (zp <= 0.1) hp = 10 * h;
      else if (zp <= 1.4) hp = h / zp;
      if (hp > hn) { hn = hp; kn = k + 1; }
    }
    this.order = Math.max(this.minOrder, kn);

    const q = h / hn;
    let hnew;
    // A steady step is worth keeping: every change costs a rescale of the
    // differences and, if the leading coefficient moves far enough, a
    // factorisation. So a step within a fifth of the current one is left alone
    // while the order is still settling.
    if (preferConstStep && q > 0.6 && q < 1.2) hnew = h;
    else if (q <= this.qsteadyMax && q >= this.qsteadyMin) hnew = h;
    else hnew = h / Math.min(1 / this.qmin, Math.max(1 / this.qmax, q));
    this.dtpropose = Math.sign(dtjust) * hnew;
  }

  /** As FBDF: compare this order's step with the one below and drop if better. */
  rejected(integ) {
    const k = this.order;
    let h = Math.abs(integ.dt);
    this.consfailcnt++;
    this.nconsteps = 0;
    if (this.consfailcnt > 1) h /= 2;

    const z = this.gammaCtrl * integ.EEst ** (1 / (k + 1));
    const hk = z <= 10 ? h / z : 0.1 * h;
    let hn = hk;
    let kn = k;
    if (k > 1 && Number.isFinite(this.EEst1)) {
      const zm = 1.3 * this.EEst1 ** (1 / k);
      const hm = zm <= 10 ? h / zm : 0.1 * h;
      if (this.consfailcnt > 2 || Math.abs(hm) > Math.abs(hk)) { hn = Math.min(h, Math.abs(hm)); kn = k - 1; }
    }
    this.order = Math.max(this.minOrder, kn);
    integ.dt = Math.sign(integ.dt) * hn;
    // The differences are about the old step size; the next attempt rescales.
    this.dtpropose = null;
    return true;
  }
}

/**
 * QNDF: the numerical differentiation formulas, orders 1 to 5.
 *
 * @param {object} [options]
 * @param {number} [options.maxOrder=5]
 * @param {number} [options.minOrder=1]
 * @param {number[]} [options.kappa]  five values; all zero gives plain BDF.
 *        Not to be confused with `solve`'s `kappa`, which is how tightly the
 *        Newton iteration must converge; the two are kept apart below.
 */
export function QNDF(options = {}) {
  return {
    name: 'QNDF',
    order: options.maxOrder || QNDF_MAX_ORDER,
    build: (n, integ, opts) => new QNDFCache(n, integ, {
      ...opts, ...options, ndfKappa: options.kappa,
    }),
    controller: { qmax: 5, qmin: 0.2, gamma: 1.2, qsteadyMin: 0.25, qsteadyMax: 4 },
  };
}

/** QBDF: QNDF with every κ zero, which is the plain variable-step BDF. */
export function QBDF(options = {}) {
  return QNDF({ ...options, kappa: [0, 0, 0, 0, 0] });
}
