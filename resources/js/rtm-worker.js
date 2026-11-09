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
  // The species only: a model holding its equilibria has its totals after them.
  const last = model.stateWidth || p.n;
  for (let col = 0; col < last; col++) {
    const cc = Math.floor(col / ns);
    const c = col - cc * ns;
    for (let k = p.colPtr[col]; k < p.colPtr[col + 1]; k++) {
      const row = p.rowIdx[k];
      if (row >= last) continue;
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
    cells: model.cells,                  // every cell, matrix layers and extra cells included
    fracture: model.fracture,            // the cells along the column
    stride: model.stride,                // cells per fracture cell: 1 + matrix layers
    // The cells past a semi-infinite right-hand end, after the column's own.
    extra: model.extra ? {
      n: model.extra.n,
      centres: Array.from(model.extra.centres),
      width: Array.from(model.extra.width),
    } : null,
    // The rock matrix, when there is one: how many layers, how thick, and
    // how deep their centres sit, in metres from the fracture wall; how they
    // were laid out and how the first was chosen.
    matrix: model.matrix ? {
      n: model.matrix.n,
      thickness: Array.from(model.matrix.d),
      depth: Array.from(model.matrix.centre),
      total: model.matrix.depth,
      porosity: model.matrix.porosity,
      density: model.matrix.density,
      aw: model.matrix.aw,
      grid: model.matrix.grid,
      rule: model.matrix.rule,
      ratio: model.matrix.q,
      enters: model.speciesNames.filter((_, s) => model.enters[s]),
    } : null,
    // The water's travel time, when the flow gives one.
    travelTime: model.surface && model.surface.tw < Infinity ? model.surface.tw : null,
    // What crosses each end, per species, as a sum over the stored states.
    faces: model.faces,
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
    // The tables the rate laws read at the clock, and where the run restarts.
    clockTables: model.clockTables || [],
    breaks: typeof model.breaks === 'function' ? model.breaks(0, model.settings.TEND).length : 0,
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
    initial: Array.from(model.toConcentrations ? model.toConcentrations(model.initialState()) : model.initialState()),
    // Equilibria held throughout the run (EQUILIBRATE = always): how many
    // relations, conserved totals and species, and the species' share of the state.
    heldEquilibria: model.heldEquilibria || null,
    speciesStates: model.stateWidth || model.nspecies,
    // ACTIVITY: the model, its temperature and A and B, and how many ions.
    activity: model.activity || null,
    // Ion exchange: the exchangers, and how many species are on them.
    exchange: model.act && model.act.ex
      ? { exchangers: model.act.ex.exchangers.map((k) => model.speciesNames[k]), species: model.act.ex.list.length }
      : null,
    // Surface complexation: the sites of each type (the species of each that
    // comes first), how many species are on them, and in how many types.
    surface: model.act && model.act.sf
      ? { sites: model.act.sf.types.map((t) => model.speciesNames[t.members[0]]), species: model.act.sf.list.length,
        // Each double layer's potential, and its psi at the start, in volts, over the cells.
        potentials: model.act.pt ? model.act.pt.list.map((k) => rtmPotentialSummary(model, k)) : [] }
      : null,
    // Redox: the electron, the relations tied to it, and the pe the start has.
    redox: model.electron >= 0 ? rtmRedoxSummary(model) : null,
    // A gas phase: its gases, and the volume or the total pressure it is held at.
    gas: model.act && model.act.gas
      ? { fixed: model.act.gas.fixed, volume: model.act.gas.volume, pressure: model.act.gas.pressure,
        species: model.act.gas.list.map((k) => model.speciesNames[k]) }
      : null,
    // The solid solutions: each one's name, its members and, for a binary one, a0 and a1 at 25 C and whether there is
    // a miscibility gap.
    solidSolutions: model.solidSolutions && model.solidSolutions.length ? model.solidSolutions : null,
    // The temperature: what TEMPERATURE gives, whether it goes with the cell or the time, how many relations' and
    // phases' log K go with it, and the cells' lowest and highest at the start.
    temperature: model.temperature ? { ...model.temperature, start: rtmTemperatureRange(model, 0) } : null,
    // What the run can be read as besides its species, and what <DATA> measured: the charts' pickers and points.
    quantities: model.quantities || [],
    data: model.data || [],
    // What each species is made of: where an element is, and the water's major ions (compositionOf).
    composition: model.composition || null,
    // The species dissolved in the water: those a diagram can hold an activity of.
    solutes: model.speciesNames.filter((_, k) => rtmSolute(model, k)),
  };
}

