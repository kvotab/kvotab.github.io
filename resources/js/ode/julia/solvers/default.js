/* ==========================================================================
   ode_julia / solvers / default

   DefaultODEAlgorithm: what DifferentialEquations.jl runs when it is given no
   algorithm (OrdinaryDiffEqDefault), and the switching machinery under it
   (OrdinaryDiffEqCore's CompositeAlgorithm, AutoSwitch and their caches).

   It starts on an explicit method and watches every step for stiffness. Six
   methods, of which a run uses at most two -- one of each kind, both fixed by
   the tolerance and the size of the system before it starts:

       non-stiff   Tsit5          reltol ≥ 1e-6
                   Vern7          reltol < 1e-6
       stiff       Rosenbrock23   up to 50 states, reltol ≥ 1e-6
                   Rodas5P        up to 50 states, reltol < 1e-6
                   FBDF           51 to 500 states
                   KrylovFBDF     over 500 states: FBDF, its Newton
                                  iterations solved matrix-free by GMRES

   THE TEST. After every attempted step, accepted or not, the explicit
   method's estimate of the largest eigenvalue |λ| (see explicitStiffness in
   ./tsit5.js), or ‖J‖∞ whenever a stiff method has formed J, is turned into

       stiffness = |λ|·dt / S,      S the width of the non-stiff method's
                                    stability region (3.5068 Tsit5, 4.64 Vern7)

   and the step counts as stiff if that exceeds 9/10. Eleven stiff verdicts in
   a row on the explicit method switch to the stiff one and double dt; four
   non-stiff ones in a row on the stiff method switch back and halve it. A
   counter of verdicts is all the state there is (AutoSwitchCache).

   While the explicit method is being found stiff the integrator's error
   checks are waived (OrdinaryDiffEq's do_error_check), so a step forced down
   by instability does not end the run before the switch can happen.

   WHAT IS ITS OWN HERE. Each method keeps its own step controller, as each
   branch of OrdinaryDiffEq's CompositeController does; the stiff and
   non-stiff ones share the integrator's Jacobian, W and Newton iteration,
   which only one of them uses. A method switched to is started as
   OrdinaryDiffEq's initialize! would: FBDF from order 1, a Rosenbrock method
   as it always starts.

   A FAULT IN JULIA, NOT REPRODUCED. Inside OrdinaryDiffEq's composite
   (OrdinaryDiffEqCore 4.18.1, OrdinaryDiffEqBDF 2.4.12) the BDF controller
   decides acceptance from the error estimate in its own cache, which only
   ever holds its starting 1: the estimate is written to the composite's. So
   no FBDF step is ever rejected there -- one 62 tolerance units out was
   accepted. Here the error test stands, and two things follow from keeping
   it, both above: no verdict is counted on an FBDF attempt it rejects, which
   in Julia never exists, and FBDF's first step after a switch is predicted
   by an Euler step rather than from the last value, whose first estimate is
   h·f and was rejected over and over at tight tolerances.

   And one deliberate difference in the stiffness estimate: a state that has
   not moved at all is passed over instead of making the estimate NaN (and so
   "stiff") -- see explicitStiffness. `stillIsStiff: true` gives
   OrdinaryDiffEq's reading.
   ========================================================================== */

import { PIController } from '../core/controller.js';
import { hermite } from '../core/integrator.js';
import { Tsit5 } from './tsit5.js';
import { Vern7 } from './vern7.js';
import { Rosenbrock23 } from './rosenbrock23.js';
import { Rodas5P } from './rosenbrock.js';
import { FBDF } from './fbdf.js';

// OrdinaryDiffEqDefault/src/default_alg.jl
const LOW_TOL = 1e-6;
const SMALLSIZE = 50;
const MEDIUMSIZE = 500;
/** DefaultSolverChoice, numbered from 0 here (1 there). */
export const DEFAULT_CHOICES = ['Tsit5', 'Vern7', 'Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF'];
const TSIT5 = 0;
const VERN7 = 1;
const ROSENBROCK23 = 2;
const RODAS5P = 3;
const FBDF_CHOICE = 4;
const KRYLOV_FBDF = 5;
// alg_stability_size of the two non-stiff methods.
const STABILITY_SIZES = [3.5068, 4.64];

function nonstiffchoice(reltol) {
  return reltol < LOW_TOL ? VERN7 : TSIT5;
}

function stiffchoice(reltol, len) {
  if (len > MEDIUMSIZE) return KRYLOV_FBDF;
  if (len > SMALLSIZE) return FBDF_CHOICE;
  return reltol < LOW_TOL ? RODAS5P : ROSENBROCK23;
}

