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
    // What flows in at the left, each species' left= or else its start: the water an inverse model can start from.
    inflow: model.transport ? model.speciesList.map((sp) => (sp.left == null ? sp.initial : sp.left)) : null,
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
  left it -- held at each point of a range of pH, pe or Eh, a species'
  activity, a cation's activity over the hydrogen ion's, or an element's
  total, or of two such ranges, and speciated there by the
  model's own relations (RtmModel.speciate), as PhreePlot does with
  PHREEQC's. Each point starts from the one before it, the grid walked to and
  fro so that the one before is always beside it, and from the water itself
  where that does not settle. An activity is held through the concentration
  that gives it, the activity coefficient taken again from the speciation
  until it stops moving. Returns each point's concentrations in that cell and
  every quantity of the model there; a point that did not settle is NaN.
*/
const RTM_DIAGRAM_KINDS = { pH: 'pH', pe: 'pe', Eh: 'Eh', la: 'log activity', ratio: 'log activity ratio', tot: 'log total' };

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
  // An Eh is the electron's pe in volts: held at the pe it is at the water's temperature (RtmModel.ehPerPe).
  if (ax.kind === 'pe' || ax.kind === 'Eh') {
    if (!(model.electron >= 0)) throw new Error(`A${ax.kind === 'Eh' ? 'n Eh' : ' pe'} is the electron's, and the model has none: e- electron.`);
    return { kind: ax.kind, k: model.electron, values, sign: -1 };
  }
  if (ax.kind === 'la') {
    const k = model.speciesNames.indexOf(ax.species);
    if (k < 0 || !solute(k)) throw new Error(`log a(${ax.species}): it is no species dissolved in the water.`);
    return { kind: 'la', k, values, sign: 1, species: ax.species };
  }
  /*
    log a(X)/a(H+)^z, X a cation of charge z, as the axes of Garrels and
    Christ's silicate diagrams are: X held at the activity that gives the
    ratio over the H+ there -- the pH of the other axis, or the water's,
    held where it has it.
  */
  if (ax.kind === 'ratio') {
    const k = model.speciesNames.indexOf(ax.species);
    const h = model.speciesNames.indexOf('H+');
    if (k < 0 || !solute(k)) throw new Error(`log a(${ax.species})/a(H+): it is no species dissolved in the water.`);
    if (h < 0 || !solute(h)) throw new Error('An activity ratio is over the activity of H+, and the model has no H+ in its water.');
    const z = RtmModel.chargeOf(ax.species);
    if (!(z > 0) || k === h) throw new Error(`log a(${ax.species})/a(H+): a ratio is a cation's, over H+ to the power of its charge.`);
    return { kind: 'ratio', k, z, values, sign: 1, species: ax.species };
  }
  if (ax.kind === 'tot') {
    const comp = (model.composition && model.composition.elements || []).find((e) => e.el === ax.species);
    if (!comp) throw new Error(`The total of ${ax.species}: no species of the model has any.`);
    const weights = new Float64Array(ns);
    for (const [k, n] of comp.terms) weights[k] = n;
    return { kind: 'tot', weights, values, name: ax.species };
  }
  throw new Error(`"${ax.kind}" is no axis of a diagram: pH, pe, Eh, la, ratio or tot.`);
}

/**
 * What a diagram holds and how a point of it settles, shared by the grid and
 * by the boundaries found between its points: the model, the water it starts
 * from, the axes and the species held. Null where it is of a run that is not
 * kept, which the page then sends.
 */