/** The cells' lowest and highest temperature at time t, C; null where TEMPERATURE is a number. */
function rtmTemperatureRange(model, t) {
  if (!model.temperature || !model.temperature.varies) return null;
  const tc = model.temperatures(t);
  return [Math.min(...tc), Math.max(...tc)];
}

/** Each stored point's cells' temperatures, C, point by point, where TEMPERATURE goes with the cell or the time. */
function rtmTemperatures(model, ts, n) {
  if (!model.temperature || !model.temperature.varies) return null;
  const nc = model.cells;
  const out = new Float64Array(n * nc);
  for (let i = 0; i < n; i++) out.set(model.temperatures(ts[i]), i * nc);
  return out;
}

function rtmPotentialSummary(model, k) {
  const ns = model.speciesNames.length;
  const c = model.toConcentrations ? model.toConcentrations(model.initialState()) : model.initialState();
  const pt = model.act.pt;
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < model.cells; i++) {
    // F/RT at the cell's temperature, at the start, where it goes with the cell or the time.
    const psi = -Math.log(c[i * ns + k]) / (pt.fRTc ? pt.fRTc[i] : pt.fRT);
    if (Number.isFinite(psi)) { lo = Math.min(lo, psi); hi = Math.max(hi, psi); }
  }
  // CD-MUSIC's planes: 0, 1 and 2 of a surface with three potentials; a double layer's has none.
  const q = pt.list.indexOf(k);
  const plane = q >= 0 && pt.kind ? { c0: 0, c1: 1, cd: 2 }[pt.kind[q]] : undefined;
  return { name: model.speciesNames[k], psi: Number.isFinite(lo) ? [lo, hi] : null, plane: plane === undefined ? null : plane };
}

function rtmRedoxSummary(model) {
  const e = model.electron;
  const ns = model.speciesNames.length;
  const c = model.toConcentrations ? model.toConcentrations(model.initialState()) : model.initialState();
  let lo = Infinity;
  let hi = -Infinity;
  for (let k = 0; k < model.cells; k++) {
    const pe = -Math.log10(c[k * ns + e]);
    if (Number.isFinite(pe)) { lo = Math.min(lo, pe); hi = Math.max(hi, pe); }
  }
  return {
    name: model.speciesNames[e],
    relations: model.equilibria.filter((eq) => eq.net.some(([s]) => s === e)).length,
    fixed: !!model.fixed[e],
    pe: Number.isFinite(lo) ? [lo, hi] : null,
  };
}

/**
 * The stored states as concentrations: the model's own where it keeps
 * concentrations, else converted -- logarithms back, totals dropped -- each
 * at its time ts[i], which the relations are those of where the temperature
 * goes with time.
 */
function rtmConcentrations(model, ys, n, width, ts) {
  const states = new Float64Array(n * width);
  for (let i = 0; i < n; i++) {
    states.set(model.toConcentrations ? model.toConcentrations(ys[i], ts[i]) : ys[i].subarray(0, width), i * width);
  }
  return states;
}

