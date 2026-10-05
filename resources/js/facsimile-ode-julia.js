/* ==========================================================================
   FACSIMILE.HTML AND RTM.HTML: THE ode_julia SOLVERS

   The solvers ported from DifferentialEquations.jl, offered beside the pages'
   own NDF -- the same ones Kompartment offers, under the same names:

     the stiff ones     FBDF (factorising, or with its Newton iterations
                        solved by GMRES), QNDF, Rodas5P, Rosenbrock23,
                        KenCarp4, TRBDF2 and RadauIIA5
     the explicit ones  Tsit5 and Vern7
     the switching one  DefaultODEAlgorithm, what DifferentialEquations.jl
                        runs when it is given no method: explicit until the
                        run turns stiff, then a stiff method, and back

   and `auto`, Kompartment's fast form of the last: the same explicit start
   and the same test for stiffness, with the page's own NDF taking the rest of
   the run from where it turns stiff. The package is in
   resources/js/ode/julia/ and knows nothing about these pages; this file is
   the adapter, and it is thin on purpose.

   WHY THEY ARE WORTH HAVING HERE. The built-in solver is one method with one
   set of compromises. These models are stiff chemical systems with an
   analytic sparse Jacobian and switches in them, which is exactly the ground
   these methods were designed for, and they disagree in useful ways:

     FBDF        multistep, variable order, and the cheapest per step on a
                 large system because it reuses one factorisation across many
                 steps. By GMRES it forms no matrix at all.
     QNDF        the same numerical differentiation formulas as the pages'
                 own NDF: the same kappa, the same backward differences,
                 written by other people. The most direct check there is of
                 the built-in solver. With the BDF formulas switch it is
                 QBDF, every kappa zero: the plain variable-step BDF,
                 slightly more stable and slightly less accurate per step,
                 and a control on what the kappa terms buy -- as the switch
                 is on the pages' own NDF.
     Rodas5P     no nonlinear iteration at all, so nothing to fail to converge.
                 The one to try when a run will not get past something.
     Rosenbrock23  the method of the pages' own Rosenbrock 2-3, run as
                 DifferentialEquations.jl runs it.
     RadauIIA5   the most accurate per step, and the least troubled by
                 stiffness; the one to believe when two others disagree.
     KenCarp4    a middle course, and cheap at moderate tolerances.
     TRBDF2      second order and L-stable. Fast at loose tolerances; see the
                 note in the package README before trusting it at tight ones.
     Tsit5, Vern7  explicit pairs of orders 5 and 7: no Jacobian and no
                 matrix, and on a stiff model a step held at the edge of
                 their stability.

   Nothing is downloaded: this is JavaScript, and it runs offline exactly as
   the pages' own solver does.

   THE CONTRACT. facsimile-solver.js calls a solver as

       solver(f, t0, tfinal, y0, opts) -> { t, y, stopped, stats }

   and drives the events, the restarts, the point store and the progress
   itself. So each of these is wrapped to stop at the first event and hand
   back where it stopped, exactly as the pages' own solver does. A run is a
   segment per event, and `opts.carry` is one object for all of them: the
   switching solvers keep there what they were on, so that a restart does not
   send a run that has turned stiff back to its explicit start.
   ========================================================================== */
