/* ==========================================================================
   ode_julia / solvers / esdirk

   Singly diagonally implicit Runge-Kutta methods with an explicit first stage:
   TRBDF2 and KenCarp4.

   Each stage solves, for the increment zᵢ = h·f at that stage,

       zᵢ = h·f(t + cᵢh,  uprev + Σⱼ<ᵢ aᵢⱼ·zⱼ + γ·zᵢ)

   by the simplified Newton iteration in core/newton.js. "Singly" means every
   stage shares the same γ, so one W = I − γh·J serves the whole step and, if
   the step size does not move much, several steps after it. That is the
   economy these methods are built around, and it is why they beat a Rosenbrock
   method of the same order on a long smooth run.

   Both are stiffly accurate: the last row of `a` is `b`, so the solution is
   the last stage value, and f at the end of the step is z_s/h -- free, and
   reused as the first stage of the next step.

   Where they sit. TRBDF2 is second order, which sounds modest and is not: it
   is L-stable, it is unusually forgiving on problems where Newton struggles,
   and at loose tolerances it is often the cheapest thing here. KenCarp4 is
   fourth order and is the one to reach for at tolerances below about 1e-6.
   ========================================================================== */

import { TRBDF2Tableau, KenCarp4Tableau } from './esdirk-tableaus.js';
import { DIRK, Convergence } from '../core/newton.js';

class ESDIRKCache {
  constructor(n, tab, integ, opts) {
    this.tab = tab;
    this.n = n;
    this.order = tab.order;
    this.errorOrder = tab.errorOrder;
    // Stiffly accurate: f at the end of the step is the last stage's z over h.
    this.hasFsalLast = true;
    this.dtpropose = null;

    this.z = Array.from({ length: tab.stages }, () => new Float64Array(n));
    this.est = new Float64Array(n);
    this.smoothEst = opts.smoothEst !== false;
    // How many consecutive steps have reused the same W. Julia rebuilds when
    // the Newton iteration stops converging quickly, not on a fixed schedule.
    this.newW = true;
  }

  init(integ) {
    integ.newton.method = DIRK;
    integ.newton.gamma = this.tab.gamma;
  }

  restart() { this.newW = true; }

  step(integ) {
    const { tab, n, z } = this;
    const dt = integ.dt;
    const { uprev, u, t } = integ;
    const newton = integ.newton;
    const gammaDt = tab.gamma * dt;
    const s = tab.stages;

    // One W for the whole step, and usually for several steps after it.
    //
    // Two different questions, and they were confused here at first: W must be
    // rebuilt whenever γh moves, and `form` does that from the stored Jacobian
    // without being asked. A new JACOBIAN is a much larger expense and is
    // justified only by the Newton iteration labouring, or by something having
    // invalidated it. Forcing one on every change of step size -- which is
    // almost every step -- threw away the reuse entirely: FBDF re-differenced
    // on three steps in four.
    const freshJac = integ.W.jacStale || !integ.W.haveFactor || !newton.fastConvergence;
    const gammaMoved = Math.abs(integ.W.gammaDt - gammaDt) > 0.2 * Math.abs(gammaDt);
    if (!integ.formW(gammaDt, false, freshJac)) return false;
    this.newW = freshJac || gammaMoved;

    // Stage 1 is explicit: z₁ = h·f(t, uprev), which the integrator has.
    for (let i = 0; i < n; i++) z[0][i] = dt * integ.fsalfirst[i];

    for (let stage = 1; stage < s; stage++) {
      const a = tab.a[stage];
      const alpha = tab.alpha[stage];
      for (let i = 0; i < n; i++) {
        let v = uprev[i];
        for (let j = 0; j < stage; j++) v += a[j] * z[j][i];
        newton.tmp[i] = v;
      }
      // Seed the iterate from the stages already solved. Shampine's choice;
      // it is worth one Newton iteration a stage and costs a few multiplies.
      for (let i = 0; i < n; i++) {
        let v = 0;
        for (let j = 0; j < stage; j++) v += alpha[j] * z[j][i];
        newton.z[i] = v;
      }
      newton.c = tab.c[stage];
      newton.gamma = tab.gamma;
      const status = newton.solve(
        integ.f, integ.W, t, dt, uprev, { reltol: integ.reltol, abstol: integ.abstolFixed },
        this.newW && stage === 1, true,
      );
      integ.stats.nnonliniter += newton.iter;
      if (status !== Convergence) {
        integ.stats.nnonlinconvfail++;
        // A Newton that will not converge is a statement about W, not about
        // accuracy: the next attempt gets a fresh Jacobian and a shorter step.
        integ.W.markStale();
        return false;
      }
      z[stage].set(newton.z);
      this.newW = false;   // later stages of this step reuse the same W
    }

    // Stiffly accurate, so the solution is the last stage value.
    for (let i = 0; i < n; i++) {
      let v = uprev[i];
      for (let j = 0; j < s; j++) v += tab.b[j] * z[j][i];
      u[i] = v;
    }
    // ... and f at the end of the step came with it.
    const invdt = 1 / dt;
    for (let i = 0; i < n; i++) integ.fsallast[i] = z[s - 1][i] * invdt;

    const est = this.est;
    for (let i = 0; i < n; i++) {
      let v = 0;
      for (let j = 0; j < s; j++) {
        const bt = tab.btilde[j];
        if (bt !== 0) v += bt * z[j][i];
      }
      est[i] = v;
    }
    // Smoothing the estimate through W, as Shampine proposed and Julia does by
    // default. The raw embedded difference is the error of an explicit
    // combination and is badly pessimistic on a very stiff problem -- it sees
    // the fast modes the method is deliberately damping. Passing it through
    // (I − γhJ)⁻¹ damps them in the estimate the same way.
    if (this.smoothEst) integ.solveW(est);
    integ.EEst = integ.errorNorm(est);
    return true;
  }
}

/** TRBDF2: 2nd order, L-stable, 3 stages, trapezoid then BDF2. */
export function TRBDF2(options = {}) {
  return {
    name: 'TRBDF2',
    order: TRBDF2Tableau.order,
    build: (n, integ, opts) => new ESDIRKCache(n, TRBDF2Tableau, integ, { ...options, ...opts }),
    controller: { qmax: 10, qsteadyMin: 1, qsteadyMax: 1.2, ...(options.controller || {}) },
  };
}

/** KenCarp4: 4th order, L-stable, 6 stages, the implicit half of ARK4(3)6L[2]SA. */
export function KenCarp4(options = {}) {
  return {
    name: 'KenCarp4',
    order: KenCarp4Tableau.order,
    build: (n, integ, opts) => new ESDIRKCache(n, KenCarp4Tableau, integ, { ...options, ...opts }),
    controller: { qmax: 10, qsteadyMin: 1, qsteadyMax: 1.2, ...(options.controller || {}) },
  };
}

/** The generic builder, for another ESDIRK tableau of the same shape. */
export function esdirkAlgorithm(tab, options = {}) {
  return {
    name: tab.name,
    order: tab.order,
    build: (n, integ, opts) => new ESDIRKCache(n, tab, integ, { ...options, ...opts }),
    controller: { ...(options.controller || {}) },
  };
}