function rtmDiagramSetup(msg) {
  let model;
  let base;
  let t = 0;
  if (msg.at === 'end') {
    const run = rtmRunFor(msg);
    if (!run) return null;
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
    the pH would go with that choice, which is no choice of the reader's. An
    activity ratio without the pH holds it there too: the ratio is over it.
  */
  const holds = axes.map((ax, a) => ({ ax, a }));
  let pHHeld = null;
  const iH = model.speciesNames.indexOf('H+');
  if (model.thermoAt) model.thermoAt(t);
  // Volts to a pe, at the cell's temperature as the water is taken.
  const ehPe = RtmModel.ehPerPe((model.temperatures ? model.temperatures(t)[cell] : 25) + 273.15);
  const pHAxis = axes.findIndex((ax) => ax.kind === 'pH');
  // A pH asked for, where nothing varied is the pH: held there, as PHREEQC's SOLUTION holds the pH it is given.
  if (msg.pHAt !== undefined && msg.pHAt !== null) {
    if (pHAxis >= 0) throw new Error('The pH is what is varied: it cannot be held as well.');
    if (!(iH >= 0 && rtmSolute(model, iH))) throw new Error('A pH held is the activity of H+, and the model has no H+ in its water.');
    if (!Number.isFinite(msg.pHAt)) throw new Error('The pH to hold the water at is a number.');
    pHHeld = msg.pHAt;
    held[iH] = true;
    holds.push({ ax: { kind: 'pH', k: iH }, a: -1 });
  } else if ((totAxis >= 0 || axes.some((ax) => ax.kind === 'ratio')) && pHAxis < 0 && iH >= 0 && rtmSolute(model, iH) && !held[iH]) {
    const g0 = new Float64Array(ns);
    if (model.act) RtmModel.activityAt(model.act, base, b, g0, new Float64Array(ns), cell);
    pHHeld = -(Math.log(base[b + iH]) + g0[iH]) / Math.LN10;
    held[iH] = true;
    holds.push({ ax: { kind: 'pH', k: iH }, a: -1 });
  }
  const lnG = new Float64Array(ns);
  const lnD = new Float64Array(ns);
  /*
    The water y (every cell; this one is speciated) held at vals, from each
    held species' ln gamma as lnGamma has it: both are moved to the answer.
    False where it does not settle.
  */
  const settle = (y, vals, lnGamma) => {
    for (let it = 0; it < 40; it++) {
      holds.forEach(({ ax, a }, h) => {
        const v = a >= 0 ? vals[a] : pHHeld;
        if (ax.kind === 'pe') y[b + ax.k] = 10 ** -v;
        else if (ax.kind === 'Eh') y[b + ax.k] = 10 ** -(v / ehPe);
        else if (ax.kind === 'pH') y[b + ax.k] = 10 ** -v * Math.exp(-lnGamma[h]);
        else if (ax.kind === 'la') y[b + ax.k] = 10 ** v * Math.exp(-lnGamma[h]);
        else if (ax.kind === 'ratio') y[b + ax.k] = 10 ** (v - ax.z * (pHAxis >= 0 ? vals[pHAxis] : pHHeld)) * Math.exp(-lnGamma[h]);
      });
      const r = RtmModel.speciate(model, y, { fixed: held, cells: [cell], t,
        total: totAxis >= 0 ? { weights: axes[totAxis].weights, value: 10 ** vals[totAxis], name: axes[totAxis].name } : undefined });
      if (!r.cells.length || !r.cells[0].converged) return false;
      y.set(r.y.subarray(b, b + ns), b);
      if (!model.act) return true;
      RtmModel.activityAt(model.act, y, b, lnG, lnD, cell);
      let moved = 0;
      holds.forEach(({ ax }, h) => {
        if (ax.kind !== 'pH' && ax.kind !== 'la' && ax.kind !== 'ratio') return;
        moved = Math.max(moved, Math.abs(lnG[ax.k] - lnGamma[h]));
        lnGamma[h] = lnG[ax.k];
      });
      if (moved < 1e-11) return true;
    }
    return false;
  };
  /** Each held species' ln gamma in the water y: where a point near it starts. */
  const gammas = (y) => {
    const out = holds.map(() => 0);
    if (!model.act) return out;
    RtmModel.activityAt(model.act, y, b, lnG, lnD, cell);
    holds.forEach(({ ax }, h) => { if (ax.kind === 'pH' || ax.kind === 'la' || ax.kind === 'ratio') out[h] = lnG[ax.k]; });
    return out;
  };
  return { model, base, t, b, cell, ns, axes, holds, pHHeld, settle, gammas, ehPe };
}

function rtmDiagram(msg, post) {
  const S = rtmDiagramSetup(msg);
  if (!S) return { type: 'diagram', id: msg.id, missing: true };
  const { model, base, t, b, cell, ns, axes, holds, pHHeld, settle } = S;
  const n1 = axes[0].values.length;
  const n2 = axes[1] ? axes[1].values.length : 1;
  const npts = n1 * n2;
  const nq = model.quantities.length;
  const which = Int32Array.from({ length: nq }, (_, q) => q);
  const states = new Float64Array(npts * ns).fill(NaN);
  const quant = new Float64Array(npts * nq).fill(NaN);
  const qOut = new Float64Array(nq);
  // Each held species' ln gamma, carried from point to point.
  const lnGamma = holds.map(() => 0);
  let failed = 0;
  let cur = Float64Array.from(base);
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
      try { ok = settle(y, vals, lnGamma); } catch (e) { ok = false; }
      if (!ok) {
        y = Float64Array.from(base);
        lnGamma.fill(0);
        try { ok = settle(y, vals, lnGamma); } catch (e) { ok = false; }
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
  /*
    A point that settled neither from the point before it nor from the
    water itself, tried again from the point after it: the walk back the
    other way. The walk starts at one end of the range, which may be far
    from the water -- pe -10 from a water at pe 4, its sulfate and
    carbonate to be turned into sulfide and methane in one go -- and every
    point after it then starts from the water too, until one is near enough;
    from that one back, each is a step from a point settled beside it.
  */
  if (failed) {
    let near = null;
    for (let jj = 0; jj < n2; jj++) {
      const j = n2 - 1 - jj;
      for (let step = 0; step < n1; step++) {
        const i = j % 2 ? step : n1 - 1 - step;
        const p = j * n1 + i;
        if (!Number.isNaN(states[p * ns])) { near = states.subarray(p * ns, (p + 1) * ns); continue; }
        if (!near) continue;
        const y = Float64Array.from(base);
        y.set(near, b);
        let ok = false;
        try { ok = settle(y, [axes[0].values[i], axes[1] ? axes[1].values[j] : 0], S.gammas(y)); } catch (e) { ok = false; }
        if (!ok) continue;
        states.set(y.subarray(b, b + ns), p * ns);
        model.quantitiesAt(y, t, cell, which, qOut);
        quant.set(qOut, p * nq);
        near = states.subarray(p * ns, (p + 1) * ns);
        failed--;
      }
    }
  }
  return { type: 'diagram', id: msg.id, n1, n2, x: axes[0].values, y: axes[1] ? axes[1].values : null, ns,
    species: model.speciesNames, states, nq, keys: model.quantities.map((q) => q.key), quant, failed, t, cell, pHHeld };
}

/*
  THE BOUNDARIES OF A MAP: where two fields of a diagram over two things
  meet -- the species that holds most of an element, or the phase furthest
  over saturation -- found between each two neighbouring points of the grid
  whose fields differ, by holding the water at points between them and
  speciating it again, as PhreePlot finds PHREEQC's boundaries rather than
  colouring a grid. Along the edge, false position on what tells the two
  fields apart -- the log of the one's amount of the element over the
  other's, or the difference of their saturation indices -- Illinois' way,
  to 1e-10 in the axis' units; a third field met on the way is two
  boundaries. Where three fields meet in one square of the grid, the point
  they share is solved for, Newton's way, the two differences zero at once.
  Each square is then cut along its boundaries into the pieces of its
  fields, and the pieces of a field joined by dropping the sides two of them
  share: what is left, followed round, is the field's outline.
*/
const RTM_BOUND_TOL = 1e-10;
// Two fields within this of each other (a log of amounts, or saturation indices) are a tie, the first of them taken:
// a point on a boundary that lies along a grid line is then of one field for certain, not of whichever the rounding says.
const RTM_BOUND_TIE = 1e-10;

/**
 * What tells the fields of a map apart: each point's field, and between two
 * fields a difference that is positive in the first, negative in the second
 * and zero where they meet.
 *   predominance: { terms: [[k, n], ...] } -- the species of an element and
 *     the element's count in each; the field is the one holding most of it.
 *   phase: { keys: ['SI(Calcite)', ...] } -- the field is the phase whose
 *     saturation index is the largest, if that is zero or more, else the one
 *     past them all: none. A mineral of the model's own, held at saturation
 *     where there is any of it, its SI zero to the rounding, counts as at it
 *     there whatever the rounding says.
 *     With per: [n, ...], each phase's count of an element, each index is
 *     over its count -- the phases weighed per mole of aluminium, say -- and
 *     the field is the largest, saturated or not: the phase the others would
 *     turn into, the element kept in the solids, whatever is dissolved of
 *     it, as Garrels and Christ's silicate diagrams are drawn. No none.
 */
function rtmMapCriterion(model, crit, base, b, t, cell) {
  if (crit.kind === 'predominance') {
    const terms = crit.terms;
    if (!Array.isArray(terms) || terms.length < 2) throw new Error('A predominance map needs two species of the element or more.');
    const labelOf = (c) => {
      let best = -1;
      let most = -Infinity;
      for (let q = 0; q < terms.length; q++) {
        const v = terms[q][1] * c[terms[q][0]];
        if (!Number.isFinite(v)) return -1;
        if (v > most && (best < 0 || !(Math.log(v) - Math.log(most) <= RTM_BOUND_TIE))) { most = v; best = q; }
      }
      return best;
    };
    const disc = (c, a, z) => Math.log(terms[a][1] * c[terms[a][0]]) - Math.log(terms[z][1] * c[terms[z][0]]);
    return { labelOf, disc, n: terms.length };
  }
  if (crit.kind === 'phase') {
    const which = Int32Array.from(crit.keys.map((key) => model.quantities.findIndex((q) => q.key === key)));
    if (!which.length || [...which].some((x) => x < 0)) throw new Error('The phases of the map are not the model\'s.');
    const none = which.length;
    const per = Array.isArray(crit.per) ? crit.per.map(Number) : null;
    if (per && (per.length !== which.length || per.some((n) => !(n > 0 && Number.isFinite(n))))) {
      throw new Error('Each phase weighed by its count of the element: a positive number for each.');
    }
    const mineral = crit.keys.map((key) => {
      const k = model.speciesNames.indexOf(key.slice(3, -1));
      return k >= 0 && model.speciesList[k].mineral ? k : -1;
    });
    const y = Float64Array.from(base);
    const out = new Float64Array(which.length);
    // Each phase's saturation index, a mineral there taken as at saturation.
    const score = new Float64Array(which.length);
    const scores = (c) => {
      y.set(c, b);
      model.quantitiesAt(y, t, cell, which, out);
      for (let q = 0; q < out.length; q++) {
        score[q] = (mineral[q] >= 0 && c[mineral[q]] > 0 ? Math.max(0, out[q]) : out[q]) / (per ? per[q] : 1);
      }
      return score;
    };
    const labelOf = (c) => {
      const s = scores(c);
      let best = -1;
      let most = -Infinity;
      for (let q = 0; q < s.length; q++) if (Number.isFinite(s[q]) && s[q] > most + (best < 0 ? 0 : RTM_BOUND_TIE)) { most = s[q]; best = q; }
      if (best < 0) return -1;
      return per || most >= 0 ? best : none;
    };
    const disc = (c, a, z) => {
      const s = scores(c);
      return (a === none ? 0 : s[a]) - (z === none ? 0 : s[z]);
    };
    return { labelOf, disc, n: per ? none : none + 1 };
  }
  throw new Error(`"${crit.kind}" is no map to find the boundaries of: predominance or phase.`);
}

/*
  A REDOX LADDER: where each of the model's couples turns over at a pH --
  the pe, or the Eh, at which the water holds as much of the element in the
  couple's oxidised state as in its reduced one, the two states' amounts in
  the water or in the whole cell -- as the textbooks' ladders place them,
  but for this water: its totals, its complexes and its activity model.
  Found along the diagram's pe or Eh at the pH held, between each two
  neighbouring points whose sign of the log of the one amount over the
  other differs, by holding the water at points between them and speciating
  it again: false position, Illinois' way, to 1e-10 in the axis' units, and
  halving where an amount is none -- a mineral not there yet.
*/
function rtmDiagramLadder(msg, post) {
  const S = rtmDiagramSetup(msg);
  if (!S) return { type: 'diagramLadder', id: msg.id, missing: true };
  const { model, base, b, ns, axes, holds, settle, gammas, pHHeld, ehPe } = S;
  if (axes.length !== 1 || (axes[0].kind !== 'pe' && axes[0].kind !== 'Eh') || pHHeld === null) {
    throw new Error('A redox ladder is along pe or Eh alone, the pH held.');
  }
  const xs = axes[0].values;
  const n1 = xs.length;
  const grid = msg.grid;
  if (!grid || grid.length !== n1 * ns) throw new Error('The points sent are not the diagram\'s.');
  const couples = msg.couples || [];
  const amount = (c, terms) => {
    let s = 0;
    for (const [k, n] of terms) s += n * Math.max(0, c[k]);
    return s;
  };
  // The log of the oxidised state's amount over the reduced one's: zero where the couple turns over.
  const disc = (c, cp) => Math.log(amount(c, cp.hi)) - Math.log(amount(c, cp.lo));
  const y = new Float64Array(base.length);
  const at = (v, near) => {
    for (const start of near ? [near, null] : [null]) {
      y.set(base);
      if (start) y.set(start, b);
      const lnGamma = start ? gammas(y) : holds.map(() => 0);
      let ok = false;
      try { ok = settle(y, [v], lnGamma); } catch (e) { ok = false; }
      if (ok) return y.slice(b, b + ns);
    }
    return null;
  };
  let unsolved = 0;
  let lastReport = Date.now();
  const rungs = couples.map((cp, q) => {
    const g = Array.from({ length: n1 }, (_, i) => disc(grid.subarray(i * ns, (i + 1) * ns), cp));
    const roots = [];
    for (let i = 0; i + 1 < n1; i++) {
      let gLo = g[i];
      let gHi = g[i + 1];
      if (Number.isNaN(gLo) || Number.isNaN(gHi) || gLo === gHi || Math.sign(gLo) === Math.sign(gHi)) continue;
      if (gLo === 0) { roots.push(xs[i]); continue; }
      let lo = xs[i];
      let hi = xs[i + 1];
      let cLo = grid.subarray(i * ns, (i + 1) * ns);
      let cHi = grid.subarray((i + 1) * ns, (i + 2) * ns);
      const up = gLo < 0;
      let side = 0;
      let solved = true;
      for (let it = 0; it < 200 && Math.abs(hi - lo) > RTM_BOUND_TOL; it++) {
        let v = (lo + hi) / 2;
        if (Number.isFinite(gLo) && Number.isFinite(gHi)) {
          const f = lo + (hi - lo) * (gLo / (gLo - gHi));
          if (f > Math.min(lo, hi) && f < Math.max(lo, hi)) v = f;
        }
        const c = at(v, Math.abs(v - lo) <= Math.abs(hi - v) ? cLo : cHi);
        if (!c) { solved = false; break; }
        const gv = disc(c, cp);
        if (Number.isNaN(gv)) { solved = false; break; }
        // Illinois: an end kept twice running has its difference halved, so that both ends close in.
        if ((gv < 0) === up) {
          lo = v; cLo = c; gLo = gv;
          if (side === 1) gHi /= 2;
          side = 1;
        } else {
          hi = v; cHi = c; gHi = gv;
          if (side === -1) gLo /= 2;
          side = -1;
        }
        if (gv === 0) { lo = v; hi = v; }
      }
      if (!solved) unsolved++;
      roots.push((lo + hi) / 2);
    }
    if (post && Date.now() - lastReport > 250) {
      lastReport = Date.now();
      post({ type: 'progress', id: msg.id, frac: (q + 1) / couples.length, done: q + 1, npts: couples.length });
    }
    // Where it does not turn over in the range: its sign at either end -- above it, below it, or none of the element.
    const finite = g.filter((v) => !Number.isNaN(v));
    return { roots, first: finite.length ? finite[0] : null, last: finite.length ? finite[finite.length - 1] : null };
  });
  // The water's own pe, and its pH, where it has an electron and an H+.
  const iH = model.speciesNames.indexOf('H+');
  const lnG = new Float64Array(ns);
  if (model.act) RtmModel.activityAt(model.act, base, b, lnG, new Float64Array(ns), S.cell);
  const waterPe = model.electron >= 0 && base[b + model.electron] > 0 ? -Math.log10(base[b + model.electron]) : null;
  const waterPH = iH >= 0 && base[b + iH] > 0 ? -(Math.log(base[b + iH]) + lnG[iH]) / Math.LN10 : null;
  return { type: 'diagramLadder', id: msg.id, rungs, unsolved, pHHeld, ehPe, waterPe, waterPH };
}

function rtmDiagramBounds(msg, post) {
  const S = rtmDiagramSetup(msg);
  if (!S) return { type: 'diagramBounds', id: msg.id, missing: true };
  const { model, base, t, b, cell, ns, axes, holds, settle, gammas } = S;
  if (axes.length !== 2) throw new Error('Boundaries are a map\'s: two things varied.');
  const xs = axes[0].values;
  const ys = axes[1].values;
  const n1 = xs.length;
  const n2 = ys.length;
  const grid = msg.grid;
  if (!grid || grid.length !== n1 * n2 * ns) throw new Error('The points sent are not the diagram\'s.');
  const crit = rtmMapCriterion(model, msg.criterion, base, b, t, cell);
  const L = new Int32Array(n1 * n2);
  for (let p = 0; p < n1 * n2; p++) L[p] = crit.labelOf(grid.subarray(p * ns, (p + 1) * ns));
  const waterAt = (p) => grid.subarray(p * ns, (p + 1) * ns);

  // The water held at a point, from the water `near` it, or else from the water the diagram starts from.
  let evals = 0;
  const y = new Float64Array(base.length);
  const at = (vals, near) => {
    for (const start of near ? [near, null] : [null]) {
      y.set(base);
      if (start) y.set(start, b);
      const lnGamma = start ? gammas(y) : holds.map(() => 0);
      let ok = false;
      evals++;
      try { ok = settle(y, vals, lnGamma); } catch (e) { ok = false; }
      if (ok) {
        const c = y.slice(b, b + ns);
        return { c, label: crit.labelOf(c) };
      }
    }
    return null;
  };

  // The edges whose two ends differ: along x, (i, j) to (i + 1, j); along y, (i, j) to (i, j + 1).
  const todo = [];
  for (let j = 0; j < n2; j++) {
    for (let i = 0; i < n1; i++) {
      const p = j * n1 + i;
      if (i + 1 < n1 && L[p] !== L[p + 1]) todo.push([0, i, j]);
      if (j + 1 < n2 && L[p] !== L[p + n1]) todo.push([1, i, j]);
    }
  }
  let unsolved = 0;
  let lastReport = Date.now();
  const report = (done) => {
    if (!post || Date.now() - lastReport < 250) return;
    lastReport = Date.now();
    post({ type: 'progress', id: msg.id, frac: done / Math.max(1, todo.length), done, npts: todo.length });
  };

  /** The boundaries along one edge, in order along it: [{ s, x, y, from, to, solved }]. */
  const crossingsOf = (dir, i, j) => {
    const p0 = j * n1 + i;
    const p1 = dir === 0 ? p0 + 1 : p0 + n1;
    const lo0 = dir === 0 ? xs[i] : ys[j];
    const hi0 = dir === 0 ? xs[i + 1] : ys[j + 1];
    const width = Math.abs(hi0 - lo0);
    const pointAt = (s) => (dir === 0 ? [lo0 + s * (hi0 - lo0), ys[j]] : [xs[i], lo0 + s * (hi0 - lo0)]);
    const found = [];
    const between = (lo, eLo, hi, eHi, depth) => {
      const la = eLo.label;
      const lb = eHi.label;
      if (la < 0 || lb < 0) { found.push({ s: (lo + hi) / 2, from: la, to: lb, solved: false }); return; }
      let gLo = crit.disc(eLo.c, la, lb);
      let gHi = crit.disc(eHi.c, la, lb);
      let side = 0;
      for (let it = 0; it < 200 && (hi - lo) * width > RTM_BOUND_TOL; it++) {
        // False position where both differences are of their side's sign, else halfway.
        let s = (lo + hi) / 2;
        if (Number.isFinite(gLo) && Number.isFinite(gHi) && gLo > 0 && gHi < 0) {
          const f = lo + (hi - lo) * (gLo / (gLo - gHi));
          if (f > lo && f < hi) s = f;
        }
        const e = at(pointAt(s), s - lo <= hi - s ? eLo.c : eHi.c);
        if (!e) { unsolved++; found.push({ s, from: la, to: lb, solved: false }); return; }
        if (e.label !== la && e.label !== lb) {
          // A third field between them: a boundary either side of it.
          if (depth < 8 && e.label >= 0) {
            between(lo, eLo, s, e, depth + 1);
            between(s, e, hi, eHi, depth + 1);
          } else { unsolved++; found.push({ s, from: la, to: lb, solved: false }); }
          return;
        }
        // Which side of the boundary by the sign of the difference, and where it is zero -- a tie, or a mineral there at
        // saturation -- by the field.
        const g = crit.disc(e.c, la, lb);
        // Illinois: an end kept twice running has its difference halved, so that both ends close in.
        if (g > 0 || (!(g < 0) && e.label === la)) {
          lo = s; eLo = e; gLo = g;
          if (side === 1) gHi /= 2;
          side = 1;
        } else {
          hi = s; eHi = e; gHi = g;
          if (side === -1) gLo /= 2;
          side = -1;
        }
      }
      found.push({ s: (lo + hi) / 2, from: la, to: lb, solved: true });
    };
    between(0, { c: waterAt(p0), label: L[p0] }, 1, { c: waterAt(p1), label: L[p1] }, 0);
    return found.map((f) => {
      const [x, yv] = pointAt(f.s);
      return { ...f, x, y: yv };
    });
  };
  const cross = [new Map(), new Map()];
  todo.forEach(([dir, i, j], q) => {
    cross[dir].set(j * n1 + i, crossingsOf(dir, i, j));
    report(q + 1);
  });

  /*
    The point where three fields meet in square (i, j): both differences
    zero, Newton's way, from each guess in turn -- the middle of the
    crossings, then each crossing, where both amounts of a mineral's
    boundary are there to take the log of. A step that lands where a
    difference has no value (a mineral gone) is halved. Null if no guess
    finds it inside the square.
  */
  const triple = (i, j, labs, guesses) => {
    const [a, m, z] = labs;
    const wx = Math.abs(xs[i + 1] - xs[i]);
    const wy = Math.abs(ys[j + 1] - ys[j]);
    const hx = 1e-6 * (xs[i + 1] - xs[i]);
    const hy = 1e-6 * (ys[j + 1] - ys[j]);
    const res = (ev) => [crit.disc(ev.c, a, m), crit.disc(ev.c, m, z)];
    const finite = (r) => Number.isFinite(r[0]) && Number.isFinite(r[1]);
    // The differences' change along one axis, forward or else backward.
    const slope = (p, e, r, d, h) => {
      for (const sg of [1, -1]) {
        const q = d === 0 ? [p[0] + sg * h, p[1]] : [p[0], p[1] + sg * h];
        const ev = at(q, e.c);
        const rq = ev && res(ev);
        if (rq && finite(rq)) return [(rq[0] - r[0]) / (sg * h), (rq[1] - r[1]) / (sg * h)];
      }
      return null;
    };
    const newton = (guess) => {
      let p = [guess.x, guess.y];
      let e = at(p, waterAt(j * n1 + i));
      let r = e && res(e);
      if (!r || !finite(r)) return null;
      for (let it = 0; it < 30; it++) {
        if (Math.abs(r[0]) < 1e-13 && Math.abs(r[1]) < 1e-13) break;
        const cx = slope(p, e, r, 0, hx);
        const cy = slope(p, e, r, 1, hy);
        if (!cx || !cy) return null;
        const det = cx[0] * cy[1] - cy[0] * cx[1];
        if (!Number.isFinite(det) || det === 0) return null;
        const dx = (-r[0] * cy[1] + r[1] * cy[0]) / det;
        const dy = (-r[1] * cx[0] + r[0] * cx[1]) / det;
        if (!(Math.abs(dx) < 4 * wx && Math.abs(dy) < 4 * wy)) return null;
        let lam = 1;
        let moved = null;
        for (let bt = 0; bt < 30 && !moved; bt++, lam /= 2) {
          const q = [p[0] + lam * dx, p[1] + lam * dy];
          const ev = at(q, e.c);
          const rq = ev && res(ev);
          if (rq && finite(rq)) moved = { q, ev, rq };
        }
        if (!moved) return null;
        p = moved.q;
        e = moved.ev;
        r = moved.rq;
        if (Math.abs(lam * dx) <= 2e-13 * wx && Math.abs(lam * dy) <= 2e-13 * wy) break;
      }
      if (!(Math.abs(r[0]) < 1e-9 && Math.abs(r[1]) < 1e-9) || !labs.includes(e.label)) return null;
      const inside = (v, u, w) => v >= Math.min(u, w) - 1e-9 * Math.abs(w - u) && v <= Math.max(u, w) + 1e-9 * Math.abs(w - u);
      if (!inside(p[0], xs[i], xs[i + 1]) || !inside(p[1], ys[j], ys[j + 1])) return null;
      const clamp = (v, u, w) => Math.min(Math.max(v, Math.min(u, w)), Math.max(u, w));
      return { x: clamp(p[0], xs[i], xs[i + 1]), y: clamp(p[1], ys[j], ys[j + 1]) };
    };
    for (const guess of guesses) {
      const found = newton(guess);
      if (found) return found;
    }
    return null;
  };

  // Each square cut into the pieces of its fields; the boundaries between them as segments.
  const pieces = [];
  const segs = [];
  const junctions = [];
  for (let j = 0; j + 1 < n2; j++) {
    for (let i = 0; i + 1 < n1; i++) {
      const corner = (ii, jj) => ({ key: `c${ii}_${jj}`, x: xs[ii], y: ys[jj] });
      const along = (dir, ii, jj, rev) => {
        const its = (cross[dir].get(jj * n1 + ii) || []).map((c, q) => ({ key: `${dir ? 'v' : 'h'}${ii}_${jj}_${q}`, x: c.x, y: c.y,
          cross: true, from: rev ? c.to : c.from, to: rev ? c.from : c.to }));
        return rev ? its.reverse() : its;
      };
      // Round the square: along its bottom, up its right side, back along its top and down its left.
      const walk = [corner(i, j), ...along(0, i, j, false), corner(i + 1, j), ...along(1, i + 1, j, false),
        corner(i + 1, j + 1), ...along(0, i, j + 1, true), corner(i, j + 1), ...along(1, i, j, true)];
      const X = [];
      walk.forEach((w, q) => { if (w.cross) X.push(q); });
      const k = X.length;
      if (!k) { pieces.push({ label: L[j * n1 + i], verts: walk }); continue; }
      // Arc m runs from crossing m to the next, round the square; its field is what crossing m goes to.
      const arcs = X.map((q) => walk[q].to);
      const arc = (m) => {
        const out = [];
        const end = X[(m + 1) % k];
        for (let q = X[m]; ; q = (q + 1) % walk.length) {
          out.push(walk[q]);
          if (q === end && out.length > 1) break;
        }
        return out;
      };
      const centre = () => ({ x: X.reduce((sum, q) => sum + walk[q].x, 0) / k, y: X.reduce((sum, q) => sum + walk[q].y, 0) / k });
      // Four crossings: the field on two opposite arcs runs through the square, and the other two are cut off its corners.
      let through = -1;
      if (k === 4) {
        const even = arcs[0] === arcs[2];
        const odd = arcs[1] === arcs[3];
        if (even && odd) {
          const e = at([(xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2], waterAt(j * n1 + i));
          through = e && e.label === arcs[0] ? 0 : e && e.label === arcs[1] ? 1 : -1;
        } else if (even) through = 0;
        else if (odd) through = 1;
      }
      if (k === 2) {
        pieces.push({ label: arcs[0], verts: arc(0) }, { label: arcs[1], verts: arc(1) });
        segs.push({ u: walk[X[0]], v: walk[X[1]], a: arcs[1], b: arcs[0] });
      } else if (through >= 0) {
        const [m0, m1, m2, m3] = [through, through + 1, through + 2, (through + 3) % 4];
        pieces.push({ label: arcs[m1], verts: arc(m1) }, { label: arcs[m3], verts: arc(m3) },
          { label: arcs[m0], verts: [...arc(m0), ...arc(m2)] });
        segs.push({ u: walk[X[m1]], v: walk[X[m2]], a: arcs[m1], b: arcs[m0] },
          { u: walk[X[m3]], v: walk[X[m0]], a: arcs[m3], b: arcs[m0] });
      } else {
        // Three fields, or more: each one's arc to the point they meet at.
        const three = k === 3 && new Set(arcs).size === 3 && arcs.every((a) => a >= 0);
        const solved = three ? triple(i, j, arcs, [centre(), ...X.map((q) => walk[q])]) : null;
        const J = solved || centre();
        const jv = { key: `j${i}_${j}`, x: J.x, y: J.y };
        junctions.push({ x: J.x, y: J.y, labels: [...new Set(arcs)], solved: !!solved });
        for (let m = 0; m < k; m++) {
          pieces.push({ label: arcs[m], verts: [...arc(m), jv] });
          segs.push({ u: walk[X[m]], v: jv, a: arcs[(m + k - 1) % k], b: arcs[m] });
        }
      }
    }
  }

  // A field's pieces joined: the sides two of its pieces share go, and what is left is followed round.
  const byField = new Map();
  for (const pc of pieces) {
    if (pc.label < 0) continue;
    let F = byField.get(pc.label);
    if (!F) byField.set(pc.label, (F = { edges: new Map(), at: new Map() }));
    const vs = pc.verts;
    for (let q = 0; q < vs.length; q++) {
      const u = vs[q];
      const v = vs[(q + 1) % vs.length];
      if (u.key === v.key) continue;
      F.at.set(u.key, u);
      const back = `${v.key}>${u.key}`;
      if (F.edges.has(back)) F.edges.delete(back);
      else F.edges.set(`${u.key}>${v.key}`, [u.key, v.key]);
    }
  }
  const area = (lx, ly) => {
    let sum = 0;
    for (let q = 0; q < lx.length; q++) {
      const r = (q + 1) % lx.length;
      sum += lx[q] * ly[r] - lx[r] * ly[q];
    }
    return sum / 2;
  };
  const fields = [];
  for (const [label, F] of byField) {
    const next = new Map();
    for (const [u, v] of F.edges.values()) {
      if (!next.has(u)) next.set(u, []);
      next.get(u).push(v);
    }
    const loops = [];
    for (const start of next.keys()) {
      while (next.get(start).length) {
        const keys = [start];
        let u = start;
        for (;;) {
          const outs = next.get(u);
          if (!outs || !outs.length) break;
          const v = outs.pop();
          if (v === start) break;
          keys.push(v);
          u = v;
        }
        // A point where the one before is (a boundary met at a corner) goes, and then, one at a time, each point in a
        // straight line between its neighbours, along the frame or a grid line: neither changes the area.
        const flat = (u, v, w) => (v.x - u.x) * (w.y - v.y) - (v.y - u.y) * (w.x - v.x) === 0;
        let pts = keys.map((key) => F.at.get(key));
        pts = pts.filter((pt, q) => q === 0 || pt.x !== pts[q - 1].x || pt.y !== pts[q - 1].y);
        while (pts.length > 1 && pts[0].x === pts[pts.length - 1].x && pts[0].y === pts[pts.length - 1].y) pts.pop();
        const kept = [];
        for (const pt of pts) {
          kept.push(pt);
          while (kept.length >= 3 && flat(kept[kept.length - 3], kept[kept.length - 2], kept[kept.length - 1])) kept.splice(kept.length - 2, 1);
        }
        for (let turn = 0; turn < 2; turn++) {
          while (kept.length >= 3 && flat(kept[kept.length - 2], kept[kept.length - 1], kept[0])) kept.pop();
          while (kept.length >= 3 && flat(kept[kept.length - 1], kept[0], kept[1])) kept.shift();
        }
        pts = kept;
        if (pts.length < 3) continue;
        const lx = pts.map((pt) => pt.x);
        const ly = pts.map((pt) => pt.y);
        loops.push({ x: lx, y: ly, area: area(lx, ly) });
      }
    }
    const net = loops.reduce((sum, lp) => sum + lp.area, 0);
    fields.push({ label, loops: loops.map(({ x, y: ly }) => ({ x, y: ly })), area: Math.abs(net),
      gross: Math.max(0, ...loops.map((lp) => Math.abs(lp.area))) });
  }

  // The boundaries as lines, one for each two fields and each stretch of it.
  const lines = [];
  const byPair = new Map();
  for (const sg of segs) {
    if (sg.a < 0 || sg.b < 0 || sg.a === sg.b) continue;
    const key = sg.a < sg.b ? `${sg.a}|${sg.b}` : `${sg.b}|${sg.a}`;
    if (!byPair.has(key)) byPair.set(key, []);
    byPair.get(key).push(sg);
  }
  for (const [key, list] of byPair) {
    const [a, z] = key.split('|').map(Number);
    const ends = new Map();
    list.forEach((sg, q) => {
      for (const e of [sg.u.key, sg.v.key]) {
        if (!ends.has(e)) ends.set(e, []);
        ends.get(e).push(q);
      }
    });
    const used = new Uint8Array(list.length);
    const follow = (startKey) => {
      const pts = [];
      let k = startKey;
      for (;;) {
        const q = (ends.get(k) || []).find((s) => !used[s]);
        if (q === undefined) break;
        used[q] = 1;
        const sg = list[q];
        if (!pts.length) pts.push(sg.u.key === k ? sg.u : sg.v);
        const other = sg.u.key === k ? sg.v : sg.u;
        pts.push(other);
        k = other.key;
      }
      if (pts.length > 1) lines.push({ a, b: z, x: pts.map((pt) => pt.x), y: pts.map((pt) => pt.y) });
    };
    // From the ends first, then round whatever closes on itself.
    for (const [e, qs] of ends) if (qs.length === 1 && !used[qs[0]]) follow(e);
    list.forEach((sg, q) => { if (!used[q]) follow(sg.u.key); });
  }
  const crossings = [...cross[0].values(), ...cross[1].values()].reduce((n, list) => n + list.length, 0);
  return { type: 'diagramBounds', id: msg.id, labels: L, fields, lines, junctions, crossings, unsolved,
    edges: todo.length, evals };
}

/*
  SWEEPS: the model run again for each value of what is varied -- a
  setting, a parameter, a species' start or what flows in -- or for each
  pair of values of two, as Gibbs Studio's parametric runs: the text with
  that number put in (RtmModel.withValue), compiled and run with the page's
  solver settings. Kept of each run: every species and quantity at one cell
  at each stored point, thinned to 400 points, and along the column at its
  end. A run that fails says why and the rest go on.
*/
function rtmSweep(msg, post) {
  const s = msg.solver || {};
  const vary = msg.vary;
  const lists = msg.values;
  // The runs: every value of one, every pair of two, or -- for the uncertainty bands -- the draws given, a value of each
  // thing varied to a run.
  const combos = msg.combos || (lists.length === 2 ? lists[1].flatMap((b) => lists[0].map((a) => [a, b])) : lists[0].map((a) => [a]));
  const runs = [];
  let names = null;
  let keys = null;
  const started = Date.now();
  let lastReport = 0;
  combos.forEach((combo, r) => {
    const t0 = Date.now();
    try {
      let text = msg.text;
      vary.forEach((v, d) => { text = RtmModel.withValue(text, v, combo[d]); });
      const model = RtmModel.compile(text);
      const tend = s.tend > 0 ? s.tend : model.settings.TEND;
      // msg.times: every run read at the same times, as bands across the runs need, rather than at the steps it stored.
      const times = msg.times ? msg.times.filter((x) => x <= tend * (1 + 1e-12)) : null;
      const res = FacsimileODE.runModel(model, { ...rtmSolveOptions(s, tend, (t, nsteps) => {
        const now = Date.now();
        if (now - lastReport < 250) return true;
        lastReport = now;
        post({ type: 'progress', id: msg.id, run: r, runs: combos.length, t, tend, nsteps,
          frac: Math.min(1, (r + Math.min(1, t / tend)) / combos.length) });
        return true;
      }), ...(times ? { outputTimes: times, maxPoints: 4 } : {}) });
      const at = times ? res.grid : res;
      if (times && (!at || at.t.length < times.length)) throw new Error('the run did not reach every time asked for');
      const n = at.t.length;
      const width = model.stateWidth || model.nspecies;
      const states = rtmConcentrations(model, at.y, n, width, at.t);
      const ns = model.speciesNames.length;
      const nq = model.quantities.length;
      names = names || model.speciesNames;
      keys = keys || model.quantities.map((q) => q.key);
      const which = Int32Array.from({ length: nq }, (_, q) => q);
      const qOut = new Float64Array(nq);
      // At the cell, thinned to 400 points, the first and the last kept.
      const cell = Math.min(msg.cell, model.fracture - 1) * (model.stride || 1);
      const step = Math.max(1, Math.ceil(n / 400));
      const pick = [];
      for (let i = 0; i < n; i += step) pick.push(i);
      if (pick[pick.length - 1] !== n - 1) pick.push(n - 1);
      const m = pick.length;
      const t = new Float64Array(m);
      const cellStates = new Float64Array(m * ns);
      const cellQuant = new Float64Array(m * nq);
      pick.forEach((i, j) => {
        const c = states.subarray(i * width, (i + 1) * width);
        t[j] = at.t[i];
        cellStates.set(c.subarray(cell * ns, (cell + 1) * ns), j * ns);
        model.quantitiesAt(c, at.t[i], cell, which, qOut);
        cellQuant.set(qOut, j * nq);
      });
      // Along the column at the end, the fracture's cells.
      const nf = model.fracture;
      const stride = model.stride || 1;
      const last = states.subarray((n - 1) * width, n * width);
      const endStates = new Float64Array(nf * ns);
      const endQuant = new Float64Array(nf * nq);
      for (let k = 0; k < nf; k++) {
        endStates.set(last.subarray(k * stride * ns, (k * stride + 1) * ns), k * ns);
        model.quantitiesAt(last, at.t[n - 1], k * stride, which, qOut);
        endQuant.set(qOut, k * nq);
      }
      runs.push({ values: combo, ok: true, m, t, cellStates, cellQuant, nf, centres: Float64Array.from(model.grid.centres.slice(0, nf)),
        endStates, endQuant, tend: at.t[n - 1], steps: res.stats ? res.stats.nsteps : null, seconds: (Date.now() - t0) / 1000 });
    } catch (e) {
      runs.push({ values: combo, ok: false, error: rtmErrorMessage(e), seconds: (Date.now() - t0) / 1000 });
    }
  });
  const transfer = [];
  for (const run of runs) {
    if (!run.ok) continue;
    for (const key of ['t', 'cellStates', 'cellQuant', 'centres', 'endStates', 'endQuant']) transfer.push(run[key].buffer);
  }
  return { reply: { type: 'sweep', id: msg.id, runs, species: names || [], keys: keys || [], cell: msg.cell,
    seconds: (Date.now() - started) / 1000 }, transfer };
}

/*
  FITTING: the numbers named -- a setting, a parameter, a species' start or
  what flows in, a relation's log K, a reaction's constant -- moved until the
  run is as near as it can be to what <DATA> measured, as PhreePlot's fit and
  Gibbs Studio's do: least squares by Levenberg and Marquardt, each
  derivative from a run with one number moved a little. An amount's residual
  is the log10 of the run's value over the one measured, pH, SI and the like
  the difference. A number above zero is fitted in its logarithm, so that it
  stays above zero and its steps are relative; a log K and the temperature as
  they are. The standard errors and correlations are those of the Jacobian at
  the end, the misfit's variance taken from the residuals.
*/
/** Each value <DATA> measured of the columns asked for, where it is in the model and what kind of residual it has. */
function rtmFitPoints(model, columns, tend) {
  const stride = model.stride || 1;
  const points = [];
  let skipped = 0;
  model.data.forEach((tab, ti) => {
    tab.columns.forEach((key, j) => {
      if (columns && !columns.includes(key)) return;
      const k = model.speciesNames.indexOf(key);
      const q = k >= 0 ? -1 : model.quantities.findIndex((qq) => qq.key === key);
      const index = q >= 0 && model.quantities[q].axis === 'index';
      for (const row of tab.rows) {
        const value = row[j + 1];
        if (value === null) continue;
        // An amount is compared in its logarithm, which none and less have not got.
        if (!index && !(value > 0)) { skipped++; continue; }
        if (tab.kind === 'time') {
          points.push({ table: ti, kind: 'time', t: row[0], cell: (tab.cell || 0) * stride + Math.min(tab.layer || 0, stride - 1),
            x: null, key, k, q, index, value });
        } else {
          points.push({ table: ti, kind: 'distance', t: tab.at !== null ? tab.at : tend, cell: null, layer: Math.min(tab.layer || 0, stride - 1),
            x: row[0], key, k, q, index, value });
        }
      }
    });
  });
  return { points, skipped };
}

/** A key's value in model cell `cell` of concentrations c at time t: a species', or a quantity's. */
function rtmValueAt(model, c, t, cell, k, q, out) {
  if (k >= 0) return c[cell * model.speciesNames.length + k];
  model.quantitiesAt(c, t, cell, [q], out);
  return out[0];
}

/** Along the fracture at distance x: between the two cells either side, as a straight line; past the ends, the end cell. */
function rtmValueAlong(model, c, t, layer, x, k, q, out) {
  const nf = model.fracture;
  const stride = model.stride || 1;
  const xs = model.grid.centres;
  const at = (i) => rtmValueAt(model, c, t, i * stride + layer, k, q, out);
  if (nf === 1 || x <= xs[0]) return at(0);
  if (x >= xs[nf - 1]) return at(nf - 1);
  let i = 0;
  while (i < nf - 2 && xs[i + 1] < x) i++;
  const f = (x - xs[i]) / (xs[i + 1] - xs[i]);
  return at(i) * (1 - f) + at(i + 1) * f;
}

/** x of A x = b, A small and dense, by Gaussian elimination with partial pivoting; null where A is singular. */
function rtmSolveSmall(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let best = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[best][col])) best = r;
    if (!(Math.abs(M[best][col]) > 0)) return null;
    [M[col], M[best]] = [M[best], M[col]];
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = M[r][col] / M[col][col];
      if (f) for (let c = col; c <= n; c++) M[r][c] -= f * M[col][c];
    }
  }
  return M.map((row, i) => row[n] / row[i]);
}