/**
 * OrdinaryDiffEq's AutoSwitchCache: the verdict counter and the thresholds.
 * `count` runs positive for consecutive stiff verdicts and negative for
 * consecutive non-stiff ones.
 */
function switchState(o = {}) {
  return {
    count: 0,
    successiveSwitches: 0,
    isStiffAlg: !!o.stiffalgfirst,
    maxstiffstep: o.maxstiffstep ?? 10,
    maxnonstiffstep: o.maxnonstiffstep ?? 3,
    nonstifftol: o.nonstifftol ?? 9 / 10,
    stifftol: o.stifftol ?? 9 / 10,
    dtfac: o.dtfac ?? 2,
    stiffalgfirst: !!o.stiffalgfirst,
    switchMax: o.switchMax ?? 5,
    current: -1,              // none chosen yet (0 in Julia, which counts from 1)
  };
}

/**
 * is_stiff: the verdict on the last attempt, with its side effects on the
 * waiver of error checks -- default_alg.jl's version, whose S is always the
 * non-stiff method's own for the tolerance in force.
 */
function isStiff(integ, AS, stabilitySize) {
  const stiffness = Math.abs(integ.eigenEst * integ.dt / stabilitySize);
  const tol = AS.isStiffAlg ? AS.stifftol : AS.nonstifftol;
  // NaN-safe as OrdinaryDiffEq writes it: a NaN estimate counts as stiff.
  const stiff = !(stiffness <= tol);
  if (!stiff) AS.successiveSwitches++;
  else AS.successiveSwitches = 0;
  integ.doErrorCheck = (AS.successiveSwitches > AS.switchMax || !stiff) || AS.isStiffAlg;
  return stiff;
}

/** Count a verdict into AS.count, Julia's way round. */
function countVerdict(AS, stiff) {
  if (stiff) AS.count = AS.count < 0 ? 1 : AS.count + 1;
  else AS.count = AS.count > 0 ? -1 : AS.count - 1;
}

/** default_autoswitch: which of the six the next step is taken with. */
function defaultAutoswitch(AS, integ) {
  const len = integ.n;
  const reltol = integ.reltol;
  if (AS.current < 0) {
    AS.current = AS.stiffalgfirst ? stiffchoice(reltol, len) : nonstiffchoice(reltol);
    return AS.current;
  }
  const dt = integ.dt;
  countVerdict(AS, isStiff(integ, AS, STABILITY_SIZES[nonstiffchoice(reltol)]));
  if (!AS.isStiffAlg && AS.count > AS.maxstiffstep) {
    integ.dt = dt * AS.dtfac;
    AS.isStiffAlg = true;
    AS.current = stiffchoice(reltol, len);
  } else if (AS.isStiffAlg && AS.count < -AS.maxnonstiffstep) {
    integ.dt = dt / AS.dtfac;
    AS.isStiffAlg = false;
    AS.current = nonstiffchoice(reltol);
  }
  return AS.current;
}

/**
 * The generic AutoSwitch of two methods, (nonstiff, stiff) at indices 0 and
 * 1: OrdinaryDiffEqCore's AutoSwitchCache call, used by AutoAlgSwitch.
 */
function genericAutoswitch(AS, integ, cache) {
  if (AS.current < 0) {
    AS.current = AS.stiffalgfirst ? 1 : 0;
    return AS.current;
  }
  const dt = integ.dt;
  countVerdict(AS, isStiff(integ, AS, cache.stabilitySizeOf(0)));
  if (!AS.isStiffAlg && AS.count > AS.maxstiffstep) {
    integ.dt = dt * AS.dtfac;
    AS.isStiffAlg = true;
  } else if (AS.isStiffAlg && AS.count < -AS.maxnonstiffstep) {
    integ.dt = dt / AS.dtfac;
    AS.isStiffAlg = false;
  }
  AS.current = AS.isStiffAlg ? 1 : 0;
  return AS.current;
}

/**
 * The cache of a composite method: the methods' own caches, made the first
 * time each is chosen (as DefaultCache makes them), and a controller for each.
 * To the integrator it is one method, whichever is in charge.
 */
class CompositeCache {
  constructor(n, integ, opts, spec) {
    this.n = n;
    this.opts = opts;
    this.algs = spec.algs;
    this.chooseFn = spec.choose;
    this.state = switchState(spec.options);
    this.caches = new Array(this.algs.length).fill(null);
    this.controllers = new Array(this.algs.length).fill(null);
    this.current = -1;
    this.sub = null;
    this.stepsBy = new Array(this.algs.length).fill(0);
    this.attemptsBy = new Array(this.algs.length).fill(0);
    this.switchLog = [];
    this.nswitches = 0;
    this.fsalStep = -1;
    integ.stillIsStiff = !!spec.options?.stillIsStiff;
    this.skipNext = false;
    // (info) => void, after every verdict: for tests and for looking.
    this.trace = typeof spec.options?.trace === 'function' ? spec.options.trace : null;
  }

