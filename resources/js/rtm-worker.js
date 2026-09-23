/* ==========================================================================
   RTM.HTML: THE SOLVER WORKER

   Compiles a model text and integrates it off the page's thread, reporting
   progress as it goes. Messages in:

     { type: 'capabilities', id }
     { type: 'compile', id, text }
     { type: 'run',     id, text, solver: {...} }
     { type: 'verify',  id, text }

   and out: { type: 'compiled' | 'progress' | 'result' | 'verified' | 'error' }.

   The page terminates the worker to abort a run, so there is no cancel message.

   This file is the handler alone; rtm-worker-entry.js is what the Worker
   starts. The split is so that a page with no Worker at all can call this
   directly, which is what a file:// visit does.
   ========================================================================== */
/* global RtmModel, FacsimileODE, FacsimileOdeJulia */

/**
 * The sparsity pattern, folded into three blocks the page can draw from.
 *
 * The whole pattern is too big to post for a large column -- hundreds of
 * thousands of entries -- but it has only three distinct blocks: the chemistry
 * of a cell against itself, and the transport of a cell against each of its
 * two neighbours. Each is ns by ns whatever the column length, so this is a
 * few kilobytes for any model.
 *
 * The blocks are OR-ed over every cell, so a coupling that exists in one cell
 * only still shows. `outside` counts entries that fall in none of the three;
 * it should be zero, since chemistry stays in a cell and transport reaches one
 * neighbour, and the page says so rather than quietly drawing an incomplete
 * picture if it ever is not.
 */
function rtmPatternBlocks(model) {
  const ns = model.speciesNames.length;
  const p = model.pattern;
  /*
    One mask per distinct cell offset (column cell minus row cell), OR-ed over
    every cell. A plain column has three: 0 and +-1. A dual-porosity model has
    more -- the layers behind a fracture cell sit at +1..nm, the next fracture
    cell at +(1+nm) -- and how many is not the page's business to know in
    advance, so the offsets are whatever the pattern has. `outside` stays as a
    count of nothing: every entry lands in some offset now, and it is kept so
    that the page's caption need not change shape.
  */
  const blocks = new Map();
  for (let col = 0; col < p.n; col++) {
    const cc = Math.floor(col / ns);
    const c = col - cc * ns;
    for (let k = p.colPtr[col]; k < p.colPtr[col + 1]; k++) {
      const row = p.rowIdx[k];
      const rc = Math.floor(row / ns);
      const off = cc - rc;
      let mask = blocks.get(off);
      if (!mask) { mask = new Uint8Array(ns * ns); blocks.set(off, mask); }
      mask[(row - rc * ns) * ns + c] = 1;
    }
  }
  const offsets = [...blocks.keys()].sort((a, b) => a - b).map((off) => ({ off, mask: blocks.get(off) }));
  return { ns, offsets, outside: 0 };
}

/**
 * Hold the species the model calls fixed at the values it gave them.
 *
 * Their rows in both the right-hand side and the Jacobian are exactly zero, so
 * the true answer is the value they started at. A stiff step still leaves a
 * little round-off in them -- the iteration matrix is factorised with partial
 * pivoting, which mixes a unit row into the others -- and on the built-in
 * model that reaches about 2.6e-13 relative over nine hundred steps. Reporting
 * that as data would be reporting the arithmetic rather than the model.
 *
 * What is written back is the initial state, which is per cell: <INITIAL> can
 * give a fixed species a different value in every cell, and each keeps its
 * own. The largest thing corrected is returned, so that round-off which is not
 * round-off has somewhere to show up rather than being quietly erased.
 */
function rtmHoldFixed(model, states, n, width) {
  // Held state by state: `fixed` on a species line holds it in every cell,
  // "fixed" in <INITIAL> in the cells that line names.
  const held = model.fixedAt || null;
  if (held ? !held.some(Boolean) : !model.fixed.some(Boolean)) return 0;
  const ns = model.speciesNames.length;
  const y0 = model.initialState();
  let worst = 0;
  for (let k = 0; k < ns * model.cells; k++) {
    if (held ? !held[k] : !model.fixed[k % ns]) continue;
    const v = y0[k];
    const scale = Math.max(Math.abs(v), 1e-300);
    for (let i = 0; i < n; i++) {
      const at = i * width + k;
      const d = Math.abs(states[at] - v) / scale;
      if (d > worst) worst = d;
      states[at] = v;
    }
  }
  return worst;
}

