/* ==========================================================================
   ode_julia / core / integrator

   The loop every method runs inside: propose a step, judge it, save it, look
   for events, choose the next one.

   A method contributes a cache with four things -- `init`, `step`, `accepted`
   and, if it has one of its own, `interpolate`. Everything else (the Jacobian,
   W, the Newton iteration, the controller, saving, event location, the limits
   that keep a browser tab alive) belongs here and is written once.

   The interface a method implements:

     cache.order            order of the method
     cache.errorOrder       order of the error estimate, for the controller
     cache.init(integ)      once, after f(t0, u0) is known
     cache.step(integ)      compute a candidate: set integ.u and integ.EEst,
                            return true, or return false to have the step
                            rejected outright (a failed Newton, a singular W)
     cache.accepted(integ)  roll any history forward; optional
     cache.interpolate(integ, theta, out)   optional; without it, cubic
                            Hermite through the two ends is used. Read over
                            the whole step just taken, θ = 0 at its start and
                            θ = 1 at its end, and only before the history rolls
                            forward: event location and the rows saved inside
                            the step both come from it, and both happen first.
   ========================================================================== */

import { JacobianCache, WFactorization } from './jacobian.js';
import { NewtonSolver } from './newton.js';
import { PIController, initialStep } from './controller.js';

export const Success = 'Success';
export const MaxIters = 'MaxIters';
export const DtLessThanMin = 'DtLessThanMin';
export const Unstable = 'Unstable';
export const Terminated = 'Terminated';
export const ConvergenceFailure = 'ConvergenceFailure';

/** Thrown for a problem that cannot be integrated at all, rather than one that fails part-way. */
export class ODEError extends Error {
  constructor(code, message, t) {
    super(message);
    this.name = 'ODEError';
    this.code = code;
    this.t = t;
  }
}

/**
 * u' = f(t, u) on [t0, tf], with whatever is known about df/du.
 *
 * @param {(t:number,u:Float64Array,du:Float64Array)=>void} f  in place: writes du
 * @param {ArrayLike<number>} u0
 * @param {[number, number]} tspan
 * @param {object} [opts]
 * @param {(t:number,u:Float64Array,J:object)=>void} [opts.jac]  exact Jacobian, filled in place
 * @param {(t:number,u:Float64Array,dT:Float64Array)=>void} [opts.tgrad]  exact df/dt.
 *        Only the Rosenbrock methods use it, and only for a non-autonomous f.
 *        Worth giving where it is known: differenced, it is accurate to about
 *        1e-8 relative, which becomes the accuracy floor of a fifth-order
 *        method well before its step size does.
 * @param {{colPtr:Int32Array,rowIdx:Int32Array}} [opts.jacPattern]  sparsity of df/du
 * @param {object} [opts.events]  { n, fun(t, u, out), direction, enabled, terminal, apply(t, u) }.
 *        `direction` is one number for every function or an array with one
 *        per function: above 0 a rising crossing counts, below 0 a falling
 *        one, 0 either. `enabled`, if given, has one entry per function, and a
 *        function whose entry is 0 is not looked at: a caller that switches an
 *        event off once it has fired -- FACSIMILE's WHEN -- keeps it off.
 */
export class ODEProblem {
  constructor(f, u0, tspan, opts = {}) {
    this.f = f;
    this.u0 = Float64Array.from(u0);
    this.tspan = tspan;
    this.jac = opts.jac || null;
    this.tgrad = opts.tgrad || null;
    this.jacPattern = opts.jacPattern || null;
    this.events = opts.events || null;
    this.n = this.u0.length;
  }
}

/** What a solve gives back. */
export class ODESolution {
  constructor(t, u, stats, retcode, message) {
    this.t = t;                 // Float64Array of save times
    this.u = u;                 // Float64Array[] of states
    this.stats = stats;
    this.retcode = retcode;
    this.message = message || '';
    this.events = [];           // { t, u, which, all } for each event that fired:
                                // `which` the first function, `all` every one
                                // that crossed at that instant
    this.interp = null;         // set when dense output was kept
  }

  get length() { return this.t.length; }

  /** The state at the last saved time. */
  get final() { return this.u[this.u.length - 1]; }

  /**
   * u(t) by the method's own interpolant where dense output was kept, and by
   * cubic Hermite through the bracketing saved points otherwise.
   */
  at(t, out) {
    const ts = this.t;
    const dest = out || new Float64Array(this.u[0].length);
    if (t <= ts[0]) { dest.set(this.u[0]); return dest; }
    if (t >= ts[ts.length - 1]) { dest.set(this.u[this.u.length - 1]); return dest; }
    let lo = 0;
    let hi = ts.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (ts[mid] <= t) lo = mid; else hi = mid;
    }
    if (this.interp && this.interp[lo]) return this.interp[lo](t, dest);
    const h = ts[hi] - ts[lo];
    const theta = h === 0 ? 0 : (t - ts[lo]) / h;
    const a = this.u[lo];
    const b = this.u[hi];
    for (let i = 0; i < dest.length; i++) dest[i] = a[i] + theta * (b[i] - a[i]);
    return dest;
  }
}

