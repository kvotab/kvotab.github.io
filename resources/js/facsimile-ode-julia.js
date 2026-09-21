/* ==========================================================================
   FACSIMILE.HTML: THE ode_julia SOLVERS

   Seven stiff solvers ported from DifferentialEquations.jl -- FBDF, QNDF,
   QBDF, Rodas5P, KenCarp4, TRBDF2 and RadauIIA5 -- offered here beside the
   page's own NDF and BDF. The package is in resources/js/ode_julia/ and knows nothing about
   this page; this file is the adapter, and it is thin on purpose.

   WHY THEY ARE WORTH HAVING HERE. The built-in solver is one method with one set of
   compromises. This model is a stiff chemical system with an analytic sparse
   Jacobian and a switch in it, which is exactly the ground these methods were
   designed for, and they disagree in useful ways:

     FBDF        multistep, variable order, and the cheapest per step on a
                 large system because it reuses one factorisation across many
                 steps.
     QNDF        the same numerical differentiation formulas as this page's
                 own NDF: the same kappa, the same backward differences,
                 written by other people. The most direct check there is of
                 the built-in solver.
     QBDF        QNDF with every kappa set to zero, which is the plain
                 variable-step BDF. Slightly more stable and slightly less
                 accurate per step; a control on what the kappa terms buy.
     Rodas5P     no nonlinear iteration at all, so nothing to fail to converge.
                 The one to try when a run will not get past something.
     RadauIIA5   the most accurate per step, and the least troubled by
                 stiffness; the one to believe when two others disagree.
     KenCarp4    a middle course, and cheap at moderate tolerances.
     TRBDF2      second order and L-stable. Fast at loose tolerances; see the
                 note in the package README before trusting it at tight ones.

   Nothing is downloaded: this is JavaScript, and it runs offline exactly as
   the page's own solver does.

   THE CONTRACT. facsimile-solver.js calls a solver as

       solver(f, t0, tfinal, y0, opts) -> { t, y, stopped, stats }

   and drives the events, the restarts, the point store and the progress
   itself. So each of these is wrapped to stop at the first event and hand
   back where it stopped, exactly as the page's own solver does.
   ========================================================================== */
