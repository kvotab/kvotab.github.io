/* ==========================================================================
   STIFF ODE/DAE SOLVER FOR facsimile.html AND rtm.html

   The integrator and its linear algebra are the shared solver core,
   resources/js/ode/core/ and solvers/ (loaded as ode-core.js, the global
   OdeCore): the variable-order NDF/BDF for M·dy/dt = f(t, y) with M a
   diagonal of ones and zeros, its iteration matrix M - h*J factorised by
   whichever of a sparse LU that keeps its pivots, a searching Gilbert-Peierls
   LU and a dense LU the measured fill says is cheapest, differenced Jacobians
   through the pattern, and event location. Kompartment runs the same
   modules.

   What is here is this page's side of it:

     ndf          the integrator in this page's calling convention, with this
                  page's settings: see below
     runModel     a compiled model over [0, tend], restarted at each terminal
                  event after applying it, with the output grid and the
                  bounded store of points
     consistentInitial, parseSpeciesTolerances, speciesAtol

   and, for the tests and the worker, the core's own pieces under the names
   this page has always used.

   Conventions: f(t, y, out) fills and returns `out` (Float64Array); the
   Jacobian object is { pattern: {n, nnz, colPtr, rowIdx}, evaluate(t, y) ->
   Float64Array | null }; results are { t, y } at the end of the run, with the
   accepted steps handed to `onAccepted` as they happen and, when `saveAt` is
   given, the solution at those times read off the interpolant.

   One global: FacsimileODE. Runs in a page, a Worker, or Node.
   ========================================================================== */
