/* ==========================================================================
   ode_julia / core / controller

   Choosing the next step size from the error estimate.

   The PI controller is OrdinaryDiffEq's default for these methods and is what
   is implemented here, with its coefficients:

       β₁ = 7/(10k),  β₂ = 2/(5k)      k the order of the error estimate
       γ  = 9/10,     qmin = 1/5,      qmax = 10
       qoldinit = 1e-4

   The proportional term alone (the I controller, β₂ = 0) is the textbook
   h·(1/EEst)^(1/k). The integral term damps the oscillation that the plain
   version falls into on stiff problems, where one lucky step is followed by
   one that is far too large. Setting `beta2: 0` recovers the I controller,
   which is what the BDF methods use when they change order.
   ========================================================================== */

/**
 * @param {object} opts
 * @param {number} opts.order      the order of the *error estimate*
 * @param {number} [opts.beta1]
 * @param {number} [opts.beta2]
 * @param {number} [opts.gamma=0.9]      safety factor
 * @param {number} [opts.qmin=0.2]       fastest allowed shrink is dt*qmin
 * @param {number} [opts.qmax=10]        fastest allowed growth is dt*qmax
 * @param {number} [opts.qsteadyMin=1]   inside [min,max] the step is left alone
 * @param {number} [opts.qsteadyMax=1.2]
 * @param {number} [opts.qoldinit=1e-4]
 */
export class PIController {
  constructor(opts) {
    const k = opts.order;
    this.beta1 = opts.beta1 ?? 7 / (10 * k);
    this.beta2 = opts.beta2 ?? 2 / (5 * k);
    this.gamma = opts.gamma ?? 0.9;
    this.qmin = opts.qmin ?? 0.2;
    this.qmax = opts.qmax ?? 10;
    this.qsteadyMin = opts.qsteadyMin ?? 1;
    this.qsteadyMax = opts.qsteadyMax ?? 1.2;
    this.qoldinit = opts.qoldinit ?? 1e-4;
    this.errold = this.qoldinit;
    this.q11 = 1;
  }

  /** Order changed under us (the BDF methods do this); refit the exponents. */
  setOrder(k) {
    this.beta1 = 7 / (10 * k);
    this.beta2 = 2 / (5 * k);
  }

  /**
   * q, the factor the step is *divided* by: dtnew = dt / q.
   * @param {number} EEst  the scaled error estimate; <= 1 is an accepted step
   */
  q(EEst) {
    if (EEst === 0) return 1 / this.qmax;
    this.q11 = EEst ** this.beta1;
    let q = this.q11 / this.errold ** this.beta2;
    q /= this.gamma;
    return Math.min(1 / this.qmin, Math.max(1 / this.qmax, q));
  }

  /** dtnew after an accepted step, and the state update that goes with it. */
  accept(EEst, dt) {
    let q = this.q(EEst);
    if (q >= this.qsteadyMin && q <= this.qsteadyMax) q = 1;
    this.errold = Math.max(EEst, this.qoldinit);
    return dt / q;
  }

  /**
   * dtnew after a rejected step. The proportional part only: the integral term
   * remembers accepted steps, and a rejected one says nothing about the trend.
   *
   * EEst has to be passed in. Reading the q11 left over from the last accepted
   * step instead -- which is what this did at first, and what it looks like
   * OrdinaryDiffEq does until you notice it recomputes the controller on every
   * step, accepted or not -- makes the shrink factor a number about a step
   * that already succeeded. It is then always close to 1, the step comes down
   * by a tenth at a time, and a solver meeting a sharp transition takes tens
   * of thousands of rejections to get through it instead of five.
   */
  reject(EEst, dt) {
    this.q11 = EEst ** this.beta1;
    return dt / Math.min(1 / this.qmin, this.q11 / this.gamma);
  }

  reset() {
    this.errold = this.qoldinit;
    this.q11 = 1;
  }
}

/**
 * Hairer's starting step (Solving ODEs I, II.4), which is what SciML uses.
 *
 * Two explicit Euler probes: the first sizes h from ‖u₀‖/‖f₀‖, the second
 * refines it from the observed second derivative. Cheap -- two extra f calls --
 * and much better than any fixed guess, which on a stiff problem is either
 * thrown away in a dozen rejections or starts so small the first decade of the
 * solution is wasted.
 *
 * @returns {number} a signed step, in the direction of tdir
 */
export function initialStep(f, t0, u0, f0, tdir, order, reltol, abstol, dtmax, work) {
  const n = u0.length;
  const { u1, f1, w } = work;
  const scalarAtol = typeof abstol === 'number';
  for (let i = 0; i < n; i++) w[i] = (scalarAtol ? abstol : abstol[i]) + reltol * Math.abs(u0[i]);

  let d0 = 0;
  let d1 = 0;
  for (let i = 0; i < n; i++) {
    const a = u0[i] / w[i];
    const b = f0[i] / w[i];
    d0 += a * a;
    d1 += b * b;
  }
  d0 = Math.sqrt(d0 / n);
  d1 = Math.sqrt(d1 / n);

  let h0 = (d0 < 1e-5 || d1 < 1e-5) ? 1e-6 : 0.01 * (d0 / d1);
  h0 = Math.min(h0, Math.abs(dtmax));

  for (let i = 0; i < n; i++) u1[i] = u0[i] + tdir * h0 * f0[i];
  f(t0 + tdir * h0, u1, f1);

  let d2 = 0;
  for (let i = 0; i < n; i++) {
    const a = (f1[i] - f0[i]) / w[i];
    d2 += a * a;
  }
  d2 = Math.sqrt(d2 / n) / h0;

  const dmax = Math.max(d1, d2);
  const h1 = dmax <= 1e-15
    ? Math.max(1e-6, h0 * 1e-3)
    : (0.01 / dmax) ** (1 / (order + 1));

  const h = Math.min(100 * h0, h1, Math.abs(dtmax));
  return tdir * h;
}