  stabilitySizeOf(i) {
    const s = this.algs[i].stabilitySize;
    if (!(s > 0)) throw new Error(`${this.algs[i].name} has no stability size to test stiffness against`);
    return s;
  }

  /** Make method i's cache and controller, if it has none yet. */
  ensure(i, integ) {
    if (!this.caches[i]) {
      const alg = this.algs[i];
      const cache = alg.build(this.n, integ, this.opts);
      this.caches[i] = cache;
      this.controllers[i] = new PIController({
        order: cache.errorOrder ?? cache.order,
        ...(alg.controller || {}),
      });
      cache.compositeFresh = true;
    }
    return this.caches[i];
  }

  /**
   * Put method i in charge: its controller becomes the integrator's, and it
   * is started as OrdinaryDiffEq's initialize! starts a method switched to --
   * its own init the first time, and after that whatever restart it has
   * (FBDF's history begins again at order 1; the one-step methods have none).
   */
  activate(i, integ) {
    const cache = this.ensure(i, integ);
    this.current = i;
    this.sub = cache;
    integ.controller = this.controllers[i];
    if (cache.compositeFresh) {
      cache.compositeFresh = false;
      if (cache.init) cache.init(integ);
      if (integ.t !== integ.prob.tspan[0] && cache.restart) cache.restart(integ);
    } else if (cache.restart) {
      cache.restart(integ);
    }
  }

  init(integ) {
    this.activate(this.chooseFn(this.state, integ, this), integ);
  }

  /** choose_algorithm!, at the top of every pass of the integrator's loop. */
  choose(integ) {
    const dtBefore = integ.dt;
    // No verdict on an FBDF attempt the error test turned down: inside
    // OrdinaryDiffEq's composite no such attempt exists (its BDF controller
    // never rejects there -- see the header), so its switch never counts one.
    // Counted, each rejection after a switch was a "not stiff" at a step
    // shrunk tenfold, and four of them sent the run back to Tsit5 before
    // FBDF had taken a step.
    if (this.skipNext) {
      this.skipNext = false;
      return;
    }
    const next = this.chooseFn(this.state, integ, this);
    if (this.trace) {
      this.trace({
        t: integ.t, dt: dtBefore, eigenEst: integ.eigenEst, count: this.state.count,
        from: this.algs[this.current].name, to: this.algs[next].name, nsteps: integ.nsteps,
        njacs: integ._jacCache ? integ._jacCache.njac : 0, EEst: integ.EEst,
      });
    }
    if (next === this.current) return;
    const from = this.current;
    this.activate(next, integ);
    this.nswitches++;
    if (this.switchLog.length < 1000) {
      this.switchLog.push({ t: integ.t, from: this.algs[from].name, to: this.algs[next].name });
    }
  }

  // --- the integrator's interface, delegated to the method in charge ---------

  get order() { return this.sub.order; }
  get explicit() { return !!this.sub.explicit; }
  get errorOrder() { return this.sub.errorOrder; }
  get hasFsalLast() { return !!this.sub.hasFsalLast; }
  get refreshFsalOnClamp() { return !!this.sub.refreshFsalOnClamp; }
  get dtpropose() { return this.sub ? this.sub.dtpropose ?? null : null; }
  set dtpropose(v) { if (this.sub) this.sub.dtpropose = v; }

  step(integ) {
    this.attemptsBy[this.current]++;
    return this.sub.step(integ);
  }

  accepted(integ, dtjust) {
    this.stepsBy[this.current]++;
    if (this.sub.accepted) this.sub.accepted(integ, dtjust);
  }

  rejected(integ) {
    if (this.sub.family === 'fbdf') this.skipNext = true;
    return this.sub.rejected ? this.sub.rejected(integ) === true : false;
  }

  restart(integ) {
    if (this.sub.restart) this.sub.restart(integ);
  }

  interpolate(integ, theta, out) {
    if (this.sub.interpolate) return this.sub.interpolate(integ, theta, out);
    // A method without an interpolant of its own is read by the cubic
    // Hermite, which needs f at the step's end; the integrator only takes it
    // for a cache with neither, so it is taken here, once a step.
    if (!this.sub.hasFsalLast && this.fsalStep !== integ.nsteps) {
      integ.f(integ.t + integ.dt, integ.u, integ.fsallast);
      this.fsalStep = integ.nsteps;
    }
    return hermite(theta, integ.dt, integ.uprev, integ.u, integ.fsalfirst, integ.fsallast, out);
  }