(function (root, factory) {
  const api = factory(root.OdeCore || (typeof require === 'function' ? require('./ode-core.js') : null));
  root.FacsimileODE = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : this, function (core) {
  'use strict';
  if (!core) throw new Error('facsimile-solver.js needs ode-core.js, the shared solver core, loaded before it');

  const {
    SolverError, CSC, cscFromTriplets, SparseLU, DenseLU, RefactorLU,
    makeIterationMatrix, colourColumns, differenceJacobian, reverseCuthillMcKee, crossingTolerance,
  } = core;

  /**
   * Earliest crossing in (tL, tR], or null, in this page's argument order:
   * `tStart` is where the segment began, and `en` the mask of events still
   * switched on (FACSIMILE's WHEN is switched off once it has fired).
   */
  function firstCrossing(valuesAt, tL, vL, tR, vR, dir, tStart, en) {
    return core.firstCrossing(valuesAt, tL, vL, tR, vR, dir, { tStart, enabled: en });
  }

  /**
   * The NDF/BDF of the shared core, with this page's settings.
   *
   * These differ from Kompartment's, and each is this page's measured choice:
   *
   *   scaling        on: the Newton system is solved in units of each
   *                  species' own weight. The species of the canister model
   *                  span forty orders of magnitude, and unscaled, the
   *                  pivoting is decided by the largest coefficients and the
   *                  corrections for the trace species come out wrong.
   *   minNewton 2    two Newton iterations a step unless the correction is
   *                  already below the floors, rather than one on the strength
   *                  of a contraction rate remembered from an earlier step
   *   belowTolRun 5  up to five failing steps at the smallest step size in a
   *                  row, of either kind, before the run stops
   *   stallWindow    4000 accepted steps, and maxSteps 2e6
   *   denseBelow 0, denseFill 0.35   when the dense LU is cheaper: measured
   *                  here, the kept-pivot LU is ahead from the smallest models
   *                  up, and the searching sparse LU loses past a third of n²
   *
   * @param {(t:number, y:Float64Array, out:Float64Array)=>Float64Array} f
   * @param {number} t0 @param {number} tfinal @param {Float64Array} y0
   * @param {object} opts
   *   rtol, atol (number|array), maxOrder (1-5), bdf (bool), hmax, h0, maxSteps,
   *   nonNegative (bool[] or null), mass (diagonal: 1 differential, 0 algebraic),
   *   suppressAlgebraic, norm ('max'|'rms'), scaling, minNewton, stagnationTol,
   *   belowTolRun, autoAtol,
   *   jacobian: {pattern, evaluate(t,y), groups} -- `evaluate` optional (differenced through the pattern),
   *   matrix: 'auto'|'refactor'|'sparse'|'dense',
   *   events: {n, direction:Int8Array, enabled?:Uint8Array, fun(t,y,out)} or null (all terminal),
   *   tStart (segment start for events), saveAt (ascending times to read the solution at),
   *   onAccepted(t, y), onStep(t, nsteps) -> false to abort, debug(info)
   * @returns {{t: number, y: Float64Array, stopped: object|null, series: object|null, stats: object}}
   */
  function ndf(f, t0, tfinal, y0, opts = {}) {
    const Jopt = opts.jacobian || null;
    if (!Jopt || !Jopt.pattern) throw new SolverError('jacobian', 'this solver needs a Jacobian pattern (analytic or to difference through)', t0);
    const tdir = Math.sign(tfinal - t0);
    if (tdir === 0) throw new SolverError('span', 'The start and end times are equal', t0);
    // The times asked for, in three parts: those at or before the start, which
    // are the starting state; those inside the run, which are the core's own
    // output times; and those at its end.
    const saveAt = opts.saveAt && opts.saveAt.length ? opts.saveAt : null;
    let before = 0;
    const inner = [], atEnd = [];
    if (saveAt) {
      let i = 0;
      while (i < saveAt.length && tdir * (saveAt[i] - t0) <= 0) i++;
      before = i;
      while (i < saveAt.length && tdir * (tfinal - saveAt[i]) > 0) inner.push(saveAt[i++]);
      while (i < saveAt.length && tdir * (tfinal - saveAt[i]) >= 0) atEnd.push(saveAt[i++]);
    }
    const nonNegative = [];
    if (opts.nonNegative) for (let i = 0; i < y0.length; i++) if (opts.nonNegative[i]) nonNegative.push(i);
    const res = core.ndf(f, [t0, ...inner, tfinal], y0, {
      rtol: opts.rtol,
      abstol: opts.atol,
      autoAbstol: !!opts.autoAtol,
      errorNorm: opts.norm || 'max',
      maxOrder: opts.maxOrder,
      bdf: !!opts.bdf,
      hmax: opts.hmax,
      h0: opts.h0,
      maxSteps: opts.maxSteps ?? 2e6,
      nonNegative,
      mass: opts.mass,
      suppressAlgebraic: !!opts.suppressAlgebraic,
      jacobian: Jopt,
      matrix: opts.matrix || 'auto',
      denseBelow: 0,
      denseFill: 0.35,
      scaling: opts.scaling !== false,
      minNewton: opts.minNewton ?? 2,
      stagnationTol: opts.stagnationTol ?? 0,
      belowTolRun: opts.belowTolRun == null ? 5 : opts.belowTolRun,
      stallWindow: 4000,
      events: opts.events || null,
      tStart: opts.tStart,
      onAccepted: opts.onAccepted,
      onStep: opts.onStep,
      debug: opts.debug,
    });
    let series = null;
    if (saveAt) {
      const T = [], Y = [];
      for (let i = 0; i < before; i++) { T.push(saveAt[i]); Y.push(Float64Array.from(res.y[0])); }
      for (let r = 1; r <= inner.length && r < res.t.length; r++) { T.push(res.t[r]); Y.push(res.y[r]); }
      if (res.t.length === inner.length + 2) {
        const last = res.y[res.y.length - 1];
        for (const tq of atEnd) { T.push(tq); Y.push(Float64Array.from(last)); }
      }
      series = { t: Float64Array.from(T), y: Y };
    }
    return { t: res.end.t, y: res.end.y, stopped: res.stopped, series, stats: res.stats };
  }

  /* ======================================================================
     8. Driver: a compiled model over [0, tend] with its events
     ====================================================================== */
  /**
   * Read per-species absolute tolerances out of a block of text.
   *
   * One `SPECIES VALUE` a line -- `=` and `:` do as separators, `#` and `!`
   * start a comment. The syntax is deliberately forgiving about spacing and
   * case and deliberately strict about everything else: a line it cannot read
   * is reported rather than skipped, because a silently ignored tolerance
   * looks exactly like one that did not help.
   *
   * Names are not checked here -- that needs a compiled model, and this is
   * called from the panel as the reader types, before there is one.
   *
   * @param {string} text
   * @returns {{values: Object<string, number>, errors: string[]}}
   */
  function parseSpeciesTolerances(text) {
    const values = Object.create(null);
    const errors = [];
    if (!text) return { values, errors };
    // Split on newlines alone, so a reported line number is the line the
    // reader is looking at; several entries may still share one line, comma-
    // or semicolon-separated.
    String(text).split(/\r?\n/).forEach((raw, i) => {
      const line = raw.replace(/[#!].*$/, '').trim();
      if (!line) return;
      line.split(/[,;]/).forEach((entry) => {
        const item = entry.trim();
        if (!item) return;
        const m = /^([A-Za-z][A-Za-z0-9_]*)\s*(?:[=:]|\s)\s*(\S+)$/.exec(item);
        if (!m) {
          errors.push(`line ${i + 1}: "${item}" is not a species name and a number`);
          return;
        }
        const v = Number(m[2]);
        if (!(v >= 0) || !Number.isFinite(v)) {
          errors.push(`line ${i + 1}: "${m[2]}" is not a tolerance (it must be a number, and not negative)`);
          return;
        }
        values[m[1].toUpperCase()] = v;
      });
    });
    return { values, errors };
  }

  /**
   * The absolute tolerance as one number per species.
   *
   * `atol` is the floor every species gets; `overrides` names the ones that
   * get something else. Returns null when there is nothing to override, so
   * that the common case still hands the solver the scalar it started with
   * and nothing downstream has to care.
   */
  function speciesAtol(species, atol, overrides) {
    const names = overrides ? Object.keys(overrides) : [];
    if (!names.length) return null;
    const n = species.length;
    const out = typeof atol === 'number' || atol == null
      ? new Float64Array(n).fill(atol ?? 1e-6)
      : Float64Array.from(atol);
    const index = new Map();
    for (let i = 0; i < n; i++) index.set(String(species[i]).toUpperCase(), i);
    const unknown = [];
    for (const name of names) {
      const i = index.get(name.toUpperCase());
      if (i === undefined) unknown.push(name);
      else out[i] = overrides[name];
    }
    if (unknown.length) {
      throw new SolverError('atol',
        `This model has no species called ${unknown.map((u) => `"${u}"`).join(', ')}. `
        + 'Per-species tolerances are matched by name against the compiled model.', 0);
    }
    return out;
  }

  /**
   * Moves the algebraic variables onto their constraints before the run.
   *
   * A differential-algebraic system has to start from a state that satisfies
   * its own constraints. FACSIMILE required the author to supply one ("close
   * enough to the exact solution for iterative refinement to work") and so,
   * at first, did this; what that produces when the guess is off is not a
   * warning but a stall. The circle problem of the FACSIMILE User Guide,
   * started at its documented y2 = -0.9 when the constraint wants -0.866,
   * takes a first step in which the algebraic variable jumps by 0.034. The
   * error test measures that jump, rejects the step, and halves h -- and the
   * jump does not shrink with h, because the constraint has to hold at the
   * new point whatever h is. The step size collapses to the denormal floor
   * and the run never leaves t = 0.
   *
   * So the constraints are solved here instead, by Newton on the algebraic
   * variables alone with the differential ones held where the author put
   * them. That is the index-1 initialisation: with y fixed, g(y, z) = 0
   * determines z. The differential variables are never touched, so what the
   * author wrote for them is what is integrated.
   *
   * @returns {{solved: boolean, iterations: number, residual: number, moved: number, why: string}}
   */
  function consistentInitial(model, t, y, opts = {}) {
    const mass = model.mass;
    const alg = [];
    if (mass) for (let i = 0; i < model.nspecies; i++) if (!mass[i]) alg.push(i);
    if (!alg.length) return { solved: true, iterations: 0, residual: 0, moved: 0, why: '' };

    const n = model.nspecies, na = alg.length;
    const maxit = opts.maxIterations || 30;
    const rtol = opts.rtol || 1e-10;
    // Where each (algebraic row, algebraic column) entry sits in the Jacobian
    // values, worked out once from the pattern.
    const at = new Int32Array(na * na).fill(-1);
    const col = new Int32Array(n).fill(-1);
    alg.forEach((j, c) => { col[j] = c; });
    const pat = model.pattern;
    const rowSlot = new Int32Array(n).fill(-1);
    alg.forEach((i, r) => { rowSlot[i] = r; });
    for (let j = 0; j < pat.n; j++) {
      const c = col[j];
      if (c < 0) continue;
      for (let k = pat.colPtr[j]; k < pat.colPtr[j + 1]; k++) {
        const r = rowSlot[pat.rowIdx[k]];
        if (r >= 0) at[r * na + c] = k;
      }
    }

    const lu = new DenseLU(na);
    const V = new Float64Array(model.nnz);
    const f = new Float64Array(n);
    const g = new Float64Array(na), rhs = new Float64Array(na), dz = new Float64Array(na);
    const before = Float64Array.from(y);
    const gnorm = () => { let m = 0; for (let i = 0; i < na; i++) m = Math.max(m, Math.abs(g[i])); return m; };
    const residual = () => { model.rhs(t, y, f); for (let i = 0; i < na; i++) g[i] = f[alg[i]]; return gnorm(); };

    let r0 = residual();
    let it = 0;
    let why = '';
    for (; it < maxit; it++) {
      // Converged when the correction is negligible against the variables
      // themselves, which is the only scale a constraint residual has.
      model.jac(t, y, V);
      for (let r = 0; r < na; r++) {
        const row = lu.lu[r];
        row.fill(0);
        for (let c = 0; c < na; c++) { const k = at[r * na + c]; if (k >= 0) row[c] = V[k]; }
      }
      lu.factorizeInPlace();
      if (lu.singular) {
        why = `the constraints do not determine ${model.species[alg[lu.failColumn]] || lu.failColumn} at the start`;
        break;
      }
      for (let i = 0; i < na; i++) rhs[i] = -g[i];
      lu.solve(rhs, dz);
      // A halving line search: Newton on a constraint can overshoot, and a
      // step that makes the residual worse is not an improvement.
      let lambda = 1, ok = false;
      const keep = alg.map((i) => y[i]);
      for (let trial = 0; trial < 12; trial++) {
        for (let i = 0; i < na; i++) y[alg[i]] = keep[i] + lambda * dz[i];
        const rn = residual();
        if (rn <= r0 || rn === 0) { r0 = rn; ok = true; break; }
        lambda *= 0.5;
      }
      if (!ok) {
        for (let i = 0; i < na; i++) y[alg[i]] = keep[i];
        residual();
        why = 'the Newton iteration on the constraints stopped improving';
        break;
      }
      let small = true;
      for (let i = 0; i < na; i++) {
        const scale = Math.max(Math.abs(y[alg[i]]), 1e-30);
        if (Math.abs(lambda * dz[i]) > rtol * scale) { small = false; break; }
      }
      if (small) { it++; why = ''; break; }
    }
    let moved = 0;
    for (let i = 0; i < na; i++) {
      const j = alg[i];
      moved = Math.max(moved, Math.abs(y[j] - before[j]) / Math.max(Math.abs(y[j]), 1e-30));
    }
    return { solved: !why, iterations: it, residual: r0, moved, why };
  }

  /**
   * How many events one run may apply before something is clearly wrong: an
   * event that stays on its zero after it is applied, or one that rounding
   * carries back and forth across it, fires again at every restart and the
   * run never ends. Kompartment's limit.
   */
  const MAX_EVENTS = 10000;

  /**
   * Integrates a FacsimileModel-compiled model, restarting at each terminal
   * event after applying it.
   *
   * @param {object} model   from FacsimileModel.compile
   * @param {object} opts    solver ('ndf' or a function), bdf (the BDF formulas: every
   *                         kappa zero, for the NDF and for QNDF), tend (s), rtol, atol,
   *                         atolSpecies ({NAME: value} overriding atol for those species),
   *                         nonNegative (bool), matrix, jacobianMode ('analytic'|'numeric'),
   *                         maxOrder, onProgress(t, nsteps), maxPoints (how many
   *                         points to keep; the store is thinned to stay inside it),
   *                         outputTimes (seconds; defaults to the model's <TIMES> section),
   *                         maxEvents (how many events a run may apply before it is
   *                         stopped with an error; MAX_EVENTS unless given)
   * @returns {{t: Float64Array, y: Float64Array[], grid: object|null, events: object[], stats: object}}
   */
  function runModel(model, opts = {}) {
    const n = model.nspecies;
    // A name, or a solver of the caller's own -- which is how the ode_julia
    // solvers are run: facsimile-ode-julia.js wraps each one in this same
    // signature, reporting its steps the same way, so everything below is
    // unchanged whichever is chosen.
    // A model with algebraic variables is a differential-algebraic system,
    // and only the solver in this file knows what to do with the mass matrix.
    // The ported ones would read a constraint residual as a rate of change
    // and integrate it, which is not a slower answer but a wrong one, so they
    // are refused rather than allowed to produce it.
    if (model.nalgebraic && typeof opts.solver === 'function') {
      throw new SolverError('solver',
        `This model has ${model.nalgebraic} algebraic variable${model.nalgebraic === 1 ? '' : 's'} `
        + `(${(model.algebraicNames || []).join(', ')}), which makes it a differential-algebraic `
        + 'system. The ported solvers do not take a mass matrix and would integrate the '
        + 'constraint residuals as if they were rates of change. Use NDF, with its BDF '
        + 'formulas or without.', 0);
    }
    let solver;
    if (typeof opts.solver === 'function') solver = opts.solver;
    // The plain BDFs are the NDF with every kappa zero: `bdf: true`, which is
    // the only difference. 'bdf' is still read as that, from a caller -- a
    // script, a test -- that names it as the solver it was before the pages
    // made it a switch.
    else if (opts.solver == null || opts.solver === 'ndf' || opts.solver === 'bdf') solver = ndf;
    else {
      // A name nothing here answers to -- a Julia port where the adapter did
      // not load, most likely. Refused rather than quietly served by the NDF,
      // which would report the wrong solver's answer as that one's.
      throw new SolverError('solver',
        `There is no solver called "${opts.solver}" here. The ported solvers are `
        + 'wired up in facsimile-ode-julia.js, which has to be loaded first.', 0);
    }
    const tend = opts.tend;
    if (!(tend > 0)) throw new SolverError('span', 'The simulated time must be positive', 0);
    const y0 = model.initialState(0);
    // The constraints, before anything is integrated. See consistentInitial.
    let startInfo = null;
    if (model.nalgebraic && opts.consistentStart !== false) {
      startInfo = consistentInitial(model, 0, y0, { rtol: opts.rtol });
      if (!startInfo.solved) {
        throw new SolverError('consistent',
          `The algebraic variables could not be put on their constraints at t = 0: ${startInfo.why}. `
          + `The largest residual left is ${startInfo.residual.toExponential(3)}. Give <INITIAL> a `
          + 'closer starting value, or check that each constraint determines its own variable.', 0);
      }
    }
    const f = (t, y, out) => model.rhs(t, y, out);
    const V = new Float64Array(model.nnz);
    const analytic = opts.jacobianMode !== 'numeric';
    const jacobian = {
      pattern: model.pattern,
      evaluate: analytic
        ? (t, y) => {
          model.jac(t, y, V);
          for (let k = 0; k < V.length; k++) if (!Number.isFinite(V[k])) return null;
          return V;
        }
        : undefined,
    };
    const nonNegative = opts.nonNegative ? new Uint8Array(n).fill(1) : null;
    const events = model.nevents
      ? {
        n: model.nevents,
        // An event says which way it is to be crossed: up (the default), down,
        // or either. 0 means either, which is what the crossing test reads a
        // zero direction as.
        direction: model.eventDirections && model.eventDirections.length === model.nevents
          ? Int8Array.from(model.eventDirections) : new Int8Array(model.nevents).fill(1),
        // An event marked `once` is switched off here after it has fired,
        // which is what makes it FACSIMILE's WHEN rather than its WHENEVER.
        // The mask lives for the whole run, not for one segment, so a
        // one-shot event stays shot across the restart at every later event.
        enabled: new Uint8Array(model.nevents).fill(1),
        fun: (t, y, out) => model.eventValues(t, y, out),
      }
      : null;
    const T = [0], Y = [Float64Array.from(y0)];
    // How many points come back, whatever the solver does to get there.
    //
    // Every accepted step used to be kept, which is fine at a few thousand of
    // them and fatal at a few hundred thousand: on this model that was 185 MB
    // of retained state after a minute and climbing at about 3 MB a second.
    // The tab does not so much freeze as run the machine out of memory, and by
    // then there is no clicking Stop. Bounded here instead, at a resolution
    // far past what a chart or a table can show.
    const maxPoints = Math.max(1000, opts.maxPoints || 20000);
    let stride = 1;   // one point kept per `stride` accepted steps
    let since = 0;
    const remember = (t, yy) => {
      if (++since < stride) return;
      since = 0;
      T.push(t);
      Y.push(Float64Array.from(yy));
      if (T.length < maxPoints) return;
      // Full: drop every other point and keep half as often from here on. The
      // sample stays uniform in step number, which is where the detail is --
      // dense through a transient the solver crept over, sparse where it flew.
      let w = 1;
      for (let r = 2; r < T.length; r += 2) { T[w] = T[r]; Y[w] = Y[r]; w++; }
      T.length = w;
      Y.length = w;
      stride *= 2;
    };
    /* ---- the output grid ---------------------------------------------------
       Values at times the model asked for rather than at the steps the solver
       chose, which is what FACSIMILE's WHEN/WHENEVER lists give and what a
       table meant for comparison needs. Between the two accepted steps that
       bracket a wanted time the solution is interpolated by the cubic through
       both ends and both derivatives; that costs two extra derivative
       evaluations per bracket that holds a wanted time, and nothing at all
       where none does. Every solver on the menu is served the same way, which
       reading each one's own interpolant would not be.                      */
    // An `outputTimes` that was given wins, even when it is empty: that is how
    // a caller says "no grid" for a model whose text asks for one. Only an
    // absent option falls back to the model's own <TIMES> section.
    const asked = opts.outputTimes !== undefined ? opts.outputTimes : model.outputTimes;
    const wanted = asked && asked.length ? asked : null;
    const gridT = [], gridY = [];
    // The mass diagonal, when there is anything algebraic to look after.
    const algMass = model.nalgebraic ? model.mass : null;
    const gridModel = model;
    let gi = 0;
    let prevT = 0;
    // One buffer for the previous step, refilled rather than replaced: this
    // runs on every accepted step, and a run that takes hundreds of thousands
    // of them is exactly the case the ceiling on the stored points exists for.
    const prevY = wanted ? Float64Array.from(y0) : null;
    const fa = wanted ? new Float64Array(n) : null;
    const fb = wanted ? new Float64Array(n) : null;
    if (wanted) {
      while (gi < wanted.length && wanted[gi] <= 0) {
        gridT.push(wanted[gi] < 0 ? 0 : wanted[gi]);
        gridY.push(Float64Array.from(y0));
        gi++;
      }
    }
    const fillGrid = (t1, y1) => {
      if (!wanted) return;
      if (!(t1 > prevT)) { prevT = t1; prevY.set(y1); return; }
      if (gi < wanted.length && wanted[gi] <= t1) {
        const h = t1 - prevT;
        model.rhs(prevT, prevY, fa);
        model.rhs(t1, y1, fb);
        while (gi < wanted.length && wanted[gi] <= t1) {
          const tq = wanted[gi];
          const u = Math.min(1, Math.max(0, (tq - prevT) / h));
          const u2 = u * u, u3 = u2 * u;
          const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u;
          const h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
          const yq = new Float64Array(n);
          for (let i = 0; i < n; i++) {
            // An algebraic variable has no derivative -- what f holds on its
            // row is a residual -- so the two Hermite slope terms are dropped
            // for it and the cubic runs through the two values alone.
            yq[i] = (algMass && !algMass[i])
              ? h00 * prevY[i] + h01 * y1[i]
              : h00 * prevY[i] + h10 * h * fa[i] + h01 * y1[i] + h11 * h * fb[i];
          }
          // And then put back on its constraint. Interpolating between two
          // points that each satisfy g = 0 does not give a point that does:
          // on Robertson's problem the reported sum of the three species was
          // out by 3e-4 where the solver's own steps hold it to rounding.
          if (algMass) consistentInitial(gridModel, tq, yq, { rtol: 1e-12 });
          gridT.push(tq);
          gridY.push(yq);
          gi++;
        }
      }
      prevT = t1;
      prevY.set(y1);
    };

    const eventLog = [];
    const total = { nsteps: 0, nfailed: 0, nfevals: 0, npds: 0, ndecomps: 0, nsolves: 0, nbelowtol: 0, negative: 0, repivots: 0, fallbacks: 0, segments: 0 };
    // One array for the whole run when the tolerance is allowed to follow the
    // solution, so that what a species has already reached is remembered
    // across the restart at each event.
    // Per-species tolerances, if any: resolved once against the compiled
    // species list, so an unknown name is refused before the run rather than
    // ignored during it.
    const baseAtol = speciesAtol(model.species, opts.atol, opts.atolSpecies) ?? opts.atol;
    const runAtol = opts.autoAtol
      ? (typeof baseAtol === 'number' || baseAtol == null
        ? new Float64Array(n).fill(baseAtol ?? 1e-6) : Float64Array.from(baseAtol))
      : baseAtol;
    let t0 = 0, y = y0, info = null, stoppedBy = null;
    const started = Date.now();
    // What has been integrated so far, for a caller to show when a run fails.
    const partial = () => ({
      t: Float64Array.from(T), y: Y, events: eventLog,
      grid: wanted ? { t: Float64Array.from(gridT), y: gridY } : null,
    });
    const maxEvents = opts.maxEvents ?? MAX_EVENTS;
    for (let seg = 0; ; seg++) {
      total.segments++;
      let res;
      try {
        res = solver(f, t0, tend, y, {
        rtol: opts.rtol, atol: runAtol, maxOrder: opts.maxOrder, bdf: opts.solver === 'bdf' || !!opts.bdf, hmax: opts.hmax, norm: opts.norm, debug: opts.debug, scaling: opts.scaling, minNewton: opts.minNewton, stagnationTol: opts.stagnationTol,
        nonNegative, jacobian, matrix: opts.matrix || 'auto', events, tStart: seg === 0 ? undefined : t0,
        mass: model.mass, suppressAlgebraic: opts.suppressAlgebraic,
        maxSteps: opts.maxSteps,
        // Named one by one rather than spread, so that a solver can only be
        // handed what this driver knows it means. The cost of that is that a
        // new option has to be added here as well as at both ends, and
        // forgetting to is silent -- the knob simply does nothing.
        minOrder: opts.minOrder, kappa: opts.kappa, maxJacAge: opts.maxJacAge,
        smoothEst: opts.smoothEst, belowTolRun: opts.belowTolRun,
        autoAtol: opts.autoAtol,
        onAccepted: (t, yy) => { fillGrid(t, yy); remember(t, yy); },
        onStep: opts.onProgress ? (t, ns) => opts.onProgress(t, ns + total.nsteps, T.length) : null,
        });
      } catch (e) {
        // Hand back what was integrated, so a failed run can still be looked at.
        e.partial = partial();
        throw e;
      }
      for (const key of ['nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'nbelowtol', 'negative', 'repivots', 'fallbacks']) total[key] += res.stats[key] || 0;
      info = res.stats;
      // Where a segment ends is worth keeping whatever the thinning says: it
      // is the answer at the end of the run, or the state an event fired at.
      fillGrid(res.t, res.y);
      if (T[T.length - 1] !== res.t) { T.push(res.t); Y.push(Float64Array.from(res.y)); }
      if (!res.stopped) break;
      // At most maxEvents of them. This loop used to end after 50 segments,
      // and a run that reached its fiftieth event came back as though it were
      // complete: no error, and a table and chart that ended at that event.
      if (eventLog.length >= maxEvents) {
        const err = new SolverError('events',
          `The run had applied ${maxEvents} events, the most one run may, when another fired at `
          + `t = ${res.stopped.t} of ${tend}. An event that fires again at every restart would never `
          + 'let it finish: look at what the last events in the log did. One that is meant to fire '
          + 'one time only can be marked "once".', res.stopped.t);
        err.partial = partial();
        throw err;
      }
      // Apply the event and continue from there.
      const which = res.stopped.which[0];
      if (!(res.stopped.t > t0)) {
        // The event has fired at the instant it was applied. The solvers here
        // step past a crossing that is still resting on zero at the start of a
        // segment; one that cannot would restart for ever, so it says so.
        throw new SolverError('events',
          `The event "${(model.events[which] || {}).shown || (model.events[which] || {}).expr || which}" fires again at the `
          + `instant it was applied (t = ${res.stopped.t}). This solver cannot step past a `
          + 'crossing that stays on zero; the NDF can.', res.stopped.t);
      }
      const ev = model.events[which] || {};
      // A pure stop event changes nothing: applying it would still recompute
      // the run constants at the event time, which is a side effect it never
      // asked for.
      const changed = ev.assigns && ev.assigns.length ? model.applyEvent(which, res.stopped.t, y0) : [];
      // An event changes the constants, so it can move the constraints; the
      // state has to be put back on them before the next segment starts.
      if (model.nalgebraic && changed.length && opts.consistentStart !== false) {
        const again = consistentInitial(model, res.stopped.t, res.stopped.y, { rtol: opts.rtol });
        if (!again.solved) {
          throw new SolverError('consistent',
            `After the event "${ev.expr}" the algebraic variables could not be put back on their `
            + `constraints: ${again.why}.`, res.stopped.t);
        }
      }
      if (ev.once) events.enabled[which] = 0;
      eventLog.push({
        t: res.stopped.t, event: which, expr: ev.shown || ev.expr, changed,
        stop: !!ev.stop, once: !!ev.once,
      });
      if (ev.stop) { stoppedBy = { event: which, expr: ev.expr, t: res.stopped.t }; break; }
      t0 = res.stopped.t;
      y = res.stopped.y;
      if (t0 >= tend) break;
    }
    return {
      t: Float64Array.from(T), y: Y, events: eventLog,
      grid: wanted ? { t: Float64Array.from(gridT), y: gridY, wanted: wanted.length } : null,
      stats: {
        ...total, sparse: info.sparse, fill: info.fill, ordering: info.ordering, lu: info.lu, solver: info.solver,
        nnz: model.nnz, n, points: T.length, stride, stoppedBy, consistentStart: startInfo,
        nalgebraic: model.nalgebraic || 0,
        seconds: (Date.now() - started) / 1000,
      },
    };
  }

  return { ndf, runModel, MAX_EVENTS, consistentInitial, parseSpeciesTolerances, speciesAtol, SolverError, CSC, cscFromTriplets, SparseLU, DenseLU, RefactorLU, makeIterationMatrix, colourColumns, differenceJacobian, reverseCuthillMcKee, firstCrossing, crossingTolerance };
});