(function (root, factory) {
  const api = factory(
    root.OdeJulia || (typeof require === 'function' ? require('./ode-julia.js') : null),
    root.FacsimileODE || (typeof require === 'function' ? require('./facsimile-solver.js') : null),
  );
  root.FacsimileOdeJulia = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function (OJ, FODE) {
  'use strict';

  /**
   * Page id -> how to build the algorithm. `bdf` is what it is called, and
   * how it is built, with the BDF formulas switch on: QNDF with every kappa
   * zero is the package's QBDF. `carry` is the run's own object (see the
   * header), for the switching solver.
   */
  const METHODS = Object.freeze({
    // The explicit start, then the page's NDF: see autoSolver below.
    auto: { label: 'Auto', quick: true },
    julia_auto: {
      label: 'DefaultODEAlgorithm', ownGrid: true,
      make: (o, carry) => OJ.DefaultODEAlgorithm({ stiffalgfirst: !!carry && carry.stiff === true }),
    },
    julia_fbdf: { label: 'FBDF', make: (o) => OJ.FBDF(o) },
    julia_fbdf_krylov: { label: 'FBDF by GMRES', make: (o) => OJ.FBDF({ ...o, linsolve: 'gmres' }) },
    julia_qndf: {
      label: 'QNDF', make: (o) => OJ.QNDF(o),
      bdf: { label: 'QBDF', make: (o) => OJ.QBDF(o) },
    },
    julia_rodas5p: { label: 'Rodas5P', make: () => OJ.Rodas5P() },
    julia_rosenbrock23: { label: 'Rosenbrock23', make: () => OJ.Rosenbrock23() },
    julia_radau5: { label: 'RadauIIA5', make: () => OJ.RadauIIA5() },
    julia_kencarp4: { label: 'KenCarp4', make: () => OJ.KenCarp4() },
    julia_trbdf2: { label: 'TRBDF2', make: () => OJ.TRBDF2() },
    julia_tsit5: { label: 'Tsit5', make: () => OJ.Tsit5(), explicit: true, ownGrid: true },
    julia_vern7: { label: 'Vern7', make: () => OJ.Vern7(), explicit: true, ownGrid: true },
  });

  const is = (id) => Object.prototype.hasOwnProperty.call(METHODS, id);

  /**
   * Which of the pages' solver settings each of these actually reads.
   *
   * Declared here, beside the code that passes them on, because that is the
   * only place the answer can be kept honest. A setting shown for a method
   * that ignores it is worse than no setting: it is a knob that does nothing,
   * and the reader has no way to tell. The groups are Kompartment's
   * (SOLVER_OPTIONS in kompartment/src/ode/solvers.js), in these pages' names.
   *
   *   maxOrder  only the variable-order multistep methods have an order to cap.
   *   norm      RadauIIA5 measures its error against Hairer's own transformed
   *             tolerances in a fixed norm, and does not read this one.
   */
  // `central` is not here: the page differences its own Jacobian and hands it
  // over, so this package never differences one and the option could not do
  // anything. A knob that does nothing is worse than a missing one.
  const COMMON = ['rtol', 'atol', 'atolSpecies', 'norm', 'hmax', 'h0', 'matrix', 'jacobian',
    'maxJacAge', 'maxSteps', 'belowTolRun', 'autoAtol', 'clamp', 'nonNegative'];
  // Newton: every one of these but the Rosenbrocks, which are linearly
  // implicit and have no nonlinear iteration to converge.
  const NEWTON = [...COMMON, 'kappa'];
  const ORDER = ['maxOrder', 'minOrder'];
  // An explicit method forms no matrix and has no Jacobian to choose.
  const EXPLICIT = COMMON.filter((k) => !['matrix', 'jacobian', 'maxJacAge'].includes(k));
  // GMRES forms no matrix either, and its Newton iteration is the FBDF's.
  const MATRIX_FREE = [...EXPLICIT, 'kappa'];
  // A Rosenbrock method re-forms the Jacobian at every step by definition --
  // a stale one changes its order, not just its speed -- so there is no age
  // to set, and no Newton iteration to give a tolerance to.
  const ROSENBROCK = COMMON.filter((k) => k !== 'maxJacAge');
  const OPTIONS = Object.freeze({
    // The explicit methods and then the NDF, which reads everything they do.
    auto: FODE ? FODE.options('ndf') : null,
    // Everything any of its methods reads: DefaultODEAlgorithm hands its
    // keyword arguments on to the stiff method it switches to.
    julia_auto: [...NEWTON, ...ORDER],
    julia_fbdf: [...NEWTON, ...ORDER],
    julia_fbdf_krylov: [...MATRIX_FREE, ...ORDER],
    julia_qndf: ['bdf', ...NEWTON, ...ORDER],
    julia_kencarp4: [...NEWTON, 'smoothEst'],
    julia_trbdf2: [...NEWTON, 'smoothEst'],
    julia_rodas5p: ROSENBROCK,
    julia_rosenbrock23: ROSENBROCK,
    julia_radau5: [...NEWTON.filter((k) => k !== 'norm'), 'smoothEst'],
    julia_tsit5: EXPLICIT,
    julia_vern7: EXPLICIT,
  });

  /** The settings `id` reads, or null if it is not one of these. */
  const options = (id) => (OPTIONS[id] ? OPTIONS[id].slice() : null);

  /**
   * Settings these read, but not in the way the built-in solver does.
   *
   * Keeping a species non-negative is three things at once: the derivative is
   * damped so that a component already at or below zero cannot be pushed
   * further down, the size of any violation is folded into the error test, and
   * an accepted step is projected back. The NDF here does all three, with its
   * BDF formulas or without. These do the last one only. That is enough to
   * keep the Jacobian on the physical side, which is what it is mostly for,
   * but it is not the same thing and saying "yes" to the same checkbox
   * without saying so would be a small lie.
   */
  const PARTIAL = Object.freeze({
    nonNegative: 'by projecting each accepted step back to zero, without the damped '
      + 'derivative and the error-test term that the NDF adds',
  });
  const AUTO_PARTIAL = Object.freeze({
    nonNegative: 'as the NDF does once the run has turned stiff, and while it is explicit by '
      + 'projecting each accepted step back to zero only',
  });

  /** Remarks on settings `id` reads only partly. */
  const notes = (id) => (id === 'auto' ? { ...AUTO_PARTIAL } : OPTIONS[id] ? { ...PARTIAL } : null);

  /**
   * Turn the page's Jacobian object into one ode_julia can fill.
   *
   * The page's compiler hands over `evaluate(t, y)` returning the values in
   * compressed-column order over a fixed pattern, or null where an exact
   * derivative is infinite. Null means "keep the last matrix", which is what a
   * stiff solver does with a Jacobian it has not re-formed anyway.
   */
  function bridgeJacobian(jac, neq) {
    if (!jac || typeof jac.evaluate !== 'function' || !jac.pattern) return null;
    const { colPtr, rowIdx } = jac.pattern;
    return {
      jacPattern: { colPtr, rowIdx },
      jac(t, y, J) {
        const values = jac.evaluate(t, y);
        if (!values) return;
        if (J.values) { J.values.set(values); return; }
        // A dense target: scatter the compressed columns into it.
        J.data.fill(0);
        for (let j = 0; j < neq; j++) {
          for (let k = colPtr[j]; k < colPtr[j + 1]; k++) J.data[j * neq + rowIdx[k]] = values[k];
        }
      },
    };
  }

  /** The problem, with the page's Jacobian and its events, the same for every method. */
  function problemOf(f, t0, tfinal, y0, opts) {
    const bridged = bridgeJacobian(opts.jacobian, y0.length);
    const events = opts.events || null;
    return new OJ.ODEProblem(
      (t, u, du) => f(t, u, du), y0, [t0, tfinal],
      {
        jac: bridged ? bridged.jac : null,
        jacPattern: bridged ? bridged.jacPattern : null,
        // Terminal, which is what this page's driver expects to be handed
        // back, and with each event's own direction and the driver's mask of
        // those still switched on. This passed `direction: 1` and no mask,
        // so a downward event was looked for as an upward one and an event
        // marked `once` fired again at every later crossing.
        events: events
          ? {
            n: events.n,
            fun: events.fun,
            direction: events.direction ?? 1,
            enabled: events.enabled ?? null,
            terminal: true,
          }
          : null,
      },
    );
  }

  /**
   * The solve settings every method is handed, under the package's names.
   * `aborted` is set when the page's progress callback says to stop.
   */
  function settingsOf(opts, state) {
    const settings = {
      reltol: opts.rtol == null ? 1e-3 : opts.rtol,
      abstol: opts.atol == null ? 1e-6 : opts.atol,
      norm: opts.norm === 'max' ? 'max' : 'rms',
      matrix: opts.matrix || 'auto',
      nonNegative: opts.nonNegative || null,
      dtmax: opts.hmax && opts.hmax > 0 ? opts.hmax : Infinity,
      maxiters: opts.maxSteps || 1e7,
      kappa: opts.kappa,
      maxJacAge: opts.maxJacAge,
      belowTolRun: opts.belowTolRun,
      autoAbstol: !!opts.autoAtol,
      smoothEst: opts.smoothEst !== false,
      // The page keeps the points and thins them; this must not keep a
      // second copy of a run that can reach hundreds of thousands of steps.
      saveEverystep: false,
      onAccepted: opts.onAccepted || null,
      progress: opts.onStep ? (t, nsteps) => {
        if (opts.onStep(t, nsteps) === false) { state.aborted = true; return false; }
        return true;
      } : null,
      progressEvery: 16,
    };
    // The first step, where the page sets one. Only then: the package merges
    // what it is handed over its own defaults, so a key present and
    // undefined would replace them.
    if (opts.h0 > 0) settings.dt = opts.h0;
    return settings;
  }

  /**
   * The model's output times inside a segment, read off the method's own
   * interpolant and handed to the driver as they are passed: what an explicit
   * method of high order does with them, its steps being long. True when the
   * driver took the offer.
   */
  function ownGridOf(settings, opts, t0, tfinal) {
    if (!opts.gridTimes || !opts.ownGrid) return false;
    const dir = Math.sign(tfinal - t0);
    const inside = Array.prototype.filter.call(opts.gridTimes, (tq) => dir * (tq - t0) > 0 && dir * (tfinal - tq) >= 0);
    if (!inside.length || !opts.ownGrid(true)) return false;
    settings.saveat = Float64Array.from(inside);
    settings.onOutput = (tq, u) => opts.onGrid(tq, u);
    return true;
  }

  /** What the page's driver is handed back: where the solve ended, and what it cost. */
  function resultOf(sol, label, saved) {
    const ev = sol.events.length ? sol.events[sol.events.length - 1] : null;
    const yEnd = sol.final;
    const s = sol.stats;
    const stats = {
      nsteps: s.naccept,
      nfailed: s.nreject,
      nfevals: s.nf,
      npds: s.njacs,
      ndecomps: s.nw,
      nsolves: s.nsolve,
      nbelowtol: s.nbelowtol || 0,
      negative: 0,
      sparse: s.sparse,
      fill: s.fill,
      ordering: s.ordering,
      solver: label,
    };
    // The switching solver's account: the steps each of its methods took, and
    // how often it changed between them.
    if (s.stepsBy) { stats.stepsBy = { ...s.stepsBy }; stats.switches = s.switches || 0; }
    if (s.krylovIters != null) stats.krylovIters = s.krylovIters;
    return {
      // With rows at the output times only, the last of them is not the end.
      t: ev ? ev.t : saved ? s.t : sol.t[sol.t.length - 1],
      y: yEnd,
      stopped: ev ? { t: ev.t, y: yEnd, which: ev.all ?? [ev.which] } : null,
      stats,
    };
  }

  /**
   * A run that did not finish, as the error the page shows. An explicit
   * method that ran out of steps has almost always met stiffness, which it
   * grinds through at the edge of its stability rather than fails at, and
   * that is worth saying -- as Kompartment's runner does.
   */
  function failure(sol, label, tfinal, explicit) {
    const stiff = explicit && sol.retcode === 'MaxIters'
      ? ' The model looks stiff: an explicit method’s step is held at the edge of its stability. '
        + 'Use the NDF, or Auto, which finds that out for itself.'
      : '';
    const err = new Error(`${label} stopped at t = ${sol.stats.t} of ${tfinal}: ${sol.message}${stiff ? `.${stiff}` : ''}`);
    err.code = sol.retcode;
    return err;
  }

  /**
   * One of the methods, wrapped to the page's solver contract.
   * @param {string} id
   */
  function solver(id) {
    if (id === 'auto') return autoSolver();
    const method = METHODS[id];
    if (!method) throw new Error(`'${id}' is not one of the ode_julia solvers`);

    const solveOne = function solveOne(f, t0, tfinal, y0, opts = {}) {
      if (!OJ) throw new Error('ode_julia is not loaded');
      // The BDF formulas switch, on the one method that has it; ignored by
      // the rest, which do not offer it.
      const entry = opts.bdf && method.bdf ? method.bdf : method;
      if (!(Math.abs(tfinal - t0) > 0)) throw new Error('The start and end times are equal');
      const carry = id === 'julia_auto' ? opts.carry || null : null;

      const state = { aborted: false };
      const settings = settingsOf(opts, state);
      const saved = !!method.ownGrid && ownGridOf(settings, opts, t0, tfinal);
      const sol = OJ.solve(problemOf(f, t0, tfinal, y0, opts), entry.make({
        maxOrder: opts.maxOrder,
        minOrder: opts.minOrder,
        smoothEst: opts.smoothEst !== false,
      }, carry), settings);
      // DefaultODEAlgorithm goes on with the method a segment ended on, as
      // DifferentialEquations.jl's does across a callback.
      if (carry && sol.stats.lastAlg) carry.stiff = STIFF_METHODS.has(sol.stats.lastAlg);

      if (state.aborted) throw new Error('Aborted');
      if (sol.retcode !== 'Success' && sol.retcode !== 'Terminated') throw failure(sol, entry.label, tfinal, !!method.explicit);
      return resultOf(sol, entry.label, saved);
    };
    solveOne.label = method.label;
    return solveOne;
  }

  /** The switching solver's stiff methods, by the names its statistics give them. */
  const STIFF_METHODS = new Set(['Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF']);

  /*
    `auto`: Kompartment's switching solver (kompartment/src/ode/julia-solvers.js),
    with these pages' NDF in place of its.

    DefaultODEAlgorithm's start and test for stiffness, with every stiff method
    handed off: where the run would turn to one, the explicit method stops and
    the NDF takes the rest of the segment, and every later segment of the run
    from its start. Measured in Kompartment over a few states to fifty
    thousand, that was the fastest of the ways to switch at every size: its
    Rosenbrock and FBDF can switch back and forth for most of a run, and above
    500 states DifferentialEquations.jl's FBDF by GMRES costs many times the
    NDF's time. What it gives up is the switch back.

    Two things the explicit start needs, neither of them
    DifferentialEquations.jl's: it runs at a tenth of the tolerances, since its
    error test is on the end of each step and what lies between is read off an
    interpolant nothing tests -- at a loose tolerance one long step across a
    change of slope the model does not declare was right at both ends and a
    factor of two out between -- and it lands on every corner of the tables the
    model reads at the clock. A segment whose tables turn more than MAX_CORNERS
    times is the NDF's from the start: landing on each costs a step.

    A model with algebraic variables is the NDF's throughout: the explicit
    methods take no mass matrix.
  */
  const EXPLICIT_TOLERANCE = 0.1;
  const MAX_CORNERS = 100;
  const HANDED_OFF = ['Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF'];

  /** A tolerance, scalar or per state, times k. */
  function scaled(tol, k) {
    return typeof tol === 'number' ? tol * k : Float64Array.from(tol, (v) => v * k);
  }

  /** The NDF's statistics, as `auto`'s, with the steps put down to it. */
  function asAuto(stats, name, before) {
    const b = before || { nsteps: 0, nfailed: 0, nfevals: 0, npds: 0, ndecomps: 0, nsolves: 0, nbelowtol: 0, stepsBy: {}, switches: 0 };
    return {
      ...stats,
      nsteps: b.nsteps + stats.nsteps,
      nfailed: b.nfailed + stats.nfailed,
      nfevals: b.nfevals + stats.nfevals,
      npds: b.npds + stats.npds,
      ndecomps: b.ndecomps + stats.ndecomps,
      nsolves: b.nsolves + stats.nsolves,
      nbelowtol: b.nbelowtol + (stats.nbelowtol || 0),
      stepsBy: { ...b.stepsBy, [name]: stats.nsteps },
      switches: b.switches + (before ? 1 : 0),
      solver: 'Auto',
    };
  }

  function autoSolver() {
    const solveAuto = function solveAuto(f, t0, tfinal, y0, opts = {}) {
      if (!OJ) throw new Error('ode_julia is not loaded');
      if (!FODE) throw new Error('facsimile-solver.js is not loaded');
      if (!(Math.abs(tfinal - t0) > 0)) throw new Error('The start and end times are equal');
      const carry = opts.carry || null;
      const ndfName = opts.bdf ? 'BDF' : 'NDF';
      const algebraic = !!opts.mass && Array.prototype.some.call(opts.mass, (m) => !m);
      const corners = algebraic || (carry && carry.ndf) || !opts.tableCorners
        ? [] : opts.tableCorners(t0, tfinal, MAX_CORNERS);
      if (algebraic || (carry && carry.ndf) || corners === null) {
        if (carry) carry.ndf = true;
        const r = FODE.ndf(f, t0, tfinal, y0, opts);
        return { ...r, stats: asAuto(r.stats, ndfName, null) };
      }

      const state = { aborted: false };
      const settings = settingsOf(opts, state);
      settings.reltol *= EXPLICIT_TOLERANCE;
      settings.abstol = scaled(settings.abstol, EXPLICIT_TOLERANCE);
      if (corners.length) settings.tstops = corners;
      // The explicit start reads the output times off its own interpolant.
      const saved = ownGridOf(settings, opts, t0, tfinal);
      const sol = OJ.solve(problemOf(f, t0, tfinal, y0, opts), OJ.DefaultODEAlgorithm({ handOff: HANDED_OFF }), settings);
      if (state.aborted) throw new Error('Aborted');
      if (sol.retcode !== 'Success' && sol.retcode !== 'Terminated' && sol.retcode !== 'HandedOff') {
        throw failure(sol, 'Auto', tfinal);
      }
      const explicit = resultOf(sol, 'Auto', saved);
      if (sol.retcode !== 'HandedOff') return explicit;

      // Turned stiff: the NDF from here, and in every later segment of the
      // run. Its rows at the output times are the driver's again, from the
      // last step the explicit method took.
      if (carry) carry.ndf = true;
      if (saved) opts.ownGrid(false);
      const t1 = sol.handOff.t;
      const sub = { ...opts };
      if (t1 !== t0) {
        // A first step and an event resting on zero belong to the start of
        // the segment, not to the middle of it.
        delete sub.h0;
        delete sub.tStart;
      }
      if (opts.maxSteps > 0) sub.maxSteps = Math.max(1, opts.maxSteps - explicit.stats.nsteps - explicit.stats.nfailed);
      if (opts.onStep) sub.onStep = (t, n) => opts.onStep(t, n + explicit.stats.nsteps);
      const r = FODE.ndf(f, t1, tfinal, sol.handOff.u, sub);
      return { ...r, stats: asAuto(r.stats, ndfName, explicit.stats) };
    };
    solveAuto.label = 'Auto';
    // A model with algebraic variables goes to the NDF, which takes the mass matrix.
    solveAuto.takesMass = true;
    return solveAuto;
  }

  /** What the method menu should call each of these. */
  function label(id) { return METHODS[id] ? METHODS[id].label : id; }

  /**
   * Whether a method is quick enough to run on the page itself, with no
   * worker: `auto`, whose stiff part is the NDF's. The rest can run for
   * minutes on a stiff model, which on the page's own thread is a frozen tab.
   */
  function quick(id) { return !!(METHODS[id] && METHODS[id].quick); }

  return { METHODS, is, solver, label, options, notes, quick, EXPLICIT_TOLERANCE, MAX_CORNERS };
}));
