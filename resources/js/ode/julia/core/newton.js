/* ==========================================================================
   ode_julia / core / newton

   The simplified Newton iteration the implicit methods share, with
   OrdinaryDiffEq's convergence machinery.

   "Simplified" means W is held fixed across the iterations of one stage, and
   usually across several steps: re-forming the Jacobian is the expensive part,
   and a Newton iteration on a stiff stage converges perfectly well with a W
   that is merely close. The price is that convergence has to be watched, and
   that watching is most of what is in this file.

   The heuristics -- κ = 1/100, the contraction estimate θ, the forecast
   η = θ/(1−θ), the divergence tests, the carried-over ηold -- are taken
   from OrdinaryDiffEqNonlinearSolve's nlsolve!. They are tuning, arrived at
   over years against the standard stiff test sets, and there is nothing to be
   gained by inventing different ones.

   SIGN AND SCALING CONVENTION. This package builds W in its textbook form:

        W = I − γh·J          (untransformed, what a Newton stage wants, and
                               what this file assumes -- see `solve`)
        W = I/(γh) − J        (transformed, what Rosenbrock and Radau want)

   OrdinaryDiffEq stores the negative of these -- `W = J - M*inv(dtgamma)`,
   despite what its own docstring says -- so its updates read `z - W\\r` where
   the same step here reads `z + W\\r`. Anyone comparing the two line by line
   should expect exactly one sign to differ at each linear solve.
   ========================================================================== */

/** How the stage value is recovered from the stage increment z. */
export const DIRK = 'DIRK';                               // u = tmp + γ·z
export const COEFFICIENT_MULTISTEP = 'COEFFICIENT_MULTISTEP'; // u = z

export const Convergence = 'Convergence';
export const Divergence = 'Divergence';
export const NewtonMaxIters = 'MaxIters';   // named apart from the
// integrator's MaxIters: one says a stage would not converge, the other
// says the whole run ran out of steps, and a single-file bundle cannot
// hold two constants of the same name.
export const Singular = 'Singular';

/** 100·sqrt(eps): the band around θ = 1 where floating point has run out. */
const EPS_AROUND_ONE = 100 * Math.sqrt(Number.EPSILON);

/**
 * How closely each stage's Newton iteration must converge, as a fraction of
 * one unit of the integration tolerance.
 *
 * OrdinaryDiffEq uses 1/100. This package uses 1/1000, and the difference is
 * measured rather than chosen: at 1/100 the stages of an ESDIRK method carry
 * enough left-over Newton error to contaminate its embedded error estimate,
 * which is a small difference of those same stages and so does not enjoy the
 * cancellation the solution does. The symptom is not an inaccurate answer --
 * it is a step-size controller acting on a corrupted estimate, which on the
 * pollution problem walked TRBDF2's solution up to 1e9 in components that
 * belong between 0 and 1, and on van der Pol left KenCarp4 twenty thousand
 * tolerance units out. At 1/1000 both are correct and, because the controller
 * is no longer being lied to, both are also several times CHEAPER: TRBDF2 on
 * the pollution problem goes from failing after 876 steps to finishing in 325.
 */
const DEFAULT_KAPPA = 1e-3;

/**
 * Scaled residual, as SciML's calculate_residuals: each component of the
 * increment measured against what a unit of error would be for that component.
 */
function residualNorm(dz, uprev, ustep, abstol, reltol, n, norm) {
  const scalarAtol = typeof abstol === 'number';
  if (norm === 'max') {
    let m = 0;
    for (let i = 0; i < n; i++) {
      const a = scalarAtol ? abstol : abstol[i];
      const w = a + reltol * Math.max(Math.abs(uprev[i]), Math.abs(ustep[i]));
      const r = Math.abs(dz[i]) / w;
      if (r > m) m = r;
    }
    return m;
  }
  let s = 0;
  for (let i = 0; i < n; i++) {
    const a = scalarAtol ? abstol : abstol[i];
    const w = a + reltol * Math.max(Math.abs(uprev[i]), Math.abs(ustep[i]));
    const r = dz[i] / w;
    s += r * r;
  }
  return Math.sqrt(s / n);
}

