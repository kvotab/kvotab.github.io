/* ==========================================================================
   ode_julia / solvers / radau

   RadauIIA5: the three-stage Radau IIA collocation method, order 5, L-stable,
   stiffly accurate. Hairer and Wanner's RADAU5, as OrdinaryDiffEqFIRK ports it.

   A fully implicit Runge-Kutta method couples all its stages: the Newton
   system is 3n by 3n, which at face value costs 27 times a single n by n
   factorisation. Radau's saving grace, and the reason it is practical at all,
   is that the inverse of its Butcher matrix has one real eigenvalue and one
   complex conjugate pair. Changing to that eigenbasis -- the matrices T and
   T⁻¹ below -- splits the coupled system into

       (γ/h·I − J)·Δw₁       = r₁                     one real n by n solve
       ((α+iβ)/h·I − J)·Δw₂₃ = r₂ + i·r₃              one complex n by n solve

   which is about four times the work of one real factorisation rather than
   twenty-seven. That is why this file needs a complex LU and the others do
   not.

   What it is for. Radau is the most robust thing here on a genuinely nasty
   problem: it is the only method in the package with no order reduction to
   speak of on stiff problems, and it holds its accuracy where the Rosenbrock
   and BDF methods degrade. It costs three function evaluations per Newton
   iteration and two factorisations per Jacobian, so it is not the cheapest --
   reach for it when something else has struggled, or when the answer has to be
   right at a tight tolerance.

   LIMITATION. The complex half is always factorised densely, even when the
   real half is sparse: this package has no complex sparse LU. For a few
   hundred states that is unnoticeable; for a few thousand it is the wrong
   method here, and FBDF is the one to use.

   TOLERANCES. Radau works internally to transformed tolerances,
   rtol' = rtol^(2/3)/10 and atol' = rtol'·(atol/rtol), which is what Hairer's
   original does and what makes its error estimate comparable with the other
   methods'. Without it the method is systematically over-cautious.
   ========================================================================== */

import { ComplexDenseLU } from '../core/linalg.js';
import { RadauIIA5Tableau } from './radau-tableau.js';

class RadauCache {
  constructor(n, integ, opts) {
    this.n = n;
    this.tab = RadauIIA5Tableau;
    this.order = 5;
    this.errorOrder = 3;
    this.hasFsalLast = true;
    this.dtpropose = null;

    // Radau keeps OrdinaryDiffEq's 1/100: its error estimate is not a
    // difference of stages the way an ESDIRK's is, and the stiff set shows no
    // benefit from tightening it. See core/newton.js for why the others do not.
    this.kappa = opts.kappa ?? 0.01;
    this.maxIters = opts.maxIters ?? 10;
    this.fastConvergenceCutoff = opts.fastConvergenceCutoff ?? 0.2;
    this.smoothEst = opts.smoothEst !== false;

    this.z1 = new Float64Array(n);
    this.z2 = new Float64Array(n);
    this.z3 = new Float64Array(n);
    this.w1 = new Float64Array(n);
    this.w2 = new Float64Array(n);
    this.w3 = new Float64Array(n);
    this.ff1 = new Float64Array(n);
    this.ff2 = new Float64Array(n);
    this.ff3 = new Float64Array(n);
    this.rhs1 = new Float64Array(n);
    this.rhs2 = new Float64Array(n);
    this.rhs3 = new Float64Array(n);
    this.ustage = new Float64Array(n);
    this.utilde = new Float64Array(n);
    this.tmpvec = new Float64Array(n);

    // The complex half, always dense. Built once.
    this.clu = new ComplexDenseLU(n);
    this.cre = new Float64Array(n * n);
    this.cim = new Float64Array(n * n);

    // The last accepted step's collocation polynomial, as divided differences
    // of its stages (OrdinaryDiffEq's cont1..cont3): what the next step's
    // starting guess is extrapolated from.
    this.cont1 = new Float64Array(n);
    this.cont2 = new Float64Array(n);
    this.cont3 = new Float64Array(n);

    this.dtprev = 1;
    this.complexValid = false;
    this.complexDt = NaN;
    this.haveHistory = false;
    this.etaOld = 1;
    this.status = 'Convergence';
    this.iter = 0;
  }

  restart() {
    this.haveHistory = false;
    this.complexValid = false;
    this.etaOld = 1;
    this.dtprev = 1;
  }

  /**
   * The scaled norm Radau measures its iterate and its error in.
   *
   * `atol` may be a number or one value per component -- the latter both when
   * the caller gave an array and when the absolute tolerance is being let
   * follow the solution. Reading only its first element, which is what this
   * did at first, silently applies one species' tolerance to all of them.
   */
  scaledNorm(v, integ, atol, rtol) {
    const n = this.n;
    const { uprev, u } = integ;
    const scalar = typeof atol === 'number';
    let s = 0;
    for (let i = 0; i < n; i++) {
      const a = scalar ? atol : atol[i];
      const w = a + rtol * Math.max(Math.abs(uprev[i]), Math.abs(u[i]));
      const r = v[i] / w;
      s += r * r;
    }
    return Math.sqrt(s / n);
  }

