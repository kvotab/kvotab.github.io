/* ==========================================================================
   ode_julia / solvers / fbdf

   FBDF: the fixed-leading-coefficient backward differentiation formulas,
   variable step, variable order 1 to 5.

   WHY FIXED LEADING COEFFICIENT. A BDF formula is derived on a uniform grid.
   A variable-step solver has no uniform grid, and there are two ways out. The
   variable-coefficient approach re-derives the formula for the actual spacing
   at every step, which is accurate but means the iteration matrix's leading
   coefficient moves whenever the step does, so W has to be re-formed and
   re-factorised. The fixed-leading-coefficient approach instead interpolates
   the real history onto a *fictitious* uniform grid of spacing h and applies
   the textbook formula to that. The leading coefficient is then a constant
   depending only on the order, W survives a change of step size, and on a
   large stiff system that is most of the cost.

       Σⱼ αⱼ·ȳ(t + h − j·h) = h·f(t + h, y)      ȳ = the interpolant of the
                                                  real history

   This is what CVODE, LSODE and Julia's FBDF all do, and it is why FBDF is
   the right default for big stiff systems.

   THE ORDER MACHINERY. Four error estimates are kept each step -- for orders
   k−2, k−1, k and k+1 -- each the scaled norm of hᵐ⁻¹·y⁽ᵐ⁻¹⁾ computed from the
   real, unequally spaced history by a Fornberg finite-difference formula. The
   order goes up only when all four are decreasing and a countdown since the
   last change has expired, and comes down as soon as they stop decreasing.
   The countdown (CVODE's `qwait`) is what stops the order oscillating.
   ========================================================================== */

import { COEFFICIENT_MULTISTEP, Convergence } from '../core/newton.js';

/**
 * Classical BDF coefficients, row k for order k:
 *
 *     Σⱼ₌₀ᵏ αⱼ·y(n+1−j) = h·f(y(n+1)),   α₀ = Σⱼ₌₁ᵏ 1/j
 *
 * Exact rationals, written out: a wrong digit here is a wrong method.
 */
const BDF_COEFFS = [
  null,                                                   // no order 0
  [1, -1],
  [3 / 2, -2, 1 / 2],
  [11 / 6, -3, 3 / 2, -1 / 3],
  [25 / 12, -4, 3, -4 / 3, 1 / 4],
  [137 / 60, -5, 5, -10 / 3, 5 / 4, -1 / 5],
];
const MAX_ORDER_LIMIT = 5;

/**
 * Fornberg's weights for the m-th derivative at `x0` from the nodes `xs`.
 *
 * Returns the weights for the highest derivative only, which is all any caller
 * here needs. (OrdinaryDiffEq's own routine returns a whole table whose lower
 * columns are wrong -- it zeroes an entry it never reads. Computing just the
 * column that is used avoids inheriting that.)
 *
 *   Fornberg, B. (1988). Generation of finite difference formulas on
 *   arbitrarily spaced grids. Mathematics of Computation 51, 699-706.
 *
 * @param {Float64Array} xs  n nodes
 * @param {number} count     how many nodes to use, from the front
 * @param {number} x0        where the derivative is wanted
 * @param {number} m         order of the derivative; m < count
 * @param {Float64Array} out length >= count
 */
export function fornbergWeights(xs, count, x0, m, out, work) {
  // work is a (count x (m+1)) scratch table, column-major by derivative order.
  const c = work;
  const stride = count;
  c.fill(0, 0, count * (m + 1));
  c[0] = 1;                                  // c[node 0][deriv 0]
  let c1 = 1;
  let c4 = xs[0] - x0;
  for (let i = 1; i < count; i++) {
    const mn = Math.min(i, m);
    let c2 = 1;
    const c5 = c4;
    c4 = xs[i] - x0;
    for (let j = 0; j < i; j++) {
      const c3 = xs[i] - xs[j];
      c2 *= c3;
      if (j === i - 1) {
        for (let k = mn; k >= 1; k--) {
          c[i + k * stride] = c1 * (k * c[(i - 1) + (k - 1) * stride]
            - c5 * c[(i - 1) + k * stride]) / c2;
        }
        c[i] = -c1 * c5 * c[i - 1] / c2;
      }
      for (let k = mn; k >= 1; k--) {
        c[j + k * stride] = (c4 * c[j + k * stride] - k * c[j + (k - 1) * stride]) / c3;
      }
      c[j] = c4 * c[j] / c3;
    }
    c1 = c2;
  }
  for (let i = 0; i < count; i++) out[i] = c[i + m * stride];
  return out;
}