/**
 * One reusable simplified-Newton solver.
 *
 * Solves, for the stage increment z,
 *
 *     z = h·f(t + c·h, tmp + γ·z)            (DIRK)
 *     z = tmp + h·γ·f(t + c·h, z)            (COEFFICIENT_MULTISTEP, rearranged
 *                                             so that z is the stage *value*)
 *
 * The caller sets `tmp`, `gamma`, `c` and the method before each solve, and
 * reads `z` afterwards. Nothing is allocated per solve.
 */
export class NewtonSolver {
  /**
   * @param {number} n
   * @param {object} opts
   * @param {number} [opts.kappa=0.01]
   * @param {number} [opts.maxIters=10]
   * @param {number} [opts.fastConvergenceCutoff=0.2]
   * @param {'rms'|'max'} [opts.norm='rms']
   */
  constructor(n, opts = {}) {
    this.n = n;
    this.kappa = opts.kappa ?? DEFAULT_KAPPA;
    this.maxIters = opts.maxIters ?? 10;
    this.fastConvergenceCutoff = opts.fastConvergenceCutoff ?? 0.2;
    this.norm = opts.norm || 'rms';

    this.z = new Float64Array(n);       // the stage increment being solved for
    this.tmp = new Float64Array(n);     // the explicit part, set by the caller
    this.ustep = new Float64Array(n);   // the stage value the residual was taken at
    this.k = new Float64Array(n);       // f at the stage value
    this.dz = new Float64Array(n);      // the Newton correction

    this.gamma = 1;
    this.c = 0;
    this.method = DIRK;

    // Carried between solves, as in OrdinaryDiffEq: the convergence estimate
    // from the previous stage is the best guess for the next one.
    this.etaOld = 1;
    this.prevTheta = 1;
    this.status = Convergence;
    this.iter = 0;
    this.eta = 1;
    this.ndz = 0;
    this.nfails = 0;
    this.nf = 0;

    // Set by the caller for BDF/NDF, where the truncation error is
    // proportional to the total Newton displacement and the convergence test
    // has to be tightened by the same constant.
    this.errorConstant = 1;
  }

  /** Forget the history; used when the integrator restarts. */
  reset() {
    this.etaOld = 1;
    this.prevTheta = 1;
    this.nfails = 0;
  }

  /** The stage value implied by the current z. */
  applyStep(out) {
    const { n, z, tmp, gamma, method } = this;
    if (method === DIRK) for (let i = 0; i < n; i++) out[i] = tmp[i] + gamma * z[i];
    else out.set(z);
    return out;
  }