(function (root, factory) {
  const api = factory(root.OdeJulia || (typeof require === 'function' ? require('./ode-julia.js') : null));
  root.FacsimileOdeJulia = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function (OJ) {
  'use strict';

  /** Page id -> how to build the algorithm. */
  const METHODS = Object.freeze({
    julia_fbdf: { label: 'FBDF', make: (o) => OJ.FBDF(o) },
    julia_qndf: { label: 'QNDF', make: (o) => OJ.QNDF(o) },
    julia_qbdf: { label: 'QBDF', make: (o) => OJ.QBDF(o) },
    julia_rodas5p: { label: 'Rodas5P', make: () => OJ.Rodas5P() },
    julia_radau5: { label: 'RadauIIA5', make: () => OJ.RadauIIA5() },
    julia_kencarp4: { label: 'KenCarp4', make: () => OJ.KenCarp4() },
    julia_trbdf2: { label: 'TRBDF2', make: () => OJ.TRBDF2() },
  });

  const is = (id) => Object.prototype.hasOwnProperty.call(METHODS, id);

  /**
   * Which of the page's solver settings each of these actually reads.
   *
   * Declared here, beside the code that passes them on, because that is the
   * only place the answer can be kept honest. A setting shown for a method
   * that ignores it is worse than no setting: it is a knob that does nothing,
   * and the reader has no way to tell.
   *
   *   maxOrder  only the variable-order multistep methods have an order to cap.
   *   norm      RadauIIA5 measures its error against Hairer's own transformed
   *             tolerances in a fixed norm, and does not read this one.
   */
  // `central` is not here: the page differences its own Jacobian and hands it
  // over, so this package never differences one and the option could not do
  // anything. A knob that does nothing is worse than a missing one.
  const COMMON = ['rtol', 'atol', 'atolSpecies', 'norm', 'hmax', 'matrix', 'jacobian',
    'maxJacAge', 'maxSteps', 'belowTolRun', 'autoAtol', 'clamp', 'nonNegative'];
  // Newton: every one of these but Rodas5P, which is linearly implicit and has
  // no nonlinear iteration to converge.
  const NEWTON = [...COMMON, 'kappa'];
  const ORDER = ['maxOrder', 'minOrder'];
  const OPTIONS = Object.freeze({
    julia_fbdf: [...NEWTON, ...ORDER],
    julia_qndf: [...NEWTON, ...ORDER],
    julia_qbdf: [...NEWTON, ...ORDER],
    julia_kencarp4: [...NEWTON, 'smoothEst'],
    julia_trbdf2: [...NEWTON, 'smoothEst'],
    // A Rosenbrock method re-forms the Jacobian at every step by definition --
    // a stale one changes its order, not just its speed -- so there is no age
    // to set, and no Newton iteration to give a tolerance to.
    julia_rodas5p: COMMON.filter((k) => k !== 'maxJacAge'),
    julia_radau5: [...NEWTON.filter((k) => k !== 'norm'), 'smoothEst'],
  });

  /** The settings `id` reads, or null if it is not one of these. */
  const options = (id) => (OPTIONS[id] ? OPTIONS[id].slice() : null);

  /**
   * Settings these read, but not in the way the built-in solver does.
   *
   * Keeping a species non-negative is three things at once: the derivative is
   * damped so that a component already at or below zero cannot be pushed
   * further down, the size of any violation is folded into the error test, and
   * an accepted step is projected back. NDF and BDF here do all three. These
   * do the last one
   * only. That is enough to keep the Jacobian on the physical side, which is
   * what it is mostly for, but it is not the same thing and saying "yes" to
   * the same checkbox without saying so would be a small lie.
   */
  const PARTIAL = Object.freeze({
    nonNegative: 'by projecting each accepted step back to zero, without the damped '
      + 'derivative and the error-test term that NDF and BDF add',
  });

  /** Remarks on settings `id` reads only partly. */
  const notes = (id) => (OPTIONS[id] ? { ...PARTIAL } : null);

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

  /**
   * One of the seven, wrapped to the page's solver contract.
   * @param {string} id
   */
  function solver(id) {
    const entry = METHODS[id];
    if (!entry) throw new Error(`'${id}' is not one of the ode_julia solvers`);

    return function solveOne(f, t0, tfinal, y0, opts = {}) {
      if (!OJ) throw new Error('ode_julia is not loaded');
      const neq = y0.length;
      if (!(Math.abs(tfinal - t0) > 0)) throw new Error('The start and end times are equal');

      const bridged = bridgeJacobian(opts.jacobian, neq);
      const events = opts.events || null;

      const problem = new OJ.ODEProblem(
        (t, u, du) => f(t, u, du), y0, [t0, tfinal],
        {
          jac: bridged ? bridged.jac : null,
          jacPattern: bridged ? bridged.jacPattern : null,
          // Terminal and upward-crossing, which is what this page's events are
          // and what its driver expects to be handed back.
          events: events ? { n: events.n, fun: events.fun, direction: 1, terminal: true } : null,
        },
      );

      let aborted = false;
      const sol = OJ.solve(problem, entry.make({
        maxOrder: opts.maxOrder,
        minOrder: opts.minOrder,
        smoothEst: opts.smoothEst !== false,
      }), {
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
          if (opts.onStep(t, nsteps) === false) { aborted = true; return false; }
          return true;
        } : null,
        progressEvery: 16,
      });

      if (aborted) throw new Error('Aborted');
      if (sol.retcode !== 'Success' && sol.retcode !== 'Terminated') {
        const err = new Error(`${entry.label} stopped at t = ${sol.stats.t} of ${tfinal}: ${sol.message}`);
        err.code = sol.retcode;
        throw err;
      }

      const ev = sol.events.length ? sol.events[sol.events.length - 1] : null;
      const yEnd = sol.final;
      const s = sol.stats;
      return {
        t: ev ? ev.t : sol.t[sol.t.length - 1],
        y: yEnd,
        stopped: ev ? { t: ev.t, y: yEnd, which: [ev.which] } : null,
        stats: {
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
          solver: entry.label,
        },
      };
    };
  }

  /** What the method menu should call each of these. */
  function label(id) { return METHODS[id] ? METHODS[id].label : id; }

  return { METHODS, is, solver, label, options, notes };
}));
