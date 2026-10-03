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
 * @param {number} [opts.qmaxFirstStep]  the growth allowed after the first
 *        accepted step instead of qmax; unset, qmax applies there too
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
    // OrdinaryDiffEq's qmax_first_step (10000 by default there, after CVODE):
    // the starting step is an estimate, so the first accepted one may be
    // followed by a much longer one. Only the methods ported with it set it;
    // the older ports keep qmax throughout, as they were checked with.
    this.qmaxFirstStep = opts.qmaxFirstStep ?? 0;
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
  q(EEst, first = false) {
    const qmax = first && this.qmaxFirstStep > 0 ? this.qmaxFirstStep : this.qmax;
    if (EEst === 0) return 1 / qmax;
    this.q11 = EEst ** this.beta1;
    let q = this.q11 / this.errold ** this.beta2;
    q /= this.gamma;
    return Math.min(1 / this.qmin, Math.max(1 / qmax, q));
  }

  /**
   * dtnew after an accepted step, and the state update that goes with it.
   * `first` says it is the run's first accepted step, for qmaxFirstStep.
   */
  accept(EEst, dt, first = false) {
    let q = this.q(EEst, first);
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

const F64 = new Float64Array(1);
const I64 = new BigInt64Array(F64.buffer);

/** The next double above x (Julia's nextfloat), for finite x >= 0. */
function nextUp(x) {
  if (x === 0) return Number.MIN_VALUE;
  F64[0] = x;
  I64[0] += 1n;
  return F64[0];
}

/** Julia's eps(x): the gap from |x| to the next double, MIN_VALUE at zero. */
export function epsOf(x) {
  const a = Math.abs(x);
  if (a === 0) return Number.MIN_VALUE;
  return nextUp(a) - a;
}

/**
 * The starting step exactly as OrdinaryDiffEq's ode_determine_initdt takes it
 * (OrdinaryDiffEqCore/src/initdt.jl, `_ode_initdt_iip`), for the methods
 * ported with it.
 *
 * The same two Euler probes as `initialStep` above, but where Hairer's book
 * refines h₁ = (0.01/max(d₁, d₂))^(1/(p+1)), OrdinaryDiffEq takes the p-th
 * root -- of the method's order, not one more -- and clamps the first probe
 * to dtmax. It also stops at the first probe when f has not changed at all
 * ("a constant zone"), answering 100 times it, and falls back to a default
 * when the first probe came out below machine epsilon. `initialStep` is kept
 * as it was for the methods checked with it.
 *
 * `norm` is the integrator's: the root mean square unless the run uses the
 * maximum.
 *
 * @returns {number} a signed step, in the direction of tdir
 */
export function initialStepSciML(f, t0, u0, f0, tdir, order, reltol, abstol, dtmax, work, opts = {}) {
  const n = u0.length;
  const { u1, f1, w } = work;
  const norm = opts.norm === 'max'
    ? (fill) => { let m = 0; for (let i = 0; i < n; i++) { const v = Math.abs(fill(i)); if (v > m || v !== v) m = v; } return m; }
    : (fill) => { let s = 0; for (let i = 0; i < n; i++) { const v = fill(i); s += v * v; } return Math.sqrt(s / n); };
  const dtminUser = opts.dtmin > 0 ? opts.dtmin : 0;
  const dtmin = nextUp(Math.max(dtminUser, epsOf(t0)));
  const smalldt = Math.max(dtmin, 1e-6);
  const dtmaxAbs = Math.abs(dtmax);

  const scalarAtol = typeof abstol === 'number';
  for (let i = 0; i < n; i++) w[i] = (scalarAtol ? abstol : abstol[i]) + Math.abs(u0[i]) * reltol;

  const d0 = norm((i) => u0[i] / w[i]);
  const d1 = norm((i) => f0[i] / w[i]);
  if (Number.isNaN(d1)) return tdir * dtmin;

  let dt0 = (d0 < 1e-5 || d1 < 1e-5) ? smalldt : (d0 / d1) / 100;
  dt0 = Math.min(dt0, dtmaxAbs);
  const tinyFirst = dt0 < 10 * Number.EPSILON;
  const fallback = (dt) => (tinyFirst && (!Number.isFinite(dt) || Math.abs(dt) < 10 * Number.EPSILON)
    ? tdir * Math.max(smalldt, dtmin)
    : dt);

  for (let i = 0; i < n; i++) u1[i] = u0[i] + tdir * dt0 * f0[i];
  f(t0 + tdir * dt0, u1, f1);

  let same = n > 0;
  for (let i = 0; i < n && same; i++) if (f0[i] !== f1[i]) same = false;
  if (same) return fallback(tdir * Math.max(dtmin, 100 * dt0));

  const d2 = norm((i) => (f1[i] - f0[i]) / w[i]) / dt0;
  const m = Math.max(d1, d2);
  const dt1 = m <= 1e-15
    ? Math.max(1e-6, dt0 * 1e-3)
    : 10 ** (-(2 + Math.log10(m)) / order);
  return fallback(tdir * Math.max(dtmin, Math.min(100 * dt0, dt1, dtmaxAbs)));
}