const DEFAULTS = {
  reltol: 1e-3,
  abstol: 1e-6,
  dtmax: Infinity,
  dtmin: 0,               // 0 means "derive it from eps and the span"
  dt: 0,                  // 0 means "choose the first step"
  maxiters: 1e7,
  maxSteps: 0,            // 0 means maxiters
  force_dtmin: false,
  saveEverystep: true,
  saveat: null,
  dense: false,
  maxPoints: 0,           // 0 means no ceiling
  progress: null,         // (t, nsteps) => false to stop
  progressEvery: 64,
  onAccepted: null,       // (t, u) after every accepted step, before the state
                          // moves on. For a caller that keeps the run itself;
                          // pair it with saveEverystep: false and nothing is
                          // stored twice.
  onOutput: null,         // (t, u) for every saveat time as it is saved, in
                          // order, before the onAccepted of the step it lies
                          // in. `u` is a buffer the next row reuses.

  matrix: 'auto',
  norm: 'rms',
  central: false,         // difference the Jacobian centrally: twice the cost,
                          // about three more digits, and it matters -- see the
                          // note on Rosenbrock methods in the README
  unstableCheck: true,
  adaptive: true,        // false: march at the given dt and ignore the error estimate
  tstops: null,
  maxEvents: 1000,
  history: null,          // { t: number[], u: Float64Array[] } before t0, newest
                          // first; the multistep methods start at full order
  maxOrder: 0,            // cap on a variable-order method's order
  minOrder: 0,
  maxJacAge: 20,          // steps a Jacobian may be reused for, come what may
  kappa: undefined,       // how tightly each stage's Newton must converge
  newtonMaxIters: undefined,
  nonNegative: null,      // boolean[] or true: clamp these components at 0
  autoAbstol: false,      // let abstol follow the solution upwards; see below
  belowTolRun: 0,         // steps at the smallest representable size that may
                          // be accepted after failing the error test. 0 is
                          // The conventional rule: stop instead.
};

/**
 * Everything one integration needs, in one object the caches are handed.
 */
class Integrator {
  constructor(prob, alg, opts) {
    const n = prob.n;
    this.n = n;
    this.prob = prob;
    this.opts = opts;
    this.reltol = opts.reltol;
    this.abstol = opts.abstol;
    /*
      Let the absolute tolerance follow the solution upwards.

      After each accepted step, abstol[i] <- max(abstol[i], reltol*|u[i]|), so
      each component ends up judged against the largest it has ever been rather
      than against a floor chosen before the run. On a chemical system that is
      often the right question: a radical that rose to 1e-5 and has decayed to
      1e-40 is otherwise still held to the original abstol, which may be thirty
      orders below anything it ever was, and the step size pays for it.

      It only ever loosens, never tightens -- the point, and the risk.

      The Newton iteration keeps the tolerance it started with. The two uses
      want opposite things: the error test asks whether a component is accurate
      enough, where its history is the fair measure, while the Newton test asks
      how well this stage has been solved, where it is not. The same conflation
      in the page's own NDF, where the threshold also scales the linear system,
      turned a 5888-step run into a 72303-step one.
    */
    this.autoAbstol = !!opts.autoAbstol;
    if (this.autoAbstol) {
      this.abstol = typeof opts.abstol === 'number'
        ? new Float64Array(n).fill(opts.abstol)
        : Float64Array.from(opts.abstol);
      this.abstolFixed = opts.abstol;   // what the Newton keeps using
    } else {
      this.abstolFixed = opts.abstol;
    }

    this.t = prob.tspan[0];
    this.tf = prob.tspan[1];
    this.tdir = Math.sign(this.tf - this.t) || 1;
    this.u = new Float64Array(n);
    this.uprev = new Float64Array(n);
    this.uprev.set(prob.u0);
    this.u.set(prob.u0);
    this.fsalfirst = new Float64Array(n);   // f(t, uprev)
    this.fsallast = new Float64Array(n);    // f(t+dt, u), where a method has it
    this.tmpvec = new Float64Array(n);
    this.EEst = 1;
    this.dt = 0;
    this.dtpropose = 0;
    this.acceptStep = true;
    this.forceStepfail = false;
    this.nsteps = 0;

    this.nonNegative = null;
    if (opts.nonNegative) {
      this.nonNegative = opts.nonNegative === true
        ? new Uint8Array(n).fill(1)
        : Uint8Array.from(opts.nonNegative, (v) => (v ? 1 : 0));
    }

    // The counted work, reported back on the solution.
    this.stats = {
      nf: 0, njacs: 0, nw: 0, nsolve: 0, nsteps: 0, naccept: 0, nreject: 0,
      nnonlinconvfail: 0, nnonliniter: 0, nbelowtol: 0, maxOrder: 0, points: 0, stride: 1,
      sparse: false, fill: null, ordering: 'none', alg: alg.name,
    };

    // Jacobian, W and Newton exist for every method here; a Rosenbrock cache
    // simply never touches the Newton solver.
    this.jacCache = new JacobianCache(n, {
      jac: prob.jac, jacPattern: prob.jacPattern, matrix: opts.matrix,
      central: opts.central,
    });
    this.W = new WFactorization(n, this.jacCache, {
      matrix: opts.matrix, maxJacAge: opts.maxJacAge,
    });
    this.newton = new NewtonSolver(n, {
      norm: opts.norm, kappa: opts.kappa, maxIters: opts.newtonMaxIters,
    });
    this.stats.sparse = this.W.sparse;
    this.stats.ordering = this.W.ordering;

    this.f = (t, u, du) => { this.stats.nf++; prob.f(t, u, du); };
    this.cache = alg.build(n, this, opts);
    this.controller = new PIController({
      order: this.cache.errorOrder ?? this.cache.order,
      ...(alg.controller || {}),
    });
  }