/** Which solvers this worker can actually run; asked for as it starts. */
function rtmSolvers() {
  // The NDF runs the plain BDFs with its BDF formulas switch, and QNDF runs
  // QBDF the same way, so neither is an entry of its own. Rosenbrock 2-3 and
  // Dormand-Prince 4-5 are the solver core's, beside the NDF.
  const out = ['ndf', 'ros23', 'dp45'];
  if (typeof FacsimileOdeJulia !== 'undefined') out.push(...Object.keys(FacsimileOdeJulia.METHODS));
  return out;
}

function rtmErrorMessage(e) {
  return (e && e.message) ? e.message : String(e);
}

/*
  The last run, kept so that the page can ask what it comes to besides its
  species -- pH, saturation indices, totals, the text's <OUTPUT> -- without
  sending it back: its model and its stored concentrations, under the key
  the result carried. A worker started again has none, and says so; the
  page then sends the run with the question.
*/
let rtmKept = null;
let rtmRunCount = 0;

/**
 * Quantities of a run: for each key and each cell asked for, the value at
 * every stored point, key-major then cell-major then point.
 */
/** The run a message asks about: the one kept, or the one it brings with it, kept from then on; null if neither. */
function rtmRunFor(msg) {
  if (rtmKept && rtmKept.key === msg.runKey) return rtmKept;
  if (!msg.states) return null;
  const model = rtmKept && rtmKept.text === msg.text ? rtmKept.model : RtmModel.compile(msg.text);
  rtmKept = { key: msg.runKey, text: msg.text, model, t: msg.t, states: msg.states, n: msg.n, width: msg.width };
  return rtmKept;
}

function rtmQuantities(msg) {
  const run = rtmRunFor(msg);
  if (!run) return { type: 'quantities', id: msg.id, missing: true };
  const { model, t, states, n, width } = run;
  const keys = msg.keys;
  const which = Int32Array.from(keys.map((k) => model.quantities.findIndex((q) => q.key === k)));
  const unknown = keys.filter((k, q) => which[q] < 0);
  if (unknown.length) throw new Error(`The model has no quantity ${unknown.join(', ')}.`);
  const cells = msg.cells;
  const values = new Float64Array(keys.length * cells.length * n);
  const out = new Float64Array(keys.length);
  for (let i = 0; i < n; i++) {
    const c = states.subarray(i * width, (i + 1) * width);
    for (let j = 0; j < cells.length; j++) {
      model.quantitiesAt(c, t[i], cells[j], which, out);
      for (let q = 0; q < keys.length; q++) values[(q * cells.length + j) * n + i] = out[q];
    }
  }
  return { type: 'quantities', id: msg.id, keys, cells, n, values };
}

/*
  DIAGRAMS: the water of one cell -- as the model starts it, or as the run
  left it -- held at each point of a range of pH, pe, a species' activity or
  an element's total, or of two such ranges, and speciated there by the
  model's own relations (RtmModel.speciate), as PhreePlot does with
  PHREEQC's. Each point starts from the one before it, the grid walked to and
  fro so that the one before is always beside it, and from the water itself
  where that does not settle. An activity is held through the concentration
  that gives it, the activity coefficient taken again from the speciation
  until it stops moving. Returns each point's concentrations in that cell and
  every quantity of the model there; a point that did not settle is NaN.
*/
const RTM_DIAGRAM_KINDS = { pH: 'pH', pe: 'pe', la: 'log activity', tot: 'log total' };

/** Whether species k is dissolved in the water: the activity model's solute, or without one what is no mineral, gas or site. */
function rtmSolute(model, k) {
  const sp = model.speciesList[k];
  return model.act ? !!model.act.solute[k] : !(sp.mineral || sp.exchange || sp.exchanger || sp.electron || sp.surface
    || sp.potential || sp.gas || sp.name === 'H2O');
}