class FBDFCache {
  constructor(n, integ, opts) {
    this.n = n;
    this.maxOrder = Math.min(opts.maxOrder || MAX_ORDER_LIMIT, MAX_ORDER_LIMIT);
    this.minOrder = Math.max(1, opts.minOrder || 1);
    this.order = this.minOrder;
    this.prevOrder = this.order;
    this.errorOrder = this.order;
    this.hasFsalLast = false;
    this.dtpropose = null;

    const K = MAX_ORDER_LIMIT + 2;
    // The history's times, measured from its newest point: ts[0] = 0 and ts[j]
    // is minus the last j steps. Not the clock readings. Late in a run the
    // clock rounds to a sizeable fraction of a short step -- half an ulp of
    // 5000 is 4.5e-13, 3 % of the smallest step there -- and a polynomial
    // through points at the rounded times is not the one the formula built:
    // its slope is off by that fraction, and the predictor carries |f| times
    // the rounding into the error estimate as though it were error. Summing
    // the steps themselves keeps the spacing the formula used.
    this.ts = new Float64Array(K);
    this.uHistory = Array.from({ length: K }, () => new Float64Array(n));
    this.nHistory = 0;

    this.thetas = new Float64Array(K);
    this.corrector = Array.from({ length: K }, () => new Float64Array(n));
    this.upred = new Float64Array(n);
    this.terkTmp = new Float64Array(n);
    this.terkp1Tmp = new Float64Array(n);
    this.lagWork = new Float64Array(K);
    this.tsTmp = new Float64Array(K + 1);
    this.fdWeights = new Float64Array(K + 1);
    this.fdWork = new Float64Array((K + 1) * (K + 2));

    // The four estimates, and the bookkeeping that gates an order change.
    this.terkm2 = Infinity;
    this.terkm1 = Infinity;
    this.terk = Infinity;
    this.terkp1 = 0;
    this.qwait = 3;
    this.nconsteps = 0;
    this.consfailcnt = 0;
    this.itersFromEvent = 0;

    this.gammaCtrl = opts.gamma ?? 1.2;      // the BDF family uses 6/5, not 9/10
    this.qmax = opts.qmax ?? 5;
    this.qmin = opts.qmin ?? 0.2;
    this.qsteadyMin = opts.qsteadyMin ?? 0.9;
    this.qsteadyMax = opts.qsteadyMax ?? 1.2;
  }

  init(integ) {
    integ.newton.method = COEFFICIENT_MULTISTEP;
    this.ts[0] = 0;
    this.uHistory[0].set(integ.uprev);
    this.nHistory = 1;
    this.itersFromEvent = 0;

    // A caller who already knows the solution before t₀ can hand it over, and
    // the method starts at its full order instead of climbing to it. Useful
    // for continuing a run that was interrupted, and it is what makes the
    // order of a k-step formula measurable at all: started cold, the first few
    // steps are order 1 and 2 whatever the rest of the run does.
    const h = integ.opts.history;
    if (h && h.t && h.t.length) {
      const m = Math.min(h.t.length, this.uHistory.length - 1);
      for (let j = 0; j < m; j++) {
        this.ts[j + 1] = h.t[j] - integ.t;
        this.uHistory[j + 1].set(h.u[j]);
      }
      this.nHistory = m + 1;
      this.itersFromEvent = m;
      this.order = Math.min(this.maxOrder, Math.max(this.minOrder, m));
      this.qwait = 0;
    }
  }

  /** History is meaningless after a discontinuity: start again at order 1. */
  restart(integ) {
    this.ts[0] = 0;
    this.uHistory[0].set(integ.uprev);
    this.nHistory = 1;
    this.itersFromEvent = 0;
    this.order = this.minOrder;
    this.prevOrder = this.order;
    this.qwait = 3;
    this.nconsteps = 0;
    this.consfailcnt = 0;
    this.terkm2 = this.terkm1 = this.terk = Infinity;
    this.terkp1 = 0;
  }