  /**
   * Run the iteration.
   *
   * @param {(t:number,u:Float64Array,out:Float64Array)=>void} f
   * @param {object} W        a WFactorization, already formed for this γh
   * @param {number} t        the step's start time
   * @param {number} dt
   * @param {Float64Array} uprev
   * @param {object} tol      { reltol, abstol }
   * @param {boolean} [newW]  W was just rebuilt, so ηold should not be trusted
   * @param {boolean} [lastAccepted=true]
   * @returns {string} one of Convergence / Divergence / MaxIters
   */
  solve(f, W, t, dt, uprev, tol, newW, lastAccepted = true) {
    const { n, z, ustep, dz, k, kappa, maxIters } = this;
    const gammaDt = this.gamma * dt;
    const tstep = t + this.c * dt;

    let eta = newW ? Math.max(this.etaOld, Number.EPSILON) ** 0.8 : this.etaOld;
    let ndz = 1;
    let prevTheta = lastAccepted ? this.prevTheta : 1;
    this.status = Divergence;

    for (let iter = 1; iter <= maxIters; iter++) {
      this.iter = iter;
      const ndzPrev = ndz;

      // --- the residual, and the correction that kills it -------------------
      //
      // For a DIRK stage the equation is  g(z) = h·f(tmp + γ·z) − z = 0, so
      // g'(z) = γh·J − I = −W with W = I − γh·J, and one Newton step is
      //
      //     z  ←  z − g'(z)⁻¹·g(z)  =  z + W⁻¹·g(z).
      //
      // W is therefore formed UNTRANSFORMED here, and g is not scaled. The
      // transformed pair -- W = I/(γh) − J against a residual divided by γh,
      // which is how OrdinaryDiffEq writes it -- gives the same increment
      // because the two factors of γh cancel; mixing one with the other does
      // not, and is off by exactly γh. That mistake makes every step fail its
      // error test rather than producing a wrong answer, which is the good
      // kind of mistake, but it is worth saying which convention is in force.
      this.applyStep(ustep);
      this.nf++;
      f(tstep, ustep, k);
      if (this.method === DIRK) {
        for (let i = 0; i < n; i++) dz[i] = dt * k[i] - z[i];
      } else {
        // The stage value is z itself:  g(z) = tmp + γh·f(z) − z.
        for (let i = 0; i < n; i++) dz[i] = this.tmp[i] + gammaDt * k[i] - z[i];
      }
      W.solve(dz);

      ndz = residualNorm(dz, uprev, ustep, tol.abstol, tol.reltol, n, this.norm);
      if (this.errorConstant !== 1) ndz *= this.errorConstant;

      if (!Number.isFinite(ndz)) {
        this.status = Divergence;
        this.nfails++;
        break;
      }

      // --- how fast is it contracting? --------------------------------------
      let theta;
      if (iter > 1) {
        // The 0.3 floor keeps one lucky iteration from declaring victory.
        theta = prevTheta = Math.max(0.3 * prevTheta, ndz / ndzPrev);
        if (Math.abs(theta - 1) <= EPS_AROUND_ONE) {
          // The iteration has stopped moving. Either it is at the root and the
          // remaining motion is rounding, or it is stuck away from it.
          if (ndz <= 1) {
            this.status = Convergence;
            this.nfails = 0;
            for (let i = 0; i < n; i++) z[i] += dz[i];
            this.eta = eta;
            this.ndz = ndz;
            this.etaOld = eta;
            this.prevTheta = prevTheta;
            return this.status;
          }
          this.status = Divergence;
          this.nfails++;
          break;
        }
        if (theta > 2) {
          this.status = Divergence;
          this.nfails++;
          break;
        }
      } else {
        theta = prevTheta;
      }

      // --- take it ----------------------------------------------------------
      for (let i = 0; i < n; i++) z[i] += dz[i];

      // η forecasts the total remaining displacement from the contraction rate:
      // ‖z* − z‖ ≲ θ/(1−θ)·‖dz‖. Converged when that forecast is below κ.
      eta = theta / (1 - theta);
      // The η test may not fire on the first iteration. η is a forecast built
      // from a contraction rate θ, and on iteration 1 there is no θ from this
      // solve to build it from -- the value used is whatever the last solve
      // left behind, which is not evidence about this one. Trusting it lets a
      // single Newton step from a seeded guess declare victory with a
      // correction a fiftieth of a tolerance unit still outstanding. The
      // `ndz < 1e-5` clause is the honest first-iteration case: a correction
      // that small means the guess was already the answer.
      if ((iter === 1 && ndz < 1e-5) || (iter > 1 && eta >= 0 && eta * ndz < kappa)) {
        this.status = Convergence;
        this.nfails = 0;
        break;
      }
      if (iter === maxIters) {
        this.status = NewtonMaxIters;
        this.nfails++;
      }
    }

    this.eta = eta;
    this.ndz = ndz;
    this.etaOld = eta;
    this.prevTheta = prevTheta;
    return this.status;
  }

  /** Did the last solve converge quickly enough to keep W for the next step? */
  get fastConvergence() {
    return this.status === Convergence && this.eta < this.fastConvergenceCutoff;
  }
}
