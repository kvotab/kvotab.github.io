/* ==========================================================================
   ode_julia / solvers / vern7

   Vern7: Verner's "most efficient" explicit Runge-Kutta pair of order 7(6)
   (OrdinaryDiffEqVerner), the non-stiff method DifferentialEquations.jl's
   default algorithm takes when the relative tolerance is below 1e-6.

   Ten stages a step and not first-same-as-last, so ten evaluations of f --
   the first of them is f at the step's start, which the integrator already
   holds, and is taken from there. Its interpolant is seventh order and needs
   six stages more; they are worked out only when a point inside the step is
   actually asked for, once per step ("lazy", OrdinaryDiffEq's default).

   Inside the automatic switch it estimates the largest eigenvalue from its
   last two stages as Tsit5 does (see explicitStiffness in ./tsit5.js), with
   OrdinaryDiffEq's choice of points: the difference of stages 10 and 9 over
   the difference of the solution and stage 10's point.
   ========================================================================== */

import { Vern7Tableau } from './vern7-tableau.js';
import { explicitStiffness } from './tsit5.js';

class Vern7Cache {
  constructor(n, tab) {
    this.n = n;
    // Never reads J or W (see the integrator's ageing of the Jacobian).
    this.explicit = true;
    this.tab = tab;
    this.order = tab.order;
    this.errorOrder = tab.errorOrder;
    this.stabilitySize = tab.stabilitySize;
    this.hasFsalLast = false;
    this.dtpropose = null;
    // Stages 1..10 of the step, and 11..16 for the interpolant.
    this.k = Array.from({ length: 16 }, () => new Float64Array(n));
    this.tmp = new Float64Array(n);
    this.utilde = new Float64Array(n);
    this.extraValid = false;
    // Each row's nonzero coefficients, in the source's order, so a stage sums
    // exactly the terms OrdinaryDiffEq writes out and no zeros.
    this.rows = tab.a.map((row) => row.map((v, j) => [j, v]).filter(([, v]) => v !== 0));
    this.extraRows = tab.extraA.map((row) => row.map((v, j) => [j, v]).filter(([, v]) => v !== 0));
    this.bTerms = tab.b.map((v, j) => [j, v]).filter(([, v]) => v !== 0);
    this.eTerms = tab.btilde.map((v, j) => [j, v]).filter(([, v]) => v !== 0);
  }

  /** out = uprev + dt·Σ coefficient·k over `terms`. */
  combine(uprev, dt, terms, out) {
    const { n, k } = this;
    const [j0, v0] = terms[0];
    const k0 = k[j0];
    for (let i = 0; i < n; i++) {
      let acc = v0 * k0[i];
      for (let m = 1; m < terms.length; m++) {
        const [j, v] = terms[m];
        acc += v * k[j][i];
      }
      out[i] = uprev[i] + dt * acc;
    }
    return out;
  }

  step(integ) {
    const { n, tab, k, tmp, rows } = this;
    const { t, dt, uprev, u } = integ;
    const f = integ.f;
    const c = tab.c;

    k[0].set(integ.fsalfirst);
    for (let s = 1; s < 10; s++) {
      this.combine(uprev, dt, rows[s], tmp);
      f(t + c[s] * dt, tmp, k[s]);
    }
    // tmp now holds stage 10's point, which the stiffness estimate reads.
    this.combine(uprev, dt, this.bTerms, u);
    this.extraValid = false;

    if (integ.isComposite) {
      integ.eigenEst = explicitStiffness(k[8], k[9], tmp, u, n, integ.stillIsStiff);
    }

    const utilde = this.utilde;
    const e = this.eTerms;
    for (let i = 0; i < n; i++) {
      let acc = e[0][1] * k[e[0][0]][i];
      for (let m = 1; m < e.length; m++) acc += e[m][1] * k[e[m][0]][i];
      utilde[i] = dt * acc;
    }
    integ.EEst = integ.errorNorm(utilde);
    return true;
  }

  /** Stages 11..16, for the interpolant: six more evaluations, once a step. */
  extraStages(integ) {
    const { tab, k, tmp } = this;
    const { t, dt, uprev } = integ;
    for (let m = 0; m < 6; m++) {
      this.combine(uprev, dt, this.extraRows[m], tmp);
      integ.f(t + tab.extraC[m] * dt, tmp, k[10 + m]);
    }
    this.extraValid = true;
  }

  /**
   * u(t + θ·dt) by Verner's seventh-order interpolant:
   *   u = uprev + dt·Σⱼ bⱼ(θ)·kⱼ over stages 1, 4..9 and 11..16,
   *   b₁(θ) = θ·p₁(θ), the others θ²·pⱼ(θ).
   */
  interpolate(integ, theta, out) {
    // The end of the step is the step's own solution: OrdinaryDiffEq saves u
    // itself at a requested time the step lands on, and Vern7 would otherwise
    // work out six stages to reproduce it.
    if (theta === 1) { out.set(integ.u); return out; }
    if (!this.extraValid) this.extraStages(integ);
    const { n, k, tab } = this;
    const { interp, interpStages } = tab;
    const m = interpStages.length;
    const w = this.w || (this.w = new Float64Array(m));
    const th2 = theta * theta;
    for (let q = 0; q < m; q++) {
      const r = interp[q];
      let p = r[r.length - 1];
      for (let d = r.length - 2; d >= 0; d--) p = r[d] + theta * p;
      w[q] = (q === 0 ? theta : th2) * p;
    }
    const { uprev } = integ;
    const dt = integ.dt;
    const k0 = k[interpStages[0] - 1];
    for (let i = 0; i < n; i++) {
      let acc = k0[i] * w[0];
      for (let q = 1; q < m; q++) acc += k[interpStages[q] - 1][i] * w[q];
      out[i] = uprev[i] + dt * acc;
    }
    return out;
  }
}

/**
 * Vern7: explicit, order 7(6), ten stages a step and six more for a point
 * inside one. PI step control with OrdinaryDiffEq's defaults for order 7:
 * β₁ = 1/10, β₂ = 2/35.
 */
export function Vern7(options = {}) {
  return {
    name: 'Vern7',
    order: 7,
    stabilitySize: Vern7Tableau.stabilitySize,
    initdt: 'sciml',
    build: (n) => new Vern7Cache(n, Vern7Tableau),
    controller: {
      beta1: 7 / 70, beta2: 2 / 35, gamma: 0.9, qmin: 0.2, qmax: 10,
      qsteadyMin: 1, qsteadyMax: 1, qoldinit: 1e-4, qmaxFirstStep: 10000,
      ...(options.controller || {}),
    },
  };
}