  /** A step's worth of clamping, where the caller asked for non-negativity. */
  clamp(u) {
    const nn = this.nonNegative;
    if (!nn) return 0;
    let hit = 0;
    for (let i = 0; i < this.n; i++) if (nn[i] && u[i] < 0) { u[i] = 0; hit++; }
    return hit;
  }

  /** The error weights for the current step: atol + rtol·max(|uprev|, |u|). */
  weight(i) {
    const a = typeof this.abstol === 'number' ? this.abstol : this.abstol[i];
    return a + this.reltol * Math.max(Math.abs(this.uprev[i]), Math.abs(this.u[i]));
  }

  /**
   * ‖e‖ in the integrator's norm, weighted as above.
   *
   * A component that is not a number makes the norm not a number, in the
   * maximum norm as in the root mean square. `r > m` alone is never true of
   * NaN, which let a step whose error could not be measured pass on the
   * components that could.
   */
  errorNorm(e) {
    const n = this.n;
    if (this.opts.norm === 'max') {
      let m = 0;
      for (let i = 0; i < n; i++) {
        const r = Math.abs(e[i] / this.weight(i));
        if (r > m) m = r;
        else if (r !== r) return NaN;
      }
      return m;
    }
    let s = 0;
    for (let i = 0; i < n; i++) {
      const r = e[i] / this.weight(i);
      s += r * r;
    }
    return Math.sqrt(s / n);
  }

  /** Build and factorise W for this γ·dt. Returns false if it is singular. */
  formW(gammaDt, transform, forceJac = false) {
    const ok = this.W.form(this.f, this.t, this.uprev, this.fsalfirst, gammaDt, transform, forceJac);
    this.stats.njacs = this.jacCache.njac;
    this.stats.nw = this.W.nfactor;
    return ok;
  }

  solveW(b) {
    this.stats.nsolve++;
    return this.W.solve(b);
  }
}

/**
 * Tell the caller where the run has got to, every `progressEvery` attempts.
 *
 * Counted in attempts and called from the rejection paths too, not only after
 * an accepted step. A solver in difficulty can reject hundreds of steps in a
 * row, and that is precisely when a page wants to show that something is
 * happening and to offer a way out of it -- so all three call sites obey the
 * answer, not only the one after an accepted step. A run collapsing its step
 * towards the minimum is exactly the run somebody wants to stop, and it is the
 * one that never reaches an accepted step to be stopped at.
 *
 * @returns {false} if the caller asked for the run to stop.
 */
function reportProgress(integ, opts) {
  if (!opts.progress) return true;
  if ((integ.nsteps % opts.progressEvery) !== 0) return true;
  return opts.progress(integ.t, integ.nsteps) !== false ? true : false;
}

/** Cubic Hermite through (t, uprev, f0) and (t+dt, u, f1). */
function hermite(theta, dt, uprev, u, f0, f1, out) {
  const n = out.length;
  const t2 = theta * theta;
  const t3 = t2 * theta;
  const h00 = 2 * t3 - 3 * t2 + 1;
  const h10 = t3 - 2 * t2 + theta;
  const h01 = -2 * t3 + 3 * t2;
  const h11 = t3 - t2;
  for (let i = 0; i < n; i++) {
    out[i] = h00 * uprev[i] + h10 * dt * f0[i] + h01 * u[i] + h11 * dt * f1[i];
  }
  return out;
}

/**
 * Locate the earliest event crossing inside the step just taken.
 *
 * The event functions are continuous and are looked at through the step's own
 * interpolant, so the crossing is found where the solution actually is rather
 * than where a straight line between the ends would put it. Bisection then
 * Illinois: bisection cannot fail, Illinois converges quickly, and together
 * they need a handful of interpolations.
 */
