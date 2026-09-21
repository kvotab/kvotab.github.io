/* ==========================================================================
   ode_julia / solvers / rosenbrock

   Rosenbrock-Wanner methods, and Rodas5P in particular.

   A Rosenbrock method is what you get by taking a diagonally implicit
   Runge-Kutta method and doing exactly one Newton iteration per stage, with
   the Jacobian written into the method rather than iterated to convergence.
   Each stage is then a single linear solve:

       (I/(γh) − J) kᵢ = f(uᵢ) + h·dᵢ·∂f/∂t + Σⱼ (Cᵢⱼ/h)·kⱼ
       uᵢ = uprev + Σⱼ Aᵢⱼ·kⱼ

   The consequences are worth stating, because they decide when to reach for
   one. There is no nonlinear iteration, so there is nothing to fail to
   converge and no iteration count to tune -- on a problem where Newton
   struggles, that is a large practical advantage. Against it, J is part of the
   method's definition rather than a convenience, so it must be re-evaluated
   and W re-factorised at every single step; a BDF method on a smooth stretch
   will reuse one factorisation for twenty steps and be far cheaper.

   So: Rodas5P for hard, moderately sized problems, and where an exact
   Jacobian is available cheaply. FBDF for large ones and long smooth runs.

   ∂f/∂t is needed because these methods are written for non-autonomous
   problems. It is differenced -- one extra evaluation per step -- and is
   exactly zero for an autonomous f, where the term costs a multiply.
   ========================================================================== */

import { Rodas5PTableau } from './rodas5p-tableau.js';

class RosenbrockCache {
  constructor(n, tab, integ) {
    this.tab = tab;
    this.n = n;
    this.order = tab.order;
    this.errorOrder = tab.errorOrder;
    this.interpOrder = tab.interpOrder;
    this.hasFsalLast = false;
    this.dtpropose = null;

    this.k = Array.from({ length: tab.stages }, () => new Float64Array(n));
    this.dT = new Float64Array(n);
    this.du = new Float64Array(n);
    this.ustage = new Float64Array(n);
    this.rhs = new Float64Array(n);
    this.err = new Float64Array(n);
    this.utmp = new Float64Array(n);
    this.dTwork = new Float64Array(n);
    // The dense-output vectors, as many as H has rows.
    this.dense = Array.from({ length: tab.H.length }, () => new Float64Array(n));
    this.denseValid = false;
  }

  /**
   * ∂f/∂t at (t, u): the caller's, if they have one, else differenced.
   *
   * Differencing costs one evaluation and is what Julia does.
   *
   * The difference step is scaled by max(|t|, |h|), and the second half of
   * that is not decoration. Scaling by |t| alone -- the obvious choice, and
   * the one this had at first -- collapses to nothing as t approaches zero,
   * and the quotient is then pure rounding noise. The cost was not a wrong
   * answer anywhere obvious: it was Rodas5P quietly converging at order three
   * instead of five, which no accuracy check at a working tolerance would ever
   * have caught. Measured on a manufactured problem with a known solution:
   * order 3.02 with the old rule, 5.00 with this one, and 5.00 with an exact
   * df/dt, which is the confirmation that this term and nothing else was the
   * limit.
   */
  timeDerivative(integ, t, u, fu, out) {
    const n = this.n;
    if (integ.prob.tgrad) { integ.prob.tgrad(t, u, out); return out; }
    const scale = Math.max(Math.abs(t), Math.abs(integ.dt));
    if (integ.opts.central) {
      const dtd = Math.cbrt(Number.EPSILON) * scale;
      integ.f(t + dtd, u, out);
      integ.f(t - dtd, u, this.dTwork);
      const inv = 1 / (2 * dtd);
      for (let i = 0; i < n; i++) out[i] = (out[i] - this.dTwork[i]) * inv;
      return out;
    }
    const dtd = Math.sqrt(Number.EPSILON) * scale;
    integ.f(t + dtd, u, out);
    const inv = 1 / dtd;
    for (let i = 0; i < n; i++) out[i] = (out[i] - fu[i]) * inv;
    return out;
  }