/** One axis of a diagram: what it holds, and its values from `from` to `to` in `n` steps. */
function rtmDiagramAxis(model, ax) {
  const ns = model.speciesNames.length;
  const values = Float64Array.from({ length: ax.n }, (_, i) => (ax.n === 1 ? ax.from : ax.from + ((ax.to - ax.from) * i) / (ax.n - 1)));
  if (!(ax.n >= 2 && ax.n <= 400) || !Number.isFinite(ax.from) || !Number.isFinite(ax.to) || ax.from === ax.to) {
    throw new Error(`${RTM_DIAGRAM_KINDS[ax.kind] || ax.kind}: from and to two different numbers, and from 2 to 400 points.`);
  }
  const solute = (k) => rtmSolute(model, k);
  if (ax.kind === 'pH') {
    const k = model.speciesNames.indexOf('H+');
    if (k < 0 || !solute(k)) throw new Error('A pH is the activity of H+, and the model has no H+ in its water.');
    return { kind: 'pH', k, values, sign: -1 };
  }
  if (ax.kind === 'pe') {
    if (!(model.electron >= 0)) throw new Error('A pe is the electron\'s, and the model has none: e- electron.');
    return { kind: 'pe', k: model.electron, values, sign: -1 };
  }
  if (ax.kind === 'la') {
    const k = model.speciesNames.indexOf(ax.species);
    if (k < 0 || !solute(k)) throw new Error(`log a(${ax.species}): it is no species dissolved in the water.`);
    return { kind: 'la', k, values, sign: 1, species: ax.species };
  }
  if (ax.kind === 'tot') {
    const comp = (model.composition && model.composition.elements || []).find((e) => e.el === ax.species);
    if (!comp) throw new Error(`The total of ${ax.species}: no species of the model has any.`);
    const weights = new Float64Array(ns);
    for (const [k, n] of comp.terms) weights[k] = n;
    return { kind: 'tot', weights, values, name: ax.species };
  }
  throw new Error(`"${ax.kind}" is no axis of a diagram: pH, pe, la or tot.`);
}