function findEvent(integ, evalAt, gPrev, work) {
  const ev = integ.prob.events;
  if (!ev) return null;
  const { gNow } = work;

  ev.fun(integ.t + integ.dt, integ.u, gNow);
  // Every function that crossed, each in the direction asked of it. The
  // direction may be one number for all of them or one each; an array used to
  // be compared with 0 as a whole, and with two or more entries that is never
  // true, so no crossing was ever seen.
  const crossed = [];
  const { enabled } = ev;
  for (let i = 0; i < ev.n; i++) {
    // A function switched off is not an event, however it moves.
    if (enabled && !enabled[i]) continue;
    const a = gPrev[i];
    const b = gNow[i];
    const dir = directionOf(ev, i);
    const rising = a < 0 && b >= 0;
    const falling = a > 0 && b <= 0;
    if ((dir >= 0 && rising) || (dir <= 0 && falling)) crossed.push(i);
  }
  if (!crossed.length) return null;

  // Each located, and the earliest is what happened: two functions crossing in
  // one step must not be reported in the order they are numbered, or the later
  // one is found first and the earlier is behind the restart, never to fire.
  // Those that cross together within the precision of the search are reported
  // together, since a restart from the one would see the other at its start.
  const found = [];
  for (const which of crossed) {
    const theta = locateRoot(integ, evalAt, ev, which, gPrev[which], work);
    const tEvent = integ.t + theta * integ.dt;
    if (rootAtStart(integ, tEvent)) continue;
    found.push({ theta, t: tEvent, which });
  }
  if (!found.length) return null;
  let first = found[0];
  for (const f of found) if (f.theta < first.theta) first = f;
  const together = Math.max(2e-14 * Math.abs(integ.dt),
    16 * Number.EPSILON * Math.max(Math.abs(first.t), Math.abs(integ.dt)));
  const group = found.filter((f) => Math.abs(f.t - first.t) <= together);
  // The state handed back is where every one of them has crossed -- the far
  // side of the latest -- so that a run restarted from it does not find the
  // same crossings again a few ulps in.
  let last = first;
  for (const f of group) if (f.theta > last.theta) last = f;
  const all = group.map((f) => f.which).sort((a, b) => a - b);
  evalAt(last.theta, work.uEvent);
  return { theta: last.theta, t: last.t, which: all[0], all };
}

/** The direction asked of event function `i`: one number for all, or one each. */
function directionOf(ev, i) {
  const d = ev.direction;
  if (d == null) return 1;
  if (typeof d === 'number') return d;
  const v = d[i];
  return v == null ? 1 : v;
}

/**
 * Where in the step, as θ, event function `which` crosses zero: bisection
 * then Illinois on the step's interpolant, from `gStart` at θ = 0.
 *
 * The answer is the bracket's far end, the first θ found at which the
 * function has crossed, as the NDF's search reports it -- not the middle of
 * the bracket. From the middle, the state handed back could lie a hair short
 * of the crossing: a caller that restarts there sees the function still on
 * the near side, and its first step crosses again. Rodas5P and KenCarp4 fired
 * `A - 0.9704455335485082, down`, with A = exp(-0.3 t), twice, 4e-16 apart.
 */
function locateRoot(integ, evalAt, ev, which, gStart, work) {
  const { gNow, utmp } = work;
  const g = (theta) => {
    evalAt(theta, utmp);
    ev.fun(integ.t + theta * integ.dt, utmp, gNow);
    return gNow[which];
  };

  let lo = 0;
  let hi = 1;
  let flo = gStart;
  let fhi = g(1);
  // Illinois: the bracket is kept, and the stale end is halved so that the
  // secant cannot stall against it.
  for (let it = 0; it < 60 && hi - lo > 1e-14; it++) {
    const denom = fhi - flo;
    let mid = denom === 0 ? 0.5 * (lo + hi) : lo - flo * (hi - lo) / denom;
    if (!(mid > lo && mid < hi)) mid = 0.5 * (lo + hi);
    const fmid = g(mid);
    if (fmid === 0) { lo = hi = mid; break; }
    if ((fmid < 0) === (flo < 0)) { lo = mid; flo = fmid; fhi *= 0.5; }
    else { hi = mid; fhi = fmid; flo *= 0.5; }
  }
  return hi;
}

/**
 * Whether a root found at `tEvent` is the instant the solve began, which is
 * not a crossing.
 */
