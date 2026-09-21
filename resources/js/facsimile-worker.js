/* ==========================================================================
   FACSIMILE.HTML: THE SOLVER WORKER

   Compiles a model text and integrates it off the page's thread, reporting
   progress as it goes. Messages in:

     { type: 'compile', id, text, settings, clampNegative }
     { type: 'run',     id, text, settings, clampNegative, solver: {...} }
     { type: 'verify',  id, text, settings, clampNegative }

   and out: { type: 'compiled' | 'progress' | 'result' | 'verified' | 'error', id, ... }.

   The page terminates the worker to abort a run, so there is no cancel message.

   This file is the handler alone. facsimile-worker-entry.js is what the
   Worker actually starts: it brings in the engine and this, and wires the two
   to onmessage. The split is so that a page with no Worker at all can call
   this directly.
   ========================================================================== */
/* global FacsimileModel, FacsimileODE, FacsimileOdeJulia */

function summary(model) {
  return {
    species: model.species,
    nspecies: model.nspecies,
    nreactions: model.reactions.length,
    nnz: model.nnz,
    density: model.density,
    equations: model.equations,
    outputs: model.outputs,
    observeNames: model.observeNames,
    rates: model.rates,
    rateNames: model.rateNames,
    outputTimes: model.outputTimes,
    outputTimeUnit: model.outputTimeUnit,
    events: model.events,
    warnings: model.warnings,
    settings: model.settings,
    tableNames: model.tableNames,
    reactions: model.reactions,
    pattern: { n: model.pattern.n, nnz: model.pattern.nnz, colPtr: model.pattern.colPtr, rowIdx: model.pattern.rowIdx },
    sources: model.sources,
    colours: FacsimileODE.colourColumns(model.pattern).length,
    constants: model.constantValues(),
    // Every constant's own comment, which is where its unit and description
    // come from. `constants` is name -> value and loses that.
    Pmeta: model.Pmeta,
  };
}

function errorMessage(e) {
  return { message: e && e.message ? e.message : String(e), line: e && e.line ? e.line : 0, code: e && e.code ? e.code : null, t: e && e.t !== undefined ? e.t : null };
}

/**
 * Handles one request; `post(message, transfer)` delivers the replies. In a
 * Worker this is wired to onmessage; a page without Workers (file://) calls it
 * directly and gets the replies synchronously.
 */
/**
 * Which solvers this worker can actually run.
 *
 * Asked for as soon as the worker starts, and compared with the menu. A Worker
 * does not inherit the page's cache-busting, so a browser holding an older
 * copy of the entry module runs a worker that has never heard of solvers the
 * page is happily offering -- which fails at the worst moment, in the middle
 * of a run, with a message about a solver name. Asked up front it is a greyed
 * menu entry and a line saying to reload.
 */
function facsimileSolvers() {
  const out = ['ndf', 'bdf'];
  if (typeof FacsimileOdeJulia !== 'undefined') out.push(...Object.keys(FacsimileOdeJulia.METHODS));
  return out;
}