  /** ((α+iβ)/h)·I − J, from whichever storage J is in. */
  formComplexW(integ, alphaDt, betaDt) {
    const n = this.n;
    const { cre, cim } = this;
    cre.fill(0);
    cim.fill(0);
    const J = integ.jacCache.J;
    if (integ.jacCache.sparse) {
      for (let j = 0; j < n; j++) {
        for (let k = J.colPtr[j]; k < J.colPtr[j + 1]; k++) cre[j * n + J.rowIdx[k]] = -J.values[k];
      }
    } else {
      for (let k = 0; k < n * n; k++) cre[k] = -J.data[k];
    }
    for (let j = 0; j < n; j++) {
      cre[j * n + j] += alphaDt;
      cim[j * n + j] += betaDt;
    }
    return this.clu.factor(cre, cim);
  }

  step(integ) {
    const { n, tab } = this;
    const dt = integ.dt;
    const { uprev, u, t } = integ;
    const { z1, z2, z3, w1, w2, w3, ff1, ff2, ff3, rhs1, rhs2, rhs3, ustage } = this;

    const reltol = integ.reltol;
    // Hairer's transformation; see the header. Applied per component, so that
    // a per-component absolute tolerance survives it.
    const rtolR = reltol ** (2 / 3) / 10;
    const scale = rtolR / reltol;
    const atolR = typeof integ.abstol === 'number'
      ? integ.abstol * scale
      : (this.atolR && this.atolR.length === n
        ? this.atolR : (this.atolR = new Float64Array(n)));
    if (typeof atolR !== 'number') {
      for (let i = 0; i < n; i++) atolR[i] = integ.abstol[i] * scale;
    }

    const gammaDt = tab.gamma / dt;
    const alphaDt = tab.alpha / dt;
    const betaDt = tab.beta / dt;

    // W for the real half: (γ/h)I − J. Passing dt/γ as the "γ·h" of the
    // transformed form gives exactly that. J is kept from the last step when
    // the Newton iteration was converging quickly and the step has not moved
    // much, which is Hairer's rule and most of what makes Radau affordable.
    const needNew = integ.W.jacStale
      || !integ.W.haveFactor
      || this.status !== 'FastConvergence';
    // The complex half is built from the same J as the real one, so whenever
    // `form` renewed J -- asked to, or because the one it had was too old --
    // it is rebuilt too. Keyed on the request alone, a J renewed for its age at
    // an unchanged step left the complex half factorised from the old one.
    const jacsBefore = integ.jacCache.njac;
    if (!integ.formW(dt / tab.gamma, true, needNew)) return false;
    const jacRenewed = integ.jacCache.njac !== jacsBefore;
    if (needNew || jacRenewed || !this.complexValid || this.complexDt !== dt) {
      if (!this.formComplexW(integ, alphaDt, betaDt)) return false;
      this.complexValid = true;
      this.complexDt = dt;
    }
    integ.stats.nw = integ.W.nfactor;

    // --- the starting guess ---------------------------------------------------
    if (!this.haveHistory) {
      z1.fill(0); z2.fill(0); z3.fill(0);
      w1.fill(0); w2.fill(0); w3.fill(0);
    } else {
      // Extrapolate the last accepted step's collocation polynomial onto this
      // step. Much better than starting from zero, and it is most of why Radau
      // needs only two or three Newton iterations on a smooth stretch.
      //
      // The accepted step's, as OrdinaryDiffEq keeps it -- not the stages as
      // they stand. After a rejected or failed attempt those are that
      // attempt's, and after a Newton that diverged they are whatever it
      // diverged to: each retry then extrapolated from the wreck of the last,
      // the iterate grew by orders of magnitude per attempt, every shorter step
      // failed at once, and the step fell to the floor and stayed there. The
      // rtm page's own Brusselator example did that at t = 13.7.
      const { cont1, cont2, cont3 } = this;
      const c1 = tab.c1;
      const c2 = tab.c2;
      const c1m1 = c1 - 1;
      const c2m1 = c2 - 1;
      const c3p = dt / this.dtprev;
      const c1p = c1 * c3p;
      const c2p = c2 * c3p;
      for (let i = 0; i < n; i++) {
        const a1 = cont1[i];
        const a2 = cont2[i];
        const a3 = cont3[i];
        z1[i] = c1p * (a1 + (c1p - c2m1) * (a2 + (c1p - c1m1) * a3));
        z2[i] = c2p * (a1 + (c2p - c2m1) * (a2 + (c2p - c1m1) * a3));
        z3[i] = c3p * (a1 + (c3p - c2m1) * (a2 + (c3p - c1m1) * a3));
      }
      // Kept at or above zero where the caller asked for that. The polynomial
      // is the step's own, from before the integrator projected the step back
      // to zero, and carried on from a component clamped there it goes on
      // below zero. Where the rates read a species as max(0, y), as the
      // facsimile and rtm models do, f is flat down there and J is not: the
      // Newton sweeps then shrink the iterate by J/(J − γ/h) each, about 0.7
      // at J = −1e3 and h = 0.01, and Radau took every step past 5e-3 for
      // divergence and ground on at that step for good.
      const nn = integ.nonNegative;
      if (nn) {
        for (let i = 0; i < n; i++) {
          if (!nn[i]) continue;
          const floor = -uprev[i];
          if (z1[i] < floor) z1[i] = floor;
          if (z2[i] < floor) z2[i] = floor;
          if (z3[i] < floor) z3[i] = floor;
        }
      }
      for (let i = 0; i < n; i++) {
        w1[i] = tab.TI11 * z1[i] + tab.TI12 * z2[i] + tab.TI13 * z3[i];
        w2[i] = tab.TI21 * z1[i] + tab.TI22 * z2[i] + tab.TI23 * z3[i];
        w3[i] = tab.TI31 * z1[i] + tab.TI32 * z2[i] + tab.TI33 * z3[i];
      }
    }

    // --- Newton ---------------------------------------------------------------
    let eta = Math.max(this.etaOld, Number.EPSILON) ** 0.8;
    let ndw = 1;
    let converged = false;
    let iter = 0;
    while (iter < this.maxIters) {
      iter++;
      for (let i = 0; i < n; i++) ustage[i] = uprev[i] + z1[i];
      integ.f(t + tab.c1 * dt, ustage, ff1);
      for (let i = 0; i < n; i++) ustage[i] = uprev[i] + z2[i];
      integ.f(t + tab.c2 * dt, ustage, ff2);
      for (let i = 0; i < n; i++) ustage[i] = uprev[i] + z3[i];
      integ.f(t + dt, ustage, ff3);

      for (let i = 0; i < n; i++) {
        const fw1 = tab.TI11 * ff1[i] + tab.TI12 * ff2[i] + tab.TI13 * ff3[i];
        const fw2 = tab.TI21 * ff1[i] + tab.TI22 * ff2[i] + tab.TI23 * ff3[i];
        const fw3 = tab.TI31 * ff1[i] + tab.TI32 * ff2[i] + tab.TI33 * ff3[i];
        rhs1[i] = fw1 - gammaDt * w1[i];
        rhs2[i] = fw2 - alphaDt * w2[i] + betaDt * w3[i];
        rhs3[i] = fw3 - betaDt * w2[i] - alphaDt * w3[i];
      }
      // Julia factorises J − (γ/h)I and subtracts the correction; this W is the
      // negative of that, so the correction is added instead.
      integ.solveW(rhs1);
      this.clu.solve(rhs2, rhs3);
      // The real solve is counted by the factorisation; the complex one is
      // this method's own and is counted here.
      integ.W.nsolve++;

      const ndwPrev = ndw;
      ndw = this.scaledNorm(rhs1, integ, atolR, rtolR)
        + this.scaledNorm(rhs2, integ, atolR, rtolR)
        + this.scaledNorm(rhs3, integ, atolR, rtolR);
      if (!Number.isFinite(ndw)) break;

      if (iter > 1) {
        const theta = ndw / ndwPrev;
        const diverging = theta > 1;
        const crawling = ndw * theta ** (this.maxIters - iter) > this.kappa * (1 - theta);
        if (diverging || crawling) { this.status = 'Divergence'; break; }
        eta = theta / (1 - theta);
      }

      for (let i = 0; i < n; i++) {
        w1[i] += rhs1[i];
        w2[i] += rhs2[i];
        w3[i] += rhs3[i];
        z1[i] = tab.T11 * w1[i] + tab.T12 * w2[i] + tab.T13 * w3[i];
        z2[i] = tab.T21 * w1[i] + tab.T22 * w2[i] + tab.T23 * w3[i];
        z3[i] = tab.T31 * w1[i] + w2[i];          // T32 = 1, T33 = 0
      }

      if (eta * ndw < this.kappa && (iter > 1 || ndw === 0 || this.haveHistory)) {
        converged = true;
        this.status = eta < this.fastConvergenceCutoff ? 'FastConvergence' : 'Convergence';
        break;
      }
    }
    integ.stats.nnonliniter += iter;
    this.iter = iter;
    if (!converged) {
      integ.stats.nnonlinconvfail++;
      integ.W.markStale();
      return false;
    }
    this.etaOld = eta;

    // Stiffly accurate: c₃ = 1, so the solution is the third stage.
    for (let i = 0; i < n; i++) u[i] = uprev[i] + z3[i];

    // --- the error estimate ---------------------------------------------------
    const utilde = this.utilde;
    const e1dt = tab.e1 / dt;
    const e2dt = tab.e2 / dt;
    const e3dt = tab.e3 / dt;
    for (let i = 0; i < n; i++) {
      utilde[i] = integ.fsalfirst[i] + e1dt * z1[i] + e2dt * z2[i] + e3dt * z3[i];
    }
    if (this.smoothEst) integ.solveW(utilde);
    let EEst = this.scaledNorm(utilde, integ, atolR, rtolR);

    // On the very first step there is no history to make the estimate
    // meaningful, and Hairer re-takes it about a perturbed point rather than
    // let a spurious rejection set the step size for the whole run.
    if (!(EEst < 1) && !this.haveHistory) {
      const tmp = this.tmpvec;
      for (let i = 0; i < n; i++) tmp[i] = uprev[i] + utilde[i];
      integ.f(t, tmp, ff1);
      for (let i = 0; i < n; i++) {
        utilde[i] = ff1[i] + e1dt * z1[i] + e2dt * z2[i] + e3dt * z3[i];
      }
      if (this.smoothEst) integ.solveW(utilde);
      EEst = this.scaledNorm(utilde, integ, atolR, rtolR);
    }
    integ.EEst = EEst;

    integ.f(t + dt, u, integ.fsallast);
    return true;
  }