function rtmFit(msg, post) {
  const s = msg.solver || {};
  const params = msg.params;
  const np = params.length;
  if (!np) throw new Error('Name at least one number to fit.');
  const logged = params.map((p) => p.kind !== 'logK' && !(p.kind === 'setting' && p.name === 'TEMPERATURE'));
  params.forEach((p, i) => {
    if (!Number.isFinite(p.start)) throw new Error(`${p.name}: give it a number to start from.`);
    if (logged[i] && !(p.start > 0)) {
      throw new Error(`${p.name} is fitted in its logarithm, so that it stays above zero: give it a start above zero.`);
    }
  });
  const fromTheta = (th, i) => (logged[i] ? 10 ** th : th);
  const textAt = (theta) => {
    let text = msg.text;
    params.forEach((p, i) => { text = RtmModel.withValue(text, p, fromTheta(theta[i], i)); });
    return text;
  };
  let theta = params.map((p, i) => (logged[i] ? Math.log10(p.start) : p.start));
  const model0 = RtmModel.compile(textAt(theta));
  const tend0 = s.tend > 0 ? s.tend : model0.settings.TEND;
  const { points, skipped } = rtmFitPoints(model0, msg.columns || null, tend0);
  const n = points.length;
  if (!n) throw new Error('<DATA> has no values of the columns asked for to fit to.');
  const times = [...new Set(points.map((p) => p.t))].sort((a, b) => a - b);
  if (times[times.length - 1] > tend0 * (1 + 1e-12)) {
    throw new Error(`<DATA> has a value at ${times[times.length - 1]}, after the run ends at ${tend0}: run it longer (TEND).`);
  }
  const out1 = new Float64Array(1);
  let runs = 0;
  const maxRuns = msg.maxRuns || 60 * (np + 2);
  let lastReport = 0;
  const history = [];
  // The residuals at theta, from a run of the text with those numbers; keep the run when asked.
  const evaluate = (th, keep = false) => {
    if (runs >= maxRuns) throw Object.assign(new Error('the runs allowed are used up'), { budget: true });
    runs++;
    const model = RtmModel.compile(textAt(th));
    const tend = s.tend > 0 ? s.tend : model.settings.TEND;
    const res = FacsimileODE.runModel(model, { ...rtmSolveOptions(s, tend, () => true), outputTimes: times,
      maxPoints: keep ? 400 : 4 });
    if (!res.grid || res.grid.t.length < times.length) throw new Error('the run did not reach every time measured');
    const conc = res.grid.y.map((y, i) => (model.toConcentrations ? model.toConcentrations(y, res.grid.t[i]) : y));
    const r = new Float64Array(n);
    points.forEach((p, i) => {
      const c = conc[times.indexOf(p.t)];
      const v = p.kind === 'time' ? rtmValueAt(model, c, p.t, p.cell, p.k, p.q, out1)
        : rtmValueAlong(model, c, p.t, p.layer, p.x, p.k, p.q, out1);
      r[i] = p.index ? v - p.value : Math.log10(Math.max(v, 1e-300) / p.value);
    });
    let ssr = 0;
    for (const x of r) ssr += x * x;
    if (!Number.isFinite(ssr)) throw new Error('the run gave no number at a point measured');
    const now = Date.now();
    if (post && now - lastReport > 250) {
      lastReport = now;
      post({ type: 'progress', id: msg.id, runs, maxRuns, ssr: history.length ? history[history.length - 1].ssr : ssr,
        iteration: history.length, frac: Math.min(1, runs / maxRuns) });
    }
    return keep ? { r, ssr, model, res, conc } : { r, ssr };
  };
  const step = (i) => (logged[i] ? 1e-3 : 1e-4 * Math.max(1, Math.abs(theta[i])));
  // How much the solver's tolerance alone moves the misfit: 2 |r| |dr|, each residual off by rtol / ln 10.
  const rtolRun = Number(s.rtol) > 0 ? Number(s.rtol) : 1e-6;
  const noise = (ssr) => 2 * Math.sqrt(ssr * n) * (rtolRun / Math.LN10);
  // Forward differences to steer by; central ones at the end, for the standard errors, whose forward bias is half a step.
  const jacobian = (th, r0, central = false) => {
    const J = Array.from({ length: n }, () => new Float64Array(np));
    for (let j = 0; j < np; j++) {
      const h = step(j);
      const up = th.slice();
      up[j] += h;
      const r2 = evaluate(up).r;
      let r1 = r0;
      if (central) {
        const down = th.slice();
        down[j] -= h;
        r1 = evaluate(down).r;
      }
      for (let i = 0; i < n; i++) J[i][j] = (r2[i] - r1[i]) / (central ? 2 * h : h);
    }
    return J;
  };
  const started = Date.now();
  let cur = evaluate(theta);
  const ssr0 = cur.ssr;
  history.push({ iteration: 0, ssr: cur.ssr, runs });
  let lambda = 1e-3;
  let why = '';
  let J = null;
  try {
    for (let it = 1; it <= (msg.maxIter || 50); it++) {
      J = jacobian(theta, cur.r);
      const A = Array.from({ length: np }, (_, a) => Array.from({ length: np }, (_, b) => {
        let v = 0;
        for (let i = 0; i < n; i++) v += J[i][a] * J[i][b];
        return v;
      }));
      const g = Array.from({ length: np }, (_, a) => {
        let v = 0;
        for (let i = 0; i < n; i++) v += J[i][a] * cur.r[i];
        return v;
      });
      let accepted = false;
      let refused = 0;
      while (refused < 6) {
        const Ad = A.map((row, a) => row.map((v, b) => (a === b ? v + lambda * Math.max(v, 1e-12) : v)));
        let d = rtmSolveSmall(Ad, g.map((v) => -v));
        if (!d) { lambda *= 10; refused++; continue; }
        // A decade, or a unit of log K, at most a step: the misfit's quadratic is not to be trusted further.
        const big = Math.max(...d.map(Math.abs));
        if (big > 1) d = d.map((v) => v / big);
        /*
          What the step should take off the misfit, by the quadratic. Where
          that is below what the runs' own tolerance moves the misfit by --
          every residual off by rtol of its value, log10 of 1 + rtol at the
          most -- no run can tell a better number from this one: this is the
          least, as near as the solver can say.
        */
        let pred = 0;
        for (let a = 0; a < np; a++) {
          pred -= g[a] * d[a];
          for (let b = 0; b < np; b++) pred -= 0.5 * d[a] * A[a][b] * d[b];
        }
        if (pred <= Math.max(1e-10 * cur.ssr, noise(cur.ssr)) + 1e-300) {
          why = 'the misfit is at its least, as near as the solver\'s tolerance can tell';
          break;
        }
        const trial = theta.map((v, a) => v + d[a]);
        let next = null;
        try { next = evaluate(trial); } catch (e) { if (e.budget) throw e; next = null; }
        if (next && next.ssr < cur.ssr) {
          const drop = cur.ssr - next.ssr;
          theta = trial;
          cur = next;
          lambda = Math.max(lambda / 10, 1e-9);
          accepted = true;
          history.push({ iteration: it, ssr: cur.ssr, runs });
          if (drop <= 1e-10 * cur.ssr + 1e-300 || Math.max(...d.map(Math.abs)) < 1e-8) why = 'the misfit stopped falling';
          break;
        }
        lambda *= 10;
        refused++;
      }
      if (why) break;
      if (!accepted) { why = 'no step made the misfit smaller: it is at its least, as near as the solver\'s tolerance can tell'; break; }
      if (cur.ssr === 0) { why = 'the misfit is zero'; break; }
    }
    if (!why) why = 'the iterations allowed are used up';
  } catch (e) {
    if (!e.budget) throw e;
    why = 'the runs allowed are used up';
  }
  // At the end: the Jacobian there for the standard errors, and the run itself, kept to draw.
  let cov = null;
  let sd = null;
  const best = evaluate(theta, true);
  if (n > np) {
    try {
      J = jacobian(theta, best.r, true);
      const A = Array.from({ length: np }, (_, a) => Array.from({ length: np }, (_, b) => {
        let v = 0;
        for (let i = 0; i < n; i++) v += J[i][a] * J[i][b];
        return v;
      }));
      sd = Math.sqrt(best.ssr / (n - np));
      const inv = Array.from({ length: np }, (_, a) => rtmSolveSmall(A, Array.from({ length: np }, (_, b) => (a === b ? 1 : 0))));
      if (inv.every((col) => col && col.every(Number.isFinite))) {
        cov = inv.map((col, a) => col.map((v, b) => sd * sd * inv[b][a]));
      }
    } catch (e) { if (!e.budget) throw e; }
  }
  const se = cov ? cov.map((row, a) => Math.sqrt(Math.max(0, row[a]))) : null;
  // The best run where it was measured: each table's columns at its cell along the run, or along the column at its time.
  const { model, res } = best;
  const conc = res.y.map((y, i) => (model.toConcentrations ? model.toConcentrations(y, res.t[i]) : y));
  const curves = [];
  const seen = new Set();
  for (const p of points) {
    const id = p.kind === 'time' ? `t|${p.cell}|${p.key}` : `x|${p.t}|${p.layer}|${p.key}`;
    if (seen.has(id)) continue;
    seen.add(id);
    if (p.kind === 'time') {
      curves.push({ kind: 'time', cell: p.cell, key: p.key, index: p.index, x: Array.from(res.t),
        y: conc.map((c, i) => rtmValueAt(model, c, res.t[i], p.cell, p.k, p.q, out1)) });
    } else {
      const c = best.conc[times.indexOf(p.t)];
      const stride = model.stride || 1;
      const xs = Array.from(model.grid.centres.slice(0, model.fracture));
      curves.push({ kind: 'distance', t: p.t, layer: p.layer, key: p.key, index: p.index, x: xs,
        y: xs.map((_, i) => rtmValueAt(model, c, p.t, i * stride + p.layer, p.k, p.q, out1)) });
    }
  }
  return {
    type: 'fit', id: msg.id, why, runs, seconds: (Date.now() - started) / 1000, n, np, skipped, ssr0, ssr: best.ssr, sd,
    params: params.map((p, i) => ({ kind: p.kind, name: p.name, start: p.start, logged: logged[i], value: fromTheta(theta[i], i),
      theta: theta[i], se: se ? se[i] : null })),
    corr: cov ? cov.map((row, a) => row.map((v, b) => v / Math.sqrt(cov[a][a] * cov[b][b]))) : null,
    history,
    points: points.map((p, i) => ({ kind: p.kind, table: p.table, t: p.t, x: p.x, cell: p.cell, key: p.key, index: p.index,
      value: p.value, residual: best.r[i] })),
    curves,
    text: textAt(theta),
  };
}