function rootAtStart(integ, tEvent) {
  // A caller that stops at a terminal event and restarts from it -- which is
  // what a compartment model does, to apply whatever the event drives -- hands
  // back the state *at* the root, where g is zero to rounding. Whether that
  // leaves g at -1e-17 or +1e-17 is luck, and on the unlucky side the very
  // first step of the new run crosses it again: the same event fires twice, a
  // duplicate row lands in the output, and a caller that restarts on every
  // event can be walked round that loop indefinitely. KenCarp4 found this on
  // `examples/recorders.json` where the other five methods happened to land on
  // the lucky side.
  const t0 = integ.prob.tspan[0];
  return Math.abs(tEvent - t0)
    <= 16 * Number.EPSILON * Math.max(Math.abs(t0), Math.abs(integ.dt));
}

/**
 * Integrate.
 *
 * @param {ODEProblem} prob
 * @param {object} alg      from the solvers/ directory: { name, build, controller }
 * @param {object} [options]
 * @returns {ODESolution}
 */
export function solve(prob, alg, options = {}) {
  const opts = { ...DEFAULTS, ...options };
  const n = prob.n;
  if (!(n > 0)) throw new ODEError('empty', 'The initial state is empty', prob.tspan[0]);
  const [t0, tf] = prob.tspan;
  if (!Number.isFinite(t0) || !Number.isFinite(tf)) {
    throw new ODEError('tspan', 'The time span must be finite', t0);
  }
  if (t0 === tf) throw new ODEError('tspan', 'The time span is empty', t0);

  const integ = new Integrator(prob, alg, opts);
  const tdir = integ.tdir;
  const span = Math.abs(tf - t0);
  // How small a step may be is a question about the CURRENT time, not about
  // the span. A step of 1e-13 is perfectly representable at t = 0 and is not
  // representable at all at t = 1e5, so a single number derived from the
  // larger end forbids the small steps every stiff solver needs at the start
  // of a run -- FBDF on Robertson over [0, 1e5] was stopped dead by exactly
  // that, three steps in, with nothing wrong with the method.
  const ulp = (x) => (x === 0 ? Number.MIN_VALUE : 2 ** (Math.floor(Math.log2(Math.abs(x))) - 52));
  const dtminAt = opts.dtmin > 0
    ? () => opts.dtmin
    : (t) => Math.max(Number.MIN_VALUE, 16 * ulp(t));
  // The span is finished when what is left of it is no longer representable
  // as a difference of times at this magnitude. Without this the last step
  // lands a few ulp short of tf, the loop asks for one more, and the run
  // reports a step-size failure at the very end of a perfectly good solve.
  const tEps = 16 * Math.max(ulp(t0), ulp(tf));
  const maxSteps = opts.maxSteps > 0 ? opts.maxSteps : opts.maxiters;

  // --- saving ---------------------------------------------------------------
  const T = [];
  const U = [];
  let stride = 1;
  let since = 0;
  const maxPoints = opts.maxPoints > 0 ? Math.max(100, opts.maxPoints) : 0;
  const interp = opts.dense ? [] : null;

  const remember = (t, u, keep) => {
    if (!keep) {
      if (++since < stride) return;
      since = 0;
    }
    T.push(t);
    U.push(Float64Array.from(u));
    if (interp) interp.push(null);
    if (!maxPoints || T.length < maxPoints) return;
    // Halve the store in place, keeping the ends. Doubling the stride as it
    // goes means the thinning is uniform over the whole run rather than
    // discarding the tail, and it costs one pass per doubling.
    let w = 1;
    for (let r = 2; r < T.length; r += 2) {
      T[w] = T[r]; U[w] = U[r];
      if (interp) interp[w] = interp[r];
      w++;
    }
    T.length = w; U.length = w;
    if (interp) interp.length = w;
    stride *= 2;
  };

  // saveat, normalised to a sorted list in the direction of travel
  let saveat = null;
  let saveatAt = 0;
  if (opts.saveat != null) {
    saveat = typeof opts.saveat === 'number'
      ? (() => {
        const out = [];
        for (let t = t0; tdir * (tf - t) > 0; t += tdir * opts.saveat) out.push(t);
        out.push(tf);
        return out;
      })()
      : Array.from(opts.saveat).slice().sort((a, b) => tdir * (a - b));
    while (saveatAt < saveat.length && tdir * (saveat[saveatAt] - t0) < 0) saveatAt++;
  }

  const tstops = opts.tstops
    ? Array.from(opts.tstops).slice().sort((a, b) => tdir * (a - b)).filter((t) => tdir * (t - t0) > 0)
    : [];
  let tstopAt = 0;

  // --- start ----------------------------------------------------------------
  integ.f(t0, integ.uprev, integ.fsalfirst);
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(integ.uprev[i]) || !Number.isFinite(integ.fsalfirst[i])) {
      throw new ODEError('nonfinite',
        `The state or its derivative is not a number at t = ${t0} (component ${i})`, t0);
    }
  }
  if (integ.cache.init) integ.cache.init(integ);

  const work = {
    u1: new Float64Array(n), f1: new Float64Array(n), w: new Float64Array(n),
    gNow: prob.events ? new Float64Array(prob.events.n) : null,
    gPrev: prob.events ? new Float64Array(prob.events.n) : null,
    utmp: new Float64Array(n),
    uEvent: new Float64Array(n),
  };

  if (!opts.adaptive && !opts.dt) {
    throw new ODEError('dt', 'A non-adaptive run needs an explicit dt', t0);
  }
  let dt = opts.dt
    ? Math.abs(opts.dt) * tdir
    : initialStep(integ.f, t0, integ.uprev, integ.fsalfirst, tdir,
                  integ.cache.order, opts.reltol, opts.abstol, opts.dtmax, work);
  if (!Number.isFinite(dt) || dt === 0) dt = tdir * Math.min(1e-6 * span, opts.dtmax);
  dt = tdir * Math.min(Math.abs(dt), Math.abs(opts.dtmax), span);
  integ.dt = dt;

  // With saveat the caller has said exactly which times they want, and t0 is
  // one of them only if they said so. Saving it anyway puts an extra row at
  // the front of every result and quietly shifts the whole array.
  if (!saveat || (saveatAt < saveat.length && saveat[saveatAt] === t0)) {
    remember(t0, integ.uprev, true);
    if (saveat && saveatAt < saveat.length && saveat[saveatAt] === t0) saveatAt++;
  }
  if (prob.events) prob.events.fun(t0, integ.uprev, work.gPrev);

  let retcode = Success;
  let message = '';
  const events = [];
  // How many steps at the floor that failed their error test may be accepted
  // in a row. 0 is the conventional rule: stop and hand back the partial.
  const belowTolMax = Math.max(0, Math.round(opts.belowTolRun ?? 0));
  let belowTolRun = 0;
  let atFloor = false;

  // --- the loop -------------------------------------------------------------
  while (tdir * (tf - integ.t) > tEps) {
    if (integ.nsteps >= maxSteps) {
      retcode = MaxIters;
      message = `More than ${maxSteps} steps were needed, and the run stopped at t = ${integ.t}`;
      break;
    }

    // Do not step past the end, nor past the next thing we were told to land on.
    let limit = tf;
    if (tstopAt < tstops.length && tdir * (tstops[tstopAt] - limit) < 0) limit = tstops[tstopAt];
    if (saveat && saveatAt < saveat.length && tdir * (saveat[saveatAt] - limit) < 0) {
      // saveat alone does not force a step; the interpolant covers it. It does
      // stop the step overshooting the *end*, which is handled above.
    }
    if (tdir * (integ.t + integ.dt - limit) > 0) integ.dt = limit - integ.t;
    // A step that would stop just short of the limit is stretched to land on
    // it, rather than leaving a crumb that costs a whole extra step.
    else if (tdir * (limit - (integ.t + integ.dt)) <= tEps) integ.dt = limit - integ.t;
    // The step is clamped to the floor rather than refused there, which is
    // what the reference implementations do (`absh = min(hmax, max(hmin, absh))`). Whether a step
    // AT the floor that then fails its error test is a failure or something to
    // accept is decided below, once it is known -- refusing here decided it in
    // advance, and decided it for a step that might well have passed.
    const dtmin = dtminAt(integ.t);
    atFloor = Math.abs(integ.dt) <= dtmin;
    if (atFloor) integ.dt = tdir * dtmin;
    if (integ.t + integ.dt === integ.t) {
      retcode = DtLessThanMin;
      message = `The step size fell to ${Math.abs(integ.dt).toExponential(3)} at t = ${integ.t}, `
        + 'which does not change the time at this magnitude';
      break;
    }

    integ.acceptStep = false;
    integ.forceStepfail = false;
    const ok = integ.cache.step(integ);
    integ.nsteps++;
    integ.stats.nsteps++;

    if (!ok || integ.forceStepfail) {
      integ.stats.nreject++;
      if (reportProgress(integ, opts) === false) {
        retcode = Terminated;
        message = 'The run was stopped from outside';
        break;
      }
      // One that failed at the smallest step the clock can represent has
      // nowhere left to go. Halving it only for the floor to bring it back ran
      // the step budget out one futile attempt at a time -- ten million of
      // them by default -- with the run standing still.
      if (atFloor) {
        retcode = ConvergenceFailure;
        message = `The step could not be taken at t = ${integ.t} even at `
          + `${Math.abs(integ.dt).toExponential(3)}, the smallest the clock can represent: `
          + 'the equations of its stages could not be solved there';
        break;
      }
      // A step that failed for a reason other than accuracy -- a Newton that
      // would not converge, a singular W -- is not the controller's business:
      // halve it, and make sure the next attempt uses a fresh Jacobian.
      integ.dt *= 0.5;
      integ.W.markStale();
      integ.controller.reset();
      continue;
    }

    if (opts.unstableCheck) {
      let bad = -1;
      for (let i = 0; i < n; i++) if (!Number.isFinite(integ.u[i])) { bad = i; break; }
      if (bad >= 0) {
        integ.stats.nreject++;
        // The candidate is no state at all; the last accepted one is, and a
        // method that reads integ.u before writing it must not be handed this.
        integ.u.set(integ.uprev);
        integ.dt *= 0.5;
        integ.W.markStale();
        if (Math.abs(integ.dt) < dtminAt(integ.t)) {
          retcode = Unstable;
          message = `The solution became infinite or not-a-number at t = ${integ.t} (component ${bad})`;
          break;
        }
        continue;
      }
    }

    // An error estimate that is not a number says nothing about the step --
    // neither that it was good nor by how much to shrink it; handed to the
    // controller it makes the next step NaN. `!(EEst > 1)` let it through as
    // accepted. It is a step that failed outright, like the ones above.
    if (opts.adaptive && Number.isNaN(integ.EEst)) {
      integ.stats.nreject++;
      integ.u.set(integ.uprev);
      if (reportProgress(integ, opts) === false) {
        retcode = Terminated;
        message = 'The run was stopped from outside';
        break;
      }
      if (atFloor) {
        retcode = Unstable;
        message = `The error estimate is not a number at t = ${integ.t}, even with a step of `
          + `${Math.abs(integ.dt).toExponential(3)}, the smallest the clock can represent`;
        break;
      }
      integ.dt *= 0.5;
      integ.W.markStale();
      integ.controller.reset();
      continue;
    }

    let accepted = !opts.adaptive || integ.EEst <= 1;

    // A step at the smallest size the clock can represent, which has failed
    // its error test anyway. There is nothing left to try: a shorter step does
    // not exist. Two things can be done with it, and `belowTolRun` chooses.
    //
    // With 0, the run stops and hands back what it has, which is what the
    // published methods do (a tolerance-not-met error) and what every solver in
    // DifferentialEquations.jl does.
    //
    // Above 0, that many such steps in a row are accepted instead, counted,
    // and reported. The case for it is that the error test is not always
    // asking a sensible question: restarting from an interpolated state leaves
    // a species with a femtosecond lifetime off its steady state by more than
    // the tolerance, and no step size mends that -- the implicit step itself
    // does. The case against is that it is accepting a step known to be
    // inaccurate, so the count is reported rather than buried.
    if (!accepted && atFloor) {
      if (belowTolRun < belowTolMax) {
        belowTolRun++;
        integ.stats.nbelowtol++;
        accepted = true;
      } else {
        retcode = DtLessThanMin;
        message = `The error test failed at t = ${integ.t} with a step of `
          + `${Math.abs(integ.dt).toExponential(3)}, the smallest the clock can represent`
          + (belowTolMax > 0 ? `, ${belowTolMax} times in a row` : '');
        break;
      }
    }
    if (accepted) belowTolRun = 0;

    if (!accepted) {
      integ.stats.nreject++;
      // A method that chooses its own step on rejection -- FBDF does, because
      // the choice is bound up with dropping the order -- says so by returning
      // true, and the generic controller keeps its hands off.
      const handled = integ.cache.rejected ? integ.cache.rejected(integ) === true : false;
      if (!handled) integ.dt = integ.controller.reject(integ.EEst, integ.dt);
      if (reportProgress(integ, opts) === false) {
        retcode = Terminated;
        message = 'The run was stopped from outside';
        break;
      }
      continue;
    }

    // --- the step is good -----------------------------------------------------
    // What is read inside the step -- the event functions, the saved rows -- is
    // read off the step's own interpolant over the whole step, θ = 0 to 1.
    const tnew = integ.t + integ.dt;
    const evalAt = (theta, out) => {
      if (integ.cache.interpolate) return integ.cache.interpolate(integ, theta, out);
      return hermite(theta, integ.dt, integ.uprev, integ.u, integ.fsalfirst, integ.fsallast, out);
    };

    let ev = null;
    if (prob.events) {
      // f at the end of the step is what the Hermite fallback needs, and only
      // it: a method with an interpolant of its own reads none.
      if (!integ.cache.hasFsalLast && !integ.cache.interpolate) {
        integ.f(tnew, integ.u, integ.fsallast);
      }
      ev = findEvent(integ, evalAt, work.gPrev, work);
    }

    integ.stats.naccept++;
    if (integ.nonNegative) integ.clamp(integ.u);

    // saveat points that the step passed -- up to the event, where one cuts it
    // short -- each where it lies in the whole step. They are read before the
    // event is applied: afterwards the end state and the step length are the
    // event's, while the interpolant is still the whole step's, and a θ worked
    // out against the shortened step read every row inside it at the wrong
    // place.
    if (saveat) {
      const tEnd = ev ? ev.t : tnew;
      while (saveatAt < saveat.length && tdir * (saveat[saveatAt] - tEnd) <= 0) {
        const ts = saveat[saveatAt];
        if (tdir * (ts - integ.t) >= 0) {
          const theta = integ.dt === 0 ? 1 : (ts - integ.t) / integ.dt;
          evalAt(theta, work.utmp);
          if (integ.nonNegative) integ.clamp(work.utmp);
          remember(ts, work.utmp, true);
          if (opts.onOutput) opts.onOutput(ts, work.utmp);
        }
        saveatAt++;
      }
    }

    // An event inside the step cuts it short at the crossing.
    if (ev) {
      integ.dt = ev.t - integ.t;
      integ.u.set(work.uEvent);
      integ.clamp(integ.u);
    }

    if (opts.saveEverystep && !saveat) remember(integ.t + integ.dt, integ.u, false);
    if (opts.onAccepted) opts.onAccepted(integ.t + integ.dt, integ.u);
    if (integ.autoAbstol) {
      const at = integ.abstol;
      for (let i = 0; i < n; i++) {
        const want = opts.reltol * Math.abs(integ.u[i]);
        if (want > at[i]) at[i] = want;
      }
    }

    const dtjust = integ.dt;
    integ.t += integ.dt;
    // Snap onto the end, or onto the time we were told to land on, rather than
    // carrying the rounding of the sum forward. Without the second half a
    // tstop is never quite reached and the solver takes an extra step of a few
    // ulp at every one of them.
    if (Math.abs(tf - integ.t) <= tEps) integ.t = tf;
    else if (tstopAt < tstops.length
      && Math.abs(tstops[tstopAt] - integ.t) <= 16 * Math.max(ulp(integ.t), Number.MIN_VALUE)) {
      integ.t = tstops[tstopAt];
    }
    integ.uprev.set(integ.u);
    if (integ.cache.hasFsalLast) integ.fsalfirst.set(integ.fsallast);
    else integ.f(integ.t, integ.uprev, integ.fsalfirst);

    integ.W.agePlus();
    if (integ.cache.accepted) integ.cache.accepted(integ, dtjust);

    if (tstopAt < tstops.length && tdir * (integ.t - tstops[tstopAt]) >= 0) tstopAt++;

    if (prob.events) {
      if (ev) {
        events.push({ t: integ.t, u: Float64Array.from(integ.u), which: ev.which, all: ev.all });
        if (events.length >= opts.maxEvents) {
          retcode = Terminated;
          message = `Stopped after ${events.length} events`;
          break;
        }
        // Applying the event changes the state discontinuously, so every
        // history the method was carrying is now about a different problem.
        if (prob.events.apply) prob.events.apply(integ.t, integ.u);
        if (integ.nonNegative) integ.clamp(integ.u);
        integ.uprev.set(integ.u);
        integ.f(integ.t, integ.uprev, integ.fsalfirst);
        integ.W.markStale();
        integ.newton.reset();
        integ.controller.reset();
        if (integ.cache.restart) integ.cache.restart(integ);
        remember(integ.t, integ.u, true);
        if (prob.events.terminal) { retcode = Terminated; message = 'An event stopped the run'; break; }
      }
      prob.events.fun(integ.t, integ.uprev, work.gPrev);
    }

    // --- the next step --------------------------------------------------------
    let dtnext = !opts.adaptive
      ? (opts.dt ? Math.abs(opts.dt) * tdir : dtjust)
      : (integ.cache.dtpropose != null
        ? integ.cache.dtpropose
        : integ.controller.accept(integ.EEst, dtjust));
    integ.cache.dtpropose = null;
    if (!Number.isFinite(dtnext) || dtnext === 0) dtnext = dtjust;
    dtnext = tdir * Math.min(Math.abs(dtnext), Math.abs(opts.dtmax));
    integ.dt = dtnext;

    if (reportProgress(integ, opts) === false) {
      retcode = Terminated;
      message = 'The run was stopped from outside';
      break;
    }
  }

  // The end of the span is always kept, whatever the thinning decided -- but
  // not when saveat named the times, where an unasked-for row is worse than a
  // missing one, and not when the run stopped early with nothing to add.
  if (!saveat && (T.length === 0 || T[T.length - 1] !== integ.t)) {
    remember(integ.t, integ.uprev, true);
  }

  const stats = integ.stats;
  stats.points = T.length;
  stats.stride = stride;
  stats.nf = integ.stats.nf;
  stats.njacs = integ.jacCache.njac;
  stats.nw = integ.W.nfactor;
  // Counted on the factorisation, because the Newton iteration solves against
  // it directly rather than through the integrator; reading the integrator's
  // own counter here reported zero solves for every implicit method.
  stats.nsolve = integ.W.nsolve;
  stats.fill = integ.W.fill;
  stats.nnonliniter = integ.newton.nf;
  stats.t = integ.t;

  const sol = new ODESolution(Float64Array.from(T), U, stats, retcode, message);
  sol.events = events;
  return sol;
}