function handleFacsimileMessage(msg, post) {
  const id = msg.id;
  // Answered before anything else, because it is the one request that does not
  // carry a model: every other kind starts by compiling msg.text, and asking
  // that question of an undefined text answers with a compiler error instead.
  if (msg.type === 'capabilities') {
    post({ type: 'capabilities', id, solvers: facsimileSolvers() });
    return;
  }
  let model;
  try {
    model = FacsimileModel.compile(msg.text, { settings: msg.settings, clampNegative: msg.clampNegative !== false });
  } catch (e) {
    post({ type: 'error', id, stage: 'compile', error: errorMessage(e) });
    return;
  }
  if (msg.type === 'compile') {
    post({ type: 'compiled', id, model: summary(model) });
    return;
  }
  if (msg.type === 'verify') {
    try {
      const y0 = model.initialState(0);
      const checks = [];
      checks.push({ label: 'initial state, t = 0', ...model.verifyJacobian(0, y0) });
      // A state with every species present, at a few times, to exercise the
      // whole pattern (a species that is zero contributes nothing to a test).
      const ymax = Math.max(...Array.from(y0));
      for (const [label, t, scale] of [['all species at 1e-6 of the largest, t = 1 h', 3600, 1e-6], ['all species at 1e-12 of the largest, t = 1 year', 3.156e7, 1e-12], ['all species at 1e-9 of the largest, t = 100 years', 3.156e9, 1e-9]]) {
        const y1 = Float64Array.from(y0, (v, i) => (v > 0 ? v : ymax * scale * (1 + (i % 7))));
        checks.push({ label, ...model.verifyJacobian(t, y1) });
      }
      post({ type: 'verified', id, checks: checks.map((c) => ({ label: c.label, checked: c.checked, discrepancies: c.discrepancies.slice(0, 12), ndiscrepancies: c.discrepancies.length, outsidePattern: c.outsidePattern })), nnz: model.nnz, colours: FacsimileODE.colourColumns(model.pattern).length });
    } catch (e) {
      post({ type: 'error', id, stage: 'verify', error: errorMessage(e) });
    }
    return;
  }
  if (msg.type === 'run') {
    const s = msg.solver || {};
    const tend = (s.tendYears > 0 ? s.tendYears : 500) * 365.25 * 86400;
    const method = s.method || 'ndf';
    const viaJulia = typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method);
    let lastReport = 0;
    const started = Date.now();

    /** The run itself, given whichever solver is to do it. */
    const go = (solve) => {
    try {
      const res = FacsimileODE.runModel(model, {
        solver: solve,
        tend,
        rtol: s.rtol, atol: s.atol, atolSpecies: s.atolSpecies,
        nonNegative: !!s.nonNegative,
        matrix: s.matrix || 'auto',
        jacobianMode: s.jacobianMode || 'analytic',
        norm: s.norm || 'max',
        maxOrder: s.maxOrder || 5,
        minOrder: s.minOrder || 1,
        kappa: s.kappa,
        maxJacAge: s.maxJacAge,
        belowTolRun: s.belowTolRun,
        autoAtol: !!s.autoAtol,
        smoothEst: s.smoothEst !== false,
        hmax: s.hmaxSeconds > 0 ? s.hmaxSeconds : undefined,
        maxSteps: s.maxSteps || 2e6,
        onProgress: (t, nsteps, npoints) => {
          const now = Date.now();
          if (now - lastReport < 120) return;
          lastReport = now;
          // Plain elapsed time over the time asked for. A log clock was tried
          // and is worse than useless here: a run that has reached thirteen
          // years of five hundred shows as nine tenths done, which is the
          // opposite of what the reader needs to know.
          post({
            type: 'progress', id, t, tend, nsteps, npoints,
            frac: Math.min(1, Math.max(0, t / tend)), seconds: (now - started) / 1000,
          });
        },
        maxPoints: s.maxPoints,
      });
      // Observables at every stored point, computed here so the page only draws.
      const names = model.observeNames;
      const observeAll = (T, Ys) => {
        const n = T.length;
        const obs = new Float64Array(names.length);
        const observed = new Float64Array(n * names.length);
        const states = new Float64Array(n * model.nspecies);
        for (let k = 0; k < n; k++) {
          try { model.observe(T[k], Ys[k], obs); } catch (_) { obs.fill(NaN); }
          observed.set(obs, k * names.length);
          states.set(Ys[k], k * model.nspecies);
        }
        return { t: T, states, observed, n };
      };
      const main = observeAll(res.t, res.y);
      const grid = res.grid && res.grid.t.length ? observeAll(res.grid.t, res.grid.y) : null;
      const payload = {
        type: 'result', id,
        ...main, nspecies: model.nspecies, observeNames: names, species: model.species,
        grid, gridWanted: res.grid ? res.grid.wanted : 0,
        events: res.events, stats: res.stats, constants: model.constantValues(),
        seconds: (Date.now() - started) / 1000,
      };
      const transfer = [main.t.buffer, main.states.buffer, main.observed.buffer];
      if (grid) transfer.push(grid.t.buffer, grid.states.buffer, grid.observed.buffer);
      post(payload, transfer);
    } catch (e) {
      const err = errorMessage(e);
      const out = { type: 'error', id, stage: 'run', error: err, trace: e.trace || null };
      if (e.partial && e.partial.t && e.partial.t.length > 1) {
        // Hand the page what was integrated before the failure.
        const names = model.observeNames;
        const observeAll = (T, Ys) => {
          const n = T.length;
          const obs = new Float64Array(names.length);
          const observed = new Float64Array(n * names.length);
          const states = new Float64Array(n * model.nspecies);
          for (let k = 0; k < n; k++) {
            try { model.observe(T[k], Ys[k], obs); } catch (_) { obs.fill(NaN); }
            observed.set(obs, k * names.length);
            states.set(Ys[k], k * model.nspecies);
          }
          return { t: T, states, observed, n };
        };
        const g = e.partial.grid && e.partial.grid.t.length ? observeAll(e.partial.grid.t, e.partial.grid.y) : null;
        out.partial = {
          ...observeAll(e.partial.t, e.partial.y),
          nspecies: model.nspecies, observeNames: names, species: model.species,
          grid: g, events: e.partial.events, constants: model.constantValues(),
        };
      }
      post(out);
    }
    };

    // Every solver here is ordinary JavaScript and needs nothing fetched, so
    // the run starts at once.
    go(viaJulia ? FacsimileOdeJulia.solver(method) : method);
  }
}

/*
  Reached two ways, and it does not care which: the Worker entry point
  (facsimile-worker-entry.js) imports this and wires it to onmessage, and a
  page with no Worker calls it directly. Hence a global rather than an export.
*/
globalThis.handleFacsimileMessage = handleFacsimileMessage;