/** A summary of a compiled model, small enough to post to the page. */
function rtmSummary(model) {
  return {
    species: model.speciesNames,
    nspecies: model.speciesNames.length,
    states: model.nspecies,
    cells: model.cells,                  // every cell, matrix layers included
    fracture: model.fracture,            // the cells along the column
    stride: model.stride,                // cells per fracture cell: 1 + matrix layers
    // The rock matrix, when there is one: how many layers, how thick, and
    // how deep their centres sit, in metres from the fracture wall.
    matrix: model.matrix ? {
      n: model.matrix.n,
      thickness: Array.from(model.matrix.d),
      depth: Array.from(model.matrix.centre),
      total: model.matrix.depth,
      porosity: model.matrix.porosity,
      aw: model.matrix.aw,
      enters: model.speciesNames.filter((_, s) => model.enters[s]),
    } : null,
    centres: Array.from(model.grid.centres),
    width: Array.from(model.grid.width),
    length: model.grid.L,
    // What the panel says about the layout: the kind and its one number, and
    // a surface layer's thickness when the first cell is pinned.
    grid: { kind: model.settings.GRID, ratio: model.settings.GRID_RATIO,
      power: model.settings.GRID_POWER, surface: model.grid.surface || 0 },
    transport: model.transport,
    mobile: model.mobile,
    fixed: model.fixed,
    held: model.held || [],
    tables: model.tables || [],
    nreactions: model.nreactions,
    nchannels: model.nchannels,
    nequilibria: model.nequilibria,
    nconserved: model.conservation.length,
    nparameters: model.parameters ? model.parameters.length : 0,
    parameters: model.parameters || [],
    // Only present when EQUILIBRATE ran: one entry per cell.
    speciated: model.speciated
      ? { cells: model.speciated.length,
          stuck: model.speciated.filter((c) => !c.converged).length,
          iterations: Math.max(...model.speciated.map((c) => c.iterations)) }
      : null,
    anyMass: !!model.anyMass,
    nnz: model.nnz,
    density: model.density,
    blocks: rtmPatternBlocks(model),
    timeUnit: model.timeUnit,
    settings: model.settings,
    warnings: model.warnings,
    initial: Array.from(model.initialState()),
  };
}

/** Which solvers this worker can actually run; asked for as it starts. */
function rtmSolvers() {
  // The NDF runs the plain BDFs with its BDF formulas switch, and QNDF runs
  // QBDF the same way, so neither is an entry of its own.
  const out = ['ndf'];
  if (typeof FacsimileOdeJulia !== 'undefined') out.push(...Object.keys(FacsimileOdeJulia.METHODS));
  return out;
}

function rtmErrorMessage(e) {
  return (e && e.message) ? e.message : String(e);
}