/** The solver's options for a run, from the page's settings (solverPayload in rtm-ui.js): a run's and a sweep's alike. */
function rtmSolveOptions(s, tend, onProgress) {
  const method = s.method || 'ndf';
  const viaJulia = typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method);
  return {
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
    onProgress,
  };
}

function handleRtmMessage(msg, post) {
  const id = msg.id;
  if (msg.type === 'capabilities') {
    post({ type: 'capabilities', id, solvers: rtmSolvers() });
    return;
  }
  if (msg.type === 'fit') {
    try {
      post(rtmFit(msg, post));
    } catch (e) {
      post({ type: 'error', id, stage: 'fit', error: rtmErrorMessage(e) });
    }
    return;
  }
  if (msg.type === 'sweep') {
    try {
      const { reply, transfer } = rtmSweep(msg, post);
      post(reply, transfer);
    } catch (e) {
      post({ type: 'error', id, stage: 'sweep', error: rtmErrorMessage(e) });
    }
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
  if (msg.type === 'diagramBounds') {
    try {
      const reply = rtmDiagramBounds(msg, post);
      post(reply, reply.labels ? [reply.labels.buffer] : []);
    } catch (e) {
      post({ type: 'error', id, stage: 'diagram', error: rtmErrorMessage(e) });
    }
    return;
  }
  if (msg.type === 'diagramLadder') {
    try {
      post(rtmDiagramLadder(msg, post));
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
  const tend = s.tend > 0 ? s.tend : model.settings.TEND;
  let lastReport = 0;
  const started = Date.now();

  try {
    const res = FacsimileODE.runModel(model, rtmSolveOptions(s, tend, (t, nsteps) => {
      const now = Date.now();
      if (now - lastReport < 250) return true;
      lastReport = now;
      post({ type: 'progress', id, t, tend, nsteps, frac: Math.min(1, t / tend) });
      return true;
    }));

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