  /**
   * The Lagrange interpolant of the history, in θ = (τ − t)/h, at θ = xi.
   *
   * Summed as the newest point plus weighted differences from it, which is the
   * same polynomial -- the weights add up to one -- but not the same
   * arithmetic. Σ wⱼ·uⱼ of a component that is not changing is its value only
   * to rounding, and the weights here are large: after the step has grown
   * five-fold the past points sit within one new step, and at order 5 the
   * weights run to 2e3 for the predictor and to 1e5 for the value the formula
   * reads four steps back. A bookkeeping species that had stopped changing
   * then wandered by 1e4 ulps, and an event on it went on firing. Differences
   * of a constant are zero.
   */
  lagrange(xi, count, out) {
    const { thetas, uHistory, n } = this;
    const u0 = uHistory[0];
    out.set(u0);
    for (let j = 1; j < count; j++) {
      let w = 1;
      for (let m = 0; m < count; m++) {
        if (m === j) continue;
        w *= (xi - thetas[m]) / (thetas[j] - thetas[m]);
      }
      if (w === 0) continue;
      const uj = uHistory[j];
      for (let i = 0; i < n; i++) out[i] += w * (uj[i] - u0[i]);
    }
    return out;
  }

  /**
   * ‖h^(m−1)·y^(m−1)(t+h)‖, from the real history by an m-node formula.
   * This is the quantity the order selection compares across m.
   */
  estimateTerk(integ, m) {
    const { n, ts, uHistory, tsTmp, fdWeights, fdWork, terkTmp } = this;
    const dt = integ.dt;
    const count = Math.min(m, this.nHistory + 1);
    if (count < 2) return Infinity;
    tsTmp[0] = dt;                           // the new point, from the newest old one
    for (let i = 0; i < count - 1; i++) tsTmp[i + 1] = ts[i];
    fornbergWeights(tsTmp, count, dt, count - 1, fdWeights, fdWork);
    const w0 = fdWeights[0];
    for (let i = 0; i < n; i++) terkTmp[i] = w0 * integ.u[i];
    for (let j = 1; j < count; j++) {
      const w = fdWeights[j];
      const uj = uHistory[j - 1];
      for (let i = 0; i < n; i++) terkTmp[i] += w * uj[i];
    }
    const scale = Math.abs(dt) ** (count - 1);
    for (let i = 0; i < n; i++) terkTmp[i] *= scale;
    return integ.errorNorm(terkTmp);
  }

