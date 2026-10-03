/* ==========================================================================
   ode_julia / solvers / tsit5

   Tsit5: Tsitouras's explicit Runge-Kutta pair of order 5(4), the
   non-stiff method DifferentialEquations.jl recommends first and the one its
   default algorithm starts on (OrdinaryDiffEqTsit5).

   Seven stages, the last of which is f at the new solution, so each step
   costs six evaluations of f: that last stage is the next step's first
   ("first same as last"). The error estimate is the embedded fourth-order
   solution's difference, and the free interpolant is fourth order, which is
   what saved rows and event location are read off.

   An explicit method has no use for a Jacobian and asks for none, so the
   integrator never forms one while it runs. On a stiff problem it is the
   wrong method -- its step is held to the edge of its stability region, a
   little over 3.5/|λ| -- and that is exactly what the automatic switch in
   ./default.js watches for: when it runs inside the switch, each step also
   estimates the largest eigenvalue from its last two stages,

       |λ| ≈ ‖(k₇ − k₆) / (g₇ − g₆)‖∞,        Hairer & Wanner II, p. 22

   with g₆ and g₇ the points those two stages were evaluated at (the second
   being the new solution), and leaves it in integ.eigenEst.
   ========================================================================== */

import { Tsit5Tableau } from './tsit5-tableau.js';

/**
 * The spectral-radius estimate of OrdinaryDiffEq's explicit methods from two
 * stages at the same time: max over i of |(kB − kA)ᵢ / (gB − gA)ᵢ|.
 *
 * A NaN makes the whole estimate NaN, as Julia's norm(·, Inf) does -- the
 * switch reads a NaN as stiff. One case is set apart, and it is a deliberate
 * difference from OrdinaryDiffEq: a component that has not moved at all
 * between the two stages, both differences exactly zero. There 0/0 is NaN in
 * Julia, so a single state at rest -- an empty compartment, a constant -- is
 * enough for every step to be judged stiff: Lorenz with one idle extra state
 * switches to Rosenbrock23 and back twenty-three times over [0, 20] (measured,
 * OrdinaryDiffEq 7.8.1), where without it it never leaves Tsit5. A component
 * at rest says nothing about stiffness either way, and here it is passed
 * over; `stillIsStiff` restores Julia's reading.
 *
 * @returns {number}
 */
export function explicitStiffness(kA, kB, gA, gB, n, stillIsStiff = false) {
  let m = 0;
  for (let i = 0; i < n; i++) {
    const num = kB[i] - kA[i];
    const den = gB[i] - gA[i];
    if (num === 0 && den === 0 && !stillIsStiff) continue;
    const r = Math.abs(num / den);
    if (r > m) m = r;
    else if (r !== r) return NaN;
  }
  return m;
}

class Tsit5Cache {
  constructor(n, tab) {
    this.n = n;
    // Never reads J or W (see the integrator's ageing of the Jacobian).
    this.explicit = true;
    this.tab = tab;
    this.order = tab.order;
    this.errorOrder = tab.errorOrder;
    this.stabilitySize = tab.stabilitySize;
    this.hasFsalLast = true;
    // A clamped solution is not the point k₇ was evaluated at; f is taken
    // again there, as OrdinaryDiffEq does after a callback changes u.
    this.refreshFsalOnClamp = true;
    this.dtpropose = null;
    this.k = Array.from({ length: tab.stages }, () => new Float64Array(n));
    this.tmp = new Float64Array(n);
    this.utilde = new Float64Array(n);
  }

  step(integ) {
    const { n, tab, k, tmp } = this;
    const { a, c, btilde } = tab;
    const { t, dt, uprev, u } = integ;
    const f = integ.f;

    k[0].set(integ.fsalfirst);
    // Stages 2..6 at their own times; stage 6 is at t + dt, and the point it
    // is evaluated at (g₆) stays in tmp for the stiffness estimate.
    const a2 = dt * a[1][0];
    for (let i = 0; i < n; i++) tmp[i] = uprev[i] + a2 * k[0][i];
    f(t + c[1] * dt, tmp, k[1]);
    for (let s = 2; s < 6; s++) {
      const row = a[s];
      for (let i = 0; i < n; i++) {
        let acc = row[0] * k[0][i];
        for (let j = 1; j < s; j++) acc += row[j] * k[j][i];
        tmp[i] = uprev[i] + dt * acc;
      }
      f(t + c[s] * dt, tmp, k[s]);
    }
    // The solution is stage 7's point, and k₇ = f(u) is the next step's k₁.
    const row = a[6];
    for (let i = 0; i < n; i++) {
      let acc = row[0] * k[0][i];
      for (let j = 1; j < 6; j++) acc += row[j] * k[j][i];
      u[i] = uprev[i] + dt * acc;
    }
    f(t + dt, u, k[6]);
    integ.fsallast.set(k[6]);

    if (integ.isComposite) {
      integ.eigenEst = explicitStiffness(k[5], k[6], tmp, u, n, integ.stillIsStiff);
    }

    const utilde = this.utilde;
    for (let i = 0; i < n; i++) {
      let acc = btilde[0] * k[0][i];
      for (let j = 1; j < 7; j++) acc += btilde[j] * k[j][i];
      utilde[i] = dt * acc;
    }
    integ.EEst = integ.errorNorm(utilde);
    return true;
  }

  /**
   * u(t + θ·dt) by Tsitouras's free interpolant, fourth order:
   *   u = uprev + dt·Σⱼ bⱼ(θ)·kⱼ,   b₁(θ) = θ·p₁(θ),  bⱼ(θ) = θ²·pⱼ(θ)
   */
  interpolate(integ, theta, out) {
    // The end of the step is the step's own solution: OrdinaryDiffEq saves u
    // itself at a requested time the step lands on.
    if (theta === 1) { out.set(integ.u); return out; }
    const { n, k, tab } = this;
    const r = tab.interp;
    const th2 = theta * theta;
    const w = this.w || (this.w = new Float64Array(7));
    const r0 = r[0];
    w[0] = theta * (r0[0] + theta * (r0[1] + theta * (r0[2] + theta * r0[3])));
    for (let j = 1; j < 7; j++) {
      const rj = r[j];
      w[j] = th2 * (rj[0] + theta * (rj[1] + theta * rj[2]));
    }
    const { uprev } = integ;
    const dt = integ.dt;
    for (let i = 0; i < n; i++) {
      let acc = k[0][i] * w[0];
      for (let j = 1; j < 7; j++) acc += k[j][i] * w[j];
      out[i] = uprev[i] + dt * acc;
    }
    return out;
  }
}

/**
 * Tsit5: explicit, order 5(4), seven stages (six evaluations a step).
 *
 * The step controller is OrdinaryDiffEq's PI controller with its defaults for
 * a fifth-order method: β₁ = 7/50, β₂ = 2/25, a safety factor of 9/10, a step
 * at most ten times the last (ten thousand after the first accepted one) and
 * at least a fifth of it.
 */
export function Tsit5(options = {}) {
  return {
    name: 'Tsit5',
    order: 5,
    stabilitySize: Tsit5Tableau.stabilitySize,
    initdt: 'sciml',
    build: (n) => new Tsit5Cache(n, Tsit5Tableau),
    controller: {
      beta1: 7 / 50, beta2: 2 / 25, gamma: 0.9, qmin: 0.2, qmax: 10,
      qsteadyMin: 1, qsteadyMax: 1, qoldinit: 1e-4, qmaxFirstStep: 10000,
      ...(options.controller || {}),
    },
  };
}