function handleRtmMessage(msg, post) {
  const id = msg.id;
  if (msg.type === 'capabilities') {
    post({ type: 'capabilities', id, solvers: rtmSolvers() });
    return;
  }

  let model;
  try {
    model = RtmModel.compile(msg.text);
  } catch (e) {
    post({ type: 'error', id, stage: 'compile', error: rtmErrorMessage(e), line: e && e.line });
    return;
  }

  if (msg.type === 'compile') {
    post({ type: 'compiled', id, model: rtmSummary(model) });
    return;
  }

  if (msg.type === 'verify') {
    try {
      const checks = [];
      const y0 = model.initialState();
      checks.push({ label: 'the initial state', ...RtmModel.verifyJacobian(model, 0, y0) });
      // A state with everything present, which exercises rate laws that are
      // identically zero at the start and so are never tested by the first.
      const y1 = Float64Array.from(y0, (v, i) => (v > 0 ? v : 1e-9 * (1 + (i % 5))));
      checks.push({ label: 'every species present', ...RtmModel.verifyJacobian(model, 0, y1) });
      post({
        type: 'verified',
        id,
        checks: checks.map((c) => ({
          label: c.label,
          checked: c.checked,
          unresolvable: c.unresolvable,
          ndiscrepancies: c.discrepancies.length,
          discrepancies: c.discrepancies.slice(0, 10).map((d) => ({
            row: model.species[d.row], col: model.species[d.col],
            analytic: d.analytic, numeric: d.numeric,
          })),
          outsidePattern: c.outsidePattern
            ? { row: model.species[c.outsidePattern.row], col: model.species[c.outsidePattern.col] }
            : null,
        })),
        nnz: model.nnz,
      });
    } catch (e) {
      post({ type: 'error', id, stage: 'verify', error: rtmErrorMessage(e) });
    }
    return;
  }

  if (msg.type !== 'run') return;

  const s = msg.solver || {};
  const method = s.method || 'ndf';
  const viaJulia = typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method);
  const tend = s.tend > 0 ? s.tend : model.settings.TEND;
  let lastReport = 0;
  const started = Date.now();

  try {
    const res = FacsimileODE.runModel(model, {
      solver: viaJulia ? FacsimileOdeJulia.solver(method) : method,
      tend,
      rtol: s.rtol,
      atol: s.atol,
      nonNegative: !!s.nonNegative,
      matrix: s.matrix || 'auto',
      // Every κ zero: the NDF as the plain BDFs, QNDF as QBDF.
      bdf: !!s.bdf,
      maxSteps: s.maxSteps,
      maxPoints: s.maxPoints || 4000,
      norm: s.norm,
      // The rest of facsimile.html's settings, which this page now offers too.
      maxOrder: s.maxOrder || 5,
      minOrder: s.minOrder || 1,
      hmax: s.hmax > 0 ? s.hmax : undefined,
      jacobianMode: s.jacobianMode || 'analytic',
      kappa: s.kappa,
      maxJacAge: s.maxJacAge,
      smoothEst: s.smoothEst !== false,
      /*
        Let the corrector stop when it has stopped improving, as long as the
        correction is within half the tolerance and the Jacobian is the one for
        this point. Reaction networks of the kind this page is for -- rate
        constants to 1e16 against concentrations of 1e-9 -- cancel so heavily
        that the residual cannot be evaluated to better than a part in 1e7, and
        the corrections stop shrinking there. Without this the step is thrown
        out as diverging and h is cut, which does nothing at all, because
        arithmetic noise does not scale with h: a run can then take millions of
        steps to cover a few seconds. facsimile.html leaves it off; see the note in
        facsimile-solver.js for what it costs a model that does not need it. The
        page's Stall tolerance, 0.5 unless it says otherwise.
      */
      stagnationTol: s.stagnationTol ?? 0.5,
      belowTolRun: s.belowTolRun,
      autoAtol: s.autoAtol,
      onProgress: (t, nsteps) => {
        const now = Date.now();
        if (now - lastReport < 250) return true;
        lastReport = now;
        post({ type: 'progress', id, t, tend, nsteps, frac: Math.min(1, t / tend) });
        return true;
      },
    });

    // The state at every stored time, flattened: point-major, then cell-major
    // within a point, which is the order the model itself uses.
    const n = res.t.length;
    const width = model.nspecies;
    const states = new Float64Array(n * width);
    for (let i = 0; i < n; i++) states.set(res.y[i], i * width);
    const heldDrift = rtmHoldFixed(model, states, n, width);
    const payload = {
      type: 'result',
      id,
      t: res.t,
      states,
      n,
      width,
      model: rtmSummary(model),
      stats: res.stats,
      heldDrift,
      seconds: (Date.now() - started) / 1000,
    };
    post(payload, [res.t.buffer, states.buffer]);
  } catch (e) {
    const out = { type: 'error', id, stage: 'run', error: rtmErrorMessage(e) };
    // Hand back whatever was integrated before the failure, as facsimile does:
    // the part that did run is usually where the trouble can be seen.
    if (e.partial && e.partial.t && e.partial.t.length > 1) {
      const n = e.partial.t.length;
      const width = model.nspecies;
      const states = new Float64Array(n * width);
      for (let i = 0; i < n; i++) states.set(e.partial.y[i], i * width);
      const heldDrift = rtmHoldFixed(model, states, n, width);
      out.partial = {
        t: e.partial.t, states, n, width, model: rtmSummary(model), stats: e.partial.stats || {},
        heldDrift,
      };
    }
    post(out);
  }
}

/*
  Reached two ways and it does not care which: rtm-worker-entry.js brings this
  in and wires it to onmessage, and a page with no Worker calls it directly.
  Hence a global rather than an export.
*/
if (typeof self !== 'undefined') self.handleRtmMessage = handleRtmMessage;
if (typeof module !== 'undefined' && module.exports) module.exports = { handleRtmMessage };