function rtmDiagram(msg, post) {
  let model;
  let base;
  let t = 0;
  if (msg.at === 'end') {
    const run = rtmRunFor(msg);
    if (!run) return { type: 'diagram', id: msg.id, missing: true };
    model = run.model;
    t = run.t[run.n - 1];
    base = Float64Array.from(run.states.subarray((run.n - 1) * run.width, run.n * run.width));
  } else {
    model = rtmKept && rtmKept.text === msg.text ? rtmKept.model : RtmModel.compile(msg.text);
    const y0 = model.initialState();
    base = Float64Array.from(model.toConcentrations ? model.toConcentrations(y0) : y0);
  }
  if (!model.equilibria || !model.equilibria.length) {
    throw new Error('The model has no relations in <EQUILIBRIUM>: a diagram is its water speciated by them, and there are none.');
  }
  const ns = model.speciesNames.length;
  const cell = msg.cell;
  if (!(Number.isInteger(cell) && cell >= 0 && cell < model.cells)) throw new Error(`There is no cell ${cell}.`);
  const b = cell * ns;
  const axes = msg.axes.map((ax) => rtmDiagramAxis(model, ax));
  if (axes.length === 2 && ((axes[0].k !== undefined && axes[0].k === axes[1].k)
    || (axes[0].kind === 'tot' && axes[1].kind === 'tot'))) {
    throw new Error('The two axes hold the same thing, or two totals: give them one each.');
  }
  // Held: the model's fixed species, and what an axis holds at an activity.
  const held = Array.from({ length: ns }, (_, k) => !!(model.fixed && model.fixed[k]));
  for (const ax of axes) if (ax.kind !== 'tot') held[ax.k] = true;
  const totAxis = axes.findIndex((ax) => ax.kind === 'tot');
  /*
    A total varied without the pH: the pH held where the water has it, as
    PHREEQC's SOLUTION holds the pH it is given. Left to itself, the element
    would come in as whichever species its conserved total is kept in, and
    the pH would go with that choice, which is no choice of the reader's.
  */
  const holds = axes.map((ax, a) => ({ ax, a }));
  let pHHeld = null;
  const iH = model.speciesNames.indexOf('H+');
  if (totAxis >= 0 && !axes.some((ax) => ax.kind === 'pH') && iH >= 0 && rtmSolute(model, iH) && !held[iH]) {
    if (model.thermoAt) model.thermoAt(t);
    const g0 = new Float64Array(ns);
    if (model.act) RtmModel.activityAt(model.act, base, b, g0, new Float64Array(ns), cell);
    pHHeld = -(Math.log(base[b + iH]) + g0[iH]) / Math.LN10;
    held[iH] = true;
    holds.push({ ax: { kind: 'pH', k: iH }, a: -1 });
  }
  const n1 = axes[0].values.length;
  const n2 = axes[1] ? axes[1].values.length : 1;
  const npts = n1 * n2;
  const nq = model.quantities.length;
  const which = Int32Array.from({ length: nq }, (_, q) => q);
  const states = new Float64Array(npts * ns).fill(NaN);
  const quant = new Float64Array(npts * nq).fill(NaN);
  const qOut = new Float64Array(nq);
  const lnG = new Float64Array(ns);
  const lnD = new Float64Array(ns);
  // Each held species' ln gamma, carried from point to point.
  const lnGamma = holds.map(() => 0);
  let failed = 0;
  let cur = Float64Array.from(base);
  const settle = (y, vals) => {
    for (let it = 0; it < 40; it++) {
      holds.forEach(({ ax, a }, h) => {
        const v = a >= 0 ? vals[a] : pHHeld;
        if (ax.kind === 'pe') y[b + ax.k] = 10 ** -v;
        else if (ax.kind === 'pH') y[b + ax.k] = 10 ** -v * Math.exp(-lnGamma[h]);
        else if (ax.kind === 'la') y[b + ax.k] = 10 ** v * Math.exp(-lnGamma[h]);
      });
      const r = RtmModel.speciate(model, y, { fixed: held, cells: [cell], t,
        total: totAxis >= 0 ? { weights: axes[totAxis].weights, value: 10 ** vals[totAxis], name: axes[totAxis].name } : undefined });
      if (!r.cells.length || !r.cells[0].converged) return false;
      y.set(r.y.subarray(b, b + ns), b);
      if (!model.act) return true;
      RtmModel.activityAt(model.act, y, b, lnG, lnD, cell);
      let moved = 0;
      holds.forEach(({ ax }, h) => {
        if (ax.kind !== 'pH' && ax.kind !== 'la') return;
        moved = Math.max(moved, Math.abs(lnG[ax.k] - lnGamma[h]));
        lnGamma[h] = lnG[ax.k];
      });
      if (moved < 1e-11) return true;
    }
    return false;
  };
  let done = 0;
  let lastReport = Date.now();
  for (let j = 0; j < n2; j++) {
    for (let step = 0; step < n1; step++) {
      // To and fro: the point before is always beside this one.
      const i = j % 2 ? n1 - 1 - step : step;
      const p = j * n1 + i;
      const vals = [axes[0].values[i], axes[1] ? axes[1].values[j] : 0];
      let y = Float64Array.from(cur);
      let ok = false;
      try { ok = settle(y, vals); } catch (e) { ok = false; }
      if (!ok) {
        y = Float64Array.from(base);
        lnGamma.fill(0);
        try { ok = settle(y, vals); } catch (e) { ok = false; }
      }
      if (ok) {
        cur = y;
        states.set(y.subarray(b, b + ns), p * ns);
        model.quantitiesAt(y, t, cell, which, qOut);
        quant.set(qOut, p * nq);
      } else failed++;
      done++;
      if (post && Date.now() - lastReport > 250) {
        lastReport = Date.now();
        post({ type: 'progress', id: msg.id, frac: done / npts, done, npts });
      }
    }
  }
  return { type: 'diagram', id: msg.id, n1, n2, x: axes[0].values, y: axes[1] ? axes[1].values : null, ns,
    species: model.speciesNames, states, nq, keys: model.quantities.map((q) => q.key), quant, failed, t, cell, pHHeld };
}