  step(integ) {
    const { n, ts, uHistory, thetas, corrector } = this;
    const dt = integ.dt;
    const { uprev, u, t } = integ;
    const newton = integ.newton;
    let k = Math.min(this.order, Math.max(1, this.nHistory));
    this.order = k;
    const a = BDF_COEFFS[k];
    const gamma = 1 / a[0];
    const gammaDt = gamma * dt;
    const tdt = dt;                          // t + dt, on the history's own clock

    // W survives a change of step size here far better than it would for a
    // variable-coefficient BDF, which is the point of the method. A new
    // Jacobian is a separate and much larger expense: `form` rebuilds W from
    // the stored one whenever γh has moved, so only a labouring Newton or an
    // invalidated matrix justifies differencing again.
    const needNew = integ.W.jacStale || !integ.W.haveFactor || !newton.fastConvergence;
    if (!integ.formW(gammaDt, false, needNew)) return false;

    const count = Math.min(k + 1, this.nHistory);
    for (let j = 0; j < count; j++) thetas[j] = ts[j] / dt;

    // The predictor, and the history resampled onto the fictitious uniform grid.
    const upred = this.upred;
    if (this.itersFromEvent >= 1 && count >= 2) {
      this.lagrange(1, count, upred);
      for (let i = 1; i < k; i++) this.lagrange(-i, count, corrector[i]);
    } else {
      // The first step, at a start or a restart, with one point of history:
      // predict by an Euler step from it, as QNDF, the NDF and CVODE do. The
      // error estimate below is the predictor-corrector difference times BDF1's
      // error constant, which is an estimate of the local error only if that
      // difference is O(h²): from the Euler predictor it is h·(f(u) − f(uprev)).
      // OrdinaryDiffEq predicts the last value itself, and then the difference
      // is h·f -- O(h), with the whole derivative in it. After a jump f is large
      // and the time is late, so that no representable step passed: a model
      // whose packages failed at t = 5000 was refused at a step of 1.5e-11.
      const f0 = integ.fsalfirst;
      for (let i = 0; i < n; i++) upred[i] = uprev[i] + dt * f0[i];
      for (let i = 1; i < k; i++) corrector[i].set(uprev);
    }

    // tmp collects everything on the left that is already known:
    // −(α₁·uₙ + Σ αₘ₊₁·ũₙ₋ₘ)/α₀, written with the α summing to zero as
    // uₙ − Σ αₘ₊₁·(ũₙ₋ₘ − uₙ)/α₀, so that a component at rest stays exactly
    // where it is (see lagrange).
    for (let i = 0; i < n; i++) {
      let v = 0;
      for (let m = 1; m < k; m++) v += a[m + 1] * (corrector[m][i] - uprev[i]);
      newton.tmp[i] = uprev[i] - v * gamma;
    }
    newton.gamma = gamma;
    newton.c = 1;
    newton.method = COEFFICIENT_MULTISTEP;
    newton.z.set(upred);
    // BDF's truncation error is proportional to the total Newton displacement,
    // so the convergence test is tightened by the same constant.
    newton.errorConstant = 1 / (k + 1);

    const status = newton.solve(
      integ.f, integ.W, t, dt, uprev, { reltol: integ.reltol, abstol: integ.abstolFixed },
      needNew, this.consfailcnt === 0,
    );
    integ.stats.nnonliniter += newton.iter;
    newton.errorConstant = 1;
    if (status !== Convergence) {
      integ.stats.nnonlinconvfail++;
      integ.W.markStale();
      // Three failures in a row is the history's fault, not the step's.
      if (this.order > 1 && newton.nfails >= 3) this.order--;
      this.consfailcnt++;
      this.nconsteps = 0;
      return false;
    }
    u.set(newton.z);

    // --- the local error, from the predictor-corrector difference -----------
    const terkp1Tmp = this.terkp1Tmp;
    for (let i = 0; i < n; i++) terkp1Tmp[i] = u[i] - upred[i];
    for (let j = 0; j < count; j++) {
      const s = ((j + 1) * dt) / (tdt - ts[j]);
      for (let i = 0; i < n; i++) terkp1Tmp[i] *= s;
    }
    // The leading error constant for this order on this (uneven) grid.
    let lte = -1 / (1 + k);
    for (let j = 2; j <= k; j++) {
      let r = 1 - j;
      for (let m = 2; m <= count; m++) r *= ((tdt - j * dt) - ts[m - 1]) / (m * dt);
      lte -= a[j - 1] * r;
    }
    const terkTmp = this.terkTmp;
    for (let i = 0; i < n; i++) terkTmp[i] = lte * terkp1Tmp[i];
    integ.EEst = integ.errorNorm(terkTmp);

    // --- what the order should be next --------------------------------------
    this.terk = this.estimateTerk(integ, k + 1);
    this.terkm1 = k > 1 ? this.estimateTerk(integ, k) : Infinity;
    this.terkm2 = k > 2 ? this.estimateTerk(integ, k - 1) : Infinity;
    this.terkp1 = (this.qwait === 0 && k < this.maxOrder && this.nHistory >= k + 2)
      ? this.estimateTerk(integ, k + 2)
      : 0;
    this.terkm3 = k > 3 ? this.estimateTerk(integ, k - 2) : Infinity;
    this.errorOrder = k;

    // Decided here, not in `accepted`, because every estimate below is taken
    // from the step that has just happened -- t, dt and u all belong to it --
    // and by the time `accepted` runs the integrator has already moved t on.
    this.decide(integ);
    return true;
  }

  /**
   * u(t + θh) inside the step just taken, from the method's own polynomial:
   * the Lagrange interpolant through the new point, at θ = 1, and the points
   * of history the step was taken from -- k of them at order k, fewer while
   * the history is shorter -- as OrdinaryDiffEq's FBDF interpolates. It gives
   * the solver's own values at both ends of the step. Without it the
   * integrator fell back on a cubic Hermite whose slope at the far end this
   * method never sets, and every row between two steps was off by about h·f.
   */
  interpolate(integ, theta, out) {
    const { n, thetas, uHistory } = this;
    const m = Math.min(this.order, this.nHistory);
    let w = 1;
    for (let j = 0; j < m; j++) w *= (theta - thetas[j]) / (1 - thetas[j]);
    // As in lagrange: the step's first point plus weighted differences from it.
    const u = integ.u;
    const u0 = uHistory[0];
    for (let i = 0; i < n; i++) out[i] = u0[i] + w * (u[i] - u0[i]);
    for (let a = 1; a < m; a++) {
      let wa = (theta - 1) / (thetas[a] - 1);
      for (let b = 0; b < m; b++) {
        if (b === a) continue;
        wa *= (theta - thetas[b]) / (thetas[a] - thetas[b]);
      }
      if (wa === 0) continue;
      const ua = uHistory[a];
      for (let i = 0; i < n; i++) out[i] += wa * (ua[i] - u0[i]);
    }
    return out;
  }