  accepted(integ, dtjust) {
    this.dtprev = dtjust;
    this.haveHistory = true;
    // The polynomial the next starting guess is extrapolated from, taken now,
    // while the stages are this accepted step's.
    const { n, tab, z1, z2, z3, cont1, cont2, cont3 } = this;
    const c1 = tab.c1;
    const c2 = tab.c2;
    const c1m1 = c1 - 1;
    const c2m1 = c2 - 1;
    const c1mc2 = c1 - c2;
    for (let i = 0; i < n; i++) {
      const a1 = (z2[i] - z3[i]) / c2m1;
      const tmp = (z1[i] - z2[i]) / c1mc2;
      const a2 = (tmp - a1) / c1m1;
      cont1[i] = a1;
      cont2[i] = a2;
      cont3[i] = a2 - (tmp - z1[i] / c1) / c2;
    }
  }

  /**
   * The collocation polynomial through the three stages: the natural dense
   * output of a Radau method, and accurate to the order of the collocation
   * rather than to the cubic Hermite the integrator would otherwise use.
   *
   * In Newton form about the nodes 1, c₂, c₁:
   *
   *     u(θ) = uprev + z₃ + (θ−1)·[k₁ + (θ−c₂)·(k₂ + (θ−c₁)·k₃)]
   *
   * The (θ−1) out front is what makes θ = 1 give back the step's own endpoint.
   * OrdinaryDiffEq writes the same polynomial with the nodes shifted by one,
   * because there it is used to extrapolate the *previous* step's polynomial
   * onto the next one (see the starting guess above, where the argument is a
   * step ratio and not a position within a step). Reusing that form here reads
   * the polynomial one unit off: it then disagrees with the solver even at the
   * ends of the step, giving a fixed error that no tolerance touches.
   */
  interpolate(integ, theta, out) {
    const { n, tab, z1, z2, z3 } = this;
    const { uprev } = integ;
    const c1 = tab.c1;
    const c2 = tab.c2;
    const c1m1 = c1 - 1;
    const c2m1 = c2 - 1;
    const c1mc2 = c1 - c2;
    const th1 = theta - 1;
    for (let i = 0; i < n; i++) {
      const k1 = (z2[i] - z3[i]) / c2m1;
      const tmp = (z1[i] - z2[i]) / c1mc2;
      const k2 = (tmp - k1) / c1m1;
      const k3 = k2 - (tmp - z1[i] / c1) / c2;
      out[i] = uprev[i] + z3[i] + th1 * (k1 + (theta - c2) * (k2 + (theta - c1) * k3));
    }
    return out;
  }
}

/** RadauIIA5: 5th order, L-stable, 3 stages, fully implicit. */
export function RadauIIA5(options = {}) {
  return {
    name: 'RadauIIA5',
    order: 5,
    build: (n, integ, opts) => new RadauCache(n, integ, { ...opts, ...options }),
    controller: { qmax: 8, qmin: 0.125, gamma: 0.9, qsteadyMin: 1, qsteadyMax: 1.2,
                  ...(options.controller || {}) },
  };
}