  step(integ) {
    const { tab, n, k, du, dT, ustage, rhs } = this;
    const dt = integ.dt;
    const { uprev, u, t } = integ;
    const gammaDt = dt * tab.gamma;
    const s = tab.stages;

    // J is part of the method, not an optimisation: a stale one changes the
    // order. Forced fresh every step, which is what a Rosenbrock method costs.
    if (!integ.formW(gammaDt, true, true)) return false;

    this.timeDerivative(integ, t, uprev, integ.fsalfirst, dT);

    // Stage 1 uses f(t, uprev), which the integrator already has.
    du.set(integ.fsalfirst);
    const d0 = dt * tab.d[0];
    for (let i = 0; i < n; i++) rhs[i] = du[i] + d0 * dT[i];
    // Julia solves W_julia \ (−rhs) with W_julia = J − I/(γh); this W is the
    // negative of that, so the same step is a plain solve of +rhs.
    integ.solveW(rhs);
    k[0].set(rhs);

    for (let stage = 1; stage < s; stage++) {
      const A = tab.a[stage];
      for (let i = 0; i < n; i++) {
        let v = uprev[i];
        for (let j = 0; j < stage; j++) v += A[j] * k[j][i];
        ustage[i] = v;
      }
      integ.f(t + tab.c[stage] * dt, ustage, du);

      const C = tab.C[stage];
      const ds = dt * tab.d[stage];
      const invdt = 1 / dt;
      for (let i = 0; i < n; i++) {
        let acc = 0;
        for (let j = 0; j < stage; j++) acc += C[j] * k[j][i];
        rhs[i] = du[i] + ds * dT[i] + acc * invdt;
      }
      integ.solveW(rhs);
      k[stage].set(rhs);
    }

    for (let i = 0; i < n; i++) {
      let v = uprev[i];
      for (let j = 0; j < s; j++) {
        const bj = tab.b[j];
        if (bj !== 0) v += bj * k[j][i];
      }
      u[i] = v;
    }

    const err = this.err;
    for (let i = 0; i < n; i++) {
      let v = 0;
      for (let j = 0; j < s; j++) {
        const bt = tab.btilde[j];
        if (bt !== 0) v += bt * k[j][i];
      }
      err[i] = v;
    }
    integ.EEst = integ.errorNorm(err);
    this.denseValid = false;
    return true;
  }

  accepted(integ) {
    // The interpolant's three vectors, folded from the stage increments. Built
    // lazily: most steps are never interpolated inside.
    this.denseValid = false;
  }

  buildDense() {
    const { tab, n, k, dense } = this;
    for (let j = 0; j < dense.length; j++) {
      const H = tab.H[j];
      const out = dense[j];
      for (let i = 0; i < n; i++) {
        let v = 0;
        for (let m = 0; m < tab.stages; m++) {
          const h = H[m];
          if (h !== 0) v += h * k[m][i];
        }
        out[i] = v;
      }
    }
    this.denseValid = true;
  }

  /**
   * u(t + θ·h), to the method's own order rather than by Hermite.
   *
   *   u(θ) = (1−θ)·u₀ + θ·(u₁ + (1−θ)·(κ₁ + θ·(κ₂ + θ·κ₃)))
   *
   * with κⱼ = Σᵢ H[j][i]·kᵢ. This is what makes saveat and event location as
   * accurate as the step itself; the fallback Hermite through the two ends is
   * third order, which on a stiff transient is visibly worse.
   */
  interpolate(integ, theta, out) {
    if (!this.denseValid) this.buildDense();
    const { n, dense } = this;
    const { uprev, u } = integ;
    const t1 = 1 - theta;
    const m = dense.length;
    for (let i = 0; i < n; i++) {
      let acc = dense[m - 1][i];
      for (let j = m - 2; j >= 0; j--) acc = dense[j][i] + theta * acc;
      out[i] = t1 * uprev[i] + theta * (u[i] + t1 * acc);
    }
    return out;
  }
}

/** Rodas5P: 5th order, L-stable, stiffly accurate, 8 stages. */
export function Rodas5P(options = {}) {
  return {
    name: 'Rodas5P',
    order: Rodas5PTableau.order,
    build: (n, integ) => new RosenbrockCache(n, Rodas5PTableau, integ),
    controller: { qmax: 10, qsteadyMin: 1, qsteadyMax: 1.2, ...(options.controller || {}) },
  };
}

/** The generic builder, for adding another Rosenbrock tableau. */
export function rosenbrockAlgorithm(tab, options = {}) {
  return {
    name: tab.name,
    order: tab.order,
    build: (n, integ) => new RosenbrockCache(n, tab, integ),
    controller: { ...(options.controller || {}) },
  };
}