function handleRtmMessage(msg, post) {
  const id = msg.id;
  if (msg.type === 'capabilities') {
    post({ type: 'capabilities', id, solvers: rtmSolvers() });
    return;
  }
  if (msg.type === 'diagram') {
    try {
      const reply = rtmDiagram(msg, post);
      post(reply, reply.states ? [reply.states.buffer, reply.quant.buffer] : []);
    } catch (e) {
      post({ type: 'error', id, stage: 'diagram', error: rtmErrorMessage(e) });
    }
    return;
  }
  if (msg.type === 'quantities') {
    try {
      const reply = rtmQuantities(msg);
      post(reply, reply.values ? [reply.values.buffer] : []);
    } catch (e) {
      post({ type: 'error', id, stage: 'quantities', error: rtmErrorMessage(e) });
    }
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
      // Made in concentrations: a model holding its equilibria keeps ln C.
      const c0 = model.toConcentrations ? model.toConcentrations(y0) : y0;
      const c1 = Float64Array.from(c0, (v, i) => (v > 0 ? v : 1e-9 * (1 + (i % 5))));
      const y1 = model.fromConcentrations ? model.fromConcentrations(c1) : c1;
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
      normControl: !!s.normControl,
      // The rest of facsimile.html's settings, which this page now offers too.
      maxOrder: s.maxOrder || 5,
      minOrder: s.minOrder || 1,
      hmax: s.hmax > 0 ? s.hmax : undefined,
      h0: s.h0 > 0 ? s.h0 : undefined,
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
    // within a point, which is the order the model itself uses. A model that
    // holds its equilibria keeps logarithms and totals in its state; what is
    // stored is the concentrations, the shape every other model has.
    const n = res.t.length;
    const width = model.stateWidth || model.nspecies;
    const states = rtmConcentrations(model, res.y, n, width, res.t);
    const heldDrift = rtmHoldFixed(model, states, n, width);
    // Each stored point's cells' temperatures, where they go with the cell or the time: the PHREEQC tab reads them.
    const temps = rtmTemperatures(model, res.t, n);
    // Kept for the quantities the page asks for (rtmQuantities): copies, as what is posted is handed over.
    const runKey = ++rtmRunCount;
    rtmKept = { key: runKey, text: msg.text, model, t: Float64Array.from(res.t), states: Float64Array.from(states), n, width };
    const payload = {
      type: 'result',
      id,
      runKey,
      t: res.t,
      states,
      temps,
      n,
      width,
      model: rtmSummary(model),
      stats: res.stats,
      heldDrift,
      // A mineral dissolving away or precipitating, where and when.
      events: (res.events || []).map((e) => ({ t: e.t, what: e.expr })),
      seconds: (Date.now() - started) / 1000,
    };
    post(payload, temps ? [res.t.buffer, states.buffer, temps.buffer] : [res.t.buffer, states.buffer]);
  } catch (e) {
    const out = { type: 'error', id, stage: 'run', error: rtmErrorMessage(e) };
    // Hand back whatever was integrated before the failure, as facsimile does:
    // the part that did run is usually where the trouble can be seen.
    if (e.partial && e.partial.t && e.partial.t.length > 1) {
      const n = e.partial.t.length;
      const width = model.stateWidth || model.nspecies;
      const states = rtmConcentrations(model, e.partial.y, n, width, e.partial.t);
      const heldDrift = rtmHoldFixed(model, states, n, width);
      const runKey = ++rtmRunCount;
      rtmKept = { key: runKey, text: msg.text, model, t: Float64Array.from(e.partial.t), states: Float64Array.from(states), n, width };
      out.partial = {
        runKey, t: e.partial.t, states, n, width, model: rtmSummary(model), stats: e.partial.stats || {},
        heldDrift, temps: rtmTemperatures(model, e.partial.t, n),
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