  get krylovSolves() {
    let s = 0;
    for (const c of this.caches) if (c && c.krylovSolves) s += c.krylovSolves;
    return s;
  }

  krylovReport() {
    const out = {};
    for (const c of this.caches) if (c && c.krylovReport) Object.assign(out, c.krylovReport());
    return out;
  }

  /** What the run did, for its statistics. */
  report() {
    const stepsBy = {};
    this.algs.forEach((a, i) => { if (this.caches[i]) stepsBy[a.name] = this.stepsBy[i]; });
    return {
      algorithms: this.algs.map((a) => a.name),
      stepsBy,
      switches: this.nswitches,
      switchLog: this.switchLog.slice(),
      lastAlg: this.algs[this.current].name,
    };
  }
}

/**
 * A composite method from a list of methods and a choice function, as
 * OrdinaryDiffEqCore's CompositeAlgorithm.
 */
function compositeAlgorithm(name, algs, choose, options = {}) {
  return {
    name,
    composite: true,
    algs,
    // OrdinaryDiffEq's starting step for whichever method is chosen first.
    initdt: 'sciml',
    order: Math.max(...algs.map((a) => a.order || 1)),
    build: (n, integ, opts) => new CompositeCache(n, integ, opts, { algs, choose, options }),
  };
}

/**
 * DefaultODEAlgorithm: DifferentialEquations.jl's automatic choice.
 *
 * @param {object} [options]
 * @param {boolean} [options.stiffalgfirst=false]  start on the stiff side
 * @param {boolean} [options.stillIsStiff=false]   read a state at rest as Julia
 *        does (the estimate becomes NaN, which counts as stiff); see
 *        explicitStiffness in ./tsit5.js
 * @param {number}  [options.maxstiffstep=10], [options.maxnonstiffstep=3],
 *        [options.nonstifftol=0.9], [options.stifftol=0.9], [options.dtfac=2]
 *        AutoSwitch's thresholds
 * @param {object}  [options.stiff]  options for the stiff methods (maxOrder
 *        and minOrder for the two FBDFs), as kwargs... are there
 */
export function DefaultODEAlgorithm(options = {}) {
  // The stiff methods as OrdinaryDiffEq has them, with one exception: FBDF
  // predicts its first step after a switch by an Euler step, as this
  // package's FBDF does after any restart, not from the last value as
  // OrdinaryDiffEq's does. Inside OrdinaryDiffEq's composite that first step
  // is never rejected however wrong (see the header), and the predictor
  // costs nothing; here the error test is kept, and with OrdinaryDiffEq's
  // predictor diffusion on 600 points at reltol 1e-6 took 26 516 steps and
  // 3147 switches (OrdinaryDiffEq: 87 and one; with this one, 88 and one).
  // `firstPredictor: 'julia'` takes OrdinaryDiffEq's. And Rodas5P with its PI
  // gains from its order, 5 -- the standalone port's come from its error
  // estimate's, 4, and are kept as they were checked.
  const stiff = { firstPredictor: options.firstPredictor ?? 'euler', ...(options.stiff || {}) };
  const algs = [
    Tsit5(), Vern7(),
    Rosenbrock23(),
    Rodas5P({ controller: { beta1: 7 / 50, beta2: 2 / 25, qmaxFirstStep: 10000 } }),
    FBDF(stiff), FBDF({ ...stiff, linsolve: 'gmres' }),
  ];
  return compositeAlgorithm('DefaultODEAlgorithm', algs, defaultAutoswitch, options);
}

/**
 * DefaultImplicitODEAlgorithm: the same, started on the stiff side and with
 * the stiffness tolerances OrdinaryDiffEqDefault gives it (stol = 0, ntol =
 * Inf).
 */
export function DefaultImplicitODEAlgorithm(options = {}) {
  const alg = DefaultODEAlgorithm({
    ...options, stiffalgfirst: true,
    stifftol: options.stol ?? 0, nonstifftol: options.ntol ?? Infinity,
  });
  alg.name = 'DefaultImplicitODEAlgorithm';
  return alg;
}

/**
 * AutoAlgSwitch(nonstiff, stiff): two methods and the generic switch between
 * them -- AutoTsit5(Rosenbrock23()) and its kind. The non-stiff method must
 * know the width of its stability region (`stabilitySize`).
 */
export function AutoAlgSwitch(nonstiff, stiff, options = {}) {
  return compositeAlgorithm(`AutoSwitch(${nonstiff.name}, ${stiff.name})`, [nonstiff, stiff],
    genericAutoswitch, options);
}