  /** Choose the next order and step size from the four estimates. */
  decide(integ) {
    this.prevOrderPending = this.order;
    let k = this.order;
    let terk = this.terk;
    let { terkm1, terkm2, terkp1 } = this;
    const decreasing = () => terkm2 > terkm1 && terkm1 > terk && terk > terkp1;
    if (k < this.maxOrder && this.qwait === 0
      && ((k === 1 && terk > terkp1)
        || (k === 2 && terkm1 > terk && terk > terkp1)
        || (k > 2 && decreasing()))) {
      k += 1;
      terk = terkp1;
    } else {
      // Walk down while the estimates are not decreasing. Only one extra
      // estimate is available (terkm3), so the walk is bounded at one step --
      // which is what happens in practice anyway.
      if (!decreasing() && k > Math.max(2, this.minOrder)) {
        terkp1 = terk;
        terk = terkm1;
        terkm1 = terkm2;
        terkm2 = this.terkm3;
        k -= 1;
      }
    }
    this.nextOrder = k;
    this.nextTerk = terk;
  }

  /** Roll the history forward and take the decision made during the step. */
  accepted(integ, dtjust) {
    this.prevOrder = this.prevOrderPending;
    const k = this.nextOrder;
    const terk = this.nextTerk;
    if (k !== this.order) { this.nconsteps = 0; this.order = k; }

    let q;
    if (!(terk > 0)) {
      q = 1 / this.qmax;
    } else {
      // CVODE's formula: eta = 1/(BIAS2·dsm)^(1/(k+1)), dsm = terk/(α₀(k+1)),
      // BIAS2 = 6.
      const alpha0 = BDF_COEFFS[k][0];
      q = (6 * terk / (alpha0 * (k + 1))) ** (1 / (k + 1));
    }
    q = Math.min(1 / this.qmin, Math.max(1 / this.qmax, q));
    if (q <= this.qsteadyMax && q >= this.qsteadyMin) q = 1;

    this.consfailcnt = 0;
    this.nconsteps++;
    this.itersFromEvent++;
    if (this.order !== this.prevOrder) this.qwait = this.order + 2;
    else if (this.qwait > 0) this.qwait--;

    // Roll the history forward: the new point goes to the front, and every
    // older one is now a further step of the size just taken behind it.
    const K = this.uHistory.length;
    const last = this.uHistory[K - 1];
    for (let j = K - 1; j > 0; j--) {
      this.uHistory[j] = this.uHistory[j - 1];
      this.ts[j] = this.ts[j - 1] - dtjust;
    }
    this.uHistory[0] = last;
    this.uHistory[0].set(integ.u);
    this.ts[0] = 0;
    if (this.nHistory < K) this.nHistory++;

    this.dtpropose = dtjust / q;
  }

  /**
   * A rejected step, as Julia's bdf_step_reject_controller: compare the step
   * this order wants with the one the order below wants, and drop the order if
   * the lower one may take a longer step.
   */
  rejected(integ) {
    const k = this.order;
    let h = Math.abs(integ.dt);
    this.consfailcnt++;
    this.nconsteps = 0;
    if (this.consfailcnt > 1) h /= 2;

    const zs = this.gammaCtrl;
    const z = zs * integ.EEst ** (1 / (k + 1));
    let hk = z <= 10 ? h / z : 0.1 * h;
    let hn = hk;
    let kn = k;
    if (k > 1 && Number.isFinite(this.terkm1)) {
      const zk1 = 1.3 * this.terkm1 ** (1 / k);
      const hk1 = zk1 <= 10 ? h / zk1 : 0.1 * h;
      if (this.consfailcnt > 2 || Math.abs(hk1) > Math.abs(hk)) {
        hn = Math.min(h, Math.abs(hk1));
        kn = k - 1;
      }
    }
    this.order = Math.max(this.minOrder, kn);
    integ.dt = Math.sign(integ.dt) * hn;
    // The integrator's own controller must not also shrink the step.
    this.dtpropose = null;
    return true;
  }
}

/**
 * FBDF: fixed-leading-coefficient BDF, orders 1 to 5, variable step.
 *
 * @param {object} [options]
 * @param {number} [options.maxOrder=5]
 * @param {number} [options.minOrder=1]
 */
export function FBDF(options = {}) {
  return {
    name: 'FBDF',
    order: options.maxOrder || MAX_ORDER_LIMIT,
    build: (n, integ, opts) => new FBDFCache(n, integ, { ...opts, ...options }),
    // FBDF chooses its own step; the generic controller is only a fallback.
    controller: { qmax: 5, qmin: 0.2, gamma: 1.2, qsteadyMin: 0.9, qsteadyMax: 1.2 },
  };
}
