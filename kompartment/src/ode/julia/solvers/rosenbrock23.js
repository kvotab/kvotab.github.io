/* ==========================================================================
   ode_julia / solvers / rosenbrock23

   Rosenbrock23: the Rosenbrock (2,3) W-method of Shampine and Reichelt's
   MATLAB ode23s, as OrdinaryDiffEqRosenbrock implements it -- the stiff
   method DifferentialEquations.jl's default algorithm switches to for a
   small system (up to 50 states) at a relative tolerance of 1e-6 or above.

   With d = 1/(2 + √2) and W = I − h·d·J,

       W k₁ = f(t, u) + h·d·∂f/∂t
       W k₂ = f(t + h/2, u + h/2·k₁) − k₁,                then k₂ += k₁
       u₁   = u + h·k₂
       W k₃ = f(t + h, u₁) − (6 + √2)·(k₂ − f₁) − 2·(k₁ − f₀) + h·∂f/∂t

   and the step's error is h/6·(k₁ − 2k₂ + k₃): second order, judged by a
   third-order estimate. f at the new solution is the next step's f₀.

   It is the same method as this repository's own `ros23` (Kompartment's
   src/ode/solvers/rosenbrock23.js) and a different implementation of it:
   OrdinaryDiffEq's step controller, error weights and norm, starting step
   and interpolant. W is formed from a fresh Jacobian on every step, as
   OrdinaryDiffEq does for this method (its max_jac_age is 1 here, and inside
   a composite algorithm it always re-forms J).

   W is held here as I/(h·d) − J, the form the Rosenbrock methods in this
   package use; OrdinaryDiffEq holds its negative and multiplies each solve by
   −1/(h·d), so here each solve is multiplied by +1/(h·d).
   ========================================================================== */

import { rosenbrockTimeDerivative } from './rosenbrock.js';

const D = 1 / (2 + Math.sqrt(2));
const C32 = 6 + Math.sqrt(2);

class Rosenbrock23Cache {
  constructor(n) {
    this.n = n;
    this.order = 2;
    // OrdinaryDiffEq's alg_adaptive_order(Rosenbrock23) is 3; the PI
    // controller's gains are set from the method's order, 2, below.
    this.errorOrder = 3;
    this.hasFsalLast = true;
    this.refreshFsalOnClamp = true;
    this.dtpropose = null;
    this.k1 = new Float64Array(n);
    this.k2 = new Float64Array(n);
    this.k3 = new Float64Array(n);
    this.f1 = new Float64Array(n);
    this.dT = new Float64Array(n);
    this.dTwork = new Float64Array(n);
    this.rhs = new Float64Array(n);
    this.err = new Float64Array(n);
  }

  step(integ) {
    const { n, k1, k2, k3, f1, dT, rhs } = this;
    const { t, dt, uprev, u } = integ;
    const dtgamma = dt * D;
    const inv = 1 / dtgamma;
    const dto2 = dt / 2;
    const dto6 = dt / 6;
    const f0 = integ.fsalfirst;

    // A fresh J on every step, W = I/(h·d) − J.
    if (!integ.formW(dtgamma, true, true)) return false;
    rosenbrockTimeDerivative(integ, t, uprev, f0, dT, this.dTwork);

    for (let i = 0; i < n; i++) rhs[i] = f0[i] + dtgamma * dT[i];
    integ.solveW(rhs);
    for (let i = 0; i < n; i++) k1[i] = rhs[i] * inv;

    for (let i = 0; i < n; i++) u[i] = uprev[i] + dto2 * k1[i];
    integ.f(t + dto2, u, f1);

    for (let i = 0; i < n; i++) rhs[i] = f1[i] - k1[i];
    integ.solveW(rhs);
    for (let i = 0; i < n; i++) k2[i] = rhs[i] * inv + k1[i];

    for (let i = 0; i < n; i++) u[i] = uprev[i] + dt * k2[i];

    const f2 = integ.fsallast;
    integ.f(t + dt, u, f2);
    for (let i = 0; i < n; i++) {
      rhs[i] = f2[i] - C32 * (k2[i] - f1[i]) - 2 * (k1[i] - f0[i]) + dt * dT[i];
    }
    integ.solveW(rhs);
    for (let i = 0; i < n; i++) k3[i] = rhs[i] * inv;

    const err = this.err;
    for (let i = 0; i < n; i++) err[i] = dto6 * (k1[i] - 2 * k2[i] + k3[i]);
    integ.EEst = integ.errorNorm(err);
    return true;
  }

  /**
   * u(t + θ·dt) by the method's own second-order interpolant (the MATLAB
   * suite's): uprev + dt·(c₁k₁ + c₂k₂), c₁ = θ(1−θ)/(1−2d), c₂ = θ(θ−2d)/(1−2d).
   */
  interpolate(integ, theta, out) {
    // The end of the step is the step's own solution: OrdinaryDiffEq saves u
    // itself at a requested time the step lands on.
    if (theta === 1) { out.set(integ.u); return out; }
    const { n, k1, k2 } = this;
    const c1 = theta * (1 - theta) / (1 - 2 * D);
    const c2 = theta * (theta - 2 * D) / (1 - 2 * D);
    const { uprev } = integ;
    const dt = integ.dt;
    for (let i = 0; i < n; i++) out[i] = uprev[i] + dt * (c1 * k1[i] + c2 * k2[i]);
    return out;
  }
}

/**
 * Rosenbrock23: linearly implicit, order 2 with a third-order error
 * estimate, L-stable. PI step control with OrdinaryDiffEq's defaults for
 * order 2: β₁ = 7/20, β₂ = 1/5, the step held where it would change by less
 * than a fifth (as for every adaptive implicit method there).
 */
export function Rosenbrock23(options = {}) {
  return {
    name: 'Rosenbrock23',
    order: 2,
    initdt: 'sciml',
    build: (n) => new Rosenbrock23Cache(n),
    controller: {
      beta1: 7 / 20, beta2: 1 / 5, gamma: 0.9, qmin: 0.2, qmax: 10,
      qsteadyMin: 1, qsteadyMax: 1.2, qoldinit: 1e-4, qmaxFirstStep: 10000,
      ...(options.controller || {}),
    },
  };
}
