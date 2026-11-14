/* ==========================================================================
   RTM.HTML: THE PAGE

   Wiring only: the compiler is rtm-model.js, the solvers are facsimile-solver.js
   and the ode_julia ports, and the work happens in rtm-worker.js on a Worker
   thread. This file keeps the state, draws the charts and says what happened.

   One global: nothing. Everything is inside the IIFE; the page reaches it
   through the data-on-* actions registered at the bottom.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = 'kvot-rtm-v1';
  const WORKER_URL = 'resources/js/rtm-worker-entry.js?v=20261111y';
  const DEFAULT_WIDTH = 330;

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    text: typeof RTM_DEFAULT_MODEL === 'string' ? RTM_DEFAULT_MODEL : '',
    // facsimile.html's settings, since the two pages run the same solver, with
    // this page's own defaults: a tighter rtol, and a stalled Newton correction
    // taken (see stagnationTol in solverPayload).
    solver: {
      method: 'ndf', bdf: false, tend: '', rtol: '1e-6', atol: '1e-20', matrix: 'auto', norm: 'max',
      maxOrder: 5, minOrder: 1, hmax: '0', h0: '0', normControl: false, jacobianMode: 'analytic', kappa: '1e-3',
      maxJacAge: '20', belowTolRun: '5', stagnationTol: '0.5',
      maxSteps: '500000', maxPoints: '4000', nonNegative: true, autoAtol: false, smoothEst: true,
    },
    picked: [],            // species names drawn on the time chart
    cell: 0,               // which cell the time chart is of
    layer: 0,              // 0 the fracture, j the j-th matrix layer behind it
    profileAxis: 'fracture',
    profileLayer: 0,
    gradLayer: 0,
    profileSpecies: '',
    profileTimes: '',      // empty for a spread over the run; else a list
    // The slider's time on Against distance, in the model's unit: null for the Times; and how fast play goes through the run.
    profileAt: null,
    profilePace: '10',
    gradSpecies: '',
    gradScale: 'YlOrRd',
    gradView: 'map',       // the gradient as a map, as contours of it, or as a surface
    gradTMin: '1e-6',
    // Where each log concentration axis starts (logFloor): empty for the least drawn.
    yFrom: '',
    profileYFrom: '',
    gradCFrom: '',
    // The unit a concentration is shown in (CONC_UNITS): empty for the model's own.
    concUnit: '',
    // What time is shown in: '' the model's own unit, s, min, h, d or a another, 'pv' pore volumes (on Against time,
    // Against distance and Gradient; elsewhere the model's own unit).
    timeIn: '',
    // Against time at several cells: the list typed in Cells; empty for the one cell Cell chooses.
    cells: '',
    // Under Against time, where each curve is half-way and what has gone out of the column (breakthrough numbers).
    btc: false,
    every: true,           // every species in numbers, under Against time
    // The list of what to draw on Against time, as tall as its corner was dragged; 0 for its own height.
    seriesHeight: 0,
    // The composition tab: what it shows, of which element, in what, as what, along the run or the column, where.
    compView: 'where',
    compBeside: false,     // the water as PHREEQC lists it, with PHREEQC's own numbers beside
    compBudgetOf: '',      // a budget over the run: 'element:Ca' or 'species:X'
    compBudgetBy: 'where', // by where it is held, by each <REACTIONS> line ('lines'), or where an element goes ('flows')
    compBudgetAt: 'column', // by each line: over the whole column, or at a cell (its number)
    compElement: '',
    compIn: 'water',
    compAs: 'percent',
    compAlong: 'time',
    compCell: 0,
    compLayer: 0,
    compTimes: '',
    compTMin: '1e-6',
    // The column at the slider's one time, in the model's unit: null for At; and how fast play goes through the run.
    compAt: null,
    compPace: '10',
    // Principal components: of what, and whether an amount is taken as its log.
    compPcaVars: '',
    compPcaLog: true,
    // The Diagrams tab: whose water, and what is varied over what range; then what is drawn of it.
    dg: {
      cell: 0, at: 'start',
      x: { kind: 'pH', sp: '', from: '2', to: '12', n: '101' },
      y: { kind: '', sp: '', from: '-12', to: '16', n: '41', phases: '' },
      show: 'shares', el: '', in: 'water', q: '', satAt: 0,
    },
    // The Sweeps tab: what is varied over what values, the cell kept; then what is drawn of the runs.
    sw: { what: '', values: '', what2: '', values2: '', cell: 0, show: 'summary', key: '', of: 'end', logT: true },
    // The Fit tab: the numbers fitted and where each starts, and the <DATA> columns left out.
    fit: { params: [], off: [] },
    // The Uncertainty tab: each number drawn and its distribution, how many runs, how drawn, the cell kept; the last fit's
    // correlations where its numbers were taken; then what is drawn of the runs.
    unc: { rows: [], n: '100', scheme: 'lhs', seed: '1', cell: 0, useCorr: true, corr: null, show: 'time', key: '', of: 'end' },
    tab: 'time',
    syntax: true,          // colour the model text in the editor
    lineNumbers: true,     // the line numbers beside the model text
    modelName: null,       // the name Save… offers: what the text was saved under, or opened from; null, its title's
    sideWidth: null,
    footHeight: null,      // the run's area, as tall as its top edge was dragged; null, as its buttons and status need
    sections: {},
    compiled: null,        // the summary from the worker
    compileError: null,
    result: null,          // { t, states, n, width, model, stats }
    running: false,
    ran: null,             // the solver options and text the last run was given
    verify: null,
    storedStamp: null,
    storedEdited: null,
    textNote: null,
  };

  /** The solver settings as the page ships them, before a visit's own are read over them: the (i) panels quote these as the defaults. */
  const SOLVER_DEFAULTS = Object.freeze({ ...state.solver });

  /** A cheap, stable fingerprint. Not a checksum: only equality. */
  function stampOf(text) {
    const s = String(text);
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
    return `${s.length.toString(36)}-${h.toString(36)}`;
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        text: state.text, solver: state.solver, picked: state.picked, cell: state.cell,
        tab: state.tab, syntax: state.syntax, lineNumbers: state.lineNumbers, modelName: state.modelName, sideWidth: state.sideWidth,
        footHeight: state.footHeight, sections: state.sections,
        layer: state.layer, profileAxis: state.profileAxis, profileLayer: state.profileLayer,
        gradLayer: state.gradLayer,
        profileSpecies: state.profileSpecies, profileTimes: state.profileTimes, profileAt: state.profileAt, profilePace: state.profilePace,
        gradSpecies: state.gradSpecies, gradScale: state.gradScale, gradView: state.gradView,
        gradTMin: state.gradTMin, yFrom: state.yFrom, profileYFrom: state.profileYFrom, gradCFrom: state.gradCFrom,
        concUnit: state.concUnit, timeIn: state.timeIn, cells: state.cells, btc: state.btc, every: state.every, seriesHeight: state.seriesHeight,
        compView: state.compView, compBeside: state.compBeside, compBudgetOf: state.compBudgetOf, compBudgetBy: state.compBudgetBy, compBudgetAt: state.compBudgetAt, compElement: state.compElement, compIn: state.compIn, compAs: state.compAs,
        compAlong: state.compAlong, compCell: state.compCell, compLayer: state.compLayer, compTimes: state.compTimes,
        compTMin: state.compTMin, compPcaVars: state.compPcaVars, compPcaLog: state.compPcaLog, compAt: state.compAt, compPace: state.compPace,
        dg: state.dg, sw: state.sw, fit: state.fit, unc: state.unc,
        // Which built-in model this text was written against, and whether the
        // reader had changed it. Without both, a stored text shadows a built-in
        // model that has moved on and no amount of reloading shifts it -- it is
        // in localStorage, not the cache. See migrateStoredText.
        modelStamp: stampOf(RTM_DEFAULT_MODEL),
        textEdited: state.text !== RTM_DEFAULT_MODEL,
      }));
    } catch (e) { /* storage unavailable: nothing to do */ }
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (typeof s.text === 'string' && s.text.trim()) state.text = s.text;
      if (s.solver && typeof s.solver === 'object') Object.assign(state.solver, s.solver);
      if (Array.isArray(s.picked)) state.picked = s.picked.filter((x) => typeof x === 'string');
      if (Number.isFinite(s.cell) || s.cell === 'left' || s.cell === 'right') state.cell = s.cell;
      if (Number.isFinite(s.layer)) state.layer = s.layer;
      if (Number.isFinite(s.profileLayer)) state.profileLayer = s.profileLayer;
      if (Number.isFinite(s.gradLayer)) state.gradLayer = s.gradLayer;
      if (s.profileAxis === 'matrix' || s.profileAxis === 'fracture') state.profileAxis = s.profileAxis;
      if (typeof s.tab === 'string') state.tab = s.tab;
      if (typeof s.syntax === 'boolean') state.syntax = s.syntax;
      if (typeof s.lineNumbers === 'boolean') state.lineNumbers = s.lineNumbers;
      if (typeof s.modelName === 'string' && s.modelName) state.modelName = s.modelName;
      if (typeof s.profileSpecies === 'string') state.profileSpecies = s.profileSpecies;
      if (typeof s.profileTimes === 'string') state.profileTimes = s.profileTimes;
      if (s.profileAt === null || Number.isFinite(s.profileAt)) state.profileAt = s.profileAt;
      if (PROFILE_PACES.includes(s.profilePace)) state.profilePace = s.profilePace;
      if (typeof s.gradSpecies === 'string') state.gradSpecies = s.gradSpecies;
      if (typeof s.gradScale === 'string') state.gradScale = s.gradScale;
      if (['map', 'contour', 'surface'].includes(s.gradView)) state.gradView = s.gradView;
      if (typeof s.gradTMin === 'string') state.gradTMin = s.gradTMin;
      for (const k of ['yFrom', 'profileYFrom', 'gradCFrom']) if (typeof s[k] === 'string') state[k] = s[k];
      if (typeof s.concUnit === 'string' && (s.concUnit === '' || CONC_UNITS[s.concUnit])) state.concUnit = s.concUnit;
      if (s.timeIn === '' || s.timeIn === 'pv' || SHOW_UNITS.some(([sym]) => sym === s.timeIn)) state.timeIn = s.timeIn;
      if (typeof s.cells === 'string') state.cells = s.cells;
      if (typeof s.btc === 'boolean') state.btc = s.btc;
      if (typeof s.every === 'boolean') state.every = s.every;
      if (Number.isFinite(s.seriesHeight) && s.seriesHeight >= 0) state.seriesHeight = s.seriesHeight;
      if (['where', 'listing', 'budget', 'fronts', 'piper', 'durov', 'schoeller', 'stiff', 'ussl', 'wilcox', 'pca'].includes(s.compView)) state.compView = s.compView;
      if (typeof s.compElement === 'string') state.compElement = s.compElement;
      if (typeof s.compBeside === 'boolean') state.compBeside = s.compBeside;
      if (typeof s.compBudgetOf === 'string') state.compBudgetOf = s.compBudgetOf;
      if (['where', 'lines', 'flows'].includes(s.compBudgetBy)) state.compBudgetBy = s.compBudgetBy;
      if (s.compBudgetAt === 'column' || Number.isInteger(s.compBudgetAt)) state.compBudgetAt = s.compBudgetAt;
      if (s.compIn === 'water' || s.compIn === 'all') state.compIn = s.compIn;
      if (s.compAs === 'percent' || s.compAs === 'amount') state.compAs = s.compAs;
      if (s.compAlong === 'time' || s.compAlong === 'distance') state.compAlong = s.compAlong;
      if (Number.isInteger(s.compCell) && s.compCell >= 0) state.compCell = s.compCell;
      if (Number.isInteger(s.compLayer) && s.compLayer >= 0) state.compLayer = s.compLayer;
      if (typeof s.compTimes === 'string') state.compTimes = s.compTimes;
      if (typeof s.compTMin === 'string') state.compTMin = s.compTMin;
      if (typeof s.compPcaVars === 'string') state.compPcaVars = s.compPcaVars;
      if (typeof s.compPcaLog === 'boolean') state.compPcaLog = s.compPcaLog;
      if (s.compAt === null || Number.isFinite(s.compAt)) state.compAt = s.compAt;
      if (PROFILE_PACES.includes(s.compPace)) state.compPace = s.compPace;
      if (s.dg && typeof s.dg === 'object') {
        const d = state.dg;
        if (Number.isInteger(s.dg.cell) && s.dg.cell >= 0) d.cell = s.dg.cell;
        if (s.dg.at === 'start' || s.dg.at === 'end') d.at = s.dg.at;
        for (const key of ['x', 'y']) {
          const ax = s.dg[key];
          if (!ax || typeof ax !== 'object') continue;
          if (['pH', 'pe', 'Eh', 'la', 'ratio', 'tot', ...(key === 'y' ? ['', 'pHheld', 'sat'] : [])].includes(ax.kind)) d[key].kind = ax.kind;
          for (const f of ['sp', 'from', 'to', 'n']) if (typeof ax[f] === 'string') d[key][f] = ax[f];
        }
        if (s.dg.y && typeof s.dg.y.phases === 'string') d.y.phases = s.dg.y.phases;
        if (Number.isInteger(s.dg.satAt) && s.dg.satAt >= 0) d.satAt = s.dg.satAt;
        for (const f of ['show', 'el', 'q']) if (typeof s.dg[f] === 'string') d[f] = s.dg[f];
        if (s.dg.in === 'water' || s.dg.in === 'all') d.in = s.dg.in;
      }
      if (s.sw && typeof s.sw === 'object') {
        for (const f of ['what', 'values', 'what2', 'values2', 'show', 'key']) if (typeof s.sw[f] === 'string') state.sw[f] = s.sw[f];
        if (Number.isInteger(s.sw.cell) && s.sw.cell >= 0) state.sw.cell = s.sw.cell;
        if (['end', 'max', 'min'].includes(s.sw.of)) state.sw.of = s.sw.of;
        if (typeof s.sw.logT === 'boolean') state.sw.logT = s.sw.logT;
      }
      if (s.fit && typeof s.fit === 'object') {
        if (Array.isArray(s.fit.params)) {
          state.fit.params = s.fit.params.filter((p) => p && typeof p.what === 'string' && typeof p.start === 'string')
            .slice(0, 4).map((p) => ({ what: p.what, start: p.start }));
        }
        if (Array.isArray(s.fit.off)) state.fit.off = s.fit.off.filter((x) => typeof x === 'string');
      }
      if (s.unc && typeof s.unc === 'object') {
        const u = state.unc;
        if (Array.isArray(s.unc.rows)) {
          u.rows = s.unc.rows.filter((r) => r && typeof r.what === 'string' && UN_FAMILIES[r.family]).slice(0, 8)
            .map((r) => ({ what: r.what, family: r.family, a: String(r.a ?? ''), b: String(r.b ?? ''), c: String(r.c ?? '') }));
        }
        for (const f of ['n', 'seed', 'key']) if (typeof s.unc[f] === 'string') u[f] = s.unc[f];
        if (['lhs', 'sobol', 'random'].includes(s.unc.scheme)) u.scheme = s.unc.scheme;
        if (['time', 'profile', 'spread', 'matters', 'indices'].includes(s.unc.show)) u.show = s.unc.show;
        if (['end', 'max', 'min'].includes(s.unc.of)) u.of = s.unc.of;
        if (Number.isInteger(s.unc.cell) && s.unc.cell >= 0) u.cell = s.unc.cell;
        if (typeof s.unc.useCorr === 'boolean') u.useCorr = s.unc.useCorr;
        if (s.unc.corr && Array.isArray(s.unc.corr.whats) && Array.isArray(s.unc.corr.m)) u.corr = s.unc.corr;
      }
      if (Number.isFinite(s.sideWidth)) state.sideWidth = s.sideWidth;
      if (Number.isFinite(s.footHeight) && s.footHeight > 0) state.footHeight = s.footHeight;
      if (s.sections && typeof s.sections === 'object') state.sections = s.sections;
      state.storedStamp = typeof s.modelStamp === 'string' ? s.modelStamp : null;
      state.storedEdited = typeof s.textEdited === 'boolean' ? s.textEdited : null;
    } catch (e) { /* a corrupt entry: start fresh */ }
  }

  /**
   * Bring a stored text forward when the built-in model has changed.
   *
   * Whether the reader edited it cannot be worked out here -- a stored text
   * that differs from today's built-in differs either because they changed it
   * or because the built-in did, and afterwards the two look the same -- so it
   * is recorded at save time. A state stored before that was recorded is asked
   * the question anyway, which errs towards keeping the reader's text.
   */
  function migrateStoredText() {
    if (state.storedStamp === stampOf(RTM_DEFAULT_MODEL)) return;
    if (state.text === RTM_DEFAULT_MODEL) return;
    const edited = state.storedEdited === null ? true : state.storedEdited;
    if (edited) {
      state.textNote = 'Note: the built-in model has been updated since the text on the Model tab '
        + 'was saved, and that text is what you are looking at — it is kept in this browser and a '
        + 'reload does not touch it. "Reset to the built-in model" takes the new one.';
      return;
    }
    state.text = RTM_DEFAULT_MODEL;
    state.textNote = 'The built-in model has been updated, and this is the new one.';
  }

  /* ---------------------------------------------------------------------
     The worker, or the page itself
     --------------------------------------------------------------------- */
  let worker = null;
  let workerKind = 'none';       // 'worker' | 'inline'
  let workerSolvers = null;
  let nextId = 1;
  const pending = new Map();
  /*
    A page opened straight off the disk cannot start a Worker: the browser will
    not let a file:// document load a file:// script as one. Everything then
    runs on the page's own thread, which works -- the solvers are all here as
    ordinary scripts, the ported ones included -- but the page cannot repaint
    until the run is over, so Stop does nothing and the progress bar cannot
    move. Serving the folder is the fix, and is worth saying rather than
    leaving someone to wonder why the page went quiet.
  */
  const INLINE_NOTE = 'There is no background worker here, so a run holds the page until it '
    + 'finishes: the progress bar cannot move and Stop cannot be heard.';
  const SERVE_NOTE = location.protocol === 'file:'
    ? ' A page opened from the disk cannot start one. Serving this folder — '
      + '"python3 -m http.server" in it, then the address it prints — gives you a '
      + 'background worker, a live progress bar and a Stop that works.'
    : '';

  function ensureWorker() {
    if (worker || workerKind === 'inline') return;
    if (typeof Worker === 'undefined') { workerKind = 'inline'; return; }
    try {
      worker = new Worker(WORKER_URL);
      workerKind = 'worker';
      worker.onmessage = (ev) => receive(ev.data);
      worker.onerror = () => {
        worker = null;
        workerKind = 'inline';
        setStatus(INLINE_NOTE, 'error');
      };
      askCapabilities();
    } catch (e) {
      worker = null;
      workerKind = 'inline';
    }
  }

  function askCapabilities() {
    request({ type: 'capabilities' }).then((reply) => {
      workerSolvers = reply.solvers || null;
    }).catch(() => { workerSolvers = null; });
  }

  function receive(msg) {
    const entry = pending.get(msg.id);
    if (!entry) return;
    if (msg.type === 'progress') { if (entry.onProgress) entry.onProgress(msg); return; }
    pending.delete(msg.id);
    if (msg.type === 'error') entry.reject(Object.assign(new Error(msg.error), msg));
    else entry.resolve(msg);
  }

  function request(message, onProgress) {
    ensureWorker();
    const id = nextId++;
    const full = { ...message, id };
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject, onProgress });
      if (worker) { worker.postMessage(full); return; }
      // Inline: the same handler, called directly. It replies synchronously,
      // so the promise settles before this returns.
      try {
        self.handleRtmMessage(full, (reply) => receive(reply));
      } catch (e) {
        pending.delete(id);
        reject(e);
      }
    });
  }

  /**
   * Why this method cannot be run here, or null.
   *
   * The ported solvers used to be refused whenever there was no worker. They
   * are loaded on the page as ordinary scripts and run perfectly well there,
   * so what that refusal actually did was stop anyone who had opened the file
   * from disk from using them at all. It is a warning now, not a refusal --
   * see inlineWarning.
   */
  function methodRefusal(method) {
    ensureWorker();
    if (worker && workerSolvers && !workerSolvers.includes(method)) {
      return `The background worker does not have ${method}. That usually means the browser is `
        + 'holding an older copy of it; reload the page, with a hard reload if that does not do it.';
    }
    if ((/^julia_/.test(method) || method === 'auto') && typeof FacsimileOdeJulia === 'undefined') {
      return `${method} is not loaded on this page. Reload it, with a hard reload if that does `
        + 'not do it.';
    }
    // Equilibria held throughout the run are algebraic equations, which the
    // NDF solves and Auto hands to it at once; the others take no mass matrix.
    const m = state.compiled;
    if (m && m.heldEquilibria && method !== 'ndf' && method !== 'auto') {
      return 'EQUILIBRATE = always holds the equilibria as algebraic equations, which only the NDF '
        + 'solves (Auto hands such a model to it). Choose NDF, with or without its BDF formulas, or '
        + 'give the equilibria a kf and EQUILIBRATE = 1 to run them as fast pairs.';
    }
    return null;
  }

  /** What to say before a run that will hold the page, or ''. */
  function inlineWarning() {
    if (workerKind !== 'inline') return '';
    return ` ${INLINE_NOTE}${SERVE_NOTE}`;
  }

  /** Let the browser paint before something that will block it. */
  function repaint() {
    return new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
  }

  /* ---------------------------------------------------------------------
     Status and progress
     --------------------------------------------------------------------- */
  function setStatus(text, tone) {
    const el = $('rtmStatus');
    el.textContent = text;
    // The box is a fixed height and scrolls; a new message starts at its
    // beginning rather than wherever the last one had been scrolled to.
    el.scrollTop = 0;
    el.className = 'rtm-status'
      + (tone === 'error' ? ' error' : tone === 'warn' ? ' warn' : tone === 'ok' ? ' ok' : '');
  }

  function setProgress(frac) {
    const bar = $('rtmProgress');
    if (frac === null) { bar.hidden = true; return; }
    bar.hidden = false;
    $('rtmProgressFill').style.width = `${Math.max(1.5, Math.min(100, frac * 100))}%`;
  }

  /*
    The model's own time unit, and what one of them is in seconds. The text
    says which; until something has compiled it is seconds, which is what a
    model that says nothing means.
  */
  function timeUnit() {
    return (state.compiled && state.compiled.timeUnit) || { name: 'second', symbol: 's', seconds: 1 };
  }

  /**
   * A time in the model's own unit, written for a person: in the unit Time in
   * shows, where one is chosen.
   *
   * Else scaled up the ladder when that reads better -- 5000 s is 1.39 h -- but
   * never below the model's own unit: a model written in years has nothing to
   * say about seconds, and "3.16e7 s" where the reader wrote 1 would answer a
   * question nobody asked.
   */
  /** A time's number for a person: to three figures, those from a thousand to a million written out -- 1890, not 1.89e+3. */
  const fmtTimeNumber = (v) => {
    const r = Number(v.toPrecision(3));
    return Math.abs(r) >= 1e3 && Math.abs(r) < 1e6 ? String(r) : v.toPrecision(3);
  };

  const fmtTime = (t) => {
    const st = shownTime();
    if (st.fixed) return `${fmtTimeNumber(t * st.per)} ${st.sym}`;
    const u = timeUnit();
    const s = t * u.seconds;
    const ladder = [[1, 's'], [60, 'min'], [3600, 'h'], [86400, 'd'], [365.25 * 86400, 'a']];
    let pick = Math.max(0, ladder.findIndex(([sec]) => sec === u.seconds));
    while (pick + 1 < ladder.length && Math.abs(s) >= ladder[pick + 1][0]) pick++;
    return `${fmtTimeNumber(s / ladder[pick][0])} ${ladder[pick][1]}`;
  };

  /** A number for a person: as written when it is short, to four figures when it is not. */
  const fmtNumber = (v) => {
    if (!Number.isFinite(v)) return String(v);
    if (String(v).length <= 8) return String(v);
    return Math.abs(v) >= 1e-3 && Math.abs(v) < 1e6 ? String(Number(v.toPrecision(4))) : v.toExponential(3);
  };

  /** A pe, or the range of pe over the cells: [lowest, highest]. */
  const fmtPe = ([lo, hi]) => (Math.abs(hi - lo) < 5e-3 ? lo.toFixed(2) : `${lo.toFixed(2)} to ${hi.toFixed(2)}`);
  // A potential, from volts, in millivolts: one, or the range over the cells.
  const fmtMv = ([lo, hi]) => (Math.abs(hi - lo) < 5e-5 ? `${(lo * 1e3).toFixed(1)} mV`
    : `${(lo * 1e3).toFixed(1)} to ${(hi * 1e3).toFixed(1)} mV`);

  /** A thickness, in mm or µm where that reads better than metres. */
  const fmtLength = (x) => {
    const a = Math.abs(x);
    if (a >= 1) return `${Number(x.toPrecision(3))} m`;
    if (a >= 1e-3) return `${Number((x * 1e3).toPrecision(3))} mm`;
    if (a >= 1e-6) return `${Number((x * 1e6).toPrecision(3))} µm`;
    return `${x.toExponential(2)} m`;
  };

  /*
    Times may be written with a unit, because a model whose TEND is in years is
    painful to talk to in seconds. The units are the ones fmtTime prints back,
    so what is typed and what appears in the legend agree.
  */
  const TIME_UNITS = { s: 1, min: 60, h: 3600, d: 86400, a: 365.25 * 86400, y: 365.25 * 86400 };

  /**
   * "0, 1 h, 30 d, 500 y, 2 PV" -> times in the model's own unit, plus whatever could not be read.
   *
   * A unit is glued to its number first, so that a space between the two does
   * not split them, and a bare list of numbers still separates on spaces.
   * PV is pore volumes, where the water flows. A bare number is read on the
   * time axis ax (timeAxis) where there is one -- in the unit Time in shows,
   * or in pore volumes -- and in the model's own unit where there is none.
   */
  function parseTimes(text, ax = null) {
    const glued = String(text).replace(/(\d)\s+(s|min|h|d|a|y|pv)\b/gi, '$1$2');
    const times = [];
    const bad = [];
    const own = timeUnit().seconds;
    const tw = poreTime();
    for (const tok of glued.split(/[\s,;]+/).filter(Boolean)) {
      const m = /^([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(s|min|h|d|a|y|pv)?$/i.exec(tok);
      if (!m) { bad.push(tok); continue; }
      const unit = m[2] ? m[2].toLowerCase() : '';
      if (unit === 'pv') {
        if (tw > 0) times.push(Number(m[1]) * tw);
        else bad.push(tok);
        continue;
      }
      if (!unit && ax) { times.push(Number(m[1]) / ax.per); continue; }
      // A bare number is in the model's own unit; a suffixed one is converted
      // into it, so "500 a" means the same thing whatever the model counts in.
      times.push((Number(m[1]) * (unit ? TIME_UNITS[unit] : own)) / own);
    }
    return { times, bad };
  }

  /** The stored point nearest a wanted time; the run is stored thinned. */
  function nearestIndex(t, want) {
    let best = 0;
    let gap = Infinity;
    for (let i = 0; i < t.length; i++) {
      const d = Math.abs(t[i] - want);
      if (d < gap) { gap = d; best = i; }
    }
    return best;
  }

  /*
    TIME IN, on Against time, Against distance and Gradient: one choice for
    the three of how a time is shown -- in the model's own unit, as it comes;
    in another of seconds to years; or, where the water flows, in the pore
    volumes that have flowed into the column, t/t_w, t_w the time the water
    takes to cross it: TRAVEL_TIME, or LENGTH over the pore-water speed
    |VELOCITY|/POROSITY. The flow is one number for the whole run, so a pore
    volume is a fixed length of time, and every axis is the model's time
    scaled: ax.per, what a time of the model is multiplied by to be on it.
    The model and its run are as they are; only the showing changes. A run
    kept beside counts in its own pore volumes: two runs at different speeds
    line up.
  */
  const SHOW_UNITS = [['s', 'seconds', 1], ['min', 'minutes', 60], ['h', 'hours', 3600], ['d', 'days', 86400],
    ['a', 'years', 365.25 * 86400]];
  /**
   * The time unit times are shown in, on every tab and wherever the page writes
   * one: { fixed, per, sym } -- the unit Time in has chosen, or the model's own
   * where none is, or where pore volumes are, which only the three charts with
   * Time in are drawn in. per is what a time of the model is multiplied by.
   */
  function shownTime() {
    const own = timeUnit();
    const want = SHOW_UNITS.find(([sym]) => sym === state.timeIn && sym !== own.symbol);
    return want ? { fixed: true, per: own.seconds / want[2], sym: want[0] } : { fixed: false, per: 1, sym: own.symbol };
  }
  /** A time of the model as it is shown; anything not a number as it is. */
  const showT = (t) => (Number.isFinite(t) ? t * shownTime().per : t);
  /** Composition's "from", typed in the unit shown, in the model's unit. */
  const compFrom = () => (Number(state.compTMin) || 0) / shownTime().per;
  /** A number typed on one time axis -- { per } -- written on another. */
  const turnTime = (v, from, to) => {
    const x = Number(((v / from.per) * to.per).toPrecision(6));
    return x !== 0 && (Math.abs(x) < 1e-3 || Math.abs(x) >= 1e6) ? x.toExponential() : String(x);
  };
  /** The bare numbers of a list of times written on another axis; those with a unit as they were typed. */
  const turnBareTimes = (text, from, to) => String(text).replace(
    /(^|[\s,;])([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(?!\s*(?:s|min|h|d|a|y|pv)\b)(?=$|[\s,;])/gi,
    (all, lead, num) => `${lead}${turnTime(Number(num), from, to)}`);
  /** A pore volume of run r -- the time its water takes to cross the column, in its model's unit -- or 0 where it does not flow. */
  function poreTime(r = state.result) {
    const m = r ? r.model : state.compiled;
    return m && m.transport && m.travelTime > 0 ? m.travelTime : 0;
  }
  /**
   * The time axis run r is shown on: { pv, fixed, tw, per, sym, title, why } -- pv whether in pore volumes, fixed whether
   * in a unit chosen (pore volumes or a time unit not the model's), tw a pore volume (0 where the water does not flow),
   * per what a time of the model is multiplied by to be on the axis, sym what a number on it is in, why the note's words
   * where pore volumes are chosen and r has none.
   */
  function timeAxis(r = state.result) {
    const tw = poreTime(r);
    if (state.timeIn === 'pv' && tw > 0) return { pv: true, fixed: true, tw, per: 1 / tw, sym: 'PV', title: 'pore volumes', why: '' };
    const m = r ? r.model : state.compiled;
    const st = shownTime();
    return { pv: false, fixed: st.fixed, tw, per: st.per, sym: st.sym, title: `time (${st.sym})`,
      why: state.timeIn === 'pv' && m ? `time in ${timeUnit().name}s: ${m.transport ? 'the water does not flow' : 'a batch has no pore volumes'}` : '' };
  }
  /** Run r's stored times on the axis: its own, or scaled, kept with the run. */
  function axisTimes(r, ax) {
    if (ax.per === 1) return r.t;
    if (!r.axisT || r.axisT.per !== ax.per) r.axisT = { per: ax.per, x: Float64Array.from(r.t, (t) => t * ax.per) };
    return r.axisT.x;
  }
  /** A time of the run, in the model's unit, for a person on the axis: 1.25 PV, 3.50 h, or as fmtTime writes it. */
  const fmtOnAxis = (ax, t) => (ax.fixed ? `${fmtTimeNumber(t * ax.per)} ${ax.sym}` : fmtTime(t));
  /** A number on the axis -- a "from" -- for a person. */
  const fmtAxisNumber = (ax, v) => (ax.fixed ? `${Number(v.toPrecision(3))} ${ax.sym}` : fmtTime(v));

  // The Time in selects, on Against time, Against distance and Gradient, as one: what the run on show can be shown in.
  const TIME_SELECTS = ['rtmTimeInTime', 'rtmTimeInProfile', 'rtmTimeInGrad'];
  function renderTimeIn() {
    const r = state.result || (state.compiled ? { model: state.compiled } : null);
    const flows = poreTime(r) > 0;
    // Every time unit, the model's own said so; pore volumes only where the water flows.
    const own = timeUnit().symbol;
    const html = SHOW_UNITS.map(([sym, name]) => `<option value="${sym}">${name}${sym === own ? ' (the model’s)' : ''}</option>`).join('')
      + (flows ? '<option value="pv">pore volumes</option>' : '');
    const ax = timeAxis(r);
    for (const id of TIME_SELECTS) {
      const sel = $(id);
      if (!sel) continue;
      sel.innerHTML = html;
      sel.value = ax.pv ? 'pv' : ax.sym;
    }
    // A "from" is read on the axis.
    $('rtmTMinUnit').textContent = ax.sym;
    $('rtmGradTMinUnit').textContent = ax.sym;
  }
  /*
    What was typed on one time axis, put on the other, so that the picture
    stays as it was: each "from", and each bare number of the Times; a time
    with its unit means the same on either and stays as typed.
  */
  function retypeTimes(from, to) {
    for (const id of ['rtmTMin', 'rtmGradTMin']) {
      const el = $(id);
      const v = Number(el.value);
      if (el.value.trim() && Number.isFinite(v)) el.value = turnTime(v, from, to);
    }
    state.gradTMin = $('rtmGradTMin').value;
    const times = $('rtmProfileTimes');
    times.value = turnBareTimes(times.value, from, to);
    state.profileTimes = times.value;
  }
  /** Composition's "from" and Times, in the unit shown, put in another: pore volumes are not among them. */
  function retypeShown(from, to) {
    const v = Number(state.compTMin);
    if (String(state.compTMin).trim() && Number.isFinite(v)) state.compTMin = turnTime(v, from, to);
    state.compTimes = turnBareTimes(state.compTimes, from, to);
    $('rtmCompTMin').value = state.compTMin;
    $('rtmCompTimes').value = state.compTimes;
  }

  /* ---------------------------------------------------------------------
     Compiling
     --------------------------------------------------------------------- */
  let compileTimer = null;
  function scheduleCompile(ms) {
    clearTimeout(compileTimer);
    compileTimer = setTimeout(() => compile(), ms);
  }

  async function compile() {
    saveState();
    // What has changed since the text was opened, as of this text.
    showChanges();
    const note = state.textNote ? ` ${state.textNote}` : '';
    state.textNote = null;
    try {
      const reply = await request({ type: 'compile', text: state.text });
      state.compiled = reply.model;
      state.compileError = null;
      renderFacts();
      renderSeriesList();
      renderCells();
      renderUnits();
      renderComp();
      renderDg();
      renderSw();
      renderFit();
      renderUn();
      drawJacobianPattern();
      const m = reply.model;
      const warn = m.warnings.length ? ` ${m.warnings.length} warning${m.warnings.length > 1 ? 's' : ''}: ${m.warnings[0]}` : '';
      if (!state.running) {
        setStatus(`Compiled: ${m.nspecies} species, ${m.nreactions} reactions, ${m.cells} cell`
          + `${m.cells === 1 ? '' : 's'} — ${m.states} equations, Jacobian with ${m.nnz} non-zeros `
          + `(${(100 * m.density).toFixed(2)} % of the matrix). Ready to run.${warn}${note}`, 'ok');
        linkLines($('rtmStatus'));
      }
      // The warnings one a line, a line of the text one names a link to it; a name thought mistyped, a fix for it.
      $('rtmModelNote').replaceChildren(...m.warnings.map((w) => {
        const li = document.createElement('li');
        li.textContent = w;
        linkLines(li);
        const fix = (m.fixes || []).find((f) => w.startsWith(`Line ${f.line}: ${f.name} is used up`));
        for (const to of fix ? fix.meant : []) {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'rtm-fix';
          b.dataset.onClick = 'rtm:fixName';
          b.dataset.line = String(fix.line);
          b.dataset.from = fix.name;
          b.dataset.to = to;
          b.textContent = `Change to ${to}`;
          li.append(' ', b);
        }
        return li;
      }));
      $('rtmModelNote').hidden = !m.warnings.length;
      renderLineNumbers();
      infoRefresh();
      return true;
    } catch (e) {
      state.compiled = null;
      state.compileError = e;
      renderFacts();
      renderLineNumbers();
      infoRefresh();
      if (!state.running) {
        setStatus(`The model does not compile: ${e.message}${note}`, 'error');
        linkLines($('rtmStatus'));
      }
      return false;
    }
  }

  /*
    A LINE OF THE MODEL TEXT NAMED -- "Line 194: the charges do not balance",
    "<DATA>, the table on line 5" -- in a warning under the text or in what
    the status line says of the compile, a link to it: a click goes to the
    line, scrolled into view a third of the way down the box, the whole line
    selected and the keyboard in it.
  */
  const LINE_NAMED = /\b([Ll]ine) (\d+)\b/g;
  function linkLines(el) {
    const found = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      LINE_NAMED.lastIndex = 0;
      if (LINE_NAMED.test(node.data) && !node.parentElement.closest('button')) found.push(node);
    }
    for (const node of found) {
      const frag = document.createDocumentFragment();
      let last = 0;
      // matchAll starts where the expression's last test left it.
      LINE_NAMED.lastIndex = 0;
      for (const m of node.data.matchAll(LINE_NAMED)) {
        frag.append(node.data.slice(last, m.index));
        const link = document.createElement('button');
        link.type = 'button';
        link.className = 'rtm-line-link';
        link.dataset.onClick = 'rtm:goLine';
        link.dataset.line = m[2];
        link.textContent = m[0];
        frag.append(link);
        last = m.index + m[0].length;
      }
      frag.append(node.data.slice(last));
      node.replaceWith(frag);
    }
  }

  /*
    A FIX OFFERED: a name a warning thinks mistyped changed, on its line, into
    the one it may have meant -- every place the name stands as a name in the
    line's equation, nothing else -- as if typed: the browser's own insertText,
    so that Cmd+Z takes it back as it would a keystroke, and the text compiled
    again as after any typing.
  */
  function fixName(line, from, to) {
    const ta = $('rtmText');
    const lines = ta.value.split('\n');
    const text = lines[line - 1];
    if (text === undefined) return;
    // The equation: the line up to its first comma outside brackets.
    let depth = 0;
    let end = text.length;
    for (let k = 0; k < text.length; k += 1) {
      const ch = text[k];
      if (ch === '(' || ch === '[' || ch === '{') depth += 1;
      else if (ch === ')' || ch === ']' || ch === '}') depth -= 1;
      else if (ch === ',' && depth === 0) { end = k; break; }
    }
    const eq = text.slice(0, end);
    // Each word of it that is the name, a coefficient before it or not: 2Bx, 0.5 Bx.
    const fixed = eq.replace(/\S+/g, (tok) => {
      const m = /^((?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)?(.*)$/.exec(tok);
      return m[2] === from ? `${m[1] || ''}${to}` : tok;
    });
    if (fixed === eq) {
      setStatus(`${from} is not on line ${line} any more: the text has changed since the warning.`, 'warn');
      return;
    }
    if (state.tab !== 'model') showTab('model');
    let start = 0;
    for (let i = 0; i < line - 1; i += 1) start += lines[i].length + 1;
    ta.focus({ preventScroll: true });
    ta.setSelectionRange(start, start + eq.length);
    // As typed, for the browser's undo; where it will not, set, and said to the page as typing is.
    if (!document.execCommand('insertText', false, fixed)) {
      ta.setRangeText(fixed, start, start + eq.length, 'end');
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    }
    // What changed, shown: the equation as it is now, selected, its line in view.
    ta.setSelectionRange(start, start + fixed.length);
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 18;
    ta.scrollTop = Math.max(0, (line - 1) * lh - ta.clientHeight / 3);
  }

  /** Line n of the model text: on the Model tab, scrolled to, selected whole, the keyboard in it. */
  function goLine(n) {
    const ta = $('rtmText');
    const lines = ta.value.split('\n');
    if (!(n >= 1 && n <= lines.length)) return;
    if (state.tab !== 'model') showTab('model');
    let start = 0;
    for (let i = 0; i < n - 1; i += 1) start += lines[i].length + 1;
    ta.focus({ preventScroll: true });
    ta.setSelectionRange(start, start + lines[n - 1].length);
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 18;
    ta.scrollTop = Math.max(0, (n - 1) * lh - ta.clientHeight / 3);
  }

  /*
    WHERE A NAME IS USED: the name the caret is on -- a species, a parameter,
    a table -- and every line that names it, said in words under the text,
    each line a link that puts the caret on the name there. The lines are
    marked beside the line numbers and, with the colouring on, the name in
    the text itself, through the CSS Custom Highlight API: ranges over the
    coloured copy, so that nothing in it is rewritten and it still lines up
    with the text to the pixel. It is read from the text as it stands
    (RtmModel.usesOf), so a text that does not compile is read too.

    The line under the text keeps two lines' height, so that the text box
    stays where it is as the caret goes from name to name: a kind of line
    past USES_MANY lists its first USES_FIRST and "and 16 more", which lists
    them all. A line whose rate reads a species is said only where the line
    does not make it or use it up: every rate in a model like the built-in
    one reads what its line uses up, and saying so would say each line twice.
  */
  const USES_MANY = 6;
  const USES_FIRST = 4;
  const USE_MARK = 'rtm-use';
  /** What a line does with the name, in the order the sentence says it: [role, of one line, of several]. */
  const USE_WORDS = {
    species: [
      ['listed', 'in the list of species on', 'in the list of species on'],
      ['start', 'its starting amount set on', 'its starting amounts set on'],
      ['added', 'added on', 'added on'],
      ['made', 'made on', 'made on'],
      ['usedUp', 'used up on', 'used up on'],
      ['removed', 'removed on', 'removed on'],
      ['both', 'on both sides of', 'on both sides of'],
      ['twoWay', 'in the two-way reaction on', 'in the two-way reactions on'],
      ['read', 'read by the rate on', 'read by the rates on'],
      ['equilibrium', 'in the equilibrium on', 'in the equilibria on'],
      ['phase', 'in the phase on', 'in the phases on'],
      ['output', 'read by the output on', 'read by the outputs on'],
      ['data', 'measured, in the data on', 'measured, in the data on'],
      ['other', 'also on', 'also on'],
    ],
    parameter: [['set', 'set on', 'set on'], ['used', 'used on', 'used on']],
    table: [['table', 'given on', 'given on'], ['used', 'read on', 'read on']],
  };
  // The roles that say a species does something, and what is said where it does none.
  const USE_ACTS = ['added', 'made', 'usedUp', 'removed', 'both', 'twoWay', 'read', 'equilibrium', 'phase', 'output'];
  const USE_IDLE = {
    species: 'no line makes it, uses it up or reads it',
    parameter: 'used on no line',
    table: 'read on no line',
  };
  const USE_TERMS = ['added', 'made', 'usedUp', 'removed', 'both', 'twoWay'];

  let usesNames = { text: null, names: null };   // the text's names, read again when the text changes
  let usesNow = null;                             // what the line under the text shows: RtmModel.usesOf's
  let usesDrawn = null;
  let usesOpen = '';                              // kind|name whose lines are all listed
  let usesFrame = 0;
  let useLines = new Set();                       // the lines marked beside the line numbers

  /** Once a frame at most: the caret moves many times a frame while a selection is dragged. */
  function scheduleUses() {
    if (usesFrame) return;
    usesFrame = requestAnimationFrame(() => { usesFrame = 0; showUses(); });
  }

  function showUses() {
    const ta = $('rtmText');
    const box = $('rtmUses');
    if (!ta || !box || typeof RtmModel === 'undefined' || !RtmModel.usesOf) return;
    const text = ta.value;
    if (usesNames.text !== text) usesNames = { text, names: RtmModel.namesOf(text) };
    const at = RtmModel.nameAt(text, ta.selectionStart, ta.selectionEnd, usesNames.names);
    usesNow = at ? RtmModel.usesOf(text, at.name, at.kind) : null;
    // All of a name's lines stay listed while the caret stays on it.
    if (!usesNow || usesOpen !== `${usesNow.kind}|${usesNow.name}`) usesOpen = '';
    const here = text.slice(0, ta.selectionStart).split('\n').length;
    const key = usesNow ? `${usesNow.kind}|${usesNow.name}|${usesOpen === `${usesNow.kind}|${usesNow.name}`}|${here}|`
      + usesNow.places.map((p) => `${p.line}:${p.start}`).join(',') : '';
    if (key !== usesDrawn) {
      usesDrawn = key;
      drawUses(box, usesNow, here);
    }
    const lines = new Set(usesNow ? usesNow.places.map((p) => p.line) : []);
    if (lines.size !== useLines.size || [...lines].some((l) => !useLines.has(l))) {
      useLines = lines;
      renderLineNumbers();
    }
    markUses(usesNow);
  }

  /** The sentence under the text: the name, then what each kind of line does with it, each line a link. */
  function drawUses(box, uses, here) {
    box.replaceChildren();
    if (!uses) {
      box.textContent = 'Put the cursor on a name to see where it is used.';
      return;
    }
    const name = document.createElement('strong');
    name.textContent = uses.name;
    box.append(name, ' — ');
    const open = usesOpen === `${uses.kind}|${uses.name}`;
    const terms = new Set(USE_TERMS.flatMap((r) => uses.roles[r] || []));
    let said = 0;
    for (const [role, one, several] of USE_WORDS[uses.kind]) {
      let lines = uses.roles[role] || [];
      if (role === 'read' && uses.kind === 'species') lines = lines.filter((l) => !terms.has(l));
      if (!lines.length) continue;
      if (said) box.append(' · ');
      said += 1;
      box.append(`${lines.length === 1 ? one : several} `);
      if (lines.length === 1) {
        box.append(useLink(lines[0], `line ${lines[0]}`, here));
        continue;
      }
      box.append('lines ');
      const shown = open || lines.length <= USES_MANY ? lines : lines.slice(0, USES_FIRST);
      shown.forEach((l, i) => {
        if (i) box.append(i === shown.length - 1 && shown.length === lines.length ? ' and ' : ', ');
        box.append(useLink(l, String(l), here));
      });
      if (shown.length < lines.length) {
        const more = document.createElement('button');
        more.type = 'button';
        more.className = 'rtm-line-link';
        more.dataset.onClick = 'rtm:usesMore';
        more.textContent = `${lines.length - shown.length} more`;
        box.append(' and ', more);
      }
    }
    const acts = uses.kind === 'species' ? USE_ACTS : ['used'];
    if (!acts.some((r) => (uses.roles[r] || []).length)) box.append(said ? ' · ' : '', USE_IDLE[uses.kind]);
  }

  /** A line the name is on, as a link that puts the caret on the name there; the caret's own line in bold. */
  function useLink(line, label, here) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = line === here ? 'rtm-line-link here' : 'rtm-line-link';
    b.dataset.onClick = 'rtm:goUse';
    b.dataset.line = String(line);
    b.textContent = label;
    return b;
  }

  /** The name on line n, selected, the keyboard in the text; scrolled to only where the line is out of view. */
  function goUse(n) {
    const ta = $('rtmText');
    const p = usesNow && usesNow.places.find((q) => q.line === n);
    if (!p) { goLine(n); return; }
    const lines = ta.value.split('\n');
    let start = 0;
    for (let i = 0; i < n - 1; i += 1) start += lines[i].length + 1;
    if (state.tab !== 'model') showTab('model');
    ta.focus({ preventScroll: true });
    ta.setSelectionRange(start + p.start, start + p.end);
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 18;
    const pad = parseFloat(getComputedStyle(ta).paddingTop) || 0;
    const top = pad + (n - 1) * lh;
    if (top < ta.scrollTop || top + lh > ta.scrollTop + ta.clientHeight) {
      ta.scrollTop = Math.max(0, (n - 1) * lh - ta.clientHeight / 3);
    }
    scheduleUses();
  }

  /** The name marked wherever it stands in the coloured copy: none where the colouring is off or the API missing. */
  function markUses(uses) {
    if (typeof Highlight !== 'function' || typeof CSS === 'undefined' || !CSS.highlights) return;
    const code = $('rtmHighlight') && $('rtmHighlight').firstElementChild;
    const ranges = [];
    if (uses && state.syntax && code) {
      for (const p of uses.places) {
        const el = code.children[p.line - 1];
        const r = el && textRange(el, p.start, p.end);
        if (r) ranges.push(r);
      }
    }
    if (ranges.length) CSS.highlights.set(USE_MARK, new Highlight(...ranges));
    else CSS.highlights.delete(USE_MARK);
  }

  /** A range over characters start to end of an element's text, across the spans the colouring split it into. */
  function textRange(el, start, end) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const r = document.createRange();
    let pos = 0;
    let begun = false;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const len = node.data.length;
      if (!begun && start < pos + len) { r.setStart(node, start - pos); begun = true; }
      if (begun && end <= pos + len) { r.setEnd(node, end - pos); return r; }
      pos += len;
    }
    return null;
  }

  /*
    THE MODEL'S OWN DESCRIPTION: the comment its text begins with, before
    anything else in it. Its first line with words, written ## -- as
    MATLAB's %% starts a cell -- is its title, a rule of = or - before it
    left aside. Its lines run together into paragraphs, a line of only #
    between them; a line indented further than the rest -- a table of
    reactions, a formula -- keeps its line and its spacing; a rule of = or -
    alone, which only draws a box, is left out. { title, blocks: [{ pre,
    text }] }, empty where the text does not begin with a comment.
  */
  function modelAbout(text) {
    const raws = [];
    for (const raw of String(text || '').split(/\r?\n/)) {
      if (!raws.length && !raw.trim()) continue;
      if (!/^\s*#/.test(raw)) break;
      raws.push(raw);
    }
    let title = '';
    let words = false;
    const lines = [];
    for (const raw of raws) {
      const [, hashes, rest] = /^\s*(#+)(.*)$/.exec(raw);
      if (!rest.trim() || /^\s*([=\-*_~#+])\1{2,}\s*$/.test(rest)) { lines.push(''); continue; }
      if (!words && hashes.length >= 2) { title = rest.trim(); words = true; continue; }
      words = true;
      lines.push(rest.replace(/\s+$/, ''));
    }
    // The comment's own margin, the least indent of its words: a line indented further is a table's.
    const indents = lines.filter((l) => l.trim()).map((l) => /^ */.exec(l)[0].length);
    const margin = indents.length ? Math.min(...indents) : 0;
    const blocks = [];
    let cur = null;
    for (const l of lines) {
      if (!l.trim()) { cur = null; continue; }
      const body = l.slice(margin);
      const pre = /^\s/.test(body);
      if (!cur || cur.pre !== pre) { cur = { pre, lines: [] }; blocks.push(cur); }
      cur.lines.push(pre ? body : body.trim());
    }
    return {
      title,
      blocks: blocks.map((bl) => {
        if (!bl.pre) return { pre: false, text: bl.lines.join(' ') };
        // A table starts at its own left edge.
        const cut = Math.min(...bl.lines.map((l) => /^ */.exec(l)[0].length));
        return { pre: true, text: bl.lines.map((l) => l.slice(cut)).join('\n') };
      }),
    };
  }

  /*
    A long description is folded after its first paragraph, More opening the
    rest; a first paragraph that is long itself, after its first sentences.
    Long: more than ABOUT_LONG characters, the title aside. Folded, a long
    first paragraph shows its sentences up to ABOUT_LEAD characters, one at
    least -- cut at a word, with an ellipsis, only where that one is longer
    than ABOUT_LONG. Opened, it stays open until another description comes.
  */
  const ABOUT_LONG = 300;
  const ABOUT_LEAD = 200;
  let aboutOpen = false;
  let aboutKey = '';
  function aboutLead(text) {
    const ends = [];
    const re = /[.!?]["')\]]*(?=\s+["'(<A-Z0-9]|$)/g;
    for (let m = re.exec(text); m; m = re.exec(text)) ends.push(m.index + m[0].length);
    const within = ends.filter((e) => e <= ABOUT_LEAD);
    if (within.length) return text.slice(0, within[within.length - 1]);
    if (ends.length && ends[0] <= ABOUT_LONG) return text.slice(0, ends[0]);
    const at = text.lastIndexOf(' ', ABOUT_LEAD);
    return `${text.slice(0, at > 0 ? at : ABOUT_LEAD)}…`;
  }

  function renderAbout() {
    const box = $('rtmAbout');
    const { title, blocks } = modelAbout(state.text);
    const key = [title, ...blocks.map((bl) => bl.text)].join('\n');
    if (key !== aboutKey) { aboutKey = key; aboutOpen = false; }
    const long = blocks.reduce((n, bl) => n + bl.text.length, 0) > ABOUT_LONG;
    const first = blocks[0];
    const shown = !long || aboutOpen ? blocks
      : [first.pre || first.text.length <= ABOUT_LONG ? first : { pre: false, text: aboutLead(first.text) }];
    const els = [];
    if (title) {
      const h = document.createElement('p');
      h.className = 'rtm-about-title';
      h.textContent = title;
      els.push(h);
    }
    for (const bl of shown) {
      const el = document.createElement(bl.pre ? 'pre' : 'p');
      el.textContent = bl.text;
      els.push(el);
    }
    if (long) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'rtm-more rtm-about-more';
      more.dataset.onClick = 'rtm:aboutMore';
      more.setAttribute('aria-expanded', String(aboutOpen));
      more.textContent = aboutOpen ? 'Less' : 'More';
      els.push(more);
    }
    box.replaceChildren(...els);
    box.hidden = !els.length;
  }

  /*
    WHAT THE PAGE SOLVES, said from the compiled model a sentence at a
    time: a batch, or a column and the rock behind it, and for how long; the
    species and the reactions with a rate law; what moves, and through which
    ends; the relations held at equilibrium and how, between activities or
    concentrations, with exchangers, surfaces, the electron, a gas, solid
    solutions; the temperature; parameters, tables, what is read at the
    clock; and how many equations that makes.
  */
  function renderFacts() {
    renderAbout();
    const el = $('rtmFacts');
    const m = state.compiled;
    if (!m) { el.textContent = state.compileError ? 'Does not compile; see the Model tab.' : 'Not compiled yet.'; return; }
    const s = m.settings;
    const count = (n, one, many) => `${n} ${n === 1 ? one : many || `${one}s`}`;
    const listed = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
    const say = [];
    const tend = fmtTime(s.TEND);
    if (m.transport) {
      // The layout in words: its kind, the number that shapes it, and a pinned surface layer when there is one.
      const g = m.grid || { kind: s.GRID };
      const shape = g.kind === 'log' ? `on a log grid, the last cell ${g.ratio}× the first`
        : g.kind === 'powerlaw' ? `on a power-law grid, exponent ${g.power}`
          : g.kind === 'faces' ? 'its faces as given' : g.kind === 'linear' ? 'evenly spaced' : `on a ${g.kind} grid`;
      say.push(`A column of ${count(m.fracture, 'cell')} over ${fmtLength(m.length != null ? m.length : s.LENGTH)}, ${shape}`
        + `${g.surface > 0 ? `, the first a surface layer ${g.surface} m thick` : ''}, run for ${tend}.`);
    } else {
      say.push(`A batch, one well-mixed water, run for ${tend}.`);
    }
    say.push(`${count(m.nspecies, 'species', 'species')} and ${m.nreactions ? count(m.nreactions, 'reaction') : 'no reactions'} `
      + 'with a rate law.');
    if (m.transport) {
      if (m.matrix) {
        // How the layers came out: the first, how they grow, and why the first is what it is -- the thing a reader most
        // needs to see of a layout worked out for them.
        const x = m.matrix;
        const why = { matched: 'worked out from the path', e: 'FARFCOMP’s rule', given: 'MATRIX_FIRST' }[x.rule] || '';
        say.push(`Behind each cell, rock in ${count(x.n, 'matrix layer')} to ${x.total} m, ${x.grid}: the first `
          + `${fmtLength(x.thickness[0])}${why ? ` (${why})` : ''}${x.n > 1 ? `, growing by ${x.ratio.toFixed(3)}` : ''}; `
          + `porosity ${x.porosity}, ${fmtNumber(x.aw)} m² of wall per m³ of water.`);
        say.push(x.enters.length ? `${listed(x.enters)} enter${x.enters.length === 1 ? 's' : ''} the rock.`
          : 'Nothing enters the rock.');
      }
      const moves = [];
      if (s.DIFFUSION) {
        moves.push(`${s.DIFFUSION === 2 ? 'Nernst-Planck diffusion' : 'diffusion'}`
          + `${s.DIFFUSION_GRADIENT === 'activity' ? ' down the activities' : ''}`);
      }
      if (s.ADVECTION && s.VELOCITY) {
        moves.push(`${s.ADVECTION_SCHEME === 'limited' ? 'limited ' : ''}advection at ${fmtNumber(s.VELOCITY)} m/${timeUnit().symbol}`
          + (m.travelTime ? `, a travel time of ${fmtTime(m.travelTime)}` : ''));
      }
      say.push(moves.length ? `Transport by ${moves.join(' and ')}${s.PECLET > 0 && s.ADVECTION ? `; Peclet number ${s.PECLET}` : ''}.`
        : 'Nothing moves between the cells.');
      // Each end by its name and what it does, in a few words.
      const does = {
        dirichlet: 'held at what it is given', neumann: 'nothing crosses it', robin: 'the flow carries in what it is given',
        free: 'the flow takes what it takes', 'semi-infinite': 'the column goes on past it',
        reservoir: 'a well-mixed water of its own, which reacts',
      };
      say.push(`The left end is ${s.LEFT}${does[s.LEFT] ? `: ${does[s.LEFT]}` : ''}.`);
      say.push(`The right end is ${s.RIGHT}${does[s.RIGHT] ? `: ${does[s.RIGHT]}` : ''}`
        + `${m.extra ? `, in ${count(m.extra.n, 'more cell')}` : ''}.`);
    }
    if (m.nequilibria) {
      const n = m.nequilibria;
      const h = m.heldEquilibria;
      const a = m.activity;
      say.push(`${count(n, 'relation')} at equilibrium, which conserve${n === 1 ? 's' : ''} ${count(m.nconserved, 'total')}.`);
      if (m.speciated) {
        say.push(`The water is brought to equilibrium before the run starts, in ${count(m.speciated.iterations, 'iteration')}.`);
      }
      if (h) {
        say.push(`${h.relations === n ? (n === 1 ? 'It is' : 'All are') : `${h.relations} are`} held exactly at every step of `
          + `the run: ${count(h.species, 'species', 'species')} worked out from the totals in every cell`
          + `${h.minerals ? `, ${count(h.minerals, 'mineral')} at saturation while there is any` : ''}.`);
      }
      if (a) {
        const name = { davies: 'Davies', sit: 'SIT', pitzer: 'Pitzer', llnl: 'LLNL’s B-dot' }[a.kind] || 'Debye–Hückel';
        const own = [
          ...(a.kind === 'sit' ? [`${count(a.sit, 'pair')} in <SIT>`] : []),
          ...(a.kind === 'pitzer' && a.pitzer ? [`${count(a.pitzer.params, 'parameter')} in <PITZER>`
            + `${a.pitzer.macinnes ? ', MacInnes scaled' : ''}`] : []),
        ];
        // Volumes that correct no log K say so, unless <CONDUCTANCE> makes the density of them.
        const vol = !a.volumes || (a.volumes.idle && a.conductance) ? ''
          : a.volumes.idle ? '; log K at 1 atm: the molar volumes in <VOLUMES> correct nothing'
            : `; log K at the pressure from ${count(a.volumes.given, 'molar volume')} in <VOLUMES>`;
        say.push(`The relations hold between activities, by ${name} at `
          + `${typeof a.temperature === 'number' ? `${a.temperature}\u00a0°C` : 'each cell’s temperature'}, for ${count(a.ions, 'ion')}`
          + `${own.length ? `, with ${own.join(', ')}` : ''}${vol}.`);
        if (a.conductance) say.push('The conductance, the density and the viscosity come from <CONDUCTANCE>.');
      } else {
        say.push('The relations hold between concentrations: no activity coefficients.');
      }
      if (m.exchange) {
        say.push(`${count(m.exchange.species, 'species', 'species')} on the exchanger${m.exchange.exchangers.length === 1 ? ''
          : 's'} ${m.exchange.exchangers.join(', ')}, by Gaines–Thomas.`);
      }
      if (m.surface) {
        const pots = (m.surface.potentials || []).map((pp) => `${pp.plane !== null && pp.plane !== undefined
          ? `CD-MUSIC's plane ${pp.plane} ` : 'the double layer\'s '}potential ${pp.name}${pp.psi ? ` at ${fmtMv(pp.psi)} to start with` : ''}`);
        say.push(`${count(m.surface.species, 'species', 'species')} on ${m.surface.sites.length === 1 ? 'a surface'
          : `${m.surface.sites.length} kinds of surface site`} (${m.surface.sites.join(', ')}), each with its fraction of the `
          + `sites for its activity${pots.length ? `; ${pots.join(', ')}` : ''}.`);
      }
      if (m.redox) {
        say.push(`${count(m.redox.relations, 'relation')} tied to the electron ${m.redox.name}`
          + `${m.redox.pe ? `, pe ${fmtPe(m.redox.pe)} ${m.redox.fixed ? 'held' : 'at the start'}` : ''}.`);
      }
      if (m.gas) {
        say.push(`${m.gas.species.join(', ')} in a gas phase ${m.gas.fixed === 'volume'
          ? `of ${fmtNumber(m.gas.volume)} L to each kg of water, each gas at n R T/V`
          : `at ${fmtNumber(m.gas.pressure)} atm, a bubble while the water holds its gases at that between them`}.`);
      }
      for (const ss of m.solidSolutions || []) {
        say.push(`The solid solution ${ss.name} (${ss.members.join(', ')}), ${ss.binary
          ? `a0 ${fmtNumber(ss.binary.a0)} and a1 ${fmtNumber(ss.binary.a1)} at 25 °C${ss.binary.gap ? ', a miscibility gap' : ''}`
          : 'ideal'}, there while the water is saturated in it.`);
      }
    }
    // The temperature, where it goes with the cell or the time, and the log K that follow it.
    const T = m.temperature;
    if (T && (T.varies || T.relations || T.phases)) {
      // A number and its unit kept on one line.
      const range = T.start ? (T.start[0] === T.start[1] ? `${fmtNumber(T.start[0])}\u00a0°C`
        : `${fmtNumber(T.start[0])} to ${fmtNumber(T.start[1])}\u00a0°C`) : '';
      const how = !T.varies ? `${fmtNumber(T.given)}\u00a0°C`
        : `${T.given}: ${range}${T.cells ? ' from cell to cell' : ''}`
          + `${T.clock ? `${T.cells ? ', ' : ' '}at the start, and it goes with time` : ''}`;
      const k = T.relations + T.phases;
      say.push(`The temperature is ${how}${k ? `; ${k} log K ${k === 1 ? 'follows' : 'follow'} it, by dH or an analytic `
        + 'expression' : ''}.`);
    }
    // The unit labels follow the model: a run in years should not be asked
    // for a "from" time in seconds.
    const u = timeUnit();
    $('rtmTendUnit').textContent = `${u.name}s, or with a unit; blank uses TEND from the text`;
    $('rtmHmaxUnit').textContent = `${u.name}s; 0: a tenth of the run for the NDF, no limit for the ports`;
    $('rtmH0Unit').textContent = `${u.name}s; 0: chosen from the derivative at the start`;
    // The charts' time: in the model's unit, or in pore volumes where the water flows; each "from" in it.
    renderTimeIn();
    if (m.nparameters) say.push(`${count(m.nparameters, 'parameter')}: ${m.parameters.join(', ')}.`);
    if (m.tables && m.tables.length) say.push(`${count(m.tables.length, 'table')}: ${m.tables.join(', ')}.`);
    // A release history, or anything else a rate law reads at the clock, and
    // the corners the run is started again at so that none is stepped over.
    if (m.clockTables && m.clockTables.length) {
      say.push(`Read at the clock: ${listed(m.clockTables.map((c) => c.name))}`
        + (m.breaks ? `, the run started again at ${count(m.breaks, 'corner')} up to TEND` : '') + '.');
    }
    // A species held in some cells only; one held everywhere is in its line.
    for (const h of m.held || []) {
      const c = h.cells;
      const contiguous = c.every((v, k) => k === 0 || v === c[k - 1] + 1);
      const where = c.length === 1 ? `cell ${c[0]}`
        : contiguous ? `cells ${c[0]}–${c[c.length - 1]}` : `${c.length} cells`;
      say.push(`${h.species} is held in ${where}.`);
    }
    if (m.anyMass) say.push('A mass matrix is in force.');
    say.push(`${count(m.states, 'equation')} to solve, with ${count(m.nnz, 'non-zero')} in their Jacobian.`);
    el.replaceChildren(...say.map((t) => {
      const p = document.createElement('p');
      p.textContent = t;
      return p;
    }));
  }

  /* ---------------------------------------------------------------------
     Running
     --------------------------------------------------------------------- */
  function solverPayload() {
    const s = state.solver;
    const num = (v, what, test) => {
      const x = Number(v);
      if (!test(x)) throw new Error(what);
      return x;
    };
    const maxOrder = Math.round(num(s.maxOrder, 'The maximum order must be 1 to 5', (x) => x >= 1 && x <= 5));
    const out = {
      method: s.method,
      bdf: !!s.bdf,
      rtol: num(s.rtol, 'The relative tolerance must be between 0 and 1', (x) => x > 0 && x < 1),
      atol: num(s.atol, 'The absolute tolerance must be a non-negative number', (x) => x >= 0),
      matrix: s.matrix,
      norm: s.norm,
      maxOrder,
      // Pinned below the maximum, as facsimile.html does: a floor above the
      // ceiling is a fixed order at the ceiling.
      minOrder: Math.min(maxOrder, Math.round(num(s.minOrder, 'The minimum order must be 1 to 5',
        (x) => x >= 1 && x <= 5))),
      hmax: num(s.hmax || 0, `The maximum step must be a non-negative number of ${timeUnit().name}s`, (x) => x >= 0),
      h0: num(s.h0 || 0, `The first step must be a non-negative number of ${timeUnit().name}s`, (x) => x >= 0),
      normControl: !!s.normControl,
      jacobianMode: s.jacobianMode === 'numeric' ? 'numeric' : 'analytic',
      kappa: num(s.kappa, 'The Newton tolerance must be a number between 0 and 1', (x) => x > 0 && x < 1),
      maxJacAge: Math.round(num(s.maxJacAge, 'A Jacobian must be reused for at least one step', (x) => x >= 1)),
      belowTolRun: Math.round(num(s.belowTolRun, 'Steps at the floor must be a count of zero or more', (x) => x >= 0)),
      stagnationTol: num(s.stagnationTol, 'The stall tolerance must be a number from 0 to 1', (x) => x >= 0 && x <= 1),
      maxSteps: num(s.maxSteps, 'The step budget must be at least 100', (x) => x >= 100),
      // The engine keeps at least 1000 whatever it is told, so that is the floor
      // said here rather than a smaller number it would quietly raise.
      maxPoints: num(s.maxPoints, 'Points kept must be at least 1000', (x) => x >= 1000),
      nonNegative: s.nonNegative,
      autoAtol: s.autoAtol,
      smoothEst: s.smoothEst !== false,
    };
    if (String(s.tend).trim()) {
      // A unit of its own may follow the number, as in TEND: 1890 days.
      let t = NaN;
      try { t = RtmModel.readTime(s.tend, timeUnit().name, 'The simulated time'); } catch (e) { t = NaN; }
      if (!(t > 0)) {
        throw new Error(`The simulated time must be a positive number of ${timeUnit().name}s, or one with its unit: 1890 days`);
      }
      out.tend = t;
    }
    return out;
  }

  async function run() {
    if (state.running) return;
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    const refusal = methodRefusal(solver.method);
    if (refusal) { setStatus(refusal, 'error'); return; }
    /*
      A compile is scheduled a moment after the last keystroke, and run()
      compiles anyway. Leaving the scheduled one to fire meant it landed after
      the run had finished and replaced "Done in 0.6 s ..." with "Compiled:
      ...", which reads as though nothing had been run at all. Cancelled here
      rather than first, so that a run refused above leaves it to fire.
    */
    clearTimeout(compileTimer);
    if (!(await compile())) return;

    // What this run was given, kept for the HDF5 file: the panel can be
    // changed while a run is going, and the file must say what was solved.
    state.ran = { solver, text: state.text };

    state.running = true;
    $('rtmRun').disabled = true;
    $('rtmVerify').disabled = true;
    $('rtmStop').disabled = false;
    setProgress(0);
    setStatus(`Running ${methodLabel()}…${inlineWarning()}`);
    // Inline, the run blocks everything that follows, so the bar and the line
    // above it have to reach the screen first or they never appear at all.
    if (workerKind === 'inline') await repaint();
    const started = Date.now();
    try {
      const reply = await request({ type: 'run', text: state.text, solver }, (p) => {
        setProgress(p.frac);
        setStatus(`Running ${methodLabel()}: ${fmtTime(p.t)} of ${fmtTime(p.tend)}, `
          + `${p.nsteps.toLocaleString()} steps`);
      });
      state.result = reply;
      afterRun(reply, Date.now() - started);
    } catch (e) {
      if (e.partial) { state.result = e.partial; afterRun(e.partial, Date.now() - started, true); }
      setProgress(null);
      setStatus(`The run failed: ${e.message}`, 'error');
    } finally {
      state.running = false;
      $('rtmRun').disabled = false;
      $('rtmVerify').disabled = false;
      $('rtmStop').disabled = true;
    }
  }

  function afterRun(reply, ms, partial) {
    setProgress(null);
    profileStop();
    compStop();
    // A check is of the run it checked.
    checkNow = null;
    state.compiled = reply.model;
    // A look at the run before this one, through PHREEQC, stays on its tab and says which run it is.
    runNumber++;
    renderFacts();
    renderBeside();
    infoRefresh();
    renderSeriesList();
    renderCells();
    renderProfileSpecies();
    renderGradSpecies();
    renderUnits();
    renderComp();
    renderDg();
    renderSw();
    renderFit();
    renderUn();
    drawTime();
    drawProfile();
    drawGradient();
    drawComp();
    // The run against what was measured, where it is open; else when its tab is shown.
    if (state.tab === 'fit') drawFit();
    else renderFitShow();
    pqRenderView();
    if (partial) return;
    openExampleView();
    const st = reply.stats || {};
    /*
      A fixed species is held at the value it was given, because its row in
      both the right-hand side and the Jacobian is exactly zero and so its
      answer is that value. The solver still leaves round-off in it -- about
      1e-13 on the built-in model -- which the worker writes back out. That is
      arithmetic, not chemistry, and worth a word only if it is ever big
      enough to be something else.
    */
    const drift = reply.heldDrift > 1e-8
      ? ` A fixed species moved by ${reply.heldDrift.toExponential(1)} before being held, `
        + 'which is more than round-off: check the tolerances.'
      : '';
    // The switching solvers say which of their methods took the steps; an
    // explicit method, and FBDF by GMRES, factorise nothing.
    const methods = methodSteps(st);
    const matrix = !st.ndecomps ? 'no iteration matrix'
      : st.lu === 'refactor' ? 'sparse LU keeping its pivots' : st.sparse ? 'sparse LU' : 'dense LU';
    // Started again at the corners of a table read at the clock: said, since
    // it is what a run with a release history spends its first steps on.
    const restarts = st.breaks ? `, started again at ${st.breaks.toLocaleString()} table corner${st.breaks === 1 ? '' : 's'}` : '';
    // Minerals held at saturation: when one dissolved away or precipitated,
    // the run stopped there and went on; the first and the last are named.
    const ev = reply.events || [];
    const said = (e) => `${e.what} at ${fmtTime(e.t)}`;
    const minerals = !ev.length ? ''
      : ev.length === 1 ? ` ${said(ev[0])}.`
        : ` ${ev.length.toLocaleString()} mineral changes, from “${said(ev[0])}” to “${said(ev[ev.length - 1])}”.`;
    setStatus(`Done in ${(ms / 1000).toFixed(2)} s — ${(st.nsteps || 0).toLocaleString()} steps `
      + `(${(st.nfailed || 0).toLocaleString()} rejected)${methods ? `: ${methods}` : ''}${restarts}, ${reply.n.toLocaleString()} points kept, `
      + `${matrix}.${minerals}${drift}`, drift ? 'warn' : 'ok');
  }

  /**
   * The switching solvers' account of a run, in words: which of their
   * methods took how many of the steps, and how often they changed between
   * them -- "Vern7 11 steps, NDF 1874; 1 switch". facsimile.html and
   * Kompartment say it the same way. Null for every other method.
   */
  function methodSteps(st) {
    if (!st || !st.stepsBy) return null;
    const parts = Object.entries(st.stepsBy).map(([name, k], i) => `${name} ${k.toLocaleString()}${i === 0 ? ` step${k === 1 ? '' : 's'}` : ''}`);
    const sw = st.switches || 0;
    return `${parts.join(', ')}; ${sw} switch${sw === 1 ? '' : 'es'}`;
  }

  function stop() {
    if (!state.running && !dgBusy && !dgBoundsAsked && !dgLadderAsked) return;
    if (worker) { worker.terminate(); worker = null; workerKind = 'none'; pending.clear(); }
    state.running = false;
    // A sweep or a diagram stopped with the worker: what waited on it never hears, so its buttons come back here.
    swBusy = false;
    dgBusy = false;
    // Boundaries stopped are not asked for again: the map stays as its points.
    if (dgBoundsAsked) dgBoundsAsked.res.bounds.set(dgBoundsAsked.sig, null);
    dgBoundsAsked = null;
    if (dgLadderAsked) (dgLadderAsked.couples ? dgLadderAsked.res.couples : dgLadderAsked.res.ladders).set(dgLadderAsked.sig, null);
    dgLadderAsked = null;
    fitBusy = false;
    unBusy = false;
    // A check stopped is not made: Check the run comes back under the table.
    const checked = checkBusy;
    checkBusy = null;
    if (checked) drawEvery(state.result);
    $('rtmSwGo').disabled = false;
    $('rtmDgGo').disabled = false;
    $('rtmFitGo').disabled = false;
    $('rtmUnGo').disabled = false;
    $('rtmRun').disabled = false;
    $('rtmVerify').disabled = false;
    $('rtmStop').disabled = true;
    setProgress(null);
    setStatus('Stopped.');
  }

  /**
   * What to call the chosen method in prose: the menu's text without where it
   * came from, and with the BDF formulas switch on the method that runs --
   * NDF as BDF, QNDF as QBDF.
   */
  function methodLabel() {
    const chosen = $('rtmMethod').selectedOptions[0];
    const name = chosen ? chosen.textContent.replace(/\s*[↓(].*$/, '').trim() : state.solver.method;
    return $('rtmBdf').checked && readsBdf($('rtmMethod').value) ? name.replace(/NDF$/, 'BDF') : name;
  }

  /* ---------------------------------------------------------------------
     Checking the Jacobian
     --------------------------------------------------------------------- */
  async function verify() {
    if (state.running) return;
    setStatus('Checking the Jacobian…');
    try {
      const reply = await request({ type: 'verify', text: state.text });
      state.verify = reply;
      showTab('jacobian');
      renderVerify();
      const bad = reply.checks.reduce((a, c) => a + c.ndiscrepancies, 0);
      setStatus(bad
        ? `${bad} entr${bad === 1 ? 'y' : 'ies'} disagree with a difference; see the Jacobian tab.`
        : 'The Jacobian agrees with a central difference everywhere it can be measured.',
      bad ? 'error' : 'ok');
    } catch (e) {
      setStatus(`The check failed: ${e.message}`, 'error');
    }
  }

  function renderVerify() {
    const el = $('rtmVerifyOut');
    const v = state.verify;
    if (!v) { el.innerHTML = ''; return; }
    const rows = v.checks.map((c) => {
      const head = `<p><strong>${esc(c.label)}</strong>: ${c.checked.toLocaleString()} entries `
        + `compared, ${c.ndiscrepancies} disagreed`
        + (c.unresolvable ? `, ${c.unresolvable.toLocaleString()} too small beside the largest in `
          + 'their column for a difference to measure' : '') + '.</p>';
      if (!c.ndiscrepancies) return head;
      const body = c.discrepancies.map((d) => `<tr><td>${esc(d.row)}</td><td>${esc(d.col)}</td>`
        + `<td>${d.analytic.toExponential(4)}</td><td>${d.numeric.toExponential(4)}</td></tr>`).join('');
      return `${head}<table><thead><tr><th>d f[..]</th><th>/ d[..]</th><th>analytic</th>`
        + `<th>differenced</th></tr></thead><tbody>${body}</tbody></table>`;
    }).join('');
    el.innerHTML = rows;
  }

  /* ---------------------------------------------------------------------
     The Jacobian pattern
     --------------------------------------------------------------------- */
  /** The (row, column) pairs a block mask holds, worked out once per draw. */
  function blockCoords(mask, ns) {
    const out = [];
    for (let r = 0; r < ns; r++) {
      for (let c = 0; c < ns; c++) if (mask[r * ns + c]) out.push(r, c);
    }
    return out;
  }

  function drawJacobianPattern() {
    const canvas = $('rtmJacCanvas');
    const m = state.compiled;
    if (!canvas || !m) return;
    // The species' part: the totals of equilibria held throughout the run
    // come after them in the state and are not drawn.
    const n = m.speciesStates || m.states;
    const size = Math.min(620, Math.max(200, n));
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    const css = getComputedStyle(document.documentElement);
    ctx.fillStyle = css.getPropertyValue('--bg-surface').trim() || '#fff';
    ctx.fillRect(0, 0, size, size);
    const accent = css.getPropertyValue('--color-kvot-accent').trim() || '#b5651d';
    const ink = css.getPropertyValue('--text-primary').trim() || '#222';
    const ns = m.nspecies;
    const scale = size / n;
    const dot = Math.max(1, Math.floor(scale));
    const note = $('rtmJacNote');

    /*
      The whole pattern is too big to post for a long column, but it has only
      three distinct blocks -- a cell against itself, and against each of its
      two neighbours -- and the worker sends those. Drawing from them is the
      real pattern: an earlier version filled each cell's block solid, which
      made a batch model one square and told a reader nothing.
    */
    if (!m.blocks) {
      ctx.fillStyle = accent;
      for (let i = 0; i < m.cells; i++) {
        const b = i * ns * scale;
        ctx.fillRect(b, b, Math.max(1, ns * scale), Math.max(1, ns * scale));
      }
      if (note) note.textContent = '';
      return;
    }
    const b = m.blocks;
    // One block per cell offset the pattern has: 0 is the chemistry of a cell
    // against itself; the others are transport, to whichever cells this
    // model couples -- neighbours along a column, the rock layers behind a
    // fracture cell and the next fracture cell in a dual-porosity one.
    const blocks = b.offsets.map((o) => ({ off: o.off, coords: blockCoords(o.mask, ns) }));
    let couplings = 0;
    for (let i = 0; i < m.cells; i++) {
      const o = i * ns;
      for (const blk of blocks) {
        const target = i + blk.off;
        if (target < 0 || target >= m.cells) continue;
        ctx.fillStyle = blk.off === 0 ? accent : ink;
        const c0 = target * ns;
        for (let k = 0; k < blk.coords.length; k += 2) {
          ctx.fillRect((c0 + blk.coords[k + 1]) * scale, (o + blk.coords[k]) * scale, dot, dot);
        }
        if (blk.off !== 0) couplings += blk.coords.length / 2;
      }
    }
    if (!note) return;
    const diag = blocks.find((blk) => blk.off === 0);
    const chem = diag ? diag.coords.length / 2 : 0;
    const whole = `${m.nnz} non-zeros (${(100 * m.density).toFixed(2)} % of the matrix)`;
    const bits = [n === m.states ? `${n} × ${n}, ${whole}`
      : `the species' ${n} × ${n} of the ${m.states} × ${m.states} the solver works with, which has ${whole}; `
        + `the ${m.states - n} totals the held equilibria conserve are not drawn`,
    `the chemistry of one cell is ${chem} of the ${ns * ns} it could be`];
    if (m.cells > 1) bits.push(`${couplings} transport couplings across ${blocks.length - 1} kinds of neighbour`);
    note.textContent = `${bits.join('; ')}.`;
  }

  /* ---------------------------------------------------------------------
     The species picker
     --------------------------------------------------------------------- */
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function speciesNames() {
    return (state.compiled && state.compiled.species) || [];
  }

  /*
    QUANTITIES: what the run can be read as besides its species -- the
    water's pH, pe, Eh and ionic strength, element totals, saturation indices,
    log activities, gases, what is on an exchanger or a surface, and the
    text's <OUTPUT> -- as the model lists them (compile's QUANTITIES). Each
    has a key, which the charts pick by and <DATA> names a column by, a
    label, a group and an axis: 'conc' for an amount, on the left with the
    species, 'index' for the rest, on the right.
  */
  const quantityList = () => (state.compiled && state.compiled.quantities) || [];
  const quantityOf = (key) => quantityList().find((q) => q.key === key) || null;
  /** Whether a key is one of the model's quantities rather than a species. */
  const isQuantity = (key) => !speciesNames().includes(key) && !!quantityOf(key);
  const GROUP_ORDER = ['water', 'totals', 'saturation', 'gases', 'exchange', 'surface', 'outputs', 'reactions', 'activities'];
  const GROUP_LABELS = { species: 'Species', water: 'The water', totals: 'Totals in the water', saturation: 'Saturation indices',
    gases: 'Gases', exchange: 'On the exchanger', surface: 'On the surface', outputs: 'From <OUTPUT>',
    reactions: 'What each reaction does', activities: 'Log activities' };
  // Shut until opened: the log activities, one a solute; and what each reaction does in a network of more than six lines,
  // two entries a line.
  const GROUP_SHUT = new Set(['activities']);
  const REACTIONS_OPEN_MOST = 12;
  /** A key as the charts and their legends name it: a species its name, a quantity its label. */
  const labelOf = (key) => (isQuantity(key) ? quantityOf(key).label : key);
  /** A key as a right-hand axis's title names it: a quantity with a unit its label and the unit, Eh (V); else its label. */
  const axisLabelOf = (key) => {
    if (!isQuantity(key)) return key;
    const q = quantityOf(key);
    return q.unit && !q.label.includes(q.unit) ? `${q.label} (${q.unit})` : q.label;
  };
  /** Which axis a key goes on: the left for a species and an amount, the right for the rest. */
  const axisOf = (key) => (isQuantity(key) && quantityOf(key).axis === 'index' ? 'index' : 'conc');

  /**
   * The groups a picker offers, in order: the species, then each group of quantities that has any. `sums` false leaves out
   * what is a sum over the run, a reaction's extent: Diagrams, Sweeps and Uncertainty read a quantity point by point.
   */
  function pickerGroups(sums = true) {
    const groups = [{ id: 'species', items: speciesNames().map((nm) => ({ key: nm, label: nm })) }];
    for (const g of GROUP_ORDER) {
      const items = quantityList().filter((q) => q.group === g && (sums || !q.of)).map((q) => ({ key: q.key, label: q.label }));
      if (items.length) groups.push({ id: g, items });
    }
    return groups;
  }

  /** <optgroup>s of every key a one-quantity chart can show, `chosen` selected; `sums` as pickerGroups has it. */
  function pickerOptions(chosen, sums = true) {
    return pickerGroups(sums).map((g) => `<optgroup label="${esc(GROUP_LABELS[g.id])}">${g.items.map((it) => `<option value="`
      + `${esc(it.key)}"${it.key === chosen ? ' selected' : ''}>${esc(it.label)}</option>`).join('')}</optgroup>`).join('');
  }

  function renderSeriesList() {
    const box = $('rtmSeries');
    const picked = new Set(state.picked);
    const groups = pickerGroups();
    // The title is the name alone, for one too long for its cell. Which
    // species do not move is in the (i) of this tab, pane:time. With
    // quantities beside the species, each group has a heading across the grid,
    // and the long groups (the log activities, a network's reactions) are shut until opened.
    box.innerHTML = groups.map((g) => {
      const shut = groups.length > 1 && (state.sections[`series:${g.id}`] === undefined
        ? GROUP_SHUT.has(g.id) || (g.id === 'reactions' && g.items.length > REACTIONS_OPEN_MOST) : !state.sections[`series:${g.id}`]);
      const head = groups.length > 1
        ? `<button type="button" class="rtm-series-head" data-group="${g.id}" aria-expanded="${!shut}" `
          + `data-on-click="rtm:toggleGroup">${esc(GROUP_LABELS[g.id])} <span class="rtm-muted">${g.items.length}</span></button>`
        : '';
      return head + g.items.map((it) => {
        const on = picked.has(it.key);
        return `<label class="rtm-item${on ? ' on' : ''}" title="${esc(it.label)}"${shut && !on ? ' hidden' : ''} data-group="${g.id}">`
          + `<input type="checkbox" value="${esc(it.key)}"${on ? ' checked' : ''} data-on-change="rtm:pick">`
          + `<span>${esc(it.label)}</span></label>`;
      }).join('');
    }).join('');
  }

  /*
    The quantities of a run, worked out in the worker from the model and the
    stored concentrations it kept, and kept here: key|cell -> the value at
    every stored point, cell counted as the model counts its cells, rock
    layers included. The run on show has its own, and each run kept to draw
    beside the next (keptRuns) its own: the worker keeps only the run it
    made last, and works a kept run's out again from its numbers, sent with
    the question.
  */
  const current = { r: null, cache: new Map(), asked: new Set(), failed: new Set() };
  /** Where a run's quantities are kept: the run on show's, a kept run's, or null. */
  function holderOf(r) {
    if (r && r === state.result) {
      if (current.r !== r) { current.r = r; current.cache = new Map(); current.asked = new Set(); current.failed = new Set(); }
      return current;
    }
    return keptRuns.find((k) => k.r === r) || null;
  }
  function quantityCache() { return holderOf(state.result).cache; }
  /** Whether a quantity in a model cell of run r is still to come: neither kept nor given up on. */
  const quantityPending = (key, cell, r = state.result) => {
    const h = holderOf(r);
    return !!h && !h.cache.has(`${key}|${cell}`) && !h.failed.has(`${key}|${cell}`);
  };

  /** A quantity's values in model cell `cell` of run r, or null until worked out (fetchQuantities). */
  function quantitySeries(key, cell, r = state.result) {
    const h = holderOf(r);
    return (h && h.cache.get(`${key}|${cell}`)) || null;
  }

  /**
   * Has the worker work out the quantities `keys` in model cells `cells` at
   * every stored point of run r, unless they are kept or asked for already,
   * and draws the charts again once they come. A worker that has made a run
   * since -- or been started again -- has let it go, and the run is sent
   * with the question. One that fails is not asked again for this run: the
   * status says why.
   */
  async function fetchQuantities(keys, cells, r = state.result) {
    const h = r && holderOf(r);
    if (!h || !keys.length || !cells.length) return;
    const cache = h.cache;
    const want = [];
    for (const k of keys) for (const c of cells) if (!cache.has(`${k}|${c}`) && !h.asked.has(`${k}|${c}`)) want.push([k, c]);
    if (!want.length) return;
    want.forEach(([k, c]) => h.asked.add(`${k}|${c}`));
    const wk = [...new Set(want.map(([k]) => k))];
    const wc = [...new Set(want.map(([, c]) => c))];
    const text = h === current ? ((state.ran && state.ran.text) || state.text) : h.text;
    const ask = (withRun) => request({ type: 'quantities', runKey: r.runKey, keys: wk, cells: wc,
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      if (holderOf(r) !== h) return;
      const nc = reply.cells.length;
      reply.keys.forEach((k, q) => reply.cells.forEach((c, j) => {
        cache.set(`${k}|${c}`, reply.values.subarray((q * nc + j) * reply.n, (q * nc + j + 1) * reply.n));
      }));
      drawTime();
      drawProfile();
      drawGradient();
      drawComp();
      if (state.tab === 'fit') drawFit();
    } catch (e) {
      want.forEach(([k, c]) => h.failed.add(`${k}|${c}`));
      setStatus(`Could not work out ${wk.map(labelOf).join(', ')}${h === current ? '' : ` for the run ${h.label}`}: ${e.message}`, 'error');
    }
  }

  /*
    THE RUNS KEPT to draw beside the next (Keep this run), as Kompartment
    keeps its runs: up to four, each with the text it was made with, its
    numbers and its summary -- its own species, cells and time unit -- and
    its quantities as they are worked out for it. The one chosen is drawn
    beside the run on show, dashed in the same colours, on Against time,
    Against distance, Gradient and Composition, wherever it has the same
    species or quantity and the cell; the notes say where it has not. A run
    kept outlives the model it was made with: comparing two models is what
    it is for.
  */
  const KEPT_MOST = 4;
  const keptRuns = [];
  let besideId = null;
  let keptCount = 0;
  /** The kept run drawn beside the run on show, or null: none chosen, or the run on show itself. */
  function besideRun() {
    const k = keptRuns.find((x) => x.id === besideId) || null;
    return k && k.r !== state.result ? k : null;
  }
  /** Whether run r has species or quantity `name`. */
  const runHas = (r, name) => r.model.species.includes(name) || (r.model.quantities || []).some((q) => q.key === name);
  const runQuantity = (r, name) => !r.model.species.includes(name) && (r.model.quantities || []).some((q) => q.key === name);
  /** Run r's stored times in the unit of the run on show. */
  function besideTimes(k) {
    const own = (k.r.model.timeUnit && k.r.model.timeUnit.seconds) || 1;
    const here = timeUnit().seconds || 1;
    if (!k.times || k.timesIn !== here) { k.times = Float64Array.from(k.r.t, (t) => (t * own) / here); k.timesIn = here; }
    return k.times;
  }
  /** The kept run k's stored times on the time axis ax (timeAxis): in this run's unit, scaled, or in its own pore volumes; null where it has none. */
  function besideAxis(k, ax) {
    if (ax.pv) {
      const tw = poreTime(k.r);
      return tw > 0 ? axisTimes(k.r, { per: 1 / tw }) : null;
    }
    const t = besideTimes(k);
    if (ax.per === 1) return t;
    if (!k.shown || k.shown.per !== ax.per || k.shown.of !== t) k.shown = { per: ax.per, of: t, x: Float64Array.from(t, (v) => v * ax.per) };
    return k.shown.x;
  }
  // Why a kept run is not beside a chart in pore volumes.
  const BESIDE_NO_PV = 'its water does not flow: it has no pore volumes';
  // What a chart in pore volumes says of the kept run's own, where one of them is not as long as one of this run's.
  function besidePoreNote(k, ax) {
    if (!ax.pv) return '';
    const own = (k.r.model.timeUnit && k.r.model.timeUnit.seconds) || 1;
    const tw = (poreTime(k.r) * own) / (timeUnit().seconds || 1);
    return Math.abs(tw - ax.tw) > 1e-9 * ax.tw ? ` in its own pore volumes, ${fmtTime(tw)} each` : '';
  }

  function keepRun() {
    const r = state.result;
    if (!r) { setStatus('Run the model first: there is no run to keep.', 'error'); return; }
    const already = keptRuns.find((k) => k.r === r);
    if (already) { setStatus(`This run is kept already, ${already.label}.`, 'warn'); return; }
    const now = new Date();
    const two = (v) => String(v).padStart(2, '0');
    let label = `kept at ${two(now.getHours())}:${two(now.getMinutes())}`;
    if (keptRuns.some((k) => k.label === label)) label += `:${two(now.getSeconds())}`;
    const k = { id: ++keptCount, label, r, text: (state.ran && state.ran.text) || state.text, stem: fileStem(),
      cache: new Map(current.r === r ? current.cache : []), asked: new Set(), failed: new Set() };
    keptRuns.push(k);
    const gone = keptRuns.length > KEPT_MOST ? keptRuns.shift() : null;
    besideId = k.id;
    renderBeside();
    setStatus(`This run is kept, ${label}: change the model or its settings and run again, and it is drawn beside the next`
      + `${gone ? `; ${gone.label} is let go, ${KEPT_MOST} runs being kept at most` : ''}.`, 'ok');
  }

  function renderBeside() {
    $('rtmKeep').disabled = !state.result;
    $('rtmBesideWrap').hidden = !keptRuns.length;
    if (besideId !== null && !keptRuns.some((k) => k.id === besideId)) besideId = null;
    $('rtmBeside').innerHTML = `<option value="">nothing</option>${keptRuns.map((k) => `<option value="${k.id}"`
      + `${k.id === besideId ? ' selected' : ''}>${esc(k.label)}${k.stem !== 'rtm' ? `, ${esc(k.stem.replace(/^rtm_/, ''))}` : ''}</option>`).join('')}`;
  }

  /** Why the kept run k has nothing to draw of `name` at a chart's cell and layer, or '' where it has. */
  function besideWhy(k, name, cell, layer) {
    const m = k.r.model;
    if (!runHas(k.r, name)) return `it has no ${labelOf(name)}`;
    if (isFace(cell)) return m.faces && m.faces[cell] ? '' : `it has no ${cell} end`;
    const cells = m.fracture || 1;
    if (!(cell < cells)) return `it has ${cells} cell${cells === 1 ? '' : 's'}`;
    if (layer > 0 && !(layer < (m.stride || 1))) return 'it has no rock matrix';
    return '';
  }

  /** What a chart's note says of the run beside: what of it is drawn, or why not. */
  function besideNote(k, why) {
    return why ? `${k.label} not beside it: ${why}` : `dashed, the run ${k.label}`;
  }

  /** The model cell a chart's cell and layer are: the fracture cell, then its rock layers. */
  const modelCell = (cell, layer, r = state.result) => {
    const stride = (r && r.model.stride) || 1;
    return cell * stride + Math.min(layer, stride - 1);
  };

  /** What <DATA> measured of `key` in tables of `kind` ('time' or 'distance'). */
  function measured(kind, key) {
    const data = (state.compiled && state.compiled.data) || [];
    return data.filter((tab) => tab.kind === kind && tab.columns.includes(key)).map((tab) => {
      const j = tab.columns.indexOf(key) + 1;
      const rows = tab.rows.filter((row) => row[j] !== null);
      return { tab, x: rows.map((row) => row[0]), y: rows.map((row) => row[j]) };
    }).filter((d) => d.x.length);
  }

  /** Whether the time chart's place is an end of the column rather than a cell. */
  const isFace = (c) => c === 'left' || c === 'right';

  function renderCells() {
    const sel = $('rtmCell');
    const m = state.compiled;
    const cells = m ? m.fracture : 1;
    // A column's two ends come after its cells: what crosses them, which at
    // an outlet is the release.
    const ends = !!(m && m.transport && m.faces);
    if (isFace(state.cell) ? !ends : !(state.cell < cells)) state.cell = 0;
    const opts = Array.from({ length: cells }, (_, i) => {
      const x = m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : '';
      return `<option value="${i}"${i === state.cell ? ' selected' : ''}>${i}${x}</option>`;
    });
    if (ends) {
      for (const side of ['left', 'right']) {
        opts.push(`<option value="${side}"${state.cell === side ? ' selected' : ''}>flux through the ${side} end</option>`);
      }
    }
    sel.innerHTML = opts.join('');
    sel.parentElement.hidden = cells === 1;
    $('rtmCellsWrap').hidden = cells === 1;
    $('rtmCells').value = state.cells;
    // Breakthrough numbers are a column's: a batch has none.
    $('rtmBtcWrap').hidden = cells === 1;
    $('rtmBtc').checked = state.btc;
    $('rtmEvery').checked = state.every;
    renderLayerPickers();
  }

  /*
    AGAINST TIME AT SEVERAL CELLS: the list typed in Cells -- cell numbers,
    and end for the last -- each ticked series at each of them, in its own
    colour in steps of lightness down the column, faintest at the cell
    nearest the inlet (cellColour). Six at most: more steps of one colour
    than that cannot be told apart. Empty, the one cell Cell chooses, or an
    end of the column.
  */
  const CELLS_MOST = 6;
  function cellsAsked(r = state.result) {
    const m = r ? r.model : state.compiled;
    const n = m ? m.fracture || 1 : 1;
    const cells = [];
    const bad = [];
    for (const tok of String(state.cells).split(/[\s,;]+/).filter(Boolean)) {
      const c = /^end$/i.test(tok) ? n - 1 : /^\d+$/.test(tok) ? Number(tok) : NaN;
      if (!(c >= 0 && c < n)) bad.push(tok);
      else if (!cells.includes(c)) cells.push(c);
    }
    const more = cells.length > CELLS_MOST ? cells.splice(CELLS_MOST) : [];
    return { cells: n > 1 ? cells : [], bad, more, n };
  }
  /** Where the time chart is: the cells listed in Cells, or the one Cell chooses -- a cell or an end of the column. */
  function timeCells(r = state.result) {
    const asked = cellsAsked(r);
    return { ...asked, several: asked.cells.length > 0, at: asked.cells.length ? asked.cells : [state.cell] };
  }

  /** The layer selects, one per chart: the fracture, then each matrix layer by depth. */
  function layerOptions(chosen) {
    const m = state.compiled;
    const nm = m && m.matrix ? m.matrix.n : 0;
    const opts = [`<option value="0"${chosen === 0 ? ' selected' : ''}>fracture</option>`];
    for (let j = 1; j <= nm; j++) {
      opts.push(`<option value="${j}"${chosen === j ? ' selected' : ''}>rock ${j} (${m.matrix.depth[j - 1].toExponential(2)} m in)</option>`);
    }
    return opts.join('');
  }

  function renderLayerPickers() {
    const m = state.compiled;
    const nm = m && m.matrix ? m.matrix.n : 0;
    if (state.layer > nm) state.layer = 0;
    if (state.profileLayer > nm) state.profileLayer = 0;
    if (state.gradLayer > nm) state.gradLayer = 0;
    $('rtmLayer').innerHTML = layerOptions(state.layer);
    $('rtmProfileLayer').innerHTML = layerOptions(state.profileLayer);
    $('rtmGradLayer').innerHTML = layerOptions(state.gradLayer);
    // An end of the column has no rock behind it; the cells listed in Cells have.
    $('rtmLayerWrap').hidden = nm === 0 || (isFace(state.cell) && !cellsAsked().cells.length);
    $('rtmGradLayerWrap').hidden = nm === 0;
    $('rtmProfileAxisWrap').hidden = nm === 0;
    $('rtmProfileAxis').value = state.profileAxis;
    // Across the rock, the picker chooses the fracture cell instead of the layer.
    const across = nm > 0 && state.profileAxis === 'matrix';
    $('rtmProfileLayerWrap').hidden = nm === 0;
    $('rtmProfileLayerLabel').textContent = across ? 'At cell' : 'Layer';
    if (across) {
      $('rtmProfileLayer').innerHTML = Array.from({ length: m.fracture }, (_, i) =>
        `<option value="${i}"${i === state.profileLayer ? ' selected' : ''}>${i} (${m.centres[i].toExponential(2)} m)</option>`).join('');
    }
  }

  // The distance and gradient charts' pickers: every species, then every quantity, grouped; the distance
  // chart's first, those ticked against time, together at one time (drawProfileTicked).
  const PROFILE_TICKED = '*ticked';
  function renderProfileSpecies() {
    const names = speciesNames();
    if (state.profileSpecies !== PROFILE_TICKED && !names.includes(state.profileSpecies) && !quantityOf(state.profileSpecies)) {
      state.profileSpecies = names[0] || '';
    }
    $('rtmProfileSpecies').innerHTML = `<option value="${PROFILE_TICKED}"${state.profileSpecies === PROFILE_TICKED ? ' selected' : ''}>`
      + 'Those ticked against time, at one time</option>' + pickerOptions(state.profileSpecies);
  }

  function renderGradSpecies() {
    const names = speciesNames();
    const zones = zoneItems(state.compiled).length > 0;
    if (!(zones && state.gradSpecies === GRAD_ZONES) && !names.includes(state.gradSpecies) && !quantityOf(state.gradSpecies)) {
      state.gradSpecies = names[0] || '';
    }
    $('rtmGradSpecies').innerHTML = (zones ? `<option value="${GRAD_ZONES}"${state.gradSpecies === GRAD_ZONES ? ' selected' : ''}>`
      + 'The redox zones: the couple holding the pe</option>' : '') + pickerOptions(state.gradSpecies);
  }

  /* ---------------------------------------------------------------------
     Charts
     --------------------------------------------------------------------- */
  const PLOT_CONFIG = { displaylogo: false, responsive: true,
    modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'] };

  function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
      text: cs.getPropertyValue('--text-primary').trim() || '#333',
      grid: cs.getPropertyValue('--border-color').trim() || '#ddd',
      surface: cs.getPropertyValue('--bg-surface').trim() || '#fff',
    };
  }

  function baseLayout() {
    const c = themeColors();
    return {
      margin: { l: 70, r: 20, t: 14, b: 48 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: c.text, size: 11 },
      legend: { orientation: 'h', y: -0.18, font: { size: 10 } },
      xaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      // automargin: a tick label as long as 2.824×10⁻⁷ is wider than the 70 px
      // margin, and ran under the axis title; the margin now grows to take
      // the labels, and the title stands off beyond them -- 8 px, from the
      // template, which every y axis takes, whose title a chart sets anew.
      yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid, exponentformat: 'power', automargin: true },
      template: { layout: { yaxis: { title: { standoff: 8 } } } },
      hovermode: 'x unified',
      // Said explicitly: Plotly's default hover box is near-white whatever the
      // page is, which on the dark theme is light text on a light background.
      hoverlabel: { bgcolor: c.surface, bordercolor: c.grid, font: { color: c.text, size: 11 } },
    };
  }

  /**
   * The value of one species in one cell at every stored time -- or, at an
   * end of the column, what crosses it: the model's own sum over the states
   * beside that end, worked out at each stored point.
   */
  function series(name, cell, layer = state.layer, r = state.result) {
    // A quantity: as the worker worked it out, or null until it has (fetchQuantities). An end has none.
    if (runQuantity(r, name)) return isFace(cell) ? null : quantitySeries(name, modelCell(cell, layer, r), r);
    const ns = r.model.nspecies;
    const si = r.model.species.indexOf(name);
    if (si < 0) return null;
    if (isFace(cell)) {
      const f = r.model.faces && r.model.faces[cell] ? r.model.faces[cell][si] : null;
      if (!f) return null;
      const flux = new Float64Array(r.n);
      for (let i = 0; i < r.n; i++) {
        let v = f.constant;
        for (const [idx, w] of f.terms) v += w * r.states[i * r.width + idx];
        flux[i] = v;
      }
      return flux;
    }
    const stride = r.model.stride || 1;
    const col = (cell * stride + Math.min(layer, stride - 1)) * ns + si;
    const out = new Float64Array(r.n);
    for (let i = 0; i < r.n; i++) out[i] = r.states[i * r.width + col];
    return out;
  }

  /*
    THE UNIT A CONCENTRATION IS SHOWN IN, on Against time, Against distance
    and Gradient and in the water's listing: the model's own, or -- under
    ACTIVITY, whose concentrations are mol/kgw -- mmol, µmol or nmol per
    kgw, or mg or µg per kgw by the formula mass: a species by its own
    (formulaMassesOf in rtm-model.js), a mineral by what its relation makes
    it, an element's total or a valence state's by the element's atomic
    weight, the sulfate's as SO4. A model without ACTIVITY that names its
    unit, CONC_UNIT = mol/L (or mol/kgw), is shown the same way in that unit
    -- mmol/L, mg/L -- and says it on its axes in its own unit too. One that
    names none is in whatever unit the text means: shown times 10^3, 10^6 or
    10^9, and never weighed. pH, pe, an SI and the like are shown as they are. What has no
    such unit -- a pressure, an alkalinity in mg, a species with no formula
    in mg -- is left off a chart of several, which the note says, and a
    chart of one draws it as the model has it.
  */
  const CONC_UNITS = {
    mmol: { scale: 1e3, unit: 'mmol', bare: '× 10³' },
    umol: { scale: 1e6, unit: 'µmol', bare: '× 10⁶' },
    nmol: { scale: 1e9, unit: 'nmol', bare: '× 10⁹' },
    mg: { scale: 1e3, mass: true, unit: 'mg' },
    ug: { scale: 1e6, mass: true, unit: 'µg' },
  };
  /**
   * The unit a model's concentrations are in: mol/kgw under ACTIVITY, else its CONC_UNIT -- mol/L or mol/kgw -- else ''
   * as the model has them; and whether the model names it itself (CONC_UNIT), for the axes to say it in its own unit too.
   */
  const concBase = (m) => (m && m.activity ? 'mol/kgw' : (m && m.settings && m.settings.CONC_UNIT) || '');
  const concNamed = (m) => !!(m && m.settings && m.settings.CONC_UNIT);
  /** A unit of the table over a model's: mmol/L, mg/kgw. */
  const unitOver = (x, base) => `${x.unit}/${base.split('/')[1]}`;
  /**
   * The unit chosen, as run r can show it: { id, scale, mass, text, bare, named, why } -- id '' the model's own; text
   * what an axis says, '× 10³' where the model names no unit (bare); named, the model's own said too, as CONC_UNIT
   * names it; why the note's words where a mass is the model's own for want of a unit to weigh.
   */
  function shownUnit(r = state.result) {
    const m = r && r.model;
    const base = concBase(m);
    const u = CONC_UNITS[state.concUnit];
    const own = { id: '', scale: 1, mass: false, text: base, bare: !base, named: concNamed(m), why: '' };
    if (!u) return own;
    if (u.mass && !base) {
      return { ...own, why: `in the model's own unit: ${u.unit} needs the unit the concentrations are in, ACTIVITY's mol/kgw or a CONC_UNIT` };
    }
    return { id: state.concUnit, scale: u.scale, mass: !!u.mass, text: base ? unitOver(u, base) : u.bare, bare: !base, named: true, why: '' };
  }
  /** Whether a label says the unit: one chosen, or the model's own where it names it. */
  const unitSaid = (u) => !!(u && (u.id || u.named));
  /** A title in the unit shown: 'concentration (mg/kgw)', 'concentration × 10³' where the model names no unit. */
  const inUnit = (title, u) => (!unitSaid(u) ? title : u.bare ? `${title} ${u.text}` : `${title} (${u.text})`);
  /**
   * How run r shows `key` in the unit u (shownUnit): { f }, its values times f; { why }, why it cannot be -- a pressure,
   * a species with no formula in mg; or null, no concentration (pH, an SI and the like), shown as it is.
   */
  function shownAs(r, key, u) {
    const m = r.model;
    const k = m.species.indexOf(key);
    const q = k < 0 ? (m.quantities || []).find((x) => x.key === key) : null;
    if (k < 0 && (!q || q.axis === 'index')) return null;
    if (!u.id) return { f: 1 };
    const base = concBase(m);
    if (u.mass && !base) return { why: 'no unit named' };
    if (k >= 0) {
      // The electron's state is its activity, a potential's exp(-F psi/RT): neither an amount.
      if ((m.redox && m.redox.name === key) || (m.surface && (m.surface.potentials || []).some((p) => p.name === key))) {
        return { why: 'no amount' };
      }
      if (!u.mass) return { f: u.scale };
      const M = m.masses ? m.masses[k] : null;
      return M > 0 ? { f: u.scale * M } : { why: 'no formula mass' };
    }
    // The model's totals are in its unit, or in mol/kgw where it names none, as they always were.
    const qBase = base || 'mol/kgw';
    const qEq = qBase.replace(/^mol/, 'eq');
    if (q.unit === qEq && !u.mass) return { f: u.scale };
    if (q.unit !== qBase) return { why: q.unit === qEq ? 'in equivalents' : `in ${q.unit || 'a unit of its own'}` };
    if (!u.mass) return { f: u.scale };
    const M = q.group === 'totals' ? totalMass(key) : null;
    return M > 0 ? { f: u.scale * M } : { why: 'no formula mass' };
  }
  /** What one mole of a total weighs, g/mol: an element's, or a valence state's, its atomic weight; the sulfate's SO4's. */
  function totalMass(key) {
    if (key === 'tot(SO4)') return RtmModel.formulaMass('SO4');
    const el = /^tot\(([A-Z][a-z]?)(?:\(-?[\d.]+\))?\)$/.exec(key);
    return el ? RtmModel.ATOMIC_WEIGHTS[el[1]] || null : null;
  }
  /** What a chart's note says of the keys left off in the unit shown: [[label, why]]. */
  function unitNote(u, left) {
    if (!left.length) return '';
    const by = new Map();
    for (const [label, why] of left) {
      if (!by.has(why)) by.set(why, []);
      if (!by.get(why).includes(label)) by.get(why).push(label);
    }
    return `left off${u.bare ? '' : `, not in ${u.text}`}: ${[...by].map(([why, ls]) => `${ls.join(', ')} (${why})`).join(', ')}`;
  }
  /** What a chart of one key says where it draws it as the model has it, not in the unit chosen. */
  const ownUnitNote = (u, label, why) => `${label} as the model has it${u.bare ? '' : `, not in ${u.text}`}: ${why}`;
  /** Why the kept run's `label` is not drawn beside: it cannot be shown in the unit chosen. */
  const besideUnitWhy = (u, label, why) => `its ${label} cannot be ${u.bare ? 'scaled' : `shown in ${u.text}`} (${why})`;

  // The unit selects, one on each chart's bar and on the listing's, as one: what the model on show can be shown in.
  const UNIT_SELECTS = ['rtmUnitTime', 'rtmUnitProfile', 'rtmUnitGrad', 'rtmUnitComp'];
  function renderUnits() {
    const r = state.result || (state.compiled ? { model: state.compiled } : null);
    const base = concBase(r && r.model);
    const opts = [['', base || 'as the model has them', false],
      ...Object.entries(CONC_UNITS).map(([id, x]) => [id, base ? unitOver(x, base) : x.mass ? `${x.unit}, with ACTIVITY or a CONC_UNIT` : x.bare,
        !base && !!x.mass])];
    const html = opts.map(([id, label, off]) => `<option value="${id}"${off ? ' disabled' : ''}>${esc(label)}</option>`).join('');
    const now = shownUnit(r).id;
    for (const id of UNIT_SELECTS) {
      const sel = $(id);
      if (!sel) continue;
      sel.innerHTML = html;
      sel.value = now;
    }
  }

  /*
    THE FLOOR OF A LOG CONCENTRATION AXIS: the least concentration it shows,
    typed after its box; empty, the axis reaches the least drawn, as Plotly
    ranges it. A redox run's species span 150 decades -- methane at 1e-144
    where the water is oxic -- and that range squeezed every curve that
    matters into the top few millimetres. What lies below drops out of view;
    the data drawn, and so what is saved, are every value still.
  */
  function logFloor(text) {
    const t = String(text || '').trim();
    if (!t) return { lo: null, at: null, bad: '' };
    const v = Number(t);
    return Number.isFinite(v) && v > 0 ? { lo: Math.log10(v), at: v, bad: '' } : { lo: null, at: null, bad: t };
  }
  // The log axis from the floor to a little above the largest value drawn on it.
  function floorRange(lo, arrays) {
    let top = -Infinity;
    for (const ys of arrays) for (const v of ys) if (v > 0 && Number.isFinite(v)) top = Math.max(top, Math.log10(v));
    return top > lo ? [lo, top + Math.max(0.05, 0.04 * (top - lo))] : [lo, lo + 1];
  }
  // What a chart's note says of its floor: where the axis starts, in the unit shown, and which curves lie wholly below it, or what was not read.
  function floorNote(f, curves, u = null) {
    if (f.bad) return `could not read "${f.bad}" as where the log axis starts`;
    if (f.lo === null) return '';
    const under = curves.filter((cv) => !Array.from(cv.y || []).some((v) => v >= f.at)).map((cv) => cv.name);
    return `the log axis from ${f.at.toExponential()}${unitSaid(u) && !u.bare ? ` ${u.text}` : ''}`
      + `${under.length ? `, below it all through: ${under.join(', ')}` : ''}`;
  }

  function drawTime() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartTime');
    const empty = $('rtmTimeEmpty');
    const r = state.result;
    // Cell stands aside while Cells lists some.
    const tc = timeCells(r);
    const several = tc.several;
    $('rtmCell').disabled = several;
    if (!r || !state.picked.length) {
      drawBtc(null);
      // Every species in numbers is of the run, whatever is ticked.
      drawEvery(r);
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = r ? 'Tick a species to draw it.' : 'Run the model, then tick a species to draw it.';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    // Where: the cells listed in Cells, or the one Cell chooses -- a cell, or an end of the column.
    const face = !several && isFace(state.cell);
    // The quantities picked that the worker has still to work out: asked for, and drawn when they come.
    const mcs = face ? [] : tc.at.map((c) => modelCell(c, state.layer));
    const missing = face ? [] : state.picked.filter((k) => isQuantity(k) && mcs.some((mc) => quantityPending(k, mc)));
    if (missing.length) fetchQuantities(missing, mcs);
    const logT = $('rtmLogT').checked;
    const logY = $('rtmLogY').checked;
    // The time axis: the model's unit, or pore volumes where the water flows; the "from" is read on it.
    const ax = timeAxis(r);
    const xr = axisTimes(r, ax);
    const tmin = Number($('rtmTMin').value) || 0;
    const traces = [];
    const right = [];
    const skipped = [];
    // Each key its colour, its measured points the same: Plotly's own ten, in the order picked.
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    // At several cells, each in steps of lightness of it down the column from the inlet, and named by where it is.
    const leftward = !!(r.model.settings && r.model.settings.ADVECTION && r.model.settings.VELOCITY < 0);
    const fromInlet = tc.at.slice().sort((a, b) => (leftward ? b - a : a - b));
    const centre = (c) => `${Number(r.model.centres[c].toPrecision(3))} m`;
    // The unit the concentrations are shown in, and what has none in it: left off, and the note says so.
    const u = shownUnit(r);
    const unitLeft = [];
    // The kept run beside it: the same keys at the same cells, dashed in the same colours, at its times on this axis.
    const bk = besideRun();
    const kt = bk ? besideAxis(bk, ax) : null;
    const besideLeft = [];
    const besideComing = [];
    const besideTraces = [];
    for (const [pickIndex, nm] of state.picked.entries()) {
      const base = palette[pickIndex % palette.length];
      const shown = runHas(r, nm) ? shownAs(r, nm, u) : null;
      if (shown && shown.why) { unitLeft.push([labelOf(nm), shown.why]); continue; }
      const f = shown ? shown.f : 1;
      // An amount goes on the left with the species, log or not; pH, SI and the like on the right, linear.
      const onRight = axisOf(nm) === 'index';
      for (const cell of tc.at) {
        const color = several ? cellColour(base, fromInlet.indexOf(cell), tc.at.length) : base;
        const name = several ? `${labelOf(nm)} at ${centre(cell)}` : labelOf(nm);
        if (bk) {
          const why = !kt ? BESIDE_NO_PV : besideWhy(bk, nm, cell, state.layer);
          const mcK = face ? null : modelCell(cell, state.layer, bk.r);
          const kShown = why ? null : shownAs(bk.r, nm, u);
          // What the kept run has not is worth saying only of what this run draws: a tick left from another model is neither's.
          if (why) { if (runHas(r, nm)) besideLeft.push(why); }
          else if (kShown && kShown.why) besideLeft.push(besideUnitWhy(u, labelOf(nm), kShown.why));
          else if (runQuantity(bk.r, nm) && !face && quantityPending(nm, mcK, bk.r)) {
            fetchQuantities([nm], [mcK], bk.r);
            besideComing.push(labelOf(nm));
          } else {
            const ky = series(nm, cell, state.layer, bk.r);
            const kf = kShown ? kShown.f : 1;
            const kx = [];
            const kv = [];
            for (let i = 0; ky && i < bk.r.n; i++) {
              if (logT && !(kt[i] >= tmin && kt[i] > 0)) continue;
              const v = ky[i] * kf;
              if (!Number.isFinite(v) || (logY && !onRight && !(v > 0))) continue;
              kx.push(kt[i]);
              kv.push(v);
            }
            if (kx.length && onRight && !right.includes(axisLabelOf(nm))) right.push(axisLabelOf(nm));
            if (kx.length) {
              besideTraces.push({ name: `${name}, ${bk.label}`, x: kx, y: kv, mode: 'lines', type: 'scatter',
                line: { color, dash: 'dash', width: 1.6 }, ...(onRight ? { yaxis: 'y2' } : {}) });
            }
          }
        }
        const y = series(nm, cell);
        if (!y) { if (face && isQuantity(nm)) skipped.push(labelOf(nm)); continue; }
        const xs = [];
        const ys = [];
        for (let i = 0; i < r.n; i++) {
          const x = xr[i];
          if (logT && !(x >= tmin && x > 0)) continue;
          const v = y[i] * f;
          if (!Number.isFinite(v) || (logY && !onRight && !(v > 0))) continue;
          xs.push(x);
          ys.push(v);
        }
        if (onRight && !right.includes(axisLabelOf(nm))) right.push(axisLabelOf(nm));
        if (xs.length) {
          traces.push({ name, x: xs, y: ys, mode: 'lines', type: 'scatter', line: { color },
            ...(onRight ? { yaxis: 'y2' } : {}) });
        }
        // What <DATA> measured of it, at this cell and layer: points, in the unit shown, at their times on the axis.
        if (!face) {
          for (const d of measured('time', nm)) {
            if ((d.tab.cell || 0) !== cell || (d.tab.layer || 0) !== state.layer) continue;
            traces.push({ name: `${name}, measured`, x: ax.per === 1 ? d.x : d.x.map((t) => t * ax.per), y: f === 1 ? d.y : d.y.map((v) => v * f),
              mode: 'markers', type: 'scatter', marker: { size: 8, symbol: 'circle-open', color, line: { width: 1.6 } },
              ...(onRight ? { yaxis: 'y2' } : {}) });
          }
        }
      }
    }
    traces.push(...besideTraces);
    const besideDrawn = besideTraces.length;
    const layout = baseLayout();
    layout.xaxis.type = logT ? 'log' : 'linear';
    layout.xaxis.title = { text: ax.title, font: { size: 11 } };
    layout.yaxis.type = logY ? 'log' : 'linear';
    // Where the log axis starts: the curves on the left, and the kept run's and what was measured with them.
    $('rtmYFrom').disabled = !logY;
    const floor = logY ? logFloor(state.yFrom) : logFloor('');
    const onLeft = traces.filter((t) => !t.yaxis);
    if (floor.lo !== null) layout.yaxis.range = floorRange(floor.lo, onLeft.map((t) => t.y));
    // An end's flux is per m2 of the water's cross-section, positive to the right.
    const flux = unitSaid(u) && !u.bare ? `${u.text} · m/${timeUnit().symbol}` : `concentration · m/${timeUnit().symbol}`;
    layout.yaxis.title = { text: face
      ? `flux through the ${state.cell} end (${flux})${u.id && u.bare ? ` ${u.text}` : ''}` : inUnit('concentration', u), font: { size: 11 } };
    if (right.length) {
      const c = themeColors();
      layout.yaxis2 = { overlaying: 'y', side: 'right', gridcolor: c.grid, zeroline: false, linecolor: c.grid, showgrid: false,
        automargin: true, title: { text: right.join(', '), font: { size: 11 } } };
      layout.margin.r = 64;
    }
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    $('rtmTimeNote').textContent = [several ? `at cell${tc.at.length > 1 ? 's' : ''} ${tc.at.join(', ')}`
      + `${tc.at.length > 1 ? ', faintest nearest the inlet' : ''}` : '',
      tc.bad.length ? `could not read ${tc.bad.join(', ')} as a cell: ${tc.n} cells, 0 to ${tc.n - 1}` : '',
      tc.more.length ? `${CELLS_MOST} cells at most: ${tc.more.join(', ')} left off` : '',
      ax.pv ? `a pore volume ${fmtTime(ax.tw)}` : '', ax.why,
      missing.length ? `working out ${missing.map(labelOf).join(', ')}…` : '',
      skipped.length ? `${skipped.join(', ')}: a quantity of the water, which an end has none of` : '',
      u.why, unitNote(u, unitLeft),
      bk && besideDrawn ? besideNote(bk) + besidePoreNote(bk, ax) : '',
      bk && besideComing.length ? `working out ${besideComing.join(', ')} for ${bk.label}…` : '',
      bk && besideLeft.length ? besideNote(bk, [...new Set(besideLeft)].join('; ')) : '', floorNote(floor, onLeft, u)]
      .filter(Boolean).join('; ');
    drawBtc(r, tc, u, bk);
    drawEvery(r);
  }

  /*
    BREAKTHROUGH NUMBERS, under Against time: of each curve drawn, where it
    starts, the farthest it gets from there and when, and when it is
    half-way from the one to the other -- the first time, between stored
    points linearly -- read off every stored point, whatever the axes leave
    out; where the water flows, that time in pore volumes, and the
    retardation it implies: those pore volumes over the share of the column
    the water has crossed to get there, 1 for what moves with the water.
    The half-way is a front's median, not its mean: where a front spreads
    much, even what moves with the water reads a little off 1, so a species
    is best set against a tracer in the same run. And of each species and
    each element's total, what has come out of the column: its budget over
    the run, as the Composition tab keeps it -- what the column held at the
    start, what came in at the left, what went out at the right, what it
    holds at the end and what reactions made or took -- and the share gone
    out of what was there and came in.
  */
  /** Where a curve starts, the farthest it gets from there and when, and when it is first half-way; null where it has no number. */
  function halfWay(t, y) {
    const n = y.length;
    if (!n || Array.prototype.some.call(y, (v) => !Number.isFinite(v))) return null;
    const y0 = y[0];
    let far = 0;
    let iFar = 0;
    for (let i = 1; i < n; i++) {
      const d = Math.abs(y[i] - y0);
      if (d > far) { far = d; iFar = i; }
    }
    if (!(far > 1e-12 * Math.max(Math.abs(y0), Math.abs(y[iFar])))) return { moves: false, start: y0 };
    const half = y0 + (y[iFar] - y0) / 2;
    let tHalf = t[iFar];
    for (let i = 1; i <= iFar; i++) {
      const a = y[i - 1] - half;
      const b = y[i] - half;
      if (a === 0) { tHalf = t[i - 1]; break; }
      if (a * b < 0 || b === 0) { tHalf = t[i - 1] + ((t[i] - t[i - 1]) * (half - y[i - 1])) / (y[i] - y[i - 1]); break; }
    }
    // When it gets there: the first time within 1e-4 of the farthest -- a plateau's last wiggle is no time -- and at the
    // end of the run only where it is still going then.
    let iReach = iFar;
    for (let i = 0; i <= iFar; i++) if (Math.abs(y[i] - y0) >= far * (1 - 1e-4)) { iReach = i; break; }
    return { moves: true, start: y0, far: y[iFar], tFar: t[iReach], atEnd: iReach === n - 1, half, tHalf };
  }
  /** What a budget can be kept of for a key: a species, or an element's total in the water; null for anything else. */
  function budgetFor(key, r) {
    if (r.model.species.includes(key)) return key === 'e-' ? null : { kind: 'species', name: key };
    const el = /^tot\(([A-Z][a-z]?)\)$/.exec(key);
    const C = el ? compositionOf(r.model) : null;
    return C && C.elements.some((e) => e.el === el[1] && e.terms.length) ? { kind: 'element', name: el[1] } : null;
  }
  let btcNow = null;
  function drawBtc(r, tc, u, bk) {
    const box = $('rtmTimeNumbers');
    btcNow = null;
    if (!state.btc || !r || !r.model.transport || !(r.model.fracture > 1)) { box.hidden = true; box.innerHTML = ''; return; }
    const here = timeUnit().seconds || 1;
    // The runs: this one, and the one kept beside, its times in this run's unit and its own pore volume.
    const runs = [{ r, suffix: '', label: 'this run', t: r.t, tw: poreTime(r) }];
    if (bk) {
      const own = (bk.r.model.timeUnit && bk.r.model.timeUnit.seconds) || 1;
      runs.push({ r: bk.r, suffix: `, ${bk.label}`, label: bk.label, t: besideTimes(bk), tw: (poreTime(bk.r) * own) / here, kept: true });
    }
    const half = [];
    const out = [];
    const coming = new Set();
    for (const run of runs) {
      const m = run.r.model;
      const L = m.length;
      const leftward = !!(m.settings && m.settings.ADVECTION && m.settings.VELOCITY < 0);
      // How far the water has come from the inlet to a cell, or to an end.
      const crossed = (cell) => (cell === 'left' ? (leftward ? L : 0) : cell === 'right' ? (leftward ? 0 : L)
        : leftward ? L - m.centres[cell] : m.centres[cell]);
      for (const nm of state.picked) {
        if (!runHas(run.r, nm)) continue;
        const shown = shownAs(run.r, nm, u);
        if (shown && shown.why) continue;
        const f = shown ? shown.f : 1;
        for (const cell of tc.at) {
          if (run.kept && besideWhy(bk, nm, cell, state.layer)) continue;
          const y = series(nm, cell, state.layer, run.r);
          if (!y) continue;
          const h = halfWay(run.t, f === 1 ? y : Float64Array.from(y, (v) => v * f));
          if (!h) continue;
          const name = `${tc.several ? `${labelOf(nm)} at ${Number(m.centres[cell].toPrecision(3))} m` : labelOf(nm)}${run.suffix}`;
          const pv = h.moves && run.tw > 0 ? h.tHalf / run.tw : null;
          const d = crossed(cell);
          half.push({ name, h, pv, R: pv !== null && d > 0 ? pv / (d / L) : null });
        }
        // What has come out of the column: the budget of a species, or of an element's total.
        const of = budgetFor(nm, run.r);
        if (!of) continue;
        const key = `${run.r.runKey}|${of.kind}|${of.name}`;
        const got = budgetCache.get(key);
        if (got === undefined || got === null) { coming.add(labelOf(nm)); fetchBudget(run.r, of, key); continue; }
        if (got.error) continue;
        const n = got.total.length;
        const start = got.total[0];
        const cin = got.cumIn[n - 1];
        const gone = got.cumOut[n - 1];
        // What holding put in is given to the column as what came in is.
        const hold = holdingOf(got);
        const held = hold ? hold.put[n - 1] : null;
        const given = start + cin + Math.max(held || 0, 0);
        out.push({ name: `${of.kind === 'element' ? `${of.name}, all of it` : labelOf(nm)}`, run: run.label, start, cin, gone,
          end: got.total[n - 1], made: got.byReactions[n - 1], held, share: given > 0 ? gone / given : null });
      }
    }
    // Each number to four figures, the whole of it in data-v for whoever reads the page by machine.
    const num = (v) => (v === null || v === undefined ? '' : esc(v === 0 ? '0' : fit4(v)));
    const td = (v, text = num(v)) => `<td${v === null || v === undefined ? '' : ` data-v="${v}"`}>${text}</td>`;
    const halfHtml = half.map(({ name, h, pv, R }) => (h.moves
      ? `<tr><td>${esc(name)}</td>${td(h.start)}`
        + `${td(h.far, `${num(h.far)} ${h.atEnd ? 'at the end of the run' : `at ${esc(fmtTime(h.tFar))}`}`)}`
        + `${td(h.tHalf, `${num(h.half)} at ${esc(fmtTime(h.tHalf))}`)}${td(pv, pv === null ? '' : esc(pv.toPrecision(3)))}`
        + `${td(R, R === null ? '' : esc(R.toPrecision(3)))}</tr>`
      : `<tr><td>${esc(name)}</td>${td(h.start)}<td colspan="4">does not move</td></tr>`)).join('');
    const anyHeld = out.some((o) => o.held !== null);
    const outHtml = out.map((o) => `<tr><td>${esc(o.name)}</td><td>${esc(o.run)}</td>${td(o.start)}${td(o.cin)}${td(o.gone)}`
      + `${td(o.end)}${td(o.made)}${anyHeld ? td(o.held) : ''}${td(o.share, o.share === null ? '' : `${esc((100 * o.share).toPrecision(3))} %`)}</tr>`).join('');
    const unitText = unitSaid(u) && !u.bare ? ` (${u.text})` : '';
    box.innerHTML = (half.length ? `<table><thead><tr><th>Where each curve is half-way${esc(unitText)}</th><th>it starts at</th>`
      + '<th>the farthest it gets</th><th>half-way</th><th>in pore volumes</th><th>retardation</th></tr></thead>'
      + `<tbody>${halfHtml}</tbody></table>` : '')
      + (out.length ? '<table><thead><tr><th>What has come out of the column</th><th>run</th><th>there at the start</th>'
        + '<th>came in at the left</th><th>went out at the right</th><th>there at the end</th><th>made by reactions, net</th>'
        + `${anyHeld ? '<th>put in by holding</th><th>gone out of what was there, came in and was put in</th>'
          : '<th>gone out of what was there and came in</th>'}</tr></thead><tbody>${outHtml}</tbody></table>` : '')
      + `<p>${[half.length ? 'Half-way from where a curve starts to the farthest it gets, the first time, between stored points; the '
        + 'retardation the pore volumes then over the share of the column the water has crossed to get there, 1 for what moves '
        + 'with the water, a median that a front spreading much moves a little' : '',
      out.length ? 'Amounts as the budget on the Composition tab keeps them, concentration × m per m² of the water\'s '
        + 'cross-section' : '', coming.size ? `working out the budget of ${[...coming].join(', ')}…` : '']
      .filter(Boolean).join('. ')}.</p>`;
    box.hidden = !half.length && !out.length && !coming.size;
    btcNow = {
      half: { name: 'half-way', head: ['curve', 'starts at', 'farthest', 'farthest at', 'half-way', 'half-way at', 'in pore volumes', 'retardation'],
        rows: half.map(({ name, h, pv, R }) => (h.moves ? [name, h.start, h.far, h.tFar, h.half, h.tHalf, pv, R] : [name, h.start, null, null, null, null, null, null])) },
      out: { name: 'out of the column', head: ['of', 'run', 'there at the start', 'came in at the left', 'went out at the right', 'there at the end',
        'made by reactions, net', ...(anyHeld ? ['put in by holding', 'gone out of what was there, came in and was put in']
          : ['gone out of what was there and came in'])],
      rows: out.map((o) => [o.name, o.run, o.start, o.cin, o.gone, o.end, o.made, ...(anyHeld ? [o.held] : []), o.share]) },
    };
  }

  /*
    EVERY SPECIES IN NUMBERS, under Against time: of each species at the cell
    shown -- the first of Cells where it lists several -- where it starts and
    where it ends, its highest and when it first gets there (within 1e-4 of
    it, so that a plateau's last wiggle is no time), and when it settles: from
    when it stays within 1 % of where it ends -- or within a billionth of its
    highest, for one that ends at nought -- where that leaves a tenth of the
    run at least; else it is still changing at the end. Read off every stored
    point, whatever the axes leave out, in the unit chosen, the times as Time
    in shows them. A click on a species ticks it, or unticks it; Copy the
    table puts it on the clipboard, and Excel has it on a sheet of its own.
  */
  const EVERY_BAND = 0.01;
  let everyNow = null;
  /** What a species does over a run: { start, end, high, tHigh, atStart, atEnd, settled } or { start, end, flat } where it does nothing. */
  function speciesOver(t, y) {
    const n = y.length;
    if (!n) return null;
    let peak = 0;
    let hi = 0;
    for (let i = 0; i < n; i++) {
      if (!Number.isFinite(y[i])) return null;
      peak = Math.max(peak, Math.abs(y[i]));
      if (y[i] > y[hi]) hi = i;
    }
    const start = y[0];
    const end = y[n - 1];
    if (peak === 0) return { start, end, flat: 'nought throughout' };
    if (!Array.prototype.some.call(y, (v) => Math.abs(v - start) > 1e-12 * peak)) return { start, end, flat: 'does not change' };
    const top = y[hi];
    let iTop = hi;
    for (let i = 0; i <= hi; i++) if (y[i] >= top - 1e-4 * Math.abs(top)) { iTop = i; break; }
    const band = Math.max(EVERY_BAND * Math.abs(end), 1e-9 * peak);
    let k = n - 1;
    while (k > 0 && Math.abs(y[k - 1] - end) <= band) k -= 1;
    const settled = t[k] <= t[0] + 0.9 * (t[n - 1] - t[0]) ? t[k] : null;
    return { start, end, high: top, tHigh: t[iTop], atStart: iTop === 0, atEnd: iTop === n - 1, settled, fromStart: k === 0 };
  }

  function drawEvery(r) {
    const box = $('rtmTimeEvery');
    everyNow = null;
    if (!box) return;
    if (!state.every || !r) { box.hidden = true; box.innerHTML = ''; return; }
    const tc = timeCells(r);
    const cell = tc.at[0];
    if (isFace(cell)) {
      box.innerHTML = '<p>Every species in numbers is of a cell: <em>Cell</em> shows what crosses an end.</p>';
      box.hidden = false;
      return;
    }
    const u = shownUnit(r);
    const m = r.model;
    const column = (m.fracture || 1) > 1;
    const layered = (m.stride || 1) > 1;
    const where = [column ? `at cell ${cell} (${Number(m.centres[cell].toPrecision(3))} m)` : '',
      layered ? (state.layer ? `rock ${state.layer}` : 'the fracture') : '',
      tc.several && tc.at.length > 1 ? 'the first of those listed' : ''].filter(Boolean).join(', ');
    const left = [];
    const rows = [];
    // Once the run is checked: how far each species moved at this cell when it was solved more carefully.
    const ck = checkOf(r);
    const mc = modelCell(cell, state.layer, r);
    // Held here: fixed on its line, or in this cell by <INITIAL>.
    const heldHere = (nm) => !!((m.fixed && m.fixed[m.species.indexOf(nm)])
      || (m.held || []).some((h) => h.species === nm && h.cells.includes(mc)));
    for (const nm of m.species) {
      const shown = shownAs(r, nm, u);
      if (shown && shown.why) { left.push([labelOf(nm), shown.why]); continue; }
      const f = shown ? shown.f : 1;
      const y = series(nm, cell, state.layer, r);
      if (!y) continue;
      const s = speciesOver(r.t, f === 1 ? y : Float64Array.from(y, (v) => v * f));
      if (s) rows.push({ nm, s, f, held: heldHere(nm), moved: ck ? ck.moved[mc * m.nspecies + m.species.indexOf(nm)] : null });
    }
    const num = (v) => (v === 0 ? '0' : fit4(v));
    // What holding put in or took out of each species held here, once the worker has said (rtmHeld).
    const hr = rows.some((x) => x.held) ? heldAt(r, mc) : null;
    const heldOf = (nm) => (hr && hr.held ? hr.held.find((h) => h.name === nm) || null : null);
    const putOf = (x) => { const h = x.held ? heldOf(x.nm) : null; return h && h.whole && h.put ? h.put * x.f : null; };
    const heldText = (x) => { const v = putOf(x); return v === null ? 'held' : `held; ${num(Math.abs(v))} ${v > 0 ? 'put in' : 'taken out'} over the run`; };
    const highText = (s) => `${num(s.high)} ${s.atStart ? 'at the start' : s.atEnd ? 'at the end of the run' : `at ${fmtTime(s.tHigh)}`}`;
    const settleText = (x) => (x.held ? heldText(x) : x.s.flat ? x.s.flat : x.s.settled === null ? 'still changing at the end'
      : x.s.fromStart ? 'from the start' : `by ${fmtTime(x.s.settled)}`);
    const td = (v, text) => `<td${v === null || v === undefined ? '' : ` data-v="${v}"`}>${esc(text)}</td>`;
    const movedTd = (v) => `<td data-v="${v}"${v >= CHECK_HOLDS ? ' class="rtm-moved"' : ''}>${esc(movedText(v))}</td>`;
    const unitText = unitSaid(u) && !u.bare ? ` (${u.text})` : u.id ? ` ${u.text}` : '';
    const html = rows.map((x) => {
      const { nm, s, moved } = x;
      const on = state.picked.includes(nm);
      return `<tr${on ? ' class="on"' : ''}><td><button type="button" class="rtm-every-name" data-on-click="rtm:everyPick" `
        + `data-key="${esc(nm)}" aria-pressed="${on}">${esc(labelOf(nm))}</button></td>${td(s.start, num(s.start))}${td(s.end, num(s.end))}`
        + `${s.flat ? '<td></td>' : `<td data-v="${s.high}" data-t="${s.tHigh}">${esc(highText(s))}</td>`}`
        + `${td(x.held ? putOf(x) : s.flat ? null : s.settled, settleText(x))}${ck ? movedTd(moved) : ''}</tr>`;
    }).join('');
    // Check the run, while the run is one it can check and has not checked; Checking… while it does.
    const checking = checkBusy && checkBusy === r;
    const checkBtn = checking ? ' <button type="button" class="rtm-more" disabled>Checking…</button>'
      : !checkNow || checkNow.r !== r ? (canCheck(r) ? ' <button type="button" class="rtm-more" id="rtmCheckRun" '
        + 'data-on-click="rtm:checkRun">Check the run</button>' : '') : '';
    const verdict = checkNow && checkNow.r === r ? checkVerdict(checkNow, r, u) : null;
    const gas = gasLine(r, cell, mc);
    box.innerHTML = `<table><thead><tr><th>Every species${where ? ` ${esc(where)}` : ''}${esc(unitText)}</th><th>starts at</th>`
      + `<th>ends at</th><th>highest</th><th>settles</th>${ck ? '<th>moved when solved more carefully</th>' : ''}</tr></thead>`
      + `<tbody>${html}</tbody></table>`
      + (verdict ? `<p class="rtm-every-check ${verdict.holds ? 'ok' : 'warn'}" id="rtmCheckLine">${verdict.html}</p>` : '')
      + (gas ? `<p class="rtm-every-gas${gas.over ? ' warn' : ''}" id="rtmGasLine">${gas.html}</p>` : '')
      + `<p>${esc(['Read off every stored point of the run; a species settles from when it stays within 1 % of where it ends, '
        + 'where that leaves a tenth of the run at least. A click on a species draws it, or takes it off the chart',
      ck ? 'Moved: the largest difference through the run, as a share of the most the species reaches here' : '',
      rows.some((x) => putOf(x) !== null) ? 'Held: kept where it is; what the reactions took of it, less what they made, was put in '
        + 'to keep it there, or taken out where they made more' : '',
      unitNote(u, left), u.why].filter(Boolean).join('. '))}. <button type="button" class="rtm-more" data-on-click="rtm:everyCopy">`
      + `Copy the table</button>${checkBtn}</p>`;
    box.hidden = false;
    const sym = timeUnit().symbol;
    const movedHead = 'moved when solved more carefully';
    everyNow = {
      name: 'every species',
      head: ['species', 'starts at', 'ends at', 'highest', `highest at (${sym})`, `settles by (${sym})`, 'note',
        ...(ck ? [`${movedHead} (% of its highest)`] : [])],
      rows: rows.map((x) => [labelOf(x.nm), x.s.start, x.s.end, x.s.flat ? null : x.s.high, x.s.flat ? null : x.s.tHigh,
        x.s.flat ? null : x.s.settled, x.held ? heldText(x) : x.s.flat || (x.s.settled === null ? 'still changing at the end' : ''),
        ...(ck ? [Number.isFinite(x.moved) ? 100 * x.moved : null] : [])]),
      text: [['species', 'starts at', 'ends at', 'highest', 'settles', ...(ck ? [movedHead] : [])],
        ...rows.map((x) => [labelOf(x.nm), num(x.s.start), num(x.s.end), x.s.flat ? '' : highText(x.s), settleText(x),
          ...(ck ? [movedText(x.moved)] : [])])],
      title: `Every species${where ? ` ${where}` : ''}${unitText}`,
    };
  }

  /*
    What holding put in or took out, at one cell of a run, of each species
    held there (rtmHeld): asked for once a cell, kept with the run itself --
    not by its key, which a worker started again counts from 1 -- and the
    table drawn again when it comes. Null until then.
  */
  const heldAsked = new WeakMap();
  function heldAt(r, mc) {
    let byCell = heldAsked.get(r);
    if (!byCell) { byCell = new Map(); heldAsked.set(r, byCell); }
    if (byCell.has(mc)) return byCell.get(mc);
    byCell.set(mc, null);
    const text = (state.ran && state.ran.text) || state.text;
    const ask = (withRun) => request({ type: 'held', runKey: r.runKey, at: mc,
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    (async () => {
      let got;
      try {
        got = await ask(false);
        if (got.missing) got = await ask(true);
      } catch (e) { got = { error: e.message }; }
      byCell.set(mc, got);
      if (state.result === r) drawEvery(r);
    })();
    return null;
  }

  /*
    THE PRESSURE EACH DISSOLVED GAS WOULD NEED, under the table of every
    species: of each species the model has that phreeqc.dat dissolves from a
    gas -- a phase X(g) whose reaction gives that one species, CO2(g) = CO2,
    O2, H2, N2, CH4, NH3, water's vapour aside -- the pressure of the gas
    that would hold as much of it in the water as the run has at its highest
    at the cell shown: that concentration over the phase's K at the
    temperature there (the analytic expression, else log_k with delta_h),
    a litre taken as a kilogram of water and the activity coefficient as 1.
    Of a model that names no unit, only that it needs one. phreeqc.dat is
    the page's own copy, the PHREEQC tab's, loaded the first time it is
    wanted and the table drawn again.
  */
  const PHREEQC_DAT_SRC = 'vendors/phreeqc/phreeqc-dat.js?v=20261107';
  let gasPhases = null;
  /** Of a database's text, its gas phases that dissolve to one species: Map(species -> { phase, logK, dH, analytic }). */
  function readGasPhases(text) {
    const out = new Map();
    let inPhases = false;
    let cur = null;
    const done = () => {
      if (cur && cur.species && cur.phase.endsWith('(g)') && cur.species !== 'H2O' && Number.isFinite(cur.logK)) out.set(cur.species, cur);
      cur = null;
    };
    for (const raw of String(text).split(/\r?\n/)) {
      const line = raw.replace(/#.*$/, '');
      if (!line.trim()) continue;
      if (/^[A-Z][A-Z_]{2,}\s*$/.test(line)) { done(); inPhases = line.trim() === 'PHASES'; continue; }
      if (!inPhases) continue;
      if (!/^\s/.test(line)) { done(); cur = { phase: line.trim().split(/\s+/)[0], species: null, reacted: false, logK: NaN, dH: null, analytic: null }; continue; }
      if (!cur) continue;
      for (const part of line.split(';').map((x) => x.trim()).filter(Boolean)) {
        let m;
        if ((m = /^-?log_?k\s+(\S+)/i.exec(part))) cur.logK = Number(m[1]);
        else if ((m = /^-?delta_?h\s+(\S+)\s*(\S*)/i.exec(part))) cur.dH = Number(m[1]) * (/kcal/i.test(m[2]) ? 4.184 : 1);
        else if ((m = /^-?(?:analytic(?:al_expression)?|a_e|ae)\s+(.+)/i.exec(part))) cur.analytic = m[1].trim().split(/\s+/).map(Number);
        else if (!part.startsWith('-') && !cur.reacted && /=/.test(part)) {
          cur.reacted = true;
          const [lhs, rhs] = part.split('=').map((x) => x.trim());
          // The gas to one species of the same formula: CO2 = CO2; not H2S = H+ + HS-.
          if (rhs && !/\s\+\s/.test(rhs) && rhs === lhs) cur.species = rhs;
        }
      }
    }
    done();
    return out;
  }
  /** A gas phase's log K at t °C: its analytic expression, else log_k moved by delta_h (kJ/mol). */
  function gasLogK(g, t) {
    const T = t + 273.15;
    if (g.analytic && g.analytic.some((v) => v)) {
      const [a1 = 0, a2 = 0, a3 = 0, a4 = 0, a5 = 0, a6 = 0] = g.analytic;
      return a1 + a2 * T + a3 / T + a4 * Math.log10(T) + a5 / (T * T) + a6 * T * T;
    }
    if (g.dH) return g.logK - (g.dH * 1000 / (8.314462618 * Math.LN10)) * (1 / T - 1 / 298.15);
    return g.logK;
  }
  /** The gas phases, once read; null while phreeqc.dat is on its way, the table drawn again when it comes. */
  function gasPhasesNow() {
    if (gasPhases && gasPhases !== 'loading') return gasPhases;
    if (gasPhases === 'loading') return null;
    if (self.PHREEQC_DAT) { gasPhases = readGasPhases(self.PHREEQC_DAT); return gasPhases; }
    gasPhases = 'loading';
    loadScript(PHREEQC_DAT_SRC).then(() => { gasPhases = readGasPhases(self.PHREEQC_DAT || ''); })
      .catch((e) => { gasPhases = { error: e.message }; })
      .finally(() => { if (state.result) drawEvery(state.result); });
    return null;
  }
  /** The line under the table of each dissolved gas's pressure at its highest at model cell mc of run r: { over, html }, or null. */
  function gasLine(r, cell, mc) {
    const gases = gasPhasesNow();
    if (!gases || gases.error) return null;
    const m = r.model;
    const found = m.species.map((nm) => [nm, gases.get(nm.replace(/\(aq\)$/, ''))]).filter(([, g]) => g);
    if (!found.length) return null;
    const names = found.map(([nm]) => labelOf(nm));
    const list = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
    if (!concBase(m)) {
      return { over: false, html: esc(`Dissolved gases, ${list(names)}: the pressure each would need to stay in the water takes the unit the `
        + 'concentrations are in, an ACTIVITY\'s mol/kgw or a CONC_UNIT.') };
    }
    const fixedT = typeof m.settings.TEMPERATURE === 'number' ? m.settings.TEMPERATURE : 25;
    const temps = new Set();
    const parts = [];
    let over = false;
    for (const [nm, g] of found) {
      const y = series(nm, cell, state.layer, r);
      if (!y) continue;
      let hi = 0;
      for (let i = 1; i < y.length; i++) if (y[i] > y[hi]) hi = i;
      const t = r.temps ? r.temps[hi * m.cells + mc] : fixedT;
      temps.add(Math.round(t * 10) / 10);
      const atm = Math.max(0, y[hi]) / 10 ** gasLogK(g, t);
      const text = `${labelOf(nm)} ${atm >= 1e-3 && atm < 1e5 ? String(Number(atm.toPrecision(3))) : atm.toExponential(2)} atm`;
      if (atm > 1) over = true;
      parts.push(atm > 1 ? `<strong>${esc(text)}</strong>` : esc(text));
    }
    if (!parts.length) return null;
    const at = temps.size === 1 ? `at ${[...temps][0]} °C` : 'at the temperature where each is highest';
    return { over, html: `Dissolved gases, the pressure of each gas that would hold as much in the water as it has at its highest here: `
      + `${parts.join(', ')}; by phreeqc.dat ${esc(at)}, a litre taken as a kilogram of water. At the surface the most is 1 atm; `
      + 'underground the water\'s own pressure is higher, about 50 atm at 500 m.' };
  }

  /** The table as it stands, on the clipboard: tab-separated for a sheet, and as a table for a document. */
  async function copyEvery() {
    if (!everyNow) return;
    const rows = everyNow.text;
    const tsv = [[everyNow.title, ...rows[0].slice(1)], ...rows.slice(1)].map((row) => row.join('\t')).join('\n');
    const html = `<table><thead><tr>${[everyNow.title, ...rows[0].slice(1)].map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>`
      + `<tbody>${rows.slice(1).map((row) => `<tr>${row.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    let copied = false;
    try {
      if (typeof ClipboardItem === 'function' && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({
          'text/plain': new Blob([tsv], { type: 'text/plain' }), 'text/html': new Blob([html], { type: 'text/html' }) })]);
      } else await navigator.clipboard.writeText(tsv);
      copied = true;
    } catch (e) {
      try { await navigator.clipboard.writeText(tsv); copied = true; } catch (err) { copied = false; }
    }
    setStatus(copied ? `The table is on the clipboard: ${rows.length - 1} species.`
      : 'The table could not be put on the clipboard: the browser would not allow it.', copied ? 'ok' : 'warn');
  }

  /*
    HOW FAR THE RUN HOLDS: Check the run, under every species in numbers,
    solves the run on show again a hundred times more carefully -- its
    tolerances a hundred times tighter, its method and other settings as
    they were, the step budget ten times as large -- and the worker sets the
    two against each other at every stored point (rtmCheck): of each species
    in each cell, the largest difference through the run as a share of the
    most it reaches there. The table gains a column of it at the cell shown,
    and a line under the table says that the run holds -- no species moved
    by 0.1 % of its highest -- nearly holds, none by 1 %, or does not; and
    where it does not quite hold, names the one that moved most, when and
    where, what it is in each run, and offers to run with the careful
    setting. A species smaller than the absolute tolerance over the
    relative is judged against that size. A check belongs to the run it
    checked and goes with it.
  */
  const CHECK_TIGHTER = 100;
  const CHECK_RTOL_FLOOR = 1e-12;
  // Under 0.1 % of its highest every species holds; under 1 % the run nearly holds; past that it does not.
  const CHECK_HOLDS = 1e-3;
  const CHECK_NEARLY = 1e-2;
  let checkNow = null;     // the last check: { r, factor, floor, solver, ...the worker's reply }
  let checkBusy = null;    // the run being checked
  /** The check of run r where it compared anything, or null. */
  const checkOf = (r) => (checkNow && checkNow.r === r && checkNow.moved ? checkNow : null);
  /** Whether run r can be checked: the run on show, run to its end, whose text and settings are known. */
  const canCheck = (r) => !!(r && r === state.result && r.type === 'result' && state.ran && r.model && r.model.nspecies);
  /** A share moved, as the table says it: 0, under 0.0001 %, 0.0021 %, 4.1 %. */
  const movedText = (v) => (v === 0 ? '0' : !Number.isFinite(v) ? 'no number' : v * 100 < 1e-4 ? 'under 0.0001 %'
    : `${Number((v * 100).toPrecision(2))} %`);
  /** A tolerance as the solver panel takes it: 1e-8, 2.5e-9, 5e-3. */
  const fmtTol = (x) => (Number(x) === 0 ? '0' : Number(Number(x).toPrecision(6)).toExponential());
  /** How many times more carefully, in words. */
  const timesWord = (f) => (Math.abs(f - 100) < 1e-6 ? 'a hundred times' : Math.abs(f - 10) < 1e-6 ? 'ten times'
    : `${Number(f.toPrecision(2))} times`);

  /** The settings run r is checked under: its own, the tolerances tighter; null where none can be tighter. */
  function carefulSolver(ran) {
    const s = ran.solver;
    const rtol = Number(Math.max(s.rtol / CHECK_TIGHTER, CHECK_RTOL_FLOOR).toPrecision(6));
    const factor = Number((s.rtol / rtol).toPrecision(6));
    if (!(factor >= 2)) return null;
    const atol = Number((s.atol / factor).toPrecision(6));
    // Where the absolute tolerance takes over from the relative one: a species never as large is judged against it.
    return { factor, floor: s.atol / s.rtol, solver: { ...s, rtol, atol, maxSteps: s.maxSteps * 10, maxPoints: 1000 } };
  }

  /** Where model cell mc of run r is, in words: '' in a batch. */
  function cellWords(r, mc) {
    const m = r.model;
    const stride = m.stride || 1;
    if ((m.fracture || 1) <= 1 && stride <= 1) return '';
    const fc = Math.floor(mc / stride);
    const layer = mc % stride;
    const rock = stride > 1 ? (layer ? `, rock ${layer}` : ', the fracture') : '';
    if (fc < m.fracture) return `at cell ${fc} (${Number(m.centres[fc].toPrecision(3))} m)${rock}`;
    if (m.extra && fc < m.fracture + m.extra.n) return `past the right-hand end, at ${Number(m.extra.centres[fc - m.fracture].toPrecision(3))} m${rock}`;
    return 'in a reservoir at an end';
  }

  /** A value of `nm` in run r as the table shows it, in its unit where it says one; else as the model has it. */
  function valueWords(r, nm, v, u) {
    const shown = shownAs(r, nm, u);
    const num = (x) => (x === 0 ? '0' : fit4(x));
    if (!Number.isFinite(v)) return 'no number';
    if (shown && shown.f && !u.bare) return `${num(v * shown.f)}${unitSaid(u) ? ` ${u.text}` : ''}`;
    const base = concBase(r.model);
    return `${num(v)}${base ? ` ${base}` : ''}`;
  }

  /**
   * The line under the table once run r is checked: { holds, word, html } -- word what the run does, 'holds', 'nearly
   * holds' or 'does not hold', by the most any species moved: under 0.1 % of its highest, under 1 %, or more.
   */
  function checkVerdict(ck, r, u) {
    const how = `solved again ${timesWord(ck.factor)} more carefully, at a relative tolerance of ${fmtTol(ck.solver.rtol)} `
      + `and an absolute one of ${fmtTol(ck.solver.atol)}`;
    if (!ck.moved) {
      return { holds: false, word: '', html: esc(`The run could not be checked: ${how}, it failed at the start`
        + `${ck.failed ? `: ${ck.failed}` : ''}.`) };
    }
    const m = r.model;
    const ns = m.nspecies;
    // The most each species moved, in any cell; and the most of all, where.
    const most = new Float64Array(ns);
    let worst = 0;
    for (let j = 0; j < ck.moved.length; j++) {
      if (ck.moved[j] > ck.moved[worst]) worst = j;
      if (ck.moved[j] > most[j % ns]) most[j % ns] = ck.moved[j];
    }
    const share = ck.moved[worst];
    const k = worst % ns;
    const nm = m.species[k];
    const where = cellWords(r, Math.floor(worst / ns));
    const i = ck.at[worst];
    const holds = share < CHECK_HOLDS;
    const word = holds ? 'holds' : share < CHECK_NEARLY ? 'nearly holds' : 'does not hold';
    const upTo = ck.failed ? `The careful run stopped at ${fmtTime(ck.failedAt)} (${ck.failed}); up to there, ` : '';
    const list = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
    let say;
    if (holds) {
      say = `${upTo ? `${upTo}the run holds` : 'The run holds'}: ${how}, `
        + (share === 0 ? 'no species moved at all.'
          : share * 100 < 1e-4 ? 'no species moved by as much as 0.0001 % of its highest.'
            : `no species moved by more than ${movedText(share)} of its highest; the most was ${labelOf(nm)}`
            + `${where ? ` ${where}` : ''}${i >= 0 ? `, at ${fmtTime(r.t[i])}` : ''}.`);
    } else {
      const was = i >= 0 ? r.states[i * r.width + worst] : NaN;
      // The others that moved by 0.1 % or more, the most first: named, up to three.
      const others = Array.from(most, (v, s) => [s, v]).filter(([s, v]) => s !== k && v >= CHECK_HOLDS).sort((a, b) => b[1] - a[1]);
      const named = others.slice(0, 3);
      say = `${upTo ? `${upTo}the run ${word}` : `The run ${word}`}: ${how}, ${labelOf(nm)}${where ? ` ${where}` : ''} `
        + `moved by ${movedText(share)} of its highest`
        + (i >= 0 ? `: at ${fmtTime(r.t[i])} it is ${valueWords(r, nm, was, u)} in this run and `
          + `${valueWords(r, nm, ck.there[worst], u)} in the careful one.` : '.')
        + (!others.length ? '' : others.length <= 3
          ? ` ${list(named.map(([s]) => labelOf(m.species[s])))} moved too, by ${list(named.map(([, v]) => movedText(v)))}.`
          : ` ${others.length} more species moved by 0.1 % or more, the most of them ${labelOf(m.species[named[0][0]])}, `
            + `by ${movedText(named[0][1])}.`);
    }
    const use = holds ? '' : ` <button type="button" class="rtm-more" id="rtmCheckUse" data-on-click="rtm:checkUse">Run with the careful setting</button>`;
    return { holds, word, html: `${esc(say)}${use}` };
  }

  /** Check the run: the run on show solved again more carefully, and set against it (see above). */
  async function checkRun() {
    const r = state.result;
    if (!canCheck(r) || state.running || checkBusy) return;
    const careful = carefulSolver(state.ran);
    if (!careful) {
      setStatus(`The run's relative tolerance is ${fmtTol(state.ran.solver.rtol)} already: there is none tighter to check it against.`, 'warn');
      return;
    }
    const text = state.ran.text;
    checkBusy = r;
    state.running = true;
    $('rtmRun').disabled = true;
    $('rtmStop').disabled = false;
    drawEvery(r);
    setProgress(0);
    const doing = `Solving again ${timesWord(careful.factor)} more carefully`;
    setStatus(`${doing}…${inlineWarning()}`);
    if (workerKind === 'inline') await repaint();
    const ask = (withRun) => request({ type: 'check', runKey: r.runKey, solver: careful.solver, floor: careful.floor,
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) }, (p) => {
      setProgress(p.frac);
      setStatus(`${doing}: ${fmtTime(p.t)} of ${fmtTime(p.tend)}, ${p.nsteps.toLocaleString()} steps`);
    });
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      if (state.result !== r) return;
      checkNow = { ...reply, r, factor: careful.factor, floor: careful.floor, solver: careful.solver };
      setProgress(null);
      const v = checkVerdict(checkNow, r, shownUnit(r));
      const took = `${reply.seconds.toFixed(2)} s${reply.steps ? `, ${reply.steps.toLocaleString()} steps` : ''}`;
      setStatus(!reply.moved ? `The run could not be checked: ${reply.failed || 'the careful run failed at the start'}.`
        : `Checked, solved again ${timesWord(careful.factor)} more carefully in ${took}: `
        + `the run ${v.word}${reply.failed ? ` as far as the careful run got, ${fmtTime(reply.failedAt)}` : ''}. `
        + 'The line under the table says more.', !reply.moved ? 'error' : v.holds && !reply.failed ? 'ok' : 'warn');
    } catch (e) {
      setProgress(null);
      setStatus(`The run could not be checked: ${e.message}`, 'error');
    } finally {
      if (checkBusy === r) {
        checkBusy = null;
        state.running = false;
        $('rtmRun').disabled = false;
        $('rtmStop').disabled = true;
      }
      drawEvery(state.result);
    }
  }

  /** Run with the careful setting: the tolerances the check solved under, in the panel, and the model run again. */
  function checkUse() {
    const ck = checkNow;
    if (!ck || !ck.solver || state.running) return;
    $('rtmRtol').value = fmtTol(ck.solver.rtol);
    $('rtmAtol').value = fmtTol(ck.solver.atol);
    readSolverControls();
    updateSolverOptions();
    saveState();
    infoRefresh();
    run();
  }

  /*
    ONE TIME AT A TIME, ON AGAINST DISTANCE: a slider through the stored
    points, and play, which moves it on through the run -- evenly in time,
    the whole run in 5, 10 or 30 seconds, or a stored point a frame, which
    is slower where the solver stored more. On the slider the chart draws
    what it shows at that one time on axes that span the whole run, so that
    a front moves across a still frame; Back to Times draws the Times again.
  */
  const PROFILE_PACES = ['5', '10', '30', 'points'];
  let profilePlaying = null;
  function profileStop() {
    if (!profilePlaying) return;
    cancelAnimationFrame(profilePlaying.raf);
    profilePlaying = null;
    $('rtmProfilePlay').textContent = 'play';
  }
  function profilePlay() {
    if (profilePlaying) { profileStop(); saveState(); return; }
    const r = state.result;
    if (!r || !(r.n > 1)) return;
    // From where the slider is, or from the start where it is at the end or not yet used.
    let i0 = state.profileAt === null ? 0 : nearestIndex(r.t, state.profileAt);
    if (i0 >= r.n - 1) i0 = 0;
    const p = { i0, wall0: performance.now(), last: -1, raf: 0 };
    profilePlaying = p;
    $('rtmProfilePlay').textContent = 'pause';
    const frame = (now) => {
      if (profilePlaying !== p) return;
      if (state.result !== r) { profileStop(); return; }
      let i;
      if (state.profilePace === 'points') i = Math.min(r.n - 1, p.i0 + Math.floor(((now - p.wall0) * 30) / 1000));
      else {
        const t = r.t[p.i0] + ((now - p.wall0) / (Number(state.profilePace) * 1000)) * (r.t[r.n - 1] - r.t[0]);
        i = t >= r.t[r.n - 1] ? r.n - 1 : nearestIndex(r.t, t);
      }
      if (i !== p.last) {
        p.last = i;
        state.profileAt = r.t[i];
        drawProfile();
      }
      if (i >= r.n - 1) { profileStop(); saveState(); return; }
      p.raf = requestAnimationFrame(frame);
    };
    p.raf = requestAnimationFrame(frame);
  }
  // The slider's row: under a run along a column, its thumb at the time drawn, or at the end under the Times.
  function renderProfilePlay(r) {
    const ok = !!(r && r.model.transport && r.model.fracture > 1 && r.n > 1);
    $('rtmProfilePlayRow').hidden = !ok;
    if (!ok) { profileStop(); return; }
    const i = state.profileAt === null ? r.n - 1 : nearestIndex(r.t, state.profileAt);
    const at = $('rtmProfileAt');
    at.max = String(r.n - 1);
    at.value = String(i);
    $('rtmProfileAtLabel').textContent = state.profileAt === null ? 'drag or play' : fmtOnAxis(timeAxis(r), r.t[i]);
    $('rtmProfilePace').value = state.profilePace;
    $('rtmProfileAll').disabled = state.profileAt === null;
    $('rtmProfilePlay').textContent = profilePlaying ? 'pause' : 'play';
  }
  /*
    What a profile's values come to over every stored point of a run -- the
    least, the greatest and the least above zero -- for an axis that holds
    still on the slider; kept for the run, which does not change.
  */
  const spanCache = new Map();
  function spanOver(key, n, npts, at) {
    if (key !== null && spanCache.has(key)) return spanCache.get(key);
    const s = { lo: Infinity, hi: -Infinity, pos: Infinity };
    for (let i = 0; i < n; i++) {
      for (let k = 0; k < npts; k++) {
        const v = at(i, k);
        if (!Number.isFinite(v)) continue;
        if (v < s.lo) s.lo = v;
        if (v > s.hi) s.hi = v;
        if (v > 0 && v < s.pos) s.pos = v;
      }
    }
    if (key === null) return s;
    if (spanCache.size > 400) spanCache.clear();
    spanCache.set(key, s);
    return s;
  }
  // The same of a few values, kept nowhere: what was measured.
  const spanOf = (ys) => spanOver(null, 1, ys.length, (i, k) => ys[k]);
  // An axis's range over those spans: log from the floor, or from the least above zero, to the greatest; linear a little wider.
  function stillRange(spans, log, floor) {
    const lo = Math.min(...spans.map((s) => s.lo));
    const hi = Math.max(...spans.map((s) => s.hi));
    const pos = Math.min(...spans.map((s) => s.pos));
    if (log) {
      const top = hi > 0 ? Math.log10(hi) : NaN;
      const bottom = floor.lo !== null ? floor.lo : Math.log10(pos);
      if (!Number.isFinite(top) || !Number.isFinite(bottom)) return null;
      const pad = Math.max(0.05, 0.04 * (top - bottom));
      return top > bottom ? [floor.lo !== null ? bottom : bottom - pad, top + pad] : [bottom - 1, bottom + 1];
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
    const pad = 0.05 * (hi - lo) || 0.05 * Math.abs(hi) || 1;
    return [lo - pad, hi + pad];
  }

  function drawProfile() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartProfile');
    const empty = $('rtmProfileEmpty');
    const r = state.result;
    renderProfilePlay(r);
    if (!r || !r.model.transport || r.model.fracture < 2) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = r ? 'This run was a batch: there is no distance to plot against.'
        : 'A profile needs a run in transport mode.';
      $('rtmProfileNote').textContent = '';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const name = state.profileSpecies || r.model.species[0];
    const ns = r.model.nspecies;
    const si = r.model.species.indexOf(name);
    const stride = r.model.stride || 1;
    const nm = r.model.matrix ? r.model.matrix.n : 0;
    const across = nm > 0 && state.profileAxis === 'matrix';
    // Along the fracture the points are the fracture cells at one layer; into
    // the rock they are the layers behind one cell, the fracture first at
    // depth zero.
    const layer = across ? 0 : Math.min(state.profileLayer, nm);
    const atCell = across ? Math.min(state.profileLayer, r.model.fracture - 1) : 0;
    const x = across ? [0, ...r.model.matrix.depth] : r.model.centres;
    const npts = across ? nm + 1 : r.model.fracture;
    const cellAt = (k) => (across ? (atCell * stride + k) : (k * stride + layer));
    if (name === PROFILE_TICKED) {
      drawProfileTicked({ r, plot, empty, across, layer, atCell, x, npts, cellAt, where: across
        ? `${nm} layers to ${r.model.matrix.total} m, the fracture at depth 0`
        : `${r.model.fracture} cells over ${r.model.length} m${nm && layer ? `, rock layer ${layer}` : ''}` });
      return;
    }
    const stateIndex = (k) => cellAt(k) * ns + si;
    // A quantity: every point's, from the worker; asked for, and drawn when it comes.
    const quantity = isQuantity(name);
    const cellsHere = Array.from({ length: npts }, (_, k) => cellAt(k));
    if (quantity && cellsHere.some((c) => quantityPending(name, c))) {
      fetchQuantities([name], cellsHere);
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = `Working out ${labelOf(name)} in every cell…`;
      $('rtmProfileNote').textContent = '';
      return;
    }
    /*
      In the unit shown, the kept run's and what was measured by the same;
      a key that has none in it -- no formula to weigh -- as the model has
      it, and the note says so.
    */
    const u = shownUnit(r);
    const shown = shownAs(r, name, u);
    const own = !!(shown && shown.why);
    const f = shown && shown.f ? shown.f : 1;
    const suffix = unitSaid(u) && shown && !own ? (u.bare ? ` ${u.text}` : ` (${u.text})`) : '';
    const meta = suffix ? { meta: { unitSuffix: suffix } } : {};
    const valueAt = (i, k) => {
      const v = quantity ? (quantitySeries(name, cellAt(k)) || [])[i] : r.states[i * r.width + stateIndex(k)];
      return v === undefined ? v : v * f;
    };
    // The slider's one time; or the times the reader asked for, or eight
    // spread over the run: a profile is only readable with a handful of
    // curves on it. Each named on the time axis, in pore volumes where they
    // are chosen, and the Times' bare numbers read in them.
    const ax = timeAxis(r);
    const slider = state.profileAt !== null;
    const asked = slider ? { times: [], bad: [] } : parseTimes(state.profileTimes, ax);
    const picks = [];
    const past = [];
    if (slider) picks.push(nearestIndex(r.t, state.profileAt));
    else if (asked.times.length) {
      for (const want of asked.times) {
        if (want > r.t[r.n - 1] * 1.000001) { past.push(want); continue; }
        const idx = nearestIndex(r.t, want);
        if (!picks.includes(idx)) picks.push(idx);
      }
    } else {
      const want = 8;
      for (let k = 0; k < want; k++) {
        const frac = (k + 1) / want;
        const idx = Math.round(frac * (r.n - 1));
        if (picks.includes(idx)) continue;
        picks.push(idx);
      }
    }
    // Each time its colour, Plotly's own order, so that the kept run's profile at it is drawn in the same.
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const traces = picks.map((i, q) => {
      const y = [];
      for (let k = 0; k < npts; k++) y.push(valueAt(i, k));
      return { name: fmtOnAxis(ax, r.t[i]), x, y, mode: across ? 'lines+markers' : 'lines', type: 'scatter', line: { color: palette[q % palette.length] },
        ...meta };
    });
    /*
      The kept run beside it: at each time drawn, its stored time nearest --
      in pore volumes, its own nearest the same pore volume -- along its own
      cells, or into the rock behind its cell, dashed in the same colour; a
      time past its end is not drawn.
    */
    const bk = besideRun();
    let besideSaid = '';
    // On the slider, what the kept run's values come to over its run: the axis holds them too.
    const spans = [];
    if (bk) {
      const kr = bk.r;
      const km = kr.model;
      const kStride = km.stride || 1;
      const kShown = runHas(kr, name) && !own ? shownAs(kr, name, u) : null;
      const why = !km.transport || !(km.fracture > 1) ? 'it was a batch' : !runHas(kr, name) ? `it has no ${labelOf(name)}`
        : across && !(km.matrix && km.matrix.n) ? 'it has no rock matrix'
          : !across && layer > 0 && !(layer < kStride) ? `it has no rock layer ${layer}`
            : ax.pv && !poreTime(kr) ? BESIDE_NO_PV
              : kShown && kShown.why ? besideUnitWhy(u, labelOf(name), kShown.why) : '';
      const kf = kShown && kShown.f ? kShown.f : 1;
      if (why) besideSaid = besideNote(bk, why);
      else {
        const kAtCell = across ? Math.min(state.profileLayer, km.fracture - 1) : 0;
        const kx = across ? [0, ...km.matrix.depth] : km.centres;
        const kn = across ? km.matrix.n + 1 : km.fracture;
        const kCellAt = (k) => (across ? kAtCell * kStride + k : k * kStride + layer);
        const kQuantity = runQuantity(kr, name);
        const kCells = Array.from({ length: kn }, (_, k) => kCellAt(k));
        const ksi = km.species.indexOf(name);
        if (kQuantity && kCells.some((c) => quantityPending(name, c, kr))) {
          fetchQuantities([name], kCells, kr);
          besideSaid = `working out ${labelOf(name)} for ${bk.label}…`;
        } else {
          const kt = besideAxis(bk, ax);
          const xr = axisTimes(r, ax);
          const pastIt = [];
          const kValue = (j, k) => {
            const v = kQuantity ? (quantitySeries(name, kCellAt(k), kr) || [])[j] : kr.states[j * kr.width + kCellAt(k) * km.nspecies + ksi];
            return v === undefined ? v : v * kf;
          };
          if (slider) spans.push(spanOver(`${kr.runKey}|${name}|${across}|${layer}|${kAtCell}|${kf}`, kr.n, kn, kValue));
          picks.forEach((i, q) => {
            if (xr[i] > kt[kr.n - 1] * 1.000001) { pastIt.push(fmtOnAxis(ax, r.t[i])); return; }
            const j = nearestIndex(kt, xr[i]);
            const y = [];
            for (let k = 0; k < kn; k++) y.push(kValue(j, k));
            traces.push({ name: `${fmtOnAxis(ax, r.t[i])}, ${bk.label}`, x: kx, y, mode: across ? 'lines+markers' : 'lines', type: 'scatter',
              line: { color: palette[q % palette.length], dash: 'dash', width: 1.6 }, ...meta });
          });
          besideSaid = [besideNote(bk) + besidePoreNote(bk, ax), pastIt.length ? `${pastIt.join(', ')} past its end` : ''].filter(Boolean).join(', ');
        }
      }
    }
    // What <DATA> measured of it along the column: points, at the time each table says, the end of the run unless it says;
    // on the slider faint but at the stored time nearest its own.
    if (!across) {
      for (const d of measured('distance', name)) {
        const at = d.tab.at !== null ? d.tab.at : r.t[r.n - 1];
        const ys = f === 1 ? d.y : d.y.map((v) => v * f);
        if (slider) spans.push(spanOf(ys));
        traces.push({ name: `measured, ${fmtOnAxis(ax, at)}`, x: d.x, y: ys, mode: 'markers', type: 'scatter',
          marker: { size: 8, symbol: 'circle-open', color: themeColors().text, line: { width: 1.6 },
            opacity: slider && nearestIndex(r.t, at) !== picks[0] ? 0.3 : 1 }, ...meta });
      }
    }
    const layout = baseLayout();
    layout.xaxis.title = { text: across ? `depth into the rock behind cell ${atCell} (m)`
      : 'distance from the left-hand face (m)', font: { size: 11 } };
    // pH, SI and the like are drawn as they are; an amount log or not, as the box says.
    const index = quantity && axisOf(name) === 'index';
    const logAxis = $('rtmProfileLog').checked && !index;
    layout.yaxis.type = logAxis ? 'log' : 'linear';
    $('rtmProfileYFrom').disabled = !$('rtmProfileLog').checked;
    const floor = logAxis ? logFloor(state.profileYFrom) : logFloor('');
    if (floor.lo !== null) layout.yaxis.range = floorRange(floor.lo, traces.map((t) => t.y));
    // On the slider the axis spans the whole run, the kept one's and what was measured too: a front moves across a still frame.
    if (slider) {
      spans.push(spanOver(`${r.runKey}|${name}|${across}|${layer}|${atCell}|${f}`, r.n, npts, valueAt));
      const still = stillRange(spans, logAxis, floor);
      if (still) layout.yaxis.range = still;
    }
    const q = quantity ? quantityOf(name) : null;
    layout.yaxis.title = { text: suffix ? `${q ? q.label : u.bare ? `${name} concentration` : name}${suffix}`
      : q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : `${name} concentration`, font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    /*
      The run is stored thinned, so a wanted time lands on the nearest point
      that was kept. The legend shows the time drawn rather than the time
      asked for, and this says so when the two are not the same.
    */
    const bits = [across ? `${nm} layers to ${r.model.matrix.total} m, the fracture at depth 0`
      : `${r.model.fracture} cells over ${r.model.length} m${nm && layer ? `, rock layer ${layer}` : ''}`];
    if (slider) bits.push(`at ${fmtOnAxis(ax, r.t[picks[0]])} on the slider, the axis over the whole run`);
    if (ax.pv) bits.push(`a pore volume ${fmtTime(ax.tw)}`);
    if (ax.why) bits.push(ax.why);
    if (asked.bad.length) bits.push(`could not read ${asked.bad.join(', ')}`);
    if (past.length) bits.push(`${past.map((t) => fmtOnAxis(ax, t)).join(', ')} past the end of the run`);
    if (asked.times.length && picks.length) {
      const off = asked.times.filter((w) => {
        const got = r.t[nearestIndex(r.t, w)];
        return Math.abs(got - w) > 0.01 * Math.max(w, 1e-300);
      });
      if (off.length) bits.push(`nearest stored time used for ${off.map((t) => fmtOnAxis(ax, t)).join(', ')}`);
    }
    if (u.why) bits.push(u.why);
    if (own) bits.push(ownUnitNote(u, labelOf(name), shown.why));
    if (besideSaid) bits.push(besideSaid);
    if (floorNote(floor, traces, own ? null : u)) bits.push(floorNote(floor, traces, own ? null : u));
    $('rtmProfileNote').textContent = bits.join('; ');
  }

  /*
    THOSE TICKED AGAINST TIME, AT ONE TIME: each along the column -- or into
    the rock -- at the first of Times, or at the end of the run, a curve each
    in its colour on the time chart: a plume's zones side by side, as
    PHREEQC's transport graphs draw them. pH, pe, a saturation index and the
    like go on the right as they are, the rest on the left, log or not as the
    box says. The kept run beside it at its stored time nearest, dashed in
    the same colours; what <DATA> measured along the column as points.
  */
  function drawProfileTicked(g) {
    const { r, plot, empty, across, layer, x, npts, cellAt } = g;
    const keys = state.picked.filter((k) => runHas(r, k));
    const cells = Array.from({ length: npts }, (_, k) => cellAt(k));
    const pending = keys.filter((k) => runQuantity(r, k) && cells.some((c) => quantityPending(k, c)));
    if (!keys.length || pending.length) {
      if (pending.length) fetchQuantities(pending, cells);
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = pending.length ? `Working out ${pending.map(labelOf).join(', ')} in every cell…`
        : 'Tick species or quantities against time to draw them here.';
      $('rtmProfileNote').textContent = '';
      return;
    }
    // The slider's time; or the first of Times, or the end of the run; on the time axis, in pore volumes where they are chosen.
    const ax = timeAxis(r);
    const slider = state.profileAt !== null;
    const asked = slider ? { times: [], bad: [] } : parseTimes(state.profileTimes, ax);
    const end = r.t[r.n - 1];
    const want = slider ? state.profileAt : asked.times.length ? asked.times[0] : end;
    const past = !slider && want > end * 1.000001;
    const i = past ? r.n - 1 : nearestIndex(r.t, want);
    const log = $('rtmProfileLog').checked;
    // On the slider, what each curve comes to over the run, on the left and on the right: axes that hold still.
    const spansL = [];
    const spansR = [];
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const traces = [];
    const right = [];
    const bk = besideRun();
    const kt = bk ? besideAxis(bk, ax) : null;
    const xi = axisTimes(r, ax)[i];
    const kI = kt && !(xi > kt[bk.r.n - 1] * 1.000001) ? nearestIndex(kt, xi) : -1;
    const besideTraces = [];
    const besideLeft = [];
    const besideComing = [];
    // The unit the concentrations are shown in, and what has none in it: left off, and the note says so.
    const u = shownUnit(r);
    const unitLeft = [];
    for (const key of keys) {
      const color = palette[state.picked.indexOf(key) % palette.length];
      const onRight = axisOf(key) === 'index';
      const shown = shownAs(r, key, u);
      if (shown && shown.why) { unitLeft.push([labelOf(key), shown.why]); continue; }
      const f = shown ? shown.f : 1;
      const meta = unitSaid(u) && shown ? { meta: { unitSuffix: u.bare ? ` ${u.text}` : ` (${u.text})` } } : {};
      // Every value as it is, none at all on a log axis too: Plotly leaves it out there, and what is saved keeps it.
      const keep = (v) => (Number.isFinite(v) ? v * f : null);
      const quantity = runQuantity(r, key);
      const si = r.model.species.indexOf(key);
      const valueAt = (j, k) => keep(quantity ? (quantitySeries(key, cellAt(k)) || [])[j] : r.states[j * r.width + cellAt(k) * r.model.nspecies + si]);
      const y = Array.from({ length: npts }, (_, k) => valueAt(i, k));
      if (slider) (onRight ? spansR : spansL).push(spanOver(`${r.runKey}|${key}|${g.across}|${layer}|${g.atCell}|${f}`, r.n, npts, valueAt));
      if (onRight && !right.includes(axisLabelOf(key))) right.push(axisLabelOf(key));
      traces.push({ name: labelOf(key), x, y, mode: across ? 'lines+markers' : 'lines', type: 'scatter', line: { color },
        ...(onRight ? { yaxis: 'y2' } : {}), ...meta });
      if (bk) {
        const kr = bk.r;
        const km = kr.model;
        const kStride = km.stride || 1;
        const kShown = runHas(kr, key) ? shownAs(kr, key, u) : null;
        const why = !km.transport || !(km.fracture > 1) ? 'it was a batch' : !runHas(kr, key) ? `it has no ${labelOf(key)}`
          : across && !(km.matrix && km.matrix.n) ? 'it has no rock matrix'
            : !across && layer > 0 && !(layer < kStride) ? `it has no rock layer ${layer}`
              : !kt ? BESIDE_NO_PV : kI < 0 ? `${fmtOnAxis(ax, r.t[i])} is past its end`
                : kShown && kShown.why ? besideUnitWhy(u, labelOf(key), kShown.why) : '';
        const kf = kShown && kShown.f ? kShown.f : 1;
        if (why) besideLeft.push(why);
        else {
          const kAtCell = across ? Math.min(state.profileLayer, km.fracture - 1) : 0;
          const kx = across ? [0, ...km.matrix.depth] : km.centres;
          const kn = across ? km.matrix.n + 1 : km.fracture;
          const kCellAt = (k) => (across ? kAtCell * kStride + k : k * kStride + layer);
          const kCells = Array.from({ length: kn }, (_, k) => kCellAt(k));
          const kQuantity = runQuantity(kr, key);
          if (kQuantity && kCells.some((c) => quantityPending(key, c, kr))) {
            fetchQuantities([key], kCells, kr);
            besideComing.push(labelOf(key));
          } else {
            const ksi = km.species.indexOf(key);
            const kKeep = (v) => (Number.isFinite(v) ? v * kf : null);
            const kValue = (j, k) => kKeep(kQuantity ? (quantitySeries(key, kCellAt(k), kr) || [])[j]
              : kr.states[j * kr.width + kCellAt(k) * km.nspecies + ksi]);
            const ky = Array.from({ length: kn }, (_, k) => kValue(kI, k));
            if (slider) (onRight ? spansR : spansL).push(spanOver(`${kr.runKey}|${key}|${across}|${layer}|${kAtCell}|${kf}`, kr.n, kn, kValue));
            besideTraces.push({ name: `${labelOf(key)}, ${bk.label}`, x: kx, y: ky, mode: across ? 'lines+markers' : 'lines',
              type: 'scatter', line: { color, dash: 'dash', width: 1.6 }, ...(onRight ? { yaxis: 'y2' } : {}), ...meta });
          }
        }
      }
      // What <DATA> measured of it along the column: points, at the time each table says, the end of the run unless it says.
      if (!across) {
        for (const d of measured('distance', key)) {
          const at = d.tab.at !== null ? d.tab.at : end;
          const ys = f === 1 ? d.y : d.y.map((v) => v * f);
          if (slider) (onRight ? spansR : spansL).push(spanOf(ys));
          traces.push({ name: `${labelOf(key)}, measured, ${fmtOnAxis(ax, at)}`, x: d.x, y: ys, mode: 'markers',
            type: 'scatter', marker: { size: 8, symbol: 'circle-open', color, line: { width: 1.6 },
              opacity: slider && nearestIndex(r.t, at) !== i ? 0.3 : 1 }, ...(onRight ? { yaxis: 'y2' } : {}), ...meta });
        }
      }
    }
    traces.push(...besideTraces);
    const layout = baseLayout();
    layout.xaxis.title = { text: across ? `depth into the rock behind cell ${g.atCell} (m)`
      : 'distance from the left-hand face (m)', font: { size: 11 } };
    layout.yaxis.type = log ? 'log' : 'linear';
    layout.yaxis.title = { text: inUnit('concentration', u), font: { size: 11 } };
    $('rtmProfileYFrom').disabled = !log;
    const floor = log ? logFloor(state.profileYFrom) : logFloor('');
    const onLeft = traces.filter((t) => !t.yaxis);
    if (floor.lo !== null) layout.yaxis.range = floorRange(floor.lo, onLeft.map((t) => t.y));
    if (slider && spansL.length) {
      const still = stillRange(spansL, log, floor);
      if (still) layout.yaxis.range = still;
    }
    if (right.length) {
      const c = themeColors();
      layout.yaxis2 = { overlaying: 'y', side: 'right', gridcolor: c.grid, zeroline: false, linecolor: c.grid, showgrid: false,
        automargin: true, title: { text: right.join(', '), font: { size: 11 } } };
      if (slider && spansR.length) {
        const still = stillRange(spansR, false, logFloor(''));
        if (still) layout.yaxis2.range = still;
      }
      layout.margin.r = 64;
    }
    const bits = [g.where, `at ${fmtOnAxis(ax, r.t[i])}${slider ? ' on the slider, the axes over the whole run'
      : asked.times.length && !past ? '' : ', the end of the run'}`];
    if (ax.pv) bits.push(`a pore volume ${fmtTime(ax.tw)}`);
    if (ax.why) bits.push(ax.why);
    if (asked.bad.length) bits.push(`could not read ${asked.bad.join(', ')}`);
    if (past) bits.push(`${fmtOnAxis(ax, want)} is past it`);
    else if (asked.times.length && Math.abs(r.t[i] - want) > 0.01 * Math.max(want, 1e-300)) {
      bits.push(`the nearest stored time to ${fmtOnAxis(ax, want)}`);
    }
    if (asked.times.length > 1) bits.push('the first of Times alone');
    if (u.why) bits.push(u.why);
    if (unitLeft.length) bits.push(unitNote(u, unitLeft));
    if (bk && besideTraces.length) bits.push(besideNote(bk) + besidePoreNote(bk, ax));
    if (bk && besideComing.length) bits.push(`working out ${besideComing.join(', ')} for ${bk.label}…`);
    if (bk && besideLeft.length) bits.push(besideNote(bk, [...new Set(besideLeft)].join('; ')));
    if (floorNote(floor, onLeft, u)) bits.push(floorNote(floor, onLeft, u));
    // The note first: a longer one moves the chart down, and Plotly places its legend for where the chart is when drawn.
    $('rtmProfileNote').textContent = bits.join('; ');
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  /*
    THE REDOX ZONES, ON GRADIENT: each cell at each stored time coloured by
    the redox couple that holds its pe -- the one with the most poising
    capacity there, the electrons it takes or gives for a change in pe:
    n Tox Tred/(Tox + Tred), n the electrons between its two states (the
    couples of compositionOf, as the redox ladder has them) and T what the
    cell holds in each, minerals and all; the water's own O2 2 Tox to each O
    of it, and H2 Tred to each H, the water the other state of each. The
    zones in the order the couples turn over, each read off the run where
    its two states come nearest even -- pe less log10(Tox/Tred)/n there --
    oxic first and down the ladder. A model without the electron has none.
  */
  const GRAD_ZONES = '*zones';
  /** The couples a run's zones can be: [{ name, n, hi: [[k, n]] or null, lo: likewise, top, bottom }], or [] without the electron. */
  function zoneItems(m) {
    const C = m && m.composition;
    if (!m || !m.redox || !C) return [];
    const items = dgCoupleItems(C, true, m.species).filter((it) => it.hi.length && it.lo.length)
      .map((it) => ({ name: `${it.cp.ox.join(' + ')}/${it.cp.red.join(' + ')}`, n: it.cp.hi - it.cp.lo, hi: it.hi, lo: it.lo }));
    // The water's own: a species made of O alone, or of H alone, with no charge -- O2 and H2.
    const own = (el) => m.species.map((nm, k) => {
      const made = /[+-]/.test(nm) ? null : RtmModel.elementsOf(nm);
      return made && made.size === 1 && made.has(el) ? [k, made.get(el)] : null;
    }).filter(Boolean);
    const o = own('O');
    const h = own('H');
    if (o.length) items.unshift({ name: `${o.map(([k]) => m.species[k]).join(' + ')}/H2O`, n: 2, hi: o, lo: null, top: true });
    if (h.length) items.push({ name: `H2O/${h.map(([k]) => m.species[k]).join(' + ')}`, n: 1, hi: null, lo: h, bottom: true });
    return items;
  }
  /**
   * Run r's zones at a layer: { items, zone: each model cell along the column by stored point the item holding the pe
   * (-1: none), pe likewise, rung: each item's pe of turning over, read off the run, count: how many waters each holds }.
   */
  const zoneCache = new Map();
  function zonesOf(r, layer) {
    const key = `${r.runKey}|${layer}`;
    if (zoneCache.has(key)) return zoneCache.get(key);
    const m = r.model;
    const items = zoneItems(m);
    const ns = m.nspecies;
    const stride = m.stride || 1;
    const e = m.redox ? m.species.indexOf(m.redox.name) : -1;
    const cells = m.fracture;
    const zone = new Int16Array(cells * r.n).fill(-1);
    const pe = new Float64Array(cells * r.n);
    const near = items.map(() => Infinity);
    const rung = items.map((it) => (it.top ? Infinity : it.bottom ? -Infinity : NaN));
    const count = items.map(() => 0);
    const sum = (terms, b) => { let s = 0; for (const [k, c] of terms) s += c * Math.max(0, r.states[b + k]); return s; };
    for (let c = 0; c < cells; c++) {
      for (let i = 0; i < r.n; i++) {
        const b = i * r.width + (c * stride + Math.min(layer, stride - 1)) * ns;
        const p = e >= 0 ? -Math.log10(r.states[b + e]) : NaN;
        pe[c * r.n + i] = p;
        let most = 0;
        let z = -1;
        items.forEach((it, q) => {
          const ox = it.hi ? sum(it.hi, b) : Infinity;
          const red = it.lo ? sum(it.lo, b) : Infinity;
          const beta = it.n * (it.hi && it.lo ? (ox + red > 0 ? (ox * red) / (ox + red) : 0) : it.hi ? ox : red);
          if (beta > most) { most = beta; z = q; }
          if (it.hi && it.lo && ox > 0 && red > 0 && Number.isFinite(p)) {
            const d = Math.log10(ox / red) / it.n;
            if (Math.abs(d) < near[q]) { near[q] = Math.abs(d); rung[q] = p - d; }
          }
        });
        zone[c * r.n + i] = z;
        if (z >= 0) count[z]++;
      }
    }
    const out = { items, zone, pe, rung, count };
    if (zoneCache.size > 20) zoneCache.clear();
    zoneCache.set(key, out);
    return out;
  }
  // The colour scales of the Gradient, as Plotly has them, dark at 0: the zones' colours are sampled from the one chosen.
  const GRAD_SCALE_STOPS = {
    YlOrRd: [[0, '#800026'], [0.125, '#bd0026'], [0.25, '#e31a1c'], [0.375, '#fc4e2a'], [0.5, '#fd8d3c'], [0.625, '#feb24c'],
      [0.75, '#fed976'], [0.875, '#ffeda0'], [1, '#ffffcc']],
    Viridis: [[0, '#440154'], [0.0627, '#48186a'], [0.1255, '#472d7b'], [0.1882, '#424086'], [0.251, '#3b528b'], [0.3137, '#33638d'],
      [0.3765, '#2c728e'], [0.4392, '#26828e'], [0.502, '#21918c'], [0.5647, '#1fa088'], [0.6275, '#28ae80'], [0.6902, '#3fbc73'],
      [0.7529, '#5ec962'], [0.8157, '#84d44b'], [0.8784, '#addc30'], [0.9412, '#d8e219'], [1, '#fde725']],
    Cividis: [[0, '#00204c'], [0.0588, '#002a66'], [0.1176, '#00346e'], [0.1765, '#273f6c'], [0.2353, '#3c4a6b'], [0.2941, '#4c556b'],
      [0.3529, '#5b5f6d'], [0.4118, '#686a70'], [0.4706, '#757575'], [0.5294, '#838178'], [0.5882, '#928c78'], [0.6471, '#a19876'],
      [0.7059, '#b0a572'], [0.7647, '#c0b16d'], [0.8235, '#d1bf66'], [0.8824, '#e1cc5c'], [0.9412, '#f3db4f'], [1, '#ffe945']],
    Greys: [[0, '#000000'], [1, '#ffffff']],
  };
  const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const rgbHex = (v) => `#${v.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('')}`;
  // A scale's colour p of the way from its light end to its dark end, as Plotly blends it.
  function scaleAt(stops, p) {
    const x = Math.min(1, Math.max(0, 1 - p));
    for (let i = 1; i < stops.length; i++) {
      if (x <= stops[i][0]) {
        const [x0, c0] = stops[i - 1];
        const [x1, c1] = stops[i];
        const w = (x - x0) / (x1 - x0);
        const a = hexRgb(c0);
        const b = hexRgb(c1);
        return rgbHex(a.map((v, j) => v + w * (b[j] - v)));
      }
    }
    return stops[stops.length - 1][1];
  }
  // A colour in OKLab, [L, a, b]: L its lightness, 0 black to 1 white.
  function toOklab(h) {
    const [r, g, b] = hexRgb(h).map((v) => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
  }
  const oklabL = (h) => toOklab(h)[0];
  // Back from OKLab to a colour, its chroma eased off, the hue kept, until a screen can show it.
  function fromOklab([L, a, b]) {
    const lin = (k) => {
      const l = (L + k * (0.3963377774 * a + 0.2158037573 * b)) ** 3;
      const m = (L - k * (0.1055613458 * a + 0.0638541728 * b)) ** 3;
      const s = (L - k * (0.0894841775 * a + 1.291485548 * b)) ** 3;
      return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
    };
    let k = 1;
    let rgb = lin(k);
    while (k > 0.01 && rgb.some((v) => v < -1e-7 || v > 1 + 1e-7)) { k *= 0.95; rgb = lin(k); }
    return rgbHex(rgb.map((v) => {
      const c = Math.min(1, Math.max(0, v));
      return 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
    }));
  }
  /*
    A series' colour at the j-th of n cells from the inlet, on Against time
    at several cells: its own hue at equal steps of OKLab lightness, the
    cell nearest the inlet faintest -- nearest the page's own colour, light
    on a light page and dark on a dark one -- so that the further down the
    column, the more a curve stands out. Every step of Plotly's ten keeps
    3:1 against the page, light or dark, and six cells are at least 0.06
    apart in lightness.
  */
  const CELL_LIGHTNESS = { light: [0.62, 0.28], dark: [0.6, 0.92] };
  function cellColour(hex, j, n) {
    if (n < 2) return hex;
    const [L0, L1] = CELL_LIGHTNESS[document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'];
    const [, a, b] = toOklab(hex);
    return fromOklab([L0 + ((L1 - L0) * j) / (n - 1), a, b]);
  }
  /*
    K colours for K zones in order, from the scale chosen, at equal steps of
    lightness between 0.12 and 0.92 of the way along it -- no zone white or
    black -- the first, the most oxidised, nearest the page: light to dark
    on a light page and dark to light on a dark one, so that the oxic water
    recedes and the more reduced a zone the more it stands out.
  */
  function zoneColours(K, scale) {
    const stops = GRAD_SCALE_STOPS[scale] || GRAD_SCALE_STOPS.YlOrRd;
    const fine = Array.from({ length: 161 }, (_, j) => { const p = 0.12 + (0.8 * j) / 160; return [p, oklabL(scaleAt(stops, p))]; });
    const [L0, L1] = [fine[0][1], fine[fine.length - 1][1]];
    const out = [];
    for (let j = 0; j < K; j++) {
      const want = K === 1 ? (L0 + L1) / 2 : L0 + ((L1 - L0) * j) / (K - 1);
      let q = 1;
      while (q < fine.length - 1 && (fine[q][1] - want) * (L1 - L0) < 0) q++;
      const [pa, la] = fine[q - 1];
      const [pb, lb] = fine[q];
      out.push(scaleAt(stops, lb === la ? pb : pa + ((want - la) / (lb - la)) * (pb - pa)));
    }
    return document.documentElement.getAttribute('data-theme') === 'dark' ? out.reverse() : out;
  }

  /*
    The zones as a map: the run's, and the kept run's under it, on one list
    of zones in the order the couples turn over -- the zones either holds
    somewhere -- each its colour. A map of categories only: the As of
    contours or a surface, log concentration and smooth do not apply to it.
  */
  function drawGradZones(r, plot, gl, logT, tmin) {
    const empty = $('rtmGradEmpty');
    const cells = r.model.fracture;
    const Z = zonesOf(r, gl);
    if (!Z.items.length) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = 'This model has no redox zones: they need the electron and a couple of an element\'s valence states.';
      $('rtmGradNote').textContent = '';
      return;
    }
    // Time across, in the model's unit or in pore volumes; the "from" read on it.
    const ax = timeAxis(r);
    const xr = axisTimes(r, ax);
    const cols = [];
    for (let i = 0; i < r.n; i++) if (!logT || (xr[i] > 0 && xr[i] >= tmin)) cols.push(i);
    if (!cols.length) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = `Nothing is stored after ${fmtAxisNumber(ax, tmin)}: lower the "from" time.`;
      $('rtmGradNote').textContent = '';
      return;
    }
    // The kept run beside it: its own zones, of its own couples, where it has the column and the layer.
    const bk = besideRun();
    const kr = bk ? bk.r : null;
    const kWhy = !bk ? '' : !kr.model.transport || !(kr.model.fracture > 1) ? 'it was a batch'
      : gl > 0 && !(gl < (kr.model.stride || 1)) ? `it has no rock layer ${gl}` : !zoneItems(kr.model).length ? 'it has no redox zones'
        : ax.pv && !poreTime(kr) ? BESIDE_NO_PV : '';
    const KZ = bk && !kWhy ? zonesOf(kr, gl) : null;
    // One list, by name: the zones either run holds, in the order they turn over, the run's own reading first.
    const rungOf = new Map();
    for (const z of KZ ? [Z, KZ] : [Z]) {
      z.items.forEach((it, q) => { if (z.count[q] && !rungOf.has(it.name)) rungOf.set(it.name, z.rung[q]); });
    }
    const names = [...rungOf.keys()].sort((a, b) => {
      const ra = rungOf.get(a);
      const rb = rungOf.get(b);
      return (Number.isNaN(rb) ? -Infinity : rb) - (Number.isNaN(ra) ? -Infinity : ra);
    });
    const K = names.length;
    if (!K) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = 'No couple holds the pe anywhere in this run: none of them has both its states in any cell.';
      $('rtmGradNote').textContent = '';
      return;
    }
    const colours = zoneColours(K, state.gradScale);
    const colorscale = [];
    colours.forEach((col, j) => { colorscale.push([j / K, col], [(j + 1) / K, col]); });
    const view = state.gradView || 'map';
    const at = ax.pv ? '%{x:.3g} PV' : `t = %{x:.3e} ${ax.sym}`;
    const big = cells * cols.length > 400000;
    const mapOf = (z, run, cs, ncells) => {
      const at = z.items.map((it) => names.indexOf(it.name));
      const zz = [];
      const text = [];
      for (let c = 0; c < ncells; c++) {
        const row = [];
        const words = [];
        for (const i of cs) {
          const q = z.zone[c * run.n + i];
          row.push(q >= 0 && at[q] >= 0 ? at[q] : null);
          if (!big) words.push(q >= 0 ? `${z.items[q].name}, pe ${z.pe[c * run.n + i].toFixed(2)}` : 'no couple holds it');
        }
        zz.push(row);
        text.push(words);
      }
      return { zz, text };
    };
    const own = mapOf(Z, r, cols, cells);
    const trace = {
      type: 'heatmap', x: cols.map((i) => xr[i]), y: Array.from(r.model.centres), z: own.zz, zmin: -0.5, zmax: K - 0.5, zauto: false,
      colorscale, connectgaps: false, zsmooth: false, meta: { categories: names },
      ...(big ? { hovertemplate: `${at}<br>x = %{y:.3e} m<extra></extra>` }
        : { text: own.text, hovertemplate: `${at}<br>x = %{y:.3e} m<br>%{text}<extra></extra>` }),
      colorbar: { title: { text: 'the couple holding the pe', side: 'right', font: { size: 11 } }, tickvals: names.map((_, j) => j),
        ticktext: names.map((nm) => esc(nm)), thickness: 14, outlinewidth: 0, tickfont: { size: 10 } },
    };
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.margin.l = 92;
    layout.xaxis.type = logT ? 'log' : 'linear';
    layout.xaxis.title = { text: ax.title, font: { size: 11 } };
    layout.yaxis.title = { text: 'distance from the left-hand face (m)', font: { size: 11 } };
    const traces = [trace];
    let besideSaid = bk && kWhy ? besideNote(bk, kWhy) : '';
    if (KZ) {
      const kt = besideAxis(bk, ax);
      const kcols = [];
      for (let i = 0; i < kr.n; i++) if (!logT || (kt[i] > 0 && kt[i] >= tmin)) kcols.push(i);
      const theirs = mapOf(KZ, kr, kcols, kr.model.fracture);
      traces.push({ ...trace, x: kcols.map((i) => kt[i]), y: Array.from(kr.model.centres), z: theirs.zz, showscale: false,
        ...(big ? {} : { text: theirs.text }), xaxis: 'x2', yaxis: 'y2',
        hovertemplate: trace.hovertemplate.replace('<extra></extra>', `<extra>${esc(bk.label)}</extra>`) });
      const note = (text, x, y) => ({ text: esc(text), xref: 'paper', yref: 'paper', x, y, xanchor: 'left', yanchor: 'bottom',
        showarrow: false, font: { size: 11, color: themeColors().text } });
      layout.yaxis.domain = [0.54, 1];
      layout.xaxis.anchor = 'y';
      layout.xaxis2 = { ...layout.xaxis, anchor: 'y2', matches: 'x' };
      layout.yaxis2 = { ...layout.yaxis, domain: [0, 0.44], anchor: 'x2' };
      layout.xaxis.title = undefined;
      layout.margin.t = 24;
      layout.annotations = [note('this run', 0, 1.0), note(bk.label, 0, 0.445)];
      besideSaid = `${bk.label} beside it${besidePoreNote(bk, ax)}, its own zones below, in the same colours`;
    }
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    // What share of the map each zone holds, in order; the couples that hold the pe nowhere in it.
    const total = Z.count.reduce((a, b) => a + b, 0);
    const shares = names.map((nm) => {
      const q = Z.items.findIndex((it) => it.name === nm);
      return q >= 0 && Z.count[q] ? `${nm} ${((100 * Z.count[q]) / Math.max(1, total)).toFixed(1)} %` : '';
    }).filter(Boolean);
    const never = Z.items.filter((it, q) => !Z.count[q]).map((it) => it.name);
    const bits = [`${cells} cells × ${cols.length} stored times${gl ? `, rock layer ${gl}` : ''}`,
      `the redox zones by the couple holding the pe, oxidised first: ${shares.join(', ')} of the waters`];
    if (ax.pv) bits.push(`a pore volume ${fmtTime(ax.tw)}`);
    if (ax.why) bits.push(ax.why);
    if (never.length) bits.push(`never holding it: ${never.join(', ')}`);
    if (logT && cols.length < r.n) bits.push(`${r.n - cols.length} earlier points left off (t = 0 cannot go on a log axis)`);
    if (view !== 'map') bits.push('drawn as a map: zones are no amount to draw contours of or raise into a surface');
    if (besideSaid) bits.push(besideSaid);
    $('rtmGradNote').textContent = bits.join('; ');
  }

  /**
   * The whole run as one picture: time across, distance down, concentration as
   * colour. What a stack of profiles says one curve at a time, this says at
   * once -- where a front is, when it arrives, how far it gets.
   *
   * Time runs along x and distance up y, which is the transpose of the way the
   * skbrtm examples draw it.
   */
  function drawGradient() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartGradient');
    const empty = $('rtmGradEmpty');
    const r = state.result;
    if (!r || !r.model.transport || r.model.fracture < 2) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = r ? 'This run was a batch: there is no distance to plot against.'
        : 'A gradient needs a run in transport mode.';
      $('rtmGradNote').textContent = '';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const name = state.gradSpecies || r.model.species[0];
    const si = r.model.species.indexOf(name);
    const ns = r.model.nspecies;
    const cells = r.model.fracture;
    const stride = r.model.stride || 1;
    const gl = Math.min(state.gradLayer, stride - 1);
    const logT = $('rtmGradLogT').checked;
    // The redox zones are categories: no log of them, no from, no smoothing between them.
    const zones = name === GRAD_ZONES;
    $('rtmGradLogC').disabled = zones;
    $('rtmGradSmooth').disabled = zones;
    if (zones) {
      $('rtmGradCFrom').disabled = true;
      drawGradZones(r, plot, gl, logT, Number($('rtmGradTMin').value) || 0);
      return;
    }
    // A quantity: every cell's, from the worker; pH, SI and the like are on a scale of their own, never logged again.
    const quantity = isQuantity(name);
    const q = quantity ? quantityOf(name) : null;
    const logC = $('rtmGradLogC').checked && !(q && q.axis === 'index');
    const cellsHere = Array.from({ length: cells }, (_, c) => c * stride + gl);
    if (quantity && cellsHere.some((c) => quantityPending(name, c))) {
      fetchQuantities([name], cellsHere);
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = `Working out ${labelOf(name)} in every cell…`;
      $('rtmGradNote').textContent = '';
      return;
    }
    // In the unit shown; a key that has none in it -- no formula to weigh -- as the model has it, and the note says so.
    const u = shownUnit(r);
    const shown = shownAs(r, name, u);
    const own = !!(shown && shown.why);
    const f = shown && shown.f ? shown.f : 1;
    const suffix = unitSaid(u) && shown && !own ? (u.bare ? ` ${u.text}` : ` (${u.text})`) : '';
    const valueAt = (i, c) => (quantity ? (quantitySeries(name, c * stride + gl) || [])[i]
      : r.states[i * r.width + (c * stride + gl) * ns + si]) * f;

    /*
      A log time axis cannot show t = 0, and a stiff run's first steps are
      femtoseconds -- fifteen decades in which nothing has happened yet. So the
      same "from" the time chart has, and the note says what it left out.
    */
    const tmin = Number($('rtmGradTMin').value) || 0;
    // Time across, in the model's unit or in pore volumes; the "from" read on it.
    const ax = timeAxis(r);
    const xr = axisTimes(r, ax);
    const cols = [];
    for (let i = 0; i < r.n; i++) if (!logT || (xr[i] > 0 && xr[i] >= tmin)) cols.push(i);
    if (!cols.length) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = `Nothing is stored after ${fmtAxisNumber(ax, tmin)}: lower the "from" time.`;
      $('rtmGradNote').textContent = '';
      return;
    }

    // z is row-major over y: one row per cell, one column per stored time.
    const z = [];
    let lo = Infinity;
    let hi = -Infinity;
    let nonPositive = 0;
    for (let c = 0; c < cells; c++) {
      const row = new Array(cols.length);
      for (let k = 0; k < cols.length; k++) {
        const v = valueAt(cols[k], c);
        if (logC) {
          if (v > 0) { row[k] = Math.log10(v); } else { row[k] = null; nonPositive++; }
        } else row[k] = Number.isFinite(v) ? v : null;
        if (row[k] !== null) { lo = Math.min(lo, row[k]); hi = Math.max(hi, row[k]); }
      }
      z.push(row);
    }
    const layout = baseLayout();
    layout.hovermode = 'closest';
    // The distances run to 1e-4, so the ticks are wide: the default margin
    // puts the axis title through them.
    layout.margin.l = 92;
    layout.xaxis.type = logT ? 'log' : 'linear';
    layout.xaxis.title = { text: ax.title, font: { size: 11 } };
    layout.yaxis.title = { text: 'distance from the left-hand face (m)', font: { size: 11 } };
    // Distance up the page from zero at the origin, the ordinary way round.
    // As a map, as contours of it, or as a surface over time and distance.
    const view = state.gradView || 'map';
    const title = suffix ? `${q ? q.label : name}${suffix}` : q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : name;
    const at = ax.pv ? '%{x:.3g} PV' : `t = %{x:.3e} ${ax.sym}`;
    const trace = {
      type: view === 'contour' ? 'contour' : view === 'surface' ? 'surface' : 'heatmap',
      x: cols.map((i) => xr[i]),
      y: Array.from(r.model.centres),
      z,
      colorscale: state.gradScale,
      reversescale: state.gradScale === 'YlOrRd',
      ...(view === 'contour' ? { contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 10 } }, line: { width: 0.6 } } : {}),
      connectgaps: false,
      /*
        Off by default: with twenty cells the bands ARE the cells, and a
        smoothed picture shows a resolution the run does not have. On, it
        matches the way the skbrtm examples are drawn.
      */
      zsmooth: $('rtmGradSmooth').checked ? 'best' : false,
      hovertemplate: logC
        ? `${at}<br>x = %{y:.3e} m<br>log₁₀ c = %{z:.3f}<extra></extra>`
        : `${at}<br>x = %{y:.3e} m<br>c = %{z:.4e}<extra></extra>`,
      colorbar: {
        title: { text: logC ? `log₁₀ ${title}` : title, side: 'right', font: { size: 11 } },
        thickness: 14, outlinewidth: 0, tickfont: { size: 10 },
        exponentformat: 'power',
      },
    };
    if (view === 'surface') {
      // A surface in three dimensions: the same axes, with the value up.
      delete trace.zsmooth;
      delete trace.connectgaps;
      const c = themeColors();
      const axis3 = (text, type) => ({ title: { text, font: { size: 11 } }, type, gridcolor: c.grid, color: c.text });
      layout.scene = { xaxis: axis3(ax.title, logT ? 'log' : 'linear'), yaxis: axis3('distance (m)', 'linear'),
        zaxis: axis3(logC ? `log₁₀ ${title}` : title, 'linear'), camera: { eye: { x: -1.6, y: -1.6, z: 1.0 } } };
      layout.margin = { l: 0, r: 0, t: 10, b: 0 };
    }
    /*
      The kept run beside it: its own map, its cells and its stored times --
      in this run's unit -- under this run's, or beside it as a second
      surface, on one colour scale from the lowest of the two to the
      highest.
    */
    const bk = besideRun();
    const traces = [trace];
    let besideSaid = '';
    if (bk) {
      const kr = bk.r;
      const km = kr.model;
      const kStride = km.stride || 1;
      const kShown = runHas(kr, name) && !own ? shownAs(kr, name, u) : null;
      const why = !km.transport || !(km.fracture > 1) ? 'it was a batch' : !runHas(kr, name) ? `it has no ${labelOf(name)}`
        : gl > 0 && !(gl < kStride) ? `it has no rock layer ${gl}`
          : ax.pv && !poreTime(kr) ? BESIDE_NO_PV
            : kShown && kShown.why ? besideUnitWhy(u, labelOf(name), kShown.why) : '';
      const kf = kShown && kShown.f ? kShown.f : 1;
      const kCells = why ? [] : Array.from({ length: km.fracture }, (_, c) => c * kStride + gl);
      const kQuantity = !why && runQuantity(kr, name);
      if (why) besideSaid = besideNote(bk, why);
      else if (kQuantity && kCells.some((c) => quantityPending(name, c, kr))) {
        fetchQuantities([name], kCells, kr);
        besideSaid = `working out ${labelOf(name)} for ${bk.label}…`;
      } else {
        const kt = besideAxis(bk, ax);
        const ksi = km.species.indexOf(name);
        const kcols = [];
        for (let i = 0; i < kr.n; i++) if (!logT || (kt[i] > 0 && kt[i] >= tmin)) kcols.push(i);
        const kz = [];
        for (let c = 0; c < km.fracture; c++) {
          kz.push(kcols.map((i) => {
            const v = (kQuantity ? (quantitySeries(name, kCells[c], kr) || [])[i] : kr.states[i * kr.width + kCells[c] * km.nspecies + ksi]) * kf;
            const u = logC ? (v > 0 ? Math.log10(v) : null) : (Number.isFinite(v) ? v : null);
            if (u !== null) { lo = Math.min(lo, u); hi = Math.max(hi, u); }
            return u;
          }));
        }
        const second = { ...trace, x: kcols.map((i) => kt[i]), y: Array.from(km.centres), z: kz, showscale: false,
          hovertemplate: trace.hovertemplate.replace('<extra></extra>', `<extra>${esc(bk.label)}</extra>`) };
        const range = Number.isFinite(lo) ? { [view === 'surface' ? 'cmin' : 'zmin']: lo, [view === 'surface' ? 'cmax' : 'zmax']: hi } : {};
        Object.assign(trace, range);
        Object.assign(second, range);
        const note = (text, x, y, xanchor = 'left') => ({ text: esc(text), xref: 'paper', yref: 'paper', x, y, xanchor, yanchor: 'bottom',
          showarrow: false, font: { size: 11, color: themeColors().text } });
        if (view === 'surface') {
          layout.scene.domain = { x: [0, 0.49], y: [0, 1] };
          layout.scene2 = { ...layout.scene, domain: { x: [0.51, 1], y: [0, 1] } };
          second.scene = 'scene2';
          layout.annotations = [note('this run', 0.02, 0.95), note(bk.label, 0.53, 0.95)];
        } else {
          layout.yaxis.domain = [0.54, 1];
          layout.xaxis.anchor = 'y';
          layout.xaxis2 = { ...layout.xaxis, anchor: 'y2', matches: 'x' };
          layout.yaxis2 = { ...layout.yaxis, domain: [0, 0.44], anchor: 'x2' };
          layout.xaxis.title = undefined;
          layout.margin.t = 24;
          second.xaxis = 'x2';
          second.yaxis = 'y2';
          layout.annotations = [note('this run', 0, 1.0), note(bk.label, 0, 0.445)];
        }
        traces.push(second);
        besideSaid = `${bk.label} beside it${besidePoreNote(bk, ax)}, its own map${view === 'surface' ? ' to the right' : ' below'}, on one colour scale`;
      }
    }
    /*
      The floor of a log concentration: the colour scale from it, what lies
      below in its colour; a surface's value axis from it, what lies below
      out of the box. The values themselves, and so what is saved, are all
      there still.
    */
    $('rtmGradCFrom').disabled = !$('rtmGradLogC').checked;
    const floor = logC ? logFloor(state.gradCFrom) : logFloor('');
    if (floor.lo !== null && Number.isFinite(hi)) {
      const top = Math.max(hi, floor.lo + 1e-9);
      for (const tr of traces) Object.assign(tr, view === 'surface' ? { cmin: floor.lo, cmax: top } : { zmin: floor.lo, zmax: top, zauto: false });
      if (view === 'surface') {
        const zr = [floor.lo, top + Math.max(0.05, 0.04 * (top - floor.lo))];
        layout.scene.zaxis.range = zr;
        if (layout.scene2) layout.scene2 = { ...layout.scene2, zaxis: { ...layout.scene2.zaxis, range: zr } };
      }
    }
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    const bits = [`${cells} cells × ${cols.length} stored times${gl ? `, rock layer ${gl}` : ''}`];
    if (ax.pv) bits.push(`a pore volume ${fmtTime(ax.tw)}`);
    if (ax.why) bits.push(ax.why);
    if (Number.isFinite(lo)) {
      bits.push(logC ? `10^${lo.toFixed(2)} to 10^${hi.toFixed(2)}`
        : `${lo.toExponential(3)} to ${hi.toExponential(3)}`);
    } else bits.push('nothing to show: every value is zero or below');
    if (logT && cols.length < r.n) {
      bits.push(`${r.n - cols.length} earlier points left off (t = 0 cannot go on a log axis)`);
    }
    if (nonPositive) bits.push(`${nonPositive} values at or below zero left blank`);
    if (floor.bad) bits.push(floorNote(floor, []));
    else if (floor.lo !== null && Number.isFinite(lo)) {
      bits.push(`the colour scale from ${floor.at.toExponential()}${suffix && !u.bare ? ` ${u.text}` : ''}${lo < floor.lo
        ? `, below it ${view === 'surface' ? 'out of the box' : 'in its colour'}` : ''}`);
    }
    if (u.why) bits.push(u.why);
    if (own) bits.push(ownUnitNote(u, labelOf(name), shown.why));
    if (besideSaid) bits.push(besideSaid);
    $('rtmGradNote').textContent = bits.join('; ');
  }

  /* ---------------------------------------------------------------------
     Composition: where an element is, and the water's major ions as the
     Piper, Schoeller and Stiff diagrams draw them

     All of it from the stored concentrations and what each species is made
     of (compositionOf in rtm-model.js): sums, no chemistry, so nothing is
     asked of the worker.
     --------------------------------------------------------------------- */
  /** What each species is made of, as the model compiled says, or null. */
  const compositionOf = (m) => (m && m.composition) || null;
  const WHERE_LABELS = { water: 'dissolved', exchange: 'on the exchanger', surface: 'on the surface', mineral: 'mineral',
    gas: 'gas' };

  /** The elements a chart of where an element is can show: those two species or more hold, in the water or anywhere. */
  function compElements(m, scope) {
    const C = compositionOf(m);
    if (!C) return [];
    return C.elements.map((e) => ({ el: e.el, terms: scope === 'all' ? e.terms : e.terms.filter((tm) => tm[2] === 'water') }))
      .filter((e) => e.terms.length > 1);
  }

  /*
    The six poles of the water's major ions, in equivalents: Ca and Mg twice
    their totals, Na and K together, Cl, the sulfate twice its sulfur, and the
    carbonate's alkalinity, HCO3- one and CO3-2 two (compositionOf). A total
    is everything dissolved: CaHCO3+ counts in Ca and in the carbonate.
  */
  const POLES = [
    { key: 'Ca', label: 'Ca', cation: true }, { key: 'Mg', label: 'Mg', cation: true },
    { key: 'NaK', label: 'Na + K', cation: true }, { key: 'Cl', label: 'Cl' }, { key: 'SO4', label: 'SO₄' },
    { key: 'HCO3', label: 'HCO₃ + CO₃' },
  ];
  const CATIONS = POLES.filter((p) => p.cation);
  const ANIONS = POLES.filter((p) => !p.cation);

  /** Each pole of the model's water as [[species, equivalents to one of it]]. */
  function poleTerms(C) {
    const dissolved = (el, z) => ((C.elements.find((e) => e.el === el) || { terms: [] }).terms)
      .filter((tm) => tm[2] === 'water').map(([k, n]) => [k, n * z]);
    return { Ca: dissolved('Ca', 2), Mg: dissolved('Mg', 2), NaK: [...dissolved('Na', 1), ...dissolved('K', 1)],
      Cl: dissolved('Cl', 1), SO4: C.sulfate.map(([k, s]) => [k, 2 * s]), HCO3: C.carbonate.map(([k, q]) => [k, q]) };
  }

  /**
   * What the poles are counted in: meq/kgw where an activity model says the
   * concentrations are mol/kgw, else the concentrations' own unit times the
   * charge.
   */
  const poleUnit = (m) => (m && m.activity ? { scale: 1000, text: 'meq/kgw' }
    : { scale: 1, text: 'equivalents: concentration × charge' });

  /** A water's six poles at stored point i in model cell mc. */
  function waterAt(r, terms, scale, i, mc) {
    const ns = r.model.nspecies;
    const base = i * r.width + mc * ns;
    const w = {};
    for (const p of POLES) {
      let s = 0;
      for (const [k, q] of terms[p.key]) s += q * Math.max(0, r.states[base + k]);
      w[p.key] = s * scale;
    }
    return w;
  }

  /**
   * The waters <DATA> measured where the chart is looking -- a table in time
   * at its cell and layer, every table in distance -- each row with any of
   * the major ions a water: a column read by the name the model gives it,
   * tot(Ca) or Ca+2, alk(CO3) or HCO3- and CO3-2; one the table has not got
   * counts as none.
   */
  function measuredWaters(along, cell, layer, scale) {
    const data = (state.compiled && state.compiled.data) || [];
    const r = state.result;
    const out = [];
    for (const tab of data) {
      if (tab.kind !== along) continue;
      if (along === 'time' && ((tab.cell || 0) !== cell || (tab.layer || 0) !== layer)) continue;
      const col = (row, keys, z) => {
        for (const key of keys) {
          const j = tab.columns.indexOf(key);
          if (j >= 0) return row[j + 1] === null ? 0 : row[j + 1] * z;
        }
        return 0;
      };
      if (!['tot(Ca)', 'Ca+2', 'tot(Mg)', 'Mg+2', 'tot(Na)', 'Na+', 'tot(K)', 'K+', 'tot(Cl)', 'Cl-', 'tot(SO4)', 'tot(S)',
        'SO4-2', 'alk(CO3)', 'HCO3-', 'CO3-2'].some((key) => tab.columns.includes(key))) continue;
      const at = tab.kind === 'distance' ? (tab.at !== null ? tab.at : r.t[r.n - 1]) : null;
      for (const row of tab.rows) {
        const w = {
          Ca: col(row, ['tot(Ca)', 'Ca+2'], 2), Mg: col(row, ['tot(Mg)', 'Mg+2'], 2),
          NaK: col(row, ['tot(Na)', 'Na+'], 1) + col(row, ['tot(K)', 'K+'], 1), Cl: col(row, ['tot(Cl)', 'Cl-'], 1),
          SO4: col(row, ['tot(SO4)', 'tot(S)', 'SO4-2'], 2),
          HCO3: tab.columns.includes('alk(CO3)') ? col(row, ['alk(CO3)'], 1) : col(row, ['HCO3-'], 1) + col(row, ['CO3-2'], 2),
        };
        for (const p of POLES) w[p.key] *= scale;
        if (!(CATIONS.some((p) => w[p.key] > 0) && ANIONS.some((p) => w[p.key] > 0))) continue;
        out.push({ w, measured: true, t: along === 'time' ? row[0] : at, x: along === 'distance' ? row[0] : null,
          cell: along === 'time' ? (tab.cell || 0) : null,
          label: along === 'time' ? `measured, ${fmtTime(row[0])}` : `measured, ${fmtNumber(row[0])} m` });
      }
    }
    return out;
  }

  /** The shares of a water's cations and of its anions, each summing to one; null where either has none. */
  function poleShares(w) {
    const cs = CATIONS.reduce((s, p) => s + w[p.key], 0);
    const as = ANIONS.reduce((s, p) => s + w[p.key], 0);
    if (!(cs > 0 && as > 0)) return null;
    const f = {};
    for (const p of CATIONS) f[p.key] = w[p.key] / cs;
    for (const p of ANIONS) f[p.key] = w[p.key] / as;
    return f;
  }

  /**
   * A water's type, its hydrochemical facies, the usual way: the cation and
   * the anion that are half or more of theirs, or the two largest where none
   * is -- Ca–HCO₃, Na–Cl, Ca–Na–HCO₃–Cl.
   */
  function faciesOf(f) {
    const side = (poles) => {
      const sorted = poles.map((p) => [p.key === 'NaK' ? 'Na' : p.label.replace(' + CO₃', ''), f[p.key]]).sort((a, b) => b[1] - a[1]);
      // Half, give or take the rounding: three of six is 0.49999999999999994.
      return sorted[0][1] >= 0.5 - 1e-12 ? [sorted[0][0]] : sorted.slice(0, 2).filter(([, v]) => v > 0).map(([nm]) => nm);
    };
    return [...side(CATIONS), ...side(ANIONS)].join('–');
  }

  // The Piper diagram's geometry: triangles of side 1, the gap between them, and the diamond above.
  const PIPER_H = Math.sqrt(3) / 2;
  const PIPER_GAP = 0.2;
  /** A water's three points: in the cations' triangle, in the anions' and in the diamond. */
  function piperXY(f) {
    const H = PIPER_H;
    const g = PIPER_GAP;
    // The diamond from its lowest corner: Ca + Mg up to the left, SO4 + Cl up to the right.
    const p = f.Ca + f.Mg;
    const q = f.Cl + f.SO4;
    return {
      cat: [f.NaK + 0.5 * f.Mg, H * f.Mg],
      an: [1 + g + f.Cl + 0.5 * f.SO4, H * f.SO4],
      dia: [1 + g / 2 - 0.5 * p + 0.5 * q, g * H + H * (p + q)],
    };
  }

  /** The Piper diagram's frame and its grid every 20 %, as traces and labels. */
  function piperFrame(c) {
    const H = PIPER_H;
    const g = PIPER_GAP;
    const xs = [];
    const ys = [];
    const seg = (a, b) => { xs.push(a[0], b[0], null); ys.push(a[1], b[1], null); };
    const tri = (x0) => {
      for (const f of [0.2, 0.4, 0.6, 0.8]) {
        seg([x0 + 0.5 * f, H * f], [x0 + 1 - 0.5 * f, H * f]);
        seg([x0 + 1 - f, 0], [x0 + 0.5 * (1 - f), H * (1 - f)]);
        seg([x0 + f, 0], [x0 + f + 0.5 * (1 - f), H * (1 - f)]);
      }
    };
    tri(0);
    tri(1 + g);
    const B = [1 + g / 2, g * H];
    const at = (p, q) => [B[0] - 0.5 * p + 0.5 * q, B[1] + H * (p + q)];
    for (const f of [0.2, 0.4, 0.6, 0.8]) { seg(at(f, 0), at(f, 1)); seg(at(0, f), at(1, f)); }
    const outline = (pts) => ({ type: 'scatter', mode: 'lines', x: [...pts.map((pt) => pt[0]), pts[0][0]],
      y: [...pts.map((pt) => pt[1]), pts[0][1]], line: { color: c.text, width: 1 }, hoverinfo: 'skip', showlegend: false });
    const traces = [
      { type: 'scatter', mode: 'lines', x: xs, y: ys, line: { color: c.grid, width: 0.7 }, hoverinfo: 'skip', showlegend: false },
      outline([[0, 0], [1, 0], [0.5, H]]),
      outline([[1 + g, 0], [2 + g, 0], [1.5 + g, H]]),
      outline([at(0, 0), at(1, 0), at(1, 1), at(0, 1)]),
    ];
    const label = (x, y, text, extra = {}) => ({ x, y, xref: 'x', yref: 'y', text, showarrow: false, font: { size: 11, color: c.text },
      ...extra });
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const ul = mid(at(1, 0), at(1, 1));
    const ur = mid(at(0, 1), at(1, 1));
    const annotations = [
      // The corners at the gap read away from it, so that Na + K and HCO3 + CO3 do not run into each other.
      label(0, -0.035, 'Ca', { yanchor: 'top' }), label(1, -0.035, 'Na + K', { yanchor: 'top', xanchor: 'right' }),
      label(0.5 - 0.03, H, 'Mg', { xanchor: 'right' }),
      label(1 + g, -0.035, 'HCO₃ + CO₃', { yanchor: 'top', xanchor: 'left' }), label(2 + g, -0.035, 'Cl', { yanchor: 'top' }),
      label(1.5 + g + 0.03, H, 'SO₄', { xanchor: 'left' }),
      // Along the diamond's upper edges, each pole the way it grows.
      label(ul[0] - 0.05 * H, ul[1] + 0.025, 'SO₄ + Cl', { textangle: -60 }),
      label(ur[0] + 0.05 * H, ur[1] + 0.025, 'Ca + Mg', { textangle: 60 }),
    ];
    return { traces, annotations };
  }

  /** What the composition chart drew, as a table for CSV and Excel: kept as it is drawn. */
  let compTableNow = null;

  /** The composition tab's controls, for the run or the model compiled: the pickers filled, what does not apply hidden. */
  function renderComp() {
    const m = (state.result && state.result.model) || state.compiled;
    const view = state.compView;
    const column = !!(m && m.transport && m.fracture > 1);
    const along = column ? state.compAlong : 'time';
    const list = compElements(m, state.compIn);
    if (list.length && !list.some((e) => e.el === state.compElement)) state.compElement = list[0].el;
    $('rtmCompElement').innerHTML = list.length ? list.map((e) => `<option value="${esc(e.el)}"`
      + `${e.el === state.compElement ? ' selected' : ''}>${esc(e.el)}</option>`).join('') : '<option value="">none</option>';
    $('rtmCompView').value = view;
    $('rtmCompIn').value = state.compIn;
    $('rtmCompAs').value = state.compAs;
    $('rtmCompAlong').value = along;
    document.querySelectorAll('[data-comp-for]').forEach((el) => { el.hidden = el.dataset.compFor !== view; });
    // The water as PHREEQC lists it: one cell at one time, and no picture to save.
    const listing = view === 'listing';
    // A budget: of the whole column, along the run; of an element, or of one species.
    const budget = view === 'budget';
    {
      const { els, sp } = budgetChoices(m);
      if (!state.compBudgetOf || !((state.compBudgetOf.startsWith('element:') && els.includes(state.compBudgetOf.slice(8)))
        || (state.compBudgetOf.startsWith('species:') && sp.includes(state.compBudgetOf.slice(8)))
        || (state.compBudgetOf === BUDGET_ALL && els.length))) {
        state.compBudgetOf = els.length ? `element:${els[0]}` : sp.length ? `species:${sp[0]}` : '';
      }
      const opt = (v, label) => `<option value="${esc(v)}"${v === state.compBudgetOf ? ' selected' : ''}>${esc(label)}</option>`;
      $('rtmCompBudgetOf').innerHTML = (els.length ? `<optgroup label="Elements">${opt(BUDGET_ALL, 'every element')}`
        + `${els.map((e) => opt(`element:${e}`, e)).join('')}</optgroup>` : '')
        + (sp.length ? `<optgroup label="Species">${sp.map((x) => opt(`species:${x}`, x)).join('')}</optgroup>` : '');
    }
    document.querySelectorAll('[data-comp-hide]').forEach((el) => { el.hidden = el.dataset.compHide === view; });
    // By each reaction, where the model has <REACTIONS> lines: over the whole column, or at one of its cells. Where it goes,
    // of an element: from species to species over the run.
    {
      const hasLines = !!(m && (m.quantities || []).some((q) => q.group === 'reactions'));
      const every = state.compBudgetOf === BUDGET_ALL;
      const ofElement = state.compBudgetOf.startsWith('element:');
      const offered = (v) => v === 'where' || (v === 'lines' && hasLines) || (v === 'flows' && ofElement);
      for (const o of $('rtmCompBudgetBy').options) {
        o.disabled = !offered(o.value);
        if (o.value === 'flows') o.textContent = ofElement ? 'where it goes' : 'where it goes, of an element';
      }
      const by = offered(state.compBudgetBy) ? state.compBudgetBy : 'where';
      const byLines = budget && by === 'lines' && !every;
      $('rtmCompBudgetBy').value = by;
      $('rtmCompBudgetByWrap').hidden = !budget || every || (!hasLines && !ofElement);
      const nfc = m ? m.fracture : 1;
      if (state.compBudgetAt !== 'column' && !(state.compBudgetAt >= 0 && state.compBudgetAt < nfc)) state.compBudgetAt = 'column';
      $('rtmCompBudgetAt').innerHTML = `<option value="column"${state.compBudgetAt === 'column' ? ' selected' : ''}>the whole column</option>`
        + Array.from({ length: column ? nfc : 0 }, (_, i) => `<option value="${i}"${i === state.compBudgetAt ? ' selected' : ''}>cell ${i}`
          + `${m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
      $('rtmCompBudgetAtWrap').hidden = !(byLines && column);
    }
    // The minerals' fronts: along the whole column, through the whole run.
    const fronts = view === 'fronts';
    $('rtmCompAlongWrap').hidden = !column || listing || budget || fronts;
    const cells = m ? m.fracture : 1;
    if (!(state.compCell < cells)) state.compCell = 0;
    $('rtmCompCell').innerHTML = Array.from({ length: cells }, (_, i) => `<option value="${i}"${i === state.compCell ? ' selected' : ''}>`
      + `${i}${m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
    $('rtmCompCellWrap').hidden = (along !== 'time' && !listing) || cells < 2 || budget || fronts;
    const nm = m && m.matrix ? m.matrix.n : 0;
    if (state.compLayer > nm) state.compLayer = 0;
    $('rtmCompLayer').innerHTML = layerOptions(state.compLayer);
    $('rtmCompLayerWrap').hidden = nm === 0;
    // Along the run, the times are those the water is drawn at (where an element is needs none); across the column, one time.
    $('rtmCompTimesWrap').hidden = (along === 'time' && ['where', 'ussl', 'wilcox', 'pca'].includes(view) && !listing) || budget || fronts;
    $('rtmCompPcaVars').value = state.compPcaVars;
    $('rtmCompPcaLog').checked = state.compPcaLog;
    $('rtmCompBeside').checked = state.compBeside;
    $('rtmCompTimesLabel').textContent = along === 'time' && !listing ? 'Times' : 'At';
    $('rtmCompTimes').placeholder = along === 'time' && !listing ? 'spread over the run' : 'the end of the run';
    $('rtmCompTimes').value = state.compTimes;
    // Every element at once has no time axis to draw, nor has where an element goes, over the whole run.
    $('rtmCompLogTWrap').hidden = ((along !== 'time' || view === 'schoeller' || view === 'stiff') && !budget) || listing || fronts
      || (budget && state.compBudgetOf === BUDGET_ALL)
      || (budget && state.compBudgetBy === 'flows' && state.compBudgetOf.startsWith('element:'));
    $('rtmCompTMinWrap').hidden = $('rtmCompLogTWrap').hidden;
    $('rtmCompTMin').value = state.compTMin;
    $('rtmCompTMinUnit').textContent = shownTime().sym;
  }

  function drawComp() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartComp');
    const empty = $('rtmCompEmpty');
    const note = $('rtmCompNote');
    const r = state.result;
    compTableNow = null;
    compTextNow = '';
    $('rtmCompListing').hidden = true;
    $('rtmCompLines').hidden = true;
    const fail = (text) => {
      Plotly.purge(plot);
      plot.hidden = true;
      $('rtmCompListing').hidden = true;
      $('rtmCompLines').hidden = true;
      empty.hidden = false;
      empty.textContent = text;
      note.textContent = '';
    };
    if (!r) { fail('Run the model to see what its water is made of.'); return; }
    if (!compositionOf(r.model)) { fail('Run the model again: this run was made before the page could read what its species are made of.'); return; }
    const column = r.model.transport && r.model.fracture > 1;
    const along = column ? state.compAlong : 'time';
    const stride = r.model.stride || 1;
    const layer = Math.min(state.compLayer, stride - 1);
    const cell = Math.min(state.compCell, r.model.fracture - 1);
    // Across the column, one time: the slider's, or the first asked for, or the end of the run.
    const asked = parseTimes(state.compTimes, shownTime());
    const still = compSliding(r) && state.compAt !== null;
    const atIndex = still ? nearestIndex(r.t, state.compAt) : asked.times.length ? nearestIndex(r.t, asked.times[0]) : r.n - 1;
    renderCompPlay(r, atIndex);
    const ctx = { r, plot, along, layer, cell, asked, atIndex, column, fail, note, still };
    empty.hidden = true;
    plot.hidden = false;
    if (state.compView === 'where') drawWhere(ctx);
    else if (state.compView === 'listing') drawListing(ctx);
    else if (state.compView === 'budget') drawBudget(ctx);
    else if (state.compView === 'fronts') drawFronts(ctx);
    else if (state.compView === 'ussl') drawUssl(ctx);
    else if (state.compView === 'wilcox') drawWilcox(ctx);
    else if (state.compView === 'pca') drawPca(ctx);
    else drawWaters(ctx);
    if (still && !plot.hidden && note.textContent) note.textContent += '; on the slider, the axes over the whole run';
  }

  /*
    ONE TIME AT A TIME, ON THE COMPOSITION TAB: the column at the slider's
    stored point -- its waters on the diagram chosen, or an element along
    it -- and play, which moves it on through the run at the Pace chosen,
    as on Against distance. The axes hold still: the triangles and the
    diamond are still of themselves, and the rest are drawn to what every
    stored point of every cell of the run comes to -- the Schoeller's and
    the Stiff's scales, the Durov's pH and dissolved solids, the USSL's
    conductance and SAR, the Wilcox's cations, an element's amounts; the
    principal components are the whole run's waters', each time's put on
    them. Back to At draws the time At gives again, and so does typing it.
  */
  const COMP_PLAYABLE = ['where', 'piper', 'durov', 'schoeller', 'stiff', 'ussl', 'wilcox', 'pca'];
  function compSliding(r) {
    return !!(r && r.model.transport && r.model.fracture > 1 && r.n > 1) && state.compAlong === 'distance'
      && COMP_PLAYABLE.includes(state.compView);
  }
  let compPlaying = null;
  function compStop() {
    if (!compPlaying) return;
    cancelAnimationFrame(compPlaying.raf);
    compPlaying = null;
    $('rtmCompPlay').textContent = 'play';
  }
  function compPlay() {
    if (compPlaying) { compStop(); saveState(); return; }
    const r = state.result;
    if (!compSliding(r)) return;
    // From where the slider is, or from the start where it is at the end or not yet used.
    let i0 = state.compAt === null ? 0 : nearestIndex(r.t, state.compAt);
    if (i0 >= r.n - 1) i0 = 0;
    const p = { i0, wall0: performance.now(), last: -1, raf: 0 };
    compPlaying = p;
    $('rtmCompPlay').textContent = 'pause';
    const frame = (now) => {
      if (compPlaying !== p) return;
      if (state.result !== r) { compStop(); return; }
      let i;
      if (state.compPace === 'points') i = Math.min(r.n - 1, p.i0 + Math.floor(((now - p.wall0) * 30) / 1000));
      else {
        const t = r.t[p.i0] + ((now - p.wall0) / (Number(state.compPace) * 1000)) * (r.t[r.n - 1] - r.t[0]);
        i = t >= r.t[r.n - 1] ? r.n - 1 : nearestIndex(r.t, t);
      }
      if (i !== p.last) {
        p.last = i;
        state.compAt = r.t[i];
        drawComp();
      }
      if (i >= r.n - 1) { compStop(); saveState(); return; }
      p.raf = requestAnimationFrame(frame);
    };
    p.raf = requestAnimationFrame(frame);
  }
  // The slider's row: under a view of the column at one time, its thumb at the time drawn, At's where the slider is not in use.
  function renderCompPlay(r, atIndex) {
    const ok = compSliding(r);
    $('rtmCompPlayRow').hidden = !ok;
    if (!ok) { compStop(); return; }
    const at = $('rtmCompAt');
    at.max = String(r.n - 1);
    at.value = String(atIndex);
    $('rtmCompAtLabel').textContent = state.compAt === null ? 'drag or play' : fmtTime(r.t[atIndex]);
    $('rtmCompPace').value = state.compPace;
    $('rtmCompAll').disabled = state.compAt === null;
    $('rtmCompPlay').textContent = compPlaying ? 'pause' : 'play';
  }
  /*
    What every stored point of every cell of the column comes to, folded
    into one value by `step` from `start` -- an axis's least and greatest --
    kept for the run under `key`, which does not change.
  */
  const compStillCache = new Map();
  function overRun(key, r, layer, start, step) {
    if (compStillCache.has(key)) return compStillCache.get(key);
    const stride = r.model.stride || 1;
    let acc = start;
    for (let i = 0; i < r.n; i++) for (let k = 0; k < r.model.fracture; k++) acc = step(acc, i, k * stride + layer);
    if (compStillCache.size > 200) compStillCache.clear();
    compStillCache.set(key, acc);
    return acc;
  }

  /*
    THE WATER, AS PHREEQC LISTS IT: one cell at one stored point, from the
    model's own speciation, in PHREEQC's blocks and order -- the solution's
    composition, element by element; its description, the pH, pe, Eh,
    temperature, ionic strength, water's activity and charge balance as
    PHREEQC's percent error; the distribution of species, the water's own
    first, then each element, in each valence state where the model tells
    them, every species of it by its molality, activity and activity
    coefficient; the saturation indices, each phase's log IAP and log K at
    the water's temperature beside them; and the minerals, what is on an
    exchanger or a surface, and the gases. The worker works out the activity
    coefficients, the quantities and the phases' constants
    (model.listingAt); the page puts them together.
  */
  const listingCache = new Map();
  let compTextNow = '';
  async function fetchListing(r, index, mc, key) {
    if (listingCache.has(key)) return;
    listingCache.set(key, null);
    const text = (state.ran && state.ran.text) || state.text;
    const ask = (withRun) => request({ type: 'listing', runKey: r.runKey, index, cell: mc,
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      listingCache.set(key, reply);
      if (state.result === r && state.compView === 'listing') drawComp();
    } catch (e) {
      listingCache.delete(key);
      setStatus(`Could not list the water: ${e.message}`, 'error');
    }
  }

  /*
    BESIDE PHREEQC: the same water given to PHREEQC as the PHREEQC tab gives
    a run's -- its element totals, the pH walked onto its [H+], its pe --
    through the database chosen there, and PHREEQC's numbers set beside the
    model's: each species' molality and log gamma, each phase's SI, the
    water's. One stored point goes to the PHREEQC worker, not the run.
  */
  const pqListingCache = new Map();
  async function fetchPqListing(r, atIndex, cell, layer, mc, key) {
    if (pqListingCache.has(key)) return;
    pqListingCache.set(key, null);
    const ns = r.model.nspecies;
    const at = atIndex * r.width;
    const run = { t: Float64Array.of(r.t[atIndex]), states: r.states.slice(at, at + r.width), n: 1, width: r.width, model: r.model,
      temps: r.temps ? r.temps.slice(atIndex * r.model.cells, (atIndex + 1) * r.model.cells) : null };
    const one = layer ? { state: Array.from(r.states.subarray(at + mc * ns, at + (mc + 1) * ns)), label: 'the water' }
      : { cell, k: 0, label: 'the water' };
    try {
      const reply = await pqRequest({ type: 'listing', database: pqDatabase(), run, options: { only: [one] },
        water: pq.fill && pq.water.trim() ? { name: 'The water', text: pq.water } : null,
        modelText: (state.ran && state.ran.text) || state.text });
      pqListingCache.set(key, reply);
    } catch (e) {
      pqListingCache.set(key, { error: e.message });
    }
    if (state.result === r && state.compView === 'listing' && state.compBeside) drawComp();
  }

  /** PHREEQC's numbers for the listing's own, by the model's names, and how far apart the two are. */
  function besidePhreeqc(p, L) {
    const asOf = new Map(L.counted.map((x) => [x.name, x.as]));
    const pqSp = new Map(L.species.map(([n, , m, lg]) => [n, [m, lg]]));
    const sp = new Map();
    const worst = { lm: [0, ''], lg: [0, ''], si: [0, ''] };
    const note = (key, d, what) => { if (Number.isFinite(d) && Math.abs(d) > Math.abs(worst[key][0])) worst[key] = [d, what]; };
    for (const [name, , mol, , lm, , lg] of p.species) {
      const v = asOf.has(name) ? pqSp.get(asOf.get(name)) : null;
      if (!v) continue;
      sp.set(name, v);
      if (mol > 0 && v[0] > 0) note('lm', lm - Math.log10(v[0]), name);
      note('lg', lg - v[1], name);
    }
    const counted = new Set(L.counted.map((x) => x.as));
    const only = L.species.filter(([n, , m]) => !counted.has(n) && n !== 'H2O' && n !== 'e-' && m > 0)
      .sort((a, b) => b[2] - a[2]).map(([n, , m, lg]) => [n, m, lg]);
    const si = new Map();
    for (const [name, s] of p.si) {
      const hit = L.phases.find(([n, page]) => n === name || page === name);
      if (!hit) continue;
      si.set(name, hit[2]);
      note('si', s - hit[2], name);
    }
    const desc = new Map([['pH', L.pH], ['pe', L.pe], ['Temperature', L.tc], ['Ionic strength', L.mu], ['Activity of water', L.aw],
      ['Percent error, 100*(Cat-|An|)/(Cat+|An|)', L.percent]].filter(([, v]) => Number.isFinite(v)));
    // What is dissolved and the database has no species for; a mineral, an exchanger or a surface is never the water's.
    const left = [...L.unmapped];
    return { db: L.database, version: L.version, sp, only, si, desc, worst, left };
  }

  /** The listing's parts, from the run and what the worker worked out: each a head and its rows, numbers as they are. */
  function listingParts(r, got, atIndex, mc) {
    const m = r.model;
    const C = compositionOf(m);
    const ns = m.nspecies;
    const base = atIndex * r.width + mc * ns;
    const conc = (k) => r.states[base + k];
    const qv = (key) => { const i = m.quantities.findIndex((x) => x.key === key); return i >= 0 ? got.values[i] : null; };
    const solutes = (m.solutes || []).map((nm) => m.species.indexOf(nm)).filter((k) => k >= 0);
    const row = (k, group) => {
      const mol = conc(k);
      const lg = got.lnG[k] / Math.LN10;
      return [m.species[k], group, mol, mol * 10 ** lg, mol > 0 ? Math.log10(mol) : null, mol > 0 ? Math.log10(mol) + lg : null, lg];
    };
    const byMolality = (a, b) => conc(b) - conc(a);
    // The water's own, made of H and O alone: H+ and OH- first, as PHREEQC lists them; H2 and O2 as H(0) and O(0).
    const madeOf = (k) => {
      const made = typeof RtmModel !== 'undefined' && RtmModel.elementsOf ? RtmModel.elementsOf(m.species[k]) : null;
      return made ? [...made] : null;
    };
    const groups = [];
    const own = [];
    const inGroups = new Set();
    for (const k of solutes) {
      const made = madeOf(k);
      if (!made || !made.every(([el]) => el === 'H' || el === 'O')) continue;
      inGroups.add(k);
      if (made.length === 1 && !/[+-]/.test(m.species[k])) {
        const [el, n] = made[0];
        groups.push({ name: `${el}(0)`, total: n * conc(k), ks: [k] });
      } else own.push(k);
    }
    // Each element dissolved, in each of its valence states where the model tells two or more of them.
    for (const e of C.elements) {
      const water = e.terms.filter((tm) => tm[2] === 'water');
      if (!water.length) continue;
      const states = [...new Set(water.map((tm) => tm[3]))];
      const split = states.length > 1 && states.every((v) => v !== null && v !== undefined);
      const parts = split ? [...states].sort((a, b) => a - b).map((v) => [`${e.el}(${Number(v.toFixed(3))})`, water.filter((tm) => tm[3] === v)])
        : [[e.el, water]];
      for (const [name, terms] of parts) {
        let total = 0;
        for (const [k, n] of terms) total += n * conc(k);
        const ks = [...new Set(terms.map((tm) => tm[0]))];
        ks.forEach((k) => inGroups.add(k));
        groups.push({ name, total, ks });
      }
    }
    groups.sort((a, b) => a.name.localeCompare(b.name, 'en'));
    const others = solutes.filter((k) => !inGroups.has(k));
    const species = [...own.sort(byMolality).map((k) => row(k, '')),
      ...groups.flatMap((g) => g.ks.sort(byMolality).map((k) => row(k, g.name))),
      ...others.sort(byMolality).map((k) => row(k, 'other'))];
    const composition = C.elements.map((e) => {
      let total = 0;
      for (const [k, n, where] of e.terms) if (where === 'water') total += n * conc(k);
      return [e.el, total];
    }).filter(([, v]) => v > 0).sort((a, b) => a[0].localeCompare(b[0], 'en'));
    // PHREEQC's words for them, and the figures it prints them to.
    const description = [
      ['pH', qv('pH'), ''], ['pe', qv('pe'), ''], ['Eh', qv('Eh'), 'V'], ['Temperature', got.tc, '°C'],
      ['Ionic strength', qv('I'), 'mol/kgw'], ['Activity of water', qv('a(H2O)'), ''], ['Carbonate alkalinity', qv('alk(CO3)'), 'eq/kgw'],
      ['Specific conductance', qv('SC'), 'µS/cm'], ['Density', qv('rho'), 'kg/L'], ['Viscosity', qv('viscos'), 'mPa s'],
      ['Percent error, 100*(Cat-|An|)/(Cat+|An|)', qv('charge'), ''],
    ].filter(([, v]) => v !== null && Number.isFinite(v));
    const si = got.phases.map((p) => [p.name, p.logIAP - p.logK, p.logIAP, p.logK]).sort((a, b) => a[0].localeCompare(b[0], 'en'));
    const siOf = new Map(si.map((x) => [x[0], x[1]]));
    const where = (kind) => [...new Set(C.elements.flatMap((e) => e.terms.filter((tm) => tm[2] === kind).map((tm) => tm[0])))];
    const minerals = where('mineral').map((k) => [m.species[k], conc(k), siOf.has(m.species[k]) ? siOf.get(m.species[k]) : null])
      .sort((a, b) => a[0].localeCompare(b[0], 'en'));
    const shareRows = (kind) => where(kind).sort(byMolality).map((k) => [m.species[k], conc(k), qv(`share(${m.species[k]})`)]);
    const gases = m.quantities.filter((x) => /^p\(/.test(x.key)).map((x) => [x.key.slice(2, -1), qv(x.key)]);
    return { species, composition, description, si, minerals, exchange: shareRows('exchange'), surface: shareRows('surface'), gases,
      groupTotals: new Map(groups.map((g) => [g.name, g.total])) };
  }

  // PHREEQC's way with a block's title: centred in a line of dashes.
  const listingBar = (title) => {
    const left = Math.floor((79 - title.length) / 2);
    return `${'-'.repeat(left)}${title}${'-'.repeat(79 - left - title.length)}`;
  };
  // As PHREEQC prints its numbers: 1.234e-05, two figures to the exponent; and fixed.
  const lsE = (v) => (v === null || !Number.isFinite(v) ? '' : v.toExponential(3).replace(/e([+-])(\d)$/, 'e$10$2'));
  const lsF = (v, d = 3) => (v === null || !Number.isFinite(v) ? '' : v.toFixed(d));
  const LISTING_FIGURES = { Temperature: 2, 'Specific conductance': 0, Density: 5, Viscosity: 4, 'Percent error, 100*(Cat-|An|)/(Cat+|An|)': 2,
    'Ionic strength': 'e', 'Carbonate alkalinity': 'e', Eh: 4 };
  const lsDesc = (label, v) => {
    const f = LISTING_FIGURES[label];
    return f === 'e' ? lsE(v) : lsF(v, f === undefined ? 3 : f);
  };

  /** The listing as PHREEQC prints it, to compare line by line. */
  function listingText(title, p) {
    const out = [title, ''];
    // In a unit chosen, a column after PHREEQC's own (listingUnit).
    const U = p.unit || null;
    out.push(listingBar('Solution composition'), '', `\t${'Elements'.padEnd(15)}${'Molality'.padStart(12)}${U ? U.head.padStart(16) : ''}`, '');
    for (const [el, v] of p.composition) out.push(`\t${el.padEnd(15)}${lsE(v).padStart(12)}${U ? lsE(U.el(el, v)).padStart(16) : ''}`);
    out.push('', listingBar('Description of solution'), '');
    const B = p.pq;
    for (const [label, v, unit] of p.description) {
      const theirs = B && B.desc.has(label) ? `${''.padStart(4)}PHREEQC ${lsDesc(label, B.desc.get(label))}` : '';
      out.push(`${`${label}${unit ? ` (${unit})` : ''}`.padStart(45)}  =  ${lsDesc(label, v).padEnd(10)}${theirs}`.trimEnd());
    }
    out.push('', listingBar('Distribution of species'), '',
      `${''.padEnd(43)}${'Log'.padStart(10)}${'Log'.padStart(10)}${'Log'.padStart(10)}`,
      `   ${'Species'.padEnd(15)}${'Molality'.padStart(12)}${'Activity'.padStart(12)}${'Molality'.padStart(10)}${'Activity'.padStart(10)}${'Gamma'.padStart(10)}`
        + (U ? U.head.padStart(16) : '')
        + (B ? `${'PHREEQC m'.padStart(12)}${'PHREEQC lg'.padStart(11)}${'d log m'.padStart(10)}` : ''), '');
    let group = null;
    for (const [sp, g, mol, a, lm, la, lg] of p.species) {
      if (g !== group) {
        group = g;
        if (g) {
          const tot = p.groupTotals.get(g);
          out.push(`${g.padEnd(14)}${tot === undefined ? '' : lsE(tot)}${U && tot !== undefined && g !== 'other' ? `  ${lsE(U.el(g, tot))}` : ''}`);
        }
      }
      const v = B ? B.sp.get(sp) : null;
      out.push(`   ${sp.padEnd(15)}${lsE(mol).padStart(12)}${lsE(a).padStart(12)}${lsF(lm).padStart(10)}${lsF(la).padStart(10)}${lsF(lg).padStart(10)}`
        + (U ? lsE(U.sp(sp, mol)).padStart(16) : '')
        + (B ? (v ? `${lsE(v[0]).padStart(12)}${lsF(v[1]).padStart(11)}${lsE(mol > 0 && v[0] > 0 ? lm - Math.log10(v[0]) : null).padStart(10)}`
          : `${'not given'.padStart(12)}`) : ''));
    }
    if (p.si.length) {
      out.push('', listingBar('Saturation indices'), '', `  ${'Phase'.padEnd(18)}${'SI'.padStart(7)}${'log IAP'.padStart(10)}${'log K'.padStart(9)}`
        + (B ? `${'PHREEQC SI'.padStart(12)}${'d SI'.padStart(10)}` : ''), '');
      for (const [ph, s, iap, k] of p.si) {
        const v = B && B.si.has(ph) ? B.si.get(ph) : null;
        out.push(`  ${ph.padEnd(18)}${lsF(s, 2).padStart(7)}${lsF(iap, 2).padStart(10)}${lsF(k, 2).padStart(9)}`
          + (B ? (v === null ? `${'none'.padStart(12)}` : `${lsF(v, 2).padStart(12)}${lsE(s - v).padStart(10)}`) : ''));
      }
    }
    if (p.minerals.length) {
      out.push('', listingBar('Minerals'), '', `  ${'Mineral'.padEnd(18)}${'Amount'.padStart(12)}${'SI'.padStart(8)}`, '');
      for (const [mn, v, s] of p.minerals) out.push(`  ${mn.padEnd(18)}${lsE(v).padStart(12)}${lsF(s, 2).padStart(8)}`);
    }
    for (const [title2, rows, third] of [['Exchange composition', p.exchange, 'Equiv. fraction'], ['Surface composition', p.surface, 'Share of sites']]) {
      if (!rows.length) continue;
      out.push('', listingBar(title2), '', `  ${'Species'.padEnd(18)}${'Amount'.padStart(12)}${third.padStart(17)}`, '');
      for (const [sp, v, sh] of rows) out.push(`  ${sp.padEnd(18)}${lsE(v).padStart(12)}${lsE(sh).padStart(17)}`);
    }
    if (p.gases.length) {
      out.push('', listingBar('Gases'), '', `  ${'Gas'.padEnd(18)}${'Pressure (atm)'.padStart(16)}`, '');
      for (const [g, v] of p.gases) out.push(`  ${g.padEnd(18)}${lsE(v).padStart(16)}`);
    }
    if (B && B.only.length) {
      out.push('', listingBar("Only in PHREEQC's speciation"), '', `   ${'Species'.padEnd(15)}${'Molality'.padStart(12)}${'Log Gamma'.padStart(11)}`, '');
      for (const [sp, m2, lg2] of B.only) out.push(`   ${sp.padEnd(15)}${lsE(m2).padStart(12)}${lsF(lg2).padStart(11)}`);
    }
    return `${out.join('\n')}\n`;
  }

  function drawListing({ r, plot, cell, layer, atIndex, fail, note }) {
    Plotly.purge(plot);
    plot.hidden = true;
    const box = $('rtmCompListing');
    const mc = modelCell(cell, layer);
    const key = `${r.runKey}|${atIndex}|${mc}`;
    const got = listingCache.get(key);
    if (!got) {
      fetchListing(r, atIndex, mc, key);
      fail(`Working out the water of cell ${cell} at ${fmtTime(r.t[atIndex])}…`);
      return;
    }
    const m = r.model;
    const p = listingParts(r, got, atIndex, mc);
    const u = shownUnit(r);
    p.unit = listingUnit(r, u);
    const U = p.unit;
    // Beside PHREEQC: its numbers once it has them, through the database the PHREEQC tab has chosen.
    let pqSaid = '';
    if (state.compBeside) {
      const db = pqDatabase();
      const key2 = `${key}|${db ? db.name : 'phreeqc.dat'}|${pq.fill && pq.water.trim() ? 'fill' : ''}`;
      const L = pqListingCache.get(key2);
      if (L && L.error) pqSaid = `PHREEQC could not take this water: ${L.error}`;
      else if (L) {
        p.pq = besidePhreeqc(p, L);
        const w = p.pq.worst;
        pqSaid = `beside PHREEQC (${L.database}, ${L.version}): the species within ${Math.abs(w.lm[0]).toExponential(1)} in log molality`
          + `${w.lm[1] ? ` (${w.lm[1]})` : ''} and ${Math.abs(w.lg[0]).toExponential(1)} in log gamma${w.lg[1] ? ` (${w.lg[1]})` : ''}`
          + `${p.si.length ? `, the SI within ${Math.abs(w.si[0]).toExponential(1)}${w.si[1] ? ` (${w.si[1]})` : ''}` : ''}`
          + `${p.pq.left.length ? `; not given to PHREEQC, which has no such species: ${p.pq.left.join(', ')}` : ''}`;
      } else {
        fetchPqListing(r, atIndex, cell, layer, mc, key2);
        pqSaid = 'PHREEQC is working out the same water…';
      }
    }
    const B = p.pq || null;
    const where = `cell ${cell}${m.centres ? ` (${m.centres[cell].toExponential(2)} m)` : ''}${layer ? `, rock layer ${layer}` : ''}`;
    const title = `The water of ${where} at ${fmtTime(r.t[atIndex])}`;
    const td = (v, kind) => `<td>${esc(kind === 'e' ? lsE(v) : kind === '2' ? lsF(v, 2) : kind === 't' ? String(v) : lsF(v))}</td>`;
    const table = (head, rows, kinds) => `<table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>`
      + rows.map((rw) => `<tr>${rw.map((v, i) => td(v, kinds[i])).join('')}</tr>`).join('') + '</tbody></table>';
    let html = `<h4 class="rtm-listing-title">${esc(title)}</h4>`;
    html += '<h4>Solution composition</h4>' + table(['Element', 'Molality', ...(U ? [U.head] : [])],
      U ? p.composition.map(([el, v]) => [el, v, U.el(el, v)]) : p.composition, ['t', 'e', 'e']);
    html += '<h4>Description of solution</h4>' + table(['', 'Value', 'Unit', ...(B ? ['PHREEQC'] : [])],
      p.description.map(([label, v, unit]) => [label, lsDesc(label, v), unit,
        ...(B ? [B.desc.has(label) ? lsDesc(label, B.desc.get(label)) : ''] : [])]), ['t', 't', 't', 't']);
    let body = '';
    let group = null;
    for (const [sp, g, mol, a, lm, la, lg] of p.species) {
      if (g !== group) {
        group = g;
        if (g) {
          body += `<tr class="rtm-listing-group"><td>${esc(g)}</td><td>${esc(g === 'other' ? '' : lsE(p.groupTotals.get(g)))}</td>`
            + `${'<td></td>'.repeat(4)}${U ? `<td>${esc(g === 'other' ? '' : lsE(U.el(g, p.groupTotals.get(g))))}</td>` : ''}`
            + `${B ? '<td></td>'.repeat(3) : ''}</tr>`;
        }
      }
      const v = B ? B.sp.get(sp) : null;
      body += `<tr><td class="rtm-listing-sp">${esc(sp)}</td>${td(mol, 'e')}${td(a, 'e')}${td(lm)}${td(la)}${td(lg)}`
        + (U ? td(U.sp(sp, mol), 'e') : '')
        + (B ? (v ? `${td(v[0], 'e')}${td(v[1])}${td(mol > 0 && v[0] > 0 ? lm - Math.log10(v[0]) : null, 'e')}`
          : '<td>not given</td><td></td><td></td>') : '') + '</tr>';
    }
    html += '<h4>Distribution of species</h4><table><thead><tr><th>Species</th><th>Molality</th><th>Activity</th><th>Log molality</th>'
      + `<th>Log activity</th><th>Log gamma</th>${U ? `<th>${esc(U.head)}</th>` : ''}`
      + `${B ? '<th>PHREEQC molality</th><th>PHREEQC log gamma</th><th>Δ log molality</th>' : ''}`
      + `</tr></thead><tbody>${body}</tbody></table>`;
    const siRows = p.si.map(([ph, s, iap, k]) => [ph, s, iap, k, ...(B ? (B.si.has(ph) ? [B.si.get(ph), s - B.si.get(ph)] : [null, null]) : [])]);
    if (p.si.length) {
      html += '<h4>Saturation indices</h4>' + table(['Phase', 'SI', 'log IAP', 'log K', ...(B ? ['PHREEQC SI', 'Δ SI'] : [])], siRows,
        ['t', '2', '2', '2', '2', 'e']);
    }
    if (p.minerals.length) html += '<h4>Minerals</h4>' + table(['Mineral', 'Amount', 'SI'], p.minerals, ['t', 'e', '2']);
    if (p.exchange.length) html += '<h4>Exchange composition</h4>' + table(['Species', 'Amount', 'Equivalent fraction'], p.exchange, ['t', 'e', 'e']);
    if (p.surface.length) html += '<h4>Surface composition</h4>' + table(['Species', 'Amount', 'Share of its sites'], p.surface, ['t', 'e', 'e']);
    if (p.gases.length) html += '<h4>Gases</h4>' + table(['Gas', 'Partial pressure (atm)'], p.gases, ['t', 'e']);
    if (B && B.only.length) {
      html += '<h4>Only in PHREEQC\'s speciation</h4>' + table(['Species', 'Molality', 'Log gamma'], B.only, ['t', 'e', 'f']);
    }
    box.innerHTML = html;
    box.hidden = false;
    $('rtmCompEmpty').hidden = true;
    const name = `${fileStem()}_water_cell${cell}${layer ? `_layer${layer}` : ''}`;
    const withPq = (rw) => {
      const v = B ? B.sp.get(rw[0]) : null;
      return [...rw, ...(U ? [U.sp(rw[0], rw[2])] : []),
        ...(B ? (v ? [v[0], v[1], rw[2] > 0 && v[0] > 0 ? rw[4] - Math.log10(v[0]) : null] : [null, null, null]) : [])];
    };
    compTableNow = { head: ['species', 'in', 'molality', 'activity', 'log molality', 'log activity', 'log gamma', ...(U ? [U.head] : []),
      ...(B ? ['PHREEQC molality', 'PHREEQC log gamma', 'log molality, the model less PHREEQC'] : [])], name,
      rows: p.species.map((rw) => withPq(rw.map((v) => (v === undefined ? null : v)))),
      extra: [
        { name: 'composition', head: ['element', 'molality', ...(U ? [U.head] : [])],
          rows: U ? p.composition.map(([el, v]) => [el, v, U.el(el, v)]) : p.composition },
        { name: 'description', head: ['', 'value', 'unit', ...(B ? ['PHREEQC'] : [])],
          rows: p.description.map(([label, v, unit]) => [label, v, unit, ...(B ? [B.desc.has(label) ? B.desc.get(label) : null] : [])]) },
        ...(p.si.length ? [{ name: 'saturation indices', head: ['phase', 'SI', 'log IAP', 'log K',
          ...(B ? ['PHREEQC SI', 'SI, the model less PHREEQC'] : [])], rows: siRows }] : []),
        ...(B && B.only.length ? [{ name: 'only in PHREEQC', head: ['species', 'molality', 'log gamma'], rows: B.only }] : []),
        ...(p.minerals.length ? [{ name: 'minerals', head: ['mineral', 'amount', 'SI'], rows: p.minerals }] : []),
        ...(p.exchange.length ? [{ name: 'exchange', head: ['species', 'amount', 'equivalent fraction'], rows: p.exchange }] : []),
        ...(p.surface.length ? [{ name: 'surface', head: ['species', 'amount', 'share of its sites'], rows: p.surface }] : []),
        ...(p.gases.length ? [{ name: 'gases', head: ['gas', 'partial pressure (atm)'], rows: p.gases }] : []),
      ] };
    compTextNow = listingText(title, p);
    note.textContent = `${title}; ${p.species.length} lines of species, ${p.si.length} phases${U && U.none.length
      ? `; no ${U.head}: ${U.none.join(', ')}, no formula mass` : ''}${u.why ? `; ${u.why}` : ''}${pqSaid ? `; ${pqSaid}` : ''}`;
  }

  /**
   * The listing's column in the unit chosen (shownUnit), or null in the
   * model's own: { head, el(name, v), sp(name, v), none } -- an element's
   * total, or a valence state's, by the element's atomic weight, a species
   * by its formula mass; none the species that have none, blank.
   */
  function listingUnit(r, u) {
    if (!u.id) return null;
    const none = [];
    const head = u.bare ? `Molality ${u.text}` : u.text;
    const times = (v, f) => (f === null || v === null || v === undefined || !Number.isFinite(v) ? null : v * f);
    const el = (name, v) => {
      if (!u.mass) return times(v, u.scale);
      const w = RtmModel.ATOMIC_WEIGHTS[String(name).replace(/\(.*$/, '')];
      return times(v, w ? u.scale * w : null);
    };
    const sp = (name, v) => {
      const sh = shownAs(r, name, u);
      if (!(sh && sh.f)) { if (!none.includes(name)) none.push(name); return null; }
      return times(v, sh.f);
    };
    return { head, el, sp, none };
  }

  /*
    A BUDGET OVER THE RUN, of an element or of one species: what the column
    holds of it at each stored time, in the water, on an exchanger or a
    surface, in each mineral and in the rock, stacked, with what has gone
    out at the right-hand end on top; beside it, dashed, what was there at
    the start with what has come in at the left -- the gap between them what
    the reactions made of it, drawn dotted on its own. The worker weighs and
    sums it (rtmBudget); a run whose element no reaction makes or takes
    closes to the solver's tolerance and the summing over the stored points.
  */
  const budgetCache = new Map();
  /**
   * What holding put in, of a budget the worker kept (rtmBudget): { put, names } -- put at each stored point since the
   * start, names the held species it was of, those it made up for most first; null where it put in nothing.
   */
  function holdingOf(got) {
    if (!got || !got.byHolding || !got.byHolding.some((v) => v !== 0)) return null;
    const by = got.heldBy || [];
    const some = by.filter((h) => h.put !== 0);
    const names = (some.length ? some : by).map((h) => labelOf(h.name));
    return { put: got.byHolding, names: names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` };
  }
  async function fetchBudget(r, of, key) {
    if (budgetCache.has(key)) return;
    budgetCache.set(key, null);
    // The text the run was made with: the run on show's, or the kept run's own.
    const h = holderOf(r);
    const text = h && h !== current ? h.text : ((state.ran && state.ran.text) || state.text);
    const ask = (withRun) => request({ type: 'budget', runKey: r.runKey, of,
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      budgetCache.set(key, reply);
    } catch (e) {
      budgetCache.set(key, { error: e.message });
    }
    if (state.result === r && state.compView === 'budget') drawComp();
    // What has come out of the column, under Against time, where it is shown; else when its tab is.
    if (state.btc && state.tab === 'time') drawTime();
  }

  /*
    THE RUN'S BALANCE, EVERY ELEMENT AT ONCE: of each element the budget
    keeps (rtmBudget, one each) what the column held at the start, what came
    in and went out, what it holds at the end and what the reactions made of
    it, and how far its balance is from closing -- the most the reactions
    made of it at any stored point, as a share of the most the column held or
    was given -- the budget's own measure. Below 1e-4 it closes, to the
    solver's tolerance and the summing over the stored points; above, a
    reaction makes or takes it: a decay, a source. Drawn as a bar each, on a
    log axis.
  */
  const BUDGET_ALL = 'all:';
  function drawBudgetAll({ r, plot, fail, note }, els) {
    const keys = els.map((el) => `${r.runKey}|element|${el}`);
    const got = keys.map((key) => budgetCache.get(key));
    const coming = [];
    got.forEach((g, q) => { if (g === undefined || g === null) { coming.push(els[q]); if (g === undefined) fetchBudget(r, { kind: 'element', name: els[q] }, keys[q]); } });
    if (coming.length) { fail(`Working out the budget of every element: ${els.length - coming.length} of ${els.length}…`); return; }
    const bad = got.find((g) => g.error);
    if (bad) { fail(`A budget could not be kept: ${bad.error}`); return; }
    const last = r.n - 1;
    const rows = els.map((el, q) => {
      const g = got[q];
      // What holding put in, beside what came in: given to the column all the same.
      const hold = holdingOf(g);
      let scale = 0;
      let off = 0;
      for (let i = 0; i <= last; i++) {
        scale = Math.max(scale, Math.abs(g.total[i]), Math.abs(g.total[0] + g.cumIn[i] + (hold ? hold.put[i] : 0)));
        off = Math.max(off, Math.abs(g.byReactions[i]));
      }
      const rel = scale > 0 ? off / scale : 0;
      return { el, start: g.total[0], cin: g.cumIn[last], gone: g.cumOut[last], end: g.total[last], made: g.byReactions[last], rel,
        held: hold ? hold.put[last] : null, heldBy: hold ? hold.names : '', closes: rel < 1e-4, transport: g.transport };
    });
    const transport = rows.some((x) => x.transport);
    const anyHeld = rows.some((x) => x.held !== null);
    const c = themeColors();
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.type = 'log';
    layout.xaxis.title = { text: 'the most the reactions made or took of it, as a share of the most the column held or was given', font: { size: 11 } };
    layout.yaxis.type = 'category';
    layout.yaxis.autorange = 'reversed';
    layout.yaxis.automargin = true;
    layout.height = Math.max(260, 26 * rows.length + 110);
    // A balance that closes to the last digit has nothing to draw on a log axis: drawn at the floor, 1e-17.
    const floor = 1e-17;
    Plotly.react(plot, [{ type: 'bar', orientation: 'h', y: rows.map((x) => x.el), x: rows.map((x) => Math.max(x.rel, floor)),
      marker: { color: rows.map((x) => (x.closes ? '#3b82c4' : '#e0663e')) }, showlegend: false,
      text: rows.map((x) => (x.rel > 0 ? x.rel.toExponential(1) : '0')), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{y}: %{text}<extra></extra>' }], {
      ...layout,
      shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: 1e-4, x1: 1e-4, y0: 0, y1: 1, line: { color: c.text, width: 1, dash: 'dot' } }],
    }, PLOT_CONFIG);
    const num = (v) => (v === null || v === undefined || !Number.isFinite(v) ? '' : esc(v === 0 ? '0' : fit4(v)));
    const td = (v, text = num(v)) => `<td${v === null || v === undefined || !Number.isFinite(v) ? '' : ` data-v="${v}"`}>${text}</td>`;
    const box = $('rtmCompLines');
    box.innerHTML = `<table><thead><tr><th>Every element</th><th>there at the start</th>${transport ? '<th>came in at the left</th>'
      + '<th>went out at the right</th>' : ''}<th>there at the end</th><th>made by reactions, net</th>${anyHeld ? '<th>put in by holding</th>' : ''}`
      + '<th>off its balance</th><th></th></tr></thead><tbody>'
      + rows.map((x) => `<tr><td>${esc(x.el)}</td>${td(x.start)}${transport ? `${td(x.cin)}${td(x.gone)}` : ''}${td(x.end)}${td(x.made)}`
        + `${anyHeld ? td(x.held) : ''}`
        + `${td(x.rel, x.rel > 0 ? esc(x.rel.toExponential(1)) : '0')}<td>${x.closes ? 'closes' : 'made or taken by reactions'}</td></tr>`).join('')
      + '</tbody></table>'
      + `<p>Amounts ${transport ? "per m² of the water's cross-section, concentration × m" : 'per kg of water'}. Off its balance: the most the `
      + 'reactions made or took of it at any stored time, as a share of the most the column held or was given. Below 1e-4 the '
      + 'balance closes, to the solver\'s tolerance and the summing of the ends\' fluxes over the stored points; above, a reaction '
      + 'makes or takes it — a decay, a source.'
      + (anyHeld ? ' Put in by holding: what the reactions took of a species held, less what they made of it, made up for to keep it '
        + 'where it is, the reactions\' own part counted apart.' : '') + '</p>';
    box.hidden = false;
    const made = rows.filter((x) => !x.closes);
    const worst = rows.filter((x) => x.closes).reduce((b, x) => (b === null || x.rel > b.rel ? x : b), null);
    const heldRows = rows.filter((x) => x.held !== null && x.held !== 0);
    note.textContent = [`${rows.length} element${rows.length === 1 ? '' : 's'}`,
      worst ? `${rows.length - made.length} close, the worst ${worst.el} at ${worst.rel > 0 ? worst.rel.toExponential(1) : '0'}` : '',
      made.length ? `made or taken by reactions: ${made.map((x) => `${x.el} (${fmtNumber(x.made)})`).join(', ')}` : 'no reaction makes or takes any',
      heldRows.length ? `put in by holding: ${heldRows.map((x) => `${x.el} (${fmtNumber(x.held)}, by holding ${x.heldBy})`).join(', ')}` : '']
      .filter(Boolean).join('; ');
    compTableNow = { head: ['element', 'there at the start', ...(transport ? ['came in at the left', 'went out at the right'] : []),
      'there at the end', 'made by reactions, net', ...(anyHeld ? ['put in by holding'] : []), 'off its balance', 'closes'],
    name: `${fileStem()}_budget_every_element`,
    rows: rows.map((x) => [x.el, x.start, ...(transport ? [x.cin, x.gone] : []), x.end, x.made, ...(anyHeld ? [x.held] : []), x.rel,
      x.closes ? 'yes' : 'no']) };
  }

  /** What a budget can be of: every element a species holds, then every species. */
  function budgetChoices(m) {
    const C = compositionOf(m);
    const els = C ? C.elements.filter((e) => e.terms.length).map((e) => e.el) : [];
    const sp = ((m && m.species) || []).filter((nm) => nm !== 'e-');
    return { els, sp };
  }

  function drawBudget({ r, plot, fail, note }) {
    const { els, sp } = budgetChoices(r.model);
    if (state.compBudgetOf === BUDGET_ALL && els.length) { drawBudgetAll({ r, plot, fail, note }, els); return; }
    let chosen = state.compBudgetOf;
    if (!chosen || !(els.includes(chosen.replace(/^element:/, '')) && chosen.startsWith('element:')
      || sp.includes(chosen.replace(/^species:/, '')) && chosen.startsWith('species:'))) {
      chosen = els.length ? `element:${els[0]}` : `species:${sp[0]}`;
    }
    const kind = chosen.startsWith('species:') ? 'species' : 'element';
    const name = chosen.slice(kind.length + 1);
    const key = `${r.runKey}|${kind}|${name}`;
    // Where an element goes, from species to species over the run.
    if (state.compBudgetBy === 'flows' && kind === 'element') {
      drawBudgetFlows({ r, plot, fail, note }, name);
      return;
    }
    // By each reaction: each <REACTIONS> line's part of what the reactions made of it.
    if (state.compBudgetBy === 'lines' && (r.model.quantities || []).some((q) => q.group === 'reactions')) {
      drawBudgetLines({ r, plot, fail, note }, kind, name, key);
      return;
    }
    const got = budgetCache.get(key);
    if (got === undefined || got === null) {
      fetchBudget(r, { kind, name }, key);
      fail(`Working out the budget of ${name}…`);
      return;
    }
    if (got.error) { fail(`The budget of ${name} could not be kept: ${got.error}`); return; }
    const pick = compTimeIndices(r);
    const idx = pick.idx;
    if (!idx.length) { fail(`Nothing is stored after ${fmtTime(compFrom())}: lower the "from" time.`); return; }
    const c = themeColors();
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22', '#17becf'];
    const xs = idx.map((i) => showT(r.t[i]));
    const traces = got.bands.map((b, q) => ({ type: 'scatter', mode: 'lines', name: b.name, x: xs, y: idx.map((i) => b.values[i]),
      stackgroup: 'held', line: { width: 0.6, color: palette[q % palette.length] } }));
    const anyOut = got.transport && got.cumOut.some((v) => v !== 0);
    if (anyOut) {
      traces.push({ type: 'scatter', mode: 'lines', name: 'gone out at the right-hand end', x: xs, y: idx.map((i) => got.cumOut[i]),
        stackgroup: 'held', line: { width: 0.6, color: '#7f7f7f' } });
    }
    const n = r.n;
    const supplied = Float64Array.from(got.cumIn, (v) => got.total[0] + v);
    traces.push({ type: 'scatter', mode: 'lines', name: got.transport ? 'there at the start, and come in at the left' : 'there at the start',
      x: xs, y: idx.map((i) => supplied[i]), line: { color: c.text, dash: 'dash', width: 1.6 } });
    traces.push({ type: 'scatter', mode: 'lines', name: 'made by reactions, net', x: xs, y: idx.map((i) => got.byReactions[i]),
      line: { color: c.text, dash: 'dot', width: 1.6 } });
    // What holding put in, a species held being kept where it is whatever the reactions take or make of it.
    const hold = holdingOf(got);
    if (hold) {
      traces.push({ type: 'scatter', mode: 'lines', name: `put in by holding ${hold.names}`, x: xs, y: idx.map((i) => hold.put[i]),
        line: { color: c.text, dash: 'dashdot', width: 1.6 } });
    }
    const layout = baseLayout();
    layout.xaxis.type = pick.logT ? 'log' : 'linear';
    layout.xaxis.title = { text: `time (${shownTime().sym})`, font: { size: 11 } };
    layout.yaxis.title = { text: got.transport ? "amount, concentration × m per m² of the water's cross-section" : 'amount per kg of water',
      font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    // What the note says: where it is at the end, what crossed the ends, and what the reactions made of it.
    const last = n - 1;
    const fmt = (v) => fmtNumber(v);
    const where = got.bands.filter((b) => b.values[last] !== 0)
      .map((b) => `${fmt(b.values[last])} ${b.name}${got.total[last] > 0 ? ` (${(100 * b.values[last] / got.total[last]).toFixed(1)} %)` : ''}`);
    let scale = 0;
    for (let i = 0; i < n; i++) scale = Math.max(scale, Math.abs(supplied[i] + (hold ? hold.put[i] : 0)), Math.abs(got.total[i]));
    let off = 0;
    for (let i = 0; i < n; i++) off = Math.max(off, Math.abs(got.byReactions[i]));
    const rel = scale > 0 ? off / scale : 0;
    const heldPut = hold ? hold.put[last] : 0;
    note.textContent = `${name}${kind === 'species' ? '' : ', all of it'} at the end: ${where.join(', ') || 'none in the column'}`
      + `${got.transport ? `; ${fmt(got.cumIn[last])} came in at the left and ${fmt(got.cumOut[last])} went out at the right` : ''}`
      + (hold ? `; ${heldPut >= 0 ? 'put in' : 'taken out'} by holding ${hold.names}, ${fmt(Math.abs(heldPut))} by the end` : '')
      + (rel < 1e-4 ? `; no reaction makes or takes any to speak of: what is left over, at most ${off.toExponential(1)}, ${rel.toExponential(1)}`
        + ` of what was there${hold ? ', came in and was put in' : ' and came in'}, is the solver's and the summing over the stored points'`
        : `; made by reactions, net, ${fmt(got.byReactions[last])} by the end`);
    const unit = shownTime().sym;
    compTableNow = { head: [`t (${unit})`, ...got.bands.map((b) => b.name), ...(anyOut ? ['gone out at the right-hand end'] : []),
      ...(got.transport ? ['come in at the left-hand end'] : []), 'made by reactions, net',
      ...(hold ? [`put in by holding ${hold.names}`] : []), 'in the column, all of it'],
    name: `${fileStem()}_budget_${name.replace(/[^\w.-]+/g, '_')}`,
    rows: Array.from({ length: n }, (_, i) => [showT(r.t[i]), ...got.bands.map((b) => b.values[i]), ...(anyOut ? [got.cumOut[i]] : []),
      ...(got.transport ? [got.cumIn[i]] : []), got.byReactions[i], ...(hold ? [hold.put[i]] : []), got.total[i]]) };
  }

  /*
    A BUDGET BY EACH REACTION: what the reactions made of it, line by line.
    Each <REACTIONS> line's rate of making it and of taking it at each
    stored point, over the whole column or in one cell -- the worker works
    each out as the derivative does (rtmLines) -- stacked, what the lines
    make above nought and what they take below, the lines that move most of
    it named and the rest together, and made less taken by every line
    dotted. Under the chart, over the run, what each line made and took, its
    rate summed over the stored points. Over the whole column, what no line
    accounts for -- what the budget counts the reactions as having made less
    what the lines did -- relation by relation where the model has relations
    (rtmRelations): each one's part, read off the balance of a species of its
    own, and what is left the summing's error.
  */
  const linesCache = new Map();
  const LINES_NAMED = 8;
  /** A reply of the worker's for run r, kept in `cache` under `key`: asked for once, and asked again with the run if it has another. */
  async function fetchKept(cache, r, message, key) {
    if (cache.has(key)) return;
    cache.set(key, null);
    const h = holderOf(r);
    const text = h && h !== current ? h.text : ((state.ran && state.ran.text) || state.text);
    const ask = (withRun) => request({ ...message, runKey: r.runKey,
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      cache.set(key, reply);
    } catch (e) {
      cache.set(key, { error: e.message });
    }
    if (state.result === r && state.compView === 'budget') drawComp();
  }

  function drawBudgetLines({ r, plot, fail, note }, kind, name, key) {
    const m = r.model;
    const column = !!(m.transport && m.fracture > 1);
    const stride = m.stride || 1;
    const layer = Math.min(state.compLayer, stride - 1);
    const cellAt = column && state.compBudgetAt !== 'column' && state.compBudgetAt < m.fracture ? state.compBudgetAt : null;
    const whole = cellAt === null;
    const at = whole ? 'column' : cellAt * stride + layer;
    const what = `${name}${kind === 'element' ? ', all of it' : ''}`;
    const hasRelations = (m.nequilibria || 0) > 0;
    // What the lines made and took; over the whole column the budget too, and what the relations moved.
    const want = [[linesCache, { type: 'lines', of: { kind, name }, at }, `${key}|${at}`]];
    if (whole) want.push([budgetCache, null, key]);
    if (whole && hasRelations) want.push([linesCache, { type: 'relations', of: { kind, name } }, `${key}|relations`]);
    const [got, bud, rel] = want.map(([cache, message, k]) => {
      const v = cache.get(k);
      if (v === undefined || v === null) {
        if (message) fetchKept(cache, r, message, k);
        else fetchBudget(r, { kind, name }, k);
      }
      return v;
    });
    if (want.some(([cache, , k]) => { const v = cache.get(k); return v === undefined || v === null; })) {
      fail(`Working out what each reaction made and took of ${name}…`);
      return;
    }
    if (got.error) { fail(`What each reaction made and took of ${name} could not be worked out: ${got.error}`); return; }
    if (whole && bud.error) { fail(`The budget of ${name} could not be kept: ${bud.error}`); return; }
    if (rel && rel.error) { fail(`What the relations moved of ${name} could not be worked out: ${rel.error}`); return; }
    const n = r.n;
    const last = n - 1;
    const fmt = (v) => fmtNumber(v);
    const made = whole ? bud.byReactions[last] : null;
    // What holding put in of it, over the whole column: the budget's, beside what the reactions made.
    const hold = whole ? holdingOf(bud) : null;
    const place = whole ? (m.transport ? ' over the whole column' : '')
      : ` at cell ${cellAt}${stride > 1 && layer ? `, rock layer ${layer}` : ''}`;
    const sym = timeUnit().symbol;
    const per = !whole ? `per kg of the water of cell ${cellAt}${stride > 1 && layer ? `, rock layer ${layer}` : ''}`
      : m.transport ? "concentration × m per m² of the water's cross-section" : 'per kg of water';
    // The lines by how much of it they move over the run, made and taken together.
    const ranked = got.lines.map((l) => ({ l, made: l.madeCum[last], taken: l.takenCum[last], gross: l.madeCum[last] - l.takenCum[last] }))
      .sort((a, b) => b.gross - a.gross || a.l.index - b.l.index);
    // The relations, each with its part over the run, the most first.
    const relRows = rel && rel.determined ? rel.relations.map((x) => ({ x, part: x.part[last] }))
      .sort((a, b) => Math.abs(b.part) - Math.abs(a.part) || a.x.index - b.x.index) : [];
    if (!ranked.length && !relRows.length && !(rel && !rel.determined)) {
      fail(`No <REACTIONS> line makes or takes any ${what}${place}`
        + (whole ? `: what the budget counts the reactions as having made of it, ${fmt(made)} by the end, is the summing's error, ${
          hasRelations ? 'the relations only moving an element between its species' : 'the model having no relations'}.` : '.'));
      return;
    }
    const pick = compTimeIndices(r);
    const idx = pick.idx;
    if (!idx.length) { fail(`Nothing is stored after ${fmtTime(compFrom())}: lower the "from" time.`); return; }
    if (ranked.length) {
      const named = ranked.slice(0, LINES_NAMED);
      const rest = ranked.slice(LINES_NAMED);
      const c = themeColors();
      const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22'];
      const xs = idx.map((i) => showT(r.t[i]));
      const traces = [];
      const add = (label, color, mk, tk, group) => {
        const anyMade = mk.some((v) => v > 0);
        const anyTaken = tk.some((v) => v < 0);
        if (anyMade) {
          traces.push({ type: 'scatter', mode: 'lines', name: label, legendgroup: group, x: xs, y: idx.map((i) => mk[i]),
            stackgroup: 'made', line: { width: 0.6, color } });
        }
        if (anyTaken) {
          traces.push({ type: 'scatter', mode: 'lines', name: label, legendgroup: group, showlegend: !anyMade, x: xs,
            y: idx.map((i) => tk[i]), stackgroup: 'taken', line: { width: 0.6, color } });
        }
      };
      named.forEach(({ l }, q) => add(l.name, palette[q], l.made, l.taken, `line${l.index}`));
      if (rest.length) {
        const mk = new Float64Array(n);
        const tk = new Float64Array(n);
        for (const { l } of rest) for (let i = 0; i < n; i++) { mk[i] += l.made[i]; tk[i] += l.taken[i]; }
        add(`the other ${rest.length} reaction${rest.length === 1 ? '' : 's'}`, '#7f7f7f', mk, tk, 'rest');
      }
      const net = new Float64Array(n);
      for (const { l } of ranked) for (let i = 0; i < n; i++) net[i] += l.made[i] + l.taken[i];
      traces.push({ type: 'scatter', mode: 'lines', name: 'made less taken, every reaction', x: xs, y: idx.map((i) => net[i]),
        line: { color: c.text, dash: 'dot', width: 1.6 } });
      const layout = baseLayout();
      layout.xaxis.type = pick.logT ? 'log' : 'linear';
      layout.xaxis.title = { text: `time (${shownTime().sym})`, font: { size: 11 } };
      layout.yaxis.title = { text: `made (+) and taken (−) per ${sym}<br>${per}`, font: { size: 11 } };
      layout.margin.l = 86;
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
    } else {
      fail(`No <REACTIONS> line makes or takes any ${what}${place}: what the reactions made of it, ${fmt(made)} by the end, is what the `
        + 'relations moved, in the table.');
    }
    // Over the run: what each line made and took, the lines together; over the whole column each relation's part, all of
    // them, and the summing's error -- or, where the relations cannot be told apart, what they moved together.
    const sumMade = ranked.reduce((s, x) => s + x.made, 0);
    const sumTaken = ranked.reduce((s, x) => s + x.taken, 0);
    const netLines = sumMade + sumTaken;
    const leftover = whole ? made - netLines : null;
    const relSum = relRows.reduce((s, x) => s + x.part, 0);
    const together = !!(rel && !rel.determined);
    const error = whole && !together ? leftover - relSum : null;
    const moved = sumMade - sumTaken + relRows.reduce((s, x) => s + Math.abs(x.part), 0);
    const errRel = error !== null && moved > 0 ? Math.abs(error) / moved : null;
    const errText = errRel === null ? '' : errRel < 0.01 ? errRel.toExponential(1) : `${(100 * errRel).toPrecision(3)} %`;
    const share = (v, of) => (of !== 0 && v !== 0 ? v / of : null);
    const num = (v) => (v === null || v === undefined ? '' : esc(v === 0 ? '0' : fit4(v)));
    const td = (v, text = num(v)) => `<td${v === null || v === undefined ? '' : ` data-v="${v}"`}>${text}</td>`;
    const pctTd = (v) => td(v, v === null ? '' : `${esc((100 * v).toPrecision(3))} %`);
    const blank = '<td></td>';
    const netRow = (label, v, line = '') => `<tr><td>${esc(label)}</td><td>${line}</td>${blank}${blank}${td(v)}${blank}${blank}</tr>`;
    const lineRows = ranked.map(({ l, made: mk, taken: tk }) => `<tr><td>${esc(l.name)}</td><td>${l.lines.join(', ')}</td>${td(mk)}${td(tk)}`
      + `${td(mk + tk)}${pctTd(share(mk, sumMade))}${pctTd(share(tk, sumTaken))}</tr>`).join('');
    const relHtml = relRows.length
      ? `<tr><th>Each relation, over the run</th><th>line</th>${blank}${blank}<th>net</th>${blank}${blank}</tr>`
        + relRows.map(({ x, part }) => netRow(x.name, part, x.line)).join('') + netRow('every relation', relSum) : '';
    const restIs = together ? 'what the relations moved, together, with the summing\'s error: they cannot be told apart one by one'
      : !hasRelations ? 'the summing\'s error, the model having no relations'
        : kind === 'element' && !relRows.length ? 'the summing\'s error, the relations only moving an element between its species'
          : 'the summing\'s error over the stored points, each species\' own';
    const box = $('rtmCompLines');
    box.innerHTML = `<table><thead><tr><th>Each reaction, over the run: ${esc(what)}${esc(place)}</th><th>line</th><th>made</th>`
      + '<th>taken</th><th>net</th><th>of what was made</th><th>of what was taken</th></tr></thead>'
      + `<tbody>${lineRows}<tr><td>every reaction</td>${blank}${td(sumMade)}${td(sumTaken)}${td(netLines)}${blank}${blank}</tr>`
      + (whole ? relHtml + (together ? netRow('the relations, together, with the summing\'s error', leftover) : netRow('the summing\'s error', error))
        + netRow('made by reactions, net, as the budget has it', made)
        + (hold ? netRow(`put in by holding ${hold.names}`, hold.put[last]) : '') : '')
      + '</tbody></table>'
      + `<p>Each reaction's rate of making it and of taking it summed over the stored points by the trapezoidal rule, ${esc(per)}; `
      + 'a line and one written apart that undoes it are one reaction, both lines given. '
      + (whole ? `${relRows.length ? 'Each relation\'s part is its extent, read off the balance of a species of its own, times what it '
        + 'makes of this. ' : ''}What none of them accounts for is ${restIs}.`
        + (hold ? ' A species held is kept where it is: what the reactions took of it, less what they made, was put in to keep it there, '
          + 'and each line counts what it took or made of it all the same.' : '')
        : 'At a cell the water carries it in and out besides, which only the budget of the whole column weighs.') + '</p>';
    box.hidden = false;
    const makers = ranked.filter((x) => x.made > 0);
    const takers = ranked.filter((x) => x.taken < 0);
    const topMaker = makers.length ? makers.reduce((b, x) => (x.made > b.made ? x : b)) : null;
    const topTaker = takers.length ? takers.reduce((b, x) => (x.taken < b.taken ? x : b)) : null;
    const topRel = relRows.length ? relRows[0] : null;
    note.textContent = [`${what}${place}: ${makers.length ? `made by ${makers.length} reaction${makers.length === 1 ? '' : 's'}, `
      + `${fmt(sumMade)}, the most by ${topMaker.l.name} (${(100 * topMaker.made / sumMade).toPrecision(3)} %)` : 'made by no reaction'}`,
    takers.length ? `taken by ${takers.length}, ${fmt(-sumTaken)}, the most by ${topTaker.l.name} `
      + `(${(100 * topTaker.taken / sumTaken).toPrecision(3)} %)` : 'taken by none',
    topRel ? `the relations ${relSum >= 0 ? 'made' : 'took'} ${fmt(Math.abs(relSum))} net, ${relRows.length} of them, the most by `
      + `${topRel.x.name} (${fmt(topRel.part)})` : '',
    whole ? (together ? `what no line accounts for, ${fmt(leftover)}, is what the relations moved together: they cannot be told apart`
      : `the summing's error ${fmt(error)}, ${errText} of what was made and taken`) : '',
    hold ? `${hold.put[last] >= 0 ? 'put in' : 'taken out'} by holding ${hold.names}, ${fmt(Math.abs(hold.put[last]))}` : '']
      .filter(Boolean).join('; ');
    // Saved: each line's rates and its sum at every stored point, each relation's part; in Excel, the table on a sheet of its own.
    const head = [`t (${shownTime().sym})`];
    for (const { l } of ranked) {
      const who = `${l.name} (line${l.lines.length > 1 ? 's' : ''} ${l.lines.join(' and ')})`;
      head.push(`${who}, made per ${sym}`, `${who}, taken per ${sym}`, `${who}, net since the start`);
    }
    head.push('every reaction, net since the start');
    if (whole) {
      for (const { x } of relRows) head.push(`${x.name} (line ${x.line}), net since the start`);
      if (relRows.length) head.push('every relation, net since the start');
      head.push(together ? "the relations, together, with the summing's error" : "the summing's error", 'made by reactions, net, as the budget has it');
      if (hold) head.push(`put in by holding ${hold.names}`);
    }
    compTableNow = {
      head,
      name: `${fileStem()}_budget_${name.replace(/[^\w.-]+/g, '_')}_by_reaction${whole ? '' : `_cell${cellAt}${layer ? `_layer${layer}` : ''}`}`,
      rows: Array.from({ length: n }, (_, i) => {
        const row = [showT(r.t[i])];
        let all = 0;
        for (const { l } of ranked) { row.push(l.made[i], l.taken[i], l.madeCum[i] + l.takenCum[i]); all += l.madeCum[i] + l.takenCum[i]; }
        row.push(all);
        if (whole) {
          let rs = 0;
          for (const { x } of relRows) { row.push(x.part[i]); rs += x.part[i]; }
          if (relRows.length) row.push(rs);
          row.push(bud.byReactions[i] - all - rs, bud.byReactions[i]);
          if (hold) row.push(hold.put[i]);
        }
        return row;
      }),
      extra: [{ name: 'over the run', head: ['reaction or relation', 'line', 'made', 'taken', 'net', 'of what was made', 'of what was taken'],
        rows: [...ranked.map(({ l, made: mk, taken: tk }) => [l.name, l.lines.join(', '), mk, tk, mk + tk, share(mk, sumMade), share(tk, sumTaken)]),
          ['every reaction', null, sumMade, sumTaken, netLines, null, null],
          ...(whole ? [...relRows.map(({ x, part }) => [x.name, String(x.line), null, null, part, null, null]),
            ...(relRows.length ? [['every relation', null, null, null, relSum, null, null]] : []),
            [together ? "the relations, together, with the summing's error" : "the summing's error", null, null, null, together ? leftover : error, null, null],
            ['made by reactions, net, as the budget has it', null, null, null, made, null, null],
            ...(hold ? [[`put in by holding ${hold.names}`, null, null, null, hold.put[last], null, null]] : [])] : [])] }],
    };
  }

  /*
    WHERE AN ELEMENT GOES over the run, over the whole column: a flow
    diagram of its species and the ends of its account -- what holding put
    in or took out, what came in and went out at the ends, what reactions
    made from nowhere or lost, what was drawn from what was there at the
    start and what built up by the end -- each band as wide as what went
    from one to the other, net (rtmFlows). Hovering on a band names the
    lines that carried it, and those that carried some of it back. Under the
    chart the same as a table, every flow, and the bands under 1e-4 of the
    largest, which the chart leaves out, said. Asked for once a run and an
    element, kept with the run itself.
  */
  const flowsAsked = new WeakMap();
  const FLOWS_SHOWN = 1e-4;
  function flowsOf(r, name) {
    let byEl = flowsAsked.get(r);
    if (!byEl) { byEl = new Map(); flowsAsked.set(r, byEl); }
    if (byEl.has(name)) return byEl.get(name);
    byEl.set(name, null);
    const h = holderOf(r);
    const text = h && h !== current ? h.text : ((state.ran && state.ran.text) || state.text);
    const ask = (withRun) => request({ type: 'flows', runKey: r.runKey, of: { kind: 'element', name },
      ...(withRun ? { text, t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    (async () => {
      let got;
      try {
        got = await ask(false);
        if (got.missing) got = await ask(true);
      } catch (e) { got = { error: e.message }; }
      byEl.set(name, got);
      if (state.result === r && state.compView === 'budget') drawComp();
    })();
    return null;
  }

  function drawBudgetFlows({ r, plot, fail, note }, name) {
    const got = flowsOf(r, name);
    if (!got) { fail(`Working out where ${name} goes…`); return; }
    if (got.error) { fail(`Where ${name} goes could not be worked out: ${got.error}`); return; }
    if (!got.links.length) { fail(`Nothing moves any ${name} over the run: it stays in the species it starts in.`); return; }
    const m = r.model;
    const held = got.held.map(labelOf);
    const heldNames = held.length < 2 ? held.join('') : `${held.slice(0, -1).join(', ')} and ${held[held.length - 1]}`;
    const ENDS = {
      '#heldIn': `put in by holding ${heldNames}`, '#heldOut': `taken out by holding ${heldNames}`,
      '#inLeft': 'came in at the left', '#outLeft': 'went out at the left', '#inRight': 'came in at the right',
      '#outRight': 'went out at the right', '#made': 'made by reactions', '#lost': 'lost by reactions',
      '#drawn': 'drawn from what was there at the start', '#builtUp': 'built up over the run',
    };
    const label = (key) => ENDS[key] || labelOf(key);
    const top = got.links[0].value;
    const shown = got.links.filter((x) => x.value >= FLOWS_SHOWN * top);
    const keys = [...new Set(shown.flatMap((x) => [x.from, x.to]))];
    const kindOf = new Map(got.nodes.map((x) => [x.key, x.kind]));
    const colorOf = (key) => (key === '#lost' ? '#e0663e' : kindOf.get(key) === 'source' ? '#2ca02c'
      : kindOf.get(key) === 'sink' ? '#7f7f7f' : '#3b82c4');
    const fmt = (v) => fmtNumber(v);
    const linesText = (list) => list.slice(0, 3).map(([line, nm, amt]) => (line === null ? `${nm}, ${fmt(amt)}`
      : `${nm} (line${String(line).includes(',') ? 's' : ''} ${line}), ${fmt(amt)}`)).join('; ') + (list.length > 3 ? `; and ${list.length - 3} more` : '');
    const hover = (x) => [x.by.length ? `by ${esc(linesText(x.by))}` : '', x.back.length ? `back by ${esc(linesText(x.back))}` : '']
      .filter(Boolean).join('<br>');
    const c = themeColors();
    const layout = baseLayout();
    layout.height = Math.max(360, 30 * keys.length + 80);
    layout.margin = { l: 10, r: 10, t: 10, b: 10 };
    Plotly.react(plot, [{
      type: 'sankey', orientation: 'h', arrangement: 'snap', valueformat: '.4~g',
      node: { label: keys.map(label), color: keys.map(colorOf), pad: 16, thickness: 14, line: { width: 0 },
        hovertemplate: '%{label}<extra></extra>' },
      link: { source: shown.map((x) => keys.indexOf(x.from)), target: shown.map((x) => keys.indexOf(x.to)), value: shown.map((x) => x.value),
        color: shown.map((x) => (x.to === '#lost' ? 'rgba(224,102,62,0.45)' : x.from === '#heldIn' ? 'rgba(44,160,44,0.35)'
          : 'rgba(127,127,127,0.32)')),
        customdata: shown.map(hover), hovertemplate: '%{source.label} → %{target.label}: %{value}<br>%{customdata}<extra></extra>' },
    }], { ...layout, font: { ...layout.font, color: c.text } }, PLOT_CONFIG);
    const per = m.transport ? "concentration × m per m² of the water's cross-section" : 'per kg of water';
    const lost = got.links.filter((x) => x.to === '#lost').reduce((s, x) => s + x.value, 0);
    const made = got.links.filter((x) => x.from === '#made').reduce((s, x) => s + x.value, 0);
    const putIn = got.links.filter((x) => x.from === '#heldIn').reduce((s, x) => s + x.value, 0);
    const biggest = got.links.find((x) => kindOf.get(x.from) === 'species' && kindOf.get(x.to) === 'species');
    const hidden = got.links.length - shown.length;
    note.textContent = [`${name}, all of it, over the run${m.transport ? ' and the whole column' : ''}: ${got.links.length} `
      + `flow${got.links.length === 1 ? '' : 's'}`,
    putIn ? `put in by holding ${heldNames}, ${fmt(putIn)}` : '',
    biggest ? `the most from one species to another, ${labelOf(biggest.from)} to ${labelOf(biggest.to)}, ${fmt(biggest.value)}` : '',
    lost ? `lost by reactions, ${fmt(lost)}` : '', made ? `made by reactions, ${fmt(made)}` : '',
    hidden ? `${hidden} under ${FLOWS_SHOWN} of the largest, in the table only` : ''].filter(Boolean).join('; ');
    const num = (v) => esc(v === 0 ? '0' : fit4(v));
    const rows = got.links.map((x) => `<tr><td>${esc(label(x.from))}</td><td>${esc(label(x.to))}</td><td data-v="${x.value}">${num(x.value)}</td>`
      + `<td>${esc(linesText(x.by))}</td><td>${esc(linesText(x.back))}</td></tr>`).join('');
    const box = $('rtmCompLines');
    box.innerHTML = `<table><thead><tr><th>Where ${esc(name)} goes, over the run: from</th><th>to</th><th>net</th><th>carried by</th>`
      + `<th>carried back by</th></tr></thead><tbody>${rows}</tbody></table>`
      + `<p>Amounts ${esc(per)}, net over the run. What each <code>&lt;REACTIONS&gt;</code> line took of ${esc(name)}'s species is sent to `
      + 'what it gave, in proportion; what it took and gave nowhere is lost by reactions, and what it gave from nowhere made. Beside them, '
      + 'what holding put in or took out, what came in or went out at the ends, what the relations moved, together, and what each species '
      + 'built up by the end or was drawn from what was there at the start. A pair of species both ways is set against itself: a reaction '
      + 'and its reverse can move far more than ever stays, and the table names both. A line with a coefficient on more than one species '
      + 'of it is shared out among them in proportion, which is a reading of the line, not something the run itself says.</p>';
    box.hidden = false;
    compTableNow = { head: ['from', 'to', 'net', 'carried by', 'carried back by'], name: `${fileStem()}_where_${name}_goes`,
      rows: got.links.map((x) => [label(x.from), label(x.to), x.value, linesText(x.by), linesText(x.back)]) };
  }

  /*
    WHERE THE MINERALS' FRONTS ARE: along the column, from the inlet, at each
    stored time. A mineral the column holds at the start: the length of
    column it has been cleared of, each cell counting its width times the
    share of its first amount gone -- for a sharp front from the inlet where
    the front is, the front cell's share placing it inside the cell, and for
    a spread one the middle of the spread. A mineral it holds none of at the
    start: the zone it has formed in, its edges the first and the last cell
    from the inlet holding any -- more than a millionth of its most -- at
    their centres. Each front's speed is the slope of its place against time
    over the second half of the run, by least squares; set against the
    water's own speed, the column's length over the time it takes the water
    to cross it.
  */
  function drawFronts({ r, plot, layer, fail, note }) {
    const m = r.model;
    if (!(m.transport && m.fracture > 1)) { fail('A front moves along a column: this run is not one.'); return; }
    const C = compositionOf(m);
    const ks = [...new Set(C.elements.flatMap((e) => e.terms.filter((tm) => tm[2] === 'mineral').map((tm) => tm[0])))];
    if (!ks.length) { fail('The model has no mineral: there is no front to follow.'); return; }
    const nf = m.fracture;
    const stride = m.stride || 1;
    const ns = m.nspecies;
    const n = r.n;
    const L = m.length;
    const leftward = !!(m.settings && m.settings.ADVECTION && m.settings.VELOCITY < 0);
    const order = Array.from({ length: nf }, (_, j) => (leftward ? nf - 1 - j : j));
    const fromInlet = (x) => (leftward ? L - x : x);
    const at = (i, cell, k) => r.states[i * r.width + (cell * stride + layer) * ns + k];
    const sym = timeUnit().symbol;
    const lines = [];
    const events = [];
    for (const k of ks) {
      const name = m.species[k];
      let most = 0;
      for (let i = 0; i < n; i++) for (const cell of order) most = Math.max(most, at(i, cell, k));
      if (!(most > 0)) continue;
      const start = order.map((cell) => at(0, cell, k));
      if (start.some((v) => v > 0)) {
        const pos = new Float64Array(n);
        for (let i = 0; i < n; i++) {
          let s = 0;
          order.forEach((cell, j) => { if (start[j] > 0) s += m.width[cell] * Math.max(0, 1 - at(i, cell, k) / start[j]); });
          pos[i] = s;
        }
        if (pos[n - 1] > 0) lines.push({ name, label: `${name}, cleared to`, pos, dash: 'solid' });
        const inlet = Array.from({ length: n }, (_, i) => i).find((i) => start[0] > 0 && !(at(i, order[0], k) > 0));
        if (inlet !== undefined) events.push([`${name} gone at the inlet`, r.t[inlet]]);
        const all = Array.from({ length: n }, (_, i) => i).find((i) => order.every((cell) => !(at(i, cell, k) > 0)));
        if (all !== undefined) events.push([`${name} gone from the column`, r.t[all]]);
      } else {
        const up = new Float64Array(n).fill(NaN);
        const down = new Float64Array(n).fill(NaN);
        let first = -1;
        for (let i = 0; i < n; i++) {
          let a = -1;
          let b = -1;
          order.forEach((cell, j) => { if (at(i, cell, k) > 1e-6 * most) { if (a < 0) a = j; b = j; } });
          if (a < 0) continue;
          if (first < 0) { first = i; events.push([`${name} first formed, ${fmtNumber(fromInlet(m.centres[order[a]]))} m from the inlet`, r.t[i]]); }
          up[i] = fromInlet(m.centres[order[a]]);
          down[i] = fromInlet(m.centres[order[b]]);
        }
        lines.push({ name, label: `${name}, formed from`, pos: up, dash: 'dash' }, { name, label: `${name}, formed to`, pos: down, dash: 'dot' });
      }
    }
    if (!lines.length) { fail('No mineral moved: none dissolved where it was, and none formed where it was not.'); return; }
    // Each front's speed over the second half of the run, and the water's.
    const half = r.t[n - 1] / 2;
    const speed = (pos) => {
      let cnt = 0; let sx = 0; let sy = 0; let sxx = 0; let sxy = 0;
      for (let i = 0; i < n; i++) {
        if (!(r.t[i] >= half) || !Number.isFinite(pos[i])) continue;
        cnt++; sx += r.t[i]; sy += pos[i]; sxx += r.t[i] * r.t[i]; sxy += r.t[i] * pos[i];
      }
      const d = cnt * sxx - sx * sx;
      return cnt > 1 && d > 0 ? (cnt * sxy - sx * sy) / d : null;
    };
    const water = poreTime(r) > 0 ? L / poreTime(r) : null;
    const rows = lines.map((x) => {
      const v = speed(x.pos);
      return { ...x, end: x.pos[n - 1], v, share: v !== null && water ? v / water : null };
    });
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22', '#17becf'];
    const colourOf = new Map([...new Set(rows.map((x) => x.name))].map((nm, q) => [nm, palette[q % palette.length]]));
    const tShown = shownTime();
    const xs = Array.from(r.t, (t) => t * tShown.per);
    const traces = rows.map((x) => ({ type: 'scatter', mode: 'lines', name: x.label, x: xs, y: Array.from(x.pos, (v) => (Number.isFinite(v) ? v : null)),
      line: { color: colourOf.get(x.name), width: 1.8, dash: x.dash }, connectgaps: false }));
    const layout = baseLayout();
    layout.xaxis.title = { text: `time (${tShown.sym})`, font: { size: 11 } };
    layout.yaxis.title = { text: `distance from the inlet (m)${stride > 1 && layer ? `, rock layer ${layer}` : ''}`, font: { size: 11 } };
    layout.yaxis.range = [0, L];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    const num = (v) => (v === null || v === undefined || !Number.isFinite(v) ? '' : esc(v === 0 ? '0' : fit4(v)));
    const td = (v, text = num(v)) => `<td${v === null || v === undefined || !Number.isFinite(v) ? '' : ` data-v="${v}"`}>${text}</td>`;
    const box = $('rtmCompLines');
    box.innerHTML = `<table><thead><tr><th>Each front, from the inlet</th><th>at the end (m)</th><th>speed (m/${esc(sym)})</th>`
      + '<th>of the water\'s speed</th></tr></thead><tbody>'
      + rows.map((x) => `<tr><td>${esc(x.label)}</td>${td(x.end)}${td(x.v)}${td(x.share)}</tr>`).join('') + '</tbody></table>'
      + (events.length ? `<table><thead><tr><th>When</th><th>t (${esc(tShown.sym)})</th></tr></thead><tbody>${events.sort((a, b) => a[1] - b[1])
        .map(([what, t]) => `<tr><td>${esc(what)}</td>${td(t * tShown.per)}</tr>`).join('')}</tbody></table>` : '')
      + `<p>A mineral the column holds at the start: the length of column cleared of it, each cell its width times the share of `
      + `its first amount gone. One it holds none of: the first and the last cell holding any. A speed is over the second half `
      + `of the run${water ? `; the water's, ${fmtNumber(water)} m/${esc(sym)}, the column's length over the time it takes the water to cross it` : ''}.</p>`;
    box.hidden = false;
    const lead = rows.filter((x) => x.v !== null).sort((a, b) => Math.abs(b.v) - Math.abs(a.v))[0];
    note.textContent = [`${rows.length} front${rows.length === 1 ? '' : 's'} over ${fmtNumber(L)} m`,
      lead ? `the fastest ${lead.label} ${fmtNumber(lead.end)} m by the end, at ${fit4(lead.v)} m/${sym}`
        + `${lead.share !== null ? `, ${fit4(lead.share)} of the water's speed` : ''}` : '']
      .filter(Boolean).join('; ');
    compTableNow = {
      head: [`t (${tShown.sym})`, ...rows.map((x) => `${x.label} (m)`)],
      name: `${fileStem()}_fronts${layer ? `_layer${layer}` : ''}`,
      rows: Array.from({ length: n }, (_, i) => [r.t[i] * tShown.per, ...rows.map((x) => (Number.isFinite(x.pos[i]) ? x.pos[i] : null))]),
      extra: [{ name: 'speeds', head: ['front', 'at the end (m)', `speed (m/${sym})`, "of the water's speed"],
        rows: rows.map((x) => [x.label, x.end, x.v, x.share]) },
      ...(events.length ? [{ name: 'when', head: ['what', `t (${tShown.sym})`], rows: events.map(([what, t]) => [what, t * tShown.per]) }] : [])],
    };
  }

  /** The stored points along the run a chart in time draws: after "from" on a log axis. */
  function compTimeIndices(r) {
    const logT = $('rtmCompLogT').checked;
    const tmin = compFrom();
    const out = [];
    for (let i = 0; i < r.n; i++) if (!logT || (r.t[i] > 0 && r.t[i] >= tmin)) out.push(i);
    return { idx: out, logT };
  }

  /**
   * Where an element is: each species with any of it, as its share of all
   * there is in the water or the whole cell, stacked, or as its amount --
   * along the run at one cell, or along the column at one time. A species
   * that never comes to 1 % is drawn with the others like it, as one band.
   */
  function drawWhere({ r, plot, along, layer, cell, atIndex, fail, note, still }) {
    const list = compElements(r.model, state.compIn);
    if (!list.length) {
      fail(state.compIn === 'water' ? 'No element is dissolved in two species or more here: try the whole cell.'
        : 'No element is in two species or more here.');
      return;
    }
    const E = list.find((e) => e.el === state.compElement) || list[0];
    const ns = r.model.nspecies;
    const stride = r.model.stride || 1;
    const names = r.model.species;
    let xs;
    let valueAt;
    let idx = null;
    if (along === 'time') {
      const pick = compTimeIndices(r);
      idx = pick.idx;
      if (!idx.length) { fail(`Nothing is stored after ${fmtTime(compFrom())}: lower the "from" time.`); return; }
      const mc = modelCell(cell, layer);
      xs = idx.map((i) => showT(r.t[i]));
      valueAt = (j, k) => r.states[idx[j] * r.width + mc * ns + k];
    } else {
      xs = Array.from(r.model.centres);
      valueAt = (j, k) => r.states[atIndex * r.width + (j * stride + layer) * ns + k];
    }
    const npts = xs.length;
    const bands = E.terms.map(([k, n, where]) => ({ name: where === 'water' ? names[k] : `${names[k]}, ${WHERE_LABELS[where]}`,
      y: Float64Array.from({ length: npts }, (_, j) => n * Math.max(0, valueAt(j, k))) }));
    const total = new Float64Array(npts);
    for (const b of bands) for (let j = 0; j < npts; j++) total[j] += b.y[j];
    for (const b of bands) {
      let most = 0;
      let sum = 0;
      for (let j = 0; j < npts; j++) {
        const f = total[j] > 0 ? b.y[j] / total[j] : 0;
        most = Math.max(most, f);
        sum += f;
      }
      b.most = most;
      b.mean = sum / npts;
    }
    /*
      On the slider, which species are bands of their own, and in what order, by the whole run -- each one's largest and
      mean share over every stored point of every cell -- so that the bands and their colours stay from one time to the
      next; and amounts on an axis to the most the run holds anywhere.
    */
    const sliding = still && along !== 'time';
    let runTop = 0;
    if (sliding) {
      const run = overRun(`${r.runKey}|where|${E.el}|${state.compIn}|${layer}`, r, layer,
        { most: new Float64Array(E.terms.length), sum: new Float64Array(E.terms.length), n: 0, top: 0 }, (a, i, mc) => {
          const v = E.terms.map(([k, n]) => n * Math.max(0, r.states[i * r.width + mc * ns + k]));
          let tot = 0;
          for (const x of v) tot += x;
          if (tot > 0) v.forEach((x, q) => { const f = x / tot; if (f > a.most[q]) a.most[q] = f; a.sum[q] += f; });
          a.n++;
          if (tot > a.top) a.top = tot;
          return a;
        });
      bands.forEach((b, q) => { b.most = run.most[q]; b.mean = run.sum[q] / Math.max(1, run.n); });
      runTop = run.top;
    }
    // The largest at the bottom; a species never 1 % of the total, with the rest like it.
    bands.sort((a, b) => b.mean - a.mean);
    const kept = bands.filter((b) => b.most >= 0.01);
    const small = bands.filter((b) => b.most < 0.01);
    if (small.length) {
      const y = new Float64Array(npts);
      for (const b of small) for (let j = 0; j < npts; j++) y[j] += b.y[j];
      kept.push({ name: small.length === 1 ? small[0].name : `${small.length} more, each under 1 %`, y, rest: small });
    }
    const percent = state.compAs === 'percent';
    const shown = kept.map((b) => Array.from(b.y, (v, j) => (percent ? (total[j] > 0 ? (100 * v) / total[j] : null) : v)));
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const traces = kept.map((b, q) => ({
      type: 'scatter', mode: 'lines', name: b.name, x: xs, y: shown[q], stackgroup: 'one',
      line: { width: 0.6, color: palette[q % palette.length] },
      hovertemplate: percent ? `${esc(b.name)}: %{y:.3g} %<extra></extra>` : `${esc(b.name)}: %{y:.4e}<extra></extra>`,
    }));
    const layout = baseLayout();
    const where = state.compIn === 'water' ? 'dissolved' : 'in the cell';
    layout.xaxis.type = along === 'time' && $('rtmCompLogT').checked ? 'log' : 'linear';
    layout.xaxis.title = { text: along === 'time' ? `time (${shownTime().sym})` : 'distance from the left-hand face (m)',
      font: { size: 11 } };
    layout.yaxis.title = { text: percent ? `share of the ${E.el} ${where} (%)` : `${E.el} ${where} (concentration × count)`,
      font: { size: 11 } };
    if (percent) layout.yaxis.range = [0, 100];
    else if (sliding && runTop > 0) layout.yaxis.range = [0, 1.05 * runTop];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    const xHead = along === 'time' ? `t (${shownTime().sym})` : 'distance (m)';
    compTableNow = { head: [xHead, ...kept.map((b) => `${b.name}${percent ? ' (%)' : ''}`), `${E.el} ${where}, all of it`],
      rows: xs.map((x, j) => [x, ...shown.map((col) => col[j]), total[j]]),
      name: `rtm_${E.el}_${along === 'time' ? `cell${cell}` : 'column'}` };
    const bits = [along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}, ${npts} stored points`
      : `${npts} cells at ${fmtTime(r.t[atIndex])}${layer ? `, rock layer ${layer}` : ''}`,
    `${E.terms.length} species hold ${E.el} ${where}`];
    if (small.length > 1) bits.push(`${small.length} never come to 1 %, drawn as one band`);
    const bk = besideRun();
    if (bk) bits.push(besideNote(bk, 'bands that stack take no second run; the other views draw it'));
    if (along === 'distance' && !sliding && state.compTimes.trim() && Math.abs(r.t[atIndex] - parseTimes(state.compTimes, shownTime()).times[0])
      > 0.01 * Math.abs(r.t[atIndex] || 1)) bits.push('the nearest stored time');
    note.textContent = bits.join('; ');
  }

  /*
    The kept run's waters for the waters drawn: on a Piper diagram its own
    path -- every stored point at the cell, or every cell at its time
    nearest -- and on the Schoeller and Stiff diagrams, beside each water,
    the kept run's at the same cell at its time nearest, or at the same cell
    of the column; null where it has none there. Its own species make its
    poles; Schoeller and Stiff need its unit to be this run's.
  */
  function besideWaters({ r, view, along, layer, cell, atIndex, drawable }) {
    const k = besideRun();
    if (!k) return {};
    const kr = k.r;
    const km = kr.model;
    const C = compositionOf(km);
    const unit = poleUnit(km);
    const why = !C ? 'it was made before the page could read what its species are made of'
      : !['piper', 'durov'].includes(view) && unit.text !== poleUnit(r.model).text ? `its ions are in ${unit.text}, these in ${poleUnit(r.model).text}`
        : along === 'time' && !(cell < (km.fracture || 1)) ? `it has ${km.fracture || 1} cells`
          : along !== 'time' && !(km.transport && km.fracture > 1) ? 'it was a batch'
            : layer > 0 && !(layer < (km.stride || 1)) ? 'it has no rock matrix' : '';
    if (why) return { said: besideNote(k, why) };
    const terms = poleTerms(C);
    const kStride = km.stride || 1;
    const kt = besideTimes(k);
    const at = (i, mc, label, extra) => ({ w: waterAt(kr, terms, unit.scale, i, mc), label, i, mc, ...extra });
    let waters;
    if (along === 'time') {
      const mc = modelCell(cell, layer, kr);
      if (view === 'piper' || view === 'durov') {
        const logT = $('rtmCompLogT').checked;
        const tmin = compFrom();
        const idx = [];
        for (let i = 0; i < kr.n; i++) if (!logT || (kt[i] > 0 && kt[i] >= tmin)) idx.push(i);
        const step = Math.max(1, Math.ceil(idx.length / 300));
        waters = idx.filter((_, j) => j % step === 0 || j === idx.length - 1).map((i) => at(i, mc, fmtTime(kt[i])));
      } else {
        waters = drawable.map((wt) => (wt.t > kt[kr.n - 1] * 1.000001 ? null : at(nearestIndex(kt, wt.t), mc, fmtTime(wt.t))));
      }
    } else {
      const j = nearestIndex(kt, r.t[atIndex]);
      const cells = view === 'piper' || view === 'durov' ? Array.from({ length: km.fracture }, (_, c) => c) : drawable.map((wt) => wt.cell);
      waters = cells.map((c) => (c < km.fracture ? at(j, c * kStride + layer, `cell ${c}`) : null));
    }
    const drawn = waters.filter(Boolean).length;
    return { waters, label: k.label, said: drawn ? besideNote(k) : besideNote(k, 'none of its waters is at these times or cells') };
  }

  /**
   * The water's major ions, from the model and from <DATA>: as a Piper
   * diagram, a path through the run or along the column; as a Schoeller
   * diagram, a line per water; or as Stiff diagrams, one per water.
   */
  function drawWaters({ r, plot, along, layer, cell, asked, atIndex, fail, note, still }) {
    const C = compositionOf(r.model);
    const terms = poleTerms(C);
    const unit = poleUnit(r.model);
    const missing = POLES.filter((p) => !terms[p.key].length).map((p) => p.label);
    if (missing.length === POLES.length) { fail('The model has none of the major ions: Ca, Mg, Na, K, Cl, sulfate or carbonate.'); return; }
    const stride = r.model.stride || 1;
    const view = state.compView;
    const c = themeColors();
    const waters = [];
    let colorTitle = '';
    if (along === 'time') {
      const mc = modelCell(cell, layer);
      if (view === 'piper' || view === 'durov') {
        // The path through the run: every stored point after "from", a few hundred at most.
        const { idx, logT } = compTimeIndices(r);
        const step = Math.max(1, Math.ceil(idx.length / 300));
        const take = idx.filter((_, j) => j % step === 0 || j === idx.length - 1);
        for (const i of take) {
          waters.push({ w: waterAt(r, terms, unit.scale, i, mc), t: r.t[i], cell, label: fmtTime(r.t[i]),
            color: logT ? Math.log10(showT(r.t[i])) : showT(r.t[i]), i, mc });
        }
        colorTitle = logT ? `log₁₀ time (${shownTime().sym})` : `time (${shownTime().sym})`;
      } else {
        // The times asked for, or six spread over the run.
        const picks = asked.times.length ? [...new Set(asked.times.map((tt) => nearestIndex(r.t, tt)))]
          : [...new Set(Array.from({ length: 6 }, (_, k) => Math.round(((k + 1) / 6) * (r.n - 1))))];
        if (!asked.times.length && r.t[0] === 0) picks.unshift(0);
        for (const i of [...new Set(picks)]) waters.push({ w: waterAt(r, terms, unit.scale, i, mc), t: r.t[i], cell, label: fmtTime(r.t[i]), i, mc });
      }
    } else {
      const nf = r.model.fracture;
      const cells = view === 'piper' || view === 'durov' ? Array.from({ length: nf }, (_, k) => k)
        : [...new Set(Array.from({ length: Math.min(6, nf) }, (_, k) => Math.round((k * (nf - 1)) / Math.max(1, Math.min(6, nf) - 1))))];
      for (const k of cells) {
        waters.push({ w: waterAt(r, terms, unit.scale, atIndex, k * stride + layer), t: r.t[atIndex], cell: k,
          x: r.model.centres[k], label: `cell ${k}, ${fmtNumber(Number(r.model.centres[k].toPrecision(3)))} m`, color: r.model.centres[k],
          i: atIndex, mc: k * stride + layer });
      }
      colorTitle = 'distance (m)';
    }
    const measuredHere = measuredWaters(along, cell, layer, unit.scale);
    const all = [...waters, ...measuredHere];
    for (const wt of all) { wt.f = poleShares(wt.w); }
    const drawable = waters.filter((wt) => wt.f);
    if (!drawable.length) { fail('No water here has both cations and anions among the major ions to draw.'); return; }
    const kept = besideWaters({ r, view, along, layer, cell, atIndex, drawable });
    if (kept.waters) for (const wt of kept.waters) if (wt) wt.f = poleShares(wt.w);
    let durovSaid = '';
    if (view === 'durov') {
      // The pH of each water, as the worker works it out, and the solids dissolved in it; the kept run's from its own.
      const runs = [[r, drawable], ...(kept.waters ? [[besideRun().r, kept.waters.filter(Boolean)]] : [])];
      for (const [run, ws] of runs) {
        if (!runHas(run, 'pH')) continue;
        const cells = [...new Set(ws.map((wt) => wt.mc))];
        if (cells.some((mc) => quantityPending('pH', mc, run))) {
          fetchQuantities(['pH'], cells, run);
          if (run === r) { fail('Working out the pH…'); return; }
        }
      }
      for (const [run, ws] of runs) {
        for (const wt of ws) {
          const ph = runHas(run, 'pH') ? quantitySeries('pH', wt.mc, run) : null;
          wt.ph = ph ? ph[wt.i] : null;
          wt.tds = tdsAt(run, wt.i, wt.mc);
        }
      }
      const T = tdsTerms(r);
      if (!runHas(r, 'pH')) durovSaid = 'no pH: the model has no H+';
      if (!T) durovSaid = [durovSaid, 'no TDS: the concentrations are not mol/kgw, which an ACTIVITY makes them'].filter(Boolean).join('; ');
      else if (T.without.length) durovSaid = [durovSaid, `the TDS leaves out ${T.without.join(', ')}, which have no formula`].filter(Boolean).join('; ');
    }
    /*
      On the slider, the axes over the whole run: the ions' least and greatest, and the Durov's pH and dissolved solids, at
      every stored point of every cell, the kept run's beside it too -- a pH still to be worked out is left for the next
      drawing rather than kept short.
    */
    let axes = null;
    if (still && along !== 'time') {
      axes = { lo: Infinity, hi: -Infinity, phLo: Infinity, phHi: -Infinity, tds: 0 };
      const bk = kept.waters ? besideRun() : null;
      const runs = [[r, terms, unit.scale]];
      if (bk && compositionOf(bk.r.model)) runs.push([bk.r, poleTerms(compositionOf(bk.r.model)), poleUnit(bk.r.model).scale]);
      for (const [run, tms, sc] of runs) {
        const ions = overRun(`${run.runKey}|ions|${layer}|${sc}`, run, layer, { lo: Infinity, hi: -Infinity }, (a, i, mc) => {
          const w = waterAt(run, tms, sc, i, mc);
          for (const p of POLES) {
            const v = w[p.key];
            if (v > 0) { if (v < a.lo) a.lo = v; if (v > a.hi) a.hi = v; }
          }
          return a;
        });
        axes.lo = Math.min(axes.lo, ions.lo);
        axes.hi = Math.max(axes.hi, ions.hi);
        if (view !== 'durov') continue;
        const rs = run.model.stride || 1;
        const all = Array.from({ length: run.model.fracture }, (_, k) => k * rs + layer);
        if (runHas(run, 'pH') && all.some((mc) => quantityPending('pH', mc, run))) continue;
        const d = overRun(`${run.runKey}|durov|${layer}`, run, layer, { phLo: Infinity, phHi: -Infinity, tds: 0 }, (a, i, mc) => {
          const ph = runHas(run, 'pH') ? quantitySeries('pH', mc, run) : null;
          if (ph && Number.isFinite(ph[i])) { a.phLo = Math.min(a.phLo, ph[i]); a.phHi = Math.max(a.phHi, ph[i]); }
          const tds = tdsAt(run, i, mc);
          if (Number.isFinite(tds)) a.tds = Math.max(a.tds, tds);
          return a;
        });
        axes.phLo = Math.min(axes.phLo, d.phLo);
        axes.phHi = Math.max(axes.phHi, d.phHi);
        axes.tds = Math.max(axes.tds, d.tds);
      }
    }
    const xHead = [`t (${shownTime().sym})`, 'cell', 'distance (m)'];
    compTableNow = {
      head: ['water', ...xHead, ...POLES.map((p) => `${p.label} (${unit.text})`), ...POLES.map((p) => `${p.label} (% of the ${p.cation ? 'cations' : 'anions'})`), 'type',
        ...(view === 'durov' ? ['pH', 'TDS (mg/kgw)'] : [])],
      rows: all.map((wt) => [wt.measured ? wt.label : `model, ${wt.label}`, showT(wt.t), wt.cell, wt.x !== undefined ? wt.x : null,
        ...POLES.map((p) => wt.w[p.key]), ...POLES.map((p) => (wt.f ? 100 * wt.f[p.key] : null)), wt.f ? faciesOf(wt.f) : null,
        ...(view === 'durov' ? [Number.isFinite(wt.ph) ? wt.ph : null, Number.isFinite(wt.tds) ? wt.tds : null] : [])]),
      name: `rtm_${view}_${along === 'time' ? `cell${cell}` : 'column'}`,
    };
    const where = along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}` : `the column at ${fmtTime(r.t[atIndex])}`;
    const bits = [];
    if (view === 'piper' || view === 'durov') {
      if (view === 'durov') drawDurov(plot, drawable, measuredHere.filter((wt) => wt.f), colorTitle, c, kept, axes);
      else drawPiper(plot, drawable, measuredHere.filter((wt) => wt.f), colorTitle, c, kept);
      const first = drawable[0];
      const last = drawable[drawable.length - 1];
      bits.push(along === 'time'
        ? `${where}: ${faciesOf(first.f)} at ${first.t <= r.t[Math.min(2, r.n - 1)] ? 'the start' : fmtTime(first.t)}`
          + `${drawable.length > 1 ? `, ${faciesOf(last.f)} at ${fmtTime(last.t)}` : ''}`
        : `${where}: ${faciesOf(first.f)} in cell ${first.cell}${drawable.length > 1 ? `, ${faciesOf(last.f)} in cell ${last.cell}` : ''}`);
    } else if (view === 'schoeller') {
      drawSchoeller(plot, drawable, measuredHere.filter((wt) => wt.f), unit, c, kept, axes);
      bits.push(`${where}: ${drawable.length} water${drawable.length === 1 ? '' : 's'}`);
    } else {
      drawStiff(plot, drawable, measuredHere.filter((wt) => wt.f), unit, c, kept, axes);
      bits.push(`${where}: ${drawable.length} water${drawable.length === 1 ? '' : 's'}`);
    }
    if (measuredHere.length) bits.push(`${measuredHere.length} measured`);
    if (kept.said) bits.push(kept.said);
    if (durovSaid) bits.push(durovSaid);
    if (missing.length) bits.push(`the model has no ${missing.join(', ')}`);
    if (asked.bad.length) bits.push(`could not read ${asked.bad.join(', ')}`);
    note.textContent = bits.join('; ');
  }

  /*
    A Composition chart's points of the kept run: along the run at the cell,
    every stored point after "from", a few hundred at most, or along the
    column at its stored time nearest -- each pointAt(kr, i, mc) of it, or
    null. The quantities it reads (needs) are asked of the worker first,
    where they are still to come.
  */
  function besidePoints({ r, along, layer, cell, atIndex }, { needs = [], why: own = '', pointAt }) {
    const k = besideRun();
    if (!k) return {};
    const kr = k.r;
    const km = kr.model;
    const lack = needs.filter((key) => !runHas(kr, key));
    const why = own || (lack.length ? `it has no ${lack.map(labelOf).join(' or ')}`
      : along === 'time' && !(cell < (km.fracture || 1)) ? `it has ${km.fracture || 1} cells`
        : along !== 'time' && !(km.transport && km.fracture > 1) ? 'it was a batch'
          : layer > 0 && !(layer < (km.stride || 1)) ? 'it has no rock matrix' : '');
    if (why) return { said: besideNote(k, why) };
    const kStride = km.stride || 1;
    const cells = along === 'time' ? [modelCell(cell, layer, kr)] : Array.from({ length: km.fracture }, (_, c) => c * kStride + layer);
    const qk = needs.filter((key) => runQuantity(kr, key));
    if (cells.some((mc) => qk.some((key) => quantityPending(key, mc, kr)))) {
      fetchQuantities(qk, cells, kr);
      return { said: `working out ${qk.map(labelOf).join(', ')} for ${k.label}…` };
    }
    const kt = besideTimes(k);
    const pts = [];
    if (along === 'time') {
      const logT = $('rtmCompLogT').checked;
      const tmin = compFrom();
      const idx = [];
      for (let i = 0; i < kr.n; i++) if (!logT || (kt[i] > 0 && kt[i] >= tmin)) idx.push(i);
      const step = Math.max(1, Math.ceil(idx.length / 300));
      for (const i of idx.filter((_, j) => j % step === 0 || j === idx.length - 1)) {
        const pt = pointAt(kr, i, cells[0]);
        if (pt) pts.push({ ...pt, label: fmtTime(kt[i]), t: kt[i], cell });
      }
    } else {
      const j = nearestIndex(kt, r.t[atIndex]);
      cells.forEach((mc, c) => {
        const pt = pointAt(kr, j, mc);
        if (pt) pts.push({ ...pt, label: `cell ${c}`, t: kt[j], cell: c, x: km.centres[c] });
      });
    }
    return { pts, label: k.label, said: pts.length ? besideNote(k) : besideNote(k, 'none of its waters has these') };
  }

  /** The kept run's points as a dashed path of open diamonds. */
  const besideTrace = (kept, x, y, text, c, extra = {}) => ({ type: 'scatter', mode: kept.pts.length > 1 ? 'lines+markers' : 'markers',
    name: kept.label, x, y, line: { color: c.text, width: 1, dash: 'dash' },
    marker: { size: 7, symbol: 'diamond-open', color: c.text, line: { width: 1.4 } }, text, hovertemplate: '%{text}<extra></extra>', ...extra });

  /*
    THE USSL DIAGRAM of irrigation water (Richards 1954, USDA Handbook 60;
    Wilcox 1955, USDA Circular 969, fig. 2): the specific conductance across,
    on a log scale, its salinity classes split at 250, 750 and 2,250 uS/cm,
    and the sodium adsorption ratio up, its sodium classes split by lines that
    fall with the conductance -- SAR = a - b log10 EC, through 10, 18 and 26 at
    100 uS/cm; S1/S2 and S2/S3 through SAR 9 at 168 and 2,250 uS/cm, as the
    Circular's own example has them.
  */
  const USSL_C = [250, 750, 2250];
  const USSL_S = [[18.87, 4.44], [31.31, 6.66], [43.75, 8.87]];
  /** A water's class, C1-S1 to C4-S4, from its conductance, uS/cm, and its SAR. */
  function usslClass(sc, sar) {
    const c = 1 + USSL_C.filter((x) => sc >= x).length;
    const lg = Math.log10(sc);
    const s = 1 + USSL_S.filter(([a, b]) => sar >= a - b * lg).length;
    return `C${c}-S${s}`;
  }

  /**
   * The waters on a USSL diagram: the run's at the cell, every stored point
   * after "from", or along the column at one time, each its conductance and
   * its SAR as the model works them out (the quantities SC and SAR), and
   * what <DATA> measured there -- an SC column and a SAR one, or the SAR from
   * Na, Ca and Mg as the model names them.
   */
  function drawUssl({ r, plot, along, layer, cell, atIndex, fail, note, still }) {
    const keys = ['SC', 'SAR'];
    const lack = keys.filter((k) => !quantityOf(k));
    if (lack.length) {
      fail(lack.includes('SC') ? 'A USSL diagram needs the water\'s specific conductance, which a model has with <CONDUCTANCE>: a water '
        + 'from PHREEQC whose database gives -dw has it.' : 'A USSL diagram needs the sodium adsorption ratio, and the model has no '
        + 'Na, or no Ca and Mg.');
      return;
    }
    const stride = r.model.stride || 1;
    const cells = along === 'time' ? [modelCell(cell, layer)] : Array.from({ length: r.model.fracture }, (_, k) => k * stride + layer);
    const pending = cells.filter((mc) => keys.some((k) => quantityPending(k, mc)));
    if (pending.length) {
      fetchQuantities(keys, cells);
      fail('Working out the conductance and the SAR…');
      return;
    }
    const pts = [];
    let colorTitle;
    if (along === 'time') {
      const mc = cells[0];
      const sc = quantitySeries('SC', mc);
      const sar = quantitySeries('SAR', mc);
      const { idx, logT } = compTimeIndices(r);
      const step = Math.max(1, Math.ceil(idx.length / 300));
      for (const i of idx.filter((_, j) => j % step === 0 || j === idx.length - 1)) {
        if (sc && sar && sc[i] > 0 && Number.isFinite(sar[i])) {
          pts.push({ sc: sc[i], sar: sar[i], color: logT ? Math.log10(showT(r.t[i])) : showT(r.t[i]), label: fmtTime(r.t[i]), t: r.t[i], cell });
        }
      }
      colorTitle = logT ? `log₁₀ time (${shownTime().sym})` : `time (${shownTime().sym})`;
    } else {
      cells.forEach((mc, k) => {
        const sc = quantitySeries('SC', mc);
        const sar = quantitySeries('SAR', mc);
        if (sc && sar && sc[atIndex] > 0 && Number.isFinite(sar[atIndex])) {
          pts.push({ sc: sc[atIndex], sar: sar[atIndex], color: r.model.centres[k], label: `cell ${k}`, t: r.t[atIndex], cell: k,
            x: r.model.centres[k] });
        }
      });
      colorTitle = 'distance (m)';
    }
    if (!pts.length) { fail('No water here has a conductance and a SAR to draw.'); return; }
    // What <DATA> measured: SC, and SAR or Na, Ca and Mg by the model's names for them, in mol/kgw.
    const data = (state.compiled && state.compiled.data) || [];
    const measuredPts = [];
    for (const tab of data) {
      if (tab.kind !== along || !tab.columns.includes('SC')) continue;
      if (along === 'time' && ((tab.cell || 0) !== cell || (tab.layer || 0) !== layer)) continue;
      const col = (row, names) => {
        for (const nm of names) { const j = tab.columns.indexOf(nm); if (j >= 0 && row[j + 1] !== null) return row[j + 1]; }
        return null;
      };
      for (const row of tab.rows) {
        const sc = col(row, ['SC']);
        let sar = col(row, ['SAR']);
        if (sar === null) {
          const na = col(row, ['tot(Na)', 'Na+']);
          const camg = (col(row, ['tot(Ca)', 'Ca+2']) || 0) + (col(row, ['tot(Mg)', 'Mg+2']) || 0);
          sar = na !== null && camg > 0 ? (1000 * na) / Math.sqrt(1000 * camg) : null;
        }
        if (sc > 0 && sar !== null) {
          measuredPts.push({ sc, sar, label: along === 'time' ? `measured, ${fmtTime(row[0])}` : `measured, ${fmtNumber(row[0])} m` });
        }
      }
    }
    // The kept run beside it: its own conductance and SAR.
    const kept = besidePoints({ r, along, layer, cell, atIndex }, { needs: ['SC', 'SAR'], pointAt: (kr, i, mc) => {
      const sc = (quantitySeries('SC', mc, kr) || [])[i];
      const sar = (quantitySeries('SAR', mc, kr) || [])[i];
      return sc > 0 && Number.isFinite(sar) ? { sc, sar } : null;
    } });
    const keptPts = kept.pts || [];
    // On the slider, the conductance and SAR every stored point of every cell comes to, the kept run's too: still axes.
    const span = [];
    if (still && along !== 'time') {
      const bk = keptPts.length ? besideRun() : null;
      for (const run of bk ? [r, bk.r] : [r]) {
        const e = overRun(`${run.runKey}|ussl|${layer}`, run, layer, { lo: Infinity, hi: 0, top: 0 }, (a, i, mc) => {
          const sc = (quantitySeries('SC', mc, run) || [])[i];
          const sar = (quantitySeries('SAR', mc, run) || [])[i];
          if (sc > 0 && Number.isFinite(sar)) { a.lo = Math.min(a.lo, sc); a.hi = Math.max(a.hi, sc); a.top = Math.max(a.top, sar); }
          return a;
        });
        if (e.hi > 0) span.push({ sc: e.lo, sar: 0 }, { sc: e.hi, sar: e.top });
      }
    }
    const all = [...pts, ...measuredPts, ...keptPts, ...span];
    const lo = Math.min(100, ...all.map((p) => p.sc * 0.8));
    const hi = Math.max(5000, ...all.map((p) => p.sc * 1.25));
    const top = Math.max(32, ...all.map((p) => p.sar * 1.1));
    const c = themeColors();
    const traces = [];
    // The sodium lines, falling with the conductance, cut at SAR 0.
    for (const [a, bb] of USSL_S) {
      const x1 = Math.min(hi, 10 ** (a / bb));
      traces.push({ type: 'scatter', mode: 'lines', x: [lo, x1], y: [a - bb * Math.log10(lo), Math.max(0, a - bb * Math.log10(x1))],
        line: { color: c.text, width: 1 }, hoverinfo: 'skip', showlegend: false });
    }
    const hover = (p) => `${esc(p.label)}<br>${usslClass(p.sc, p.sar)}: SC ${fit4(p.sc)} µS/cm, SAR ${fit4(p.sar)}`;
    traces.push({ type: 'scatter', mode: pts.length > 1 ? 'lines+markers' : 'markers', name: 'the model', x: pts.map((p) => p.sc),
      y: pts.map((p) => p.sar), line: { color: c.grid, width: 1 },
      marker: { size: 7, color: pts.length > 1 ? pts.map((p) => p.color) : '#1f77b4', colorscale: 'Viridis', showscale: pts.length > 1,
        colorbar: pts.length > 1 ? { title: { text: colorTitle, side: 'right', font: { size: 11 } }, thickness: 12, outlinewidth: 0,
          tickfont: { size: 10 }, len: 0.7 } : undefined },
      text: pts.map(hover), hovertemplate: '%{text}<extra></extra>' });
    if (keptPts.length) traces.push(besideTrace(kept, keptPts.map((p) => p.sc), keptPts.map((p) => p.sar), keptPts.map(hover), c));
    if (measuredPts.length) {
      traces.push({ type: 'scatter', mode: 'markers', name: 'measured', x: measuredPts.map((p) => p.sc), y: measuredPts.map((p) => p.sar),
        marker: { size: 9, symbol: 'circle-open', color: c.text, line: { width: 1.6 } }, text: measuredPts.map(hover),
        hovertemplate: '%{text}<extra></extra>' });
    }
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.type = 'log';
    layout.xaxis.range = [Math.log10(lo), Math.log10(hi)];
    layout.xaxis.title = { text: 'specific conductance, SC (µS/cm at the water\'s temperature)', font: { size: 11 } };
    layout.yaxis.range = [0, top];
    layout.yaxis.title = { text: 'sodium adsorption ratio, SAR (from meq/kgw)', font: { size: 11 } };
    layout.shapes = USSL_C.map((x) => ({ type: 'line', xref: 'x', yref: 'paper', x0: x, x1: x, y0: 0, y1: 1,
      line: { color: c.text, width: 1, dash: 'dot' } }));
    // The classes' names: C1 to C4 along the top, S1 to S4 at the left between the lines.
    const edges = [lo, ...USSL_C, hi].map(Math.log10);
    layout.annotations = [
      ...[1, 2, 3, 4].map((k) => ({ x: (edges[k - 1] + edges[k]) / 2, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom', showarrow: false,
        text: `C${k}`, font: { size: 11, color: c.text } })),
      ...[0, 1, 2, 3].map((k) => {
        const lg = Math.log10(lo);
        const below = k ? USSL_S[k - 1][0] - USSL_S[k - 1][1] * lg : 0;
        const above = k < 3 ? USSL_S[k][0] - USSL_S[k][1] * lg : top;
        return { x: Math.log10(lo * 1.08), xref: 'x', y: (below + Math.min(above, top)) / 2, yref: 'y', xanchor: 'left', showarrow: false,
          text: `S${k + 1}`, font: { size: 11, color: c.text } };
      }),
    ];
    // Log axes take their annotations' x in log10.
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    compTableNow = { head: ['water', `t (${shownTime().sym})`, 'cell', 'distance (m)', 'SC (µS/cm)', 'SAR', 'class'], name: 'rtm_ussl',
      rows: [...pts.map((p) => [`model, ${p.label}`, showT(p.t), p.cell, p.x === undefined ? null : p.x, p.sc, p.sar, usslClass(p.sc, p.sar)]),
        ...measuredPts.map((p) => [p.label, null, null, null, p.sc, p.sar, usslClass(p.sc, p.sar)])] };
    const first = pts[0];
    const last = pts[pts.length - 1];
    const where = along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}` : `the column at ${fmtTime(r.t[atIndex])}`;
    note.textContent = `${where}: ${usslClass(first.sc, first.sar)} ${along === 'time' ? 'at the start' : `in cell ${first.cell}`}`
      + `${pts.length > 1 ? `, ${usslClass(last.sc, last.sar)} ${along === 'time' ? `at ${fmtTime(last.t)}` : `in cell ${last.cell}`}` : ''}`
      + `${measuredPts.length ? `; ${measuredPts.length} measured` : ''}${kept.said ? `; ${kept.said}` : ''}`;
  }

  /*
    WILCOX'S DIAGRAM (1948, USDA Technical Bulletin 962, figure 1): total
    concentration across, in e.p.m. -- the cations in milliequivalents, here
    meq/kgw -- and percent sodium up, Na x 100 over Ca + Mg + Na + K. Wilcox
    gives the class lines at 7.5, 20 and 30 e.p.m. as numbers and draws the
    three curves that close the classes from above, each from 100 % through
    open circles. The circles here are traced from the bulletin's scan: each
    centred on its white hole, x set by the frame (the class lines fall at
    7.52, 19.95 and 30.00), y by the ticks every 5 % (to 0.14 %). Between them
    a monotone cubic, which lies on the drawn lines to 0.4 % (95 % of their
    ink within 3 pixels of it, 0.6 % at worst); Wilcox's Yuma dot is on the
    scan at 11.95 e.p.m. and 38.92 % for the 12.06 and 39 % he gives it.
  */
  const WILCOX_CURVES = [
    // Below it, excellent to good under 7.5 e.p.m. and good to permissible to 20.
    [[0, 100], [0.81, 90.88], [2.45, 81.3], [4.9, 71.37], [7.45, 64.7], [9.93, 59.76], [12.35, 55.84], [14.84, 52.87],
      [17.41, 50.33], [19.94, 48.12]],
    // Below it, to 20 e.p.m.: permissible to doubtful.
    [[0, 100], [0.72, 98.24], [2.23, 95.71], [4.79, 91.73], [7.31, 88.61], [9.95, 85.79], [12.29, 82.84], [14.83, 80.66],
      [17.26, 78.73], [19.71, 76.62]],
    // Below it, to 30 e.p.m.: doubtful to unsuitable. Above it, or past 30: unsuitable.
    [[0, 100], [0.71, 99.78], [2.22, 99.48], [4.76, 98.7], [7.31, 97.96], [9.84, 97.36], [12.3, 96.73], [14.78, 96.05],
      [17.19, 95.41], [19.79, 94.79], [24.88, 93.66], [29.87, 92.39]],
  ];

  /**
   * A curve through points as a monotone cubic (Fritsch and Carlson's, the
   * ends by the three-point rule kept to the side): it neither overshoots
   * nor turns between the points. Past the last point, its last piece goes on.
   */
  function monotoneCubic(pts) {
    const n = pts.length;
    const xs = pts.map((pt) => pt[0]);
    const ys = pts.map((pt) => pt[1]);
    const h = [];
    const d = [];
    for (let i = 0; i < n - 1; i++) {
      h.push(xs[i + 1] - xs[i]);
      d.push((ys[i + 1] - ys[i]) / h[i]);
    }
    const m = new Array(n).fill(0);
    for (let i = 1; i < n - 1; i++) {
      if (d[i - 1] * d[i] > 0) {
        const w1 = 2 * h[i] + h[i - 1];
        const w2 = h[i] + 2 * h[i - 1];
        m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i]);
      }
    }
    const end = (h0, h1, d0, d1) => {
      const e = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1);
      if (Math.sign(e) !== Math.sign(d0)) return 0;
      if (Math.sign(d0) !== Math.sign(d1) && Math.abs(e) > Math.abs(3 * d0)) return 3 * d0;
      return e;
    };
    m[0] = end(h[0], h[1], d[0], d[1]);
    m[n - 1] = end(h[n - 2], h[n - 3], d[n - 2], d[n - 3]);
    return (x) => {
      let i = 0;
      while (i < n - 2 && x > xs[i + 1]) i++;
      const t = (x - xs[i]) / h[i];
      const t2 = t * t;
      const t3 = t2 * t;
      return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1];
    };
  }
  const WILCOX_AT = WILCOX_CURVES.map(monotoneCubic);

  /** A water's class on Wilcox's diagram, from its cations in meq/kgw and its percent sodium. */
  function wilcoxClass(epm, pctNa) {
    if (epm >= 30 || pctNa >= WILCOX_AT[2](epm)) return 'unsuitable';
    if (epm >= 20 || pctNa >= WILCOX_AT[1](epm)) return 'doubtful to unsuitable';
    if (pctNa >= WILCOX_AT[0](epm)) return 'permissible to doubtful';
    return epm < 7.5 ? 'excellent to good' : 'good to permissible';
  }

  function drawWilcox({ r, plot, along, layer, cell, atIndex, fail, note, still }) {
    if (poleUnit(r.model).scale !== 1000) {
      fail('A Wilcox diagram needs the concentrations in mol/kgw, which a model with ACTIVITY has: its classes are set by the '
        + 'cations\' total in milliequivalents.');
      return;
    }
    const C = compositionOf(r.model);
    const termsOf = (el) => {
      const e = C.elements.find((x) => x.el === el);
      return e ? e.terms.filter((tm) => tm[2] === 'water') : [];
    };
    const terms = { Ca: termsOf('Ca'), Mg: termsOf('Mg'), Na: termsOf('Na'), K: termsOf('K') };
    if (!terms.Na.length) { fail('A Wilcox diagram needs sodium, and the model has none in its water.'); return; }
    const charge = { Ca: 2, Mg: 2, Na: 1, K: 1 };
    const ns = r.model.nspecies;
    // A water's point: its cations in meq/kgw, and the sodium's share of them.
    const pointOf = (c) => {
      const total = c.Ca + c.Mg + c.Na + c.K;
      return total > 0 ? { epm: total, na: (100 * c.Na) / total } : null;
    };
    const waterAt = (i, mc) => {
      const base = i * r.width + mc * ns;
      const c = {};
      for (const el of ['Ca', 'Mg', 'Na', 'K']) {
        let sum = 0;
        for (const [k, n] of terms[el]) sum += n * Math.max(0, r.states[base + k]);
        c[el] = 1000 * charge[el] * sum;
      }
      return pointOf(c);
    };
    const stride = r.model.stride || 1;
    const pts = [];
    let colorTitle;
    if (along === 'time') {
      const mc = modelCell(cell, layer);
      const { idx, logT } = compTimeIndices(r);
      const step = Math.max(1, Math.ceil(idx.length / 300));
      for (const i of idx.filter((_, j) => j % step === 0 || j === idx.length - 1)) {
        const pt = waterAt(i, mc);
        if (pt) pts.push({ ...pt, color: logT ? Math.log10(showT(r.t[i])) : showT(r.t[i]), label: fmtTime(r.t[i]), t: r.t[i], cell });
      }
      colorTitle = logT ? `log₁₀ time (${shownTime().sym})` : `time (${shownTime().sym})`;
    } else {
      for (let k = 0; k < r.model.fracture; k++) {
        const pt = waterAt(atIndex, k * stride + layer);
        if (pt) pts.push({ ...pt, color: r.model.centres[k], label: `cell ${k}`, t: r.t[atIndex], cell: k, x: r.model.centres[k] });
      }
      colorTitle = 'distance (m)';
    }
    if (!pts.length) { fail('No water here has any of the cations to draw.'); return; }
    // What <DATA> measured: the cations by the model's names for them, in mol/kgw; one without a column counts as none.
    const data = (state.compiled && state.compiled.data) || [];
    const measuredPts = [];
    for (const tab of data) {
      if (tab.kind !== along || !['tot(Na)', 'Na+'].some((k) => tab.columns.includes(k))) continue;
      if (along === 'time' && ((tab.cell || 0) !== cell || (tab.layer || 0) !== layer)) continue;
      const col = (row, names) => {
        for (const nm of names) { const j = tab.columns.indexOf(nm); if (j >= 0) return row[j + 1] === null ? 0 : row[j + 1]; }
        return 0;
      };
      for (const row of tab.rows) {
        const pt = pointOf({ Ca: 2000 * col(row, ['tot(Ca)', 'Ca+2']), Mg: 2000 * col(row, ['tot(Mg)', 'Mg+2']),
          Na: 1000 * col(row, ['tot(Na)', 'Na+']), K: 1000 * col(row, ['tot(K)', 'K+']) });
        if (pt) measuredPts.push({ ...pt, label: along === 'time' ? `measured, ${fmtTime(row[0])}` : `measured, ${fmtNumber(row[0])} m` });
      }
    }
    // The kept run beside it: its own cations, from what its species are made of, where it too is in mol/kgw.
    const bk = besideRun();
    let kTerms = null;
    const keptPoint = (kr, i, mc) => {
      if (!kTerms) {
        const KC = compositionOf(kr.model);
        const of = (el) => { const e = KC && KC.elements.find((x) => x.el === el); return e ? e.terms.filter((tm) => tm[2] === 'water') : []; };
        kTerms = { Ca: of('Ca'), Mg: of('Mg'), Na: of('Na'), K: of('K') };
      }
      const base = i * kr.width + mc * kr.model.nspecies;
      const cw = {};
      for (const el of ['Ca', 'Mg', 'Na', 'K']) {
        let sum = 0;
        for (const [k, n] of kTerms[el]) sum += n * Math.max(0, kr.states[base + k]);
        cw[el] = 1000 * charge[el] * sum;
      }
      return pointOf(cw);
    };
    const kept = besidePoints({ r, along, layer, cell, atIndex }, {
      why: bk && poleUnit(bk.r.model).scale !== 1000 ? 'its concentrations are not in mol/kgw' : '', pointAt: keptPoint });
    const keptPts = kept.pts || [];
    // On the slider, the most cations every stored point of every cell comes to, the kept run's too: a still axis.
    const span = [];
    if (still && along !== 'time') {
      const most = (run, at) => overRun(`${run.runKey}|wilcox|${layer}`, run, layer, { hi: 0 }, (a, i, mc) => {
        const pt = at(i, mc);
        if (pt) a.hi = Math.max(a.hi, pt.epm);
        return a;
      }).hi;
      span.push({ epm: most(r, waterAt) });
      if (keptPts.length) span.push({ epm: most(bk.r, (i, mc) => keptPoint(bk.r, i, mc)) });
    }
    const all = [...pts, ...measuredPts, ...keptPts, ...span];
    const right = Math.max(35, ...all.map((p) => p.epm * 1.05));
    const c = themeColors();
    const traces = [];
    // The three curves, each to where its class line rises to meet it, and the lines.
    [20, 20, 30].forEach((to, q) => {
      const xs = Array.from({ length: 241 }, (_, j) => (to * j) / 240);
      traces.push({ type: 'scatter', mode: 'lines', x: xs, y: xs.map(WILCOX_AT[q]), line: { color: c.text, width: 1 }, hoverinfo: 'skip',
        showlegend: false });
    });
    [[7.5, 0], [20, 1], [30, 2]].forEach(([x, q]) => traces.push({ type: 'scatter', mode: 'lines', x: [x, x], y: [0, WILCOX_AT[q](x)],
      line: { color: c.text, width: 1 }, hoverinfo: 'skip', showlegend: false }));
    const hover = (p) => `${esc(p.label)}<br>${wilcoxClass(p.epm, p.na)}: ${fit4(p.epm)} meq/kgw, ${fit4(p.na)} % sodium`;
    traces.push({ type: 'scatter', mode: pts.length > 1 ? 'lines+markers' : 'markers', name: 'the model', x: pts.map((p) => p.epm),
      y: pts.map((p) => p.na), line: { color: c.grid, width: 1 },
      marker: { size: 7, color: pts.length > 1 ? pts.map((p) => p.color) : '#1f77b4', colorscale: 'Viridis', showscale: pts.length > 1,
        colorbar: pts.length > 1 ? { title: { text: colorTitle, side: 'right', font: { size: 11 } }, thickness: 12, outlinewidth: 0,
          tickfont: { size: 10 }, len: 0.7 } : undefined },
      text: pts.map(hover), hovertemplate: '%{text}<extra></extra>' });
    if (keptPts.length) traces.push(besideTrace(kept, keptPts.map((p) => p.epm), keptPts.map((p) => p.na), keptPts.map(hover), c));
    if (measuredPts.length) {
      traces.push({ type: 'scatter', mode: 'markers', name: 'measured', x: measuredPts.map((p) => p.epm), y: measuredPts.map((p) => p.na),
        marker: { size: 9, symbol: 'circle-open', color: c.text, line: { width: 1.6 } }, text: measuredPts.map(hover),
        hovertemplate: '%{text}<extra></extra>' });
    }
    // Wilcox's own scale along the top: the conductance, about a hundred times the e.p.m.
    traces.push({ type: 'scatter', mode: 'lines', x: [0, right * 100], y: [null, null], xaxis: 'x2', hoverinfo: 'skip', showlegend: false });
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.range = [0, right];
    layout.xaxis.title = { text: 'total concentration: the cations, meq/kgw (Wilcox\'s e.p.m.)', font: { size: 11 } };
    layout.xaxis2 = { overlaying: 'x', side: 'top', range: [0, right * 100], showgrid: false, zeroline: false,
      linecolor: c.grid, tickfont: { size: 10, color: c.text },
      title: { text: 'conductance, about 100 × the e.p.m. (µS/cm, as Wilcox took it)', font: { size: 11 } } };
    layout.yaxis.range = [0, 100];
    layout.yaxis.title = { text: 'percent sodium, Na over Ca + Mg + Na + K (%)', font: { size: 11 } };
    layout.margin = { ...layout.margin, t: 56 };
    const label = (x, y, text) => ({ x, y, xref: 'x', yref: 'y', showarrow: false, text, font: { size: 10, color: c.text } });
    layout.annotations = [label(3.75, 8, 'excellent<br>to good'), label(13.75, 8, 'good to<br>permissible'),
      label(25, 8, 'doubtful to<br>unsuitable'), label((30 + right) / 2, 8, 'unsuitable'), label(11, 70, 'permissible<br>to doubtful'),
      label(11, 90.5, 'doubtful to unsuitable'), label(25, 97.6, 'unsuitable')];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    compTableNow = { head: ['water', `t (${shownTime().sym})`, 'cell', 'distance (m)', 'cations (meq/kgw)', 'percent sodium (%)', 'class'],
      name: 'rtm_wilcox',
      rows: [...pts.map((p) => [`model, ${p.label}`, showT(p.t), p.cell, p.x === undefined ? null : p.x, p.epm, p.na, wilcoxClass(p.epm, p.na)]),
        ...measuredPts.map((p) => [p.label, null, null, null, p.epm, p.na, wilcoxClass(p.epm, p.na)])] };
    const first = pts[0];
    const last = pts[pts.length - 1];
    const where = along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}` : `the column at ${fmtTime(r.t[atIndex])}`;
    note.textContent = `${where}: ${wilcoxClass(first.epm, first.na)} ${along === 'time' ? 'at the start' : `in cell ${first.cell}`}`
      + `${pts.length > 1 ? `, ${wilcoxClass(last.epm, last.na)} ${along === 'time' ? `at ${fmtTime(last.t)}` : `in cell ${last.cell}`}` : ''}`
      + `${measuredPts.length ? `; ${measuredPts.length} measured` : ''}`
      + `${kept.said ? `; ${kept.said}${keptPts.length ? `, ${wilcoxClass(keptPts[keptPts.length - 1].epm, keptPts[keptPts.length - 1].na)} `
        + `${along === 'time' ? `at ${fmtTime(keptPts[keptPts.length - 1].t)}` : `in cell ${keptPts[keptPts.length - 1].cell}`}` : ''}` : ''}`;
  }

  /** The variables of a principal component analysis: as named, or the pH and each element dissolved. */
  function pcaKeys(r) {
    const given = state.compPcaVars.split(/[,;]/).map((x) => x.trim()).filter(Boolean);
    if (given.length) return given;
    const keys = quantityOf('pH') ? ['pH'] : [];
    for (const e of compositionOf(r.model).elements) {
      if (e.el === 'H' || e.el === 'O') continue;
      const water = e.terms.filter((tm) => tm[2] === 'water');
      if (quantityOf(`tot(${e.el})`)) keys.push(`tot(${e.el})`);
      else if (water.length === 1) keys.push(r.model.species[water[0][0]]);
    }
    return keys;
  }

  /**
   * Principal components of the waters (RtmModel.pca), as Gibbs Studio gives
   * them: every stored point along the run at a cell, or each cell along the
   * column at a time, a row of the variables named, an amount as its log
   * unless asked not to. The waters at their scores on the first two
   * components, each variable an arrow to its correlation with them, drawn to
   * the waters' scale, and the waters <DATA> measured of every variable put
   * on the same components.
   */
  const pcaRunCache = new Map();
  function drawPca({ r, plot, along, layer, cell, atIndex, fail, note, still }) {
    const keys = pcaKeys(r);
    const names = r.model.species;
    const unknown = keys.filter((k) => !names.includes(k) && !quantityOf(k));
    if (unknown.length) {
      fail(`${unknown.map((k) => `"${k}"`).join(', ')}: no species or quantity of the model. Name them as the time chart does: `
        + 'pH, tot(Ca), Na+, SI(Calcite).');
      return;
    }
    if (keys.length < 2) { fail('Principal components need two variables or more: name them under Of, as pH, tot(Ca), Na+.'); return; }
    const stride = r.model.stride || 1;
    const cells = along === 'time' ? [modelCell(cell, layer)] : Array.from({ length: r.model.fracture }, (_, k) => k * stride + layer);
    const qkeys = keys.filter((k) => !names.includes(k));
    if (cells.some((mc) => qkeys.some((k) => quantityPending(k, mc)))) {
      fetchQuantities(qkeys, cells);
      fail(`Working out ${qkeys.join(', ')}…`);
      return;
    }
    const ns = r.model.nspecies;
    const valueOf = (k, i, mc) => {
      const si = names.indexOf(k);
      if (si >= 0) return r.states[i * r.width + mc * ns + si];
      const series = quantitySeries(k, mc);
      return series ? series[i] : NaN;
    };
    const waters = [];
    let colorTitle;
    if (along === 'time') {
      const mc = cells[0];
      const { idx, logT } = compTimeIndices(r);
      const step = Math.max(1, Math.ceil(idx.length / 400));
      for (const i of idx.filter((_, j) => j % step === 0 || j === idx.length - 1)) {
        waters.push({ row: keys.map((k) => valueOf(k, i, mc)), t: r.t[i], cell, label: fmtTime(r.t[i]),
          color: logT ? Math.log10(showT(r.t[i])) : showT(r.t[i]) });
      }
      colorTitle = logT ? `log₁₀ time (${shownTime().sym})` : `time (${shownTime().sym})`;
    } else {
      cells.forEach((mc, k) => waters.push({ row: keys.map((key) => valueOf(key, atIndex, mc)), t: r.t[atIndex], cell: k,
        x: r.model.centres[k], label: `cell ${k}`, color: r.model.centres[k] }));
      colorTitle = 'distance (m)';
    }
    let usable = waters.filter((w) => w.row.every(Number.isFinite));
    /*
      On the slider, the components are the whole run's: every cell's waters at the stored points (a few thousand at
      most), worked out once a run, and each time's waters put on them -- the axes and the arrows hold still while the
      waters move. Otherwise those drawn.
    */
    const sliding = still && along !== 'time';
    let fitRows = usable.map((w) => w.row);
    if (sliding) {
      const step = Math.max(1, Math.ceil((r.n * cells.length) / 4000));
      fitRows = [];
      for (let i = 0; i < r.n; i += step) for (const mc of cells) fitRows.push(keys.map((k) => valueOf(k, i, mc)));
      fitRows = fitRows.filter((row) => row.every(Number.isFinite));
    }
    // An amount as its log, where every water has some of it -- on the slider every water of the run, so that it is the
    // same from one time to the next, a water then without any of one left off that time.
    const amount = (k) => names.includes(k) || quantityOf(k).axis === 'conc';
    const logged = keys.map((k, j) => state.compPcaLog && amount(k) && fitRows.length > 0 && fitRows.every((row) => row[j] > 0)
      && (sliding || usable.every((w) => w.row[j] > 0)));
    if (sliding) usable = usable.filter((w) => w.row.every((v, j) => !logged[j] || v > 0));
    const shape = (row) => row.map((v, j) => (logged[j] ? Math.log10(v) : v));
    let res;
    const runKey = `${r.runKey}|${keys.join(',')}|${layer}|${logged.join(',')}`;
    try {
      if (sliding && pcaRunCache.has(runKey)) res = pcaRunCache.get(runKey);
      else {
        res = RtmModel.pca(fitRows.map(shape), { names: keys });
        if (sliding) { if (pcaRunCache.size > 20) pcaRunCache.clear(); pcaRunCache.set(runKey, res); }
      }
    } catch (e) {
      fail(e.message);
      return;
    }
    // The waters drawn, on the components: their own scores, or on the slider each put on the run's.
    const scores = sliding ? usable.map((w) => res.project(shape(w.row))) : res.scores;
    const q = res.kept.length;
    const dropped = keys.filter((_, j) => !res.kept.includes(j));
    // What <DATA> measured of every variable, here: put on the model's components.
    const data = (state.compiled && state.compiled.data) || [];
    const measuredPts = [];
    for (const tab of data) {
      if (tab.kind !== along || !keys.every((k) => tab.columns.includes(k))) continue;
      if (along === 'time' && ((tab.cell || 0) !== cell || (tab.layer || 0) !== layer)) continue;
      for (const row of tab.rows) {
        const vals = keys.map((k) => row[tab.columns.indexOf(k) + 1]);
        if (vals.some((v, j) => v === null || !Number.isFinite(v) || (logged[j] && !(v > 0)))) continue;
        measuredPts.push({ s: res.project(shape(vals)), x0: row[0],
          label: along === 'time' ? `measured, ${fmtTime(row[0])}` : `measured, ${fmtNumber(row[0])} m` });
      }
    }
    // The kept run beside it: its waters, every variable of them, put on these components as the measured ones are.
    const kept = besidePoints({ r, along, layer, cell, atIndex }, { needs: keys, pointAt: (kr, i, mc) => {
      const row = keys.map((key) => {
        const si = kr.model.species.indexOf(key);
        return si >= 0 ? kr.states[i * kr.width + mc * kr.model.nspecies + si] : (quantitySeries(key, mc, kr) || [])[i];
      });
      return row.every((v, j) => Number.isFinite(v) && (!logged[j] || v > 0)) ? { s: res.project(shape(row)) } : null;
    } });
    const keptPts = kept.pts || [];
    const c = themeColors();
    const X = scores.map((sc) => sc[0]);
    const Y = scores.map((sc) => sc[1]);
    const hover = (label, sc) => `${esc(label)}<br>PC1 ${sc[0].toFixed(3)}, PC2 ${sc[1].toFixed(3)}`;
    const traces = [{ type: 'scatter', mode: usable.length > 1 ? 'lines+markers' : 'markers', name: 'the model', x: X, y: Y,
      line: { color: c.grid, width: 1 },
      marker: { size: 7, color: usable.map((w) => w.color), colorscale: 'Viridis', showscale: true,
        colorbar: { title: { text: colorTitle, side: 'right', font: { size: 11 } }, thickness: 12, outlinewidth: 0, tickfont: { size: 10 },
          len: 0.7 } },
      text: usable.map((w, i) => hover(w.label, scores[i])), hovertemplate: '%{text}<extra></extra>' }];
    if (keptPts.length) {
      traces.push(besideTrace(kept, keptPts.map((p) => p.s[0]), keptPts.map((p) => p.s[1]),
        keptPts.map((p) => hover(`${p.label}, ${kept.label}`, p.s)), c));
    }
    if (measuredPts.length) {
      traces.push({ type: 'scatter', mode: 'markers', name: 'measured', x: measuredPts.map((p) => p.s[0]), y: measuredPts.map((p) => p.s[1]),
        marker: { size: 9, symbol: 'circle-open', color: c.text, line: { width: 1.6 } },
        text: measuredPts.map((p) => hover(p.label, p.s)), hovertemplate: '%{text}<extra></extra>' });
    }
    // Each variable an arrow to its correlations with the two components, drawn to the scores' reach.
    const corr = res.kept.map((j, k) => [res.vectors[k][0] * Math.sqrt(res.values[0]), res.vectors[k][1] * Math.sqrt(res.values[1])]);
    // On the slider, the whole run's waters as well as those drawn: the arrows' reach and the axes hold still.
    const whole = sliding ? res.scores : [];
    const reach = Math.max(...X.map(Math.abs), ...Y.map(Math.abs), ...measuredPts.flatMap((p) => [Math.abs(p.s[0]), Math.abs(p.s[1])]),
      ...keptPts.flatMap((p) => [Math.abs(p.s[0]), Math.abs(p.s[1])]), ...whole.flatMap((sc) => [Math.abs(sc[0]), Math.abs(sc[1])]));
    const longest = Math.max(...corr.map(([a, b]) => Math.hypot(a, b)));
    const f = longest > 0 && reach > 0 ? (0.85 * reach) / longest : 1;
    const pct = (j) => (100 * res.explained[j]).toFixed(1);
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.title = { text: `PC1, ${pct(0)} % of the variance`, font: { size: 11 } };
    layout.yaxis.title = { text: `PC2, ${pct(1)} %`, font: { size: 11 } };
    layout.xaxis.zeroline = true;
    layout.yaxis.zeroline = true;
    if (sliding) {
      const extent = (j) => {
        const v = [...whole.map((sc) => sc[j]), ...scores.map((sc) => sc[j]), ...measuredPts.map((p) => p.s[j]), ...keptPts.map((p) => p.s[j])];
        const lo = Math.min(...v, -0.85 * reach);
        const hi = Math.max(...v, 0.85 * reach);
        const pad = 0.08 * (hi - lo || 1);
        return [lo - pad, hi + pad];
      };
      layout.xaxis.range = extent(0);
      layout.yaxis.range = extent(1);
    }
    layout.annotations = corr.flatMap(([a, b], k) => [
      { x: a * f, y: b * f, xref: 'x', yref: 'y', ax: 0, ay: 0, axref: 'x', ayref: 'y', text: '', showarrow: true, arrowhead: 2,
        arrowsize: 1, arrowwidth: 1.2, arrowcolor: c.text },
      { x: a * f * 1.08, y: b * f * 1.08, xref: 'x', yref: 'y', showarrow: false, xanchor: a >= 0 ? 'left' : 'right',
        text: esc(`${logged[res.kept[k]] ? 'log ' : ''}${keys[res.kept[k]]}`), font: { size: 11, color: c.text } },
    ]);
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    const pcs = Array.from({ length: q }, (_, j) => `PC${j + 1}`);
    let sum = 0;
    compTableNow = {
      head: ['water', `t (${shownTime().sym})`, 'cell', 'distance (m)', ...pcs], name: `rtm_pca_${along === 'time' ? `cell${cell}` : 'column'}`,
      rows: [...usable.map((w, i) => [`model, ${w.label}`, showT(w.t), w.cell, w.x === undefined ? null : w.x, ...scores[i]]),
        ...measuredPts.map((p) => [p.label, null, null, null, ...p.s])],
      extra: [
        { name: 'loadings', head: ['variable', 'as', 'mean', 'standard deviation', ...pcs],
          rows: res.kept.map((j, k) => [keys[j], logged[j] ? 'log10' : 'as it is', res.mean[k], res.sd[k], ...res.vectors[k]]) },
        { name: 'variance', head: ['component', 'eigenvalue', 'of the variance (%)', 'cumulative (%)'],
          rows: res.values.map((v, j) => { sum += res.explained[j]; return [`PC${j + 1}`, v, 100 * res.explained[j], 100 * sum]; }) },
      ],
    };
    const where = along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}` : `the column at ${fmtTime(r.t[atIndex])}`;
    note.textContent = `${where}: ${usable.length} waters, ${q} variables${dropped.length ? ` (${dropped.join(', ')} the same in every `
      + 'water, left out)' : ''}; PC1 ${pct(0)} % of the variance, PC2 ${pct(1)} %${q > 2 ? `, PC3 ${pct(2)} %` : ''}`
      + `${usable.length < waters.length ? `; ${waters.length - usable.length} waters without every variable left out` : ''}`
      + `${measuredPts.length ? `; ${measuredPts.length} measured, put on them` : ''}`
      + `${kept.said ? `; ${kept.said}${keptPts.length ? ', put on these components' : ''}` : ''}`;
  }

  /**
   * A species' formula mass, g/mol, for the Durov diagram's total dissolved solids: from its name by the standard atomic
   * weights, the model's rule (formulaMass in rtm-model.js); null where it has no formula, or an element without a weight.
   */
  const formulaMass = (name) => RtmModel.formulaMass(name);

  /**
   * What the total dissolved solids of run r are made of: every species
   * dissolved but the water, [[index, g/mol]], and those that have no
   * formula, which it leaves out. A run whose concentrations are not mol/kgw
   * -- no ACTIVITY -- has none.
   */
  function tdsTerms(r) {
    if (poleUnit(r.model).scale !== 1000) return null;
    if (r.tdsTerms) return r.tdsTerms;
    const terms = [];
    const without = [];
    for (const nm of r.model.solutes || []) {
      if (nm === 'H2O') continue;
      const k = r.model.species.indexOf(nm);
      const M = formulaMass(nm);
      if (k < 0) continue;
      if (M === null) without.push(nm); else terms.push([k, M]);
    }
    r.tdsTerms = { terms, without };
    return r.tdsTerms;
  }

  /** The total dissolved solids, mg/kgw, of run r at stored point i in model cell mc. */
  function tdsAt(r, i, mc) {
    const T = tdsTerms(r);
    if (!T) return null;
    const base = i * r.width + mc * r.model.nspecies;
    let s = 0;
    for (const [k, M] of T.terms) s += Math.max(0, r.states[base + k]) * M;
    return 1000 * s;
  }

  /*
    THE DUROV DIAGRAM (S. A. Durov 1948, Doklady Akademii Nauk SSSR 59,
    87-90), as it is drawn: the cations' shares in a triangle on the left
    side of a square -- Na + K at its foot, Ca at its head, Mg at the apex
    -- and the anions' in a triangle on its top side -- Cl to the left,
    HCO3 + CO3 to the right, SO4 at the apex -- and the water in the square
    where the two meet, each triangle's point carried straight into it along
    the axis of its third ion: HCO3 + SO4/2 across and Ca + Mg/2 up, Na-Cl
    waters at the square's foot on the left and Ca-HCO3 at its head on the
    right. Extended, as the programs that draw it extend it (Grapher,
    RockWorks; WQChartPy, Yang et al. 2022, Groundwater 60, 555): the pH in
    a panel under the square at the water's place across, its lowest at the
    top, and the total dissolved solids in a panel to its right at the
    water's place up.
  */
  const DUROV_H = Math.sqrt(3) / 2;
  const DUROV_PANEL = 0.62;
  function durovXY(f) {
    const across = f.HCO3 + f.SO4 / 2;
    const up = f.Ca + f.Mg / 2;
    return { cat: [-DUROV_H * f.Mg, up], an: [across, 1 + DUROV_H * f.SO4], sq: [across, up] };
  }

  /** A round number at or above v, 1, 2 or 5 times a power of ten. */
  function niceAbove(v) {
    if (!(v > 0)) return 1;
    const p = 10 ** Math.floor(Math.log10(v));
    return [1, 2, 5, 10].map((m) => m * p).find((x) => x >= v * (1 - 1e-12));
  }

  /**
   * The Durov diagram of waters (each with its shares f, and its ph and tds
   * where there are), the measured ones and the kept run's.
   */
  function drawDurov(plot, waters, measured, colorTitle, c, kept = {}, axes = null) {
    const H = DUROV_H;
    const P = DUROV_PANEL;
    const kw = (kept.waters || []).filter((wt) => wt && wt.f);
    const all = [...waters, ...kw];
    const withPh = all.filter((wt) => Number.isFinite(wt.ph));
    const withTds = all.filter((wt) => Number.isFinite(wt.tds));
    const hasPh = waters.some((wt) => Number.isFinite(wt.ph));
    const hasTds = waters.some((wt) => Number.isFinite(wt.tds));
    // On the slider, the run's least and greatest pH and its most dissolved solids anywhere: panels that hold still.
    const runPh = axes && Number.isFinite(axes.phLo) ? [axes.phLo, axes.phHi] : [];
    const runTds = axes && axes.tds > 0 ? [axes.tds] : [];
    // The pH from a half unit below the lowest to a half above the highest, a unit at least; the TDS from nothing.
    let phLo = 0;
    let phHi = 1;
    if (hasPh) {
      const v = [...withPh.map((wt) => wt.ph), ...runPh];
      phLo = Math.floor(2 * (Math.min(...v) - 0.25)) / 2;
      phHi = Math.ceil(2 * (Math.max(...v) + 0.25)) / 2;
      if (phHi - phLo < 1) phHi = phLo + 1;
    }
    const tdsTop = hasTds ? niceAbove(1.05 * Math.max(...withTds.map((wt) => wt.tds), ...runTds)) : 1;
    const phY = (ph) => (-P * (ph - phLo)) / (phHi - phLo);
    const tdsX = (tds) => 1 + (P * tds) / tdsTop;
    const traces = [];
    const line = (x, y, color = c.text, width = 1, dash) => traces.push({ type: 'scatter', mode: 'lines', x, y,
      line: { color, width, ...(dash ? { dash } : {}) }, hoverinfo: 'skip', showlegend: false });
    // Every 20 % in both triangles and across the square; the halves of the square dotted.
    for (let k = 1; k < 5; k++) {
      const v = k / 5;
      line([-H * v, -H * v], [v / 2, 1 - v / 2], c.grid, 0.6);
      line([0, -H * (1 - v)], [v, v + (1 - v) / 2], c.grid, 0.6);
      line([0, -H * (1 - v)], [1 - v, (1 - v) / 2], c.grid, 0.6);
      line([v / 2, 1 - v / 2], [1 + H * v, 1 + H * v], c.grid, 0.6);
      line([v, v + (1 - v) / 2], [1, 1 + H * (1 - v)], c.grid, 0.6);
      line([1 - v, (1 - v) / 2], [1, 1 + H * (1 - v)], c.grid, 0.6);
      line([v, v], [0, 1], c.grid, 0.6);
      line([0, 1], [v, v], c.grid, 0.6);
    }
    line([0.5, 0.5], [0, 1], c.text, 0.8, 'dot');
    line([0, 1], [0.5, 0.5], c.text, 0.8, 'dot');
    line([0, 1, 1, 0, 0], [0, 0, 1, 1, 0]);
    line([0, -H, 0], [0, 0.5, 1]);
    line([0, 0.5, 1], [1, 1 + H, 1]);
    if (hasPh) line([0, 1, 1, 0, 0], [0, 0, -P, -P, 0]);
    if (hasTds) line([1, 1 + P, 1 + P, 1, 1], [0, 0, 1, 1, 0]);
    const annotations = [];
    const note = (x, y, text, extra = {}) => annotations.push({ x, y, xref: 'x', yref: 'y', text, showarrow: false,
      font: { size: 11, color: c.text }, ...extra });
    // Na + K just above the corner it shares with the pH's panel, whose first value hangs just below it.
    note(-0.03, 0.01, 'Na + K', { xanchor: 'right', yanchor: 'bottom' });
    note(-0.03, 1, 'Ca', { xanchor: 'right' });
    note(-H - 0.03, 0.5, 'Mg', { xanchor: 'right' });
    note(0, 1.03, 'Cl', { xanchor: 'right', yanchor: 'bottom' });
    note(1.02, 1.03, 'HCO₃ + CO₃', { xanchor: 'left', yanchor: 'bottom' });
    note(0.5, 1 + H + 0.03, 'SO₄', { yanchor: 'bottom' });
    const corner = (x, y, text, xanchor, yanchor) => note(x, y, text, { xanchor, yanchor, font: { size: 10, color: c.text }, opacity: 0.7 });
    corner(0.02, 0.02, 'Na–Cl', 'left', 'bottom');
    corner(0.98, 0.02, 'Na–HCO₃', 'right', 'bottom');
    corner(0.02, 0.98, 'Ca–Cl', 'left', 'top');
    corner(0.98, 0.98, 'Ca–HCO₃', 'right', 'top');
    // The pH's scale on the panel's left; the TDS's under its own panel, at its ends and middle.
    if (hasPh) {
      for (let ph = phLo; ph <= phHi + 1e-9; ph += phHi - phLo > 4 ? 1 : 0.5) {
        line([0, 0.025], [phY(ph), phY(ph)]);
        note(-0.02, phY(ph), String(ph), { xanchor: 'right', yanchor: ph === phLo ? 'top' : 'middle', font: { size: 10, color: c.text } });
      }
      note(-0.16, -P / 2, 'pH', { textangle: -90 });
    }
    if (hasTds) {
      for (let q = 0; q <= 2; q++) {
        const v = (q * tdsTop) / 2;
        line([tdsX(v), tdsX(v)], [0, 0.025]);
        note(tdsX(v), -0.02, fmtNumber(Number(v.toPrecision(6))), { yanchor: 'top', font: { size: 10, color: c.text } });
      }
      note(1 + P / 2, -0.1, 'TDS (mg/kgw)', { yanchor: 'top' });
    }
    // Where a water is in each panel: the triangles and the square always, pH and TDS where it has them.
    const placeOf = (wt) => {
      const xy = durovXY(wt.f);
      return { ...xy, ph: Number.isFinite(wt.ph) ? [xy.sq[0], phY(wt.ph)] : [null, null],
        tds: Number.isFinite(wt.tds) ? [tdsX(wt.tds), xy.sq[1]] : [null, null] };
    };
    const panels = ['cat', 'an', 'sq', ...(hasPh ? ['ph'] : []), ...(hasTds ? ['tds'] : [])];
    const hover = (wt) => `${esc(wt.label)}<br>${faciesOf(wt.f)}<br>`
      + `${CATIONS.map((p) => `${p.label} ${(100 * wt.f[p.key]).toFixed(1)} %`).join(', ')}<br>`
      + `${ANIONS.map((p) => `${p.label} ${(100 * wt.f[p.key]).toFixed(1)} %`).join(', ')}`
      + `${Number.isFinite(wt.ph) ? `<br>pH ${wt.ph.toFixed(2)}` : ''}${Number.isFinite(wt.tds) ? `, TDS ${fit4(wt.tds)} mg/kgw` : ''}`;
    const pts = waters.map(placeOf);
    const colored = waters.length > 1;
    panels.forEach((panel, q) => {
      traces.push({
        type: 'scatter', mode: waters.length > 1 ? 'lines+markers' : 'markers', name: 'the model', legendgroup: 'model',
        showlegend: q === 0, x: pts.map((pt) => pt[panel][0]), y: pts.map((pt) => pt[panel][1]), line: { color: c.grid, width: 1 },
        marker: { size: 7, color: colored ? waters.map((wt) => wt.color) : '#1f77b4', colorscale: 'Viridis', showscale: colored && q === 0,
          colorbar: colored && q === 0 ? { title: { text: colorTitle, side: 'right', font: { size: 11 } }, thickness: 12,
            outlinewidth: 0, tickfont: { size: 10 }, len: 0.7 } : undefined },
        text: waters.map(hover), hovertemplate: '%{text}<extra></extra>',
      });
    });
    if (kw.length) {
      const kp = kw.map(placeOf);
      panels.forEach((panel, q) => {
        traces.push({ type: 'scatter', mode: kw.length > 1 ? 'lines+markers' : 'markers', name: kept.label, legendgroup: 'beside',
          showlegend: q === 0, x: kp.map((pt) => pt[panel][0]), y: kp.map((pt) => pt[panel][1]),
          line: { color: c.text, width: 1, dash: 'dash' }, marker: { size: 7, symbol: 'diamond-open', color: c.text, line: { width: 1.4 } },
          text: kw.map(hover), hovertemplate: '%{text}<extra></extra>' });
      });
    }
    if (measured.length) {
      const mp = measured.map(placeOf);
      ['cat', 'an', 'sq'].forEach((panel, q) => {
        traces.push({ type: 'scatter', mode: 'markers', name: 'measured', legendgroup: 'measured', showlegend: q === 0,
          x: mp.map((pt) => pt[panel][0]), y: mp.map((pt) => pt[panel][1]),
          marker: { size: 9, symbol: 'circle-open', color: c.text, line: { width: 1.6 } },
          text: measured.map(hover), hovertemplate: '%{text}<extra></extra>' });
      });
    }
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.margin = { l: 20, r: 20, t: 14, b: 20 };
    layout.legend = { x: 1, y: 1, xanchor: 'right', yanchor: 'top', font: { size: 10 } };
    layout.xaxis = { visible: false, range: [-H - 0.24, (hasTds ? 1 + P : 1) + 0.14] };
    layout.yaxis = { visible: false, range: [(hasPh ? -P : 0) - (hasTds ? 0.2 : 0.1), 1 + H + 0.12], scaleanchor: 'x', scaleratio: 1 };
    layout.annotations = annotations;
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  function drawPiper(plot, waters, measured, colorTitle, c, kept = {}) {
    const frame = piperFrame(c);
    const traces = [...frame.traces];
    const hover = (wt) => `${esc(wt.label)}<br>${faciesOf(wt.f)}<br>`
      + `${CATIONS.map((p) => `${p.label} ${(100 * wt.f[p.key]).toFixed(1)} %`).join(', ')}<br>`
      + `${ANIONS.map((p) => `${p.label} ${(100 * wt.f[p.key]).toFixed(1)} %`).join(', ')}`;
    const panels = ['cat', 'an', 'dia'];
    const pts = waters.map((wt) => piperXY(wt.f));
    const colored = waters.length > 1;
    panels.forEach((panel, q) => {
      traces.push({
        type: 'scatter', mode: waters.length > 1 ? 'lines+markers' : 'markers', name: 'the model',
        legendgroup: 'model', showlegend: q === 0,
        x: pts.map((pt) => pt[panel][0]), y: pts.map((pt) => pt[panel][1]),
        line: { color: c.grid, width: 1 },
        marker: { size: 7, color: colored ? waters.map((wt) => wt.color) : '#1f77b4', colorscale: 'Viridis',
          showscale: colored && q === 0,
          colorbar: colored && q === 0 ? { title: { text: colorTitle, side: 'right', font: { size: 11 } }, thickness: 12,
            outlinewidth: 0, tickfont: { size: 10 }, len: 0.7 } : undefined },
        text: waters.map(hover), hovertemplate: '%{text}<extra></extra>',
      });
    });
    // The kept run's waters: a dashed path of open diamonds.
    const kw = (kept.waters || []).filter((wt) => wt && wt.f);
    if (kw.length) {
      const kp = kw.map((wt) => piperXY(wt.f));
      panels.forEach((panel, q) => {
        traces.push({ type: 'scatter', mode: kw.length > 1 ? 'lines+markers' : 'markers', name: kept.label, legendgroup: 'beside',
          showlegend: q === 0, x: kp.map((pt) => pt[panel][0]), y: kp.map((pt) => pt[panel][1]),
          line: { color: c.text, width: 1, dash: 'dash' }, marker: { size: 7, symbol: 'diamond-open', color: c.text, line: { width: 1.4 } },
          text: kw.map(hover), hovertemplate: '%{text}<extra></extra>' });
      });
    }
    if (measured.length) {
      const mp = measured.map((wt) => piperXY(wt.f));
      panels.forEach((panel, q) => {
        traces.push({ type: 'scatter', mode: 'markers', name: 'measured', legendgroup: 'measured', showlegend: q === 0,
          x: mp.map((pt) => pt[panel][0]), y: mp.map((pt) => pt[panel][1]),
          marker: { size: 9, symbol: 'circle-open', color: c.text, line: { width: 1.6 } },
          text: measured.map(hover), hovertemplate: '%{text}<extra></extra>' });
      });
    }
    const H = PIPER_H;
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.margin = { l: 20, r: 20, t: 14, b: 20 };
    layout.legend = { x: 0, y: 1, xanchor: 'left', yanchor: 'top', font: { size: 10 } };
    layout.xaxis = { visible: false, range: [-0.12, 2 + PIPER_GAP + 0.12] };
    layout.yaxis = { visible: false, range: [-0.12, 2 * H + PIPER_GAP * H + 0.06], scaleanchor: 'x', scaleratio: 1 };
    layout.annotations = frame.annotations;
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  function drawSchoeller(plot, waters, measured, unit, c, kept = {}, axes = null) {
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const labels = POLES.map((p) => p.label);
    // On a log axis a pole the water has none of is a gap.
    const ys = (wt) => POLES.map((p) => (wt.w[p.key] > 0 ? wt.w[p.key] : null));
    const traces = waters.map((wt, q) => ({ type: 'scatter', mode: 'lines+markers', name: wt.label, x: labels, y: ys(wt),
      line: { color: palette[q % palette.length], width: 1.6 }, marker: { size: 6 },
      hovertemplate: `${esc(wt.label)}: %{x} %{y:.4g} ${esc(unit.text)}<extra></extra>` }));
    // The kept run's water at each one's time or cell, dashed in its colour.
    (kept.waters || []).forEach((wt, q) => {
      if (!wt || q >= waters.length) return;
      traces.push({ type: 'scatter', mode: 'lines+markers', name: `${wt.label}, ${kept.label}`, x: labels, y: ys(wt),
        line: { color: palette[q % palette.length], width: 1.4, dash: 'dash' }, marker: { size: 6, symbol: 'diamond-open' },
        hovertemplate: `${esc(wt.label)}, ${esc(kept.label)}: %{x} %{y:.4g} ${esc(unit.text)}<extra></extra>` });
    });
    for (const wt of measured) {
      traces.push({ type: 'scatter', mode: 'lines+markers', name: wt.label, x: labels, y: ys(wt),
        line: { color: c.text, width: 1.2, dash: 'dot' }, marker: { size: 8, symbol: 'circle-open', color: c.text },
        hovertemplate: `${esc(wt.label)}: %{x} %{y:.4g} ${esc(unit.text)}<extra></extra>` });
    }
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.type = 'category';
    layout.xaxis.title = { text: 'cations, then anions', font: { size: 11 } };
    layout.yaxis.type = 'log';
    layout.yaxis.title = { text: unit.text, font: { size: 11 } };
    // On the slider, from the least the run's ions come to anywhere to the greatest, what was measured too: a still axis.
    if (axes && axes.hi > 0) {
      let lo = axes.lo;
      let hi = axes.hi;
      for (const wt of measured) for (const p of POLES) if (wt.w[p.key] > 0) { lo = Math.min(lo, wt.w[p.key]); hi = Math.max(hi, wt.w[p.key]); }
      const a = Math.log10(lo);
      const b = Math.log10(hi);
      const pad = Math.max(0.05, 0.04 * (b - a));
      layout.yaxis.range = [a - pad, b + pad];
    }
    // A line between the cations and the anions.
    layout.shapes = [{ type: 'line', xref: 'x', yref: 'paper', x0: 2.5, x1: 2.5, y0: 0, y1: 1, line: { color: c.grid, width: 1, dash: 'dot' } }];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  /**
   * Stiff diagrams, one per water, on one scale so that their sizes compare:
   * the cations to the left of zero -- Na + K, Ca, Mg from the top -- and
   * the anions to the right -- Cl, HCO3 + CO3, SO4 -- the points joined.
   */
  function drawStiff(plot, waters, measured, unit, c, kept = {}, axes = null) {
    const all = [...waters, ...measured].slice(0, 12);
    const n = all.length;
    const cols = n <= 3 ? n : n <= 4 ? 2 : n <= 6 ? 3 : 4;
    const rows = Math.ceil(n / cols);
    // One scale for them all; on the slider, the greatest the run's ions come to anywhere.
    let most = axes && axes.hi > 0 ? axes.hi : 0;
    for (const wt of all) for (const p of POLES) most = Math.max(most, wt.w[p.key]);
    for (const wt of kept.waters || []) if (wt) for (const p of POLES) most = Math.max(most, wt.w[p.key]);
    const span = (most || 1) * 1.45;
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.showlegend = false;
    layout.margin = { l: 20, r: 20, t: 24, b: 36 };
    layout.annotations = [];
    const traces = [];
    const gapX = 0.06;
    const gapY = 0.14;
    all.forEach((wt, q) => {
      const col = q % cols;
      const row = Math.floor(q / cols);
      const ax = q === 0 ? '' : String(q + 1);
      const x0 = col / cols + (col ? gapX / 2 : 0);
      const x1 = (col + 1) / cols - (col < cols - 1 ? gapX / 2 : 0);
      const y1 = 1 - row / rows - (row ? gapY / 2 : 0);
      const y0 = 1 - (row + 1) / rows + (row < rows - 1 ? gapY / 2 : 0);
      layout[`xaxis${ax}`] = { domain: [x0, x1], range: [-span, span], anchor: `y${ax}`, zeroline: true, zerolinecolor: c.text,
        gridcolor: c.grid, tickfont: { size: 9 }, exponentformat: 'power', nticks: 5 };
      layout[`yaxis${ax}`] = { domain: [y0, y1], range: [0.4, 3.6], anchor: `x${ax}`, visible: false };
      const w = wt.w;
      const color = wt.measured ? '#ff7f0e' : '#1f77b4';
      traces.push({ type: 'scatter', mode: 'lines+markers', xaxis: `x${ax}`, yaxis: `y${ax}`, fill: 'toself',
        x: [-w.NaK, w.Cl, w.HCO3, w.SO4, -w.Mg, -w.Ca, -w.NaK], y: [3, 3, 2, 1, 1, 2, 3],
        line: { color, width: 1.4 }, marker: { size: 4, color }, fillcolor: wt.measured ? 'rgba(255,127,14,0.25)' : 'rgba(31,119,180,0.25)',
        text: ['Na + K', 'Cl', 'HCO₃ + CO₃', 'SO₄', 'Mg', 'Ca', 'Na + K'].map((nm, j) => `${esc(wt.label)}<br>${nm} `
          + `${[w.NaK, w.Cl, w.HCO3, w.SO4, w.Mg, w.Ca, w.NaK][j].toPrecision(4)} ${esc(unit.text)}`),
        hovertemplate: '%{text}<extra></extra>' });
      // The kept run's water at the same time or cell: its outline, dashed.
      const kw = !wt.measured && kept.waters ? kept.waters[q] : null;
      if (kw) {
        const k = kw.w;
        traces.push({ type: 'scatter', mode: 'lines', xaxis: `x${ax}`, yaxis: `y${ax}`,
          x: [-k.NaK, k.Cl, k.HCO3, k.SO4, -k.Mg, -k.Ca, -k.NaK], y: [3, 3, 2, 1, 1, 2, 3], line: { color: c.text, width: 1.2, dash: 'dash' },
          text: ['Na + K', 'Cl', 'HCO₃ + CO₃', 'SO₄', 'Mg', 'Ca', 'Na + K'].map((nm, j) => `${esc(kw.label)}, ${esc(kept.label)}<br>${nm} `
            + `${[k.NaK, k.Cl, k.HCO3, k.SO4, k.Mg, k.Ca, k.NaK][j].toPrecision(4)} ${esc(unit.text)}`),
          hovertemplate: '%{text}<extra></extra>' });
      }
      const ref = (side) => ({ xref: `x${ax} domain`, yref: `y${ax}`, showarrow: false, font: { size: 9, color: c.text },
        x: side ? 1 : 0, xanchor: side ? 'right' : 'left' });
      [['Na + K', 3], ['Ca', 2], ['Mg', 1]].forEach(([t, y]) => layout.annotations.push({ ...ref(0), y, text: t }));
      [['Cl', 3], ['HCO₃ + CO₃', 2], ['SO₄', 1]].forEach(([t, y]) => layout.annotations.push({ ...ref(1), y, text: t }));
      layout.annotations.push({ xref: `x${ax} domain`, yref: `y${ax} domain`, x: 0.5, y: 1, yanchor: 'bottom', showarrow: false,
        text: esc(wt.label), font: { size: 10, color: c.text } });
    });
    layout.annotations.push({ xref: 'paper', yref: 'paper', x: 0.5, y: 0, yshift: -30, showarrow: false,
      text: `${unit.text}: cations to the left, anions to the right`, font: { size: 11, color: c.text } });
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  /* ---------------------------------------------------------------------
     Diagrams: the model's own chemistry, as PhreePlot draws PHREEQC's

     The water of one cell held at each point of a range of pH, pe or Eh, a
     species' activity or an element's total -- or of two ranges -- and
     speciated there by the model's relations, in the worker (rtmDiagram in
     rtm-worker.js). What comes back is every point's concentrations and
     every quantity, so each way of drawing it is drawn here without asking
     again.
     --------------------------------------------------------------------- */
  // Where each kind of axis starts and ends unless it is given, and what it is called.
  // A held pH is one number, not a range: the neutral water's.
  const DG_RANGES = { pH: ['2', '12'], pe: ['-12', '16'], Eh: ['-0.8', '1.2'], la: ['-10', '-2'], ratio: ['0', '10'],
    tot: ['-8', '-2'], pHheld: ['7', ''] };
  // H+ to the power of the cation's charge: none written for one.
  const powerOf = (z) => (z === 1 ? '' : ({ 2: '²', 3: '³', 4: '⁴' })[z] || `^${z}`);
  const dgLabel = (ax) => (ax.kind === 'pH' ? 'pH' : ax.kind === 'pe' ? 'pe' : ax.kind === 'Eh' ? 'Eh (V)'
    : ax.kind === 'la' ? `log a(${ax.species})`
    : ax.kind === 'ratio' ? `log a(${ax.species})/a(H+)${powerOf(RtmModel.chargeOf(ax.species))}`
    : `log total ${ax.species} in the cell (mol/kgw)`);
  let dgResult = null;
  let dgTableNow = null;
  let dgBusy = false;
  // The map whose boundaries the worker is finding, { res, sig }: one at a time; and the ladder whose couples it is placing.
  let dgBoundsAsked = null;
  let dgLadderAsked = null;

  /** The species an activity can be held of, the solutes; the elements a total can be given of. */
  function dgChoices(kind) {
    const m = state.compiled;
    if (!m) return [];
    if (kind === 'la') return (m.solutes || []).filter((nm) => nm !== 'H2O');
    // A ratio is a cation's activity over that of H+ to the power of its charge.
    if (kind === 'ratio') return (m.solutes || []).filter((nm) => nm !== 'H+' && RtmModel.chargeOf(nm) > 0);
    if (kind === 'tot') return ((m.composition && m.composition.elements) || []).map((e) => e.el);
    return [];
  }

  /** The Diagrams tab's controls, from state.dg and the model compiled. */
  function renderDg() {
    const m = state.compiled;
    const d = state.dg;
    const cells = m ? m.fracture : 1;
    if (!(d.cell < cells)) d.cell = 0;
    $('rtmDgCell').innerHTML = Array.from({ length: cells }, (_, i) => `<option value="${i}"${i === d.cell ? ' selected' : ''}>`
      + `${i}${m && m.centres && cells > 1 ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
    $('rtmDgAt').value = d.at;
    for (const [axis, key] of [['X', 'x'], ['Y', 'y']]) {
      const ax = d[key];
      $(`rtmDg${axis}Kind`).value = ax.kind;
      const choices = dgChoices(ax.kind);
      if (choices.length && !choices.includes(ax.sp)) ax.sp = choices[0];
      const sel = $(`rtmDg${axis}Sp`);
      sel.innerHTML = choices.map((c) => `<option value="${esc(c)}"${c === ax.sp ? ' selected' : ''}>${esc(c)}</option>`).join('');
      sel.hidden = !choices.length;
      $(`rtmDg${axis}From`).value = ax.from;
      $(`rtmDg${axis}To`).value = ax.to;
      $(`rtmDg${axis}N`).value = ax.n;
    }
    $('rtmDgYMore').hidden = !d.y.kind || d.y.kind === 'sat';
    // At saturation: the phases, each by name, an index after one held at other than 0.
    $('rtmDgYSat').hidden = d.y.kind !== 'sat';
    $('rtmDgYPhases').value = d.y.phases || '';
    // The pH held: one number, no range.
    const held = d.y.kind === 'pHheld';
    $('rtmDgYFromWord').hidden = held;
    $('rtmDgYRange').hidden = held;
    $('rtmDgYFrom').setAttribute('aria-label', held ? 'the pH' : 'from');
    $('rtmDgGo').disabled = dgBusy;
  }

  /** The show menu for what was worked out: a range of one thing, or a grid of two. */
  function renderDgShow() {
    const bar = $('rtmDgShowBar');
    bar.hidden = !dgResult;
    if (!dgResult) return;
    const two = !!dgResult.reply.y;
    // A ladder of the couples: along pe or Eh, the pH held, where the model has a couple.
    const ladder = !two && (dgResult.axes[0].kind === 'pe' || dgResult.axes[0].kind === 'Eh') && dgResult.pHAt !== null
      && !!(dgResult.composition && dgResult.composition.couples && dgResult.composition.couples.length);
    // The couples' lines: over pH and pe or Eh, where the model has a couple.
    const kinds = dgResult.axes.map((ax) => ax.kind);
    const lines = two && kinds.includes('pH') && (kinds.includes('pe') || kinds.includes('Eh'))
      && !!(dgResult.composition && dgResult.composition.couples && dgResult.composition.couples.length);
    const opts = two
      ? [['predominance', 'the species that holds most of an element'], ['mixed', 'the species or the phase that holds most of an element'],
        ['phase', 'the phase furthest over saturation, or at it'],
        ['stable', 'the phases of an element, the most stable per mole of it'],
        ...(lines ? [['couples', 'the redox couples, as lines']] : []), ['contour', 'a species or a quantity, as contours']]
      : [...(dgResult.reply.sat ? [['solubility', 'what dissolves: the total at saturation']] : []),
        ...(ladder && !dgResult.reply.sat ? [['ladder', 'the redox couples, as a ladder']] : []),
        ['shares', 'the species of an element, as shares'], ['logc', 'the species of an element, as log concentrations'],
        ['si', 'the saturation indices'], ['quantity', 'a species or a quantity']];
    const d = state.dg;
    if (!opts.some(([v]) => v === d.show)) d.show = opts[0][0];
    $('rtmDgShow').innerHTML = opts.map(([v, t]) => `<option value="${v}"${v === d.show ? ' selected' : ''}>${esc(t)}</option>`).join('');
    // Of a saturation with several phases, the views of one water are of the phase chosen.
    const sats = dgResult.reply.sat || [];
    if (!(d.satAt < sats.length)) d.satAt = 0;
    $('rtmDgSatWrap').hidden = !(sats.length > 1 && d.show !== 'solubility');
    $('rtmDgSat').innerHTML = sats.map((x, j) => `<option value="${j}"${j === d.satAt ? ' selected' : ''}>${esc(dgSatName(x))}</option>`).join('');
    const C = dgResult.composition;
    // For the most stable phase, the elements two phases or more are made of; else those two species or more hold.
    const els = d.show === 'stable' ? dgStableElements()
      : C ? C.elements.filter((e) => (d.in === 'all' ? e.terms : e.terms.filter((tm) => tm[2] === 'water')).length > 1)
        .map((e) => e.el) : [];
    if (els.length && !els.includes(d.el)) d.el = els[0];
    $('rtmDgEl').innerHTML = els.length ? els.map((e) => `<option value="${esc(e)}"${e === d.el ? ' selected' : ''}>${esc(e)}</option>`).join('')
      : '<option value="">none</option>';
    $('rtmDgIn').value = d.in;
    const byEl = ['shares', 'logc', 'predominance', 'mixed', 'stable'].includes(d.show);
    $('rtmDgElWrap').hidden = !byEl;
    // Species and phases: the species in the water, the phases beside them.
    $('rtmDgInWrap').hidden = !(byEl || d.show === 'ladder' || d.show === 'couples') || d.show === 'stable' || d.show === 'mixed';
    $('rtmDgQWrap').hidden = !(d.show === 'quantity' || d.show === 'contour');
    if (!speciesNames().includes(d.q) && !(quantityOf(d.q) && !quantityOf(d.q).of)) d.q = quantityOf('pH') ? 'pH' : (speciesNames()[0] || '');
    $('rtmDgQ').innerHTML = pickerOptions(d.q, false);
  }

  /** The elements two phases or more are made of, aluminium first where it is one: what a stability diagram weighs by. */
  function dgStableElements() {
    const count = new Map();
    for (const q of quantityList()) {
      if (!q.key.startsWith('SI(') || !q.makeup) continue;
      for (const el of Object.keys(q.makeup)) count.set(el, (count.get(el) || 0) + 1);
    }
    const els = [...count].filter(([, n]) => n > 1).map(([el]) => el).sort();
    return els.includes('Al') ? ['Al', ...els.filter((el) => el !== 'Al')] : els;
  }

  /** Reads the calculation's controls into state.dg; a kind changed starts its range afresh. */
  function readDg() {
    const d = state.dg;
    d.cell = Number($('rtmDgCell').value) || 0;
    d.at = $('rtmDgAt').value === 'end' ? 'end' : 'start';
    for (const [axis, key] of [['X', 'x'], ['Y', 'y']]) {
      const ax = d[key];
      const kind = $(`rtmDg${axis}Kind`).value;
      if (kind !== ax.kind) {
        ax.kind = kind;
        if (DG_RANGES[kind]) [ax.from, ax.to] = DG_RANGES[kind];
        ax.sp = '';
        continue;
      }
      ax.sp = $(`rtmDg${axis}Sp`).value;
      ax.from = $(`rtmDg${axis}From`).value.trim();
      ax.to = $(`rtmDg${axis}To`).value.trim();
      ax.n = $(`rtmDg${axis}N`).value.trim();
    }
    d.y.phases = $('rtmDgYPhases').value.trim();
  }

  async function dgGo() {
    if (dgBusy) return;
    if (!state.compiled) { setStatus('The model does not compile: there is nothing to work out a diagram of.', 'error'); return; }
    const d = state.dg;
    const axis = (ax) => ({ kind: ax.kind, species: ax.sp, from: Number(ax.from), to: Number(ax.to), n: Math.round(Number(ax.n)) });
    // The pH held at a number, where nothing varied is the pH: the water speciated at it at every point.
    const held = d.y.kind === 'pHheld';
    // At saturation with each phase named, or with every phase of the model: against the one thing varied.
    const atSat = d.y.kind === 'sat';
    const axes = [axis(d.x), ...(d.y.kind && !held && !atSat ? [axis(d.y)] : [])];
    const bad = axes.find((ax) => !Number.isFinite(ax.from) || !Number.isFinite(ax.to) || !(ax.n >= 2 && ax.n <= 400));
    if (bad) { setStatus('Each axis needs a from, a to and from 2 to 400 points.', 'error'); return; }
    let sat = null;
    if (atSat) {
      if (d.x.kind === 'tot') {
        setStatus('A total varied cannot be set by a saturation as well: vary the pH, the pe, an Eh or an activity.', 'error');
        return;
      }
      const named = d.y.phases.split(/[,;]/).map((x) => x.trim()).filter(Boolean);
      const items = named.length ? named : quantityList().filter((q) => q.key.startsWith('SI(')).map((q) => q.key.slice(3, -1));
      if (!items.length) { setStatus('The model has no phase to hold the water at saturation with: give one in <PHASES>.', 'error'); return; }
      sat = [];
      for (const item of items) {
        const m = /^(\S+)(?:\s+([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?))?$/.exec(item);
        if (!m) {
          setStatus(`"${item}": a phase's name, and after it the saturation index to hold it at where that is not 0: CO2(g) -3.5.`, 'error');
          return;
        }
        sat.push({ phase: m[1], si: m[2] === undefined ? 0 : Number(m[2]) });
      }
    }
    const pHAt = held ? Number(String(d.y.from).trim() || NaN) : null;
    if (held && !Number.isFinite(pHAt)) { setStatus('The pH to hold the water at is a number: 7, say.', 'error'); return; }
    if (held && d.x.kind === 'pH') { setStatus('The pH is what is varied: it cannot be held as well.', 'error'); return; }
    const r = state.result;
    if (d.at === 'end' && !r) { setStatus('Run the model first: the water as it ends the run is what the run leaves.', 'error'); return; }
    const text = d.at === 'end' ? ((state.ran && state.ran.text) || state.text) : state.text;
    const stride = (state.compiled && state.compiled.stride) || 1;
    const ask = (withRun) => request({ type: 'diagram', text, at: d.at, cell: d.cell * stride, axes,
      ...(held ? { pHAt } : {}), ...(sat ? { sat } : {}), ...(d.at === 'end' ? { runKey: r.runKey } : {}),
      ...(withRun ? { t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) },
    (p) => { setProgress(p.frac); setStatus(`Working out the diagram: ${p.done.toLocaleString()} of ${p.npts.toLocaleString()} points…`); });
    dgBusy = true;
    $('rtmDgGo').disabled = true;
    $('rtmStop').disabled = false;
    const started = Date.now();
    setStatus(`Working out the diagram: ${(axes.reduce((n, ax) => n * ax.n, 1) * (sat ? sat.length : 1)).toLocaleString()} points…`);
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      const said = `Diagram worked out in ${((Date.now() - started) / 1000).toFixed(2)} s: `
        + `${(reply.n1 * reply.n2 * (reply.sat ? reply.sat.length : 1)).toLocaleString()} points`
        + `${reply.failed ? `, ${reply.failed.toLocaleString()} of which did not settle and are left blank` : ''}.`;
      // What the boundaries of a map are worked out from, and each map's once they are: null where they could not be.
      dgResult = { reply, axes, composition: state.compiled.composition, at: d.at, cell: d.cell, text, cellIndex: d.cell * stride,
        runKey: d.at === 'end' ? r.runKey : null, said, saidKind: reply.failed ? 'warn' : 'ok', bounds: new Map(), pHAt,
        ladders: new Map(), couples: new Map() };
      // A saturation opens on what dissolves, its element's species ready for the other views.
      if (reply.sat) { d.show = 'solubility'; d.el = reply.sat[0].el; d.satAt = 0; }
      setProgress(null);
      setStatus(said, dgResult.saidKind);
      renderDgShow();
      drawDg();
    } catch (e) {
      setProgress(null);
      setStatus(`The diagram could not be worked out: ${e.message}`, 'error');
    } finally {
      dgBusy = false;
      $('rtmDgGo').disabled = false;
      // The boundaries of the map drawn may be on their way already.
      $('rtmStop').disabled = !state.running && !dgBoundsAsked && !dgLadderAsked;
    }
  }

  /** The phase a saturation's views are of, by name and, where it is not 0, its index. */
  const dgSatName = (s) => `${s.phase}${s.si ? `, SI ${s.si}` : ''}`;

  /** The worked-out waters as the views read them: of a saturation, those at saturation with the phase chosen. */
  function dgReply() {
    const rp = dgResult.reply;
    if (!rp.sat) return rp;
    const s = rp.sat[Math.min(Math.max(0, state.dg.satAt | 0), rp.sat.length - 1)];
    return { ...rp, states: s.states, quant: s.quant, failed: s.failed, satOf: s };
  }

  /** A value of a point: a species' concentration, or a quantity. */
  function dgValue(key, p) {
    const rp = dgReply();
    const k = rp.species.indexOf(key);
    if (k >= 0 && !isQuantity(key)) return rp.states[p * rp.ns + k];
    const q = rp.keys.indexOf(key);
    return q >= 0 ? rp.quant[p * rp.nq + q] : NaN;
  }

  /** The terms of an element the chart draws: in the water, or the whole cell. */
  function dgTerms(el) {
    const C = dgResult.composition;
    const e = C && C.elements.find((x) => x.el === el);
    if (!e) return [];
    return state.dg.in === 'all' ? e.terms : e.terms.filter((tm) => tm[2] === 'water');
  }

  const DG_PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5', '#c49c94', '#f7b6d2', '#c7c7c7', '#dbdb8d', '#9edae5'];

  function drawDg() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartDg');
    const empty = $('rtmDgEmpty');
    const note = $('rtmDgNote');
    dgTableNow = null;
    const fail = (text) => { Plotly.purge(plot); plot.hidden = true; empty.hidden = false; empty.textContent = text; note.textContent = ''; };
    if (!dgResult) { fail('Choose what to vary and work it out: the water of a cell held at each value and speciated by the model\'s '
      + 'own relations, as PhreePlot does with PHREEQC\'s.'); return; }
    empty.hidden = true;
    plot.hidden = false;
    const rp = dgReply();
    const d = state.dg;
    const [ax, ay] = dgResult.axes;
    const sats = dgResult.reply.sat || null;
    const where = `cell ${dgResult.cell} as it ${dgResult.at === 'end' ? 'ends the run' : 'starts'}`
      + `${rp.pHHeld !== null && rp.pHHeld !== undefined ? `, its pH held at ${rp.pHHeld.toFixed(3)}` : ''}`
      + `${rp.satOf && d.show !== 'solubility' ? `, at saturation with ${dgSatName(rp.satOf)}` : ''}`;
    const names = rp.species;
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.title = { text: dgLabel(ax), font: { size: 11 } };
    const xs = Array.from(rp.x);
    if (!rp.y && d.show === 'ladder') { drawDgLadder(plot, note, fail, where); return; }
    if (!rp.y) {
      const traces = [];
      const cols = [];
      if (d.show === 'solubility' && sats) {
        /*
          What dissolves: at each point, each phase's element at the total
          that holds the phase at saturation, its log; with one phase, each
          species of the element beside it, what it holds of it -- 2 for
          Al2(OH)2+4 -- so that the species add up to the total.
        */
        const C = dgResult.composition;
        const waterTerms = (el) => {
          const e = C && C.elements.find((x) => x.el === el);
          return e ? e.terms.filter((tm) => tm[2] === 'water') : [];
        };
        const logOf = (v) => (Number.isFinite(v) && v > 0 ? Math.log10(v) : null);
        for (const sx of sats) {
          const terms = waterTerms(sx.el);
          cols.push([`${sx.el} dissolved, at saturation with ${dgSatName(sx)}`, xs.map((_, p) => logOf(terms.reduce(
            (acc, [k, n]) => acc + n * sx.states[p * rp.ns + k], 0))), { width: 2.6 }]);
        }
        if (sats.length === 1) {
          for (const [k, n] of waterTerms(sats[0].el)) {
            cols.push([`${n === 1 ? '' : `${n} `}${names[k]}`, xs.map((_, p) => logOf(n * sats[0].states[p * rp.ns + k])),
              { width: 1.2, dash: 'dot' }]);
          }
        }
        layout.yaxis.title = { text: 'log concentration (mol/kgw)', font: { size: 11 } };
      } else if (d.show === 'shares' || d.show === 'logc') {
        const terms = dgTerms(d.el);
        if (terms.length < 2) { fail(`No two species hold ${d.el || 'an element'} ${d.in === 'all' ? 'in the cell' : 'in the water'}.`); return; }
        const totals = xs.map((_, p) => terms.reduce((s, [k, n]) => s + n * Math.max(0, rp.states[p * rp.ns + k]), 0));
        for (const [k, n, wh] of terms) {
          const label = wh === 'water' ? names[k] : `${names[k]}, ${WHERE_LABELS[wh]}`;
          const y = xs.map((_, p) => {
            const c = rp.states[p * rp.ns + k];
            if (!Number.isFinite(c)) return null;
            return d.show === 'shares' ? (totals[p] > 0 ? (100 * n * Math.max(0, c)) / totals[p] : null) : (c > 0 ? Math.log10(c) : null);
          });
          // A species never 1 % of the element is left off the shares; every one is on the logs.
          if (d.show === 'shares' && !y.some((v) => v !== null && v >= 1)) continue;
          cols.push([label, y]);
        }
        layout.yaxis.title = { text: d.show === 'shares' ? `share of the ${d.el} ${d.in === 'all' ? 'in the cell' : 'dissolved'} (%)`
          : 'log concentration (mol/kgw)', font: { size: 11 } };
        if (d.show === 'shares') layout.yaxis.range = [0, 102];
      } else if (d.show === 'si') {
        const keys = rp.keys.filter((key) => key.startsWith('SI('));
        if (!keys.length) { fail('The model has no phase to give a saturation index of: <PHASES>, or a mineral in <EQUILIBRIUM>.'); return; }
        for (const key of keys) cols.push([key, xs.map((_, p) => { const v = dgValue(key, p); return Number.isFinite(v) ? v : null; })]);
        layout.yaxis.title = { text: 'saturation index', font: { size: 11 } };
        layout.shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: themeColors().text, width: 1, dash: 'dot' } }];
      } else {
        const key = d.q;
        const q = isQuantity(key) ? quantityOf(key) : null;
        const logged = !q || q.axis === 'conc';
        cols.push([labelOf(key), xs.map((_, p) => { const v = dgValue(key, p); return Number.isFinite(v) && (!logged || v > 0) ? v : null; })]);
        layout.yaxis.type = logged ? 'log' : 'linear';
        layout.yaxis.title = { text: q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : `${key} (mol/kgw)`,
          font: { size: 11 } };
      }
      cols.forEach(([label, y, style], q) => traces.push({ type: 'scatter', mode: 'lines', name: label, x: xs, y,
        line: { color: DG_PALETTE[q % DG_PALETTE.length], width: 1.8, ...(style || {}) },
        hovertemplate: `${esc(label)}: %{y:.4g}<extra></extra>` }));
      // What <DATA> measured of the quantity drawn, in a table against the same thing in the same cell's water: its points.
      let measured = 0;
      let ownWater = 0;
      if (d.show === 'quantity' && !sats) {
        for (const tab of (state.compiled && state.compiled.data) || []) {
          const j = tab.kind === 'speciation' && tab.axis === ax.kind && (ax.kind !== 'tot' || tab.species === ax.species)
            && (tab.cell || 0) === dgResult.cell ? tab.columns.indexOf(d.q) : -1;
          if (j < 0) continue;
          // A water of the table's own, Zn+2 = 1e-4, or held at a pH other than the one drawn's, is not the one drawn: its
          // measurements are the Fit's to draw.
          const tabPH = tab.pH !== null && tab.pH !== undefined ? tab.pH : null;
          const drawnPH = dgResult.pHAt !== null && dgResult.pHAt !== undefined ? dgResult.pHAt : null;
          if ((tab.water && tab.water.length) || tabPH !== drawnPH) { ownWater++; continue; }
          const rows = tab.rows.filter((row) => row[j + 1] !== null);
          measured += rows.length;
          // A total, measured in mol/kgw, where the diagram's axis is its log.
          traces.push({ type: 'scatter', mode: 'markers', name: `${labelOf(d.q)}, measured`,
            x: rows.map((row) => (ax.kind === 'tot' ? Math.log10(row[0]) : row[0])),
            y: rows.map((row) => row[j + 1]), marker: { size: 8, symbol: 'circle-open', color: DG_PALETTE[0], line: { width: 1.6 } },
            hovertemplate: `${esc(labelOf(d.q))}, measured: %{y:.4g}<extra></extra>` });
        }
      }
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      dgTableNow = { head: [dgLabel(ax), ...cols.map(([label]) => label)], rows: xs.map((x, p) => [x, ...cols.map(([, y]) => y[p])]),
        name: d.show === 'solubility' ? `rtm_solubility_${ax.kind}` : `rtm_diagram_${ax.kind}` };
      if (d.show === 'solubility' && sats) {
        const blank = sats.reduce((acc, sx) => acc + sx.failed, 0);
        note.textContent = `${where}; ${xs.length} points, at each ${sats.map((sx) => `the ${sx.el} set by ${dgSatName(sx)}`).join(', ')}`
          + `${blank ? `; ${blank} left blank: they did not settle` : ''}`;
      } else {
        note.textContent = `${where}; ${xs.length} points${rp.failed ? `, ${rp.failed} left blank: they did not settle` : ''}`
          + `${measured ? `; ${measured} measured, from <DATA>` : ''}`
          + `${ownWater ? `; ${ownWater} table${ownWater === 1 ? '' : 's'} of a water of ${ownWater === 1 ? 'its' : 'their'} own left to the Fit tab` : ''}`;
      }
      return;
    }
    // Two axes: a grid, y outer and x inner.
    if (d.show === 'couples') { drawDgCouples(plot, note, fail, where); return; }
    const ys = Array.from(rp.y);
    const n1 = rp.n1;
    const n2 = rp.n2;
    layout.yaxis.title = { text: dgLabel(ay), font: { size: 11 } };
    layout.margin.r = 30;
    const shapes = [];
    if (d.show === 'contour') {
      const key = d.q;
      const q = isQuantity(key) ? quantityOf(key) : null;
      const logged = !q || q.axis === 'conc';
      // To 1e-9: a saturation index held at zero is zero to the rounding either side, which contours would draw as a maze.
      const z = ys.map((_, j) => xs.map((_, i) => {
        const v = dgValue(key, j * n1 + i);
        if (!Number.isFinite(v)) return null;
        const u = logged ? (v > 0 ? Math.log10(v) : null) : v;
        return u === null ? null : Math.round(u * 1e9) / 1e9 + 0;
      }));
      const title = `${logged ? 'log₁₀ ' : ''}${labelOf(key)}`;
      Plotly.react(plot, [{ type: 'contour', x: xs, y: ys, z, colorscale: 'Viridis', connectgaps: false,
        contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 10 } }, line: { width: 0.6 },
        colorbar: { title: { text: title, side: 'right', font: { size: 11 } }, thickness: 14, outlinewidth: 0, tickfont: { size: 10 } },
        hovertemplate: `${esc(dgLabel(ax))} %{x:.3g}<br>${esc(dgLabel(ay))} %{y:.3g}<br>${esc(title)} %{z:.4g}<extra></extra>` },
      ...dgWaterLines(ax, ay, xs, ys)], { ...layout, shapes }, PLOT_CONFIG);
      dgTableNow = { head: [`${dgLabel(ay)} \\ ${dgLabel(ax)}: ${title}`, ...xs], rows: ys.map((y, j) => [y, ...z[j]]),
        name: `rtm_diagram_${ax.kind}_${ay.kind}` };
      note.textContent = `${where}; ${n1} × ${n2} points${rp.failed ? `, ${rp.failed} left blank: they did not settle` : ''}`;
      return;
    }
    // A map of names: at each point, the species holding most of the element, or the phase furthest over saturation.
    const names2 = [];
    const at = new Array(n1 * n2).fill(-1);
    const share = new Array(n1 * n2).fill(null);
    let criterion;
    let nameOf;
    let satKeys = [];
    // Of species and phases, which fields are phases: their points read as an index per mole, the rest as a share.
    let solidNames = null;
    if (d.show === 'predominance') {
      const terms = dgTerms(d.el);
      if (terms.length < 2) { fail(`No two species hold ${d.el || 'an element'} ${d.in === 'all' ? 'in the cell' : 'in the water'}.`); return; }
      const termName = ([k, , wh]) => (wh === 'water' ? names[k] : `${names[k]} (${WHERE_LABELS[wh]})`);
      for (let p = 0; p < n1 * n2; p++) {
        let best = -1;
        let most = -Infinity;
        let sum = 0;
        for (let q = 0; q < terms.length; q++) {
          const [k, n] = terms[q];
          const v = n * rp.states[p * rp.ns + k];
          if (!Number.isFinite(v)) { best = -2; break; }
          sum += Math.max(0, v);
          if (v > most) { most = v; best = q; }
        }
        if (best < 0) continue;
        const label = termName(terms[best]);
        let c = names2.indexOf(label);
        if (c < 0) { c = names2.length; names2.push(label); }
        at[p] = c;
        share[p] = sum > 0 ? (100 * most) / sum : null;
      }
      criterion = { kind: 'predominance', terms: terms.map(([k, n]) => [k, n]) };
      nameOf = (lab) => termName(terms[lab]);
    } else if (d.show === 'mixed') {
      /*
        The species or the phase that holds most of the element: where the
        phase made of it most stable per mole of it -- its saturation index
        over its count of the element, a mineral of the model's there taken
        as at saturation -- is at saturation or over, that phase, the
        element held in a solid there; elsewhere the species dissolved
        holding most of it. A Pourbaix diagram with its solids, the element
        dissolved at the water's total, as the worker's boundaries take it.
      */
      const C = dgResult.composition;
      const e = C && C.elements.find((x) => x.el === d.el);
      const terms = e ? e.terms.filter((tm) => tm[2] === 'water') : [];
      const made = rp.keys.filter((key) => key.startsWith('SI(')).map((key) => {
        const q = quantityOf(key);
        return { key, n: (q && q.makeup && q.makeup[d.el]) || 0, q: rp.keys.indexOf(key), k: names.indexOf(key.slice(3, -1)) };
      }).filter((x) => x.n > 0);
      if (!terms.length) { fail(`No species dissolved holds ${d.el || 'an element'}.`); return; }
      if (!made.length) {
        fail(`No phase is made of ${d.el}: give one in <PHASES>, or draw the species that holds most of it.`);
        return;
      }
      const nt = terms.length;
      for (let p = 0; p < n1 * n2; p++) {
        let best = -1;
        let most = -Infinity;
        for (let j = 0; j < made.length; j++) {
          const x = made[j];
          let v = rp.quant[p * rp.nq + x.q];
          if (x.k >= 0 && rp.states[p * rp.ns + x.k] > 0) v = Math.max(0, v);
          v /= x.n;
          if (Number.isFinite(v) && v > most) { most = v; best = j; }
        }
        let label;
        if (best >= 0 && most >= 0) {
          label = made[best].key.slice(3, -1);
          share[p] = most;
        } else {
          let held = -1;
          let amount = -Infinity;
          let sum = 0;
          for (let q = 0; q < nt; q++) {
            const v = terms[q][1] * rp.states[p * rp.ns + terms[q][0]];
            if (!Number.isFinite(v)) { held = -2; break; }
            sum += Math.max(0, v);
            if (v > amount) { amount = v; held = q; }
          }
          if (held < 0) continue;
          label = names[terms[held][0]];
          share[p] = sum > 0 ? (100 * amount) / sum : null;
        }
        let c = names2.indexOf(label);
        if (c < 0) { c = names2.length; names2.push(label); }
        at[p] = c;
      }
      criterion = { kind: 'mixed', terms: terms.map(([k, n]) => [k, n]), keys: made.map((x) => x.key), per: made.map((x) => x.n) };
      nameOf = (lab) => (lab < nt ? names[terms[lab][0]] : made[lab - nt].key.slice(3, -1));
      solidNames = new Set(made.map((x) => x.key.slice(3, -1)));
    } else if (d.show === 'stable') {
      /*
        Each phase of the element weighed per mole of it: its saturation index
        over its count of the element, the largest the phase the rest would
        turn into with the element kept in the solids -- whatever is dissolved
        of it, which the weighing cancels -- as Garrels and Christ draw them.
      */
      const made = rp.keys.filter((key) => key.startsWith('SI(')).map((key) => {
        const q = quantityOf(key);
        return { key, n: (q && q.makeup && q.makeup[d.el]) || 0 };
      });
      const mine = made.filter((x) => x.n > 0);
      if (mine.length < 2) { fail(`No two phases are made of ${d.el || 'an element'}: <PHASES>, or minerals in <EQUILIBRIUM>.`); return; }
      for (let p = 0; p < n1 * n2; p++) {
        let best = null;
        let most = -Infinity;
        for (const { key, n } of mine) {
          const v = rp.quant[p * rp.nq + rp.keys.indexOf(key)] / n;
          if (Number.isFinite(v) && v > most) { most = v; best = key; }
        }
        if (best === null) continue;
        const label = best.slice(3, -1);
        let c = names2.indexOf(label);
        if (c < 0) { c = names2.length; names2.push(label); }
        at[p] = c;
        share[p] = most;
      }
      criterion = { kind: 'phase', keys: mine.map((x) => x.key), per: mine.map((x) => x.n) };
      nameOf = (lab) => mine[lab].key.slice(3, -1);
      // A phase without it that comes to saturation on the map -- quartz, say -- is a line across it where it does.
      satKeys = made.filter((x) => x.n === 0).map((x) => x.key).filter((key) => {
        const v = Array.from({ length: n1 * n2 }, (_, p) => rp.quant[p * rp.nq + rp.keys.indexOf(key)]).filter(Number.isFinite);
        return v.some((u) => u > 0) && v.some((u) => u < 0);
      });
    } else {
      const keys = rp.keys.filter((key) => key.startsWith('SI('));
      if (!keys.length) { fail('The model has no phase to give a saturation index of: <PHASES>, or a mineral in <EQUILIBRIUM>.'); return; }
      for (let p = 0; p < n1 * n2; p++) {
        let best = null;
        let most = -Infinity;
        for (const key of keys) {
          const v = rp.quant[p * rp.nq + rp.keys.indexOf(key)];
          if (Number.isFinite(v) && v > most) { most = v; best = key; }
        }
        if (best === null) continue;
        // A mineral present is held at saturation, its SI zero to the rounding either side: that is it, not none.
        const label = most >= -1e-6 ? best.slice(3, -1) : 'none over saturation';
        let c = names2.indexOf(label);
        if (c < 0) { c = names2.length; names2.push(label); }
        at[p] = c;
        share[p] = most;
      }
      criterion = { kind: 'phase', keys };
      nameOf = (lab) => (lab === keys.length ? 'none over saturation' : keys[lab].slice(3, -1));
    }
    // The boundaries between the fields, found by the worker once the map is drawn: until they come, the map is its points.
    const sig = JSON.stringify(criterion);
    const bounds = dgResult.bounds.get(sig) || null;
    if (!dgResult.bounds.has(sig)) dgAskBounds(sig, criterion);
    // A saturation line is where the phase's index is zero: the boundary of its own map with none, asked for after the fields.
    const satAsk = satKeys.map((key) => { const cr = { kind: 'phase', keys: [key] }; return { key, sig: JSON.stringify(cr), cr }; });
    if (bounds) {
      const next = satAsk.find((x) => !dgResult.bounds.has(x.sig));
      if (next) dgAskBounds(next.sig, next.cr);
    }
    // A field found only between the points has a colour of its own too.
    if (bounds) for (const f of bounds.fields) if (!names2.includes(nameOf(f.label))) names2.push(nameOf(f.label));
    const m = names2.length;
    const colors = names2.map((nm, c) => (nm === 'none over saturation' ? themeColors().grid : DG_PALETTE[c % DG_PALETTE.length]));
    const scale = m === 1 ? [[0, colors[0]], [1, colors[0]]] : colors.flatMap((col, c) => [[c / m, col], [(c + 1) / m, col]]);
    const z = ys.map((_, j) => xs.map((_, i) => (at[j * n1 + i] >= 0 ? at[j * n1 + i] : null)));
    const text = ys.map((_, j) => xs.map((_, i) => {
      const p = j * n1 + i;
      if (at[p] < 0) return 'did not settle';
      if (d.show === 'stable' || (solidNames && solidNames.has(names2[at[p]]))) return `${names2[at[p]]}, SI over its ${d.el} ${(share[p] + 0).toFixed(2)}`;
      if (d.show === 'mixed') return `${names2[at[p]]}: ${share[p] === null ? '' : `${share[p].toFixed(1)} % of the ${d.el} dissolved`}`;
      return d.show === 'predominance' ? `${names2[at[p]]}: ${share[p] === null ? '' : `${share[p].toFixed(1)} %`}`
        : `${names2[at[p]]}${names2[at[p]] === 'none over saturation' ? `, the nearest SI ${share[p].toFixed(2)}` : `, SI ${(share[p] + 0).toFixed(2)}`}`;
    }));
    // Each field's name where it is: inside its outline, or else at the point of it nearest its middle.
    const gridSpot = (c) => {
      let si = 0;
      let sj = 0;
      let cnt = 0;
      for (let p = 0; p < n1 * n2; p++) if (at[p] === c) { si += p % n1; sj += Math.floor(p / n1); cnt++; }
      if (!cnt) return null;
      const ci = si / cnt;
      const cj = sj / cnt;
      let bestP = -1;
      let gap = Infinity;
      for (let p = 0; p < n1 * n2; p++) {
        if (at[p] !== c) continue;
        const g = (p % n1 - ci) ** 2 + (Math.floor(p / n1) - cj) ** 2;
        if (g < gap) { gap = g; bestP = p; }
      }
      return [xs[bestP % n1], ys[Math.floor(bestP / n1)]];
    };
    const spots = names2.map((nm, c) => {
      const f = bounds && bounds.fields.find((fd) => nameOf(fd.label) === nm);
      return (f && dgFieldSpot(f)) || gridSpot(c);
    });
    layout.annotations = names2.map((nm, c) => (spots[c] ? { x: spots[c][0], y: spots[c][1], text: esc(nm), showarrow: false,
      font: { size: 11, color: '#111' }, bgcolor: 'rgba(255,255,255,0.7)', borderpad: 2 } : null)).filter(Boolean);
    const traces = [{ type: 'heatmap', x: xs, y: ys, z, text, zmin: -0.5, zmax: m - 0.5, colorscale: scale, showscale: false,
      hovertemplate: `${esc(dgLabel(ax))} %{x:.3g}<br>${esc(dgLabel(ay))} %{y:.3g}<br>%{text}<extra></extra>` }];
    if (bounds) {
      // Each field the shape its outlines bound, the largest first so that a field inside another is drawn over it; the
      // boundaries over them all. The points under them still answer the pointer.
      for (const f of [...bounds.fields].sort((p, q) => q.gross - p.gross)) {
        const col = colors[names2.indexOf(nameOf(f.label))];
        const x = [];
        const y = [];
        f.loops.forEach((lp, q) => {
          if (q) { x.push(null); y.push(null); }
          x.push(...lp.x, lp.x[0]);
          y.push(...lp.y, lp.y[0]);
        });
        traces.push({ type: 'scatter', mode: 'lines', name: nameOf(f.label), x, y, fill: 'toself', fillcolor: col,
          line: { color: col, width: 0.5 }, hoverinfo: 'skip', showlegend: false });
      }
      const bx = [];
      const by = [];
      bounds.lines.forEach((ln, q) => {
        if (q) { bx.push(null); by.push(null); }
        bx.push(...ln.x);
        by.push(...ln.y);
      });
      traces.push({ type: 'scatter', mode: 'lines', name: 'boundaries', x: bx, y: by, line: { color: themeColors().text, width: 1.2 },
        hoverinfo: 'skip', showlegend: false });
      layout.xaxis.range = [Math.min(...xs), Math.max(...xs)];
      layout.yaxis.range = [Math.min(...ys), Math.max(...ys)];
    }
    // The saturation lines, dotted, each named where it leaves the map at the top.
    const lined = [];
    for (const { key, sig: lsig } of satAsk) {
      const lb = dgResult.bounds.get(lsig);
      if (!lb || !lb.lines.length) continue;
      const lx = [];
      const lyy = [];
      lb.lines.forEach((ln, q) => {
        if (q) { lx.push(null); lyy.push(null); }
        lx.push(...ln.x);
        lyy.push(...ln.y);
      });
      const nm = key.slice(3, -1);
      traces.push({ type: 'scatter', mode: 'lines', name: `${nm} at saturation`, x: lx, y: lyy, showlegend: false,
        line: { color: themeColors().text, width: 1.2, dash: 'dot' }, hovertemplate: `${esc(nm)} at saturation<extra></extra>` });
      let top = 0;
      lyy.forEach((v, q) => { if (v !== null && v > lyy[top]) top = q; });
      layout.annotations.push({ x: lx[top], y: lyy[top], text: esc(nm), showarrow: false, yanchor: 'top', xanchor: 'left',
        xshift: 3, font: { size: 10, color: themeColors().text } });
      lined.push(nm);
    }
    Plotly.react(plot, [...traces, ...dgWaterLines(ax, ay, xs, ys)], layout, PLOT_CONFIG);
    const counts = names2.map((nm, c) => [nm, at.filter((v) => v === c).length]).filter(([, k]) => k > 0);
    dgTableNow = { head: [dgLabel(ax), dgLabel(ay), d.show === 'predominance' ? `the species holding most of the ${d.el}`
      : d.show === 'mixed' ? `the species or the phase holding most of the ${d.el}`
        : d.show === 'stable' ? `the phase most stable per mole of ${d.el}` : 'the phase furthest over saturation, or at it',
    d.show === 'predominance' ? 'its share (%)' : d.show === 'mixed' ? `a species' share of the ${d.el} dissolved (%), or a phase's SI over its ${d.el}`
      : d.show === 'stable' ? `its SI over its ${d.el}` : 'its SI'],
    rows: at.map((c, p) => [xs[p % n1], ys[Math.floor(p / n1)], c >= 0 ? names2[c] : null, share[p]]),
    name: `rtm_diagram_${d.show}` };
    if (bounds) {
      // The Excel workbook's second sheet: each boundary's points, and where three fields meet.
      const rows = [];
      bounds.lines.forEach((ln, q) => ln.x.forEach((x, i) => rows.push([q + 1, nameOf(ln.a), nameOf(ln.b), x, ln.y[i]])));
      bounds.junctions.filter((jn) => jn.solved).forEach((jn) => rows.push(['where three meet', ...jn.labels.map(nameOf), jn.x, jn.y]));
      dgTableNow.extra = [{ name: 'boundaries', head: ['boundary', 'between', 'and', dgLabel(ax), dgLabel(ay)], rows }];
    }
    const meet = bounds ? bounds.junctions.filter((jn) => jn.solved).length : 0;
    note.textContent = `${where}; ${n1} × ${n2} points: ${counts.map(([nm, k]) => `${nm} ${k}`).join(', ')}`
      + `${rp.failed ? `; ${rp.failed} left blank: they did not settle` : ''}`
      + (bounds ? `; the boundaries between them found to 1e-10${meet ? `, and ${meet} point${meet === 1 ? '' : 's'} where three fields meet` : ''}`
        : dgBoundsAsked && dgBoundsAsked.res === dgResult && dgBoundsAsked.sig === sig ? '; finding the boundaries between them…' : '')
      + (lined.length ? `; dotted, where ${lined.join(' and ')} ${lined.length === 1 ? 'is' : 'are'} at saturation` : '');
  }

  /**
   * Where a field's name goes: the middle of its largest outline, if that is
   * inside the field -- inside an odd number of its outlines, a field within
   * it being a hole -- or null.
   */
  function dgFieldSpot(f) {
    let big = null;
    let most = 0;
    for (const lp of f.loops) {
      let a = 0;
      let cx = 0;
      let cy = 0;
      for (let q = 0; q < lp.x.length; q++) {
        const r = (q + 1) % lp.x.length;
        const cr = lp.x[q] * lp.y[r] - lp.x[r] * lp.y[q];
        a += cr;
        cx += (lp.x[q] + lp.x[r]) * cr;
        cy += (lp.y[q] + lp.y[r]) * cr;
      }
      if (Math.abs(a) > most) { most = Math.abs(a); big = [cx / (3 * a), cy / (3 * a)]; }
    }
    if (!big) return null;
    const [px, py] = big;
    let inside = false;
    for (const lp of f.loops) {
      const n = lp.x.length;
      for (let q = 0, r = n - 1; q < n; r = q++) {
        if ((lp.y[q] > py) !== (lp.y[r] > py) && px < ((lp.x[r] - lp.x[q]) * (py - lp.y[q])) / (lp.y[r] - lp.y[q]) + lp.x[q]) inside = !inside;
      }
    }
    return inside ? big : null;
  }

  /**
   * Asks the worker for the boundaries of the map on show (rtmDiagramBounds
   * in rtm-worker.js), one map at a time: when they come the chart is drawn
   * again, and asks for whatever it shows then. The water the diagram held is
   * held again between its points, so a diagram of the water as a run left
   * it needs that run still.
   */
  async function dgAskBounds(sig, criterion) {
    const res = dgResult;
    if (!res || dgBoundsAsked) return;
    if (res.at === 'end' && !(state.result && state.result.runKey === res.runKey)) return;
    dgBoundsAsked = { res, sig };
    const r = state.result;
    const started = Date.now();
    const ask = (withRun) => request({ type: 'diagramBounds', text: res.text, at: res.at, cell: res.cellIndex, axes: res.axes,
      grid: res.reply.states, criterion, ...(res.at === 'end' ? { runKey: res.runKey } : {}),
      ...(withRun ? { t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) },
    (p) => {
      setProgress(p.frac);
      setStatus(`Finding the diagram's boundaries: ${p.done.toLocaleString()} of ${p.npts.toLocaleString()} edges between its points…`);
    });
    $('rtmStop').disabled = false;
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      res.bounds.set(sig, reply);
      if (dgResult === res) {
        const meet = reply.junctions.filter((jn) => jn.solved).length;
        const found = `found in ${((Date.now() - started) / 1000).toFixed(2)} s`
          + `${meet ? `, with ${meet} point${meet === 1 ? '' : 's'} where three fields meet` : ''}`;
        // The first after the diagram goes with what was said of it.
        if (!res.boundsSaid) setStatus(`${res.said.replace(/\.$/, '')}; its boundaries ${found}.`, res.saidKind);
        else setStatus(`The diagram's boundaries ${found}.`, 'ok');
        res.boundsSaid = true;
      }
    } catch (e) {
      res.bounds.set(sig, null);
      if (dgResult === res) setStatus(`The diagram's boundaries could not be found: ${e.message}`, 'warn');
    } finally {
      setProgress(null);
      if (dgBoundsAsked && dgBoundsAsked.res === res) dgBoundsAsked = null;
      $('rtmStop').disabled = !state.running;
      if (dgResult) drawDg();
    }
  }

  /**
   * The redox couples as a ladder, as the textbooks draw one: each where it
   * turns over at the pH held -- the pe, or the Eh, at which the water holds
   * as much of the element in the couple's oxidised state as in its reduced
   * one, found by the worker between the diagram's points (rtmDiagramLadder)
   * -- a rung across, its oxidised species on the left and its reduced on
   * the right; where water gives way at 25 C, O2 and H2 at 1 atm, dashed;
   * and the water's own pe, dotted. A couple that does not turn over in the
   * range, or whose element the water has none of, is said in the note.
   */
  function drawDgLadder(plot, note, fail, where) {
    const res = dgResult;
    const rp = res.reply;
    const d = state.dg;
    const ax = res.axes[0];
    const C = res.composition;
    const inCell = d.in === 'all';
    const sig = `ladder|${d.in}`;
    const names = rp.species;
    const items = dgCoupleItems(C, inCell, names);
    const asked = items.filter((it) => !it.untold.length && it.hi.length && it.lo.length);
    if (!res.ladders.has(sig)) {
      Plotly.purge(plot);
      note.textContent = `${where}; finding where each couple turns over…`;
      dgAskLadder(sig, asked);
      return;
    }
    const lad = res.ladders.get(sig);
    if (!lad) { fail('Where the couples turn over could not be found: work the diagram out again.'); return; }
    const L = lad.reply;
    const isEh = ax.kind === 'Eh';
    const xs = Array.from(rp.x);
    const lo = Math.min(...xs);
    const hi = Math.max(...xs);
    const peOf = (v) => (isEh ? v / L.ehPe : v);
    const ehOf = (v) => (isEh ? v : v * L.ehPe);
    const said = (v) => (isEh ? `Eh ${v.toFixed(3)} V` : `pe ${v.toFixed(2)}`);
    const nameOf = (cp) => `${cp.ox.join(' + ')}/${cp.red.join(' + ')}`;
    const stateName = (el, v) => `${el}(${Number(v.toFixed(3))})`;
    const els = [...new Set(C.couples.map((cp) => cp.el))];
    const colourOf = (el) => DG_PALETTE[els.indexOf(el) % DG_PALETTE.length];
    const rungs = [];
    const above = [];
    const below = [];
    const none = [];
    lad.asked.forEach((it, q) => {
      const r = L.rungs[q];
      if (r.roots.length) for (const v of r.roots) rungs.push({ it, v });
      else if (r.first === null) none.push(it);
      // Reduced all the way up, it turns over above; oxidised all the way down, below.
      else if (r.first < 0 && r.last < 0) above.push(it);
      else if (r.first > 0 && r.last > 0) below.push(it);
      else none.push(it);
    });
    rungs.sort((a, b) => a.v - b.v);
    // The labels a line apart at least, pushed up from the lowest, then down from the top where they run past it.
    const gap = (hi - lo) * 0.045;
    const pos = rungs.map((r) => r.v);
    for (let i = 1; i < pos.length; i++) if (pos[i] - pos[i - 1] < gap) pos[i] = pos[i - 1] + gap;
    if (pos.length && pos[pos.length - 1] > hi - gap / 2) {
      pos[pos.length - 1] = hi - gap / 2;
      for (let i = pos.length - 2; i >= 0; i--) if (pos[i + 1] - pos[i] < gap) pos[i] = pos[i + 1] - gap;
    }
    const c = themeColors();
    const traces = [];
    const annotations = [];
    const label = (x, y, text, anchor, color) => annotations.push({ x, y, xref: 'x', yref: 'y', text: esc(text), showarrow: false,
      xanchor: anchor, yanchor: 'middle', font: { size: 11, color } });
    rungs.forEach(({ it, v }, i) => {
      const col = colourOf(it.cp.el);
      const hover = `${esc(nameOf(it.cp))}: ${stateName(it.cp.el, it.cp.hi)} over ${stateName(it.cp.el, it.cp.lo)}<br>`
        + `pe ${peOf(v).toFixed(4)}, Eh ${ehOf(v).toFixed(4)} V, at pH ${L.pHHeld}<extra></extra>`;
      traces.push({ type: 'scatter', mode: 'lines', x: [0.3, 0.7], y: [v, v], showlegend: false, line: { color: col, width: 2.4 },
        hovertemplate: hover });
      // Where a label was moved off its rung, a short line from the rung to it.
      if (Math.abs(pos[i] - v) > 1e-12) {
        for (const [a, z] of [[0.3, 0.27], [0.7, 0.73]]) {
          traces.push({ type: 'scatter', mode: 'lines', x: [a, z], y: [v, pos[i]], showlegend: false, hoverinfo: 'skip',
            line: { color: col, width: 0.8 } });
        }
      }
      const off = Math.abs(pos[i] - v) > 1e-12 ? 0.03 : 0;
      label(0.29 - off, pos[i], it.cp.ox.join(' + '), 'right', col);
      label(0.71 + off, pos[i], `${it.cp.red.join(' + ')}   ${said(v)}`, 'left', col);
    });
    // Where water gives way at 25 C, at the pH held: O2 above, H2 below, at 1 atm.
    const per25 = isEh ? RtmModel.ehPerPe(298.15) : 1;
    for (const [sum, text] of [[20.78, 'O₂ at 1 atm, 25 °C'], [0, 'H₂ at 1 atm, 25 °C']]) {
      const v = per25 * (sum - L.pHHeld);
      if (!(v >= lo && v <= hi)) continue;
      traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [v, v], showlegend: false, line: { color: c.text, width: 1.2, dash: 'dash' },
        hovertemplate: `water gives way: ${text}, ${said(v)}<extra></extra>` });
      annotations.push({ x: 1, y: v, xref: 'x', yref: 'y', text: `water and ${text}`, showarrow: false, xanchor: 'right',
        yanchor: sum ? 'bottom' : 'top', font: { size: 10, color: c.text } });
    }
    // The water itself, at its own pH.
    if (L.waterPe !== null && L.waterPe !== undefined) {
      const v = isEh ? L.waterPe * L.ehPe : L.waterPe;
      if (v >= lo && v <= hi) {
        const its = `this water, ${said(v)}${L.waterPH !== null ? ` at its own pH, ${L.waterPH.toFixed(2)}` : ''}`;
        traces.push({ type: 'scatter', mode: 'lines', x: [0, 1], y: [v, v], showlegend: false, line: { color: c.text, width: 1, dash: 'dot' },
          hovertemplate: `${esc(its)}<extra></extra>` });
        annotations.push({ x: 0, y: v, xref: 'x', yref: 'y', text: esc(its), showarrow: false, xanchor: 'left', yanchor: 'bottom',
          font: { size: 10, color: c.text } });
      }
    }
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis = { visible: false, range: [0, 1], fixedrange: true };
    layout.yaxis = { ...layout.yaxis, title: { text: dgLabel(ax), font: { size: 11 } }, range: [lo, hi], zeroline: false };
    layout.annotations = annotations;
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    dgTableNow = { head: ['couple', 'oxidised', 'reduced', 'pe', 'Eh (V)'],
      rows: rungs.slice().reverse().map(({ it, v }) => [nameOf(it.cp), stateName(it.cp.el, it.cp.hi), stateName(it.cp.el, it.cp.lo),
        peOf(v), ehOf(v)]), name: `rtm_ladder_pH_${L.pHHeld}` };
    const parts = [`${where}; ${rungs.length} couple${rungs.length === 1 ? '' : 's'} turn${rungs.length === 1 ? 's' : ''} over here`];
    if (rungs.length === 1) parts[0] += `: ${nameOf(rungs[0].it.cp)} at ${said(rungs[0].v)}`;
    else if (rungs.length) parts[0] += `, from ${nameOf(rungs[rungs.length - 1].it.cp)} at ${said(rungs[rungs.length - 1].v)} down to `
      + `${nameOf(rungs[0].it.cp)} at ${said(rungs[0].v)}`;
    if (above.length) parts.push(`above ${said(hi)}: ${above.map((it) => nameOf(it.cp)).join(', ')}`);
    if (below.length) parts.push(`below ${said(lo)}: ${below.map((it) => nameOf(it.cp)).join(', ')}`);
    if (none.length) parts.push(`none of the element ${inCell ? 'in the cell' : 'in the water'}: ${none.map((it) => nameOf(it.cp)).join(', ')}`);
    const missing = items.filter((it) => !it.untold.length && !(it.hi.length && it.lo.length));
    if (missing.length) {
      parts.push(missing.map((it) => `${nameOf(it.cp)}, ${stateName(it.cp.el, it.hi.length ? it.cp.lo : it.cp.hi)} not `
        + `${inCell ? 'in the cell' : 'in the water'}`).join('; '));
    }
    const untold = items.filter((it) => it.untold.length);
    if (untold.length) parts.push(`what state the ${untold.map((it) => it.cp.el).join(', ')} of ${[...new Set(untold.flatMap((it) => it.untold))].join(', ')} `
      + 'is in is not told by a name or a relation');
    if (L.unsolved) parts.push(`${L.unsolved} not found exactly: the water did not settle between two points`);
    note.textContent = parts.join('; ');
  }

  /** Each couple's two states, in the water or the whole cell, and any species of its element whose state is untold. */
  function dgCoupleItems(C, inCell, names) {
    return C.couples.map((cp) => {
      const e = C.elements.find((x) => x.el === cp.el);
      const terms = e ? e.terms.filter((tm) => inCell || tm[2] === 'water') : [];
      return { cp, hi: terms.filter((tm) => tm[3] === cp.hi).map(([k, n]) => [k, n]),
        lo: terms.filter((tm) => tm[3] === cp.lo).map(([k, n]) => [k, n]),
        untold: terms.filter((tm) => tm[3] === null).map(([k]) => names[k]) };
    });
  }

  /**
   * The redox couples across a map of pH and pe or Eh, as the textbooks draw a
   * water's couples: each couple's line, where the water holds as much of its
   * element in the oxidised state as in the reduced one -- the redox ladder's
   * rung at every pH -- found by the worker as a map's boundaries are
   * (rtmDiagramCouples); a colour to each element, a dash to each of its
   * couples; where water gives way, dashed; and the water itself, marked.
   */
  function drawDgCouples(plot, note, fail, where) {
    const res = dgResult;
    const rp = res.reply;
    const d = state.dg;
    const [ax, ay] = res.axes;
    const C = res.composition;
    const inCell = d.in === 'all';
    const sig = `couples|${d.in}`;
    const items = dgCoupleItems(C, inCell, rp.species);
    const asked = items.filter((it) => !it.untold.length && it.hi.length && it.lo.length);
    if (!res.couples.has(sig)) {
      Plotly.purge(plot);
      note.textContent = `${where}; finding where each couple turns over across the map…`;
      dgAskCouples(sig, asked);
      return;
    }
    const got = res.couples.get(sig);
    if (!got) { fail('Where the couples turn over could not be found: work the diagram out again.'); return; }
    const R = got.reply;
    const xs = Array.from(rp.x);
    const ys = Array.from(rp.y);
    const nameOf = (cp) => `${cp.ox.join(' + ')}/${cp.red.join(' + ')}`;
    const els = [...new Set(C.couples.map((cp) => cp.el))];
    const colourOf = (el) => DG_PALETTE[els.indexOf(el) % DG_PALETTE.length];
    const DASHES = ['solid', 'dash', 'dot', 'dashdot', 'longdash'];
    const seen = new Map();
    const traces = [];
    const rows = [];
    const across = [];
    const whole = [];
    got.asked.forEach((it, q) => {
      const c = R.couples[q];
      const el = it.cp.el;
      const nth = seen.get(el) || 0;
      seen.set(el, nth + 1);
      const name = nameOf(it.cp);
      const states = `${el}(${Number(it.cp.hi.toFixed(3))})/${el}(${Number(it.cp.lo.toFixed(3))})`;
      if (!c.lines.length) {
        whole.push(`${name}, ${c.states.length ? (c.states[0] === 0 ? 'oxidised' : 'reduced') : 'none of it'} all over`);
        return;
      }
      across.push(name);
      c.lines.forEach((ln, j) => {
        traces.push({ type: 'scatter', mode: 'lines', x: ln.x, y: ln.y, name, legendgroup: name, showlegend: j === 0,
          line: { color: colourOf(el), width: 2, dash: DASHES[nth % DASHES.length] },
          hovertemplate: `${esc(name)}, ${states}: as much in each<br>${esc(dgLabel(ax))} %{x:.4g}, ${esc(dgLabel(ay))} %{y:.4g}<extra></extra>` });
        ln.x.forEach((x, i) => rows.push([name, x, ln.y[i]]));
      });
    });
    traces.push(...dgWaterLines(ax, ay, xs, ys));
    // The water itself, at its own pH and pe, its Eh at its own temperature.
    if (R.waterPH !== null && R.waterPe !== null) {
      const at = (kind) => (kind === 'pH' ? R.waterPH : kind === 'pe' ? R.waterPe : R.waterPe * R.ehPe);
      const wx = at(ax.kind);
      const wy = at(ay.kind);
      const inside = (v, list) => v >= Math.min(...list) && v <= Math.max(...list);
      if (inside(wx, xs) && inside(wy, ys)) {
        traces.push({ type: 'scatter', mode: 'markers', x: [wx], y: [wy], name: 'this water',
          marker: { size: 10, symbol: 'circle-open', color: themeColors().text, line: { width: 2 } },
          hovertemplate: `this water: pH ${R.waterPH.toFixed(2)}, pe ${R.waterPe.toFixed(2)}<extra></extra>` });
      }
    }
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis = { ...layout.xaxis, title: { text: dgLabel(ax), font: { size: 11 } }, range: [Math.min(...xs), Math.max(...xs)] };
    layout.yaxis = { ...layout.yaxis, title: { text: dgLabel(ay), font: { size: 11 } }, range: [Math.min(...ys), Math.max(...ys)] };
    layout.legend = { font: { size: 10 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    dgTableNow = { head: ['couple', dgLabel(ax), dgLabel(ay)], rows, name: `rtm_couples_${ax.kind}_${ay.kind}` };
    const parts = [`${where}; ${across.length} couple${across.length === 1 ? '' : 's'} turn${across.length === 1 ? 's' : ''} over on `
      + `this map, each where the water holds as much of its element in either state`];
    if (whole.length) parts.push(`not on it: ${whole.join('; ')}`);
    const missing = items.filter((it) => !it.untold.length && !(it.hi.length && it.lo.length));
    if (missing.length) {
      parts.push(missing.map((it) => `${nameOf(it.cp)}, ${it.cp.el}(${Number((it.hi.length ? it.cp.lo : it.cp.hi).toFixed(3))}) not `
        + `${inCell ? 'in the cell' : 'in the water'}`).join('; '));
    }
    const untold = items.filter((it) => it.untold.length);
    if (untold.length) parts.push(`what state the ${untold.map((it) => it.cp.el).join(', ')} of ${[...new Set(untold.flatMap((it) => it.untold))].join(', ')} `
      + 'is in is not told by a name or a relation');
    const unsolved = R.couples.reduce((n, c) => n + c.unsolved, 0);
    if (unsolved) parts.push(`${unsolved} point${unsolved === 1 ? '' : 's'} of a line not found exactly: the water did not settle there`);
    note.textContent = parts.join('; ');
  }

  /** Each couple's line across the map, found by the worker from the diagram's points; one map at a time. */
  async function dgAskCouples(sig, asked) {
    const res = dgResult;
    if (!res || dgLadderAsked) return;
    if (res.at === 'end' && !(state.result && state.result.runKey === res.runKey)) return;
    dgLadderAsked = { res, sig, couples: true };
    const r = state.result;
    const started = Date.now();
    const ask = (withRun) => request({ type: 'diagramCouples', text: res.text, at: res.at, cell: res.cellIndex, axes: res.axes,
      grid: res.reply.states, couples: asked.map((it) => ({ hi: it.hi, lo: it.lo })),
      ...(res.at === 'end' ? { runKey: res.runKey } : {}),
      ...(withRun ? { t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) },
    (p) => {
      setProgress(p.frac);
      setStatus(`Finding where the couples turn over across the map: ${p.done.toLocaleString()} of ${p.npts.toLocaleString()}…`);
    });
    $('rtmStop').disabled = false;
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      res.couples.set(sig, { reply, asked });
      if (dgResult === res) {
        setStatus(`${res.said.replace(/\.$/, '')}; its couples' lines found in ${((Date.now() - started) / 1000).toFixed(2)} s.`,
          res.saidKind);
      }
    } catch (e) {
      res.couples.set(sig, null);
      if (dgResult === res) setStatus(`Where the couples turn over could not be found: ${e.message}`, 'warn');
    } finally {
      setProgress(null);
      if (dgLadderAsked && dgLadderAsked.res === res) dgLadderAsked = null;
      $('rtmStop').disabled = !state.running && !dgBoundsAsked;
      if (dgResult) drawDg();
    }
  }

  /** Where each couple turns over, found by the worker from the diagram's points; one ladder at a time. */
  async function dgAskLadder(sig, asked) {
    const res = dgResult;
    if (!res || dgLadderAsked) return;
    if (res.at === 'end' && !(state.result && state.result.runKey === res.runKey)) return;
    dgLadderAsked = { res, sig };
    const r = state.result;
    const started = Date.now();
    const ask = (withRun) => request({ type: 'diagramLadder', text: res.text, at: res.at, cell: res.cellIndex, axes: res.axes,
      pHAt: res.pHAt, grid: res.reply.states, couples: asked.map((it) => ({ hi: it.hi, lo: it.lo })),
      ...(res.at === 'end' ? { runKey: res.runKey } : {}),
      ...(withRun ? { t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) },
    (p) => {
      setProgress(p.frac);
      setStatus(`Finding where the couples turn over: ${p.done.toLocaleString()} of ${p.npts.toLocaleString()}…`);
    });
    $('rtmStop').disabled = false;
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      res.ladders.set(sig, { reply, asked });
      if (dgResult === res) {
        setStatus(`${res.said.replace(/\.$/, '')}; where its couples turn over found in ${((Date.now() - started) / 1000).toFixed(2)} s.`,
          res.saidKind);
      }
    } catch (e) {
      res.ladders.set(sig, null);
      if (dgResult === res) setStatus(`Where the couples turn over could not be found: ${e.message}`, 'warn');
    } finally {
      setProgress(null);
      if (dgLadderAsked && dgLadderAsked.res === res) dgLadderAsked = null;
      $('rtmStop').disabled = !state.running && !dgBoundsAsked;
      if (dgResult) drawDg();
    }
  }

  /**
   * On a pe-pH or an Eh-pH diagram, either way round, where water itself
   * gives way, at 25 C and one atmosphere: above pe + pH = 20.78 it gives off
   * oxygen (O2 + 4H+ + 4e- = 2H2O, log K 83.12), below pe + pH = 0 hydrogen;
   * in volts, Eh = 0.059156 (20.78 - pH) and -0.059156 pH, the volts of a
   * pe at 25 C (RtmModel.ehPerPe).
   */
  function dgWaterLines(ax, ay, xs, ys) {
    const redox = (kind) => kind === 'pe' || kind === 'Eh';
    if (!((ax.kind === 'pH' && redox(ay.kind)) || (ay.kind === 'pH' && redox(ax.kind)))) return [];
    // pH across or up, and the redox axis the other way, in volts or pe.
    const across = ax.kind === 'pH';
    const per = (across ? ay : ax).kind === 'Eh' ? RtmModel.ehPerPe(298.15) : 1;
    const range = (v) => [Math.min(...v), Math.max(...v)];
    const [pLo, pHi] = range(across ? xs : ys);
    const [rLo, rHi] = range(across ? ys : xs);
    const c = themeColors();
    return [[20.78, 'water and O₂ at 1 atm, 25 °C'], [0, 'water and H₂ at 1 atm']].flatMap(([sum, name]) => {
      // The line, per (sum - pH), over the pH where it is inside the redox axis.
      const pa = Math.max(pLo, sum - rHi / per);
      const pb = Math.min(pHi, sum - rLo / per);
      if (!(pa < pb)) return [];
      const ps = [pa, pb];
      const rs = ps.map((p) => per * (sum - p));
      return [{ type: 'scatter', mode: 'lines', x: across ? ps : rs, y: across ? rs : ps, showlegend: false,
        line: { color: c.text, width: 1.2, dash: 'dash' }, hovertemplate: `${name}<extra></extra>` }];
    });
  }

  /* ---------------------------------------------------------------------
     Sweeps: the model run again for each value of what is varied, as Gibbs
     Studio's parametric runs

     The worker (rtmSweep in rtm-worker.js) puts each value into the text,
     runs it with the panel's solver settings and keeps every species and
     quantity at one cell along the run and along the column at its end;
     each way of drawing them is drawn here without running again.
     --------------------------------------------------------------------- */
  let swResult = null;
  let swTableNow = null;
  let swBusy = false;

  /**
   * What a sweep can vary and a fit can fit, as <optgroup>s: the numeric
   * settings, the parameters, each species' start, what flows in, each
   * relation's and phase's log K, and each number a reaction's line names.
   */
  function tuneChoices() {
    const m = state.compiled;
    if (!m) return [];
    const kinds = (typeof RtmModel !== 'undefined' && RtmModel.SETTINGS) || {};
    const groups = [];
    const settings = Object.entries(kinds).filter(([, spec]) => spec.kind === 'number' || spec.kind === 'int' || spec.kind === 'time')
      .map(([name]) => ({ value: `setting:${name}`, label: `${name}${typeof m.settings[name] === 'number' ? ` (${fmtNumber(m.settings[name])})` : ''}` }));
    groups.push({ label: 'Settings', items: settings });
    // Each label says what it is, as the closed menu shows the label alone, and the number the text gives it.
    const given = (kind, name) => {
      const v = typeof RtmModel !== 'undefined' && RtmModel.valueIn ? RtmModel.valueIn(state.text, { kind, name }) : null;
      return v === null ? '' : ` (${fmtNumber(v)})`;
    };
    if (m.parameters && m.parameters.length) {
      groups.push({ label: 'Parameters', items: m.parameters.map((p) => ({ value: `parameter:${p}`, label: `${p}${given('parameter', p)}` })) });
    }
    groups.push({ label: 'A species at the start', items: m.species.map((sp) => ({ value: `initial:${sp}`,
      label: `${sp} at the start${given('initial', sp)}` })) });
    if (m.transport) {
      groups.push({ label: 'A species flowing in', items: m.species.map((sp) => ({ value: `left:${sp}`,
        label: `${sp} flowing in${given('left', sp)}` })) });
    }
    const tunable = typeof RtmModel !== 'undefined' && RtmModel.tunables ? RtmModel.tunables(state.text) : [];
    const logKs = tunable.filter((x) => x.kind === 'logK');
    if (logKs.length) {
      groups.push({ label: 'A relation\'s log K', items: logKs.map((x) => ({ value: `logK:${x.name}`,
        label: `${swVaryLabel(x)} (${fmtNumber(x.value)})` })) });
    }
    const consts = tunable.filter((x) => x.kind === 'rate');
    if (consts.length) {
      groups.push({ label: 'A reaction\'s constant', items: consts.map((x) => ({ value: `rate:${x.name}`,
        label: `${swVaryLabel(x)} (${fmtNumber(x.value)})` })) });
    }
    return groups;
  }

  /**
   * The first of what can be varied that `taken` has not got, the likeliest first: a parameter, a reaction's constant, a
   * log K, a species' start or what flows in, and a setting last -- a batch model has CELLS, which changes nothing.
   */
  function nextChoice(taken) {
    const all = tuneChoices().flatMap((g) => g.items.map((it) => it.value)).filter((v) => !taken.has(v));
    for (const kind of ['parameter:', 'rate:', 'logK:', 'initial:', 'left:', 'setting:']) {
      const v = all.find((x) => x.startsWith(kind));
      if (v) return v;
    }
    return all[0];
  }

  /** What a sweep varies, from a choice's value: { kind, name }. */
  const swVary = (value) => {
    const i = String(value).indexOf(':');
    return i < 0 ? null : { kind: value.slice(0, i), name: value.slice(i + 1) };
  };
  const swVaryLabel = (v) => (v.kind === 'initial' ? `${v.name} at the start` : v.kind === 'left' ? `${v.name} flowing in`
    : v.kind === 'logK' ? `log K of ${v.name}` : v.kind === 'rate'
      ? `${v.name.slice(v.name.lastIndexOf(' | ') + 3)} of ${v.name.slice(0, v.name.lastIndexOf(' | '))}` : v.name);

  /**
   * The values to run: a list, "0.5, 1, 2", or a range, "1e-6 to 1e-4 in 5",
   * spaced evenly or with "log" after it in the logarithm.
   */
  function swValues(text) {
    const t = String(text).trim();
    const range = /^(\S+)\s+to\s+(\S+)\s+in\s+(\d+)(\s+log)?$/i.exec(t);
    if (range) {
      const a = Number(range[1]);
      const b = Number(range[2]);
      const n = Number(range[3]);
      if (!Number.isFinite(a) || !Number.isFinite(b) || !(n >= 2)) return null;
      if (range[4]) {
        if (!(a > 0 && b > 0)) return null;
        return Array.from({ length: n }, (_, i) => Number((a * (b / a) ** (i / (n - 1))).toPrecision(12)));
      }
      return Array.from({ length: n }, (_, i) => Number((a + ((b - a) * i) / (n - 1)).toPrecision(12)));
    }
    const list = t.split(/[\s,;]+/).filter(Boolean).map(Number);
    return list.length && list.every(Number.isFinite) ? list : null;
  }

  function renderSw() {
    const m = state.compiled;
    const w = state.sw;
    const groups = tuneChoices();
    const all = groups.flatMap((g) => g.items.map((it) => it.value));
    // Each constant in turn, where the model has any.
    const each = eachTargets();
    const eachOffered = eachChoices(each);
    if (all.length && !all.includes(w.what) && !eachOffered.some(([v]) => v === w.what)) {
      w.what = (all.find((v) => v === 'setting:VELOCITY' && m && m.transport)
        || all.find((v) => v.startsWith('parameter:')) || all.find((v) => v.startsWith('initial:')) || all[0]);
    }
    if (w.what2 && !all.includes(w.what2)) w.what2 = '';
    const opts = (chosen) => groups.map((g) => `<optgroup label="${esc(g.label)}">${g.items.map((it) => `<option value="${esc(it.value)}"`
      + `${it.value === chosen ? ' selected' : ''}>${esc(it.label)}</option>`).join('')}</optgroup>`).join('');
    const eachOpt = eachOffered.length ? `<optgroup label="Each in turn">${eachOffered.map(([v, label]) => `<option value="${v}"`
      + `${w.what === v ? ' selected' : ''}>${esc(label)}</option>`).join('')}</optgroup>` : '';
    $('rtmSwWhat').innerHTML = eachOpt + opts(w.what);
    $('rtmSwWhat2').innerHTML = `<option value=""${w.what2 ? '' : ' selected'}>nothing else</option>${opts(w.what2)}`;
    $('rtmSwValues').value = w.values;
    $('rtmSwValues2').value = w.values2;
    $('rtmSwMore2').hidden = !w.what2;
    $('rtmSwOverWrap').hidden = isEach(w.what);
    $('rtmSwAndWrap').hidden = isEach(w.what);
    const cells = m ? m.fracture : 1;
    if (!(w.cell < cells)) w.cell = cells - 1;
    $('rtmSwCell').innerHTML = Array.from({ length: cells }, (_, i) => `<option value="${i}"${i === w.cell ? ' selected' : ''}>`
      + `${i}${m && m.centres && cells > 1 ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
    $('rtmSwCellWrap').hidden = cells < 2;
    $('rtmSwGo').disabled = swBusy;
  }

  /** The value of a choice as the model has it, to start a list from. */
  function swCurrent(value) {
    const m = state.compiled;
    const v = swVary(value);
    if (!m || !v) return null;
    if (v.kind === 'setting') return typeof m.settings[v.name] === 'number' ? m.settings[v.name] : null;
    // The rest as the text gives it, which is what a sweep changes: an exchanger's capacity, not what it holds at the start.
    const given = typeof RtmModel !== 'undefined' && RtmModel.valueIn ? RtmModel.valueIn(state.text, v) : null;
    return given ? given : null;
  }

  function readSw() {
    const w = state.sw;
    const what = $('rtmSwWhat').value;
    const what2 = $('rtmSwWhat2').value;
    // A new choice starts from half, the value and twice it, where the model has one.
    // A log K a unit either side.
    const start = (value) => {
      const c = swCurrent(value);
      if (!c) return '';
      return value.startsWith('logK:') ? `${fmtNumber(c - 1)}, ${fmtNumber(c)}, ${fmtNumber(c + 1)}`
        : `${fmtNumber(c / 2)}, ${fmtNumber(c)}, ${fmtNumber(c * 2)}`;
    };
    w.values = what !== w.what ? start(what) : $('rtmSwValues').value;
    w.values2 = what2 !== w.what2 ? start(what2) : $('rtmSwValues2').value;
    w.what = what;
    w.what2 = what2;
    w.cell = Number($('rtmSwCell').value) || 0;
  }

  async function swGo() {
    if (swBusy || state.running) return;
    if (!state.compiled) { setStatus('The model does not compile: there is nothing to run.', 'error'); return; }
    const w = state.sw;
    if (isEach(w.what)) { await eachGo(w.what); return; }
    const vary = [swVary(w.what), ...(w.what2 ? [swVary(w.what2)] : [])];
    const lists = [swValues(w.values), ...(w.what2 ? [swValues(w.values2)] : [])];
    if (lists.some((l) => !l)) { setStatus('Give the values: a list, 0.5, 1, 2, or a range, 1e-6 to 1e-4 in 5, with log after it to space them in the logarithm.', 'error'); return; }
    if (vary.length === 2 && vary[0].kind === vary[1].kind && vary[0].name === vary[1].name) {
      setStatus('The two things varied are the same thing: give the second another, or nothing.', 'error');
      return;
    }
    const nruns = lists.reduce((n, l) => n * l.length, 1);
    if (nruns > 400) { setStatus(`${nruns} runs: 400 at most.`, 'error'); return; }
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    swBusy = true;
    state.running = true;
    $('rtmRun').disabled = true;
    $('rtmStop').disabled = false;
    $('rtmSwGo').disabled = true;
    setProgress(0);
    setStatus(`Running ${nruns} times…`);
    const text = state.text;
    try {
      const reply = await request({ type: 'sweep', text, solver, vary, values: lists, cell: w.cell }, (p) => {
        setProgress(p.frac);
        setStatus(`Running ${p.run + 1} of ${p.runs}: ${fmtTime(p.t)} of ${fmtTime(p.tend)}, ${p.nsteps.toLocaleString()} steps`);
      });
      swResult = { reply, vary, lists, text };
      const failed = reply.runs.filter((r) => !r.ok);
      setProgress(null);
      setStatus(`${reply.runs.length - failed.length} of ${reply.runs.length} runs done in ${reply.seconds.toFixed(2)} s`
        + `${failed.length ? `; ${swRunName(failed[0])} failed: ${failed[0].error}` : '.'}`, failed.length ? 'warn' : 'ok');
      renderSwShow();
      drawSw();
    } catch (e) {
      setProgress(null);
      setStatus(`The runs could not be made: ${e.message}`, 'error');
    } finally {
      swBusy = false;
      state.running = false;
      $('rtmRun').disabled = false;
      $('rtmStop').disabled = true;
      $('rtmSwGo').disabled = false;
    }
  }

  /** A run's name: what was varied, and its value. */
  function swRunName(run) {
    return swResult.vary.map((v, d) => `${swVaryLabel(v)} = ${fmtNumber(run.values[d])}`).join(', ');
  }

  /*
    EACH CONSTANT IN TURN: every number a reaction's line names and every
    parameter given one value throughout, each raised by 1 % of itself and
    lowered by as much, one at a time, with the model as written besides --
    the worker runs them (rtmEach) and keeps every species and quantity at
    the cell, at the end and at its largest and smallest. How much each moves
    what is drawn is the change in its logarithm over the change in theirs,
    between the two runs: the per cent it changes for 1 % more of the
    constant -- for pH, an SI and the like, how much it changes. A constant
    one value put in for all would move by more than 1 % is left out, and
    the note says why: two lines with the same equation and different
    constants, a parameter with a value for each cell; and an expression or
    nought, which 1 % does not move. Each log K in turn, the same for every
    relation's and phase's log K, moved by log10 1.01 either way so that its
    K is 1 % more and 1 % less: how much a result moves is the change in its
    logarithm over the change in K's, on the same scale as the constants.
  */
  const SW_EACH = '*each';
  const SW_EACH_K = '*eachK';
  const SW_EACH_ALL = '*eachAll';
  const isEach = (v) => v === SW_EACH || v === SW_EACH_K || v === SW_EACH_ALL;
  const EACH_DELTA = 0.01;
  const EACH_LK = Math.log10(1.01);
  /** What each in turn offers, [value, label]: the constants, the log K's, and both where the model has both. */
  function eachChoices(each) {
    const nc = each.targets.length;
    const nk = each.logKs.length;
    const out = [];
    if (nc) out.push([SW_EACH, `${nc === 1 ? 'its one constant' : `each of its ${nc} constants`}, 1 % either way (${2 * nc + 1} runs)`]);
    if (nk) out.push([SW_EACH_K, `${nk === 1 ? 'its one log K' : `each of its ${nk} log K's`}, K 1 % either way (${2 * nk + 1} runs)`]);
    if (nc && nk) out.push([SW_EACH_ALL, `each of its ${nc} constant${nc === 1 ? '' : 's'} and ${nk} log K${nk === 1 ? '' : "'s"} `
      + `(${2 * (nc + nk) + 1} runs)`]);
    return out;
  }
  /**
   * The constants each in turn runs, { vary, base, label }, the log K's, { vary, base, up, down, label, k }, and those
   * left out, with why.
   */
  function eachTargets() {
    const out = [];
    const logKs = [];
    const left = [];
    const m = state.compiled;
    if (!m || typeof RtmModel === 'undefined' || !RtmModel.tunables) return { targets: out, logKs, left };
    const text = state.text;
    // Lines the text has once changed, each with the number it had: the same number put back changes nothing.
    const sameEverywhere = (vary, base) => {
      let back;
      try { back = RtmModel.withValue(text, vary, base); } catch (e) { return false; }
      if (back === text) return true;
      const a = text.split(/\r?\n/);
      const b = back.split(/\r?\n/);
      if (a.length !== b.length) return false;
      return a.every((line, i) => {
        if (line === b[i]) return true;
        const x = line.trim().split(/[\s,=]+/);
        const y = b[i].trim().split(/[\s,=]+/);
        return x.length === y.length && x.every((tok, j) => tok === y[j] || (Number.isFinite(Number(tok)) && Number(tok) === Number(y[j])));
      });
    };
    for (const p of m.parameters || []) {
      const vary = { kind: 'parameter', name: p };
      const given = RtmModel.valueIn(text, vary);
      const base = given === null ? NaN : Number(given);
      if (!Number.isFinite(base)) { left.push(`${p}, an expression`); continue; }
      if (base === 0) { left.push(`${p}, nought`); continue; }
      if (!sameEverywhere(vary, base)) { left.push(`${p}, a value for each cell`); continue; }
      out.push({ vary, base, label: p });
    }
    const consts = RtmModel.tunables(text).filter((x) => x.kind === 'rate');
    const byName = new Map();
    for (const x of consts) { if (!byName.has(x.name)) byName.set(x.name, []); byName.get(x.name).push(x.value); }
    for (const [name, values] of byName) {
      const vary = { kind: 'rate', name };
      const label = swVaryLabel(vary);
      if (values.some((v) => v !== values[0])) { left.push(`${label}, lines alike with other values`); continue; }
      if (values[0] === 0) { left.push(`${label}, nought`); continue; }
      out.push({ vary, base: values[0], label });
    }
    // Each relation's and phase's log K, a value of the text's own; moved by as much either way, K by 1 %.
    const byEq = new Map();
    for (const x of RtmModel.tunables(text).filter((y) => y.kind === 'logK')) {
      if (!byEq.has(x.name)) byEq.set(x.name, []);
      byEq.get(x.name).push(x.value);
    }
    for (const [name, values] of byEq) {
      const vary = { kind: 'logK', name };
      const label = swVaryLabel(vary);
      if (values.some((v) => v !== values[0])) { left.push(`${label}, lines alike with other values`); continue; }
      logKs.push({ vary, base: values[0], up: values[0] + EACH_LK, down: values[0] - EACH_LK, label, k: true });
    }
    return { targets: out, logKs, left };
  }

  async function eachGo(what) {
    const w = state.sw;
    const each = eachTargets();
    const targets = what === SW_EACH_K ? each.logKs : what === SW_EACH_ALL ? [...each.targets, ...each.logKs] : each.targets;
    const left = each.left.filter((x) => (what === SW_EACH_K ? x.startsWith('log K of ') : what === SW_EACH ? !x.startsWith('log K of ') : true));
    if (!targets.length) { setStatus('The model has nothing of that to move: no number a reaction\'s line names, no parameter, no log K.', 'error'); return; }
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    const nruns = 2 * targets.length + 1;
    swBusy = true;
    state.running = true;
    $('rtmRun').disabled = true;
    $('rtmStop').disabled = false;
    $('rtmSwGo').disabled = true;
    setProgress(0);
    setStatus(`Running ${nruns} times…`);
    const text = state.text;
    // Every run read at the same times, through the run: a hundred spread evenly and a hundred in the logarithm.
    const tend = solver.tend > 0 ? solver.tend : state.compiled.settings.TEND;
    const times = [...new Set([...Array.from({ length: 100 }, (_, i) => (tend * (i + 1)) / 100),
      ...Array.from({ length: 100 }, (_, i) => tend * 10 ** (-6 + (6 * i) / 99))])].sort((a, b) => a - b);
    try {
      const reply = await request({ type: 'each', text, solver, targets: targets.map((t) => ({ vary: t.vary, base: t.base,
        ...(t.k ? { up: t.up, down: t.down } : {}) })),
        delta: EACH_DELTA, cell: w.cell, ...(tend > 0 ? { times } : {}) }, (p) => {
        setProgress(p.frac);
        setStatus(`Running ${p.run + 1} of ${p.runs}: ${fmtTime(p.t)} of ${fmtTime(p.tend)}, ${p.nsteps.toLocaleString()} steps`);
      });
      swResult = { kind: 'each', what, reply, targets, left, text };
      w.show = 'ranked';
      const failed = reply.runs.filter((r) => !r.ok);
      setProgress(null);
      setStatus(`${reply.runs.length - failed.length} of ${reply.runs.length} runs done in ${reply.seconds.toFixed(2)} s`
        + `${failed.length ? `; ${eachRunName(failed[0])} failed: ${failed[0].error}` : '.'}`, failed.length ? 'warn' : 'ok');
      renderSwShow();
      drawSw();
    } catch (e) {
      setProgress(null);
      setStatus(`The runs could not be made: ${e.message}`, 'error');
    } finally {
      swBusy = false;
      state.running = false;
      $('rtmRun').disabled = false;
      $('rtmStop').disabled = true;
      $('rtmSwGo').disabled = false;
    }
  }

  /** A run of each in turn by its name: the model as written, or a constant raised or lowered. */
  const eachRunName = (run) => (run.target < 0 ? 'the model as written'
    : `${swResult.targets[run.target].label} ${run.factor > 1 ? 'raised' : 'lowered'}${swResult.targets[run.target].k ? ', K' : ''} 1 %`);

  function drawEach(plot, note) {
    const w = state.sw;
    if (w.show === 'through' && swResult.reply.times) { drawEachTime(plot, note); return; }
    const rp = swResult.reply;
    const key = w.key;
    const q = isQuantity(key) ? quantityOf(key) : null;
    const index = !!(q && q.axis === 'index');
    const k = !q ? rp.species.indexOf(key) : (rp.keys.indexOf(key) >= 0 ? rp.species.length + rp.keys.indexOf(key) : -1);
    const of = w.of === 'max' || w.of === 'min' ? w.of : 'end';
    const ofText = { end: 'at the end', max: 'its largest', min: 'its smallest' }[of];
    const yTitle = q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : key;
    const base = rp.runs.find((r) => r.target === -1);
    const failed = rp.runs.filter((r) => !r.ok).length;
    if (!base || !base.ok || k < 0) {
      Plotly.purge(plot);
      plot.hidden = true;
      $('rtmSwEmpty').hidden = false;
      $('rtmSwEmpty').textContent = !base || !base.ok ? 'The model as written did not run: nothing to set the others against.'
        : `${key} is not among what these runs kept.`;
      note.textContent = '';
      return;
    }
    const y0 = base[of][k];
    const rows = swResult.targets.map((t, j) => {
      const up = rp.runs.find((r) => r.target === j && r.factor > 1);
      const dn = rp.runs.find((r) => r.target === j && r.factor < 1);
      if (!up || !dn || !up.ok || !dn.ok) return { t, s: null, up: null, dn: null };
      const a = up[of][k];
      const b = dn[of][k];
      // A constant moved 1 % of itself either way, a log K so that K is 1 % more and 1 % less: what it moved by.
      const den = t.k ? 2 * Math.log(1.01) : 2 * rp.delta;
      let s = null;
      if (index) s = (a - b) / 2;
      else if (a > 0 && b > 0) s = (Math.log(a) - Math.log(b)) / den;
      else if (y0 !== 0 && Number.isFinite(y0)) s = (a - b) / (den * y0);
      return { t, s: Number.isFinite(s) ? s : null, up: a, dn: b };
    }).sort((x, z) => (z.s === null ? -1 : x.s === null ? 1 : Math.abs(z.s) - Math.abs(x.s)));
    const shown = rows.filter((r) => r.s !== null).slice(0, 25);
    const nk = swResult.targets.filter((t) => t.k).length;
    const nc = swResult.targets.length - nk;
    const ofEach = `for 1 % more of each${!nc ? ' K' : nk ? ' constant or K' : ''}`;
    const per = `${index ? 'change' : '% change'} in ${yTitle}, ${ofText}, ${ofEach}`;
    const c = themeColors();
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.height = Math.max(320, 24 * shown.length + 110);
    layout.xaxis.title = { text: per, font: { size: 11 } };
    layout.xaxis.zeroline = true;
    layout.xaxis.zerolinecolor = c.text;
    layout.yaxis.automargin = true;
    layout.yaxis.autorange = 'reversed';
    layout.yaxis.type = 'category';
    layout.margin.l = 20;
    const fmt = (v) => (Math.abs(v) >= 1e-3 && Math.abs(v) < 1e4 ? String(Number(v.toPrecision(3))) : v.toExponential(2));
    Plotly.react(plot, [{ type: 'bar', orientation: 'h', x: shown.map((r) => r.s), y: shown.map((r) => r.t.label),
      marker: { color: shown.map((r) => (r.s >= 0 ? '#3b82c4' : '#e0663e')) },
      text: shown.map((r) => fmt(r.s)), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{y}<br>%{x:.4g}<extra></extra>', showlegend: false }], layout, PLOT_CONFIG);
    const strong = rows.filter((r) => r.s !== null && Math.abs(r.s) > (index ? 1e-3 : 0.1));
    const top = rows[0] && rows[0].s !== null ? rows[0] : null;
    note.textContent = [`${yTitle}, ${ofText} at cell ${rp.cell}, ${fmtNumber(y0)} as written`,
      `${[nc ? `${nc} constant${nc === 1 ? '' : 's'}` : '', nk ? `${nk} log K${nk === 1 ? '' : "'s"}` : ''].filter(Boolean).join(' and ')}, `
        + `${rp.runs.length} runs${failed ? `, ${failed} failed` : ''}`,
      `${strong.length} move${strong.length === 1 ? 's' : ''} it by more than ${index ? '0.001' : '0.1 %'} for 1 % more`
        + `${top ? `, the most ${top.t.label}, ${fmt(top.s)}` : ''}`,
      rows.length > shown.length ? `the ${shown.length} that move it most drawn` : '',
      swResult.left.length ? `left out: ${swResult.left.join('; ')}` : '']
      .filter(Boolean).join('; ');
    swTableNow = { head: ['constant', 'as the text gives it', `${key} ${ofText}, as written`, 'with 1 % more of it', 'with 1 % less',
      index ? 'change for 1 % more' : '% change for 1 % more'],
    name: `rtm_each_${!nk ? 'constant' : !nc ? 'logK' : 'constant_and_logK'}_${key.replace(/[^\w.-]+/g, '_')}_${of}`,
    rows: rows.map((r) => [r.t.label, r.t.base, y0, r.up, r.dn, r.s]) };
  }

  /*
    EACH CONSTANT IN TURN, THROUGH THE RUN: every run read at the same times
    by the solver itself, a hundred spread evenly and a hundred in the
    logarithm, and at each how much each constant moves what is drawn, as
    the ranking has it: the change in its logarithm over the change in the
    constant's, between the run raised and the run lowered. The eight that
    move it most anywhere in the run drawn, a curve each. A reaction's rate
    or extent is kept at the end only, too many in a network to keep
    through the run.
  */
  function drawEachTime(plot, note) {
    const w = state.sw;
    const rp = swResult.reply;
    const key = w.key;
    const q = isQuantity(key) ? quantityOf(key) : null;
    const index = !!(q && q.axis === 'index');
    const yTitle = q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : key;
    const keys = rp.seriesKeys || [];
    const k = keys.indexOf(key);
    const base = rp.runs.find((r) => r.target === -1);
    if (!base || !base.ok || k < 0) {
      Plotly.purge(plot);
      plot.hidden = true;
      $('rtmSwEmpty').hidden = false;
      $('rtmSwEmpty').textContent = !base || !base.ok ? 'The model as written did not run: nothing to set the others against.'
        : `${yTitle} is kept at the end of each run only: a reaction's rate and extent are too many in a network to keep through it.`;
      note.textContent = '';
      return;
    }
    const nk = keys.length;
    const ts = rp.times;
    const at = (run, i) => run.series[i * nk + k];
    const curves = swResult.targets.map((t, j) => {
      const up = rp.runs.find((r) => r.target === j && r.factor > 1);
      const dn = rp.runs.find((r) => r.target === j && r.factor < 1);
      if (!up || !dn || !up.ok || !dn.ok || !up.series || !dn.series) return { t, e: null, most: -1 };
      const den = t.k ? 2 * Math.log(1.01) : 2 * rp.delta;
      const e = ts.map((_, i) => {
        const a = at(up, i);
        const b = at(dn, i);
        const y0 = at(base, i);
        let v = null;
        if (index) v = (a - b) / 2;
        else if (a > 0 && b > 0) v = (Math.log(a) - Math.log(b)) / den;
        else if (y0 !== 0 && Number.isFinite(y0)) v = (a - b) / (den * y0);
        return Number.isFinite(v) ? v : null;
      });
      let most = 0;
      let when = null;
      e.forEach((v, i) => { if (v !== null && Math.abs(v) > most) { most = Math.abs(v); when = i; } });
      return { t, e, most, when };
    }).sort((x, z) => z.most - x.most);
    const shown = curves.filter((x) => x.e && x.most > 0).slice(0, 8);
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf'];
    const logT = $('rtmSwLogT').checked;
    const keep = ts.map((x) => !logT || x > 0);
    const layout = baseLayout();
    layout.xaxis.type = logT ? 'log' : 'linear';
    layout.xaxis.title = { text: `time (${shownTime().sym})`, font: { size: 11 } };
    const nkK = swResult.targets.filter((t) => t.k).length;
    const ncC = swResult.targets.length - nkK;
    const ofEach = `for 1 % more of each${!ncC ? ' K' : nkK ? ' constant or K' : ''}`;
    layout.yaxis.title = { text: `${index ? 'change' : '% change'} in ${yTitle} at cell ${rp.cell}, ${ofEach}`, font: { size: 11 } };
    layout.yaxis.zeroline = true;
    Plotly.react(plot, shown.map((x, q2) => ({ type: 'scatter', mode: 'lines', name: x.t.label, x: ts.filter((_, i) => keep[i]).map(showT),
      y: x.e.filter((_, i) => keep[i]), line: { color: palette[q2], width: 1.8 } })), layout, PLOT_CONFIG);
    const fmt = (v) => (Math.abs(v) >= 1e-3 && Math.abs(v) < 1e4 ? String(Number(v.toPrecision(3))) : v.toExponential(2));
    const top = shown[0];
    note.textContent = [`${yTitle} at cell ${rp.cell} through the run, at ${ts.length} times`,
      `${swResult.targets.length} constant${swResult.targets.length === 1 ? '' : 's'}, ${rp.runs.length} runs`,
      shown.length < curves.length ? `the ${shown.length} that move it most drawn` : '',
      top ? `the most ${top.t.label}, ${fmt(top.e[top.when])} at ${fmtTime(ts[top.when])}` : '',
      swResult.left.length ? `left out: ${swResult.left.join('; ')}` : '']
      .filter(Boolean).join('; ');
    swTableNow = { head: [`t (${shownTime().sym})`, ...curves.map((x) => x.t.label)],
      name: `rtm_each_through_the_run_${key.replace(/[^\w.-]+/g, '_')}`,
      rows: ts.map((x, i) => [showT(x), ...curves.map((c) => (c.e ? c.e[i] : null))]) };
  }

  function renderSwShow() {
    $('rtmSwShowBar').hidden = !swResult;
    if (!swResult) return;
    const w = state.sw;
    if (swResult.kind === 'each') {
      const ks = swResult.targets.every((t) => t.k);
      const opts = [['ranked', `each ${ks ? 'log K' : 'constant'}, by how much it moves it`],
        ...(swResult.reply.times ? [['through', 'through the run, the eight that move it most']] : [])];
      if (!opts.some(([v]) => v === w.show)) w.show = 'ranked';
      $('rtmSwShow').innerHTML = opts.map(([v, t]) => `<option value="${v}"${v === w.show ? ' selected' : ''}>${esc(t)}</option>`).join('');
      if (!speciesNames().includes(w.key) && !(quantityOf(w.key) && !quantityOf(w.key).of)) w.key = speciesNames()[0] || '';
      $('rtmSwKey').innerHTML = pickerOptions(w.key, false);
      $('rtmSwOf').value = w.of;
      $('rtmSwOfWrap').hidden = w.show !== 'ranked';
      $('rtmSwLogT').checked = w.logT;
      $('rtmSwLogTWrap').hidden = w.show !== 'through';
      $('rtmSwLogWrap').hidden = true;
      return;
    }
    const two = swResult.vary.length === 2;
    const column = swResult.reply.runs.some((r) => r.ok && r.nf > 1);
    const opts = [
      ...(two ? [['lines', 'against the first varied, a curve for each of the second'], ['contour', 'over the two, as contours'],
        ['surface', 'over the two, as a surface']] : [['summary', 'against what was varied']]),
      ['time', 'against time, a curve per run'], ...(column ? [['profile', 'along the column at the end, a curve per run']] : []),
    ];
    if (!opts.some(([v]) => v === w.show)) w.show = opts[0][0];
    $('rtmSwShow').innerHTML = opts.map(([v, t]) => `<option value="${v}"${v === w.show ? ' selected' : ''}>${esc(t)}</option>`).join('');
    if (!speciesNames().includes(w.key) && !(quantityOf(w.key) && !quantityOf(w.key).of)) w.key = speciesNames()[0] || '';
    $('rtmSwKey').innerHTML = pickerOptions(w.key, false);
    $('rtmSwOf').value = w.of;
    $('rtmSwLogT').checked = w.logT;
    $('rtmSwOfWrap').hidden = w.show === 'time' || w.show === 'profile';
    $('rtmSwLogTWrap').hidden = w.show !== 'time';
    // pH, SI and the like are drawn as they are: log is for an amount.
    $('rtmSwLogWrap').hidden = isQuantity(w.key) && quantityOf(w.key).axis === 'index';
  }

  // A run's colour, along viridis by its place in the sweep.
  const VIRIDIS = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e', '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725'];
  const swColour = (i, n) => VIRIDIS[Math.round((n > 1 ? i / (n - 1) : 0) * (VIRIDIS.length - 1))];

  /** A key's values in a run of the sweep, at the cell along the run or along the column at the end. */
  const swSeries = (run, key, where) => runSeries(swResult.reply, run, key, where);

  /** A key's values in a run of a sweep's reply rp, at the cell along the run or along the column at the end. */
  function runSeries(rp, run, key, where) {
    const k = rp.species.indexOf(key);
    const isQ = !(k >= 0 && !isQuantity(key));
    const q = isQ ? rp.keys.indexOf(key) : -1;
    if (!isQ && k < 0) return null;
    if (isQ && q < 0) return null;
    const ns = rp.species.length;
    const nq = rp.keys.length;
    const n = where === 'end' ? run.nf : run.m;
    const src = where === 'end' ? (isQ ? run.endQuant : run.endStates) : (isQ ? run.cellQuant : run.cellStates);
    return Array.from({ length: n }, (_, i) => src[i * (isQ ? nq : ns) + (isQ ? q : k)]);
  }

  /** What a run comes to for the summary: the key's value at the end, its largest or its smallest, at the cell. */
  function swSummary(run, key) {
    const y = swSeries(run, key, 'cell');
    if (!y) return null;
    const fin = y.filter(Number.isFinite);
    if (!fin.length) return null;
    return state.sw.of === 'max' ? Math.max(...fin) : state.sw.of === 'min' ? Math.min(...fin) : y[y.length - 1];
  }

  function drawSw() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartSw');
    const empty = $('rtmSwEmpty');
    const note = $('rtmSwNote');
    swTableNow = null;
    if (!swResult) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      note.textContent = '';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    if (swResult.kind === 'each') { drawEach(plot, note); return; }
    const w = state.sw;
    const rp = swResult.reply;
    const runs = rp.runs;
    const ok = runs.filter((r) => r.ok);
    const key = w.key;
    const q = isQuantity(key) ? quantityOf(key) : null;
    const logY = $('rtmSwLog').checked && (!q || q.axis === 'conc');
    const yTitle = q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : `${key} concentration`;
    const ofText = { end: 'at the end', max: 'its largest', min: 'its smallest' }[w.of];
    const layout = baseLayout();
    layout.hovermode = 'closest';
    const [v1, v2] = swResult.vary;
    const logX = (vals) => vals.every((v) => v > 0) && Math.max(...vals) / Math.min(...vals) >= 100;
    const where = `cell ${rp.cell}`;
    const bits = [`${ok.length} run${ok.length === 1 ? '' : 's'}${ok.length < runs.length ? ` of ${runs.length}, ${runs.length - ok.length} failed` : ''}`];
    if (w.show === 'time' || w.show === 'profile') {
      const traces = ok.map((run) => {
        const y = swSeries(run, key, w.show === 'time' ? 'cell' : 'end');
        const x = w.show === 'time' ? Array.from(run.t, showT) : Array.from(run.centres);
        const keep = x.map((xx, i) => (w.show !== 'time' || !w.logT || xx > 0) && Number.isFinite(y[i]) && (!logY || y[i] > 0));
        return { type: 'scatter', mode: 'lines', name: swRunName(run), x: x.filter((_, i) => keep[i]), y: y.filter((_, i) => keep[i]),
          line: { color: swColour(runs.indexOf(run), runs.length), width: 1.6 } };
      });
      layout.xaxis.type = w.show === 'time' && w.logT ? 'log' : 'linear';
      layout.xaxis.title = { text: w.show === 'time' ? `time (${shownTime().sym})` : 'distance from the left-hand face (m)', font: { size: 11 } };
      layout.yaxis.type = logY ? 'log' : 'linear';
      layout.yaxis.title = { text: yTitle, font: { size: 11 } };
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      swTableNow = chartTable(plot, `rtm_sweep_${w.show}`);
      bits.push(w.show === 'time' ? where : 'the end of each run');
      note.textContent = bits.join('; ');
      return;
    }
    if (swResult.vary.length === 1 || w.show === 'lines') {
      const firsts = swResult.lists[0];
      const seconds = swResult.vary.length === 2 ? swResult.lists[1] : [null];
      const traces = seconds.map((b, j) => {
        const pts = firsts.map((a) => {
          const run = runs.find((r) => r.values[0] === a && (b === null || r.values[1] === b));
          return [a, run && run.ok ? swSummary(run, key) : null];
        });
        return { type: 'scatter', mode: 'lines+markers', name: b === null ? `${yTitle}, ${ofText}` : `${swVaryLabel(v2)} = ${fmtNumber(b)}`,
          x: pts.map(([a]) => a), y: pts.map(([, y]) => (y !== null && (!logY || y > 0) ? y : null)),
          line: { color: b === null ? '#1f77b4' : swColour(j, seconds.length), width: 1.6 }, marker: { size: 7 } };
      });
      layout.xaxis.type = logX(firsts) ? 'log' : 'linear';
      layout.xaxis.title = { text: swVaryLabel(v1), font: { size: 11 } };
      layout.yaxis.type = logY ? 'log' : 'linear';
      layout.yaxis.title = { text: `${yTitle}, ${ofText} at ${where}`, font: { size: 11 } };
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      swTableNow = { head: [swVaryLabel(v1), ...traces.map((tr) => tr.name)], name: `rtm_sweep_${w.of}`,
        rows: firsts.map((a, i) => [a, ...traces.map((tr) => tr.y[i])]) };
      note.textContent = bits.join('; ');
      return;
    }
    // Over the two: a grid, the second up and the first across.
    const [xs, ys] = swResult.lists;
    const z = ys.map((b) => xs.map((a) => {
      const run = runs.find((r) => r.values[0] === a && r.values[1] === b);
      const v = run && run.ok ? swSummary(run, key) : null;
      if (v === null || !Number.isFinite(v)) return null;
      return logY ? (v > 0 ? Math.log10(v) : null) : v;
    }));
    const title = `${logY ? 'log₁₀ ' : ''}${yTitle}, ${ofText}`;
    const lx = logX(xs);
    const ly = logX(ys);
    const trace = { type: w.show === 'surface' ? 'surface' : 'contour', x: lx ? xs.map(Math.log10) : xs, y: ly ? ys.map(Math.log10) : ys, z,
      colorscale: 'Viridis', connectgaps: false,
      colorbar: { title: { text: title, side: 'right', font: { size: 11 } }, thickness: 14, outlinewidth: 0, tickfont: { size: 10 } },
      ...(w.show === 'contour' ? { contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 10 } }, line: { width: 0.6 } } : {}) };
    const xt = `${lx ? 'log₁₀ ' : ''}${swVaryLabel(v1)}`;
    const yt = `${ly ? 'log₁₀ ' : ''}${swVaryLabel(v2)}`;
    if (w.show === 'surface') {
      const c = themeColors();
      const ax = (text) => ({ title: { text, font: { size: 11 } }, gridcolor: c.grid, color: c.text });
      layout.scene = { xaxis: ax(xt), yaxis: ax(yt), zaxis: ax(title), camera: { eye: { x: -1.6, y: -1.6, z: 1.0 } } };
      layout.margin = { l: 0, r: 0, t: 10, b: 0 };
    } else {
      layout.xaxis.title = { text: xt, font: { size: 11 } };
      layout.yaxis.title = { text: yt, font: { size: 11 } };
    }
    Plotly.react(plot, [trace], layout, PLOT_CONFIG);
    swTableNow = { head: [`${swVaryLabel(v2)} \\ ${swVaryLabel(v1)}: ${title}`, ...xs], name: `rtm_sweep_${w.of}`,
      rows: ys.map((b, j) => [b, ...z[j]]) };
    bits.push(`${title} at ${where}`);
    note.textContent = bits.join('; ');
  }

  /* ---------------------------------------------------------------------
     Fit: the numbers moved until the run is as near as it can be to what
     <DATA> measured, as PhreePlot's and Gibbs Studio's fits do

     The worker (rtmFit in rtm-worker.js) runs the text with the numbers put
     in (RtmModel.withValue) and moves them by Levenberg and Marquardt; back
     come the best numbers, their standard errors and correlations, each
     point's residual and the best run where it was measured.
     --------------------------------------------------------------------- */
  let fitResult = null;
  let fitTableNow = null;
  let fitBusy = false;
  const FIT_MAX = 4;

  /** The columns <DATA> measures, in the order its tables give them. */
  function fitColumns() {
    const data = (state.compiled && state.compiled.data) || [];
    return [...new Set(data.flatMap((tab) => tab.columns.filter((c) => !/^sd\(.+\)$/.test(c))))];
  }

  function renderFit() {
    const f = state.fit;
    const groups = tuneChoices();
    const all = groups.flatMap((g) => g.items.map((it) => it.value));
    const first = all.find((v) => v.startsWith('parameter:')) || all.find((v) => v.startsWith('rate:'))
      || all.find((v) => v.startsWith('logK:')) || all[0] || '';
    if (!f.params.length) f.params.push({ what: first, start: '' });
    for (const p of f.params) {
      if (all.length && !all.includes(p.what)) { p.what = first; p.start = ''; }
      if (p.start === '' && p.what) { const c = swCurrent(p.what); if (c !== null) p.start = fmtNumber(c); }
    }
    const opts = (chosen) => groups.map((g) => `<optgroup label="${esc(g.label)}">${g.items.map((it) => `<option value="${esc(it.value)}"`
      + `${it.value === chosen ? ' selected' : ''}>${esc(it.label)}</option>`).join('')}</optgroup>`).join('');
    $('rtmFitParams').innerHTML = f.params.map((p, i) => `<span class="rtm-fit-row">${i ? 'and' : 'Fit'} `
      + `<select data-row="${i}" aria-label="what to fit" data-on-change="rtm:fitSettings">${opts(p.what)}</select> from `
      + `<input type="text" class="rtm-dg-num" data-row="${i}" aria-label="where to start" value="${esc(p.start)}" data-on-change="rtm:fitSettings">`
      + `${f.params.length > 1 ? ` <button type="button" class="rtm-btn secondary small rtm-fit-x" data-row="${i}" `
        + 'data-on-click="rtm:fitRemove" aria-label="Leave it out">×</button>' : ''}</span>`).join('');
    $('rtmFitAdd').hidden = f.params.length >= FIT_MAX;
    const cols = fitColumns();
    $('rtmFitCols').innerHTML = cols.map((c) => `<label><input type="checkbox" value="${esc(c)}"${f.off.includes(c) ? '' : ' checked'} `
      + `data-on-change="rtm:fitSettings">${esc(labelOf(c))}</label>`).join('');
    $('rtmFitColsWrap').hidden = !cols.length;
    $('rtmFitGo').disabled = fitBusy || !cols.length;
  }

  /** The rows and ticks into state.fit; a choice changed starts from the value the text gives it. */
  function readFit() {
    const f = state.fit;
    document.querySelectorAll('#rtmFitParams select').forEach((sel) => {
      const p = f.params[Number(sel.dataset.row)];
      if (!p) return;
      const input = document.querySelector(`#rtmFitParams input[data-row="${sel.dataset.row}"]`);
      if (sel.value !== p.what) {
        p.what = sel.value;
        const c = swCurrent(p.what);
        p.start = c !== null ? fmtNumber(c) : '';
      } else p.start = input.value.trim();
    });
    f.off = [...document.querySelectorAll('#rtmFitCols input')].filter((el) => !el.checked).map((el) => el.value);
  }

  async function fitGo() {
    if (fitBusy || state.running) return;
    if (!state.compiled) { setStatus('The model does not compile: there is nothing to fit.', 'error'); return; }
    const f = state.fit;
    const params = f.params.map((p) => ({ ...swVary(p.what), start: Number(p.start) }));
    if (params.some((p) => !p.kind)) { setStatus('Choose what to fit.', 'error'); return; }
    if (new Set(f.params.map((p) => p.what)).size < params.length) { setStatus('The same number is named twice: name each once.', 'error'); return; }
    const bad = params.find((p) => !Number.isFinite(p.start) || p.start === null);
    if (bad || f.params.some((p) => p.start === '')) {
      setStatus(`${swVaryLabel(bad || params[0])}: give it a number to start from.`, 'error');
      return;
    }
    const columns = fitColumns().filter((c) => !f.off.includes(c));
    if (!columns.length) { setStatus('Tick a column of <DATA> to fit to.', 'error'); return; }
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    fitBusy = true;
    state.running = true;
    $('rtmRun').disabled = true;
    $('rtmStop').disabled = false;
    $('rtmFitGo').disabled = true;
    setProgress(0);
    setStatus('Fitting…');
    try {
      const reply = await request({ type: 'fit', text: state.text, solver, params, columns }, (p) => {
        setProgress(p.frac);
        setStatus(`Fitting: ${p.runs.toLocaleString()} runs, the misfit ${p.ssr.toPrecision(4)} after ${p.iteration} `
          + `step${p.iteration === 1 ? '' : 's'}…`);
      });
      fitResult = reply;
      // The run at the fitted numbers first; the run against what was measured, before and after, a choice away.
      renderFitShow();
      $('rtmFitShow').value = 'data';
      setProgress(null);
      setStatus(`Fitted in ${reply.seconds.toFixed(2)} s, ${reply.runs} runs: ${reply.why}. The misfit went from `
        + `${reply.ssr0.toPrecision(4)} to ${reply.ssr.toPrecision(4)}.`, 'ok');
      renderFitResult();
      drawFit();
      renderUn();
    } catch (e) {
      setProgress(null);
      setStatus(`The fit could not be made: ${e.message}`, 'error');
    } finally {
      fitBusy = false;
      state.running = false;
      $('rtmRun').disabled = false;
      $('rtmStop').disabled = true;
      $('rtmFitGo').disabled = false;
    }
  }

  /** A number as the result table writes it: four figures. */
  const fit4 = (v) => (Math.abs(v) >= 1e-3 && Math.abs(v) < 1e5 ? String(Number(v.toPrecision(4))) : v.toExponential(3));

  /**
   * What the fit came to, as a table: each number from where it started to
   * where it ended, its standard error and a range of about 95 % -- times and
   * over 10 to the 1.96 standard errors for one fitted in its logarithm, plus
   * and minus 1.96 of them for a log K -- then the misfit and, for two or
   * more, their correlations.
   */
  function renderFitResult() {
    const box = $('rtmFitResult');
    const r = fitResult;
    box.hidden = !r;
    renderFitShow();
    if (!r) return;
    const rows = r.params.map((p) => {
      const se = p.se;
      let err = 'not determined';
      let range = '';
      if (se !== null && Number.isFinite(se)) {
        if (p.logged) {
          const fac = 10 ** se;
          err = `× or ÷ ${fac.toPrecision(4)}`;
          range = `${fit4(p.value / 10 ** (1.96 * se))} to ${fit4(p.value * 10 ** (1.96 * se))}`;
        } else {
          err = `± ${fit4(se)}`;
          range = `${fit4(p.value - 1.96 * se)} to ${fit4(p.value + 1.96 * se)}`;
        }
      }
      return `<tr><td>${esc(swVaryLabel(p))}</td><td>${esc(fit4(p.start))}</td><td><strong>${esc(fit4(p.value))}</strong></td>`
        + `<td>${esc(err)}</td><td>${esc(range)}</td></tr>`;
    }).join('');
    const corr = r.corr && r.params.length > 1
      ? `<p>Correlations: ${r.params.flatMap((p, a) => r.params.slice(a + 1).map((q, b) => `${esc(swVaryLabel(p))} with `
        + `${esc(swVaryLabel(q))} ${r.corr[a][a + 1 + b].toFixed(3)}`)).join('; ')}.</p>` : '';
    const runs = `in ${r.runs} runs, ${esc(r.why)}${r.skipped ? `; ${r.skipped} amount${r.skipped === 1 ? '' : 's'} at or below zero left out` : ''}`;
    /*
      Weighted, each residual over the standard deviation <DATA> gives it: the
      misfit is chi-square on n - np degrees of freedom, near 1 a degree where
      the model and the deviations both hold, and the standard errors are the
      deviations' own. Unweighted, the residuals' scatter stands in for them.
    */
    const misfit = r.weighted
      ? `<p>The misfit, each residual over its standard deviation: χ² ${r.chi2.toPrecision(4)} on ${r.dof} degree${r.dof === 1 ? '' : 's'} `
        + `of freedom (${r.n} point${r.n === 1 ? '' : 's'}, ${r.np} number${r.np === 1 ? '' : 's'})`
        + `${r.dof > 0 ? `, ${(r.chi2 / r.dof).toPrecision(3)} a degree; a χ² this large or larger by the deviations alone has a chance of `
          + `${r.pChi2 < 1e-4 ? r.pChi2.toExponential(1) : r.pChi2.toFixed(3)}` : ''}. From ${r.ssr0.toPrecision(4)} to `
        + `${r.chi2.toPrecision(4)} ${runs}. The standard errors are the standard deviations' own, not the residuals' scatter.</p>`
      : `<p>The misfit: the residuals' standard deviation ${r.sd !== null ? r.sd.toPrecision(3) : 'not known (as many numbers as points)'}`
        + ` over ${r.n} point${r.n === 1 ? '' : 's'} and ${r.np} number${r.np === 1 ? '' : 's'}; the sum of their squares from `
        + `${r.ssr0.toPrecision(4)} to ${r.ssr.toPrecision(4)} ${runs}.</p>`;
    box.innerHTML = '<table><thead><tr><th>Fitted</th><th>from</th><th>to</th><th>standard error</th><th>about 95 %</th></tr></thead>'
      + `<tbody>${rows}</tbody></table>${misfit}${corr}`;
  }

  /** A fitted point's place, for a legend or a hover: the column, and its cell and time or its distance and time. */
  const fitWhere = (p) => {
    const stride = (state.compiled && state.compiled.stride) || 1;
    // A table's own water, Zn+2 = 1e-4: the species it starts as the table says; and the pH it holds, pH = 6.5.
    if (p.kind === 'speciation') {
      const own = [...(p.water || []).map(([nm, v]) => `${nm} = ${fmtNumber(v)}`),
        ...(p.pH !== null && p.pH !== undefined ? [`pH = ${fmtNumber(p.pH)}`] : [])];
      return `the water of cell ${Math.floor(p.cell / stride)}${own.length ? `, ${own.join(', ')}` : ''}`;
    }
    return p.kind === 'time' ? `cell ${Math.floor(p.cell / stride)}${p.cell % stride ? `, rock layer ${p.cell % stride}` : ''}`
      : `at ${fmtTime(p.t)}`;
  };
  // What a table of a water is against, as its first column names it: pH, pe, Eh, or an element in the system, sys(Zn).
  const fitHeldName = (p) => (p.axis === 'tot' ? `sys(${p.species})` : p.axis);
  // Where along its table a point is: a time, a distance, or the pH, pe, Eh or total its water is held at.
  const fitAlong = (p) => (p.kind === 'time' ? fmtTime(p.t) : p.kind === 'speciation' ? `${fitHeldName(p)} ${fmtNumber(p.x)}`
    : `${fmtNumber(p.x)} m`);

  /*
    The Show bar: after a fit, all four; before one, the run against what
    was measured alone, where there is a run and <DATA> has measured
    something; with neither, no bar.
  */
  function renderFitShow() {
    const sel = $('rtmFitShow');
    const canMatch = !!state.result && matchPoints().points.length > 0;
    for (const o of sel.options) o.disabled = o.value === 'match' ? !canMatch : !fitResult;
    if (sel.selectedOptions[0] && sel.selectedOptions[0].disabled) sel.value = fitResult ? 'data' : 'match';
    $('rtmFitShowBar').hidden = !fitResult && !canMatch;
    $('rtmFitApply').hidden = !fitResult;
  }

  function drawFit() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartFit');
    const empty = $('rtmFitEmpty');
    const note = $('rtmFitNote');
    fitTableNow = null;
    if (!fitEmptyText) fitEmptyText = empty.textContent;
    renderFitShow();
    const show = $('rtmFitShow').value;
    $('rtmFitAgainstWrap').hidden = true;
    $('rtmFitMatch').hidden = true;
    if (show === 'match' && !$('rtmFitShowBar').hidden) { drawMatch(plot, empty, note); return; }
    if (!fitResult) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = fitEmptyText;
      note.textContent = '';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const r = fitResult;
    /*
      What the run and the measurements are drawn against: time, distance,
      or what a water was held at -- pH, pe, Eh, an element in the system --
      each its own; the first the fit has, in that order, unless another is
      chosen in against, which is there where the fit has more than one.
    */
    const groupOf = (c) => (c.kind === 'speciation' ? `held:${fitHeldName(c)}` : c.kind);
    const groupRank = (g) => ['time', 'held:pH', 'held:pe', 'held:Eh'].indexOf(g) + 1 || (g === 'distance' ? 9 : 5);
    const groups = [...new Set(r.curves.map(groupOf))].sort((a, b) => groupRank(a) - groupRank(b));
    const againstSel = $('rtmFitAgainst');
    const against = groups.includes(againstSel.value) ? againstSel.value : groups[0];
    if ([...againstSel.options].map((o) => o.value).join() !== groups.join()) {
      againstSel.replaceChildren(...groups.map((g) => {
        const o = document.createElement('option');
        o.value = g;
        const c = r.curves.find((cv) => groupOf(cv) === g);
        o.textContent = g === 'time' ? 'time' : g === 'distance' ? 'distance along the column'
          : c.axis === 'tot' ? `the ${c.species} in the cell, ${fitHeldName(c)}` : c.axis;
        return o;
      }));
    }
    againstSel.value = against;
    $('rtmFitAgainstWrap').hidden = show !== 'data' || groups.length < 2;
    $('rtmFitLogTWrap').hidden = show !== 'data' || against !== 'time';
    $('rtmFitLogYWrap').hidden = show !== 'data';
    const layout = baseLayout();
    layout.hovermode = 'closest';
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    // A column for each thing a water was held at, where a table is against one -- its pH, pe, Eh or total of an element,
    // sys(Zn) -- and the pH one is held at, pH = 6.5 on its table's line, in the pH's column.
    const held = r.points.filter((p) => p.kind === 'speciation');
    const heldRank = (nm) => { const i = ['pH', 'pe', 'Eh'].indexOf(nm); return i < 0 ? 9 : i; };
    const heldAxes = [...new Set([...held.map(fitHeldName), ...(held.some((p) => p.pH !== null && p.pH !== undefined) ? ['pH'] : [])])]
      .sort((a, b) => heldRank(a) - heldRank(b));
    const heldValue = (p, name) => (p.kind !== 'speciation' ? null : fitHeldName(p) === name ? p.x
      : name === 'pH' && p.pH !== null && p.pH !== undefined ? p.pH : null);
    // The band, about 95 % for the run, at each point measured; every curve with its band on a sheet of its own.
    const bandAt = r.points.some((p) => p.band);
    const curveWhere = (c) => fitWhere(c.kind === 'speciation' ? c : c.kind === 'time' ? { kind: 'time', cell: c.cell }
      : { kind: 'distance', t: c.t });
    const curveAlong = (c) => (c.kind === 'time' ? `time (${shownTime().sym})` : c.kind === 'distance' ? 'distance (m)'
      : c.axis === 'tot' ? `${fitHeldName(c)} (mol/kgw)` : fitHeldName(c));
    const pointsTable = () => ({ head: ['column', 'where', `time (${shownTime().sym})`, 'distance (m)',
      ...heldAxes.map((name) => (/^sys\(/.test(name) ? `${name} (mol/kgw)` : name)), 'measured', ...(r.weighted ? ['sd'] : []),
      'the run', ...(bandAt ? ['about 95 % from', 'about 95 % to'] : []), 'residual', ...(r.weighted ? ['residual over its sd'] : [])],
    name: 'rtm_fit',
    rows: r.points.map((p) => {
      const run = p.index ? p.value + p.residual : p.value * 10 ** p.residual;
      return [labelOf(p.key), fitWhere(p), showT(p.t), p.kind === 'speciation' ? null : p.x,
        ...heldAxes.map((name) => heldValue(p, name)), p.value, ...(r.weighted ? [p.sd] : []), run,
        ...(bandAt ? (p.band || [null, null]) : []), p.residual, ...(r.weighted ? [p.normalized] : [])];
    }),
    extra: [{ name: 'curves', head: ['column', 'where', 'against', 'at', 'the run', 'about 95 % from', 'about 95 % to'],
      rows: r.curves.flatMap((c) => c.x.map((x, i) => [labelOf(c.key), curveWhere(c), curveAlong(c), c.kind === 'time' ? showT(x) : x, c.y[i],
        c.band ? c.band.lo[i] : null, c.band ? c.band.hi[i] : null])) }] });
    if (show === 'history') {
      Plotly.react(plot, [{ type: 'scatter', mode: 'lines+markers', name: 'the misfit', x: r.history.map((h) => h.iteration),
        y: r.history.map((h) => h.ssr), line: { color: palette[0] }, marker: { size: 6 },
        hovertemplate: 'step %{x}: %{y:.4g}<extra></extra>' }], {
        ...layout, xaxis: { ...layout.xaxis, title: { text: 'step of the fit', font: { size: 11 } }, dtick: 1 },
        yaxis: { ...layout.yaxis, type: 'log', title: { text: 'the sum of the squared residuals', font: { size: 11 } } } }, PLOT_CONFIG);
      fitTableNow = { head: ['step', 'misfit', 'runs'], rows: r.history.map((h) => [h.iteration, h.ssr, h.runs]), name: 'rtm_fit_misfit' };
      note.textContent = `${r.history.length - 1} step${r.history.length === 2 ? '' : 's'} taken, ${r.runs} runs`;
      return;
    }
    if (show === 'residuals') {
      const keys = [...new Set(r.points.map((p) => p.key))];
      const traces = keys.map((key, q) => {
        const pts = r.points.map((p, i) => [p, i]).filter(([p]) => p.key === key);
        return { type: 'scatter', mode: 'markers', name: labelOf(key), x: pts.map(([, i]) => i + 1),
          y: pts.map(([p]) => (r.weighted ? p.normalized : p.residual)),
          marker: { size: 8, color: palette[q % palette.length] },
          text: pts.map(([p]) => `${esc(labelOf(p.key))}, ${esc(fitWhere(p))}, ${esc(fitAlong(p))}`),
          hovertemplate: '%{text}: %{y:.4g}<extra></extra>' };
      });
      layout.xaxis.title = { text: 'the point measured, in the order of <DATA>', font: { size: 11 } };
      layout.yaxis.title = { text: r.weighted ? 'residual over its standard deviation'
        : 'residual: log₁₀(run / measured), or run − measured for pH, SI and the like', font: { size: 11 } };
      // Weighted, a residual within its standard deviation is inside the band of ±1.
      if (r.weighted) {
        layout.shapes = [{ type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: -1, y1: 1, line: { width: 0 }, fillcolor: 'rgba(128,128,128,0.12)' }];
      }
      layout.shapes = [...(layout.shapes || []),
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: themeColors().text, width: 1, dash: 'dot' } }];
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      fitTableNow = pointsTable();
      note.textContent = `${r.n} points${r.weighted ? ', each over its standard deviation; the band is one either way' : ''}`;
      return;
    }
    // The run at the fitted numbers where it was measured, and the measurements: along the run at a cell where the tables
    // are in time, along the column at a time where they are in distance; a water held at each pH, pe or Eh where they
    // are against one, a sorption edge.
    const logT = $('rtmFitLogT').checked;
    const logY = $('rtmFitLogY').checked;
    const curves = r.curves.filter((c) => groupOf(c) === against);
    const along = against === 'time' || against === 'distance' ? against : 'speciation';
    // An element in the system over decades: on a log axis.
    const totAxis = along === 'speciation' && curves[0].axis === 'tot';
    const tableOf = (c) => (along === 'time' ? c.cell : along === 'speciation' ? c.table : c.t);
    const several = new Set(curves.map(tableOf)).size > 1;
    // Only pH, SI, a share and the like: on the left, as they are, and no log axis to choose.
    const allIndex = curves.every((c) => c.index);
    $('rtmFitLogYWrap').hidden = show !== 'data' || allIndex;
    const traces = [];
    let right = false;
    let banded = false;
    // A colour of the palette, see-through: a band's.
    const tint = (hex, a) => {
      const v = parseInt(hex.slice(1), 16);
      return `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${a})`;
    };
    curves.forEach((c, q) => {
      const color = palette[q % palette.length];
      // A water of its own, or one held at a pH of the table's, is named by it even alone.
      const ownWater = along === 'speciation' && ((c.water && c.water.length) || (c.pH !== null && c.pH !== undefined));
      const where = several || ownWater ? `, ${fitWhere(along === 'time' ? { kind: 'time', cell: c.cell }
        : along === 'speciation' ? { kind: 'speciation', cell: c.cell, water: c.water, pH: c.pH } : { kind: 'distance', t: c.t })}` : '';
      const name = `${labelOf(c.key)}${where}`;
      const onRight = c.index && !allIndex;
      right = right || onRight;
      const keep = c.x.map((x, i) => (along !== 'time' || !logT || x > 0) && Number.isFinite(c.y[i])
        && (c.index || !logY || c.y[i] > 0));
      // The band, about 95 % for the curve: its lower edge, then its upper filled down to it, under the line.
      if (c.band) {
        const bx = c.x.filter((_, i) => keep[i]).map((x) => (along === 'time' ? showT(x) : x));
        const side = onRight ? { yaxis: 'y2' } : {};
        traces.push({ type: 'scatter', mode: 'lines', name: 'about 95 % for the curve, from', x: bx, y: c.band.lo.filter((_, i) => keep[i]),
          line: { width: 0, color }, hoverinfo: 'skip', showlegend: false, legendgroup: 'band', ...side });
        traces.push({ type: 'scatter', mode: 'lines', name: 'about 95 % for the curve', x: bx, y: c.band.hi.filter((_, i) => keep[i]),
          line: { width: 0, color }, fill: 'tonexty', fillcolor: tint(color, 0.16), hoverinfo: 'skip', showlegend: !banded,
          legendgroup: 'band', ...side });
        banded = true;
      }
      traces.push({ type: 'scatter', mode: 'lines', name, x: c.x.filter((_, i) => keep[i]).map((x) => (along === 'time' ? showT(x) : x)),
        y: c.y.filter((_, i) => keep[i]),
        line: { color, width: 1.8 }, ...(onRight ? { yaxis: 'y2' } : {}) });
      const pts = r.points.filter((p) => p.kind === along && p.key === c.key && (along === 'time' ? p.cell === c.cell
        : along === 'speciation' ? p.table === c.table : p.t === c.t));
      traces.push({ type: 'scatter', mode: 'markers', name: `${name}, measured`, x: pts.map((p) => (along === 'time' ? showT(p.t) : p.x)),
        y: pts.map((p) => p.value), marker: { size: 8, symbol: 'circle-open', color, line: { width: 1.6 } },
        ...(r.weighted ? { error_y: { type: 'data', array: pts.map((p) => p.sd), visible: true, color, thickness: 1.2, width: 4 } } : {}),
        ...(onRight ? { yaxis: 'y2' } : {}) });
    });
    layout.xaxis.type = (along === 'time' && logT) || totAxis ? 'log' : 'linear';
    // A total in mol/kgw in powers of ten, as the amounts are: 10⁻⁶, not 1µ.
    if (totAxis) layout.xaxis.exponentformat = 'power';
    layout.xaxis.title = { text: along === 'time' ? `time (${shownTime().sym})`
      : totAxis ? `${curves[0].species} in the cell, dissolved, sorbed and as minerals (mol/kgw)`
        : along === 'speciation' ? dgLabel({ kind: curves[0].axis }) : 'distance from the left-hand face (m)', font: { size: 11 } };
    layout.yaxis.type = logY && !allIndex ? 'log' : 'linear';
    layout.yaxis.title = { text: allIndex ? [...new Set(curves.map((cv) => axisLabelOf(cv.key)))].join(', ')
      : 'concentration, or an amount of <OUTPUT>', font: { size: 11 } };
    if (right) {
      const c = themeColors();
      layout.yaxis2 = { overlaying: 'y', side: 'right', gridcolor: c.grid, zeroline: false, linecolor: c.grid, showgrid: false,
        automargin: true, title: { text: [...new Set(curves.filter((cv) => cv.index).map((cv) => axisLabelOf(cv.key)))].join(', '), font: { size: 11 } } };
      layout.margin.r = 64;
    }
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    fitTableNow = pointsTable();
    note.textContent = `${along !== 'speciation' ? 'the run at the fitted numbers'
      : totAxis ? `the water at the fitted numbers, with each total of ${curves[0].species} in the cell`
        : `the water at the fitted numbers, held at each ${curves[0].axis}`}`
      + `${banded ? '; shaded, about 95 % for the curve, from the fitted numbers\' standard errors and correlations' : ''}`;
  }

  /*
    THE RUN AGAINST WHAT WAS MEASURED, one to one (Show on the Fit tab, with
    a fit or without one): each value <DATA> measured set against the run's
    there, and for each column how far off -- the mean residual, its root
    mean square and the worst point -- with the residual the Fit takes: an
    amount's the log10 of the run's value over the one measured, pH, SI and
    the like the run's less the one measured. The run on show is read between
    its stored points, and along the column between the cells either side,
    as the Fit reads a table in distance; the fitted run's values are the
    fit's own, at the times measured; a run kept beside is read as the run on
    show is. An amount measured at or below zero has no logarithm and is left
    out, as the Fit leaves it out.
  */
  /** Each value <DATA> measured, where it is and what kind of residual it has; and how many amounts at or below zero were left out. */
  function matchPoints() {
    const m = state.compiled;
    const stride = (m && m.stride) || 1;
    const points = [];
    let skipped = 0;
    ((m && m.data) || []).forEach((tab, table) => tab.kind !== 'speciation' && tab.columns.forEach((key, j) => {
      if (/^sd\(.+\)$/.test(key)) return;
      const index = axisOf(key) === 'index';
      for (const row of tab.rows) {
        const value = row[j + 1];
        if (value === null) continue;
        if (!index && !(value > 0)) { skipped++; continue; }
        const layer = Math.min(tab.layer || 0, stride - 1);
        points.push(tab.kind === 'time'
          ? { table, key, index, value, kind: 'time', t: row[0], x: null, cell: tab.cell || 0, layer }
          : { table, key, index, value, kind: 'distance', t: tab.at, x: row[0], cell: null, layer });
      }
    }));
    return { points, skipped };
  }
  // A point's name, the same for the Fit's own points and the page's: its table, its column, its time or its distance.
  const matchId = (p) => `${p.table}|${p.key}|${p.kind === 'time' ? `t${p.t}` : `x${p.x}`}`;
  /** Where t falls among run r's stored times: [i, w], (1 - w) of point i and w of point i + 1; null outside the run. */
  function bracketTime(r, t) {
    const T = r.t;
    const n = r.n;
    const tol = 1e-12 * Math.max(Math.abs(T[n - 1]), 1e-300);
    if (!(t >= T[0] - tol && t <= T[n - 1] + tol)) return null;
    if (t >= T[n - 1]) return [n - 1, 0];
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (T[mid] <= t) lo = mid; else hi = mid;
    }
    const gap = T[hi] - T[lo];
    return [lo, gap > 0 && t > T[lo] ? (t - T[lo]) / gap : 0];
  }
  /** Run r's `key` in model cell mc at stored point i: a number, undefined while a quantity is being worked out, NaN where it failed. */
  function matchValueIn(r, key, mc, i) {
    if (runQuantity(r, key)) {
      const s = quantitySeries(key, mc, r);
      return s ? s[i] : quantityPending(key, mc, r) ? undefined : NaN;
    }
    return r.states[i * r.width + mc * r.model.nspecies + r.model.species.indexOf(key)];
  }
  /**
   * Run r at each point measured: { v, res } for each, null where it has no value there, undefined while a quantity
   * is still to come; what is to be worked out (key -> model cells), and why some have none.
   */
  function matchRun(r, points) {
    const m = r.model;
    const stride = m.stride || 1;
    const nf = m.fracture || 1;
    const pending = new Map();
    const lacks = new Set();
    let after = 0;
    const out = points.map((p) => {
      if (p.layer > 0 && !(p.layer < stride)) { lacks.add(`no rock layer ${p.layer}`); return null; }
      if (!runHas(r, p.key)) { lacks.add(`no ${labelOf(p.key)}`); return null; }
      if (p.kind === 'time' && !(p.cell < nf)) { lacks.add(`no cell ${p.cell}`); return null; }
      const b = bracketTime(r, p.t === null ? r.t[r.n - 1] : p.t);
      if (!b) { after++; return null; }
      const [i, w] = b;
      let waiting = false;
      const at = (mc) => {
        const a = matchValueIn(r, p.key, mc, i);
        const c = w > 0 ? matchValueIn(r, p.key, mc, i + 1) : a;
        if (a === undefined || c === undefined) {
          waiting = true;
          if (!pending.has(p.key)) pending.set(p.key, new Set());
          pending.get(p.key).add(mc);
          return NaN;
        }
        return w > 0 ? a + (c - a) * w : a;
      };
      let v;
      if (p.kind === 'time') v = at(p.cell * stride + p.layer);
      else {
        // Along the fracture: between the two cells either side, as a straight line; past the ends, the end cell.
        const xs = m.centres;
        if (nf === 1 || p.x <= xs[0]) v = at(p.layer);
        else if (p.x >= xs[nf - 1]) v = at((nf - 1) * stride + p.layer);
        else {
          let c = 0;
          while (c < nf - 2 && xs[c + 1] < p.x) c++;
          const f = (p.x - xs[c]) / (xs[c + 1] - xs[c]);
          v = at(c * stride + p.layer) * (1 - f) + at((c + 1) * stride + p.layer) * f;
        }
      }
      if (waiting) return undefined;
      if (!Number.isFinite(v)) return null;
      return { v, res: p.index ? v - p.value : Math.log10(Math.max(v, 1e-300) / p.value) };
    });
    return { out, pending, lacks, after };
  }
  /** How far off a run is, column by column and all together: points, mean residual, root mean square, sum of squares, the worst. */
  function matchStats(points, rows) {
    const blank = () => ({ n: 0, sum: 0, ss: 0, worst: null });
    const by = new Map();
    const all = blank();
    rows.forEach((row, j) => {
      if (!row) return;
      const p = points[j];
      if (!by.has(p.key)) by.set(p.key, blank());
      for (const s of [by.get(p.key), all]) {
        s.n++;
        s.sum += row.res;
        s.ss += row.res * row.res;
        if (!s.worst || Math.abs(row.res) > Math.abs(s.worst.res)) s.worst = { res: row.res, p };
      }
    });
    const done = (s) => ({ ...s, bias: s.n ? s.sum / s.n : NaN, rms: s.n ? Math.sqrt(s.ss / s.n) : NaN });
    return { by: new Map([...by].map(([k, s]) => [k, done(s)])), all: done(all) };
  }
  // A point's place for a person: its cell and time, or its distance and time.
  function matchWhere(p, r) {
    const stride = (state.compiled && state.compiled.stride) || 1;
    if (p.kind === 'time') return `cell ${p.cell}${p.layer && stride > 1 ? `, rock layer ${p.layer}` : ''}, ${fmtTime(p.t)}`;
    return `${fmtNumber(p.x)} m at ${fmtTime(p.t === null ? r.t[r.n - 1] : p.t)}`;
  }
  // A residual for a person: an amount's as the factor the run is of what was measured, pH and the like as the difference.
  const matchRes = (res, index) => (index ? `${res < 0 ? '−' : '+'}${fit4(Math.abs(res))}`
    : `${res < 0 ? '−' : '+'}${Math.abs(res).toFixed(3)} (× ${fit4(10 ** res)})`);

  let fitEmptyText = '';
  function drawMatch(plot, empty, note) {
    const r = state.result;
    const { points, skipped } = matchPoints();
    const box = $('rtmFitMatch');
    const nothing = (text) => {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = text;
      note.textContent = '';
    };
    if (!r || !points.length) { nothing('Run the model: each value <DATA> measured is then set against the run\'s.'); return; }
    // The runs set against what was measured: the run on show, the fitted run, the run kept beside.
    const mine = matchRun(r, points);
    const runs = [{ label: 'this run', suffix: '', symbol: 'circle', rows: mine.out, how: mine, r }];
    // The fitted run where the fit was made against these very measurements: each of its points one of these, the same value.
    const here = new Map(points.map((p) => [matchId(p), p]));
    const staleFit = !!fitResult && !fitResult.points.every((fp) => { const p = here.get(matchId(fp)); return p && p.value === fp.value; });
    if (fitResult && !staleFit) {
      const fitted = new Map(fitResult.points.map((fp) => [matchId(fp), fp]));
      runs.push({ label: 'the fitted run', suffix: ', fitted', symbol: 'diamond', how: null, r: null, rows: points.map((p) => {
        const fp = fitted.get(matchId(p));
        return fp ? { v: fp.index ? fp.value + fp.residual : fp.value * 10 ** fp.residual, res: fp.residual } : null;
      }) });
    }
    const bk = besideRun();
    if (bk) {
      const theirs = matchRun(bk.r, points);
      runs.push({ label: bk.label, suffix: `, ${bk.label}`, symbol: 'circle-open', rows: theirs.out, how: theirs, r: bk.r });
    }
    // What is still to be worked out: asked for, and drawn when it comes.
    const coming = new Set();
    for (const run of runs) {
      if (!run.how) continue;
      for (const [key, cells] of run.how.pending) { coming.add(labelOf(key)); fetchQuantities([key], [...cells], run.r); }
    }
    if (coming.size) { nothing(`Working out ${[...coming].join(', ')} where it was measured…`); return; }
    // A kept run without any of the columns is left out of the table and the chart; the note says what it has not got.
    const keptHow = bk ? runs[runs.length - 1].how : null;
    for (let q = runs.length - 1; q > 0; q--) if (!runs[q].rows.some(Boolean)) runs.splice(q, 1);
    empty.hidden = true;
    plot.hidden = false;
    const keys = [...new Set(points.map((p) => p.key))];
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const both = points.some((p) => p.index) && points.some((p) => !p.index);
    const span = { amount: [Infinity, -Infinity], index: [Infinity, -Infinity] };
    const widen = (kind, v) => {
      if (!Number.isFinite(v) || (kind === 'amount' && !(v > 0))) return;
      span[kind][0] = Math.min(span[kind][0], v);
      span[kind][1] = Math.max(span[kind][1], v);
    };
    const traces = [];
    for (const run of runs) {
      for (const key of keys) {
        const js = points.map((_, j) => j).filter((j) => points[j].key === key && run.rows[j]);
        if (!js.length) continue;
        const index = points[js[0]].index;
        const kind = index ? 'index' : 'amount';
        const color = palette[keys.indexOf(key) % palette.length];
        js.forEach((j) => { widen(kind, points[j].value); widen(kind, run.rows[j].v); });
        traces.push({ type: 'scatter', mode: 'markers', name: `${labelOf(key)}${run.suffix}`,
          x: js.map((j) => points[j].value), y: js.map((j) => run.rows[j].v),
          marker: { size: run.symbol === 'diamond' ? 9 : 8, symbol: run.symbol, color, line: { width: 1.6, color } },
          text: js.map((j) => `${esc(labelOf(key))}, ${esc(matchWhere(points[j], r))}, ${esc(run.label)}: measured `
            + `${fit4(points[j].value)}, the run ${fit4(run.rows[j].v)}, ${matchRes(run.rows[j].res, index)}`),
          hovertemplate: '%{text}<extra></extra>', ...(both && index ? { xaxis: 'x2', yaxis: 'y2' } : {}) });
      }
    }
    // Each panel square on equal axes, the line of one to one through it; for amounts, twice and half as much dashed.
    const c = themeColors();
    const layout = baseLayout();
    layout.hovermode = 'closest';
    const guides = [];
    const panel = (kind, xa, ya, domain) => {
      const [lo, hi] = span[kind];
      if (!(hi >= lo)) return;
      const log = kind === 'amount';
      const a = log ? Math.log10(lo) : lo;
      const b = log ? Math.log10(hi) : hi;
      const pad = Math.max(0.05 * (b - a), log ? 0.15 : 0.05 * Math.max(Math.abs(a), Math.abs(b), 1e-300));
      const range = [a - pad, b + pad];
      const from = log ? 10 ** range[0] : range[0];
      const to = log ? 10 ** range[1] : range[1];
      const axisOn = (text, anchor) => ({ title: { text, font: { size: 11 } }, type: log ? 'log' : 'linear', range, gridcolor: c.grid,
        zeroline: false, linecolor: c.grid, exponentformat: 'power', anchor, constrain: 'domain', ...(domain ? { domain } : {}) });
      layout[xa === 'x' ? 'xaxis' : 'xaxis2'] = axisOn(`measured${both ? (log ? ', amounts' : ', pH, SI and the like') : ''}`,
        ya === 'y' ? 'y' : 'y2');
      layout[ya === 'y' ? 'yaxis' : 'yaxis2'] = { ...axisOn('the run', xa === 'x' ? 'x' : 'x2'), scaleanchor: xa, scaleratio: 1,
        ...(domain ? { domain: [0, 1] } : {}) };
      const line = (k, dash, name) => guides.push({ type: 'scatter', mode: 'lines', x: [from, to], y: [from * k, to * k],
        line: { color: c.text, width: dash ? 1 : 1.2, dash: dash || 'solid' }, hoverinfo: 'skip', showlegend: false, name,
        ...(xa === 'x' ? {} : { xaxis: 'x2', yaxis: 'y2' }) });
      line(1, '', 'one to one');
      if (log) { line(2, 'dash', 'twice'); line(0.5, 'dash', 'half'); }
    };
    if (both) {
      panel('amount', 'x', 'y', [0, 0.45]);
      panel('index', 'x2', 'y2', [0.55, 1]);
    } else panel(points[0].index ? 'index' : 'amount', 'x', 'y', null);
    Plotly.react(plot, [...guides, ...traces], layout, PLOT_CONFIG);
    // The table: each column, each run; then each run all together, its sum of squares the Fit's misfit.
    const stats = runs.map((run) => matchStats(points, run.rows));
    const rows = [];
    const html = [];
    // kind: 'amount', 'index', or 'all' -- the columns together, whose residuals are of both kinds: no bias, no factor.
    const line = (col, run, s, kind) => {
      const worst = s.worst ? `${matchRes(s.worst.res, s.worst.p.index)}, ${kind === 'all' ? `${labelOf(s.worst.p.key)}, ` : ''}`
        + `${matchWhere(s.worst.p, r)}` : '';
      const spread = !s.n ? '' : kind === 'amount' ? `${s.rms.toFixed(3)} (× ${fit4(10 ** s.rms)})` : fit4(s.rms);
      rows.push([col, run.label, s.n, kind === 'all' ? null : s.bias, s.rms, s.ss, s.worst ? s.worst.res : null,
        s.worst ? `${labelOf(s.worst.p.key)}, ${matchWhere(s.worst.p, r)}` : '']);
      html.push(`<tr><td>${esc(col)}</td><td>${esc(run.label)}</td><td>${s.n}</td>`
        + `<td>${kind === 'all' || !s.n ? '' : esc(matchRes(s.bias, kind === 'index'))}</td><td>${esc(spread)}</td>`
        + `<td>${s.n ? esc(fit4(s.ss)) : ''}</td><td>${esc(worst)}</td></tr>`);
    };
    for (const key of keys) {
      const kind = points.find((p) => p.key === key).index ? 'index' : 'amount';
      runs.forEach((run, q) => { const s = stats[q].by.get(key); if (s) line(labelOf(key), run, s, kind); });
    }
    runs.forEach((run, q) => line('all together, as the Fit sums them', run, stats[q].all, 'all'));
    box.innerHTML = '<table><thead><tr><th>Column</th><th>Run</th><th>points</th><th>bias, the mean residual</th>'
      + '<th>spread, its root mean square</th><th>sum of squares</th><th>the worst</th></tr></thead>'
      + `<tbody>${html.join('')}</tbody></table>`
      + '<p>A residual is log₁₀ of the run over what was measured for an amount, shown as the factor the run is of it, '
      + 'and the run less what was measured for pH, SI and the like.</p>';
    box.hidden = false;
    fitTableNow = { head: ['column', 'where', `time (${shownTime().sym})`, 'distance (m)', 'measured', ...runs.flatMap((run) => [run.label, `residual, ${run.label}`])],
      name: 'rtm_against_measured',
      rows: points.map((p, j) => [labelOf(p.key), p.kind === 'time' ? `cell ${p.cell}` : 'along the column',
        showT(p.t === null ? r.t[r.n - 1] : p.t), p.x, p.value, ...runs.flatMap((run) => (run.rows[j] ? [run.rows[j].v, run.rows[j].res] : [null, null]))]),
      extra: [{ name: 'how far off', head: ['column', 'run', 'points', 'bias', 'spread (root mean square)', 'sum of squares',
        'worst residual', 'where'], rows }] };
    const kept = bk ? runs.find((run) => run.r === bk.r) : null;
    const left = [skipped ? `${skipped} amount${skipped === 1 ? '' : 's'} at or below zero left out` : '',
      mine.after ? `${mine.after} after the run's end` : '', mine.lacks.size ? `this run has ${[...mine.lacks].join(', ')}` : '',
      keptHow && keptHow.lacks.size ? `${bk.label} has ${[...keptHow.lacks].join(', ')}` : '',
      keptHow && keptHow.after ? `${keptHow.after} after the end of ${bk.label}` : '',
      staleFit ? 'the fit was made against other measurements: <DATA> has changed since' : ''];
    note.textContent = [`${points.length} value${points.length === 1 ? '' : 's'} measured, each column in its own unit`,
      'this run read between its stored points and cells, linearly',
      runs.some((run) => run.symbol === 'diamond') ? 'the fitted run at the times measured, as the fit ran it' : '',
      kept ? `${bk.label} hollow` : '', ...left].filter(Boolean).join('; ');
  }

  /** The fitted numbers into the model text, to six figures, each where withValue puts it. */
  function fitApply() {
    if (!fitResult) return;
    let text = state.text;
    try {
      for (const p of fitResult.params) text = RtmModel.withValue(text, p, Number(p.value.toPrecision(6)));
    } catch (e) { setStatus(`The fitted values could not be put in: ${e.message}`, 'error'); return; }
    const kept = putAside(text);
    state.text = text;
    $('rtmText').value = text;
    renderHighlight();
    showAside(kept);
    state.fit.params.forEach((row, i) => { if (fitResult.params[i]) row.start = fmtNumber(Number(fitResult.params[i].value.toPrecision(6))); });
    saveState();
    compile().then(() => setStatus(`The fitted values are in the model text: ${fitResult.params.map((p) => `${swVaryLabel(p)} = `
      + `${Number(p.value.toPrecision(6))}`).join(', ')}.`, 'ok'));
  }

  /* ---------------------------------------------------------------------
     Uncertainty: the model run for draws of what is uncertain, and the runs
     drawn as bands, as Gibbs Studio's Monte Carlo

     Each number given a distribution is drawn by distributions.html's own
     engine (resources/js/distributions/, loaded when first needed), each
     from a stream of its own, by Latin hypercube, Sobol or simple random;
     numbers from a fit are drawn together with its correlations, through a
     Gaussian copula. The worker runs the draws as a sweep (rtmSweep, the
     draws given), each run read at the same times so that the bands are
     taken across runs at each of them.
     --------------------------------------------------------------------- */
  let unResult = null;
  let unTableNow = null;
  let unBusy = false;
  const UN_MAX = 8;
  // The families offered, and what each row's three fields are for them.
  const UN_FAMILIES = {
    normal: { label: 'normal', fields: ['mean', 'SD'] },
    lognormal: { label: 'lognormal', fields: ['median', '× or ÷'] },
    uniform: { label: 'uniform', fields: ['from', 'to'] },
    loguniform: { label: 'log-uniform', fields: ['from', 'to'] },
    triangular: { label: 'triangular', fields: ['from', 'most likely', 'to'] },
  };

  /** distributions.html's engine, loaded once: the distributions and the sampling schemes. */
  let unEngine = null;
  async function distributionsEngine() {
    if (!unEngine) {
      const base = new URL('resources/js/distributions/', document.baseURI).href;
      unEngine = Promise.all([import(`${base}dist.js`), import(`${base}sampling.js`)])
        .then(([dist, sampling]) => ({ makeDistribution: dist.makeDistribution, uniforms: sampling.uniforms }))
        .catch((e) => { unEngine = null; throw e; });
    }
    return unEngine;
  }

  /** A row's distribution as distributions.html specifies one. */
  function unSpec(row) {
    const [a, b, c] = [row.a, row.b, row.c].map(Number);
    if (row.family === 'normal') return { family: 'normal', params: { mu: a, sigma: b } };
    if (row.family === 'lognormal') {
      if (!(a > 0)) throw new Error('a lognormal\'s median is above zero');
      if (!(b > 1)) throw new Error('a lognormal\'s factor, its median times or over at one standard deviation, is above 1');
      return { family: 'lognormal', params: { mu: Math.log(a), sigma: Math.log(b) } };
    }
    if (row.family === 'uniform') return { family: 'uniform', params: { a, b } };
    if (row.family === 'loguniform') return { family: 'loguniform', params: { a, b } };
    return { family: 'triangular', params: { a, c: b, b: c } };
  }

  /** A new row's distribution about the value the text gives: a log K normal by 0.2, a number above zero lognormal ×/÷ 2. */
  function unDefault(what) {
    const c = swCurrent(what);
    if (what.startsWith('logK:')) return { family: 'normal', a: fmtNumber(c === null ? 0 : c), b: '0.2', c: '' };
    if (c !== null && c > 0) return { family: 'lognormal', a: fmtNumber(c), b: '2', c: '' };
    return { family: 'normal', a: fmtNumber(c === null ? 0 : c), b: fmtNumber(Math.max(Math.abs(c || 0) * 0.1, 1e-12)), c: '' };
  }

  function renderUn() {
    const u = state.unc;
    const m = state.compiled;
    const groups = tuneChoices();
    const all = groups.flatMap((g) => g.items.map((it) => it.value));
    const first = all.find((v) => v.startsWith('parameter:')) || all.find((v) => v.startsWith('rate:'))
      || all.find((v) => v.startsWith('logK:')) || all[0] || '';
    if (!u.rows.length && first) u.rows.push({ what: first, ...unDefault(first) });
    for (const row of u.rows) if (all.length && !all.includes(row.what)) Object.assign(row, { what: first, ...unDefault(first) });
    const opts = (chosen) => groups.map((g) => `<optgroup label="${esc(g.label)}">${g.items.map((it) => `<option value="${esc(it.value)}"`
      + `${it.value === chosen ? ' selected' : ''}>${esc(it.label)}</option>`).join('')}</optgroup>`).join('');
    $('rtmUnRows').innerHTML = u.rows.map((row, i) => {
      const fam = UN_FAMILIES[row.family] || UN_FAMILIES.normal;
      const fields = fam.fields.map((label, j) => `${esc(label)} <input type="text" class="rtm-dg-num" data-row="${i}" `
        + `data-field="${'abc'[j]}" aria-label="${esc(label)}" value="${esc(row['abc'[j]])}" data-on-change="rtm:unSettings">`).join(' ');
      return `<span class="rtm-fit-row">${i ? 'and' : 'Draw'} <select data-row="${i}" data-field="what" aria-label="what is uncertain" `
        + `data-on-change="rtm:unSettings">${opts(row.what)}</select> from a <select data-row="${i}" data-field="family" `
        + `aria-label="its distribution" data-on-change="rtm:unSettings">${Object.entries(UN_FAMILIES).map(([id, f]) => `<option `
        + `value="${id}"${id === row.family ? ' selected' : ''}>${f.label}</option>`).join('')}</select> ${fields}`
        + `${u.rows.length > 1 ? ` <button type="button" class="rtm-btn secondary small rtm-fit-x" data-row="${i}" data-on-click="rtm:unRemove" `
          + 'aria-label="Leave it out">×</button>' : ''}</span>`;
    }).join('');
    $('rtmUnAdd').hidden = u.rows.length >= UN_MAX;
    $('rtmUnFromFit').disabled = !fitResult;
    $('rtmUnN').value = u.n;
    $('rtmUnScheme').value = u.scheme;
    $('rtmUnSeed').value = u.seed;
    const cells = m ? m.fracture : 1;
    if (!(u.cell < cells)) u.cell = cells - 1;
    $('rtmUnCell').innerHTML = Array.from({ length: cells }, (_, i) => `<option value="${i}"${i === u.cell ? ' selected' : ''}>`
      + `${i}${m && m.centres && cells > 1 ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
    $('rtmUnCellWrap').hidden = cells < 2;
    // The fit's correlations go with its numbers as it gave them, in its order: changed, they no longer apply.
    $('rtmUnCorrWrap').hidden = !unCorrApplies() || u.rows.length < 2;
    $('rtmUnCorr').checked = u.useCorr;
    $('rtmUnGo').disabled = unBusy;
  }

  /** Whether the rows are the last fit's numbers, in its order, so that its correlations apply. */
  function unCorrApplies() {
    const c = state.unc.corr;
    return !!(c && c.whats.length === state.unc.rows.length && c.whats.every((w, i) => state.unc.rows[i].what === w));
  }

  function readUn() {
    const u = state.unc;
    document.querySelectorAll('#rtmUnRows [data-row]').forEach((el) => {
      const row = u.rows[Number(el.dataset.row)];
      const f = el.dataset.field;
      if (!row || !f) return;
      if (f === 'what') {
        if (el.value !== row.what) Object.assign(row, { what: el.value, ...unDefault(el.value) });
      } else if (f === 'family') {
        if (el.value !== row.family) {
          // A new family about the old centre: its middle where it has one, and a spread like the old one.
          const centre = Number(row.family === 'uniform' || row.family === 'loguniform' ? row.a : row.family === 'triangular' ? row.b : row.a);
          const c = Number.isFinite(centre) ? centre : (swCurrent(row.what) || 0);
          row.family = el.value;
          if (el.value === 'normal') Object.assign(row, { a: fmtNumber(c), b: fmtNumber(Math.max(Math.abs(c) * 0.1, 1e-12)), c: '' });
          else if (el.value === 'lognormal') Object.assign(row, { a: fmtNumber(c > 0 ? c : 1), b: '2', c: '' });
          else if (el.value === 'triangular') Object.assign(row, { a: fmtNumber(c > 0 ? c / 2 : c - 1), b: fmtNumber(c), c: fmtNumber(c > 0 ? c * 2 : c + 1) });
          else Object.assign(row, { a: fmtNumber(c > 0 ? c / 2 : c - 1), b: fmtNumber(c > 0 ? c * 2 : c + 1), c: '' });
        }
      } else row[f] = el.value.trim();
    });
    u.n = $('rtmUnN').value.trim();
    u.scheme = $('rtmUnScheme').value;
    u.seed = $('rtmUnSeed').value.trim();
    u.cell = Number($('rtmUnCell').value) || 0;
    u.useCorr = $('rtmUnCorr').checked;
  }

  /** The last fit's numbers as rows, each about its fitted value by its standard error, and its correlations with them. */
  function unFromFit() {
    if (!fitResult) return;
    const rows = fitResult.params.filter((p) => p.se !== null && Number.isFinite(p.se));
    if (!rows.length) { setStatus('The last fit gave no standard errors to draw from.', 'error'); return; }
    state.unc.rows = rows.map((p) => ({ what: `${p.kind}:${p.name}`, family: p.logged ? 'lognormal' : 'normal',
      a: String(Number(p.value.toPrecision(6))), b: String(Number((p.logged ? 10 ** p.se : p.se).toPrecision(6))), c: '' }));
    const idx = rows.map((p) => fitResult.params.indexOf(p));
    state.unc.corr = fitResult.corr ? { whats: state.unc.rows.map((r) => r.what), m: idx.map((a) => idx.map((b) => fitResult.corr[a][b])) } : null;
    state.unc.useCorr = true;
    saveState();
    renderUn();
  }

  /** The lower triangle L of a symmetric positive definite C = L L^T, or null. */
  function cholesky(C) {
    const n = C.length;
    const L = Array.from({ length: n }, () => new Float64Array(n));
    for (let i = 0; i < n; i++) {
      for (let j = 0; j <= i; j++) {
        let v = C[i][j];
        for (let k = 0; k < j; k++) v -= L[i][k] * L[j][k];
        if (i === j) { if (!(v > 0)) return null; L[i][i] = Math.sqrt(v); } else L[i][j] = v / L[j][j];
      }
    }
    return L;
  }

  /** The draws: a value of each row to a run, by the scheme, from the seed, each row a stream of its own. */
  async function unDraws() {
    const u = state.unc;
    const n = Math.round(Number(u.n));
    if (!(n >= 2 && n <= 2000)) throw new Error('Runs: from 2 to 2000.');
    const seed = Math.round(Number(u.seed));
    if (!Number.isFinite(seed)) throw new Error('The seed is a whole number.');
    const E = await distributionsEngine();
    const letters = 'ABCDEFGHIJKLMNOP';
    const D = u.rows.map((row) => {
      try { return E.makeDistribution(unSpec(row)); } catch (e) { throw new Error(`${swVaryLabel(swVary(row.what))}: ${e.message}`); }
    });
    const us = u.rows.map((row, j) => E.uniforms(u.scheme, n, seed, letters[j]));
    // Drawn together: the uniforms made normal, correlated by the fit's matrix, and made uniform again.
    if (u.useCorr && unCorrApplies() && u.rows.length > 1) {
      const L = cholesky(u.corr.m);
      if (!L) throw new Error('The fit\'s correlations make no correlation matrix: draw the numbers apart.');
      const N = E.makeDistribution({ family: 'normal', params: { mu: 0, sigma: 1 } });
      for (let i = 0; i < n; i++) {
        const z = us.map((w) => N.at(w.u[i], w.uc[i]));
        us.forEach((w, j) => {
          let v = 0;
          for (let k = 0; k <= j; k++) v += L[j][k] * z[k];
          w.u[i] = N.cdf(v);
          w.uc[i] = N.sf(v);
        });
      }
    }
    return Array.from({ length: n }, (_, i) => D.map((d, j) => d.at(us[j].u[i], us[j].uc[i])));
  }

  async function unGo() {
    if (unBusy || state.running) return;
    if (!state.compiled) { setStatus('The model does not compile: there is nothing to run.', 'error'); return; }
    const u = state.unc;
    const vary = u.rows.map((row) => swVary(row.what));
    if (new Set(u.rows.map((r) => r.what)).size < vary.length) { setStatus('The same number is drawn twice: name each once.', 'error'); return; }
    let draws;
    try { draws = await unDraws(); } catch (e) { setStatus(`The draws could not be made: ${e.message}`, 'error'); return; }
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    // The model as it is written runs first, for reference, where the text gives each number.
    const base = vary.map((v) => swCurrent(`${v.kind}:${v.name}`));
    const withBase = base.every((v) => v !== null);
    const tend = solver.tend > 0 ? solver.tend : state.compiled.settings.TEND;
    // Every run read at the same times: evenly over the run, and evenly in the logarithm over its last six decades.
    const times = [...new Set([...Array.from({ length: 101 }, (_, i) => (tend * i) / 100),
      ...Array.from({ length: 81 }, (_, i) => tend * 10 ** (-6 + (6 * i) / 80))].map((x) => Number(x.toPrecision(12))))].sort((a, b) => a - b);
    unBusy = true;
    state.running = true;
    $('rtmRun').disabled = true;
    $('rtmStop').disabled = false;
    $('rtmUnGo').disabled = true;
    setProgress(0);
    const combos = withBase ? [base, ...draws] : draws;
    setStatus(`Running ${combos.length} times…`);
    try {
      const reply = await request({ type: 'sweep', text: state.text, solver, vary, combos, times, cell: u.cell }, (p) => {
        setProgress(p.frac);
        setStatus(`Running ${p.run + 1} of ${p.runs}: ${fmtTime(p.t)} of ${fmtTime(p.tend)}`);
      });
      unResult = { reply, vary, withBase, rows: u.rows.map((r) => ({ ...r })), n: draws.length, scheme: u.scheme, seed: u.seed,
        corr: u.useCorr && unCorrApplies() && u.rows.length > 1 };
      const runs = reply.runs.slice(withBase ? 1 : 0);
      const failed = runs.filter((r) => !r.ok);
      setProgress(null);
      setStatus(`${runs.length - failed.length} of ${runs.length} runs done in ${reply.seconds.toFixed(2)} s`
        + `${failed.length ? `; the first that failed: ${failed[0].error}` : '.'}`, failed.length ? 'warn' : 'ok');
      renderUnShow();
      drawUn();
    } catch (e) {
      setProgress(null);
      setStatus(`The runs could not be made: ${e.message}`, 'error');
    } finally {
      unBusy = false;
      state.running = false;
      $('rtmRun').disabled = false;
      $('rtmStop').disabled = true;
      $('rtmUnGo').disabled = false;
    }
  }

  function renderUnShow() {
    $('rtmUnShowBar').hidden = !unResult;
    if (!unResult) return;
    const u = state.unc;
    const column = unResult.reply.runs.some((r) => r.ok && r.nf > 1);
    if (u.show === 'profile' && !column) u.show = 'time';
    $('rtmUnShow').querySelector('option[value="profile"]').hidden = !column;
    $('rtmUnShow').value = u.show;
    if (!speciesNames().includes(u.key) && !(quantityOf(u.key) && !quantityOf(u.key).of)) u.key = speciesNames()[0] || '';
    $('rtmUnKey').innerHTML = pickerOptions(u.key, false);
    $('rtmUnOf').value = u.of;
    $('rtmUnOfWrap').hidden = u.show === 'time' || u.show === 'profile';
    $('rtmUnLogTWrap').hidden = u.show !== 'time';
    $('rtmUnLogYWrap').hidden = u.show === 'matters' || u.show === 'indices' || (isQuantity(u.key) && quantityOf(u.key).axis === 'index');
  }

  /** The type-7 percentile p (0 to 100) of sorted values. */
  function percentile(sorted, p) {
    if (!sorted.length) return null;
    const h = (sorted.length - 1) * (p / 100);
    const lo = Math.floor(h);
    return lo + 1 < sorted.length ? sorted[lo] + (h - lo) * (sorted[lo + 1] - sorted[lo]) : sorted[lo];
  }

  /** Spearman's rank correlation of two lists: Pearson's of their ranks, ties given the mean of their ranks. */
  function spearman(x, y) {
    const rank = (v) => {
      const idx = v.map((_, i) => i).sort((a, b) => v[a] - v[b]);
      const r = new Array(v.length);
      for (let i = 0; i < idx.length;) {
        let j = i;
        while (j + 1 < idx.length && v[idx[j + 1]] === v[idx[i]]) j++;
        for (let k = i; k <= j; k++) r[idx[k]] = (i + j) / 2;
        i = j + 1;
      }
      return r;
    };
    const rx = rank(x);
    const ry = rank(y);
    const n = x.length;
    const mx = rx.reduce((a, b) => a + b, 0) / n;
    const my = ry.reduce((a, b) => a + b, 0) / n;
    let sxy = 0;
    let sxx = 0;
    let syy = 0;
    for (let i = 0; i < n; i++) { sxy += (rx[i] - mx) * (ry[i] - my); sxx += (rx[i] - mx) ** 2; syy += (ry[i] - my) ** 2; }
    return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : 0;
  }

  const UN_P = [5, 25, 50, 75, 95];

  /*
    Sensitivity indices of one value of the runs, worked out in the page from
    the runs as they are (resources/js/rtm-gsa/indices.js, loaded when first
    needed): each number drawn, and a dummy drawn beside them that no run
    used -- the size chance alone gives an index with this many runs. The
    bootstrap's resamples and the dummy's draws come from the tab's seed.
  */
  const GSA_URL = 'resources/js/rtm-gsa/indices.js?v=20261110b';
  let unIndicesBusy = null;
  async function unIndicesAsk(sig, ok) {
    const res = unResult;
    if (!res || unIndicesBusy) return;
    if (!res.indices) res.indices = new Map();
    const y = ok.map(([, v]) => v);
    if (ok.length < 20) {
      res.indices.set(sig, { error: `${ok.length} runs: sensitivity indices need 20 at the least, and are rough below a few hundred.` });
      drawUn();
      return;
    }
    if (Math.max(...y) === Math.min(...y)) {
      res.indices.set(sig, { error: 'the value is the same in every run: nothing drawn moves it.' });
      drawUn();
      return;
    }
    unIndicesBusy = sig;
    res.indices.set(sig, { busy: true });
    const seed = Number(state.unc.seed) || 1;
    try {
      const I = await import(new URL(GSA_URL, document.baseURI).href);
      // The dummy's draws, a stream of their own apart from the bootstrap's.
      const next = I.seeded(seed + 7919);
      const xs = [...res.vary.map((_, j) => ok.map(([r]) => r.values[j])), ok.map(() => next())];
      const out = await I.indicesOf(xs, y, { boots: 100, seed, pause: async (j, of) => {
        setStatus(`Working out the sensitivity indices: ${j + 1} of ${of} numbers…`);
        await new Promise((r) => setTimeout(r, 0));
      } });
      res.indices.set(sig, out);
      setStatus(`Sensitivity indices worked out from ${ok.length} runs, each with a 95 % interval from ${out.boots} bootstrap resamples.`,
        'ok');
    } catch (e) {
      res.indices.set(sig, { error: `the sensitivity indices could not be worked out: ${e.message}` });
    } finally {
      unIndicesBusy = null;
      if (unResult === res && state.tab === 'uncertainty') drawUn();
    }
  }

  function drawUn() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartUn');
    const empty = $('rtmUnEmpty');
    const note = $('rtmUnNote');
    unTableNow = null;
    if (!unResult) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      note.textContent = '';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const u = state.unc;
    const rp = unResult.reply;
    const base = unResult.withBase && rp.runs[0].ok ? rp.runs[0] : null;
    const runs = rp.runs.slice(unResult.withBase ? 1 : 0).filter((r) => r.ok);
    const key = u.key;
    const q = isQuantity(key) ? quantityOf(key) : null;
    const index = !!(q && q.axis === 'index');
    const logY = $('rtmUnLogY').checked && !index;
    const yTitle = q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : `${key} concentration`;
    const layout = baseLayout();
    layout.hovermode = 'closest';
    const c = themeColors();
    const blue = '#1f77b4';
    const failedNote = rp.runs.length - (unResult.withBase ? 1 : 0) > runs.length
      ? `; ${rp.runs.length - (unResult.withBase ? 1 : 0) - runs.length} failed and are left out` : '';
    const what = `${runs.length} runs, drawn by ${{ lhs: 'Latin hypercube', sobol: 'Sobol', random: 'simple random' }[unResult.scheme]}`
      + `${unResult.corr ? ' with the fit\'s correlations' : ''}${failedNote}`;
    if (u.show === 'time' || u.show === 'profile') {
      const where = u.show === 'time' ? 'cell' : 'end';
      const series = runs.map((r) => runSeries(rp, r, key, where));
      const xs = u.show === 'time' ? Array.from(runs[0].t) : Array.from(runs[0].centres);
      const bands = UN_P.map((p) => xs.map((_, i) => {
        const vals = series.map((s) => s[i]).filter((v) => Number.isFinite(v) && (!logY || v > 0)).sort((a, b) => a - b);
        return percentile(vals, p);
      }));
      const logT = u.show === 'time' && $('rtmUnLogT').checked;
      const keep = xs.map((x) => !logT || x > 0);
      const X = xs.filter((_, i) => keep[i]).map((x) => (u.show === 'time' ? showT(x) : x));
      const B = bands.map((b) => b.filter((_, i) => keep[i]));
      const traces = [
        { type: 'scatter', mode: 'lines', x: X, y: B[0], line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
        { type: 'scatter', mode: 'lines', name: '5 to 95 %', x: X, y: B[4], line: { width: 0 }, fill: 'tonexty',
          fillcolor: 'rgba(31,119,180,0.18)', hovertemplate: '95 %: %{y:.4g}<extra></extra>' },
        { type: 'scatter', mode: 'lines', x: X, y: B[1], line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
        { type: 'scatter', mode: 'lines', name: '25 to 75 %', x: X, y: B[3], line: { width: 0 }, fill: 'tonexty',
          fillcolor: 'rgba(31,119,180,0.35)', hovertemplate: '75 %: %{y:.4g}<extra></extra>' },
        { type: 'scatter', mode: 'lines', name: 'the median', x: X, y: B[2], line: { color: '#ff7f0e', width: 2 },
          hovertemplate: 'median: %{y:.4g}<extra></extra>' },
      ];
      if (base) {
        const y = runSeries(rp, base, key, where).filter((_, i) => keep[i]);
        traces.push({ type: 'scatter', mode: 'lines', name: 'the model as written', x: X, y, line: { color: c.text, width: 1.2, dash: 'dash' } });
      }
      // What <DATA> measured there: at the cell kept, or along the column at the end of the run.
      if (u.show === 'time') {
        for (const d of measured('time', key)) {
          if ((d.tab.cell || 0) !== u.cell || (d.tab.layer || 0) !== 0) continue;
          traces.push({ type: 'scatter', mode: 'markers', name: 'measured', x: d.x.map(showT), y: d.y,
            marker: { size: 8, symbol: 'circle-open', color: c.text, line: { width: 1.6 } } });
        }
      }
      layout.xaxis.type = logT ? 'log' : 'linear';
      layout.xaxis.title = { text: u.show === 'time' ? `time (${shownTime().sym})` : 'distance from the left-hand face (m)', font: { size: 11 } };
      layout.yaxis.type = logY ? 'log' : 'linear';
      layout.yaxis.title = { text: yTitle, font: { size: 11 } };
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      unTableNow = { head: [u.show === 'time' ? `t (${shownTime().sym})` : 'distance (m)', ...UN_P.map((p) => `${labelOf(key)}, ${p} %`),
        ...(base ? [`${labelOf(key)}, the model as written`] : [])], name: `rtm_uncertainty_${u.show}`,
      rows: xs.map((x, i) => [u.show === 'time' ? showT(x) : x, ...bands.map((b) => b[i]), ...(base ? [runSeries(rp, base, key, where)[i]] : [])]) };
      note.textContent = `${what}; ${u.show === 'time' ? `cell ${rp.cell}` : 'the end of each run'}`;
      return;
    }
    // One value of each run: its value at the end at the cell, its largest or its smallest.
    const summary = (r) => {
      const y = runSeries(rp, r, key, 'cell').filter(Number.isFinite);
      if (!y.length) return null;
      return u.of === 'max' ? Math.max(...y) : u.of === 'min' ? Math.min(...y) : y[y.length - 1];
    };
    const vals = runs.map(summary);
    const ok = runs.map((r, i) => [r, vals[i]]).filter(([, v]) => v !== null && Number.isFinite(v));
    const ofText = { end: 'at the end', max: 'its largest', min: 'its smallest' }[u.of];
    const labels = unResult.vary.map(swVaryLabel);
    unTableNow = { head: ['run', ...labels, `${labelOf(key)}, ${ofText} at cell ${rp.cell}`], name: 'rtm_uncertainty_runs',
      rows: ok.map(([r, v], i) => [i + 1, ...r.values, v]) };
    if (u.show === 'spread') {
      const sorted = ok.map(([, v]) => v).sort((a, b) => a - b);
      const useLog = logY && sorted[0] > 0;
      const shown = useLog ? sorted.map(Math.log10) : sorted;
      const marks = [5, 50, 95].map((p) => percentile(sorted, p));
      const traces = [{ type: 'histogram', x: shown, marker: { color: 'rgba(31,119,180,0.6)', line: { color: blue, width: 1 } },
        name: 'the runs', nbinsx: Math.min(40, Math.max(8, Math.round(Math.sqrt(sorted.length) * 2))), hovertemplate: '%{x}: %{y} runs<extra></extra>' }];
      layout.shapes = marks.map((v, i) => ({ type: 'line', xref: 'x', yref: 'paper', x0: useLog ? Math.log10(v) : v, x1: useLog ? Math.log10(v) : v,
        y0: 0, y1: 1, line: { color: blue, width: i === 1 ? 2 : 1, dash: i === 1 ? 'solid' : 'dot' } }));
      if (base) {
        const bv = summary(base);
        if (bv !== null && Number.isFinite(bv) && (!useLog || bv > 0)) {
          layout.shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: useLog ? Math.log10(bv) : bv, x1: useLog ? Math.log10(bv) : bv,
            y0: 0, y1: 1, line: { color: c.text, width: 1.2, dash: 'dash' } });
        }
      }
      layout.xaxis.title = { text: `${useLog ? 'log₁₀ ' : ''}${yTitle}, ${ofText} at cell ${rp.cell}`, font: { size: 11 } };
      layout.yaxis.title = { text: 'runs', font: { size: 11 } };
      layout.bargap = 0.04;
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      note.textContent = `${what}; 5 % ${fit4(marks[0])}, the median ${fit4(marks[1])}, 95 % ${fit4(marks[2])}`
        + `${base ? '; the dashed line the model as written' : ''}`;
      return;
    }
    if (u.show === 'indices') {
      // The sensitivity indices of the value, worked out once for each value asked of these runs.
      const sig = `${key}|${u.of}|${rp.cell}`;
      const got = unResult.indices && unResult.indices.get(sig);
      if (!got || got.busy) {
        if (!got) unIndicesAsk(sig, ok);
        Plotly.purge(plot);
        note.textContent = `${what}; working out the sensitivity indices of ${labelOf(key)}, ${ofText} at cell ${rp.cell}…`;
        return;
      }
      if (got.error) {
        Plotly.purge(plot);
        note.textContent = `${what}; ${got.error}`;
        return;
      }
      const names = [...labels, 'a dummy: drawn, never used'];
      const kinds = [['s1', 'first-order Sobol\' index (EASI)', blue], ['delta', 'Borgonovo\'s δ', '#ff7f0e'],
        ['pawn', 'PAWN, the median KS distance', '#2ca02c']];
      const traces = kinds.map(([k, name, col]) => ({
        type: 'bar', orientation: 'h', name, y: names, x: got.inputs.map((r) => r[k]), marker: { color: col },
        error_x: { type: 'data', symmetric: false, array: got.inputs.map((r) => r[`${k}High`] - r[k]),
          arrayminus: got.inputs.map((r) => r[k] - r[`${k}Low`]), color: c.text, thickness: 1, width: 3 },
        hovertemplate: `%{y}: %{x:.3f}<extra>${esc(name)}</extra>` }));
      const ends = got.inputs.flatMap((r) => [r.s1Low, r.s1High, r.deltaLow, r.deltaHigh, r.pawnLow, r.pawnHigh]).filter(Number.isFinite);
      Plotly.react(plot, traces, {
        ...layout, barmode: 'group', bargap: 0.25, hovermode: 'closest',
        margin: { ...layout.margin, l: Math.min(320, 40 + 7 * Math.max(...names.map((nm) => nm.length))) },
        xaxis: { ...layout.xaxis, range: [Math.min(0, ...ends) - 0.02, Math.max(1, ...ends) + 0.02],
          title: { text: `sensitivity of ${labelOf(key)}, ${ofText}, with 95 % intervals`, font: { size: 11 } } },
        yaxis: { ...layout.yaxis, automargin: true, autorange: 'reversed' } }, PLOT_CONFIG);
      unTableNow = { head: ['the number drawn', 'first-order Sobol\' index (EASI)', 'its 95 % interval from', 'to', 'Borgonovo\'s δ',
        'from', 'to', 'PAWN, the median KS distance', 'from', 'to'], name: 'rtm_uncertainty_indices',
      rows: names.map((nm, j) => {
        const r = got.inputs[j];
        return [nm, r.s1, r.s1Low, r.s1High, r.delta, r.deltaLow, r.deltaHigh, r.pawn, r.pawnLow, r.pawnHigh];
      }),
      extra: [{ name: 'runs', head: unTableNow.head, rows: unTableNow.rows }] };
      const dummy = got.inputs[got.inputs.length - 1];
      note.textContent = `${what}; with ${labelOf(key)}, ${ofText} at cell ${rp.cell}, from ${got.boots} bootstrap resamples: `
        + `${labels.map((l, j) => `${l} S1 ${got.inputs[j].s1.toFixed(3)}, δ ${got.inputs[j].delta.toFixed(3)}`).join('; ')}; `
        + `the dummy, how large chance alone makes them, S1 ${dummy.s1.toFixed(3)}, δ ${dummy.delta.toFixed(3)}, PAWN ${dummy.pawn.toFixed(3)}`;
      return;
    }
    // What matters: Spearman's rank correlation of each number drawn with the value.
    const rho = unResult.vary.map((_, j) => spearman(ok.map(([r]) => r.values[j]), ok.map(([, v]) => v)));
    Plotly.react(plot, [{ type: 'bar', orientation: 'h', x: rho, y: labels, marker: { color: rho.map((v) => (v < 0 ? '#d62728' : blue)) },
      hovertemplate: '%{y}: %{x:.3f}<extra></extra>' }], {
      ...layout, margin: { ...layout.margin, l: Math.min(320, 40 + 7 * Math.max(...labels.map((s) => s.length))) },
      xaxis: { ...layout.xaxis, range: [-1, 1], title: { text: `Spearman's rank correlation with ${labelOf(key)}, ${ofText}`, font: { size: 11 } } },
      yaxis: { ...layout.yaxis, automargin: true } }, PLOT_CONFIG);
    unTableNow = { ...unTableNow, head: [...unTableNow.head], rows: unTableNow.rows };
    note.textContent = `${what}; ${labels.map((l, j) => `${l} ${rho[j].toFixed(3)}`).join(', ')}`;
  }

  /* ---------------------------------------------------------------------
     CSV
     --------------------------------------------------------------------- */
  /**
   * The time chart's series as a table, every stored point: the time, then
   * each key picked (every species when none is) at the cell and layer shown,
   * or what crosses the end shown. Quantities are worked out first.
   */
  async function timeTable() {
    const r = state.result;
    // What is ticked that this model has: a pick outlives the model it was made in.
    const here = state.picked.filter((k) => r.model.species.includes(k) || isQuantity(k));
    const names = here.length ? here : r.model.species;
    // At the cells listed in Cells, each column saying where; or at the one cell Cell chooses, or an end.
    const tc = timeCells(r);
    const face = !tc.several && isFace(state.cell);
    const keys = face ? [] : names.filter((k) => isQuantity(k));
    if (keys.length) await fetchQuantities(keys, tc.at.map((c) => modelCell(c, state.layer)));
    // At a cell the layer shown, at an end what crosses it.
    const rock = state.layer > 0 && r.model.matrix ? ` rock ${state.layer}` : '';
    const whereOf = (c) => (face ? `through the ${state.cell} end`
      : `@ cell ${c}${rock}${tc.several ? ` (${Number(r.model.centres[c].toPrecision(6))} m)` : ''}`);
    const unitOf = (k) => { const q = isQuantity(k) ? quantityOf(k) : null; return q && q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''; };
    /*
      In the unit shown, each concentration's header saying it -- the
      model's own too, where its CONC_UNIT names it; one that has none in
      it -- no formula to weigh, a pressure -- as the model has it, its header
      saying in what: mol/kgw under ACTIVITY, or the CONC_UNIT.
    */
    const u = shownUnit(r);
    const shown = names.map((n) => shownAs(r, n, u));
    // At an end what crosses it, per m2 of the water's cross-section: the unit times m per the time unit.
    const per = face ? ` · m/${timeUnit().symbol}` : '';
    const own = (n) => (unitOf(n) || (concBase(r.model) && !isQuantity(n) ? ` (${concBase(r.model)}${per})` : ''));
    const headOf = (n, j, where) => {
      const sh = shown[j];
      if (!unitSaid(u) || !sh) return `${labelOf(n)}${unitOf(n)} ${where}`;
      if (sh.why) return `${labelOf(n)}${own(n)} ${where}`;
      return `${labelOf(n)}${u.bare ? ` ${u.text}` : ` (${u.text}${per})`} ${where}`;
    };
    // Each key at each cell, in the order picked; on an axis not the model's own -- pore volumes, another unit -- it comes first, then the time.
    const ax = timeAxis(r);
    const at = face ? [state.cell] : tc.at;
    const head = [...(ax.fixed ? [ax.pv ? 'pore volumes' : `t (${ax.sym})`] : []), `t (${timeUnit().symbol})`];
    const cols = [];
    names.forEach((n, j) => {
      const f = shown[j] && shown[j].f ? shown[j].f : 1;
      for (const c of at) {
        head.push(headOf(n, j, whereOf(c)));
        const s = series(n, c);
        cols.push(s && f !== 1 ? s.map((v) => v * f) : s);
      }
    });
    const xr = axisTimes(r, ax);
    const rows = [];
    for (let i = 0; i < r.n; i++) {
      rows.push([...(ax.fixed ? [xr[i]] : []), r.t[i], ...cols.map((c) => (c && Number.isFinite(c[i]) ? c[i] : null))]);
    }
    // In Excel, the breakthrough numbers and every species in numbers on sheets of their own where they are shown.
    const extra = [...(state.btc && btcNow ? [btcNow.half, btcNow.out] : []), ...(state.every && everyNow ? [everyNow] : [])]
      .filter((tb) => tb.rows.length);
    return { head, rows, name: face ? `rtm_${state.cell}_end` : `rtm_cell${at.join('_')}`, ...(extra.length ? { extra } : {}) };
  }

  async function downloadCsv() {
    if (!state.result) { setStatus('Run the model first: there is nothing to save yet.', 'error'); return; }
    const tab = await timeTable();
    saidSaved(await saveBlob(new Blob([csvOf(tab)], { type: 'text/csv' }), `${tab.name}.csv`));
  }

  /** A table as CSV: a header, then a row per point, a blank where there is no value. */
  function csvOf(tab) {
    const cell = (v) => {
      if (v === null || v === undefined) return '';
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    return [tab.head, ...tab.rows].map((row) => row.map(cell).join(',')).join('\n');
  }

  /**
   * What a chart draws, as a table. Lines and points: the x of all of them
   * in order, then each trace's value there. A map, contours or a surface:
   * a row per distance, a column per time.
   */
  function chartTable(plot, name) {
    const data = plot && plot.data ? plot.data : [];
    if (!data.length) return null;
    const grid = data.find((tr) => ['heatmap', 'contour', 'surface'].includes(tr.type));
    if (grid) {
      const title = (grid.colorbar && grid.colorbar.title && grid.colorbar.title.text) || 'value';
      // A map of categories, the redox zones: each by its name.
      const cat = grid.meta && grid.meta.categories;
      return { head: [`distance (m) \\ ${timeAxis().title}: ${title}`, ...grid.x], name,
        rows: grid.y.map((y, j) => [y, ...grid.z[j].map((v) => (v === null || v === undefined ? null : cat ? cat[v] : v))]) };
    }
    const xs = [...new Set(data.flatMap((tr) => Array.from(tr.x || [])))].sort((a, b) => a - b);
    const xTitle = (plot.layout && plot.layout.xaxis && plot.layout.xaxis.title && plot.layout.xaxis.title.text) || 'x';
    const cols = data.map((tr) => {
      const m = new Map();
      Array.from(tr.x || []).forEach((x, i) => m.set(x, tr.y[i]));
      return m;
    });
    // A curve in a unit chosen says it (shownUnit): Ca+2 (mg/kgw).
    return { head: [xTitle, ...data.map((tr) => `${tr.name}${(tr.meta && tr.meta.unitSuffix) || ''}`)], name,
      rows: xs.map((x) => [x, ...cols.map((m) => (m.has(x) ? m.get(x) : null))]) };
  }

  /** The tables of the run on show for the chart in `pane`: the time chart's every point, the others what they draw. */
  async function paneTable(pane) {
    if (pane === 'time') return timeTable();
    if (pane === 'composition') return compTableNow;
    if (pane === 'diagram') return dgTableNow;
    if (pane === 'sweep') return swTableNow;
    if (pane === 'fit') return fitTableNow;
    if (pane === 'uncertainty') return unTableNow;
    const plot = $(pane === 'profile' ? 'rtmChartProfile' : 'rtmChartGradient');
    const what = pane === 'profile' ? (state.profileSpecies === PROFILE_TICKED ? 'ticked' : state.profileSpecies) : state.gradSpecies;
    return chartTable(plot, `rtm_${pane}_${String(what).replace(/[^\w.-]+/g, '_')}`);
  }

  /**
   * Saves what a chart shows: its figure as SVG or PNG, at the size it is
   * drawn, or its numbers as CSV or as an Excel workbook -- the numbers on
   * one sheet, the model text the run was made with on another.
   */
  async function exportPane(pane, as) {
    // A diagram, a sweep, a fit and the uncertainty runs have their own runs: the rest are of the run.
    if (!state.result && ['time', 'profile', 'gradient', 'composition'].includes(pane)) {
      setStatus('Run the model first: there is nothing to save yet.', 'error');
      return;
    }
    const plot = $({ time: 'rtmChartTime', profile: 'rtmChartProfile', gradient: 'rtmChartGradient', composition: 'rtmChartComp',
      diagram: 'rtmChartDg', sweep: 'rtmChartSw', fit: 'rtmChartFit', uncertainty: 'rtmChartUn', phreeqc: 'rtmChartPq',
      inverse: 'rtmChartPqInv', batch: 'rtmChartPqBatch', batchx: 'rtmChartPqBatchX', batchmap: 'rtmChartPqBatchMap' }[pane]);
    if (as === 'txt') {
      if (!compTextNow) { setStatus('List a water first: Show the water, as PHREEQC lists it.', 'error'); return; }
      saidSaved(await saveBlob(new Blob([compTextNow], { type: 'text/plain' }), `${compTableNow.name}.txt`));
      return;
    }
    if (as === 'html') { await saveChartPage(plot, pane); return; }
    if (as === 'svg' || as === 'png') {
      if (!plot || plot.hidden || !plot.data) { setStatus('Draw something first: the chart is empty.', 'error'); return; }
      const box = plot.getBoundingClientRect();
      // Made by Plotly as it would download it, and saved where asked.
      const url = await Plotly.toImage(plot, { format: as,
        width: Math.max(400, Math.round(box.width)), height: Math.max(300, Math.round(box.height)) });
      saidSaved(await saveBlob(await (await fetch(url)).blob(), `${fileStem()}_${pane}.${as}`));
      return;
    }
    const tab = await paneTable(pane);
    if (!tab) { setStatus('Draw something first: the chart is empty.', 'error'); return; }
    if (as === 'csv') { saidSaved(await saveBlob(new Blob([csvOf(tab)], { type: 'text/csv' }), `${tab.name}.csv`)); return; }
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') {
      setStatus('The Excel writer did not load; save as CSV instead.', 'error');
      return;
    }
    const xlsx = new XlsxWriter(`${tab.name}.xlsx`);
    xlsx.writeData(tab.rows.map((row) => row.map((v) => (v === null ? '' : v))), 'run', { header: tab.head });
    for (const more of tab.extra || []) xlsx.writeData(more.rows.map((row) => row.map((v) => (v === null ? '' : v))), more.name, { header: more.head });
    const text = (state.ran && state.ran.text) || state.text;
    xlsx.writeData(text.split('\n').map((ln) => [ln]), 'model', { header: ['the model text the run was made with'] });
    saidSaved(await saveBlob(await xlsx.save(), `${tab.name}.xlsx`));
  }

  /*
    A chart as a page of its own (HTML): the figure as it is drawn, and as
    live -- zoom, pan, hover, a PNG of it -- with the pane's note above it
    and the model text the run was made with under it. plotly.js goes in the
    file: the very build this page runs, read again under the hash it is
    loaded with (fetch's integrity), so that it is that build or nothing,
    and the page opens anywhere without the internet. Where it cannot be
    read -- this page offline, say -- the page links to it as this one does
    and needs the internet to open, and the status line says so. What is the
    model's is escaped: the text as HTML, the figure as JSON with <, > and &
    written as \u escapes, so that no name or comment can end the script it
    is in.
  */
  const CHART_NOTES = { time: 'rtmTimeNote', profile: 'rtmProfileNote', gradient: 'rtmGradNote', composition: 'rtmCompNote',
    diagram: 'rtmDgNote', sweep: 'rtmSwNote', fit: 'rtmFitNote', uncertainty: 'rtmUnNote', phreeqc: 'rtmPqSummary',
    inverse: 'rtmPqInvNote', batch: 'rtmPqBatchNote', batchx: 'rtmPqBatchNote', batchmap: 'rtmPqBatchNote' };
  const CHART_NAMES = { time: 'against time', profile: 'against distance', gradient: 'gradient', composition: 'composition',
    diagram: 'diagram', sweep: 'sweeps', fit: 'fit', uncertainty: 'uncertainty', phreeqc: 'through PHREEQC',
    inverse: 'inverse models through PHREEQC', batch: 'a batch over a table of waters, its spread',
    batchx: 'a batch over a table of waters, against a column', batchmap: 'a batch over a table of waters, its map' };
  // plotly.js as this page loads it, once read: { src, integrity, text }.
  let plotlyRead = null;

  /** plotly.js to put in a page: its text, or where this page loads it from when that cannot be read. */
  async function plotlyForPage() {
    if (plotlyRead) return plotlyRead;
    const el = document.querySelector('script[src*="plotly"]');
    if (!el) return null;
    const linked = { src: el.src, integrity: el.integrity || '', text: null };
    try {
      const res = await fetch(el.src, { integrity: el.integrity || undefined, credentials: 'omit' });
      const text = res.ok ? await res.text() : '';
      // Nothing in it may end the script it goes into.
      if (text && !/<\/script|<!--/i.test(text)) {
        plotlyRead = { ...linked, text };
        return plotlyRead;
      }
    } catch (e) { /* offline, or not the build the hash names: linked instead */ }
    return linked;
  }

  /** JSON to write into a script: typed arrays as arrays, and nothing that HTML reads as markup. */
  const scriptJson = (v) => JSON.stringify(v, (k, x) => (ArrayBuffer.isView(x) ? Array.from(x) : x))
    .replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');

  async function saveChartPage(plot, pane) {
    if (!plot || plot.hidden || !plot.data || !plot.data.length) { setStatus('Draw something first: the chart is empty.', 'error'); return; }
    const lib = await plotlyForPage();
    if (!lib) { setStatus('plotly.js is not on this page: there is nothing to draw a chart with.', 'error'); return; }
    let data;
    let layout;
    try {
      data = scriptJson(plot.data);
      // As wide as the window it is opened in, as high as it is drawn here.
      const { width, height, ...rest } = plot.layout || {};
      layout = scriptJson({ ...rest, autosize: true });
    } catch (e) {
      setStatus(`The chart could not be written as a page: ${e.message}`, 'error');
      return;
    }
    const c = themeColors();
    const tall = Math.max(320, Math.round(plot.getBoundingClientRect().height));
    const noteEl = $(CHART_NOTES[pane]);
    const note = noteEl ? noteEl.textContent.trim() : '';
    const name = `${fileStem()}_${pane}`;
    const title = `${fileStem()}: ${CHART_NAMES[pane] || pane}`;
    // A batch's chart is of PHREEQC's runs over a table, not of the model's run: under it, the input each row was run with.
    const batch = (pane === 'batch' || pane === 'batchx' || pane === 'batchmap') && pq.batchResult;
    const text = batch ? pq.batchResult.text : (state.ran && state.ran.text) || state.text;
    const version = (typeof Plotly !== 'undefined' && Plotly.version) || '';
    const config = scriptJson({ ...PLOT_CONFIG, toImageButtonOptions: { filename: name } });
    const day = new Date().toISOString().slice(0, 10);
    const library = lib.text ? `<script>\n${lib.text}\n</script>`
      : `<script src="${esc(lib.src)}"${lib.integrity ? ` integrity="${esc(lib.integrity)}" crossorigin="anonymous"` : ''}></script>`;
    const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>
  html, body { margin: 0; background: ${esc(c.surface)}; color: ${esc(c.text)}; }
  body { font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1400px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 16px; font-weight: 600; margin: 0 0 4px; }
  p { margin: 0 0 10px; }
  .note { opacity: 0.8; }
  #chart { width: 100%; height: ${tall}px; }
  details { margin-top: 14px; }
  summary { cursor: pointer; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.4 ui-monospace, Menlo, Consolas, monospace; }
  .made { margin-top: 12px; font-size: 12px; opacity: 0.7; }
</style>
</head>
<body>
<main>
<h1>${esc(title)}</h1>
${note ? `<p class="note">${esc(note)}</p>\n` : ''}<div id="chart"></div>
<details><summary>${batch ? 'The PHREEQC input each row was run with' : 'The model text the run was made with'}</summary><pre>${esc(text)}</pre></details>
<p class="made">Saved from rtm.html, kvotab.github.io/rtm.html, on ${day}. Drawn by plotly.js ${esc(version)} (MIT licence)${
  lib.text ? ', which is in this file' : `, which this page loads from ${esc(new URL(lib.src).host)}`}.</p>
</main>
${library}
<script>
Plotly.newPlot('chart', ${data}, ${layout}, ${config});
</script>
</body>
</html>
`;
    const saved = await saveBlob(new Blob([html], { type: 'text/html' }), `${name}.html`);
    if (!saved) return;
    if (lib.text) setStatus(`Saved ${saved.name}: the chart as a page of its own, plotly.js in it, to open in any browser.`, 'ok');
    else {
      setStatus(`Saved ${saved.name}, linking plotly.js from ${new URL(lib.src).host}: it could not be read to go into the file, `
        + 'so the page needs the internet to open.', 'warn');
    }
  }

  /*
    SAVING ASKS WHERE. Save… and every export open the operating system's
    save dialog, the name the file would have had offered, as Kompartment's
    Save… does: a file dropped into the downloads folder under a fixed name
    -- model.rtm, then model (1).rtm -- had to be found and renamed. A page
    may open the dialog only out of a click, which Chrome lets count for five
    seconds; a file slower to make -- a workbook of a long run, an HDF5 file
    of 60 MB -- would be refused it, so where the click is spent the window
    Ready to save says the file is ready, and its Save… is a click of its
    own. Where the browser has no such dialog (Safari, Firefox), or will not
    open it, the file is downloaded as before.
  */
  const SAVE_TYPES = {
    rtm: { description: 'Model text', type: 'text/plain', ext: '.rtm' },
    csv: { description: 'CSV', type: 'text/csv', ext: '.csv' },
    txt: { description: 'Text', type: 'text/plain', ext: '.txt' },
    xlsx: { description: 'Excel workbook', type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', ext: '.xlsx' },
    html: { description: 'Web page', type: 'text/html', ext: '.html' },
    h5: { description: 'HDF5', type: 'application/x-hdf5', ext: '.h5' },
    svg: { description: 'SVG picture', type: 'image/svg+xml', ext: '.svg' },
    png: { description: 'PNG picture', type: 'image/png', ext: '.png' },
  };
  // The window Ready to save, while it is open: what the dialog is to be asked, and the promise it answers.
  let saveReady = null;

  /** The save dialog, as window.showSaveFilePicker opens it -- out of the click, or, where the click is spent, out of the window's own. */
  function savePicker(options) {
    if (!navigator.userActivation || navigator.userActivation.isActive !== false) return window.showSaveFilePicker(options);
    return new Promise((resolve, reject) => {
      saveReady = { options, resolve, reject, asked: false };
      $('rtmSaveReadyName').textContent = options.suggestedName;
      $('rtmSaveReady').showModal();
      $('rtmSaveReadyGo').focus();
    });
  }

  /**
   * A file, asking where it should go, the name offered; downloaded as before
   * where the browser cannot ask. { name, asked } of what was saved, or null:
   * a cancel, which is an answer and is not remarked on, or a write that
   * failed, which is said.
   */
  async function saveBlob(blob, name) {
    const t = SAVE_TYPES[((/\.([A-Za-z0-9]+)$/.exec(name) || [])[1] || '').toLowerCase()];
    if (typeof window.showSaveFilePicker === 'function') {
      let handle = null;
      try {
        handle = await savePicker({ suggestedName: name,
          ...(t ? { types: [{ description: t.description, accept: { [t.type]: [t.ext] } }] } : {}) });
      } catch (e) {
        // A cancel is an answer. Refused rather than cancelled -- a frame of another site may not open it -- the
        // point of pressing Save is a file, so it is downloaded.
        if (e && e.name === 'AbortError') return null;
      }
      if (handle) {
        try {
          const to = await handle.createWritable();
          await to.write(blob);
          await to.close();
          return { name: handle.name, asked: true };
        } catch (e) {
          setStatus(`${name} could not be written: ${e.message}. The folder may be read-only: try again, and pick another place.`,
            'error');
          return null;
        }
      }
    }
    downloadBlob(blob, name);
    return { name, asked: false };
  }

  /** The status line after an export saved where it was asked: where it went. Downloaded, the browser says so. */
  const saidSaved = (saved) => { if (saved && saved.asked) setStatus(`Saved as ${saved.name}.`, 'ok'); };

  function downloadBlob(blob, name) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /* ---------------------------------------------------------------------
     The run as an HDF5 file

     The same two things facsimile.html offers: the file handed straight to
     the Data Browser in another tab, and the same file as a download. The
     tree itself is rtm-hdf5.js.
     --------------------------------------------------------------------- */

  /** Where the browser is: a sibling page, so the handoff is same-origin. */
  const HDF5_BROWSER = 'rb.html';
  /** How long to wait for the tab to say it is listening, and then to answer. */
  const HANDOFF_READY_MS = 45000;
  const HANDOFF_OPEN_MS = 60000;

  /** What to call the file: the example it came from, or just the page. */
  function fileStem() {
    const picked = $('rtmExample') && $('rtmExample').value;
    return (picked ? `rtm_${picked}` : 'rtm').replace(/[^\w.-]+/g, '_');
  }

  /** The run as HDF5 bytes, described by the model that produced it. */
  function buildHdf5() {
    const ran = state.ran || { solver: solverPayload(), text: state.text };
    const picked = $('rtmExample') && $('rtmExample').value;
    const example = picked ? EXAMPLES.find((x) => x.id === picked) : null;
    return RtmHDF5.resultFile(state.result, {
      solver: ran.solver, text: ran.text, cell: state.cell, layer: state.layer,
      title: example ? example.label : 'Reactive transport',
    });
  }

  /**
   * Opens the Data Browser and hands it this run, without a file ever reaching
   * the disk. The other half of the protocol is resources/js/rb-handoff.js.
   *
   * The tab is opened first, before the file exists, and that is not an
   * accident: a pop-up is only allowed out of a user gesture, and building the
   * file takes longer than the click. So the window goes first, and the bytes
   * follow once the far side has said it is listening -- which it repeats every
   * second, so taking a while over the building is safe.
   */
  async function viewInHdf5Browser() {
    if (!state.result) { setStatus('Run the model first: there is nothing to send yet.', 'error'); return; }
    const origin = window.location.origin;
    const win = window.open(`${HDF5_BROWSER}#handoff=${encodeURIComponent(origin)}`, '_blank');
    if (!win) {
      setStatus('The browser blocked the new tab. Allow pop-ups for this page, or use '
        + '“HDF5” beside it and open the file in the Data Browser yourself.', 'error');
      return;
    }

    let ready = false;
    let onReady = null;
    let settle = null;
    const onMessage = (ev) => {
      if (ev.origin !== origin || !ev.data || typeof ev.data !== 'object') return;
      const kind = ev.data.kvot;
      if (kind === 'rb-ready') { ready = true; if (onReady) onReady(); }
      else if (kind === 'rb-opened' && settle) settle({ ok: true, names: ev.data.names || [] });
      else if (kind === 'rb-error' && settle) settle({ ok: false, message: ev.data.message || '' });
    };
    // Listening before the work starts, not after it: a ready ping that arrives
    // while the file is being built has to have somewhere to land.
    window.addEventListener('message', onMessage);

    const name = `${fileStem()}.h5`;
    try {
      setStatus(`Writing ${name}…`);
      await new Promise((r) => setTimeout(r, 0));     // let that reach the screen
      const bytes = buildHdf5();
      setStatus(`Sending ${name} (${(bytes.length / 1048576).toFixed(1)} MB) to the Data Browser…`);
      if (!ready) {
        await new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error('the tab did not answer; it may still be loading')), HANDOFF_READY_MS);
          onReady = () => { clearTimeout(timer); resolve(); };
        });
      }
      // Transferred rather than copied: the file is megabytes, and a structured
      // clone of it would be a second copy on a page already holding the first.
      const buffer = bytes.buffer;
      const answered = new Promise((resolve) => {
        const timer = setTimeout(
          () => resolve({ ok: false, message: 'it did not say whether the file opened' }), HANDOFF_OPEN_MS);
        settle = (r) => { clearTimeout(timer); settle = null; resolve(r); };
      });
      win.postMessage({ kvot: 'rb-open', name, buffer }, origin, [buffer]);
      const answer = await answered;
      if (!answer.ok) throw new Error(answer.message || 'the Data Browser refused the file');
      setStatus(`${name} is open in the Data Browser.`, 'ok');
    } catch (e) {
      setStatus(`The handoff failed: ${e.message}. “HDF5” beside it writes the same file.`, 'error');
    } finally {
      window.removeEventListener('message', onMessage);
    }
  }

  /** The same file, saved where asked. */
  async function downloadHdf5() {
    if (!state.result) { setStatus('Run the model first: there is nothing to save yet.', 'error'); return; }
    const name = `${fileStem()}.h5`;
    let bytes;
    try {
      bytes = buildHdf5();
    } catch (e) {
      setStatus(`The HDF5 file could not be written: ${e.message}`, 'error');
      return;
    }
    const saved = await saveBlob(new Blob([bytes], { type: 'application/x-hdf5' }), name);
    if (saved) setStatus(`${saved.name} written (${(bytes.length / 1048576).toFixed(1)} MB).`, 'ok');
  }

  /* ---------------------------------------------------------------------
     The panel, the tabs and the drag handle
     --------------------------------------------------------------------- */
  function showTab(name) {
    state.tab = name;
    if (name !== 'profile') profileStop();
    if (name !== 'composition') compStop();
    document.querySelectorAll('.rtm-tabs button').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === name);
    });
    document.querySelectorAll('.rtm-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    saveState();
    // A chart drawn while its tab was hidden -- a run that ends, or quantities
    // that arrive, while another tab is open -- was laid out at Plotly's own
    // 700 px, and a legend that wrapped there keeps its place when the chart
    // is resized: on Against time it lay over the x axis's title. A chart not
    // as wide as its box is cleared here and drawn afresh below; one drawn
    // where it is seen keeps its zoom.
    const afresh = typeof Plotly === 'undefined' ? []
      : [...document.querySelectorAll(`.rtm-pane[data-pane="${name}"] .plot`)]
        .filter((p) => !p.hidden && p._fullLayout && Math.abs(p._fullLayout.width - p.clientWidth) > 1);
    afresh.forEach((p) => Plotly.purge(p));
    // Plotly needs telling once its div stops being display:none.
    if (name === 'time') { drawTime(); resize(); }
    // Drawn while hidden, at Plotly's own width, a legend that wrapped there keeps its place when the chart is resized: drawn afresh.
    if (name === 'profile') { if (typeof Plotly !== 'undefined') Plotly.purge($('rtmChartProfile')); drawProfile(); resize(); }
    if (name === 'gradient') { drawGradient(); resize(); }
    if (name === 'composition') { renderComp(); drawComp(); resize(); }
    if (name === 'diagram') { renderDg(); renderDgShow(); drawDg(); resize(); }
    if (name === 'sweep') { renderSw(); renderSwShow(); drawSw(); resize(); }
    if (name === 'fit') { renderFit(); renderFitResult(); drawFit(); resize(); }
    if (name === 'uncertainty') { renderUn(); renderUnShow(); drawUn(); resize(); }
    if (name === 'phreeqc') { pqRenderView(); if (afresh.some((p) => p.id === 'rtmChartPqInv')) pqInvDraw(); resize(); }
    if (name === 'batch') { pqBatchSpread(); pqBatchAgainst(); pqBatchMap(); resize(); }
    if (name === 'jacobian') drawJacobianPattern();
  }

  /*
    Export, on each tab: a menu that is a popover (rtm.html), opened and shut
    by the browser -- its button, a click elsewhere, Escape. Here it is put
    under its button, right edges together, or above it where the window has
    no room below; the first format takes the focus and the arrow keys move
    through the rest; a format chosen shuts it, and so does the page
    scrolling under it, which would leave it behind.
  */
  function setupMenus() {
    const menus = [...document.querySelectorAll('.rtm-menu[popover]')];
    if (!menus.length || typeof HTMLElement.prototype.showPopover !== 'function') return;
    const items = (menu) => [...menu.querySelectorAll('.rtm-menu-item')].filter((b) => !b.hidden && !b.disabled);
    for (const menu of menus) {
      const button = document.querySelector(`[popovertarget="${menu.id}"]`);
      menu.addEventListener('beforetoggle', (ev) => {
        if (ev.newState !== 'open' || !button) return;
        const r = button.getBoundingClientRect();
        menu.style.top = `${Math.round(r.bottom + 4)}px`;
        menu.style.right = `${Math.max(4, Math.round(document.documentElement.clientWidth - r.right))}px`;
      });
      menu.addEventListener('toggle', (ev) => {
        if (ev.newState !== 'open' || !button) return;
        const m = menu.getBoundingClientRect();
        if (m.bottom > window.innerHeight - 4) {
          menu.style.top = `${Math.max(4, Math.round(button.getBoundingClientRect().top - 4 - m.height))}px`;
        }
        const first = items(menu)[0];
        if (first) first.focus({ preventScroll: true });
      });
      menu.addEventListener('click', (ev) => { if (ev.target.closest('.rtm-menu-item')) menu.hidePopover(); });
      menu.addEventListener('keydown', (ev) => {
        const list = items(menu);
        const at = list.indexOf(document.activeElement);
        const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: list.length - 1 }[ev.key];
        if (to === undefined || !list.length) return;
        ev.preventDefault();
        list[(to + list.length) % list.length].focus();
      });
    }
    document.addEventListener('scroll', (ev) => {
      for (const menu of menus) {
        if (menu.matches(':popover-open') && !menu.contains(ev.target)) menu.hidePopover();
      }
    }, true);
    // A press anywhere but on the menu or its button shuts it. The browser does
    // that itself, except on a chart: Plotly lays a cover over the page on the
    // press, the release lands on the cover, and the menu stayed open.
    document.addEventListener('pointerdown', (ev) => {
      for (const menu of menus) {
        if (!menu.matches(':popover-open') || menu.contains(ev.target)) continue;
        const button = document.querySelector(`[popovertarget="${menu.id}"]`);
        if (!button || !button.contains(ev.target)) menu.hidePopover();
      }
    }, true);
  }

  function resize() {
    if (typeof Plotly === 'undefined') return;
    ['rtmChartTime', 'rtmChartProfile', 'rtmChartGradient', 'rtmChartComp', 'rtmChartDg', 'rtmChartSw', 'rtmChartFit', 'rtmChartUn',
      'rtmChartPq', 'rtmChartPqBatch', 'rtmChartPqBatchX', 'rtmChartPqBatchMap']
      .forEach((id) => {
      const el = $(id);
      if (el && !el.hidden) Plotly.Plots.resize(el);
    });
  }

  function initSideResize() {
    const handle = $('rtmResize');
    const root = document.querySelector('.rtm');
    if (state.sideWidth) root.style.setProperty('--rtm-side-width', `${state.sideWidth}px`);
    let dragging = false;
    handle.addEventListener('pointerdown', (ev) => {
      dragging = true;
      handle.classList.add('active');
      // A pointer of the page's own making, as a test's, has nothing to capture.
      try { handle.setPointerCapture(ev.pointerId); } catch (e) { /* moves still reach the handle */ }
    });
    handle.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      const left = root.getBoundingClientRect().left;
      const w = Math.max(260, Math.min(640, ev.clientX - left));
      state.sideWidth = Math.round(w);
      root.style.setProperty('--rtm-side-width', `${state.sideWidth}px`);
      resize();
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('active');
      saveState();
      resize();
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    // A double click gives the panel its own width back. Bound here: the page's
    // actions are delegated for click, change, input and keys, not dblclick.
    handle.addEventListener('dblclick', resetWidth);
  }

  function resetWidth() {
    state.sideWidth = DEFAULT_WIDTH;
    document.querySelector('.rtm').style.setProperty('--rtm-side-width', `${DEFAULT_WIDTH}px`);
    saveState();
    resize();
  }

  /*
    THE RUN'S AREA, Run and the status under it, as tall as its top edge is
    dragged upwards -- the status taking the height, so that a long report
    is read without scrolling -- from as tall as its buttons and status need
    to 120 px short of the panel; and back by dragging it down, a double
    click on the edge, or the arrow keys with the edge in focus. The height is
    kept for the next visit, and the panel's own height bounds it as the
    window changes (rtm.css).
  */
  const FOOT_STEP = 18;
  const FOOT_ROOM = 120;

  function setFootHeight(h) {
    const foot = $('rtmSideFoot');
    state.footHeight = Number.isFinite(h) && h > 0 ? Math.round(h) : null;
    foot.classList.toggle('sized', state.footHeight !== null);
    foot.style.height = state.footHeight !== null ? `${state.footHeight}px` : '';
    $('rtmFootResize').setAttribute('aria-valuenow', String(Math.round(foot.getBoundingClientRect().height)));
  }

  /** As tall as the area's buttons and status need, and as tall as the panel lets it be. */
  function footBounds() {
    const foot = $('rtmSideFoot');
    const was = foot.style.height;
    const sized = foot.classList.contains('sized');
    foot.classList.remove('sized');
    foot.style.height = '';
    const min = Math.ceil(foot.getBoundingClientRect().height);
    foot.classList.toggle('sized', sized);
    foot.style.height = was;
    return { min, max: Math.max(min, Math.floor($('rtmSide').getBoundingClientRect().height) - FOOT_ROOM) };
  }

  /** To h, between the bounds: at the least, the area as its contents make it. */
  function footTo(h, bounds) {
    const b = bounds || footBounds();
    const to = Math.max(b.min, Math.min(b.max, h));
    setFootHeight(to > b.min ? to : null);
  }

  function initFootResize() {
    const handle = $('rtmFootResize');
    const foot = $('rtmSideFoot');
    if (state.footHeight) setFootHeight(state.footHeight);
    let drag = null;
    handle.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      drag = { y: ev.clientY, h: foot.getBoundingClientRect().height, bounds: footBounds() };
      handle.classList.add('active');
      // A pointer of the page's own making, as a test's, has nothing to capture.
      try { handle.setPointerCapture(ev.pointerId); } catch (e) { /* moves still reach the handle */ }
      ev.preventDefault();
    });
    handle.addEventListener('pointermove', (ev) => {
      if (drag) footTo(drag.h + drag.y - ev.clientY, drag.bounds);
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      handle.classList.remove('active');
      saveState();
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('dblclick', () => { setFootHeight(null); saveState(); });
    handle.addEventListener('keydown', (ev) => {
      const by = { ArrowUp: FOOT_STEP, ArrowDown: -FOOT_STEP }[ev.key];
      if (!by) return;
      ev.preventDefault();
      footTo(foot.getBoundingClientRect().height + by);
      saveState();
    });
  }

  function initSections() {
    document.querySelectorAll('details.rtm-sec').forEach((sec) => {
      if (Object.prototype.hasOwnProperty.call(state.sections, sec.id)) sec.open = !!state.sections[sec.id];
      sec.addEventListener('toggle', () => { state.sections[sec.id] = sec.open; saveState(); });
    });
  }

  const ADVANCED_KEY = 'sec-solver-advanced';
  function showAdvanced(open) {
    $('rtmAdvanced').hidden = !open;
    $('rtmMore').textContent = open ? 'Hide advanced settings' : 'Advanced settings';
    $('rtmMore').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  /* ---------------------------------------------------------------------
     Reading the controls
     --------------------------------------------------------------------- */
  function readSolverControls() {
    const s = state.solver;
    s.method = $('rtmMethod').value;
    s.bdf = $('rtmBdf').checked;
    s.tend = $('rtmTend').value.trim();
    s.rtol = $('rtmRtol').value.trim();
    s.atol = $('rtmAtol').value.trim();
    s.matrix = $('rtmMatrix').value;
    s.norm = $('rtmNorm').value;
    s.normControl = $('rtmNormControl').checked;
    s.maxOrder = parseInt($('rtmMaxOrder').value, 10) || 5;
    s.minOrder = parseInt($('rtmMinOrder').value, 10) || 1;
    s.hmax = $('rtmHmax').value.trim();
    s.h0 = $('rtmH0').value.trim();
    s.jacobianMode = $('rtmJacobian').value;
    s.kappa = $('rtmKappa').value.trim();
    s.maxJacAge = $('rtmJacAge').value.trim();
    s.belowTolRun = $('rtmBelowTol').value.trim();
    s.stagnationTol = $('rtmStagnation').value.trim();
    s.maxSteps = $('rtmMaxSteps').value.trim();
    s.maxPoints = $('rtmMaxPoints').value.trim();
    s.nonNegative = $('rtmNonNeg').checked;
    s.autoAtol = $('rtmAutoAtol').checked;
    s.smoothEst = $('rtmSmoothEst').checked;
  }

  function writeSolverControls() {
    const s = state.solver;
    const menu = $('rtmMethod');
    // BDF and QBDF were entries of their own, and are now the BDF formulas
    // switch on the NDF and on QNDF: a visit that had one chosen gets that
    // method with the switch on, which is the same run.
    if (s.method === 'bdf') { s.method = 'ndf'; s.bdf = true; }
    if (s.method === 'julia_qbdf') { s.method = 'julia_qndf'; s.bdf = true; }
    if (!Array.prototype.some.call(menu.options, (o) => o.value === s.method)) s.method = 'ndf';
    menu.value = s.method;
    $('rtmBdf').checked = !!s.bdf;
    $('rtmTend').value = s.tend;
    $('rtmRtol').value = s.rtol;
    $('rtmAtol').value = s.atol;
    $('rtmMatrix').value = s.matrix;
    $('rtmNorm').value = s.norm;
    $('rtmNormControl').checked = !!s.normControl;
    $('rtmMaxOrder').value = String(s.maxOrder ?? 5);
    $('rtmMinOrder').value = String(s.minOrder ?? 1);
    $('rtmHmax').value = s.hmax ?? '0';
    $('rtmH0').value = s.h0 ?? '0';
    $('rtmJacobian').value = s.jacobianMode === 'numeric' ? 'numeric' : 'analytic';
    $('rtmKappa').value = s.kappa ?? '1e-3';
    $('rtmJacAge').value = s.maxJacAge ?? '20';
    $('rtmBelowTol').value = s.belowTolRun ?? '5';
    $('rtmStagnation').value = s.stagnationTol ?? '0.5';
    $('rtmMaxSteps').value = s.maxSteps;
    $('rtmMaxPoints').value = s.maxPoints;
    $('rtmNonNeg').checked = !!s.nonNegative;
    $('rtmAutoAtol').checked = !!s.autoAtol;
    $('rtmSmoothEst').checked = s.smoothEst !== false;
  }

  /**
   * Which of the settings `method` reads: facsimile.html's declarations, beside
   * the code that hands them over -- FacsimileODE.options for the solver core's
   * own methods, FacsimileOdeJulia.options for the ported ones. The two that
   * are properties of facsimile's model language, per-species tolerances and
   * reading negatives as zero, have no row here and so are never shown.
   */
  function optionsFor(method) {
    if (typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method)) return FacsimileOdeJulia.options(method) || [];
    return FacsimileODE.options(method) || [];
  }

  /** Settings `method` reads, but not as the NDF does, with what it does instead. */
  function notesFor(method) {
    if (typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method)) return FacsimileOdeJulia.notes(method) || {};
    return FacsimileODE.notes(method) || {};
  }

  /** Whether `method` has the BDF formulas switch: the NDF, Auto through it, and QNDF. */
  function readsBdf(method) {
    return optionsFor(method).includes('bdf');
  }

  /** What the reader should see a setting called, when told it is not used: facsimile's words. */
  const OPTION_NAMES = {
    bdf: 'the BDF switch',
    rtol: 'the relative tolerance',
    atol: 'the absolute tolerance',
    norm: 'the error norm',
    normControl: 'norm control',
    maxOrder: 'the maximum order',
    minOrder: 'the minimum order',
    hmax: 'the maximum step',
    h0: 'the first step',
    matrix: 'the choice of iteration matrix',
    jacobian: 'the choice of Jacobian',
    kappa: 'the Newton tolerance',
    maxJacAge: 'how long a Jacobian is reused',
    belowTolRun: 'accepting failing steps at the floor',
    maxSteps: 'the step budget',
    stagnationTol: 'the stall tolerance',
    autoAtol: 'letting the absolute tolerance follow the solution',
    smoothEst: 'smoothing the error estimate',
    nonNegative: 'keeping species non-negative',
  };

  /** "a", "a and b", "a, b and c". */
  function listOf(items) {
    if (items.length === 1) return items[0];
    return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
  }

  /**
   * Show only the settings the chosen method reads, and name the rest, as
   * facsimile.html does: a knob that does nothing is worse than a missing one,
   * because nothing tells the reader which it is. The ported methods declare
   * theirs in facsimile-ode-julia.js, beside the code that passes them on.
   */
  function updateSolverOptions() {
    const method = $('rtmMethod').value;
    const allowed = optionsFor(method);
    const partial = notesFor(method);
    const set = new Set(allowed);
    const dropped = [];
    document.querySelectorAll('#sec-solver [data-solver-opt]').forEach((el) => {
      const key = el.dataset.solverOpt;
      const off = !set.has(key);
      el.hidden = off;
      if (off && OPTION_NAMES[key]) dropped.push(OPTION_NAMES[key]);
    });
    const label = methodLabel();
    const lines = [];
    if (dropped.length) {
      lines.push(`${label} does not read ${listOf(dropped)}, so ${
        dropped.length === 1 ? 'it is' : 'they are'} not shown.`);
    }
    for (const key of Object.keys(partial)) {
      if (set.has(key) && OPTION_NAMES[key]) lines.push(`${label} honours ${OPTION_NAMES[key]} ${partial[key]}.`);
    }
    const note = $('rtmSolverNote');
    note.hidden = !lines.length;
    note.textContent = lines.join(' ');
  }

  /* ---------------------------------------------------------------------
     The (i) beside each setting, section heading and tab toolbar

     What each setting's hover text used to say, and more: what it is, what
     its choices do, the default and the limits as this file and the solvers
     have them, and which methods read it. kvot-info.js draws the (i) into the
     slots of rtm.html and opens the panel. A topic that is a function is
     called each time its panel opens, or is refreshed, so it can mark the
     current choice and read the model as compiled; infoRefresh() is called
     wherever those change. Inline markup is `code` and **bold**, nothing else.
     --------------------------------------------------------------------- */
  const infoRefresh = () => { if (typeof KvotInfo !== 'undefined') KvotInfo.refresh(); };
  const more = (label, id) => ({ label, id });
  const mb = (bytes) => `${(bytes / 1048576).toFixed(bytes < 10 * 1048576 ? 1 : 0)} MB`;

  /** "a, b and c", or the first `max` of them and how many more. */
  function someOf(names, max = 10) {
    return names.length <= max ? listOf(names) : `${names.slice(0, max).join(', ')} and ${names.length - max} more`;
  }

  /**
   * Which of the methods on the menu read the setting `key`: from the same
   * lists updateSolverOptions hides the rows by, so the two cannot disagree.
   */
  function readers(key) {
    const menu = Array.from($('rtmMethod').options);
    const ids = menu.map((o) => o.value);
    const reads = (id) => optionsFor(id).includes(key);
    // The menu's own names, without where each came from.
    const name = (id) => menu.find((o) => o.value === id).textContent.replace(/\s*\(.*$/, '').trim();
    const yes = ids.filter(reads).map(name);
    const no = ids.filter((id) => !reads(id)).map(name);
    if (!no.length) return 'every method';
    if (!yes.length) return 'none of the methods';
    return no.length <= 2 && yes.length > no.length ? `every method but ${listOf(no)}` : listOf(yes);
  }

  /** How long a run would go: the panel's time, or the TEND of the text. */
  function runTend() {
    const typed = String(state.solver.tend ?? '').trim();
    if (typed && Number(typed) > 0) return Number(typed);
    return state.compiled ? state.compiled.settings.TEND : null;
  }

  // A chart saved as a page, the same on every chart's (i).
  const SAVE_HTML = '**HTML**: the chart as a page of its own, as live as it is here — zoom, pan, hover — with the note above it and the model text under it, plotly.js in the file, so that it opens in any browser without the internet.';
  /** A tab's Export menu in its (i): what each of its formats saves; after, where the menu waits for a chart. */
  const exportSection = (list, after) => ({
    heading: 'Export',
    text: after ? 'The menu at the right end of the bar over the chart, once there is a chart: a format each.'
      : 'The menu at the right end of the bar: a format each.',
    list,
  });

  const TOPICS = {
    'sec:model': () => {
      const m = state.compiled;
      const warned = m ? m.warnings.length : 0;
      return {
        kicker: 'Section', title: 'Model',
        lead: 'What the model is, in its own words, and what the page solves, read from the text on the Model tab. Nothing here is set in the panel: change the text, and this follows.',
        facts: [
          ['Compiles', '0.4 s after the last keystroke, or on Apply'],
          ['Warnings', m ? (warned ? `${warned}, listed under the text on the Model tab` : 'none')
            : (state.compileError ? 'the text does not compile; the status line says why' : 'not compiled yet')],
        ],
        sections: [{
          heading: 'Its own words',
          list: [
            'The comment the text begins with, before anything else in it: its lines run together into paragraphs, a line of only `#` between them, and a line indented further than the rest — a table of reactions, a formula — keeps its line. A rule of `=` or `-` alone is left out. Nothing is shown where the text begins with no comment.',
            'Its first line with words, written `##` — as MATLAB’s `%%` starts a cell — is its title, in bold: `## Zinc on ferrihydrite`.',
            'A long one, more than 300 characters, is folded after its first paragraph — after the first sentences of a first paragraph that is long itself — and **More** opens the rest, **Less** folds it again.',
          ],
        }, {
          heading: 'What is solved, a sentence at a time',
          list: [
            'A batch, one well-mixed water, or a column: how many cells, over what length and how laid out (`CELLS`, `LENGTH`, `GRID` with its `GRID_RATIO` or `GRID_POWER`, a first cell pinned by `SURFACE_LAYER`); and for how long it runs, `TEND` in the model’s time unit.',
            'How many species, and how many reactions with a rate law: `<SPECIES>` and `<REACTIONS>`.',
            'With a rock matrix: how many layers behind each cell, `matched` or `reference`, to `MATRIX_DEPTH`; the first layer, why it is that thick and how fast the rest grow; the `MATRIX_POROSITY`, the wall area per m³ of flowing water, and the species that have a `De=` and so enter the rock.',
            'What moves: diffusion (Nernst-Planck diffusion under `DIFFUSION = nernst-planck`, down the activities under `DIFFUSION_GRADIENT = activity`), advection at the `VELOCITY` with the travel time it makes (limited advection under `ADVECTION_SCHEME = limited`) and the Peclet number; or nothing.',
            'The two ends, `LEFT` and `RIGHT`, with `cauchy` and `outflow` read as the `robin` and `free` they mean, and how many cells stand for the column past a `semi-infinite` end.',
            'The relations of `<EQUILIBRIUM>` and the totals they conserve; whether `EQUILIBRATE` puts the starting water on them, and holds them exactly at every step; whether they hold between activities, by which `ACTIVITY` and at what temperature, or between concentrations; exchangers, surfaces, the electron, a gas phase and solid solutions.',
            'The temperature, where it goes with the cell or the time, and the log K that follow it.',
            'Parameters and tables by name; the tables a rate law reads at the clock, and how many corners of theirs the run is started again at; a species held in some cells only.',
            '`A mass matrix is in force`: a species has an `R=`, or a rock matrix gives it a capacity.',
            'How many equations — the species times the cells, the rock layers counted — and the non-zeros of their Jacobian.',
          ],
        }],
        more: more('<SETTINGS>', 'help-settings'),
      };
    },

    'sec:solver': () => ({
      kicker: 'Section', title: 'Solver',
      lead: 'How the equations are integrated: which method, for how long and how accurately. The same settings, by the same names and in the same order, as on the canister radiolysis page, which runs the same solvers.',
      facts: [
        ['Method', methodLabel()],
        ['Runs on', workerKind === 'inline' ? 'this page, which it holds until the run ends' : 'a background worker'],
        ['Kept', 'in this browser, between visits'],
      ],
      sections: [
        { text: 'Only the settings the chosen method reads are shown. The note at the foot of Advanced settings names the ones it passes over, and says where a method reads one differently from the NDF.' },
        { text: 'The defaults are this page’s own, set for its reaction networks: among them a tighter relative tolerance than the canister radiolysis page’s, and a stalled Newton correction taken (the stall tolerance).' },
        { text: 'A change applies to the next run. A run already going keeps what it was given, and so does the HDF5 file written from it.' },
      ],
      more: more('Choosing a solver', 'help-solver'),
    }),

    'set:method': () => {
      const cur = $('rtmMethod').value;
      return {
        kicker: 'Solver', title: 'Method',
        lead: 'Which integrator solves the model: the same methods Kompartment and the canister radiolysis page offer. NDF is the page’s own and the right first choice; Auto chooses for itself as the run goes. The Julia ports are ported from DifferentialEquations.jl and run here in the page, on the same analytic Jacobian; nothing is downloaded.',
        sections: [{
          choices: [
            ['NDF', 'The numerical differentiation formulas of Shampine and Reichelt, as in MATLAB’s ode15s: variable order 1 to 5, on the sparse Jacobian. With **BDF formulas** under Advanced settings it runs as the plain BDF.', cur === 'ndf'],
            ['Auto', 'An explicit start (Tsit5, or Vern7 below a relative tolerance of 1e-5) at a tenth of the tolerances, watched every step for stiffness as DifferentialEquations.jl’s default watches it; once it is found, the NDF takes the rest of the run. A model that never turns stiff stays explicit, and costs less than on the NDF; one that does costs about what the NDF does.', cur === 'auto'],
            ['Rosenbrock 2-3', 'Kompartment’s Rosenbrock (2,3): one Jacobian and one factorisation a step, no Newton iteration, second order, and steady through a discontinuity. Several times the NDF’s steps on the examples here.', cur === 'ros23'],
            ['Dormand–Prince 4-5', 'Kompartment’s explicit (4,5) pair: no Jacobian, no matrix. Cheap on a smooth model that is not stiff; on a stiff one it says so and stops.', cur === 'dp45'],
            ['DefaultODEAlgorithm', 'DifferentialEquations.jl’s default as it is: Tsit5 or Vern7 until the run turns stiff, then Rosenbrock23 up to 50 equations (Rodas5P below a relative tolerance of 1e-6), FBDF up to 500 and FBDF by GMRES above, and back again. For comparing with Julia: on a large column it is many times Auto’s time.', cur === 'julia_auto'],
            ['FBDF', 'Fixed-leading-coefficient BDF, variable order. It reuses one factorisation over many steps, which on a system of hundreds of equations is most of the cost: the one to try on a large column, and first when NDF will not get through.', cur === 'julia_fbdf'],
            ['FBDF by GMRES', 'FBDF with its Newton iterations solved by GMRES instead of a factorised matrix: products J·v by differencing the model, nothing formed. What DifferentialEquations.jl’s default takes above 500 equations; where the Jacobian is known, as here, the factorising FBDF is usually the faster.', cur === 'julia_fbdf_krylov'],
            ['QNDF', 'The same formulas as NDF, with the same κ, written by other people: the most direct check of the built-in solver. With **BDF formulas** it is QBDF.', cur === 'julia_qndf'],
            ['KenCarp4', 'A fourth-order diagonally implicit Runge–Kutta method (ESDIRK), L-stable. A middle course, cheap at moderate tolerances.', cur === 'julia_kencarp4'],
            ['RadauIIA5', 'Fully implicit, fifth order, L-stable: the most accurate per step and the least troubled by stiffness, the one to believe when two others disagree. It factorises its complex half densely, which is slow past a few thousand equations.', cur === 'julia_radau5'],
            ['Rodas5P', 'A Rosenbrock method, fifth order, with no Newton iteration at all, so nothing to fail to converge. The one to try when a run will not get past something.', cur === 'julia_rodas5p'],
            ['Rosenbrock23', 'The method of Rosenbrock 2-3, as DifferentialEquations.jl runs it: its step control, error norm and starting step.', cur === 'julia_rosenbrock23'],
            ['TRBDF2', 'Second order, L-stable, fast at loose tolerances on smooth problems. On sharp transients at a tight tolerance it can be far out and still report success.', cur === 'julia_trbdf2'],
            ['Tsit5', 'Tsitouras’s explicit pair of order 5(4), SciML’s first choice for a non-stiff problem and where Auto starts. No Jacobian; on a stiff model its step is held to the edge of its stability, and it grinds.', cur === 'julia_tsit5'],
            ['Vern7', 'Verner’s explicit pair of order 7(6), for tight tolerances on a non-stiff problem: fewer steps than Tsit5 below a relative tolerance of about 1e-6.', cur === 'julia_vern7'],
          ],
        }, {
          heading: 'Keep in mind',
          text: 'The Julia ports keep a species non-negative by projecting each step back and nothing more, and do not read the stall tolerance. An explicit method -- Dormand–Prince, Tsit5, Vern7 -- on a stiff model is a run of many steps that ends in a message; Auto finds that out for itself. The canister radiolysis page’s Help describes them at more length.',
        }],
        more: more('Choosing a solver', 'help-solver'),
      };
    },

    'set:tend': () => {
      const u = timeUnit();
      const m = state.compiled;
      const tend = m ? m.settings.TEND : null;
      const said = tend == null ? null
        : `${tend} ${u.symbol}${fmtTime(tend).endsWith(` ${u.symbol}`) ? '' : ` (${fmtTime(tend)})`}`;
      return {
        kicker: 'Solver', title: 'Simulated time',
        lead: `How long to run, in the model’s own time unit, ${u.name}s, or with a unit of its own after the number — \`1890 days\`, \`5 a\` — put into the model’s. Blank runs to the TEND the model text gives.`,
        facts: [['TEND', said], ['Unless the text gives one', `1 ${u.symbol}`], ['Allowed', 'a number above 0, or blank']],
        sections: [
          { text: 'A plain number: the box takes no unit, because the model has one. `TIME_UNIT` in the text converts nothing; it says which unit every rate constant, diffusivity and velocity is already written in, so 10 here is ten of those.' },
          { text: 'The Times box on Against distance does take a unit, `500 a` or `30 d`, and converts it into the model’s.' },
        ],
        more: more('The time unit', 'help-time-unit'),
      };
    },

    'set:rtol': () => ({
      kicker: 'Solver', title: 'Relative tolerance',
      lead: 'The error a step may make, as a fraction of each quantity’s own size: 1e-6 is about six significant digits. Tighter is slower and more accurate.',
      facts: [['Default', SOLVER_DEFAULTS.rtol], ['Allowed', 'above 0 and below 1'], ['Read by', readers('rtol')]],
      sections: [
        { text: 'It holds for every species in every cell alike. Near zero, where a fraction of the value is no error at all, the absolute tolerance takes over.' },
        { heading: 'Keep in mind', text: 'The way to tell whether an answer has converged is to run it again at a tenth of this: what moves was not settled. The stall tolerance is a share of this one.' },
      ],
    }),

    'set:atol': () => ({
      kicker: 'Solver', title: 'Absolute tolerance',
      lead: 'The error allowed on a quantity near zero, in the units the model’s concentrations are written in. Below it a species is not controlled, so set it below the smallest amount that matters.',
      facts: [['Default', SOLVER_DEFAULTS.atol], ['Allowed', '0 or more'], ['Read by', readers('atol')]],
      sections: [
        { text: 'Each species in each cell may be out by about the larger of this and rtol times its value. One number serves every species: the canister radiolysis page’s tolerances per species are not here.' },
        { heading: 'Keep in mind', text: 'A species that matters at 1e-12 is carried along, but not resolved, under an atol of 1e-10: its error is never looked at. **Absolute tolerance follows the solution** raises this as the run goes.' },
      ],
    }),

    'set:bdf': () => ({
      kicker: 'Solver', title: 'BDF formulas',
      lead: 'Runs the plain backward differentiation formulas: the NDF with every κ set to zero. On QNDF it gives QBDF.',
      facts: [['Default', SOLVER_DEFAULTS.bdf ? 'on' : 'off'], ['κ, orders 1 to 5', '−0.185, −1/9, −0.0823, −0.0415, 0'], ['Read by', readers('bdf')]],
      sections: [
        { text: 'κ adds a multiple of the predictor’s miss to each formula, which buys a smaller error constant for a slight loss of stability; at order 5 it is zero already. The BDFs therefore usually take a few more steps for the same answer. Switch it on to see what those terms are worth on a model, or to match a result someone else worked out with BDF.' },
        { heading: 'Keep in mind', text: 'This κ is a coefficient of the formulas. The Newton tolerance, which DifferentialEquations.jl also calls κ, is another thing.' },
      ],
      more: more('Choosing a solver', 'help-solver'),
    }),

    'set:norm': () => {
      const cur = $('rtmNorm').value;
      const n = state.compiled ? state.compiled.states : 0;
      return {
        kicker: 'Solver', title: 'Error norm',
        lead: 'How the errors of all the components are combined into the one number a step is accepted or refused on.',
        facts: [['Default', SOLVER_DEFAULTS.norm], ['Read by', readers('norm')]],
        sections: [{
          choices: [
            ['max', 'The worst-resolved species in the worst cell decides. The stricter of the two.', cur === 'max'],
            ['rms', n > 1
              ? `The root mean square over every species in every cell, as in CVODE. Here that is ${n} numbers, so one component badly out counts 1/${Math.round(Math.sqrt(n))} as much as it would under max.`
              : 'The root mean square over every species in every cell, as in CVODE. On a long column one component badly out counts for little.', cur === 'rms'],
          ],
        }],
      };
    },

    'set:maxOrder': () => ({
      kicker: 'Solver', title: 'Maximum order',
      lead: 'The highest order the variable-order formulas may reach. Lower is steadier through a discontinuity and slower on a smooth stretch.',
      facts: [['Default', String(SOLVER_DEFAULTS.maxOrder)], ['Allowed', '1 to 5'], ['Read by', readers('maxOrder')]],
      sections: [{ text: 'Orders 1 and 2 are A-stable. From 3 to 5 the formulas are stable only in a wedge about the negative real axis, narrower as the order rises, so a model whose Jacobian has stiff eigenvalues far off that axis, a fast oscillation that is damped, is safer with a maximum of 2.' }],
    }),

    'set:minOrder': () => ({
      kicker: 'Solver', title: 'Minimum order',
      lead: 'The lowest order the variable-order Julia ports may drop to. Pinned to the maximum, it holds the order fixed.',
      facts: [['Default', String(SOLVER_DEFAULTS.minOrder)], ['Allowed', '1 to 5; above the maximum it is the maximum'], ['Read by', readers('minOrder')]],
      sections: [{ text: 'A fixed order is for comparing with a code that uses one, or for seeing what the changes of order are doing. The NDF has no floor to set: it starts at order 1 and chooses its own.' }],
    }),

    'set:hmax': () => {
      const u = timeUnit();
      const tend = runTend();
      return {
        kicker: 'Solver', title: 'Maximum step',
        lead: `The longest step the solver may take, in ${u.name}s. Set it where the model changes faster than its solution shows, and the solver steps over the change.`,
        facts: [
          ['Default', SOLVER_DEFAULTS.hmax],
          ['0, where the model gives MAX_STEP', 'that, in its time unit'],
          ['0, for NDF and the two one-step methods', tend ? `a tenth of the run, ${fmtTime(tend / 10)}` : 'a tenth of the run'],
          ['0, for the Julia ports', 'no limit but the run itself'],
          ['0, for Auto', 'no limit while it is explicit, a tenth of what is left on the NDF'],
          ['Allowed', '0 or more'],
          ['Read by', readers('hmax')],
        ],
        sections: [{ text: `A limit costs steps wherever the solution is smooth, and every step counts against the step budget: a maximum of a millionth of the run needs a million steps, where the default budget is ${Number(SOLVER_DEFAULTS.maxSteps).toLocaleString('en')}.` }],
      };
    },

    'set:h0': () => {
      const u = timeUnit();
      return {
        kicker: 'Solver', title: 'First step',
        lead: `The first step to try, in ${u.name}s. 0 lets the solver choose it from the derivative at the start, which is almost always better than a guess.`,
        facts: [['Default', SOLVER_DEFAULTS.h0], ['Allowed', '0 or more'], ['Read by', readers('h0')]],
        sections: [
          { text: 'For a start the derivative there does not describe: a rate that is zero at the first instant and jumps a moment later, or a front about to reach a boundary. A first step that is too long is rejected and cut like any other, so a poor guess costs steps rather than accuracy.' },
          { heading: 'Keep in mind', text: 'Auto hands it to its explicit start; once the run has turned stiff, the NDF chooses its own.' },
        ],
      };
    },

    'set:normControl': () => ({
      kicker: 'Solver', title: 'Norm control',
      lead: 'Judges the error of a step against the size of the whole solution rather than each species in each cell against its own: the 2-norm of the error over the larger of the 2-norms of the state before and after the step. MATLAB calls it NormControl.',
      facts: [['Default', SOLVER_DEFAULTS.normControl ? 'on' : 'off'], ['Read by', readers('normControl')]],
      sections: [
        { text: 'With it on, the error norm above does not arise. Far looser on a model whose species differ by orders of magnitude, which a reaction network usually does: every trace species is judged against the largest one, and goes uncontrolled. It is off, and is there to match a result worked out that way.' },
      ],
    }),

    'set:matrix': () => {
      const cur = $('rtmMatrix').value;
      const n = state.compiled ? state.compiled.states : 0;
      return {
        kicker: 'Solver', title: 'Iteration matrix',
        lead: 'How I − hJ, the matrix every implicit step solves with, is factorised. It decides the speed, not the answer.',
        facts: [
          ['Default', SOLVER_DEFAULTS.matrix],
          ['Dense LU', 'refused past 256 MB, about 5,800 equations'],
          ['This model', n ? `${n} equations; dense, ${mb(8 * n * n)}` : null],
          ['Read by', readers('matrix')],
        ],
        sections: [{
          choices: [
            ['auto', 'One trial factorisation decides: the LU that keeps its pivots where it costs no more, the dense LU where the sparse factor fills more than 35 % of the matrix, and the searching sparse LU otherwise. Right almost always. The Julia ports make their own choice.', cur === 'auto'],
            ['sparse LU, pivots kept', 'Keeps its pivots from one factorisation to the next and re-checks them, which saves the search on a matrix whose pattern never changes; one it cannot do goes to the LU auto would otherwise use. The Julia ports have no such LU and use their sparse one.', cur === 'refactor'],
            ['sparse LU', 'Chooses its pivots afresh at every factorisation (Gilbert–Peierls).', cur === 'sparse'],
            ['dense LU', 'Every entry, zero or not: n² numbers. Quick for a small batch, slow for a long column.', cur === 'dense'],
          ],
        }],
        more: more('The Jacobian', 'help-jacobian'),
      };
    },

    'set:jacobian': () => {
      const cur = $('rtmJacobian').value;
      return {
        kicker: 'Solver', title: 'Jacobian',
        lead: 'Where df/dy comes from.',
        facts: [['Default', 'analytic, sparse'], ['Read by', readers('jacobian')]],
        sections: [{
          choices: [
            ['analytic, sparse', 'Worked out when the model compiles: the rate laws differentiated symbolically, and the transport, which is linear, entered exactly. Nothing is differenced, so there is no step size to choose.', cur === 'analytic'],
            ['finite differences', 'Differenced from the equations. The NDF differences through the analytic pattern, a group of columns per evaluation; the Julia ports are then given no pattern, and difference one column per evaluation into a dense matrix. Slower and less exact either way.', cur === 'numeric'],
          ],
        }, { text: 'Differencing is the check to run when the analytic Jacobian is in doubt. **Check Jacobian**, under Run, compares the two without a run.' }],
        more: more('The Jacobian', 'help-jacobian'),
      };
    },

    'set:kappa': () => ({
      kicker: 'Solver', title: 'Newton tolerance',
      lead: 'How closely each stage’s Newton iteration must converge, as a share of one unit of the tolerance. DifferentialEquations.jl calls it κ.',
      facts: [['Default', SOLVER_DEFAULTS.kappa], ['Allowed', 'above 0 and below 1'], ['Read by', readers('kappa')]],
      sections: [
        { text: 'Loose leaves a stage half-solved, and the error estimate is read off those stages, so the step-size controller acts on a corrupted number. 1e-3 was measured, not chosen: at DifferentialEquations.jl’s own 1e-2, TRBDF2 and KenCarp4 went wrong on standard stiff test problems, and at 1e-3 they were right and several times cheaper.' },
        { heading: 'Keep in mind', text: 'Not the κ of **BDF formulas**, which is a coefficient of the NDF’s formulas. The NDF has a Newton test of its own and does not read this; nor does Rodas5P, which has no Newton iteration.' },
      ],
    }),

    'set:maxJacAge': () => ({
      kicker: 'Solver', title: 'Jacobian reuse',
      lead: 'How many steps a Jacobian may be reused before it is formed again; 1 forms it at every step.',
      facts: [['Default', SOLVER_DEFAULTS.maxJacAge], ['Allowed', '1 or more'], ['Read by', readers('maxJacAge')]],
      sections: [
        { text: 'Reusing it is most of what makes a stiff solver cheap on a large model, and a Newton iteration that slows down asks for a fresh one anyway. This is a plain age limit on top, as CVODE has, because a Newton that converges at its first iteration never questions its Jacobian: TRBDF2 once kept a Jacobian hundreds of steps old and walked off to 1e9 in quantities that belong between 0 and 1.' },
        { text: 'Rodas5P forms the Jacobian at every step by definition, and the NDF decides for itself, so neither reads this.' },
      ],
    }),

    'set:belowTolRun': () => ({
      kicker: 'Solver', title: 'Steps at the floor',
      lead: 'How many failing steps may be accepted in a row at the smallest step the clock can represent, where no shorter step exists. 0 stops the run there and hands back what it has.',
      facts: [['Default', SOLVER_DEFAULTS.belowTolRun], ['Allowed', 'a whole number, 0 or more'], ['Read by', readers('belowTolRun')]],
      sections: [
        { text: 'At the floor a failing step can only be accepted as it stands or the run given up. The NDF counts both kinds of failure here, an error test and a Newton iteration that will not converge; the Julia ports count the error test.' },
        { heading: 'Keep in mind', text: '0 is what the published methods do: accepting a step known to be inaccurate should be asked for.' },
      ],
    }),

    'set:maxSteps': () => ({
      kicker: 'Solver', title: 'Step budget',
      lead: 'How many steps the solver may take before it gives up and says so, handing back what it had.',
      facts: [['Default', Number(SOLVER_DEFAULTS.maxSteps).toLocaleString('en')], ['Allowed', '100 or more'], ['Read by', readers('maxSteps')]],
      sections: [{ text: 'A run that reaches it has usually met something the model did not mean, rather than needing a larger budget. What it did integrate is drawn, which is usually where the trouble can be seen.' }],
    }),

    'set:stagnationTol': () => ({
      kicker: 'Solver', title: 'Stall tolerance',
      lead: 'How large a Newton correction may be, as a share of one tolerance, and still be taken once it has stopped shrinking and the Jacobian is fresh. 0 never takes one.',
      facts: [['Default', SOLVER_DEFAULTS.stagnationTol], ['Allowed', '0 to 1'], ['Read by', readers('stagnationTol')]],
      sections: [
        { text: 'Reaction networks with rate constants to 1e16 against concentrations of 1e-9 cancel over sixteen digits, and their residual cannot be worked out to better than about a part in 1e7. The correction stops shrinking there, which an ordinary convergence test reads as divergence: the step is cut, which does nothing, and a run can take millions of steps to cover a few seconds. At 0.5 such a model runs in a few thousand.' },
        { heading: 'Keep in mind', text: 'On a model that does not need it, it costs accuracy: a correction is taken that more iterations would have improved. The canister radiolysis page leaves it at 0.' },
      ],
      more: more('Choosing a solver', 'help-solver'),
    }),

    'set:maxPoints': () => {
      const m = state.compiled;
      const pts = Math.max(1000, Number(state.solver.maxPoints) || Number(SOLVER_DEFAULTS.maxPoints));
      return {
        kicker: 'Solver', title: 'Points kept',
        lead: 'How many points of the solution are kept for the charts and the files. Past this the stored points are thinned as the run goes, so a long run still fits; the solution itself is not affected.',
        facts: [
          ['Default', SOLVER_DEFAULTS.maxPoints],
          ['Least', '1000'],
          ['This model', m ? `${m.speciesStates || m.states} numbers a point, ${mb(8 * (m.speciesStates || m.states) * pts)} at ${pts}` : null],
        ],
        sections: [
          { text: 'When the store is full, every other point is dropped and from then on every second step is kept, and so on. A long run ends with between half and all of this many, dense where the solver crept and sparse where it flew.' },
          { heading: 'Keep in mind', text: 'A time asked for on Against distance is drawn at the nearest stored point, not interpolated. More points bring those closer, at the cost of memory.' },
        ],
        more: more('Reading the charts', 'help-charts'),
      };
    },

    'set:autoAtol': () => ({
      kicker: 'Solver', title: 'Absolute tolerance follows the solution',
      lead: 'Lets each component’s absolute tolerance rise to rtol times the largest it has been, so that it is judged against its own history rather than a floor fixed before the run.',
      facts: [['Default', SOLVER_DEFAULTS.autoAtol ? 'on' : 'off'], ['Read by', readers('autoAtol')]],
      sections: [
        { text: 'Much cheaper on a decay chain, or anything else that spans many decades. Each species in each cell has its own, and it only ever rises: a quantity that peaked and decayed is no longer controlled in its tail.' },
        { text: 'The Newton iteration keeps the absolute tolerance it started with: how well a step’s equations were solved is not judged against history.' },
      ],
    }),

    'set:smoothEst': () => ({
      kicker: 'Solver', title: 'Smooth the error estimate',
      lead: 'Filters the error estimate through I − hJ, as Shampine proposed, so that a stiff component cannot inflate it and force a needlessly small step.',
      facts: [['Default', SOLVER_DEFAULTS.smoothEst ? 'on' : 'off'], ['Read by', readers('smoothEst')]],
      sections: [{ text: 'The multistep methods, NDF, FBDF and QNDF, estimate their error from the backward differences instead.' }],
    }),

    'set:nonNegative': () => ({
      kicker: 'Solver', title: 'Keep every species non-negative',
      lead: 'Holds every species in every cell at or above zero.',
      facts: [['Default', SOLVER_DEFAULTS.nonNegative ? 'on' : 'off'], ['Read by', readers('nonNegative')]],
      sections: [
        { list: [
          'The NDF and Rosenbrock 2-3 damp the derivative, so that a species at zero cannot be pushed further down; count a violation in the error test; and project an accepted step back to zero.',
          'Dormand–Prince does the last two: an explicit method’s stages would straddle the kink a damped derivative makes.',
          'The Julia ports do the last of the three only, and Auto does that while it is explicit and all three on the NDF.',
        ] },
        { heading: 'Keep in mind', text: 'Switch it off to see whether the model itself drives a species below zero. A negative value then points at the model, a reaction that consumes a species its rate law does not read for one, rather than at the solver.' },
      ],
    }),

    'run:beside': () => ({
      kicker: 'Runs', title: 'Keep this run',
      lead: 'A run kept to draw beside the next: change the model or its settings, run again, and the two are on the same charts.',
      sections: [
        { heading: 'Keeping', list: [
          '**Keep this run**: the run on show, kept with the text it was made with, its species, cells and time unit its own. Four are kept at most, the oldest let go.',
          '**beside it**: which kept run is drawn beside the one on show, or nothing. A kept run outlives its model: another example, or a file opened since, is drawn beside it as well.',
        ] },
        { heading: 'Drawn beside', list: [
          '**Against time**: each line ticked, of the kept run at the same cell and layer, dashed in the same colour, its times in this run\'s unit.',
          '**Against distance**: each profile, of the kept run at its stored time nearest, dashed in the same colour along its own cells.',
          '**Gradient**: the kept run\'s map under this run\'s, on one colour scale.',
          '**Composition**: its waters beside these on the Piper, Durov, Schoeller, Stiff, Wilcox and USSL diagrams and the principal components; not where an element is, whose bands stack.',
          'Only what the kept run has: the chart\'s note says where it has not the species or quantity, the cell or the rock.',
        ] },
      ],
      more: more('Two runs side by side', 'help-beside'),
    }),

    'pane:time': () => {
      const m = state.compiled;
      const still = m && m.transport ? m.species.filter((_, i) => !m.mobile[i]) : [];
      return {
        kicker: 'Tab', title: 'Against time',
        lead: 'What is ticked in the list, at one cell, at every stored point of the run: species, and what the run comes to besides them — pH, totals, saturation indices and the rest.',
        sections: [
          { heading: 'The toolbar', list: [
            '**Cell**: which cell of the column, with its centre in metres from the left-hand face; or, after the cells, the **flux through the left end** or **the right end**: what crosses it per m² of the water’s cross-section, positive to the right, which at an outlet is the release. A batch is one cell and has no picker.',
            '**Cells**: what is ticked at several cells at once, breakthrough curves down the column — a list of cell numbers such as `4, 9, 14, end`, `end` the last; six at most. Each keeps its colour, in steps of lightness down the column, faintest at the cell nearest the inlet; the legend and the CSV give each cell’s distance. Empty, the one cell **Cell** chooses.',
            '**Layer**: with a rock matrix, the fracture or a layer of rock behind the cell, by the depth of its centre.',
            '**Time in**: the model’s own unit; another of seconds, minutes, hours, days and years, the model’s times scaled; or — where the water flows — pore volumes: the time over the time the water takes to cross the column, `TRAVEL_TIME`, or `LENGTH` over the pore water’s speed |`VELOCITY`|/`POROSITY`. One choice for Against time, Against distance and Gradient; the model and its run are not changed, only the times shown. A time unit chosen is the one the other tabs, and every time written out, show too; rates stay per the model’s own unit, and pore volumes are for these three charts alone. Opening skbrtm’s files with their script chooses the unit its `t_span` names. A run kept beside is drawn in its own pore volumes, so that two runs at different speeds line up; what `<DATA>` measured is put on the axis by its time.',
            '**breakthrough numbers**, in a column: two tables under the chart. Of each curve drawn, where it starts, the farthest it gets from there and when, and when it is first half-way from the one to the other, read off every stored point; where the water flows, that time in pore volumes and the retardation it implies — those pore volumes over the share of the column the water has crossed to get there, 1 for what moves with the water. It is a front’s median, not its mean, and a front that spreads much moves it a little: set a species against a tracer of the same run. Of each species and each element’s total ticked, what has come out of the column, from its budget as the Composition tab keeps it: what was there at the start, what came in at the left, what went out at the right, what is there at the end, what reactions made or took, and the share gone out of what was there and came in. A run kept beside has its own rows; Excel has both tables on sheets of their own.',
            '**every species in numbers**: a table under the chart of each species at the cell shown: where it starts and ends, its highest and when, and when it settles — from when it stays within 1 % of where it ends, for a tenth of the run at least — or that it is still changing at the end. A species held fixed says what was put in, or taken out, over the run to keep it there: what the reactions took of it, less what they made. Under the table, the pressure each dissolved gas — CO2, O2, H2, N2, CH4, NH3 — would need to stay in the water at its highest, by phreeqc.dat, one needing more than 1 atm in bold. A click on a species draws it, or takes it off the chart; **Copy the table** puts it on the clipboard. **Check the run**, under it, solves the run again a hundred times more carefully, both tolerances a hundred times tighter, and sets the two against each other at every stored point: a column says how far each species moved at the cell, as a share of the most it reaches there, and a line under the table says that the run holds, no species having moved by 0.1 % of its highest, that it nearly holds, none by 1 %, or that it does not; and where it does not quite hold, which species moved most, when and where, and what it is in each run, with **Run with the careful setting**, which puts the tighter tolerances in the panel and runs again. A species smaller than the absolute tolerance over the relative is judged against that size, not on digits the run was not asked for. On until turned off.',
            '**log time**, **log concentration**: logarithmic axes. A log axis cannot show zero, so t = 0, and values at or below zero, are left off.',
            '**from**, after log time: where a log time axis starts, a plain number in the unit **Time in** shows, or in pore volumes where they are chosen; changing **Time in** turns it into the other. A stiff run’s first steps are femtoseconds long, and without it the chart opens on fifteen empty decades. A linear axis starts at 0 whatever it says.',
            '**from**, after log concentration: where a log concentration axis starts, a plain number such as `1e-10`; empty, it reaches the least drawn. A redox run’s species can span 150 decades, and a floor keeps the ones that matter readable. A curve below it drops out of view, and the note names any that lie wholly below; the CSV and Excel files have every value still. pH, pe and the like on the right are drawn as they are.',
            '**Units**: the unit the concentrations are shown in, one choice for every chart and the water’s listing. Under an `ACTIVITY`, mol/kgw, mmol, µmol or nmol per kgw, or mg or µg per kgw by the formula mass — a species by its name, a nuclide by its mass number, a mineral by its relation, an element’s total by its atomic weight; without one, the same per L or per kgw where the model names its unit, `CONC_UNIT = mol/L`, and else the model’s own unit times 10³, 10⁶ or 10⁹. pH, pe and the like stay as they are; what has no such unit — a pressure, a species whose name is no formula in mg — is left off, and the note says which. The measured points, the run kept beside, the **from** of the log axis, the axis title and the CSV and Excel files are in it too.',
            '**clear**: unticks everything.',
          ] },
          exportSection([
            '**CSV**: what is ticked, or every species when nothing is, at the cell and layer shown, at each of the Cells, or through the end shown, a row per stored point; in pore volumes a column of them first, then the time.',
            '**Excel**: the same as a workbook, with the model text on a sheet of its own, and every species in numbers and the breakthrough numbers where they are shown. **SVG** and **PNG**: the chart as a figure, at the size it is drawn.',
            SAVE_HTML,
            '**HDF5**: the whole run as an HDF5 file, as a download.',
            '**View in Data Browser**: the same file, opened in the Data Browser in a new tab without touching the disk. The browser has to let the page open a tab.',
          ]),
          { heading: 'The list', text: [
            'Drag its bottom right-hand corner to make it as tall as you like; the page keeps the height, for the next visit too. A double click on the corner gives it back its own.',
            'A ticked entry is filled in the accent colour. The species come first, then what the model can be read as besides them, in groups that open and shut: the water (pH, pe, Eh, ionic strength, a(H2O), charge balance), the totals of each element in the water and, in a model with the electron where it is in two valence states or more, in each, tot(Fe(2)) as PHREEQC’s TOT("Fe(2)"), saturation indices, gases, what is on an exchanger or a surface, the text’s `<OUTPUT>`, what each reaction does (shut until opened where there are more than six lines), and under an `ACTIVITY` the log activities, shut until opened. They are worked out from the stored concentrations with the model’s own activity model, the first time they are asked for.',
            'What each reaction does: for each `<REACTIONS>` line its **rate** — the forward rate less the backward one, from the very code the solver runs, times what the cell holds of the species for a rate on the inventory and times the porosity in the rock, so that it is what the reaction moves in the cell’s water in a unit of time — on the right with pH and the like; and its **extent**, what it has done since the start, the rate summed over the stored points, as close as they are to each other. A rate drawn on Gradient shows where a reaction runs and when; an extent at the end of the run along the column, how much it did where. A held equilibrium has no rate of its own and is not among them; Diagrams, Sweeps and Uncertainty, which read a quantity point by point, offer the rates and not the extents.',
            'An amount goes on the left-hand axis with the species, log or not; pH, pe, Eh, a saturation index, a log activity or a share on the right, as it is. What `<DATA>` measured of something ticked is drawn as points beside it, at the cell its table names.',
            'In a column a species diffuses when it has a `D`, and with `ADVECTION` and a `VELOCITY` the flow carries every species that is not `fixed`, whatever its `D`.',
            still.length ? `In this model these do not move: ${someOf(still)}.` : '',
          ].filter(Boolean) },
        ],
        more: more('Taking the run away with you', 'help-export'),
      };
    },

    'pane:profile': () => ({
      kicker: 'Tab', title: 'Against distance',
      lead: 'One species, or one quantity, across the column at several times, a curve for each; or those ticked on Against time, together at one time. It needs a run in transport mode: a batch has no distance.',
      sections: [
        { heading: 'The toolbar', list: [
          '**Show**: its own choice, apart from the ticks on Against time: a species, or a quantity of the water — pH, a total, a saturation index, a share of an exchanger, an `<OUTPUT>`. What `<DATA>` measured of it along the column is drawn as points.',
          '**Those ticked against time, at one time**, first in Show: each species and quantity ticked on Against time, a curve each in its colour there, at one time — a plume’s zones side by side. pH, pe, a saturation index and the like go on an axis of their own on the right, as they are.',
          '**Across**: with a rock matrix, along the fracture at one layer, or into the rock behind one cell, with the fracture at depth 0.',
          '**Layer**, or **At cell** into the rock: which layer the curve runs along, or which cell the rock is behind.',
          '**Times**: a list such as `0, 1 h, 30 d, 500 y`, in s, min, h, d, a or y (both years of 365.25 days), or PV, pore volumes, where the water flows; a bare number is in the unit **Time in** shows, or in pore volumes where they are chosen. Empty draws eight, spread evenly over the stored points, the last at the end of the run. With those ticked against time, the first time alone, and empty the end of the run.',
          '**Time in**: as on Against time, one choice for the three charts: the model’s own unit, another time unit, or pore volumes. The legend, the slider and the note name each time in it; a run kept beside is drawn at the stored point nearest the same pore volume of its own. Changing it turns the bare numbers of Times into the other, so that the same curves are drawn.',
          '**log concentration**: a logarithmic axis, for an amount; pH, a saturation index or a share is drawn as it is.',
          '**from**: where the log concentration axis starts, a plain number such as `1e-10`; empty, it reaches the least drawn. What lies below drops out of view, and the note names any curve wholly below it; the CSV and Excel files have every value still.',
          '**Units**: as on Against time, one choice for every chart. A species or quantity with no such unit is drawn as the model has it, and the note says so; with those ticked against time it is left off.',
          '**The slider** under the bar: one time at a time, a stored point a step. The chart draws what Show has at that time — one curve, or those ticked against time — on axes that span the whole run, so that a front moves across a still frame. What `<DATA>` measured is faint, and as itself at the stored time nearest its own.',
          '**play**: moves the slider on from where it is, or from the start, at the **Pace** chosen: the whole run in 5, 10 or 30 s, evenly in time, or a stored point a frame, slower where the solver stored more; **pause** stops it. **back to Times** draws the Times again, and so does typing them.',
        ] },
        exportSection(['**CSV**, **Excel**: the curves drawn, a row per distance. **SVG**, **PNG**: the chart as a figure.', SAVE_HTML]),
        { heading: 'Which times are drawn', text: 'Each time asked for is drawn at the nearest stored point; nothing is interpolated. The legend names the time drawn, and the note says which moved by more than 1 %, which could not be read and which lie past the end of the run.' },
      ],
      more: more('Reading the charts', 'help-charts'),
    }),

    'pane:gradient': () => {
      const cur = $('rtmGradScale').value;
      return {
        kicker: 'Tab', title: 'Gradient',
        lead: 'The whole run in one picture: time along x, distance from the left-hand face up y, and one species or quantity as colour, a band per cell and a column per stored point. It needs a run in transport mode.',
        sections: [
          { heading: 'The toolbar', list: [
            '**Show**, and **Layer** with a rock matrix: what is drawn — a species, or a quantity such as pH or a saturation index — along the fracture or along one layer of rock.',
            '**The redox zones**, first in Show in a model with the electron: each cell at each time coloured by the couple that holds its pe, the one with the most poising capacity there, n·Tox·Tred/(Tox + Tred) of what the cell holds in its two states, O₂ and H₂ against the water itself; oxic first and down the ladder, in the Colours chosen at equal steps of lightness. Hover for the couple and the pe; the note gives each zone\'s share. A map only.',
            '**As**: a map, contours of it with their values on them, or a surface in three dimensions, the value up, which the mouse turns.',
            '**Time in**: as on Against time, the model’s own unit, another time unit, or pore volumes where the water flows; a run kept beside in its own.',
            '**log time** and **from**: as on Against time. Without a from time the first femtoseconds take most of a log axis; the note says how many points it left off.',
            '**log concentration**: colours by log₁₀ c. Values at or below zero are left blank rather than put at the bottom of the scale, and the note counts them.',
            '**from**, after log concentration: where the colour scale starts, a plain number such as `1e-10`; empty, the least value there is. What lies below it takes its colour, or on a surface lies below the box; the CSV and Excel files have every value still.',
            '**Units**: as on Against time, one choice for every chart. A species or quantity with no such unit is drawn as the model has it, and the note says so.',
            '**smooth**: interpolates between the cells. It looks better and claims a resolution the run has not got, which is why it is off.',
          ] },
          exportSection(['**CSV**, **Excel**: the numbers drawn, a row per cell and a column per time. **SVG**, **PNG**: the picture.', SAVE_HTML]),
          { heading: 'Colours', choices: [
            ['yellow to red', 'Light for low, dark red for high.', cur === 'YlOrRd'],
            ['viridis', 'Dark purple to yellow, even in lightness, and in order when printed in grey.', cur === 'Viridis'],
            ['cividis', 'Dark blue to yellow, made to read the same to most colour-blind readers.', cur === 'Cividis'],
            ['grey', 'Black for low, white for high.', cur === 'Greys'],
          ] },
        ],
        more: more('Reading the charts', 'help-charts'),
      };
    },

    'pane:composition': () => {
      const view = $('rtmCompView').value;
      return {
        kicker: 'Tab', title: 'Composition',
        lead: 'What the water is made of, from the stored concentrations and what each species is made of: where an element is, one water listed as PHREEQC prints it, the water\'s major ions as the Piper, Durov, Schoeller and Stiff diagrams draw them, and its class for irrigation.',
        sections: [
          { heading: 'Show', choices: [
            ['where an element is', 'Each species with any of the element, as its share of all of it, stacked to 100 %, or as its amount: in the water, or in the whole cell, on an exchanger or a surface, in a mineral and a gas too. A species that never comes to 1 % is drawn with the others like it, as one band.', view === 'where'],
            ['the water, as PHREEQC lists it', 'One water — a **Cell**, **At** a stored time, the end of the run unless given — set out as PHREEQC prints a solution, from the model\'s own speciation: its composition; its description, pH, pe, Eh, temperature, ionic strength, the water\'s activity and the percent error; the distribution of species, each element in each of its valence states, every species with its molality, activity and log gamma; the saturation indices with log IAP and log K; the minerals; an exchanger\'s or a surface\'s species and their shares; a gas\'s pressure. **beside PHREEQC**: the same water given to PHREEQC, through the database the PHREEQC tab has chosen, as that tab gives it a run\'s — its element totals, the pH walked onto its [H+], its pe — and PHREEQC\'s molality and log gamma beside each species, its SI beside each phase, its pH, ionic strength, activity of water and percent error beside the water\'s; what PHREEQC finds that the model has not, apart; the note how far apart the two are at most, and what PHREEQC was not given. **Units**, other than the model\'s own: a column in that unit after PHREEQC\'s own, in the composition, each element by its atomic weight, and in the distribution, each species by its formula mass.', view === 'listing'],
            ['a budget over the run', 'Of an element, or of one species (**Of**): what the column holds of it at each stored time — in the water, on an exchanger or a surface, in each mineral, in the rock — stacked, with what has gone out at the right-hand end on top; dashed, what was there at the start with what has come in at the left; the gap between them, what the reactions made of it, dotted on its own. Per m² of the water\'s cross-section in a column, per kg of water in a batch. What no reaction makes or takes closes to the solver\'s tolerance and the summing of the ends\' fluxes over the stored points, and the note says how far; a nuclide\'s decay, or a source among the reactions, shows as what the reactions made. A species held fixed stays where it is because what the reactions take of it is put back, and what they make of it taken away: what holding put in, dash-dotted, beside what the reactions made, the reactions\' lines counting what they did to it as to any other. **every element**, first in **Of**: each element\'s balance side by side — start, in, out, end, made by reactions, put in by holding — and how far it is off, a bar each on a log axis; below 1e-4 it closes, above a reaction makes or takes it. **By** each reaction, where the model has `<REACTIONS>`: what each line makes of it and takes, a rate worked out as the solver\'s derivative works it out, a line and one written apart that undoes it as one reaction; stacked over the whole column or at a cell (**Over**), made above nought and taken below, the eight reactions that move most named; under the chart what each made and took over the run, and over the whole column what each relation moved, its extent read off the balance of a species of its own, the summing\'s error left, and what holding put in. **By** where it goes, of an element: a flow diagram over the run of its species and the ends of its account — put in by holding, came in or went out, made or lost by reactions, drawn from what was there or built up — each band what went from one to the other, net, a reaction and its reverse netted as one; hovering on a band names the reactions that carried it; a table of every flow under it.', view === 'budget'],
            ['where the minerals\' fronts are', 'In a column, each mineral\'s fronts from the inlet through the run: of one the column holds at the start, the length of column cleared of it — each cell its width times the share of its first amount gone, a sharp front\'s place inside its cell; of one that forms, the first and the last cell holding any. A table of each front at the end and its speed over the second half of the run, against the water\'s own speed, and when each mineral was gone or first formed. A dissolution front moves at v S/(S + M), S the water\'s at saturation and M the mineral\'s.', view === 'fronts'],
            ['a Piper diagram', 'The cations\' shares in the triangle on the left, the anions\' on the right, and the two together in the diamond: a path through the run at one cell, coloured by time, or along the column at one time, coloured by distance.', view === 'piper'],
            ['a Durov diagram', 'The cations\' shares in a triangle on the left of a square, the anions\' in one on top, and the water in the square where the two meet: HCO₃ + SO₄/2 across, Ca + Mg/2 up, Na–Cl at the foot on the left, Ca–HCO₃ at the head on the right. Under the square its pH, to the right its total dissolved solids in mg/kgw, from each species\' formula, where the model has them.', view === 'durov'],
            ['a Schoeller diagram', 'Each water a line through its six major ions, in equivalents on a log axis: the same shape is the same water diluted.', view === 'schoeller'],
            ['Stiff diagrams', 'Each water a polygon, cations to the left of zero and anions to the right, on one scale so that their sizes compare.', view === 'stiff'],
            ['a USSL diagram', 'The U.S. Salinity Laboratory\'s classes of irrigation water: the specific conductance across, C1 to C4 split at 250, 750 and 2,250 µS/cm, and the sodium adsorption ratio up, S1 to S4 split by lines that fall as the conductance rises. Needs SC, which a model has with <CONDUCTANCE>, and SAR.', view === 'ussl'],
            ['a Wilcox diagram', 'Wilcox\'s (1948) classes of irrigation water: the cations\' total in meq/kgw across, about a hundredth of the conductance in µS/cm, and the percent sodium up; lines at 7.5, 20 and 30 and three curves split it from excellent to good to unsuitable. The curves are traced from his figure. Needs mol/kgw, which ACTIVITY gives, and sodium.', view === 'wilcox'],
            ['principal components (PCA)', 'Gibbs Studio\'s principal component analysis: each water a row of the variables **Of** names, or its pH and each element dissolved, each standardised; the components the eigenvectors of their correlation matrix. The waters at their scores on the first two, coloured by time or distance, and each variable an arrow to its correlation with them.', view === 'pca'],
          ] },
          { heading: 'The major ions', list: [
            'Ca and Mg are twice their dissolved totals, **Na + K** the two together, Cl its total, **SO₄** twice the sulfur in sulfate — a species with four O to each S, so not HS⁻ — and **HCO₃ + CO₃** the carbonate\'s alkalinity, HCO₃⁻ one and CO₃⁻² two. A total is everything dissolved: CaHCO₃⁺ counts in Ca and in the carbonate.',
            'In meq/kgw under an ACTIVITY, whose concentrations are mol/kgw; otherwise the concentrations times the charge.',
            'Measured waters come from <DATA>, by the names the model gives them: tot(Ca) or Ca+2, alk(CO3) or HCO3- and CO3-2. One the table has no column for counts as none.',
            'A USSL diagram reads SC and SAR, or the SAR from tot(Na), tot(Ca) and tot(Mg). Its classes are for the conductance at 25 °C; the model\'s, as PHREEQC\'s, is at the water\'s own temperature.',
            'A Wilcox diagram\'s percent sodium is Na over Ca, Mg, Na and K, all in milliequivalents, Na alone on top as Wilcox has it; its curves are traced from his figure, to 0.4 % in percent sodium.',
          ] },
          { heading: 'The toolbar', list: [
            '**Along**, in a column: the run at one **Cell**, or the column at one time, **At**.',
            '**The slider** under the bar, along the column, for where an element is and the diagrams: the column at one stored time at a time, and **play** to move it on through the run at the **Pace** chosen, as on Against distance. The axes hold still: the triangles and the diamond of themselves, the rest drawn to what every stored point of every cell comes to — the Schoeller’s and the Stiff’s scales, the Durov’s pH and dissolved solids, the USSL’s conductance and SAR, the Wilcox’s cations, an element’s amounts and which of its species are bands of their own; principal components are the whole run’s, each time’s waters put on them. **back to At** draws At’s time again, and so does typing At.',
            '**Times**: the waters a Schoeller or Stiff diagram draws, six spread over the run unless given; a Piper, a USSL or a Wilcox diagram, and principal components, draw every stored point.',
            '**Of**: the variables of a principal component analysis, as the time chart names them — `pH, tot(Ca), Na+, SI(Calcite)`. **logs of amounts**: an amount as its log, where every water has some of it. A variable the same in every water is left out.',
          ] },
          exportSection([
            '**CSV**, **Excel**: the numbers drawn — each band, or each water\'s ions, shares and type, or its scores; for principal components Excel adds the loadings and the variance each component carries. **SVG**, **PNG**: the picture.',
            '**Text**, for the water as PHREEQC lists it: every block in PHREEQC\'s columns, to set beside its output; its CSV is the distribution of species, its Excel workbook every block on a sheet of its own.',
            SAVE_HTML,
          ]),
        ],
        more: more('Reading the charts', 'help-composition'),
      };
    },

    'pane:diagram': () => {
      const two = !!(dgResult && dgResult.reply.y);
      return {
        kicker: 'Tab', title: 'Diagrams',
        lead: 'The model\'s own chemistry, as PhreePlot draws PHREEQC\'s: the water of one cell held at each point of a range — a pH, a pe or an Eh, a species\' activity, a cation\'s over the hydrogen ion\'s or an element\'s total, or two of them — and speciated there by the relations of <EQUILIBRIUM>.',
        sections: [
          { heading: 'What is worked out', list: [
            '**The water of cell**, **as it starts** or **ends the run**: the water held. Its totals stay as they are, but for what is varied; there is no charge balance, as in PHREEQC\'s SOLUTION.',
            '**Vary**: **pH**, the activity of H+; **pe**, the electron\'s; **Eh (V)**, that pe in volts at the water\'s temperature; **log activity of** a species dissolved; **log activity over H+ of** a cation, log a(K+)/a(H+) or log a(Ca+2)/a(H+)², the cation held at the activity that gives it over the H+ there, the pH of the other axis or the water\'s; **log total of** an element in the cell, mol/kgw. **and** a second one makes a grid; **and the pH held at** a number holds the water at that pH at every point, as PHREEQC\'s SOLUTION holds the pH it is given.',
            '**and the water at saturation with**: one thing varied, and at each point the water held at saturation with each phase named — every phase of the model where none is — each a water of its own: the phase\'s first element, H and O aside — gibbsite\'s aluminium, calcite\'s calcium, CO2(g)\'s carbon — set to the total at which its saturation index is 0, or the number after its name: `CO2(g) -3.5`. As PHREEQC\'s SOLUTION sets an element by a phase, `Al 1 Gibbsite 0`. A point whose total would be outside 1e-30 to 100 mol/kgw is left blank.',
            'A mineral there stays at saturation while there is any of it. A point that settles neither from the point before it nor from the water is tried again from the point after it; one that still does not is left blank, and the status line counts them.',
            '**Work it out**: in the background; a grid of 101 × 41 takes a second or less.',
          ] },
          { heading: 'Show', list: two ? [
            '**the species that holds most of an element**, in the water or the whole cell: over pH and pe or Eh, a Pourbaix diagram, with the water\'s own limits, O₂ above and H₂ below at 1 atm and 25 °C: in volts 1.229 − 0.0592 pH and −0.0592 pH.',
            '**the species or the phase that holds most of an element**: where a phase made of the element is at saturation or over, the most stable of them per mole of it — its saturation index over its count of the element — holds it, a solid\'s field; elsewhere the species dissolved holding most of it. Over pH and pe or Eh, a Pourbaix diagram with its solids — hematite and siderite beside Fe+2 and Fe+3 — at the water\'s own total of the element dissolved, as textbooks draw one at 10⁻⁶ mol/kgw. Its boundaries are found as the others\' are: between two phases where their indices per mole are equal, between a phase and a species where the phase comes to saturation.',
            '**the phase furthest over saturation, or at it**: a mineral stability diagram.',
            '**the phases of an element, the most stable per mole of it**: each phase\'s saturation index over its count of the element — aluminium in a silicate — the largest the phase the rest would turn into, the element kept in the solids, whatever of it is dissolved: over log a(H4SiO4) and log a(K+)/a(H+), Garrels and Christ\'s diagram of K-feldspar, muscovite, kaolinite and gibbsite. A phase without the element that comes to saturation on the map, quartz say, is dotted across it where it does.',
            '**the redox couples, as lines**, over pH and pe or Eh: each couple of the redox ladder traced across the map, where the water holds as much of its element in either state — the textbooks\' diagram of a water\'s couples — a colour to each element and a dash to each couple, between where water gives way, the water itself marked. A couple that does not turn over on the map is said in the note.',
            '**a species or a quantity, as contours**: its log where it is an amount.',
            'A map\'s **boundaries** are found between the grid\'s points, the water speciated again there, to 1e-10; where three fields meet, the point is solved for. A field narrower than the grid can be missed.',
          ] : [
            '**the redox couples, as a ladder**, along pe or Eh with the pH held: each relation of <EQUILIBRIUM> with the electron in it between two valence states of an element — SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O — placed where it turns over, the pe at which this water holds as much of the element in the oxidised state as in the reduced one, in the water or the whole cell, found to 1e-10. Where water gives way, O₂ and H₂ at 1 atm and 25 °C, dashed; the water\'s own pe dotted. The note says which couples turn over outside the range.',
            '**what dissolves: the total at saturation**, after a saturation: each phase\'s element dissolved at saturation with it, as its log — a solubility diagram; with one phase, each species of the element beside it, what it holds of it, 2 for Al2(OH)2+4, so that they add up to the total. The views below are then of the water at saturation with the phase chosen in **at saturation with**.',
            '**the species of an element** as shares of it, or as log concentrations.',
            '**the saturation indices** of every phase and mineral.',
            '**a species or a quantity**: pH, a total, an <OUTPUT>, …',
          ] },
          exportSection(['**CSV**, **Excel**: a row per point, what is drawn there, or per couple of a ladder, its pe and its Eh; a map\'s Excel workbook has its boundaries on a sheet of their own. **SVG**, **PNG**: the picture.', SAVE_HTML], true),
        ],
        more: more('Diagrams of the model\'s own chemistry', 'help-diagrams'),
      };
    },

    'pane:sweep': () => ({
      kicker: 'Tab', title: 'Sweeps',
      lead: 'The model run again for each value of what is varied, as Gibbs Studio\'s parametric runs: the text with that number put in, run with the panel\'s solver settings, and the runs drawn together.',
      sections: [
        { heading: 'What is run', list: [
          '**Vary**: a setting with a number — VELOCITY, TEMPERATURE, TEND, … — a parameter of <PARAMETERS>, a species\' concentration at the start on its line, what flows in at the left, its left=, a relation\'s or a phase\'s logK, or a number a reaction\'s line names. **and** a second one runs every pair.',
          '**over**: a list, 0.5, 1, 2, or a range, 1e-6 to 1e-4 in 5, with log after it to space them in the logarithm. A new choice starts from half, the value and twice it, a log K from a unit either side. 400 runs at most.',
          '**each constant in turn**, first in **Vary** where the model has any: every number a reaction\'s line names and every parameter given one value throughout, each raised 1 % and lowered 1 %, one at a time, with the model as written — twice as many runs as constants, and one. Lines alike with other values, a parameter with a value for each cell, an expression or nought are left out, and the note says which. **each log K in turn**: every relation\'s and phase\'s log K moved by log₁₀ 1.01 either way, its K 1 % more and 1 % less; and both together.',
          '**keeping cell**: the cell whose every species and quantity is kept along each run; along the column, each run\'s end is kept whole.',
          'A run that fails says why on the status line, and the rest go on. Stop stops them all.',
        ] },
        { heading: 'Show', list: [
          '**against what was varied**: a species or a quantity at the cell, its value at the end, its largest or its smallest, a point per run; over two, a curve for each value of the second, contours or a surface.',
          '**against time, a curve per run**, at the cell; **along the column at the end, a curve per run**. The curves go from dark to light as the value grows.',
          '**each constant, by how much it moves it**, after each in turn: a bar for each of the 25 that move it most, the per cent a species or an amount changes for 1 % more of the constant — the change in its logarithm over the change in the constant\'s, between the run 1 % up and the run 1 % down; for pH, an SI and the like, how much it changes. Blue raises it, orange lowers it. A log K on the same scale: the per cent it changes for 1 % more of K. At the end, its largest or its smallest, at the cell.',
          '**through the run, the eight that move it most**, after each in turn: every run read at the same 200 times by the solver itself, a hundred spread evenly and a hundred in the logarithm, and at each the per cent it changes for 1 % more of each, a curve for each of the eight that move it most anywhere in the run. A reaction\'s rate or extent is kept at the end only.',
        ] },
        exportSection(['**CSV**, **Excel**: what is drawn, a row per value or per point. **SVG**, **PNG**: the picture.', SAVE_HTML], true),
      ],
      more: more('Sweeps over runs', 'help-sweeps'),
    }),

    'pane:fit': () => ({
      kicker: 'Tab', title: 'Fit',
      lead: 'The model fitted to what <DATA> measured, as PhreePlot and Gibbs Studio fit PHREEQC: the numbers named moved until the run is as near to the measurements as it can be, by least squares.',
      sections: [
        { heading: 'What is fitted', list: [
          '**Fit** … **from**: up to four numbers and where each starts — a setting, a parameter, a species\' start or what flows in, a relation\'s or a phase\'s log K, a number a reaction\'s line names (k, kf, or a constant of a rate law). A new choice starts from the value the text gives it.',
          '**to**: the columns of <DATA> fitted to, every one unless unticked.',
          'A table against pH, pe or Eh — a sorption edge, the share of a metal on a surface at each pH — needs no run: its water is held at each value it measured and speciated there, as on the Diagrams tab, and the fit draws it against that value.',
          'A column sd(Ca+2) beside Ca+2 in <DATA> gives each value its standard deviation: the fit is then weighted, each residual over its own deviation, the misfit χ² on the points less the numbers fitted, the standard errors the deviations\' own. Every value fitted needs one, or none does.',
          'A table against pH may have a water of its own — `pH  Zn_sorbed  Zn+2 = 1e-4` — the model with those species started there: edges at several loadings or ionic strengths fitted together, which pins down what one edge leaves loose, a weak site\'s constant beside a strong one\'s. Each is drawn as a curve of its own, named by its water.',
          'A table against sys(Zn) — `sys(Zn)  Zn_sorbed  pH = 6.5` — is a sorption isotherm: the water with that much zinc in the cell, dissolved, sorbed and as minerals, as PHREEQC\'s SYS("Zn") counts it, at the pH its line holds it at, or where the water has it. Fitted beside the edges, it ties a site\'s constant to how many sites there are. **against** chooses which tables the chart draws, where the fit has tables against more than one thing; an isotherm on a log axis.',
          'A number above zero is fitted in its logarithm, so it stays above zero; a log K and the temperature as they are. Give each a start above zero where it is fitted in its logarithm.',
        ] },
        { heading: 'How', list: [
          'Levenberg and Marquardt\'s least squares, each derivative from a run with one number moved a little, with the panel\'s solver settings. The run is read at exactly the times measured.',
          'An amount\'s residual is log₁₀ of the run over what was measured, so a factor of two counts the same at any size; pH, SI and the like count as their difference.',
          'The standard errors and correlations are the Jacobian\'s at the end, the residuals giving the scatter; about 95 % is 1.96 standard errors either way, as a factor for a number fitted in its logarithm.',
          'The band shaded about each curve is about 95 % for the curve: 1.96 of its standard deviation either way, from the fitted numbers\' standard errors and correlations — the delta method, the curve worked out again with each number moved a step either side. An amount\'s goes as a factor either way, as the fit compares amounts. It is narrow where the measurements pin the curve down, wider between them and past them. The CSV gives it at each point measured, Excel at every point of every curve, on a sheet of its own.',
        ] },
        { heading: 'Then', list: [
          '**Show** the run at the fitted numbers with the measurements, the residuals, or the misfit as it fell.',
          '**the run against what was measured, one to one**, last in Show, with a fit or without one: each value measured set against the run’s at the same place and time — the run on show read between its stored points and its cells, linearly — on equal axes with the line of one to one, amounts on log axes with twice and half dashed, pH, SI and the like on their own. Under it, for each column: its points, the bias (the mean residual, for an amount shown as the factor the run is of what was measured), the spread (their root mean square), the sum of squares and the worst point; then all the columns together, as the Fit sums them. After a fit the fitted run is there as diamonds, at the times measured; a run kept beside, hollow.',
          '**Put the fitted values in the model**: each written into the text where it came from, to six figures.',
        ] },
        exportSection(['**CSV**, **Excel**: each point measured, the run there and its residual. **SVG**, **PNG**: the picture.', SAVE_HTML], true),
      ],
      more: more('Fitting to what was measured', 'help-fit'),
    }),

    'pane:uncertainty': () => ({
      kicker: 'Tab', title: 'Uncertainty',
      lead: 'The model run for draws of what is uncertain, as Gibbs Studio\'s Monte Carlo: each number given a distribution, drawn, run, and the runs drawn as bands.',
      sections: [
        { heading: 'What is drawn', list: [
          '**Draw** … **from a**: up to eight numbers — anything Sweeps can vary — each with a distribution: normal (mean, SD), lognormal (median, and the factor one standard deviation takes it × or ÷ by), uniform or log-uniform (from, to), triangular (from, most likely, to). A new one starts about the value the text gives it.',
          '**From the fit**: the last fit\'s numbers, each about its fitted value by its standard error — lognormal for one fitted in its logarithm — and **with the fit\'s correlations** drawn together, through a Gaussian copula.',
          '**Runs**, **drawn by** Latin hypercube, Sobol or simple random, and **seed**: distributions.html\'s own sampling, each number from a stream of its own, the same draws from the same seed.',
          '**keeping cell**: the cell whose every species and quantity each run keeps; along the column, each run\'s end is kept whole. The model as it is written runs too, for reference.',
        ] },
        { heading: 'Show', list: [
          '**bands against time** at the cell, or **along the column at the end**: 5 to 95 % and 25 to 75 % of the runs at each time or cell, their median, the model as written dashed, and what <DATA> measured there.',
          '**the spread of one value** — at the end, its largest or its smallest — as a histogram, with its 5 %, median and 95 %.',
          '**what matters, by rank correlation**: Spearman\'s rank correlation of each number drawn with that value, from −1 to 1.',
          '**what matters, by sensitivity indices**: from the same runs, nothing run again, each number\'s first-order Sobol\' index (EASI), the share of the value\'s variance it explains alone; Borgonovo\'s δ, how far knowing it moves the value\'s whole distribution, read off the value\'s normal scores so that runs that end alike do not throw it; and PAWN\'s median Kolmogorov–Smirnov distance — each with a 95 % interval from 100 bootstrap resamples. A dummy drawn and never used shows how large chance alone makes them: a number whose bars are no longer than the dummy\'s makes no difference the runs can tell. Twenty runs at the least; a few hundred narrow the intervals.',
        ] },
        exportSection(['**CSV**, **Excel**: the percentiles at each time or cell, or each run\'s numbers and value; the indices with their intervals, Excel adding the runs. **SVG**, **PNG**: the picture.', SAVE_HTML], true),
      ],
      more: more('Uncertainty', 'help-uncertainty'),
    }),

    'pane:model': () => ({
      kicker: 'Tab', title: 'Model',
      lead: 'The model the page solves, as text. It compiles 0.4 s after the last keystroke; the status line says what it compiled to or where it went wrong, and any warnings are listed under the text. A line a warning or an error names is a link to it: a click goes to that line and selects it. Put the cursor on a name and the line under the text says where it is used: listed, made, used up, read by a rate, each line a link. Once the text has changed, a line under it says how much since it was opened, and Show lists each change, what it was and what it is, with the line of skbrtm’s file it came from for a set of those.',
      facts: [
        ['Examples', `${EXAMPLES.length} in ${new Set(EXAMPLES.map((e) => e.group)).size} groups`],
        ['Open… or a drop reads', `up to ${DROP_MAX_FILES} files, ${DROP_MAX_BYTES / 1048576} MB`],
        ['The text is kept', 'in this browser, between visits'],
      ],
      sections: [
        { heading: 'The toolbar', list: [
          '**Example**: loads one of the examples, and a line under the picker says what the model is and where it comes from. Under **Your earlier texts** it lists the last five texts put aside, by title and when.',
          '**Open…**: a model text (`.rtm`, `.txt`), or skbrtm’s database files and the Python script that runs them (`.in`, `.py`), read as one model — or a `.zip` of either, read as its folder would be. Dropping files, their folder or a `.zip` anywhere on the page does the same.',
          '**From PHREEQC…**: opens a panel where PHREEQC speciates a water and the water, as PHREEQC leaves it, becomes the text. Its own (i) says how.',
          '**Reset to the built-in model**: water radiolysis and uranium dissolution at a spent-fuel surface, 127 reactions over 36 species. It too replaces the text without asking.',
          '**colour the syntax**: paints comments, section headings, numbers, functions and the words that mean something where they stand. Turn it off for a very large model. The choice is kept.',
          '**line numbers**: a number beside each line, as the warnings and errors name them; the lines the warnings under the text name are marked in amber, the line an error names in red. The choice is kept.',
          '**Save…**: the text, where you choose: the system’s save dialog opens, offering the name the text was saved under last, or of the file it came from, or of its title. Where the browser has no such dialog (Safari, Firefox), it is downloaded.',
          '**Apply**: compiles the text now.',
        ] },
        { heading: 'Nothing lost', text: 'Whatever replaces the text — an example, Reset, a file, a water from PHREEQC, the fitted values put in — first puts it aside, if it is one you changed or opened: **Bring it back**, in the line under the toolbar, swaps the two back, and the Example picker keeps the last five between visits. An example or the built-in model as it comes is not kept, as it can be had again. A reload does not bring the built-in model back: the text stays in this browser until something replaces it.' },
      ],
      more: more('The model text', 'help-model-text'),
    }),

    'pq:water': () => ({
      kicker: 'Model tab', title: 'A water from PHREEQC',
      lead: 'PHREEQC speciates a water, from its analysis or after whatever else the input does to it, and the water as PHREEQC leaves it becomes the model text: its species, and its equilibria with constants that hold at this water.',
      facts: [
        ['PHREEQC', 'the U.S. Geological Survey’s, version 3, compiled to run in the browser: the water goes nowhere'],
        ['Database', pqDatabase() ? pqDatabase().name : 'phreeqc.dat, which comes with the page'],
        ['Kept', 'the water and these settings, in this browser between visits'],
      ],
      sections: [
        { heading: 'What is written', list: [
          'Every aqueous species above the floor, at PHREEQC’s molality, in `<SPECIES>`.',
          'Every complexation and acid–base reaction among them, as the database writes it, in `<EQUILIBRIUM>`: held exactly through the run (`EQUILIBRATE = always`), as fast pairs with a `kf`, or at the start only, as **The equilibria during the run** says.',
          'Between activities that follow the ionic strength, with the database’s own log K (`ACTIVITY`), or with each `logK` **conditional**, the activity coefficients at this water folded in, as **Activity coefficients** says.',
          'The redox couples, as **Hold the valence states at one pe** says: each species the database writes with electrons tied to the electron, `e-`, by that reaction, so that every couple is at one pe as in PHREEQC; or none of them, each valence state keeping its own total.',
          'A name rtm.html cannot write, such as `(UO2)2(OH)2+2`, is renamed (`UO2_2(OH)2+2`), and the text lists each one at the top.',
        ] },
        { heading: 'The input', text: 'Ordinary PHREEQC input: a `SOLUTION`, and anything PHREEQC should do to it first, such as `EQUILIBRIUM_PHASES`, `REACTION` or `MIX`. The water of its last calculation is the one written. **Open…** reads a PHREEQC input file; **An example water** puts in a granitic groundwater made of round numbers.' },
        { heading: 'Keep in mind', text: 'The model text is replaced, as an example replaces it. Concentrations are molalities, so rate constants you add must use the same unit. The constants belong to this water’s ionic strength; the PHREEQC tab says how far a run moves from it.' },
      ],
      more: more('A water from PHREEQC', 'help-phreeqc-water'),
    }),

    'pq:database': () => ({
      kicker: 'PHREEQC', title: 'Database',
      lead: 'Where PHREEQC takes its species, their reactions and constants, the activity model and the phases from.',
      facts: [
        ['In use', pqDatabase() ? `${pqDatabase().name}, opened this visit` : 'phreeqc.dat, which comes with the page'],
        ['Opened this visit', pq.opened.size ? someOf([...pq.opened.keys()], 6) : 'none'],
      ],
      sections: [
        { text: '**phreeqc.dat** is the database that comes with PHREEQC 3.8.6, unchanged.' },
        { text: '**Open a database…** reads another, such as `llnl.dat`, `wateq4f.dat`, `minteq.v4.dat` or a project’s own, and PHREEQC reads it at once and says whether it can. It is used for this visit only: a database is never stored in the browser, and one opened last time is named until it is opened again.' },
        { text: 'The choice is shared by the panel on the Model tab, the PHREEQC tab and the Batch tab: one database for all of them.' },
      ],
      more: more('PHREEQC in the page', 'help-phreeqc'),
    }),

    'pq:floor': () => ({
      kicker: 'PHREEQC', title: 'Leave out species below',
      lead: 'Species PHREEQC finds at less than this many mol/kgw are left out of the model. That keeps a few thousand vanishing complexes from a large database out of the text.',
      facts: [['Default', '1e-20 mol/kgw'], ['Now', $('rtmPqFloor').value || '(empty)']],
      sections: [
        { text: 'A species below the floor is still kept when a relation that is kept needs it, so that every relation written is whole. The report says how many those were, and the largest species left out.' },
        { text: '0 keeps every species PHREEQC lists.' },
      ],
      more: more('A water from PHREEQC', 'help-phreeqc-water'),
    }),

    'pq:activity': () => ({
      kicker: 'PHREEQC', title: 'Activity coefficients',
      lead: 'PHREEQC holds its relations between activities. This says how the model written from the water holds them.',
      facts: [['Default', 'following the ionic strength']],
      sections: [{ choices: [
        ['following the ionic strength', 'The relations hold between activities, as PHREEQC’s do, and each species’ activity coefficient follows the ionic strength of its cell as the run goes on: `ACTIVITY = debye-huckel` at the water’s `TEMPERATURE`, by the database’s `-gamma` (`a=` and `b=`) where it gives one and Davies for any other ion; with a SIT database `ACTIVITY = sit`, the database’s interaction coefficients between the species written in `<SIT>`; with a Pitzer database `ACTIVITY = pitzer`, its parameters between them in `<PITZER>`, each with its terms in the temperature; with an LLNL database (`llnl.dat`) `ACTIVITY = llnl`, each species’ `-llnl_gamma` as `a=` and the database’s tables in `<LLNL>`. Each relation is written with its water and the database’s own log K, as it goes with temperature, and the comment on it gives the conditional log K at this water.', pq.act === 'follow'],
        ['fixed at this water', 'Each log K is conditional: the activity coefficients at this water, and the activity of water, are folded into it, and the relations hold between concentrations. Exact at this water; a run that moves the ionic strength moves away from it, and the PHREEQC tab says how far. The database’s temperature terms stay with it, and the coefficients folded in are this water’s at any temperature.', pq.act === 'fixed'],
      ] }, { heading: 'Keep in mind', text: 'Following costs a little: one ionic strength a cell each time the rates are worked out, and a fuller Jacobian within a cell. Under SIT each coefficient reads the species it is paired with as well, so more again, and under Pitzer every solute of its cell, so a cell is speciated whole.' }],
      more: more('A water from PHREEQC', 'help-phreeqc-water'),
    }),

    'pq:minerals': () => ({
      kicker: 'PHREEQC', title: 'Keep the phases at saturation',
      lead: 'Each phase of the input’s EQUILIBRIUM_PHASES becomes a mineral of the model, at the amount PHREEQC left of it, and is held at its saturation index while there is any of it.',
      facts: [['Default', 'off'], ['Needs', 'the equilibria held exactly']],
      sections: [
        { text: 'Off, the phases only prepare the water: calcite and a CO2 pressure put it where it is, and the run starts from that water with no calcite and no gas. On, they stay: calcite dissolves as acid comes in and precipitates where the water is supersaturated, and a gas holds its partial pressure, as EQUILIBRIUM_PHASES do in PHREEQC.' },
        { text: 'Each is written as `mineral` on its species line, at its amount per kilogram of water, with its reaction from the database’s PHASES and its log K at the water’s temperature, plus its saturation index. The run stops where one dissolves away or precipitates, and says so.' },
        { heading: 'Not carried', text: 'A phase that dissolves with electrons, such as pyrite, unless the valence states are held at one pe; and one whose line says more, such as dissolve_only. The report says which.' },
      ],
      more: more('A water from PHREEQC', 'help-phreeqc-water'),
    }),

    'pq:redox': () => ({
      kicker: 'PHREEQC', title: 'Hold the valence states at one pe',
      lead: 'Each species the database writes with electrons is tied to the electron, `e-`, by that reaction, so that every couple in the water is in equilibrium at one pe, as PHREEQC has them.',
      facts: [['Default', 'on'], ['Needs', 'the equilibria held exactly']],
      sections: [
        { text: 'On, the text gets `e- electron` and a relation such as `Fe+2 <=> Fe+3 + e-` for each species of another valence state, with the database’s own log K. The electron is no amount: the run works out its activity, 10^-pe, in every cell from the electrons the couples hold between them, so an oxidant that arrives, or a reductant that runs out, moves every couple together. A phase that dissolves with electrons, such as pyrite, can then be kept at saturation.' },
        { text: 'A water PHREEQC was given as an analysis keeps the valence states it was given, whatever its pe says: sulfate given, it has no sulfide however reducing it is. PHREEQC’s next step, any reaction, puts every couple on one pe and forms the valence states the water was given none of, and the text is that next step; the report says how far it moved the pe. With **Leave out species below** at 0, every species PHREEQC lists is written, even those it finds none of, such as oxygen in a reducing water: then there is a species for oxygen coming in to arrive as.' },
        { text: 'Off, no relation with electrons is written: each valence state keeps its own total, and electrons move only through the reactions you write, as in a radiolysis model where `e-` is the hydrated electron.' },
      ],
      more: more('Redox: the electron', 'help-redox'),
    }),

    'pq:hold': () => ({
      kicker: 'PHREEQC', title: 'The equilibria during the run',
      lead: 'Every relation written puts the start on equilibrium. This says what keeps it there while the run goes on.',
      facts: pq.eq === 'pairs'
        ? [['Relaxing at', `${$('rtmPqRelax').value || '(empty)'} per second`], ['Default', 'held exactly']]
        : [['Default', 'held exactly']],
      sections: [{ choices: [
        ['held exactly', 'Each relation is an algebraic equation in every cell, all through the run (`EQUILIBRATE = always`). What the relations conserve is integrated, and the species are worked out from it at every step, so the relations hold to rounding wherever the run is read. Only the NDF solves that; Auto hands the model to it.', pq.eq === 'exact'],
        ['held as fast reversible pairs', 'Each relation is a pair of reactions, the backward constant `kb = kf/K`, which pull it back to equilibrium at the rate given. One forward constant for every relation would not do: a water relation and a carbonate relation need constants about thirteen orders apart to move at the same speed. So each gets the **kf** that makes it relax back at that rate, at this water: near equilibrium a relation relaxes at kf times the product of its reactants times the sum of ν²/c over its species, and that is solved for kf. The kf are per second: change `TIME_UNIT` in the text and they have to change with it.', pq.eq === 'pairs'],
        ['on equilibrium at the start only', 'The relations put the start on equilibrium (`EQUILIBRATE = 1`) and nothing more: during the run only the reactions you write move the species.', pq.eq === 'start'],
      ] }, { heading: 'Keep in mind', text: 'A fast pair lags its relation wherever the water changes faster than it relaxes, as it does where a new water comes in; one held exactly does not lag. Faster relaxation closes the gap and costs the solver steps.' }],
      more: more('A water from PHREEQC', 'help-phreeqc-water'),
    }),

    'pq:diffusion': () => ({
      kicker: 'PHREEQC', title: 'Diffusion',
      lead: 'Whether the species written get a diffusion coefficient, `D=` on their lines, for a model that becomes a column.',
      sections: [{ choices: [
        ['none', 'No `D`: the model is a batch, or you add the coefficients in the text.', pq.diff === 'none'],
        ['one coefficient for every species', 'The value given, in m²/s, on every line.', pq.diff === 'one'],
        ['each species its own', 'The tracer diffusion coefficient the database gives each species (`-dw`); a species without one gets none.', pq.diff === 'dw'],
      ] }, { heading: 'Keep in mind', text: 'With each species its own coefficient the text also says `DIFFUSION = nernst-planck`: the ions are coupled so that no current flows, and the water stays neutral as they spread. With one coefficient for every species there is nothing to couple. A column from an input\'s `TRANSPORT` takes its coefficients from there: its `-diffusion_coefficient`, or under `-multi_D` each species\' `-dw` times the porosity to the n, coupled, and down the activities.' }],
      more: more('A water from PHREEQC', 'help-phreeqc-water'),
    }),

    'pane:phreeqc': () => ({
      kicker: 'Tab', title: 'PHREEQC',
      lead: 'The run, seen through PHREEQC: every stored water is given to PHREEQC, which speciates it with its own constants, activity model and ion pairs.',
      facts: [
        ['Database', pqDatabase() ? pqDatabase().name : 'phreeqc.dat'],
        ['Waters', pq.view ? `${pq.view.report.waters.toLocaleString()} in the last look` : 'none looked at yet'],
      ],
      sections: [
        { heading: 'What PHREEQC is given', list: [
          'Each species of the run that the database has, under the same name or the renamed one, counted into the element totals PHREEQC takes: `HCO3-` into C(4), `H2` twice into H(0), `(UO2)2(OH)2+2` twice into U(6).',
          'The pH, walked until PHREEQC’s molality of H+ is the run’s [H+].',
          'A mineral, an exchanger or a surface of the model, the species on them, and a gas, are not part of the water: a mineral is listed with the phases, an exchanger or a surface is looked at whole, and a gas against the pressure the water holds it at.',
          'Left out, and listed: water; rtm.html’s `e-`, which is the hydrated electron and not PHREEQC’s; radicals and anything else the database lacks.',
          'The temperature the model was written at, read from the top of its text; 25 °C for a model that does not say.',
          '**fill in from the water** (off unless ticked): the water in the panel on the Model tab gives the temperature, and any element the model does not carry at all, such as a background electrolyte, held at its totals. A model written from a water carries all of them already; this is for one that leaves its counter-ions out. A water PHREEQC will not take is said, and left out.',
        ] },
        { heading: 'What comes back', list: [
          'The pH as an activity, and the saturation index of every phase that comes within 3 of saturation, or of the **Phases** named, drawn against time for one cell or, under **Show**, against distance at one of the times looked at. The CSV holds every cell and the ionic strength, the charge balance and the activity of water as well.',
          'Which phases are supersaturated anywhere, and where and when.',
          'How far the activity coefficients of the model’s own equilibria moved along the run, in log K. That is how far constants made for the start have gone wrong; a model with `ACTIVITY` follows them, and then it says how close its own stay to PHREEQC’s.',
          'Each mineral of the model: the saturation index PHREEQC finds where the model has some of it, and where it has none.',
          'An exchanger or a surface of the model: how close what the run has on it is to what PHREEQC loads onto one of the same sites from the same water. The electron: how close the run’s valence states are to PHREEQC’s at the run’s pe. A gas phase: how close each gas’s partial pressure in the run, its fugacity for a real gas, is to the pressure PHREEQC finds the water holds it at.',
          'A water that is far from neutral, which usually means the model leaves out a counter-ion.',
        ] },
        { heading: 'Settings', text: '**Times per cell**: at most this many stored times, spread over the run (0 reads them all). **Cells**: a list such as `0, 5, 10-19`, or empty for all.' },
        exportSection(['**CSV**: every water looked at, a row each: its time, cell and layer, its ionic strength, pH, −log m(H+), charge balance and a(H2O), and the saturation index of each phase.', SAVE_HTML], true),
      ],
      more: more('A run through PHREEQC', 'help-phreeqc-run'),
    }),

    'pq:inverse': () => ({
      kicker: 'PHREEQC', title: 'Inverse models',
      lead: 'PHREEQC\'s INVERSE_MODELING between two waters of the run: which phases, dissolving or forming, make the one of the other, every element of the waters balanced to the uncertainty given.',
      facts: [['Found', pq.invResult ? `${pq.invResult.models.length} model${pq.invResult.models.length === 1 ? '' : 's'} the last time` : 'none looked for yet']],
      sections: [
        { heading: 'The waters', list: [
          '**from**, **to**: the water flowing in at the left, or a cell of the column, **at** **start**, **end** or a time such as `2 d` — the stored point nearest it.',
          'Each is given to PHREEQC as a look through PHREEQC gives it: its element totals, its pe and temperature, the pH walked until PHREEQC’s H+ is the run’s.',
        ] },
        { heading: 'The models', list: [
          '**with**: the database’s phases that may dissolve or form, as `Calcite, Gypsum, CO2(g)`; one followed by `dissolve` or `precipitate` goes that way only. Empty: the model’s own minerals and gases.',
          '**uncertainty**: how far each total may move, a fraction of it: 0.05 is 5 %. Every element of the waters is balanced, but H and O. The water a mineral brings, gypsum\'s, is not counted: each water of a run is a kilogram of water.',
          '**ranges**: how far each transfer can go in any model the uncertainty allows. **minimal models only**: none whose work a smaller set of the phases does.',
        ] },
        { heading: 'What comes back', list: [
          'Each model’s mole transfers as bars, dissolving above zero, the ranges as whiskers; and a table of each, with the adjustments PHREEQC made and its three measures of misfit. To four figures, as PHREEQC prints them.',
        ] },
        exportSection(['**CSV**: every number of every model.', SAVE_HTML], true),
      ],
      more: more('Inverse models through PHREEQC', 'help-phreeqc-inverse'),
    }),

    'pq:batch': () => ({
      kicker: 'PHREEQC', title: 'A batch over a table of waters',
      lead: 'One PHREEQC input run for every row of a table: each {name} in it the row\'s value in the column of that name, the selected output kept row by row.',
      facts: [['Table', pq.batchTable ? `${pq.batchTable.name}, ${pq.batchTable.rows.length.toLocaleString()} row${pq.batchTable.rows.length === 1 ? '' : 's'}` : 'none opened yet'],
        ['Last batch', pq.batchResult ? batchFact(pq.batchResult) : 'none run yet']],
      sections: [
        { heading: 'The table', list: [
          '**Open a table…**: CSV, or an Excel workbook, a water a row and the columns\' names in the first row with anything in it; **Sheet** chooses among a workbook\'s sheets. Read for this visit, never stored or sent anywhere.',
          '**Rows**: all, or a list such as `1-100, 205` of the table\'s rows, to try a few before the rest.',
          '**Solids**: none, or a list such as `Calcite, Gypsum`: each row then runs once for each, in turn, `{solid}` in the input the solid -- see Several solids.',
        ] },
        { heading: 'The input', list: [
          'PHREEQC input as PHREEQC takes it, with the database chosen -- one choice with the PHREEQC tab and the panel: a `SOLUTION`, and whatever PHREEQC should do with it -- `EQUILIBRIUM_PHASES`, `REACTION`, `PHASES` and `NAMED_EXPRESSIONS` of its own.',
          '`{name}`: the row\'s value in the column of that name, as the table has it, `{pH}` or `{[Ca]tot (m)}`. A name the table has no column for is said before anything runs; one after a `#`, in a comment, is not asked for.',
          '`SELECTED_OUTPUT`: what to keep of each row\'s run, its `-totals`, `-pH` and the like, or a `USER_PUNCH`; the last row it gives is kept. A table opened with the box empty starts it: a `SOLUTION` with `pH` where the table has it, every other column below, commented, to take or leave.',
          '**Open an input…**, **Save the input…**: the input as a file, its settings above it as comments -- `# Solids: Calcite, Gypsum`, `# Draws: 100` -- so that it is PHREEQC input still. Opened, they fill their fields, any it does not give left empty; the table and the database it was saved with are said where they are not the ones open.',
        ] },
        { heading: 'What comes back', list: [
          'Every row runs on a clean slate (`DELETE -all` first), so nothing one row saved is there for the next; a row PHREEQC refuses keeps the first line of what it said, and the rest go on.',
          'The first 100 rows as a table; **Stop** ends it once the parts running are done, keeping every part done.',
          'The parts run on as many copies of PHREEQC at once as the computer has cores to spare, at most eight, the status saying how many; what comes back is the same however many, only sooner.',
        ] },
        { heading: 'Several solids', list: [
          'With solids listed, `{solid}` in the input is each in turn, as `{solid} 0 10` under `EQUILIBRIUM_PHASES`: each row runs once for each solid; a column of the table named solid is then not used.',
          '**Lowest in**: for each row, the run with the lowest value in that column of the selected output, and the solid that gave it -- the least that stays dissolved with whichever solid holds it lowest. Unless another is chosen, the first total of an element.',
          'Above the rows, each solid: in how many rows it was the lowest, how many of its runs PHREEQC refused, and what it said first. A row with a solid refused names it, for the lowest is then of the others.',
          'Several elements at once: a list for each, `Ba: Barite, Witherite; Sr: Celestite, Strontianite`. Each element\'s lowest is kept in its total, `Ba(mol/kgw)`, among its own solids only -- another\'s leave it where it was -- so the input\'s `-totals` must give each. The table has every element\'s lowest and the solid that gave it; **Spread of** chooses whose spread is drawn.',
        ] },
        { heading: 'Uncertain values', list: [
          '**Uncertain**: none, or values to draw at random, each a name, how it varies and its numbers, apart by semicolons: `dU normal 0 0.5` (a mean and a standard deviation), `dU uniform -1 1` (the least and the most), `dU triangular -1 0 0.5` (the least, the likeliest and the most).',
          'Each is a `{name}` in the input, where the value drawn goes: in a `log_k`, or a named expression\'s `log_k` that `-add_logk` adds. A name the input has not, or that the table has as a column, is said before anything runs.',
          '**Draws**: how many times each row runs, 10 unless said, each time with values drawn afresh; with solids, every solid of a draw has the same values. **Seed**: 1 unless said; the same seed draws the same values again, a row\'s the same whichever other rows run.',
          'Each draw keeps the values it drew, in the table and in what Export saves; the spread is over every row\'s every draw.',
        ] },
        { heading: 'The spread over the waters', list: [
          'A chart of the column chosen -- **Lowest in**, or **Spread of** without solids -- a step for each water, or each draw of a water: for each value, the share at or below it. On a log axis where the values are all above nought and span a factor of ten or more.',
          'The median and the 95th percentile marked; beside the chart, the number of waters, the smallest, the 5th percentile, the median, the 95th percentile and the largest. A percentile lies between the two nearest values, as Excel\'s PERCENTILE.INC and NumPy\'s percentile put it.',
          'A row PHREEQC refused, or whose run gives no number there, is left out, and counted.',
        ] },
        { heading: 'A map', list: [
          'Where the table has columns of places, each water at its place -- **Map over** two of the table\'s columns, those named X and Y unless others are chosen, — for none -- coloured by its result on one hue, light to dark (dark to light on the dark page), the key beside it, logarithmic where the values span a factor of ten or more.',
          'With draws, each water\'s colour is the median of its draws, and a click looks at the draw nearest it. Two columns named as places keep the same scale both ways. Export has it as SVG, PNG or a page, under The map.',
        ] },
        { heading: 'A batch kept beside', list: [
          '**Keep this batch**: kept for the visit, and the next batch you run drawn beside it -- the kept spread\'s curve grey behind the new one, its numbers in a column of their own, its points faint behind in the chart against a column -- where it has a result in the same column.',
          'The line under the bar says what is kept; **Forget it** lets it go. The workbook has the kept batch\'s table, input and spread too.',
        ] },
        { heading: 'One water in full', list: [
          'A row of the table, or a point of either chart, clicked: that water is run again -- the input as the batch filled it, the same draw, with solids the solid that gave the lowest -- and PHREEQC\'s whole output for it shown: its species with their molalities and activities, its saturation indices, what each phase did.',
          'Where every run of it was refused, the first, and what PHREEQC said with the input as filled. **Save as text…** keeps it; **Close** puts it away. Only with the database the batch ran with.',
        ] },
        { heading: 'Against a column', list: [
          'Under the spread, the same result against something else, a point for each water or draw: **against** a column of the table with numbers in it, a value drawn, or another of PHREEQC\'s columns, of the run kept.',
          'With solids, a colour for each solid, in the order they are listed, the legend naming them. Each axis is logarithmic where its values are all above nought and span a factor of ten or more.',
          'Unless another is chosen, a value drawn, else the table\'s pH, else its first column. A point with no number for either is left out, and the note under the chart counts them.',
        ] },
        exportSection(['**Report**: the batch as one page that opens in any browser -- what was run (the table, rows, database, PHREEQC\'s version, solids, values drawn, the input in full, the batch kept), the spread\'s numbers, the solids and the rows, and the charts, live.',
          '**CSV**: every row, with the table\'s values the input asked for, what PHREEQC gave, and what it said where it refused; with solids, each row\'s lowest and the solid that gave it.',
          '**CSV, every run**: with solids, each row with each solid.',
          '**Excel**: the same, a sheet each, the spread\'s numbers on one, and the input on a sheet of its own.',
          '**SVG**, **PNG**: the spread\'s chart as it is drawn; **HTML**: the chart, live, as a page of its own, the input under it.',
          'The chart against a column and the map, each the same, under headings of their own.']),
      ],
      more: more('A batch over a table of waters', 'help-phreeqc-batch'),
    }),

    'pane:jacobian': {
      kicker: 'Tab', title: 'Jacobian',
      lead: 'The sparsity pattern of the matrix the solver factorises, and what Check Jacobian found.',
      facts: [['Picture', '200 to 620 pixels square'], ['Listed', 'up to 10 disagreements for each state checked']],
      sections: [
        { heading: 'The pattern', text: 'Every entry the rate laws and the transport put in the Jacobian: the chemistry of each cell in the accent colour, and in the text colour the couplings between cells, the thin diagonals beside the blocks. The state is ordered cell by cell, so the matrix is banded. The caption says how much of one cell’s block is filled.' },
        { heading: 'Check Jacobian', text: 'The button under Run compares the analytic Jacobian with a central difference, at the starting state and again with every species that starts at zero set to between 1e-9 and 5e-9, so that rate laws which vanish at the start are tested too. An entry far below the largest in its column cannot be measured by a difference at all; those are counted apart rather than called wrong.' },
      ],
      more: more('The Jacobian', 'help-jacobian'),
    },
  };

  /* ---------------------------------------------------------------------
     The examples
     --------------------------------------------------------------------- */
  const EXAMPLES = typeof RTM_EXAMPLES !== 'undefined' ? RTM_EXAMPLES : [];

  /** The picker, grouped as the set is grouped. */
  function renderExamples() {
    const sel = $('rtmExample');
    if (!sel) return;
    const groups = [];
    for (const e of EXAMPLES) {
      let g = groups.find((x) => x.name === e.group);
      if (!g) { g = { name: e.group, items: [] }; groups.push(g); }
      g.items.push(e);
    }
    const was = sel.value;
    const mine = aside.length ? '<optgroup label="Your earlier texts">'
      + aside.map((x, i) => `<option value="aside:${i}">${esc(`${x.title} — ${asideWhen(x.at)}`)}</option>`).join('')
      + '</optgroup>' : '';
    sel.innerHTML = '<option value="">— choose one —</option>' + mine
      + groups.map((g) => `<optgroup label="${esc(g.name)}">`
        + g.items.map((e) => `<option value="${esc(e.id)}">${esc(e.label)}</option>`).join('')
        + '</optgroup>').join('');
    if (was && [...sel.options].some((o) => o.value === was)) sel.value = was;
  }

  /**
   * Load one, and say what it is.
   *
   * The text is replaced outright and nothing is asked first, which is what
   * "Reset to the built-in model" beside it does too -- the picker says the
   * text is replaced, and a blocking dialog in the middle of a page that has
   * none anywhere else is worse than the warning already on the control.
   */
  function chooseExample(id) {
    const e = EXAMPLES.find((x) => x.id === id);
    const about = $('rtmExampleAbout');
    if (!e) { about.hidden = true; $('rtmExample').value = ''; return; }
    const kept = putAside(e.text);
    setOpened({ text: e.text, kind: 'example', name: e.label });
    state.text = e.text;
    state.modelName = `${e.id}.rtm`;
    $('rtmText').value = e.text;
    renderHighlight();
    about.textContent = e.about + (e.reference ? `  ${e.reference}` : '');
    about.hidden = false;
    state.result = null;
    state.verify = null;
    anotherModel();
    renderBeside();
    applyExampleView(e.view || null);
    showAside(kept);
    saveState();
    compile();
  }

  /**
   * A model loaded whole -- an example, a file, a water from PHREEQC: a
   * diagram, a sweep or a fit of the one before is no longer this one's, and
   * the numbers fitted start afresh from this one's, where they were the
   * other's.
   */
  function anotherModel() {
    dgResult = null;
    swResult = null;
    fitResult = null;
    unResult = null;
    state.fit.params = [];
    state.fit.off = [];
    state.unc.rows = [];
    state.unc.corr = null;
    pendingView = null;
  }

  /*
    An example's view: the tab it opens on once it has run, and what is
    drawn there -- the time chart's picks, the gradient's, the composition
    tab's, a diagram or a sweep, which are then worked out. Set when the
    example is chosen; the tab follows the first run, so that the text the
    reader has just loaded stays in front of them until they run it.
  */
  let pendingView = null;
  function applyExampleView(v) {
    pendingView = v;
    // Where each log concentration axis starts: what the example gives, and from the least drawn where it gives nothing.
    const floors = { yFrom: v && v.yFrom, profileYFrom: v && v.profile && v.profile.from, gradCFrom: v && v.grad && v.grad.from };
    for (const [k, id] of [['yFrom', 'rtmYFrom'], ['profileYFrom', 'rtmProfileYFrom'], ['gradCFrom', 'rtmGradCFrom']]) {
      state[k] = typeof floors[k] === 'string' ? floors[k] : '';
      $(id).value = state[k];
    }
    // The unit the concentrations are shown in: the example's, and the model's own where it gives none.
    state.concUnit = v && CONC_UNITS[v.unit] ? v.unit : '';
    renderUnits();
    // Time in pore volumes where the example asks, else in the model's unit; at the cells it lists, else at its one cell.
    state.timeIn = v && v.timeIn === 'pv' ? 'pv' : '';
    state.cells = v && typeof v.cells === 'string' ? v.cells : '';
    $('rtmCells').value = state.cells;
    renderTimeIn();
    // Against distance at the Times, or at the example's one time on the slider; the Composition tab at At.
    profileStop();
    state.profileAt = v && v.profile && Number.isFinite(v.profile.at) ? v.profile.at : null;
    compStop();
    state.compAt = null;
    if (!v) return;
    if (v.picked) state.picked = v.picked.slice();
    if (Number.isInteger(v.cell)) state.cell = v.cell;
    if (typeof v.logT === 'boolean') $('rtmLogT').checked = v.logT;
    if (typeof v.logY === 'boolean') $('rtmLogY').checked = v.logY;
    if (v.profile) {
      if (v.profile.species) state.profileSpecies = v.profile.species;
      if (typeof v.profile.times === 'string') { state.profileTimes = v.profile.times; $('rtmProfileTimes').value = v.profile.times; }
      if (typeof v.profile.log === 'boolean') $('rtmProfileLog').checked = v.profile.log;
    }
    if (v.grad) {
      if (v.grad.species) state.gradSpecies = v.grad.species;
      if (v.grad.view) { state.gradView = v.grad.view; $('rtmGradView').value = v.grad.view; }
      if (typeof v.grad.logT === 'boolean') $('rtmGradLogT').checked = v.grad.logT;
    }
    if (v.comp) {
      // The Composition tab's own log-time box, where a path through the run is coloured by its times.
      const { logT, ...comp } = v.comp;
      for (const [k, val] of Object.entries(comp)) state[`comp${k[0].toUpperCase()}${k.slice(1)}`] = val;
      if (typeof logT === 'boolean') $('rtmCompLogT').checked = logT;
    }
    if (v.dg) {
      for (const [k, val] of Object.entries(v.dg)) {
        if (k === 'x' || k === 'y') Object.assign(state.dg[k], val);
        else state.dg[k] = val;
      }
    }
    if (v.sw) Object.assign(state.sw, v.sw);
    // What a fit fits and from where, what the uncertainty draws and how, and PHREEQC's inverse model's waters and phases.
    if (v.fit) state.fit = { params: v.fit.params.map((p) => ({ ...p })), off: (v.fit.off || []).slice() };
    if (v.unc) {
      const { logT, logY, ...unc } = v.unc;
      Object.assign(state.unc, { ...unc, rows: (unc.rows || []).map((row) => ({ ...row })), corr: null });
      if (typeof logT === 'boolean') $('rtmUnLogT').checked = logT;
      if (typeof logY === 'boolean') $('rtmUnLogY').checked = logY;
    }
    if (v.pqInv) {
      // The database the example was written from, the built-in phreeqc.dat, and the run's waters as they are, nothing filled in.
      const { db, fill, ...inv } = v.pqInv;
      Object.assign(pq.inv, inv);
      if (db === 'builtin') { pq.db = 'builtin'; pq.missingDb = null; }
      if (typeof fill === 'boolean') pq.fill = fill;
      pqWriteControls();
      pqSave();
    }
  }

  /** After a run, the view an example asked for: its tab, and a diagram, a sweep, a fit, the uncertainty or an inverse model worked out there. */
  function openExampleView() {
    const v = pendingView;
    pendingView = null;
    if (!v || !v.tab) return;
    showTab(v.tab);
    // After the run has let go of the worker: a sweep waits for no run.
    setTimeout(() => {
      if (v.tab === 'diagram' && v.go) dgGo();
      if (v.tab === 'sweep' && v.go) swGo();
      if (v.tab === 'fit' && v.go) fitGo();
      if (v.tab === 'uncertainty' && v.go) unGo();
      if (v.tab === 'phreeqc' && v.go) pqInverse();
    }, 0);
  }

  /* ---------------------------------------------------------------------
     Syntax colouring for the model editor

     A textarea cannot colour its own text, so the coloured copy is a <pre>
     underneath it and the textarea's own text is made transparent over it.
     That keeps native editing whole -- undo, selection, the caret, the
     spell-checker being off -- which a contenteditable div would not, and it
     is why the two boxes must agree on every metric that decides where a
     character lands: font, size, line height, padding, border and tab size
     are set together in rtm.css.

     What is coloured is what the compiler reads: the sections, the settings
     and the words their values may take come from rtm-model.js's own tables,
     so the colouring cannot drift from the meaning.
     --------------------------------------------------------------------- */

  /** Words that mean something on their own, by section. */
  const HL_WORDS = {
    PITZER: new Set(['b0', 'b1', 'b2', 'c0', 'theta', 'lamda', 'lambda', 'zeta', 'psi', 'mu', 'eta', 'alphas', 'aphi',
      'macinnes', 'etheta', 'yes', 'no', 'true', 'false']),
    LLNL: new Set(['temperatures', 'dh_a', 'dh_b', 'bdot', 'co2']),
    VOLUMES: new Set(['millero']),
    CONDUCTANCE: new Set(['gfw', 'dw', 'viscosity', 'vm']),
    SPECIES: new Set(['fixed', 'immobile', 'mineral', 'exchange', 'exchanger', 'electron', 'surface', 'potential', 'gas',
      'drummond']),
    INITIAL: new Set(['all', 'matrix', 'fixed']),
    PARAMETERS: new Set(['all', 'matrix', 'fracture']),
    REACTIONS: new Set(['water', 'inventory']),
  };
  /** Names that mean something where they take a value: `NAME = ...`. */
  const HL_ASSIGN = {
    SPECIES: new Set(['d', 'dm', 'de', 'kd', 'kdf', 'left', 'right', 'mass', 'r', 'rm', 'z', 'a', 'b', 'pe', 'sites',
      'area', 'grams', 'tc', 'pc', 'omega']),
    REACTIONS: new Set(['k', 'kf', 'kb', 'r', 'rb', 'on']),
    EQUILIBRIUM: new Set(['k', 'logk', 'kf', 'kb', 'dh', 'analytic']),
    PHASES: new Set(['k', 'logk', 'dh', 'analytic']),
    SIT: new Set(['eps1']),
    SOLID_SOLUTIONS: new Set(['a0', 'a1', 'g0', 'g1', 'tc']),
  };
  /*
    A species name ends in a charge -- H+, OH-, C2O4-2 -- and the charge is
    part of the name only when it is written against it, which is the same
    rule the compiler splits a stoichiometry by. Read the other way, the 2 of
    UO2+2 would be coloured as a number of its own.
  */
  const HL_TOKEN = /(\s+)|(<=>|=>|<=)|((?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*(?:[+-][0-9]+)?)|([=])|([\s\S])/g;
  const hlSpan = (cls, text) => `<span class="hl-${cls}">${esc(text)}</span>`;

  /** The settings and their word values, read from the compiler's table. */
  let hlSettings = null;
  function settingWords() {
    if (hlSettings) return hlSettings;
    const table = (typeof RtmModel !== 'undefined' && RtmModel.SETTINGS) || {};
    const names = new Set();
    const values = new Set(['yes', 'no', 'true', 'false', 'on', 'off']);
    for (const [name, spec] of Object.entries(table)) {
      names.add(name.toLowerCase());
      for (const word of spec.of || []) values.add(String(word).toLowerCase());
      for (const word of Object.keys(spec.words || {})) values.add(word);
    }
    hlSettings = { names, values };
    return hlSettings;
  }

  /** One line of the model text as HTML, given the section it is in. */
  function highlightLine(raw, section) {
    if (!raw) return '';
    if (/^\s*<[^<>]*>\s*$/.test(raw)) return hlSpan('sec', raw);
    /*
      The comment is whatever follows a # at the start of the line or after a
      space -- the same rule readSections strips by, so what is greyed out is
      exactly what the compiler never sees.
    */
    const at = /(^|\s)#/.exec(raw);
    const cut = at ? at.index + at[1].length : -1;
    const code = cut < 0 ? raw : raw.slice(0, cut);
    const comment = cut < 0 ? '' : raw.slice(cut);
    const words = HL_WORDS[section] || null;
    const assign = HL_ASSIGN[section] || null;
    const fns = typeof FacsimileModel !== 'undefined' ? FacsimileModel.FUNCTIONS : {};
    const settings = settingWords();
    let html = '';
    HL_TOKEN.lastIndex = 0;
    let m;
    while ((m = HL_TOKEN.exec(code)) !== null) {
      if (m[1] !== undefined) { html += esc(m[1]); continue; }
      if (m[2] !== undefined) { html += hlSpan('op', m[2]); continue; }
      if (m[3] !== undefined) { html += hlSpan('num', m[3]); continue; }
      if (m[4] !== undefined) {
        const word = m[4];
        const lower = word.toLowerCase();
        const rest = code.slice(HL_TOKEN.lastIndex);
        const takesValue = /^\s*=[^=>]/.test(rest) || /^\s*=$/.test(rest);
        // A rate law's SI(phase) and SR(phase) are functions of the page's own.
        if (/^\s*\(/.test(rest) && (fns[lower] || (section === 'REACTIONS' && (word === 'SI' || word === 'SR')))) {
          html += hlSpan('fn', word);
        } else if (takesValue && section === 'SETTINGS' && settings.names.has(lower)) html += hlSpan('key', word);
        else if (takesValue && assign && assign.has(lower)) html += hlSpan('key', word);
        else if (section === 'SETTINGS' && settings.values.has(lower)) html += hlSpan('key', word);
        else if (words && words.has(lower)) html += hlSpan('key', word);
        else html += esc(word);
        continue;
      }
      if (m[5] !== undefined) { html += hlSpan('op', m[5]); continue; }
      html += esc(m[6]);
    }
    return html + (comment ? hlSpan('com', comment) : '');
  }

  /*
    THE COLOURED COPY, REPAINTED A LINE AT A TIME.

    Recolouring the whole model on every keystroke costs the whole file, and
    the tokeniser is very nearly all of it: with the colouring off the same
    keystroke costs about 1 ms at any size. On facsimile.html's own default
    model, 47 kB, it was 20 ms of main-thread work per keystroke, which fast
    typing and key repeat outrun; rtm.html's 10 kB default was 7 ms. A
    keystroke changes one line, so only that line is tokenised again and only
    that line's element is rewritten -- 8.5 ms and 4 ms measured the same way.

    One <span> per line, each ending in its own newline, so what the <pre>
    lays out is character for character what it laid out before. hlLines and
    hlSecs hold what each line was last painted from -- the section as well as
    the text, since the same words colour differently under a different
    heading.
  */
  let hlLines = [];
  let hlSecs = [];

  /** Each line's section, resolved from the top down. */
  function lineSections(lines) {
    const secs = new Array(lines.length);
    let section = '';
    for (let i = 0; i < lines.length; i += 1) {
      // <TABLE name> carries a name after the word; the section is the word.
      const sec = /^\s*<\s*([A-Za-z_]+)(?:\s+[^<>]*)?>\s*$/.exec(lines[i]);
      if (sec) section = sec[1].toUpperCase();
      secs[i] = section;
    }
    return secs;
  }

  /** One line's element, the newline it ends with included. */
  function hlLineEl(line, section) {
    const el = document.createElement('span');
    /*
      A <pre> swallows one trailing newline and the textarea does not, so the
      last line carries its own newline like every other: without it the two
      scroll out of step at the end of the file.
    */
    el.innerHTML = `${highlightLine(line, section)}\n`;
    return el;
  }

  /*
    THE LINE NUMBERS, in a column of their own beside the text: one a line,
    as many as the text has -- an empty last line is a line the caret can
    stand on -- moved up as far as the text is scrolled. The lines the
    compile's warnings name (Line 194: ...) are marked in the warning's tone,
    the line its error names in the error's, and the lines that name the
    name the caret is on (showUses) in bold. Drawn again only when the count
    or the marks change; until the text compiles again, the marks stay on
    the lines they were given.
  */
  let lineNosDrawn = '';
  function lineMarks() {
    const marks = new Map();
    const m = state.compiled;
    if (m && Array.isArray(m.warnings)) {
      for (const w of m.warnings) {
        const at = /^Line (\d+):/.exec(w);
        if (at) marks.set(Number(at[1]), 'warn');
      }
    }
    const e = state.compileError;
    if (e && Number.isInteger(e.line) && e.line > 0) marks.set(e.line, 'error');
    // The lines that name the name the caret is on (showUses).
    for (const line of useLines) marks.set(line, marks.has(line) ? `${marks.get(line)} use` : 'use');
    return marks;
  }

  function renderLineNumbers() {
    const col = $('rtmLineNos');
    const ta = $('rtmText');
    if (!col || !ta) return;
    const inner = col.firstElementChild;
    if (!state.lineNumbers) {
      if (lineNosDrawn) { inner.textContent = ''; lineNosDrawn = ''; }
      return;
    }
    const text = ta.value;
    let n = 1;
    for (let i = text.indexOf('\n'); i >= 0; i = text.indexOf('\n', i + 1)) n += 1;
    const marks = lineMarks();
    const key = `${n}|${[...marks].map(([line, kind]) => `${line}${kind}`).join(',')}`;
    if (key !== lineNosDrawn) {
      lineNosDrawn = key;
      const out = new Array(n);
      for (let i = 1; i <= n; i += 1) {
        const kind = marks.get(i);
        out[i - 1] = kind ? `<span class="${kind}">${i}</span>` : String(i);
      }
      inner.innerHTML = out.join('\n');
    }
    inner.style.transform = `translateY(${-ta.scrollTop}px)`;
  }

  /** Shows the line numbers or puts them away. */
  function applyLineNumbers() {
    const box = $('rtmCodeBox');
    const check = $('rtmLineNumbers');
    if (check) check.checked = !!state.lineNumbers;
    if (box) box.classList.toggle('no-lines', !state.lineNumbers);
    renderLineNumbers();
  }

  /** Repaints the coloured copy and keeps it under the same part of the text; the line numbers with it. */
  function renderHighlight() {
    const pre = $('rtmHighlight');
    const ta = $('rtmText');
    if (!pre || !ta) return;
    renderLineNumbers();
    // Where the name the caret is on is used, read again from the text as it now is, and marked again.
    scheduleUses();
    const code = pre.firstElementChild;
    if (!state.syntax) { code.textContent = ''; hlLines = []; hlSecs = []; return; }
    const lines = ta.value.split('\n');
    const secs = lineSections(lines);
    /*
      What actually moved. Typing sits inside one line, so the run of untouched
      lines above it and the run below it are between them nearly the whole
      file, and comparing those strings is far cheaper than colouring them
      again. Enter, or a cut line, shifts everything below by one -- which is
      why the match is made from both ends rather than only from the top.
    */
    const n = lines.length;
    const m = hlLines.length;
    // Compared as two arrays rather than as one joined key per line: building
    // those keys allocated a second copy of the whole model on every repaint,
    // which is the cost this is here to avoid.
    const same = (i, j) => lines[i] === hlLines[j] && secs[i] === hlSecs[j];
    let head = 0;
    while (head < n && head < m && same(head, head)) head += 1;
    let tail = 0;
    while (tail < n - head && tail < m - head && same(n - 1 - tail, m - 1 - tail)) tail += 1;
    // Out with the lines that changed, in with what they became. Backwards,
    // so an index stays valid until it has been used.
    for (let i = m - tail - 1; i >= head; i -= 1) code.children[i].remove();
    if (n - tail > head) {
      const frag = document.createDocumentFragment();
      for (let i = head; i < n - tail; i += 1) frag.append(hlLineEl(lines[i], secs[i]));
      code.insertBefore(frag, code.children[head] || null);
    }
    hlLines = lines;
    hlSecs = secs;
    pre.scrollTop = ta.scrollTop;
    pre.scrollLeft = ta.scrollLeft;
  }

  /** Turns the colouring on or off. */
  function applySyntaxMode() {
    const box = $('rtmCodeBox');
    const check = $('rtmSyntax');
    if (check) check.checked = !!state.syntax;
    if (box) box.classList.toggle('hl', !!state.syntax);
    renderHighlight();
  }

  /* ---------------------------------------------------------------------
     Texts put aside
     --------------------------------------------------------------------- */
  /*
    Whatever replaces the model text -- an example, Reset, a file, a water
    from PHREEQC, the fitted values put in -- first puts the text there
    aside, if it is one worth keeping: a text the reader changed or opened,
    not an example or the built-in model as they come, which can be had
    again. The browser's own undo stops where the page sets the text, so
    without this an afternoon's edits went with one slip on the Example
    picker. The line under the toolbar offers the text just put aside back;
    the last ASIDE_MAX are kept between visits under a key of their own --
    not in the state saved at every compile -- and the Example picker lists
    them under "Your earlier texts". Nothing is asked first.
  */
  const ASIDE_KEY = 'kvot-rtm-aside-v1';
  const ASIDE_MAX = 5;
  let aside = [];             // [{ text, title, at }], the latest first

  function loadAside() {
    try {
      const a = JSON.parse(localStorage.getItem(ASIDE_KEY) || '[]');
      if (Array.isArray(a)) {
        aside = a.filter((x) => x && typeof x.text === 'string' && typeof x.title === 'string' && Number.isFinite(x.at))
          .slice(0, ASIDE_MAX);
      }
    } catch (e) { aside = []; }
  }

  /** Kept between visits: as many as the browser will keep, the oldest let go first; all of them for this visit. */
  function saveAside() {
    for (let n = aside.length; n >= 0; n -= 1) {
      try {
        if (n) localStorage.setItem(ASIDE_KEY, JSON.stringify(aside.slice(0, n)));
        else localStorage.removeItem(ASIDE_KEY);
        return;
      } catch (e) { /* more than the browser keeps: one fewer */ }
    }
  }

  /** A text worth keeping: not empty, and not an example or the built-in model as they come. */
  function worthKeeping(text) {
    return !!String(text || '').trim() && text !== RTM_DEFAULT_MODEL && !EXAMPLES.some((e) => e.text === text);
  }

  /** What a text is called in the list: its ## title, else its first comment, else how long it is. */
  function asideTitle(text) {
    let title = modelAbout(text).title;
    if (!title) {
      const lines = String(text).split(/\r?\n/);
      const comment = lines.slice(0, 12).map((l) => (/^\s*#/.test(l) ? l.replace(/^\s*#+\s*/, '').trim() : ''))
        .find((l) => /[A-Za-z]/.test(l) && !/^[=\-#\s]+$/.test(l));
      title = comment || `a text of ${lines.length} lines`;
    }
    return title.length > 60 ? `${title.slice(0, 59)}…` : title;
  }

  /** When it was put aside, as the list says it: the time today, the day and the time before. */
  function asideWhen(at) {
    const d = new Date(at);
    const now = new Date();
    const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    if (d.toDateString() === now.toDateString()) return `today ${hm}`;
    const day = `${d.getDate()} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()]}`;
    return `${day}${d.getFullYear() === now.getFullYear() ? '' : ` ${d.getFullYear()}`} ${hm}`;
  }

  /**
   * The text there now put aside, before next replaces it: the entry, or
   * null where it is not kept -- nothing changes, or it is not worth keeping.
   * A text already in the list moves to its top.
   */
  function putAside(next) {
    const text = state.text;
    if (text === next || !worthKeeping(text)) return null;
    // With what it was opened as, for the list of what has changed when it comes back.
    const entry = { text, title: asideTitle(text), at: Date.now(), opened };
    aside = [entry, ...aside.filter((x) => x.text !== text)].slice(0, ASIDE_MAX);
    saveAside();
    renderExamples();
    return entry;
  }

  /** The line under the toolbar: the text just put aside, with the button that brings it back; or the one come back. */
  function showAside(kept, back) {
    const note = $('rtmAsideNote');
    if (!note) return;
    if (!kept && !back) { note.hidden = true; return; }
    $('rtmAsideText').textContent = back
      ? `“${back.title}” is back${kept ? `, and the text it replaced, “${kept.title}”, was put aside.` : '.'}`
      : `Your earlier text, “${kept.title}”, was put aside.`;
    $('rtmBringBack').hidden = !kept;
    note.hidden = false;
  }

  /** One of the texts put aside, the i-th from the latest, back in the text; the one it replaces put aside in turn. */
  function bringBack(i) {
    const entry = aside[i];
    $('rtmExample').value = '';
    if (!entry) return;
    aside.splice(i, 1);
    saveAside();
    const kept = putAside(entry.text);
    renderExamples();
    state.text = entry.text;
    state.modelName = null;
    $('rtmText').value = entry.text;
    renderHighlight();
    $('rtmExampleAbout').hidden = true;
    state.result = null;
    state.verify = null;
    anotherModel();
    renderBeside();
    showAside(kept, entry);
    // Compared again with what it was opened as, where that came with it.
    setOpened(entry.opened || { text: entry.text, kind: 'back', name: entry.title });
    saveState();
    compile();
  }

  /* ---------------------------------------------------------------------
     What has changed since the text was opened
     --------------------------------------------------------------------- */
  /*
    THE TEXT AS OPENED -- from a file, as an example, the built-in model, the
    model PHREEQC wrote -- kept, and a line under the text saying how much
    has changed since: "1 line changed since you opened set.zip". Show lists
    each change: the line it is on now, a link to it, what it was and what
    it is, the part that changed marked. Copy the list puts the list on the
    clipboard as plain text. For skbrtm's files a change names the file and
    line it came from (RtmImport's origins), where the same change belongs
    in the set itself. It is kept between visits under a key of its own, and
    with a text put aside, so that a text brought back is compared with what
    it was opened as. The fitted values put in are a change, not a new text.
  */
  const OPENED_KEY = 'kvot-rtm-opened-v1';
  let opened = null;          // { text, kind, name, at, origins }
  let changesOpen = false;    // the list shown
  let changesNow = [];        // RtmModel.lineChanges from opened.text to the text

  function loadOpened() {
    try {
      const o = JSON.parse(localStorage.getItem(OPENED_KEY) || 'null');
      if (o && typeof o.text === 'string' && typeof o.kind === 'string') opened = o;
    } catch (e) { opened = null; }
  }

  /** The text as opened from now on, kept between visits; the list put away. */
  function setOpened(o) {
    opened = { text: o.text, kind: o.kind, name: o.name || '', at: o.at || Date.now(), origins: o.origins || null };
    changesOpen = false;
    try { localStorage.setItem(OPENED_KEY, JSON.stringify(opened)); } catch (e) { /* kept for this visit */ }
  }

  /** What the text is compared with, said two ways: after "1 line changed", and as the copied list's heading. */
  function openedSaid() {
    const { kind, name, at } = opened;
    if (kind === 'file') return [`since you opened ${name}`, `${name} as opened`];
    if (kind === 'example') return [`since you chose the example “${name}”`, `the example “${name}”`];
    if (kind === 'reset') return ['since you reset it to the built-in model', 'the built-in model'];
    if (kind === 'builtin') return ['from the built-in model', 'the built-in model'];
    if (kind === 'phreeqc') return ['since PHREEQC wrote it', 'the model PHREEQC wrote'];
    if (kind === 'back') return [`since “${name}” came back`, `“${name}” as it came back`];
    return [`since the page was opened, ${asideWhen(at)}`, `the text when the page was opened, ${asideWhen(at)}`];
  }

  /** "1 line changed", "2 lines changed, 1 added and 1 removed". */
  function changesCount(hunks) {
    let changed = 0;
    let added = 0;
    let removed = 0;
    for (const h of hunks) {
      const c = Math.min(h.was.length, h.now.length);
      changed += c;
      added += h.now.length - c;
      removed += h.was.length - c;
    }
    const lines = (k) => `${k} line${k === 1 ? '' : 's'}`;
    const parts = [];
    if (changed) parts.push(`${lines(changed)} changed`);
    if (added) parts.push(`${parts.length ? added : lines(added)} added`);
    if (removed) parts.push(`${parts.length ? removed : lines(removed)} removed`);
    return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
  }

  /** Where a change stands now: "Line 169", "Lines 12–14", "Line 30, added", "Removed after line 7". */
  function changeWhere(h) {
    if (!h.now.length) return h.at > 1 ? ['Removed after line', h.at - 1] : ['Removed at the top', 0];
    const last = h.at + h.now.length - 1;
    return [h.now.length === 1 ? `Line ${h.at}` : `Lines ${h.at}–${last}`, h.at, h.was.length ? '' : ', added'];
  }

  /** Where in skbrtm's files the lines a change replaced came from: "reaction.in, line 119"; '' where none did. */
  function changeOrigin(h) {
    if (!opened || !opened.origins || !h.was.length) return '';
    const byFile = new Map();
    for (const o of opened.origins) {
      if (o.line < h.from || o.line >= h.from + h.was.length) continue;
      if (!byFile.has(o.file)) byFile.set(o.file, []);
      byFile.get(o.file).push(o.at);
    }
    const runs = (ats) => {
      const out = [];
      for (const at of ats) {
        const last = out[out.length - 1];
        if (last && at === last[1] + 1) last[1] = at; else out.push([at, at]);
      }
      return out.map(([a, b]) => (a === b ? String(a) : `${a}–${b}`)).join(', ');
    };
    return [...byFile].map(([file, ats]) => `${file}, line${ats.length === 1 ? '' : 's'} ${runs(ats)}`).join('; ');
  }

  /** A line of a change, the part that changed marked: was the part taken out, now the part put in. */
  function changeLine(label, text, other) {
    const row = document.createElement('div');
    row.className = 'rtm-change-line';
    const tag = document.createElement('span');
    tag.className = 'rtm-change-tag';
    tag.textContent = label;
    const code = document.createElement('code');
    if (!text) {
      code.className = 'rtm-change-empty';
      code.textContent = '(an empty line)';
    } else {
      // The two lines' common start and end, the part between marked; a line with no other, all of it.
      let p = 0;
      let s = 0;
      if (other !== null) {
        while (p < text.length && p < other.length && text[p] === other[p]) p += 1;
        while (s < text.length - p && s < other.length - p && text[text.length - 1 - s] === other[other.length - 1 - s]) s += 1;
      }
      const mark = document.createElement('span');
      mark.className = label === 'was' ? 'rtm-change-out' : 'rtm-change-in';
      mark.textContent = text.slice(p, text.length - s);
      code.append(text.slice(0, p), mark, text.slice(text.length - s));
    }
    row.append(tag, code);
    return row;
  }

  function changeEl(h) {
    const el = document.createElement('div');
    el.className = 'rtm-change';
    const head = document.createElement('p');
    head.className = 'rtm-change-head';
    const [said, line, more] = changeWhere(h);
    if (line && !h.now.length) {
      head.append(`${said} `);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'rtm-line-link';
      b.dataset.onClick = 'rtm:goLine';
      b.dataset.line = String(line);
      b.textContent = String(line);
      head.append(b);
    } else if (line) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'rtm-line-link';
      b.dataset.onClick = 'rtm:goLine';
      b.dataset.line = String(line);
      b.textContent = said;
      head.append(b, more || '');
    } else head.append(said);
    const where = changeOrigin(h);
    if (where) head.append(` · ${where}`);
    el.append(head);
    const pairs = Math.min(h.was.length, h.now.length);
    h.was.forEach((t, i) => el.append(changeLine('was', t, i < pairs ? h.now[i] : null)));
    h.now.forEach((t, i) => el.append(changeLine('now', t, i < pairs ? h.was[i] : null)));
    return el;
  }

  /** The line under the text, and the list where it is shown: hidden where nothing has changed. */
  function showChanges() {
    const box = $('rtmChanges');
    if (!box) return;
    changesNow = opened ? RtmModel.lineChanges(opened.text, $('rtmText').value) : [];
    box.hidden = !changesNow.length;
    if (!changesNow.length) { changesOpen = false; return; }
    $('rtmChangesSaid').textContent = `${changesCount(changesNow)} ${openedSaid()[0]}.`;
    const toggle = $('rtmChangesToggle');
    toggle.textContent = changesOpen ? 'Hide' : 'Show';
    toggle.setAttribute('aria-expanded', String(changesOpen));
    $('rtmChangesCopy').hidden = !changesOpen;
    const list = $('rtmChangesList');
    list.hidden = !changesOpen;
    if (changesOpen) list.replaceChildren(...changesNow.map(changeEl));
  }

  /** The list as plain text on the clipboard, for a note or a report. */
  async function copyChanges() {
    if (!changesNow.length) return;
    const out = [`Changes to the model text from ${openedSaid()[1]}:`, ''];
    for (const h of changesNow) {
      const [said, line, more] = changeWhere(h);
      const where = changeOrigin(h);
      const at = !h.now.length && line ? `${said} ${line}` : `${said}${more || ''}`;
      out.push(where ? `${at} (${where})` : at);
      for (const t of h.was) out.push(`  was: ${t}`);
      for (const t of h.now) out.push(`  now: ${t}`);
      out.push('');
    }
    const text = out.join('\n');
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.append(ta);
      ta.select();
      try { copied = document.execCommand('copy'); } catch (err) { copied = false; }
      ta.remove();
    }
    if (copied) setStatus(`The list of changes is on the clipboard: ${changesCount(changesNow)}.`, 'ok');
    else setStatus('The list of changes could not be put on the clipboard: the browser would not allow it.', 'warn');
  }

  /* ---------------------------------------------------------------------
     Files
     --------------------------------------------------------------------- */
  /** The name Save… offers: the one the text was saved under or opened from, else its title's, else model.rtm. */
  function modelFileName() {
    if (state.modelName) return state.modelName;
    const title = modelAbout(state.text).title;
    const clean = title ? title.replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) : '';
    return `${clean || 'model'}.rtm`;
  }

  async function saveFile() {
    const saved = await saveBlob(new Blob([state.text], { type: 'text/plain' }), modelFileName());
    if (saved && saved.asked) {
      state.modelName = saved.name;
      saveState();
      setStatus(`Saved as ${saved.name}.`, 'ok');
    }
  }

  /*
    Open… takes a model text, or skbrtm's databases: any of reaction.in,
    solutions.in, diffusion.in, sourceterm*.in and doserate*.in, and the
    Python script that runs them, which says which of them are read, in what
    order, and for how long. Those are converted to one model text by
    RtmImport, which writes at the top of it everything skbrtm itself would
    read differently. A .zip of any of these opens as its folder would.
  */
  async function fileChosen(ev) {
    const picked = Array.from((ev.target.files) || []);
    ev.target.value = '';
    if (!picked.length) return;
    let read;
    try {
      read = await readFiles([], picked, true);
    } catch (e) {
      setStatus(e.message, 'error');
      return;
    }
    landFiles(read);
  }

  /*
    DROPPED ON THE PAGE. A model text, skbrtm's files, the folder they are in
    -- an skbrtm example's own folder, script and databases/ together -- or a
    .zip of either, opens as Open... would open it. What is read is what
    either can use; a folder's or a .zip's notes, plots and results are
    passed over, and a folder is not followed without end.
  */
  const READABLE = /\.(rtm|txt|in|py)$/i;
  const ZIPPED = /\.zip$/i;
  const DROP_MAX_FILES = 200;
  const DROP_MAX_BYTES = 20 * 1024 * 1024;
  const NOTHING_TO_OPEN = 'Nothing here can be opened: a model text (.rtm, .txt), or skbrtm\'s databases and script '
    + '(.in, .py), the folder they are in, or a .zip of either.';

  /*
    The files under what was dropped or chosen, as {name, text}: a folder's,
    and a .zip's, by their paths in it. A file chosen by name with Open… is
    read whatever it is called; in a folder or a .zip, only what the page can
    use, and not what a Mac adds to a .zip it makes -- under __MACOSX/, a ._
    copy of each file's attributes named as the file is, which holds no text.
    At most DROP_MAX_FILES files and DROP_MAX_BYTES in all, a .zip's entry
    counted at the size it says it is before it is read out, and at the size
    it was once it has been.
  */
  async function readFiles(entries, plain, chosen) {
    const out = [];
    let bytes = 0;
    let skipped = 0;
    const add = async (name, size, read) => {
      if (out.length >= DROP_MAX_FILES || bytes + size > DROP_MAX_BYTES) { skipped++; return; }
      const text = await read();
      const used = Math.max(size, text.length);
      if (bytes + used > DROP_MAX_BYTES) { skipped++; return; }
      bytes += used;
      out.push({ name, text });
    };
    const unzip = async (file, folder) => {
      if (typeof JSZip === 'undefined') {
        throw new Error(`${file.name} is a .zip, and what reads one did not load with the page: unzip it, and open or drop `
          + 'what it holds.');
      }
      let zip;
      try {
        zip = await JSZip.loadAsync(file);
      } catch (e) {
        throw new Error(`${file.name} could not be read as a .zip: ${e.message}`);
      }
      for (const entry of Object.values(zip.files)) {
        const base = entry.name.split('/').pop();
        if (entry.dir || /(^|\/)__MACOSX\//.test(entry.name) || base.startsWith('._') || !READABLE.test(base)) continue;
        // eslint-disable-next-line no-underscore-dangle
        const said = entry._data && Number.isFinite(entry._data.uncompressedSize) ? entry._data.uncompressedSize : 0;
        // eslint-disable-next-line no-await-in-loop
        await add(folder + entry.name, said, () => entry.async('string'));
      }
    };
    const take = async (file, name) => {
      if (ZIPPED.test(file.name)) {
        await unzip(file, name.slice(0, name.length - file.name.length));
        return;
      }
      if (!chosen && !READABLE.test(file.name)) return;
      await add(name, file.size, () => file.text());
    };
    // What was chosen or dropped, by name -- a .zip, a folder, a file -- for Save… to offer.
    const origin = (entries.find(Boolean) || {}).name || (plain[0] && plain[0].name) || '';
    if (entries.some(Boolean)) {
      const walk = async (entry, prefix, depth) => {
        if (entry.isFile) {
          const file = await new Promise((res, rej) => entry.file(res, rej));
          await take(file, prefix + entry.name);
        } else if (entry.isDirectory && depth < 6) {
          const reader = entry.createReader();
          for (;;) {
            // eslint-disable-next-line no-await-in-loop
            const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
            if (!batch.length) break;
            // eslint-disable-next-line no-await-in-loop
            for (const e of batch) await walk(e, `${prefix}${entry.name}/`, depth + 1);
          }
        }
      };
      for (const e of entries) if (e) await walk(e, '', 0);
    } else {
      for (const f of plain) await take(f, f.name);
    }
    return { files: out, skipped, origin };
  }

  function initDrop() {
    const app = document.querySelector('.rtm');
    if (!app) return;
    let depth = 0;
    const withFiles = (ev) => !!ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes('Files');
    const done = () => { depth = 0; app.classList.remove('dropping'); };
    document.addEventListener('dragenter', (ev) => {
      if (!withFiles(ev)) return;
      depth++;
      app.classList.add('dropping');
    });
    document.addEventListener('dragleave', (ev) => {
      if (!withFiles(ev)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) app.classList.remove('dropping');
    });
    // Accepting the drag everywhere also keeps a file dropped beside the app
    // from replacing the page with the file's own text.
    document.addEventListener('dragover', (ev) => {
      if (!withFiles(ev)) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'copy';
    });
    document.addEventListener('drop', (ev) => {
      if (!withFiles(ev)) return;
      ev.preventDefault();
      done();
      // The browser takes the items back once this handler returns, so they
      // are read out now and the files read later.
      const dt = ev.dataTransfer;
      const entries = Array.from(dt.items || [])
        .map((it) => (it.kind === 'file' && typeof it.webkitGetAsEntry === 'function' ? it.webkitGetAsEntry() : null));
      const plain = Array.from(dt.files || []);
      readFiles(entries, plain, false).then(landFiles,
        (e) => setStatus(`The drop could not be read: ${e.message}`, 'error'));
    });
    window.addEventListener('dragend', done);
  }

  /** What Open… or a drop read, opened; or what was not. */
  function landFiles({ files, skipped, origin }) {
    if (!files.length) {
      setStatus(NOTHING_TO_OPEN, 'warn');
      return;
    }
    openFiles(files, origin);
    if (skipped) setStatus(`${skipped} file${skipped === 1 ? ' was' : 's were'} left out: what is opened at once is `
      + `${DROP_MAX_FILES} files and 20 MB at most.`, 'warn');
  }

  /** A model text, or skbrtm's files, however they arrived: [{name, text}], and what was chosen or dropped. */
  function openFiles(files, origin = '') {
    const about = $('rtmExampleAbout');
    const skbrtm = typeof RtmImport !== 'undefined'
      && files.some((f) => /\.py$/i.test(f.name) || RtmImport.isDatabase(f.text));
    let next;
    let said = '';
    let ranIn = null;
    let from = '';
    let origins = null;
    if (skbrtm) {
      let res;
      try {
        res = RtmImport.convert(files);
      } catch (e) {
        setStatus(`These could not be opened as skbrtm databases: ${e.message}`, 'error');
        return;
      }
      next = res.text;
      ranIn = res.timeUnit;
      origins = res.origins || null;
      // Named for what was opened: the .zip or the folder, else the script, else the first database.
      from = origin || (files.find((f) => /\.py$/i.test(f.name)) || files[0]).name;
      const n = files.filter((f) => /\.py$/i.test(f.name) || RtmImport.isDatabase(f.text)).length;
      said = `Opened ${n} skbrtm file${n === 1 ? '' : 's'} as one model.`
        + (res.warnings.length ? ` ${res.warnings.length} thing${res.warnings.length === 1 ? '' : 's'} that `
          + 'skbrtm would read differently, or that needs a look, are noted at the top of the text.' : '');
    } else {
      // A model file before any other text file that came with it.
      const pick = files.find((f) => /\.rtm$/i.test(f.name)) || files[0];
      if (files.length > 1) {
        setStatus(`One model text at a time: ${pick.name} was opened, the other ${files.length - 1} were not.`, 'warn');
      }
      next = pick.text;
      from = pick.name;
    }
    const kept = putAside(next);
    setOpened({ text: next, kind: 'file', name: String(from).replace(/^.*[\\/]/, '') || 'the file', origins });
    state.modelName = `${String(from).replace(/^.*[\\/]/, '').replace(/\.[^.]*$/, '') || 'model'}.rtm`;
    state.text = next;
    about.textContent = said;
    about.hidden = !said;
    $('rtmExample').value = '';
    $('rtmText').value = state.text;
    renderHighlight();
    anotherModel();
    /*
      skbrtm counts in seconds, and so does the model made of its files; the
      script's t_span says what it ran for in a unit of its own, and the run
      is shown in that: ten years in years.
    */
    if (ranIn) {
      const sym = { seconds: 's', minutes: 'min', hours: 'h', days: 'd', years: 'a' }[ranIn];
      if (sym) state.timeIn = sym === 's' ? '' : sym;
    }
    showAside(kept);
    showTab('model');
    scheduleCompile(0);
  }

  /* ---------------------------------------------------------------------
     The full window
     --------------------------------------------------------------------- */
  /* The page without the site's header and footer (rtm.css :root.rtm-full),
     by the button at the right end of the tab bar; kept for the next visit,
     which the page's head puts in it before the first paint. */
  const FULL_KEY = 'kvot.rtm.full';

  function setFull(on) {
    document.documentElement.classList.toggle('rtm-full', !!on);
    try { localStorage.setItem(FULL_KEY, on ? '1' : '0'); } catch (e) { /* storage unavailable: for this visit only */ }
    fullState();
    // The charts follow the window and not their box, and a pane's scroll bar
    // can come or go with its new height.
    resize();
  }

  function fullState() {
    const on = document.documentElement.classList.contains('rtm-full');
    const b = $('rtmFull');
    b.setAttribute('aria-pressed', String(on));
    b.title = on ? 'Show the site\'s header and footer again' : 'Full window: the page without the site\'s header and footer';
  }

  /* ---------------------------------------------------------------------
     PHREEQC: a water into the model, and a run back out

     PHREEQC is the USGS's IPhreeqc compiled to WebAssembly (vendors/phreeqc),
     run in a worker of its own that is started the first time PHREEQC is
     asked anything: its 2.4 MB are fetched only by someone who uses
     it, and a long look at a run leaves the page and the solver's worker
     free. A page opened from the disk cannot start a worker, so there PHREEQC
     is loaded as scripts and runs on the page itself, as the solver does.
     The chemistry of the hand-off is rtm-phreeqc.js; this keeps its state
     and shows what it did.
     --------------------------------------------------------------------- */
  const PQ_KEY = 'kvot-rtm-phreeqc-v1';
  const PQ_WORKER_URL = 'resources/js/rtm-phreeqc-worker.js?v=20261114a';
  const PQ_SCRIPTS = [
    'vendors/phreeqc/phreeqc.js?v=20261109l',
    PHREEQC_DAT_SRC,
    'resources/js/rtm-phreeqc.js?v=20261110a',
    'resources/js/rtm-phreeqc-engine.js?v=20261114a',
  ];
  /** "An example water": round numbers, nobody's sample. */
  const PQ_EXAMPLE = `# An illustrative granitic groundwater: round numbers, not a sample.
# Chloride takes the charge balance. Anything PHREEQC can do to a water may
# follow the SOLUTION -- EQUILIBRIUM_PHASES, REACTION, MIX -- and the water as
# PHREEQC leaves it is what becomes the model.
SOLUTION 1
  temp   15
  pH     7.4
  pe     -3
  units  mmol/kgw
  Na     50
  K      0.5
  Ca     15
  Mg     5
  Cl     85 charge
  S(6)   2
  C(4)   2.5
  Fe(2)  0.02
  Si     0.2
END
`;
  /** How the relations written are kept during the run: see pq:hold. */
  const PQ_HOLDS = ['exact', 'pairs', 'start'];
  /** Whether their activity coefficients follow the ionic strength: see pq:activity. */
  const PQ_ACTS = ['follow', 'fixed'];
  const pq = {
    water: '', db: 'builtin', floor: '1e-20', act: 'follow', eq: 'exact', minerals: false, redox: true, relax: '1e3', diff: 'none', D: '2e-9',
    times: '100', cells: '', phases: '', fill: false, logT: true, open: false, cell: 0, mode: 'time', at: -1,
    opened: new Map(),       // databases opened this visit, name -> text; never stored
    missingDb: null,         // a database chosen on an earlier visit and not opened on this one
    view: null,              // the last look at a run through PHREEQC
    // Inverse models: between which waters, with which phases, to what uncertainty; and what PHREEQC found.
    inv: { from: '', fromAt: 'start', to: '', toAt: 'end', phases: '', u: '0.05', range: true, minimal: true },
    invResult: null,
    // A batch over a table of waters: the input, the rows asked for, the solids tried in turn, the column whose lowest
    // is kept, and the values drawn, how many draws and from what seed (kept); the table and what it found (the visit's).
    batch: { text: '', rows: '', solids: '', lowest: '', uncertain: '', draws: '', seed: '', against: '', mapX: '', mapY: '' },
    batchTable: null,
    batchResult: null,
    batchRunning: false,
    batchStop: false,
    batchStarter: null,      // the input the page started for a table, while it is untouched
    batchLook: null,         // one water of the batch run again, what PHREEQC printed of it
    batchKept: null,         // a batch kept, to draw the next ones beside (the visit's)
    busy: false,
    worker: null,
    kind: 'none',            // 'worker' | 'inline' once started
    inline: null,
    pending: new Map(),
    nextId: 1,
  };
  /** Finished runs, counted, so that a look at an earlier one can say it is that. */
  let runNumber = 0;

  function pqSave() {
    try {
      localStorage.setItem(PQ_KEY, JSON.stringify({
        water: pq.water, db: pq.db, floor: pq.floor, act: pq.act, eq: pq.eq, minerals: pq.minerals, redox: pq.redox, relax: pq.relax, diff: pq.diff,
        D: pq.D, times: pq.times, cells: pq.cells, phases: pq.phases, fill: pq.fill, logT: pq.logT,
        open: pq.open, inv: pq.inv, batch: pq.batch,
      }));
    } catch (e) { /* storage unavailable: for this visit only */ }
  }

  function pqLoad() {
    try {
      const s = JSON.parse(localStorage.getItem(PQ_KEY) || 'null');
      if (!s) return;
      for (const k of ['water', 'floor', 'relax', 'diff', 'D', 'times', 'cells', 'phases']) {
        if (typeof s[k] === 'string') pq[k] = s[k];
      }
      for (const k of ['fill', 'logT', 'open', 'minerals', 'redox']) if (typeof s[k] === 'boolean') pq[k] = s[k];
      if (s.batch && typeof s.batch === 'object') {
        for (const k of ['text', 'rows', 'solids', 'lowest', 'uncertain', 'draws', 'seed', 'against', 'mapX', 'mapY']) if (typeof s.batch[k] === 'string') pq.batch[k] = s.batch[k];
      }
      if (s.inv && typeof s.inv === 'object') {
        for (const k of ['from', 'fromAt', 'to', 'toAt', 'phases', 'u']) if (typeof s.inv[k] === 'string') pq.inv[k] = s.inv[k];
        for (const k of ['range', 'minimal']) if (typeof s.inv[k] === 'boolean') pq.inv[k] = s.inv[k];
      }
      if (PQ_HOLDS.includes(s.eq)) pq.eq = s.eq;
      if (PQ_ACTS.includes(s.act)) pq.act = s.act;
      else if (typeof s.hold === 'boolean') pq.eq = s.hold ? 'exact' : 'start';
      // A database's text is not kept between visits: one opened last time is
      // named, and phreeqc.dat used until it is opened again.
      if (typeof s.db === 'string' && s.db !== 'builtin') pq.missingDb = s.db;
    } catch (e) { /* a corrupt entry: start fresh */ }
  }

  function pqWriteControls() {
    $('rtmPqWater').value = pq.water;
    $('rtmPqFloor').value = pq.floor;
    $('rtmPqAct').value = pq.act;
    $('rtmPqHold').value = pq.eq;
    $('rtmPqMinerals').checked = pq.minerals;
    $('rtmPqRedox').checked = pq.redox;
    $('rtmPqRelax').value = pq.relax;
    $('rtmPqDiff').value = pq.diff;
    $('rtmPqD').value = pq.D;
    $('rtmPqTimes').value = pq.times;
    $('rtmPqCells').value = pq.cells;
    $('rtmPqPhases').value = pq.phases;
    $('rtmPqFill').checked = pq.fill;
    $('rtmPqLogT').checked = pq.logT;
    pqDependents();
    pqRenderDatabases();
    pqShowPanel(pq.open);
    pqBatchRender();
  }

  /** What one setting decides about another being asked at all. */
  function pqDependents() {
    $('rtmPqDWrap').hidden = pq.diff !== 'one';
    $('rtmPqRelaxWrap').hidden = pq.eq !== 'pairs';
    // A mineral is held at saturation only where the relations are held, and
    // so is the electron.
    $('rtmPqMinerals').disabled = pq.eq !== 'exact';
    $('rtmPqRedox').disabled = pq.eq !== 'exact';
  }

  function pqReadControls() {
    pq.water = $('rtmPqWater').value;
    pq.floor = $('rtmPqFloor').value.trim();
    pq.act = PQ_ACTS.includes($('rtmPqAct').value) ? $('rtmPqAct').value : 'follow';
    pq.eq = PQ_HOLDS.includes($('rtmPqHold').value) ? $('rtmPqHold').value : 'exact';
    pq.minerals = $('rtmPqMinerals').checked;
    pq.redox = $('rtmPqRedox').checked;
    pq.relax = $('rtmPqRelax').value.trim();
    pq.diff = $('rtmPqDiff').value;
    pq.D = $('rtmPqD').value.trim();
    pq.times = $('rtmPqTimes').value.trim();
    pq.cells = $('rtmPqCells').value.trim();
    pq.phases = $('rtmPqPhases').value.trim();
    pq.fill = $('rtmPqFill').checked;
    pq.logT = $('rtmPqLogT').checked;
    pqDependents();
    pqSave();
  }

  /**
   * A number as it is typed: one comma is a decimal mark, spaces are dropped,
   * e or E starts an exponent. Null, and the field marked, when it is none.
   */
  function pqNumber(el, opts = {}) {
    const raw = String(el.value).trim().replace(/\s+/g, '');
    const text = (raw.match(/,/g) || []).length === 1 && !raw.includes('.') ? raw.replace(',', '.') : raw;
    const v = /^(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(text) ? Number(text) : NaN;
    const ok = Number.isFinite(v) && (!opts.positive || v > 0) && (!opts.integer || Number.isInteger(v));
    el.setAttribute('aria-invalid', ok ? 'false' : 'true');
    return ok ? v : null;
  }

  /** "0, 5, 10-19" as cell numbers; null when it is not that. */
  function pqCellList(text) {
    const out = [];
    for (const part of String(text).split(/[,;\s]+/).filter(Boolean)) {
      const m = /^(\d+)(?:-(\d+))?$/.exec(part);
      if (!m) return null;
      const a = Number(m[1]);
      const b = m[2] === undefined ? a : Number(m[2]);
      if (b < a || b - a > 100000) return null;
      for (let c = a; c <= b; c++) out.push(c);
    }
    return out.length ? out : null;
  }

  const pqNum = (x) => (x === 0 ? '0' : !Number.isFinite(x) ? String(x)
    : Math.abs(x) >= 1e-3 && Math.abs(x) < 1e4 ? String(Number(x.toPrecision(3))) : x.toExponential(2));

  function pqShowPanel(open) {
    pq.open = !!open;
    $('rtmPq').hidden = !pq.open;
    $('rtmPqToggle').setAttribute('aria-expanded', String(pq.open));
    infoRefresh();
  }

  /* ---- the database: phreeqc.dat, or one opened this visit ---- */
  function pqRenderDatabases() {
    const html = ['<option value="builtin">phreeqc.dat, which comes with the page</option>']
      .concat([...pq.opened.keys()].map((n) => `<option value="${esc(n)}">${esc(n)}</option>`))
      .concat('<option value="__open">Open a database…</option>')
      .join('');
    for (const id of ['rtmPqDb', 'rtmPqViewDb', 'rtmPqBatchDb']) {
      const sel = $(id);
      sel.innerHTML = html;
      sel.value = pq.opened.has(pq.db) ? pq.db : 'builtin';
    }
  }

  /** The database to send: null for the built-in phreeqc.dat. */
  function pqDatabase() {
    return pq.db !== 'builtin' && pq.opened.has(pq.db) ? { name: pq.db, text: pq.opened.get(pq.db) } : null;
  }

  /** A file's text: UTF-8 when it is that, else Latin-1, which PHREEQC's own files are. */
  async function pqFileText(file) {
    const bytes = await file.arrayBuffer();
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (e) {
      return new TextDecoder('windows-1252').decode(bytes);
    }
  }

  async function pqDatabaseChosen(ev) {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    const text = await pqFileText(file);
    pqBusy(true, `Reading ${file.name} into PHREEQC…`);
    try {
      const reply = await pqRequest({ type: 'load', database: { name: file.name, text } });
      pq.opened.set(file.name, text);
      pq.db = file.name;
      pq.missingDb = null;
      pqRenderDatabases();
      pqSave();
      setStatus(`${file.name} is loaded: ${reply.species.toLocaleString()} aqueous species and `
        + `${reply.phases.toLocaleString()} phases, for this visit. PHREEQC ${reply.version}.`, 'ok');
    } catch (e) {
      pqRenderDatabases();
      setStatus(`PHREEQC cannot read ${file.name} as a database: ${e.message}`, 'error');
    } finally {
      pqBusy(false);
    }
  }

  /* ---- PHREEQC itself: its worker, or the page ---- */
  function pqStart() {
    if (pq.worker || pq.kind === 'inline') return;
    if (typeof Worker === 'undefined' || location.protocol === 'file:') { pq.kind = 'inline'; return; }
    try {
      pq.worker = new Worker(PQ_WORKER_URL);
      pq.kind = 'worker';
      pq.worker.onmessage = (ev) => pqReceive(ev.data);
      pq.worker.onerror = (ev) => {
        // A worker that could not load its scripts. Whatever was waiting on it
        // is told so; from here on PHREEQC runs on the page.
        const w = pq.worker;
        pq.worker = null;
        pq.kind = 'inline';
        pqWorkerFailed(w, (ev && ev.message) || 'its scripts did not load');
      };
    } catch (e) {
      pq.worker = null;
      pq.kind = 'inline';
    }
  }

  /** Each request a worker that stopped had in hand is told so. */
  function pqWorkerFailed(w, why) {
    for (const [id, entry] of pq.pending) {
      if (entry.worker === w) { pq.pending.delete(id); entry.reject(new Error(`PHREEQC's worker stopped: ${why}`)); }
    }
  }

  /*
    MORE PHREEQCS AT ONCE, for a batch: PHREEQC's own worker and copies of it,
    as many as the cores the browser reports less one for the page, at most
    eight -- two where it says it has under 4 GB -- and no more than the batch
    has parts. The copies are started for the batch and ended with it. Each
    takes the next part when it is done with one, the database sent with every
    part, so that a part runs as it would alone.
  */
  const PQ_LANES_MAX = 8;
  function pqLanes() {
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    const cores = nav.hardwareConcurrency || 2;
    return Math.max(1, Math.min(nav.deviceMemory && nav.deviceMemory < 4 ? 2 : PQ_LANES_MAX, cores - 1));
  }
  /** A copy of PHREEQC's worker, its replies read as the worker's are; null where one cannot be started. */
  function pqExtraWorker() {
    try {
      const w = new Worker(PQ_WORKER_URL);
      w.onmessage = (ev) => pqReceive(ev.data);
      w.onerror = (ev) => pqWorkerFailed(w, (ev && ev.message) || 'its scripts did not load');
      return w;
    } catch (e) {
      return null;
    }
  }
  /** A request to the worker given. */
  function pqRequestOn(worker, message, onProgress) {
    const id = pq.nextId++;
    return new Promise((resolve, reject) => {
      pq.pending.set(id, { resolve, reject, onProgress, worker });
      worker.postMessage({ ...message, id });
    });
  }

  function pqReceive(msg) {
    const entry = pq.pending.get(msg.id);
    if (!entry) return;
    if (msg.type === 'progress') { if (entry.onProgress) entry.onProgress(msg); return; }
    pq.pending.delete(msg.id);
    if (msg.type === 'error') entry.reject(new Error(msg.error));
    else entry.resolve(msg);
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`${src.split('?')[0]} could not be loaded`));
      document.head.appendChild(s);
    });
  }

  async function pqInline() {
    if (pq.inline) return pq.inline;
    for (const src of PQ_SCRIPTS) await loadScript(src);
    pq.inline = self.RtmPhreeqcEngine.handler(self.createPhreeqc, { builtin: self.PHREEQC_DAT });
    return pq.inline;
  }

  async function pqRequest(message, onProgress) {
    pqStart();
    const id = pq.nextId++;
    const full = { ...message, id };
    if (pq.worker) {
      const worker = pq.worker;
      return new Promise((resolve, reject) => {
        pq.pending.set(id, { resolve, reject, onProgress, worker });
        worker.postMessage(full);
      });
    }
    const handle = await pqInline();
    // On the page, PHREEQC holds it until it is done: the words above first.
    await repaint();
    return new Promise((resolve, reject) => {
      pq.pending.set(id, { resolve, reject, onProgress });
      handle(full, (reply) => pqReceive(reply));
    });
  }

  function pqBusy(on, text) {
    pq.busy = on;
    $('rtmPqWrite').disabled = on;
    $('rtmPqLook').disabled = on;
    $('rtmPqInvGo').disabled = on;
    // The batch's own button is its Stop while it runs.
    $('rtmPqBatchGo').disabled = on && !pq.batchRunning;
    if (on && text) {
      const first = pq.kind === 'none' || (pq.kind === 'inline' && !pq.inline)
        ? ' PHREEQC is fetched the first time it is used: 2.4 MB, 0.8 MB as it travels.' : '';
      setStatus(`${text}${first}`);
    }
  }

  /* ---- a water into the model ---- */
  function pqReport(html) {
    const el = $('rtmPqReport');
    el.innerHTML = html;
    el.hidden = !html;
  }

  function pqWaterReport(reply) {
    const r = reply.report;
    const out = [];
    out.push(`<p>Written into the text below: <strong>${r.species} species</strong> and <strong>${r.equilibria} `
      + `equilibria</strong>, the water at ${pqNum(r.temperature)} °C and ionic strength `
      + `${pqNum(r.ionicStrength)} mol/kgw, pH ${r.pH.toFixed(3)} as PHREEQC has it; from ${esc(reply.database)}, `
      + `PHREEQC ${esc(reply.version)}.</p>`);
    // The column of the input's TRANSPORT (or ADVECTION): what the water above starts every cell as.
    if (r.transport) {
      const c = r.transport;
      const end = (kind, s, where) => (kind === 'robin' ? `SOLUTION ${s} flows in at the ${where}`
        : kind === 'dirichlet' ? `SOLUTION ${s} holds the ${where} end` : kind === 'free'
          ? `the water leaves at the ${where}` : `the ${where} end is closed`);
      out.push(`<p>A column, the input's <code>${esc(c.kind)}</code>: ${c.cells} cells, ${pqNum(c.length)} m, `
        + (c.velocity ? `the water crossing a cell in ${pqNum(c.timeStep)} s (${pqNum(Math.abs(c.velocity))} m/s) for `
          + `${c.shifts} shifts` : `diffusing for ${c.shifts} periods of ${pqNum(c.timeStep)} s`)
        + `${c.dispersivity ? `, dispersivity ${pqNum(c.dispersivity)} m` : ''}`
        + `${c.correction !== 1 ? ` (times ${pqNum(c.correction)}, <code>-correct_disp</code>)` : ''}, `
        + `${c.multiD ? 'each species diffusing at its own coefficient' : `diffusion coefficient ${pqNum(c.diffusion)} m²/s`}; `
        + `${end(c.left, c.leftSolution, 'left')}, ${end(c.right, c.rightSolution, 'right')}. `
        + (c.zones && c.zones.length > 1 ? `Its cells start as PHREEQC equilibrates them before the first shift, in `
          + `${c.zones.length} zones — ${c.zones.map((z) => `${z.cells[0]}-${z.cells[1]}`).join(', ')} — the first as the `
          + 'water above, the others in <code>&lt;INITIAL&gt;</code>.</p>'
          : 'Every cell starts as the water above, cell 1 as PHREEQC equilibrates it before the first shift.</p>'));
      // Multicomponent diffusion: each species' Dw times the porosity to the n, the ions coupled, down their activities.
      if (c.multiD) {
        const md = c.multiD;
        const none = md.withoutDw.length;
        out.push(`<p>Multicomponent diffusion, <code>-multi_D</code>: each species at its <code>Dw</code> in the database at `
          + `${pqNum(r.temperature)} °C${none ? ` (${pqNum(md.defaultDw)} m²/s for the ${none} without one)` : ''} times the `
          + `porosity ${pqNum(md.porosity)} to the ${pqNum(md.n)}, its <code>D</code>; the ions coupled so that no current `
          + 'flows, <code>DIFFUSION = nernst-planck</code>, and each '
          + (md.gradient === 'activity' ? 'down its activity, <code>DIFFUSION_GRADIENT = activity</code>, as PHREEQC has them.'
            : md.implicit ? 'down its concentration, as PHREEQC\'s <code>-implicit</code> scheme takes it.'
              : 'down its concentration, the activity coefficients folded into the log K.') + '</p>');
      }
      // Stagnant cells: a rock matrix of one layer, exchanging as PHREEQC's first order does.
      if (c.stagnant) {
        const st = c.stagnant;
        const apart = st.zones.filter((z) => !z.same);
        out.push(`<p>Stagnant water behind every cell, <code>-stagnant 1 ${pqNum(st.alpha)} ${pqNum(st.thm)} `
          + `${pqNum(st.thim)}</code>: exchanged with the cell's at α = ${pqNum(st.alpha)} /s, as PHREEQC does, by a rock `
          + `matrix of one layer of porosity ${pqNum(st.thim)} (<code>MATRIX_CELLS = 1</code>, every species' `
          + `<code>Dm</code> α/2). ${apart.length ? `It starts as PHREEQC equilibrates it, behind cells `
            + `${apart.map((z) => `${z.cells[0]}-${z.cells[1]}`).join(', ')} in <code>&lt;INITIAL&gt;</code> (<code>matrix</code>)`
            + `${apart.length < st.zones.length ? ' and elsewhere as the water above' : ''}.` : 'It starts as the water above.'}</p>`);
      }
      if (c.elsewhere && c.elsewhere.length) {
        out.push(`<p>Cell 1's water has none of ${c.elsewhere.map((sp) => `<code>${esc(sp)}</code>`).join(', ')}, which `
          + 'another water of the column brings: written at the trace cell 1 takes of that water, with the database\'s '
          + 'log K.</p>');
      }
      if (c.after) {
        out.push('<p class="warn">The input goes on after this column; what it does then is not carried.</p>');
      }
    }
    if (r.withTemperature) {
      const who = r.withTemperature === r.relations ? 'Every relation’s'
        : `${r.withTemperature} of the ${r.relations} relations’`;
      out.push(`<p>${who} log K goes with temperature as the database’s does, by its <code>delta_h</code> or its `
        + `analytic expression: <code>TEMPERATURE = ${pqNum(r.temperature)}</code> may be changed, or made to follow `
        + 'the cells or the clock, and the relations follow it.</p>');
    }
    const c = reply.check;
    if (c && c.error) {
      out.push(`<p class="error">rtm.html does not compile the text it was given: ${esc(c.error)}</p>`);
    } else if (c) {
      const good = c.converged && c.worst < 1e-6;
      // From what the text holds: the database's constants and the page's
      // own activity coefficients, or conditional constants alone.
      const from = r.activity ? 'from the database\'s constants and its own activity coefficients'
        : 'from the conditional constants alone';
      out.push(`<p${good ? '' : ' class="warn"'}>rtm.html's own speciation, ${from}, `
        + `${c.converged ? 'lands on' : 'does not converge to'} PHREEQC's molalities`
        + `${c.converged ? ` to ${c.worst.toExponential(1)}` : ''}.</p>`);
      if (r.activity && r.activity.kind === 'sit') {
        const np = r.activity.sitPairs;
        out.push(`<p>The activity coefficients are SIT's, as PHREEQC's are with this database: <code>ACTIVITY = sit</code> `
          + `and, in <code>&lt;SIT&gt;</code>, ${np} of its interaction coefficient${np === 1 ? '' : 's'} between the `
          + `species written, at ${pqNum(r.activity.temperature)} °C.</p>`);
      }
      if (r.activity && r.activity.kind === 'llnl') {
        out.push('<p>The activity coefficients are LLNL’s, as PHREEQC’s are with this database: <code>ACTIVITY = llnl</code>, '
          + 'each ion’s B-dot form with the database’s <code>-llnl_gamma</code> as <code>a=</code>, CO2 and its like by '
          + 'Drummond’s formula, and A, B and B-dot from its tables in <code>&lt;LLNL&gt;</code>.</p>');
      }
      if (r.pressure && r.pressure.atm > 0 && Math.abs(r.pressure.atm - 1) > 1e-12) {
        const pr = r.pressure;
        out.push(`<p>The water is at ${pqNum(pr.atm)} atm${pr.vapour ? ', its vapour pressure times a(H2O)' : ''}, written as `
          + '<code>PRESSURE</code>'
          + (pr.volumes ? `: PHREEQC corrects each log K for the pressure with the reaction's molar volumes, and so does the `
            + `model with the database's <code>-Vm</code> in <code>&lt;VOLUMES&gt;</code> (${pr.volumes}), each going with `
            + 'the ionic strength; the log K are written at one atmosphere.</p>' : '.</p>'));
      }
      if (r.conductance) {
        out.push(`<p>The water's specific conductance, density and viscosity are worked out as PHREEQC works them out, `
          + `from the solutes' <code>-dw</code> (${r.conductance.dw} of them), <code>-viscosity</code> and gram formula `
          + `weights in <code>&lt;CONDUCTANCE&gt;</code>${r.conductance.volumes ? ' and their molar volumes in '
            + '<code>&lt;VOLUMES&gt;</code>' : ''}: the quantities SC, rho and viscos, and a USSL diagram on the `
          + 'Composition tab.</p>');
      }
      if (r.activity && r.activity.kind === 'pitzer') {
        const np = r.activity.pitzer;
        out.push(`<p>The activity coefficients are Pitzer's, as PHREEQC's are with this database: <code>ACTIVITY = pitzer</code> `
          + `and, in <code>&lt;PITZER&gt;</code>, ${np} of its parameter${np === 1 ? '' : 's'} between the species `
          + 'written, each with its terms in the temperature.</p>');
      }
      if (r.minerals && r.minerals.length) {
        // An alternative reaction holds its phase's SI; dissolve_only, precipitate_only and force_equality bound it.
        out.push(`<p>Kept at saturation: ${r.minerals.map((mn) => `${esc(mn.as)} (${pqNum(mn.amount)} mol/kgw`
          + `${mn.alt ? `, ${esc(mn.alt)} added or taken away to hold ${esc(mn.phase)} at SI ${pqNum(mn.si)}`
            : mn.si ? `, SI ${pqNum(mn.si)}` : ''}`
          + `${mn.only ? `, ${mn.only}_only` : ''}${mn.forced ? ', force_equality' : ''})`).join(', ')}.</p>`);
      }
      if (r.phasesSkipped && r.phasesSkipped.length) {
        out.push(`<p class="warn">Not carried: ${r.phasesSkipped.map((ps) => `${esc(ps.name)}, ${esc(ps.why)}`).join('; ')}.</p>`);
      }
      if (r.exchange) {
        out.push(`<p>On the exchanger ${r.exchange.exchangers.map(esc).join(', ')}: ${r.exchange.species
          .map((e) => `${esc(e.as)} (${pqNum(e.amount)} mol/kgw)`).join(', ')}, held on it by Gaines–Thomas.</p>`);
        for (const x of r.exchange.per || []) {
          out.push(`<p>The sites of ${esc(x.exchanger)} go with ${esc(x.mineral)}, ${pqNum(x.ratio)} of ${esc(x.as)} to each `
            + `mole of it (PHREEQC's ${esc(x.kind)}): ${pqNum(x.sites)} sites a mole, coming and going with it.</p>`);
        }
        for (const x of r.exchange.linked || []) {
          out.push(`<p class="warn">In PHREEQC the capacity of ${esc(x.exchanger)} goes with ${esc(x.phase)}, `
            + `${pqNum(x.ratio)} to each mole of it; here it is held at what PHREEQC loaded at the start: ${esc(x.why)}.</p>`);
        }
      }
      if (r.exchangeSkipped && r.exchangeSkipped.length) {
        out.push(`<p class="warn">Not carried from the exchanger: ${r.exchangeSkipped
          .map((x) => `${esc(x.name)}, ${esc(x.why)}`).join('; ')}.</p>`);
      }
      if (r.surface) {
        const pots = r.surface.potentials || [];
        out.push(`<p>On the surface, the sites ${r.surface.sites.map(esc).join(', ')}: ${r.surface.species
          .map((e) => `${esc(e.as)} (${pqNum(e.amount)} mol/kgw)`).join(', ')}, each with its fraction of the sites `
          + 'for its activity, '
          + ((r.surface.per || []).length ? `the sites of ${r.surface.per.map((x) => `${esc(x.site)} ${pqNum(x.ratio)} to each `
            + `mole of ${esc(x.mineral)}`).join(' and ')}, going with it, ` : '')
          + (pots.some((pp) => pp.cd) ? `by CD-MUSIC: ${pots.filter((pp) => !pp.plane).map((pp) => `the planes 0, 1 and 2 of `
            + `${esc(pp.surface)}, ${pots.filter((x) => x.surface === pp.surface).map((x) => `${esc(x.name)} at `
              + `${pqNum(x.psi * 1e3)} mV`).join(', ')}, with the capacitances ${pqNum(pp.cap[0])} and ${pqNum(pp.cap[1])} `
            + 'F/m² between them').join('; ')}.</p>`
            : pots.length ? `with the diffuse double layer: ${pots.map((pp) => `${esc(pp.name)}, the potential of `
            + `${esc(pp.surface)} (${pp.phase ? `${pqNum(pp.area)} m² to each mole of ${esc(pp.phase)}`
              : `${pqNum(pp.area)} m² per gram, ${pqNum(pp.grams)} g per kgw`}), at `
            + `${pqNum(pp.psi * 1e3)} mV`).join('; ')}.</p>` : 'without electrostatics as PHREEQC\'s -no_edl.</p>'));
      }
      if (r.surfaceSkipped && r.surfaceSkipped.length) {
        out.push(`<p class="warn">Not carried from the surface: ${r.surfaceSkipped
          .map((x) => `${esc(x.name)}, ${esc(x.why)}`).join('; ')}.</p>`);
      }
      if (r.gas) {
        out.push(`<p>A gas phase ${r.gas.fixed === 'volume' ? `in a fixed volume of ${pqNum(r.gas.volume)} L per kgw`
          : `at a fixed total pressure of ${pqNum(r.gas.pressure)} atm`}: ${r.gas.species
          .map((g) => `${esc(g.as)} (${pqNum(g.amount)} mol/kgw, ${pqNum(g.pressure)} atm)`).join(', ')}, each gas's `
          + `activity its partial pressure${r.gas.fixed === 'volume' ? ', n R T/V' : ', its share of the bubble times the '
            + 'total, the bubble there only while the water holds its gases at the total between them'}.</p>`);
      }
      if (r.gasSkipped && r.gasSkipped.length) {
        out.push(`<p class="warn">Not carried from the gas phase: ${r.gasSkipped
          .map((x) => `${esc(x.name)}, ${esc(x.why)}`).join('; ')}.</p>`);
      }
      for (const ss of r.solids || []) {
        const there = ss.members.some((mb) => mb.amount > 0);
        out.push(`<p>A solid solution, ${esc(ss.name)}: ${ss.members.map((mb) => `${esc(mb.as)}${there
          ? ` (${pqNum(mb.amount)} mol/kgw)` : ''}`).join(', ')}${there ? '' : ', none of it, the water undersaturated in it'}`
          + `, each member's activity its mole fraction${ss.binary ? ` times Guggenheim's lambda, a0 ${pqNum(ss.binary.a0)} and a1 `
            + `${pqNum(ss.binary.a1)} at ${pqNum(ss.binary.tk - 273.15)} °C` : ', ideal'}.</p>`);
      }
      if (r.solidsSkipped && r.solidsSkipped.length) {
        out.push(`<p class="warn">Not carried from the solid solutions: ${r.solidsSkipped
          .map((x) => `${esc(x.name)}, ${esc(x.why)}`).join('; ')}.</p>`);
      }
      if (r.kinetics) {
        const k = r.kinetics;
        out.push(`<p>Kinetics: ${k.reactants.map((x) => `${esc(x.as)} (${pqNum(x.amount)} mol/kgw)`).join(', ')}, each `
          + 'reacting at the rate its RATES program comes to, written as a rate law in <code>&lt;REACTIONS&gt;</code> '
          + `below the program${k.phases.length ? `, the phases it reads the saturation of, ${k.phases.map(esc).join(', ')}, `
            + 'in <code>&lt;PHASES&gt;</code>' : ''}. The run goes as long as PHREEQC\'s steps, ${pqNum(k.tend)} s`
          + (k.trace ? `, from the water with ${pqNum(k.trace)} mol of the reactants in it, so that what they bring that `
            + 'it had none of is there to grow' : '') + '.</p>');
      }
      if (r.kineticsSkipped && r.kineticsSkipped.length) {
        out.push(`<p class="warn">Not carried from the kinetics: ${r.kineticsSkipped
          .map((x) => `${esc(x.name)}, ${esc(x.why)}`).join('; ')}.</p>`);
      }
      if (r.electron) {
        const e = r.electron;
        const moved = e.settled && Math.abs(e.settled.to - e.settled.from) > 1e-6;
        out.push(`<p>Redox: ${e.tied.length} species tied to the electron ${esc(e.name)} by the database's reactions `
          + `(${esc(someOf(e.tied, 8))})${e.minerals.length ? `, and ${e.minerals.map(esc).join(', ')} with them` : ''}, `
          + 'so that the couples share one pe'
          + (e.spread ? `. PHREEQC's water is out of redox equilibrium, its couples at pe ${pqNum(e.spread[0])} to `
            + `${pqNum(e.spread[1])}: the run starts where they settle on one, the electrons kept.`
            : moved ? `. The water is PHREEQC's next step, its valence states put on one pe: ${pqNum(e.settled.to)}, `
              + `where it was given ${pqNum(e.settled.from)}.` : `, PHREEQC's pe of ${pqNum(e.pe)} to start with.`)
          + (e.atNone.length ? ` ${e.atNone.length} species PHREEQC finds none of are written at none, so that they can `
            + 'arrive and form.' : '') + '</p>');
      }
      if (r.activity && r.activity.unsupported.length) {
        out.push(`<p class="warn">PHREEQC works out the activity of ${r.activity.unsupported.map(esc).join(', ')} in `
          + 'a way this page does not have; here they follow Davies, or 0.1 I if neutral.</p>');
      }
    }
    const items = [];
    if (r.dropped) {
      items.push(`${r.dropped} species below the floor left out; the largest of them is ${esc(r.droppedTop)}, at `
        + `${pqNum(r.droppedTopValue)} mol/kgw.`);
    }
    if (r.pulled) items.push(`${r.pulled} below the floor kept, because a relation kept needs them.`);
    if (r.redox.length) {
      items.push(`No redox relation for ${esc(someOf(r.redox, 8))}: each valence state keeps its own total, `
        + 'and electrons move only through the reactions you write.');
    }
    if (r.renamed.length) {
      items.push(`Renamed, since rtm.html cannot write the name as PHREEQC does: ${r.renamed.slice(0, 6)
        .map(([a, b]) => `${esc(a)} as ${esc(b)}`).join(', ')}${r.renamed.length > 6 ? ', and more' : ''}.`);
    }
    if (r.unknown.length) items.push(`Not in the database, kept with no relation: ${esc(someOf(r.unknown, 8))}.`);
    for (const s of r.skipped) items.push(`No relation for ${esc(s.species)}: it needs ${esc(s.missing.join(', '))}.`);
    for (const w of reply.warnings || []) items.push(`PHREEQC: ${esc(w.replace(/\s+/g, ' '))}`);
    if (items.length) out.push(`<ul>${items.map((x) => `<li>${x}</li>`).join('')}</ul>`);
    return out.join('');
  }

  async function pqWrite() {
    if (pq.busy) return;
    pqReadControls();
    if (!pq.water.trim()) {
      pqReport('<p class="error">Give PHREEQC a water first: a SOLUTION, as in a PHREEQC input file. '
        + '“An example water” puts one in.</p>');
      return;
    }
    const floor = pqNumber($('rtmPqFloor'));
    const relax = pq.eq === 'pairs' ? pqNumber($('rtmPqRelax'), { positive: true }) : null;
    const D = pq.diff === 'one' ? pqNumber($('rtmPqD'), { positive: true }) : null;
    if (floor === null || (pq.eq === 'pairs' && relax === null) || (pq.diff === 'one' && D === null)) {
      pqReport('<p class="error">A number in the settings is not one: the field is marked. A comma or a '
        + 'point is the decimal mark, and 1e-20 is written as here.</p>');
      return;
    }
    pqBusy(true, 'Writing the model through PHREEQC…');
    try {
      const reply = await pqRequest({
        type: 'toModel', database: pqDatabase(), water: { name: 'The water', text: pq.water },
        options: { floor, activity: pq.act === 'follow', exact: pq.eq === 'exact',
          phases: pq.minerals && pq.eq === 'exact', redox: pq.redox && pq.eq === 'exact', relax, D, dw: pq.diff === 'dw',
          date: new Date().toISOString().slice(0, 10) },
      });
      // As an example is loaded: the text replaced, the one there put aside, and said so below the panel.
      const kept = putAside(reply.text);
      setOpened({ text: reply.text, kind: 'phreeqc' });
      state.text = reply.text;
      state.modelName = null;
      $('rtmText').value = reply.text;
      renderHighlight();
      showAside(kept);
      $('rtmExample').value = '';
      $('rtmExampleAbout').hidden = true;
      state.result = null;
      state.verify = null;
      anotherModel();
      renderBeside();
      pqReport(pqWaterReport(reply));
      saveState();
      compile();
    } catch (e) {
      pqReport(`<p class="error">PHREEQC could not make a model of that water: ${esc(e.message)}</p>`);
      setStatus('PHREEQC could not make a model of that water: the panel on the Model tab says why.', 'error');
    } finally {
      pqBusy(false);
    }
  }

  /* ---- a run back out ---- */
  async function pqView() {
    if (pq.busy) return;
    pqReadControls();
    const r = state.result;
    if (!r) {
      setStatus('Run the model first: PHREEQC looks at a run that has finished.', 'warn');
      return;
    }
    const times = pqNumber($('rtmPqTimes'), { integer: true });
    if (times === null) { setStatus('Times per cell is a whole number; 0 reads every stored time.', 'error'); return; }
    let cells = null;
    if (pq.cells) {
      cells = pqCellList(pq.cells);
      if (!cells) { setStatus('Cells is a list such as 0, 5, 10-19; empty for all of them.', 'error'); return; }
    }
    const phases = pq.phases ? pq.phases.split(/[,;]/).map((s) => s.trim()).filter(Boolean) : null;
    const water = pq.fill && pq.water.trim() ? { name: 'The water', text: pq.water } : null;
    pqBusy(true, 'Looking at the run through PHREEQC…');
    setProgress(0);
    const started = Date.now();
    try {
      const reply = await pqRequest({
        type: 'view', database: pqDatabase(), water,
        // temps: each stored point's cells' temperatures, where the model's go with the cell or the time.
        run: { t: r.t, states: r.states, temps: r.temps || null, n: r.n, width: r.width, model: r.model },
        modelText: (state.ran && state.ran.text) || state.text,
        options: { times, cells, phases, siFloor: -3, unit: timeUnit().symbol },
      }, (m) => setProgress(m.total ? m.done / m.total : 0));
      // The cells' centres as the run had them, for the view against distance.
      pq.view = { ...reply, runNumber, water: !!water, centres: (r.model.centres || []).slice() };
      const shown = [...new Set(reply.table.cell)];
      if (!shown.includes(pq.cell)) pq.cell = shown[0];
      pqRenderView();
      setStatus(`PHREEQC looked at ${reply.report.waters.toLocaleString()} waters in `
        + `${((Date.now() - started) / 1000).toFixed(1)} s.`, 'ok');
    } catch (e) {
      setStatus(`PHREEQC could not look at the run: ${e.message}`, 'error');
    } finally {
      setProgress(null);
      pqBusy(false);
    }
  }

  function pqSummary(v) {
    const r = v.report;
    const where = (x) => `${r.cells > 1 ? `cell ${x.cell}, ` : ''}${x.t > 0 ? fmtTime(x.t) : 'at the start'}`;
    const tempWhy = {
      'the model text': ', as the top of the model text has it',
      'the water': ', the water’s',
      none: ': nothing said otherwise',
    }[r.temperatureFrom] || '';
    // A run whose temperature goes with the cell or the time: each water at its own.
    const tempAt = r.temperatures
      ? (r.temperatures[0] === r.temperatures[1] ? `at ${pqNum(r.temperatures[0])} °C, the run’s`
        : `each at its own temperature in the run, ${pqNum(r.temperatures[0])} to ${pqNum(r.temperatures[1])} °C`)
      : `at ${pqNum(r.temperature)} °C${tempWhy}`;
    const out = [];
    out.push(`<p>${r.waters.toLocaleString()} waters (${r.cells} cell${r.cells === 1 ? '' : 's'} × ${r.times} times) `
      + `${tempAt}, through ${esc(v.database)} and PHREEQC ${esc(v.version)}: pH `
      + `${r.pH[0].toFixed(2)} to ${r.pH[1].toFixed(2)}, ionic strength ${pqNum(r.ionicStrength[0])} to `
      + `${pqNum(r.ionicStrength[1])} mol/kgw.</p>`);
    if (r.waterError) {
      out.push(`<p class="warn">PHREEQC would not take the water in the panel on the Model tab, so nothing was `
        + `filled in from it: ${esc(r.waterError)}</p>`);
    }
    if (r.supersaturated.length) {
      out.push(`<p>Supersaturated: ${r.supersaturated.slice(0, 8).map((s) => `<strong>${esc(s.phase)}</strong>, `
        + `saturation index up to ${s.si.toFixed(2)} (${where(s)})`).join('; ')}`
        + `${r.supersaturated.length > 8 ? `; and ${r.supersaturated.length - 8} more` : ''}.</p>`);
    } else {
      out.push('<p>No phase is supersaturated anywhere in the run.</p>');
    }
    if (r.activity) {
      // The model works its activity coefficients out itself: how closely
      // they follow PHREEQC's is the question, not how far PHREEQC's moved.
      const d = r.drift[0];
      const g = r.activity.gap[0];
      const moved = d && Math.abs(d.by) > 0
        ? `moved by up to ${pqNum(Math.abs(d.by))} in log K (${esc(d.rel)}${d.t !== null ? `; ${where(d)}` : ''})`
        : 'did not move';
      if (g) {
        const big = Math.abs(g.by) > 0.02;
        out.push(`<p${big ? ' class="warn"' : ''}>The model works its activity coefficients out as the run goes `
          + `(ACTIVITY = ${esc(r.activity.kind)}). PHREEQC's ${moved}, and the model's own are within `
          + `${pqNum(Math.abs(g.by))} of PHREEQC's in log K (${esc(g.rel)}${g.t !== null ? `; ${where(g)}` : ''}).`
          + (big ? ' That is further than it should be: the database may work some activities out in a way this '
            + 'page does not, or PHREEQC counts species the model leaves out.' : '') + '</p>');
      }
    } else if (r.drift.length) {
      const d = r.drift[0];
      const big = Math.abs(d.by) > 0.02;
      out.push(`<p${big ? ' class="warn"' : ''}>The activity coefficients in the model's equilibria moved by up to `
        + `${pqNum(Math.abs(d.by))} in log K (${esc(d.rel)}${d.t !== null ? `; ${where(d)}` : ''}). `
        + (big ? 'Conditional constants made for the start are that far off by then: write the model again from a '
          + 'water nearer the run, or read what depends on them with that in mind.'
          : 'Conditional constants made for the start still hold.') + '</p>');
    }
    // The model's exchanger, against PHREEQC's loaded from the same water.
    if (r.exchange) {
      const x = r.exchange;
      if (x.error) {
        out.push(`<p class="warn">PHREEQC would not load the exchanger from the waters: ${esc(x.error)}.</p>`);
      } else {
        const big = Math.abs(x.gap) > 1e-3;
        out.push(`<p${big ? ' class="warn"' : ''}>The exchanger (${x.exchangers.map(esc).join(', ')}): loaded by PHREEQC `
          + 'from each water at the capacity the run has there, every species on it is within '
          + `${pqNum(Math.abs(x.gap))} of the run's equivalent fraction`
          + `${x.worst ? ` (${esc(x.worst)}${x.t !== null ? `; ${where(x)}` : ''})` : ''}.`
          + (big ? ' That is further than holding the relations leaves it: the water the run has may be missing '
            + 'species PHREEQC counts, or the relations are not the database\'s.' : '') + '</p>');
      }
    }
    // The model's surface, against PHREEQC's loaded from the same water.
    if (r.surface) {
      const x = r.surface;
      if (x.error) {
        out.push(`<p class="warn">PHREEQC would not load the surface from the waters: ${esc(x.error)}.</p>`);
      } else {
        const pg = x.psiGap;
        const big = Math.abs(x.gap) > 1e-3 || (pg && Math.abs(pg.by) > 1e-4);
        out.push(`<p${big ? ' class="warn"' : ''}>The surface (sites ${x.sites.map(esc).join(', ')}): loaded by PHREEQC `
          + `from each water with the sites the run has there, ${pg ? (x.cd ? 'by CD-MUSIC' : 'with its double layer')
            : 'without electrostatics'}, `
          + `every species on it is within ${pqNum(Math.abs(x.gap))} of the run's fraction of its sites`
          + `${x.worst ? ` (${esc(x.worst)}${x.t !== null ? `; ${where(x)}` : ''})` : ''}`
          + (pg ? `, and ${x.potentials.length > 1 ? 'every potential' : 'the potential'} within ${pqNum(Math.abs(pg.by) * 1e3)} mV of the run's`
            + `${pg.name ? ` (${esc(pg.name)}${pg.t !== null ? `; ${where(pg)}` : ''})` : ''}` : '') + '.'
          + (big ? ' That is further than holding the relations leaves it: the water the run has may be missing '
            + 'species PHREEQC counts, or the relations are not the database\'s.' : '') + '</p>');
      }
    }
    // The model's gases, against the pressure each water holds them at.
    if (r.gas && r.gas.compared) {
      const x = r.gas;
      const big = Math.abs(x.gap) > 1e-4;
      out.push(`<p${big ? ' class="warn"' : ''}>The gas phase (${x.species.map(esc).join(', ')}, ${x.fixed === 'volume'
        ? `in ${pqNum(x.volume)} L per kgw` : `at ${pqNum(x.pressure)} atm`}): each gas's partial pressure in the run is `
        + `within ${pqNum(Math.abs(x.gap))} in log of the pressure PHREEQC finds each water holds it at`
        + `${x.worst ? ` (${esc(x.worst)}${x.t !== null ? `; ${where(x)}` : ''})` : ''}.`
        + (big ? ' That is further than holding the relations leaves it: the water the run has may be missing species '
          + 'PHREEQC counts, or the relations are not the database\'s.' : '') + '</p>');
    }
    // The model's redox couples, against PHREEQC sharing out each element at the run's pe.
    if (r.redox) {
      const x = r.redox;
      const pe = x.pe ? (x.pe[1] - x.pe[0] < 5e-3 ? `pe ${pqNum(x.pe[0])}` : `pe ${pqNum(x.pe[0])} to ${pqNum(x.pe[1])}`)
        : 'no pe';
      if (x.error) {
        out.push(`<p class="warn">The electron ${esc(x.electron)}, ${pe} over the waters: PHREEQC would not share the `
          + `valence states out at that pe: ${esc(x.error)}.</p>`);
      } else if (!x.elements.length) {
        out.push(`<p>The electron ${esc(x.electron)}, ${pe} over the waters, which PHREEQC is given with each. No `
          + 'element the run carries has more than one valence state for it to share out.</p>');
      } else {
        const big = Math.abs(x.gap) > 1e-3;
        out.push(`<p${big ? ' class="warn"' : ''}>The electron ${esc(x.electron)}, ${pe} over the waters. Given each `
          + `water at its pe, with ${x.elements.map(esc).join(', ')} each one total, PHREEQC shares the valence states `
          + `out to within ${pqNum(Math.abs(x.gap))} of the run's, as a part of their element`
          + `${x.worst ? ` (${esc(x.worst)}${x.t !== null ? `; ${where(x)}` : ''})` : ''}.`
          + (big ? ' That is further than holding the relations leaves it: the run may be missing a valence state '
            + 'PHREEQC has, or the relations are not the database\'s.' : '') + '</p>');
      }
    }
    // The model's solid solutions, each member against x lambda in the run.
    for (const x of r.solids || []) {
      if (!x.compared) {
        out.push(`<p>The solid solution ${esc(x.name)}: the run has none of it in the waters looked at.</p>`);
        continue;
      }
      const big = Math.abs(x.gap) > 1e-4;
      out.push(`<p${big ? ' class="warn"' : ''}>The solid solution ${esc(x.name)} (${x.members.map(esc).join(', ')}): each `
        + `member's saturation index PHREEQC finds in the water is log10 of its activity in the run's solid, its mole fraction`
        + `${x.binary ? ' times lambda' : ''}, to within ${pqNum(Math.abs(x.gap))}`
        + `${x.worst ? ` (${esc(x.worst)}${x.t !== null ? `; ${where(x)}` : ''})` : ''}.`
        + (big ? ' That is further than holding the relations leaves it: the run may be missing species PHREEQC counts, or '
          + 'the relations are not the database\'s.' : '') + '</p>');
    }
    // The model's minerals, as PHREEQC sees the water around them.
    for (const mn of r.minerals || []) {
      const at = mn.present ? (mn.present[1] - mn.present[0] < 5e-5 ? `SI ${pqNum(mn.present[0])}`
        : `SI ${pqNum(mn.present[0])} to ${pqNum(mn.present[1])}`) : null;
      out.push(`<p>${esc(mn.name)}, a mineral of the model: ${at ? `where it has some, PHREEQC finds the water at ${at}` : 'the model has none of it in the waters looked at'}`
        + `${mn.absent !== null ? `${at ? '; where' : ', and where'} it has none, SI up to ${pqNum(mn.absent)}` : ''}.</p>`);
    }
    if (r.notNeutral) {
      out.push(`<p class="warn">The waters are not neutral: ${pqNum(r.notNeutral.cb)} eq/kgw at `
        + `${where(r.notNeutral)}. The model probably leaves out a counter-ion, and the ionic strength is then too `
        + `low${v.water ? '' : '; “fill in from the water” takes what the model does not carry from the water on the Model tab'}.</p>`);
    }
    if (r.noH) out.push('<p class="warn">The run has no H+, so PHREEQC set the pH by charge balance.</p>');
    if (r.failed.length) {
      out.push(`<p class="warn">PHREEQC could not calculate ${r.failed.length} of the waters; the first at `
        + `${where(r.failed[0])}: ${esc(r.failed[0].error)}</p>`);
    }
    out.push(`<p>Counted (${r.counted.length}): ${r.counted.map((c) => esc(c.name)
      + (c.as !== c.name ? ` as ${esc(c.as)}` : '')).join(', ')}.</p>`);
    if (r.skipped.length) out.push(`<p>Left out: ${r.skipped.map((s) => `${esc(s.name)}, ${esc(s.why)}`).join('; ')}.</p>`);
    if (r.unmapped.length) {
      out.push(`<p>Not in the database, so left out (${r.unmapped.length}): ${r.unmapped.slice(0, 12)
        .map((u) => `${esc(u.name)} (up to ${pqNum(u.peak)})`).join(', ')}${r.unmapped.length > 12 ? ', and more' : ''}.</p>`);
    }
    if (r.background.length) {
      out.push(`<p>From the water, held as it was: ${r.background.map(([k, x]) => `${esc(k)} ${pqNum(x)}`).join(', ')} `
        + 'mol/kgw.</p>');
    }
    if (r.unchecked.length) {
      out.push(`<p>${r.unchecked.length} of the model's equilibria could not be followed: a species in them is not in `
        + 'the database.</p>');
    }
    return out.join('');
  }

  function pqRenderView() {
    pqInvRender();
    const v = pq.view;
    const plot = $('rtmChartPq');
    $('rtmPqEmpty').hidden = !!v;
    $('rtmPqShow').hidden = !v;
    $('rtmPqSummary').hidden = !v;
    const stale = !!v && v.runNumber !== runNumber;
    $('rtmPqStale').hidden = !stale;
    if (stale) {
      $('rtmPqStale').textContent = 'This is the run before the latest one, as PHREEQC saw it. Look through '
        + 'PHREEQC again to see the new one.';
    }
    if (!v) {
      if (typeof Plotly !== 'undefined') Plotly.purge(plot);
      plot.hidden = true;
      $('rtmPqEmpty').textContent = state.result
        ? 'Look at the run through PHREEQC: the pH as an activity, the ionic strength and the saturation index '
          + 'of every phase, at each stored time.'
        : 'Run the model, then look at it through PHREEQC: the pH as an activity, the ionic strength and the '
          + 'saturation index of every phase, at each stored time.';
      return;
    }
    const cells = [...new Set(v.table.cell)];
    // Against distance needs more than one cell, and then one of the times.
    const across = cells.length > 1;
    if (!across) pq.mode = 'time';
    const times = [...new Set(v.table.t)].sort((a, b) => a - b);
    if (!(pq.at >= 0 && pq.at < times.length)) pq.at = times.length - 1;
    $('rtmPqModeWrap').hidden = !across;
    $('rtmPqMode').value = pq.mode;
    $('rtmPqCellWrap').hidden = !across || pq.mode !== 'time';
    $('rtmPqCell').innerHTML = cells.map((c) => `<option value="${c}">${c}</option>`).join('');
    $('rtmPqCell').value = String(pq.cell);
    $('rtmPqTimeWrap').hidden = pq.mode !== 'distance';
    $('rtmPqTime').innerHTML = times.map((t, k) => `<option value="${k}">${esc(t > 0 ? fmtTime(t) : 'the start')}</option>`).join('');
    $('rtmPqTime').value = String(pq.at);
    $('rtmPqLogTWrap').hidden = pq.mode !== 'time';
    $('rtmPqSummary').innerHTML = pqSummary(v);
    pqDraw();
  }

  /** The pH above, the saturation indices below, against time, for one cell. */
  function pqDraw() {
    const v = pq.view;
    const plot = $('rtmChartPq');
    if (!v || typeof Plotly === 'undefined') return;
    if (state.tab !== 'phreeqc') return;
    plot.hidden = false;
    const T = v.table;
    const distance = pq.mode === 'distance';
    const logT = pq.logT && !distance;
    const times = distance ? [...new Set(T.t)].sort((a, b) => a - b) : null;
    const at = distance ? times[Math.min(Math.max(pq.at, 0), times.length - 1)] : null;
    const rows = [];
    for (let i = 0; i < T.t.length; i++) {
      if (T.layer[i] !== 0 || T.pH[i] === null) continue;
      if (distance ? T.t[i] !== at : T.cell[i] !== pq.cell) continue;
      if (logT && !(T.t[i] > 0)) continue;
      rows.push(i);
    }
    // Against distance, each cell at its centre along the column, in order.
    if (distance) rows.sort((a, b) => T.cell[a] - T.cell[b]);
    const where = (i) => (v.centres && v.centres[T.cell[i]] !== undefined ? v.centres[T.cell[i]] : T.cell[i]);
    const x = rows.map((i) => (distance ? where(i) : showT(T.t[i])));
    const traces = [{ name: 'pH, −log a(H+)', x, y: rows.map((i) => T.pH[i]), mode: 'lines', type: 'scatter',
      yaxis: 'y', line: { width: 2 } }];
    for (const p of v.phases) {
      traces.push({ name: p, x, y: rows.map((i) => T.si[p][i]), mode: 'lines', type: 'scatter', yaxis: 'y2' });
    }
    const layout = baseLayout();
    const c = themeColors();
    layout.xaxis = { ...layout.xaxis, type: logT ? 'log' : 'linear', anchor: 'y2',
      title: { text: distance ? `distance (m), at ${at > 0 ? fmtTime(at) : 'the start'}` : `time (${shownTime().sym})`,
        font: { size: 11 } } };
    layout.yaxis = { ...layout.yaxis, domain: [0.62, 1], exponentformat: 'none',
      title: { text: 'pH', font: { size: 11 } } };
    layout.yaxis2 = { gridcolor: c.grid, linecolor: c.grid, domain: [0, 0.52], anchor: 'x', zeroline: true, automargin: true,
      zerolinecolor: c.text, zerolinewidth: 1, title: { text: 'saturation index', font: { size: 11 } } };
    layout.margin = { ...layout.margin, b: 48 };
    layout.legend = { ...layout.legend, y: -0.16 };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  async function pqCsv() {
    if (!pq.view) { setStatus('Look at a run through PHREEQC first: there is no table yet.', 'warn'); return; }
    saidSaved(await saveBlob(new Blob([pq.view.csv], { type: 'text/csv' }), `${fileStem()}_phreeqc.csv`));
  }

  /* ---- inverse models: PHREEQC's INVERSE_MODELING between two waters of the run ---- */

  /** The waters an inverse model can go between: what flows in, and each cell of the column. */
  function pqInvWaters() {
    const r = state.result;
    const m = r && r.model;
    if (!m) return [];
    const n = m.fracture || 1;
    return [...(m.inflow ? [{ value: 'inflow', label: 'the water flowing in' }] : []),
      ...Array.from({ length: n }, (_, i) => ({ value: String(i), label: n > 1 ? `cell ${i}` : 'the water' }))];
  }

  function pqInvRender() {
    const waters = pqInvWaters();
    // Unless chosen: from what flows in, or the water as it starts; to the last cell as the run ends.
    const has = (v) => waters.some((w) => w.value === v);
    if (waters.length && !has(pq.inv.from)) pq.inv.from = waters[0].value;
    if (waters.length && !has(pq.inv.to)) pq.inv.to = waters[waters.length - 1].value;
    const options = (v) => (waters.length ? waters.map((w) => `<option value="${w.value}"${w.value === v ? ' selected' : ''}>`
      + `${esc(w.label)}</option>`).join('') : '<option value="">a water of the run</option>');
    $('rtmPqInvFrom').innerHTML = options(pq.inv.from);
    $('rtmPqInvTo').innerHTML = options(pq.inv.to);
    $('rtmPqInvFromAt').value = pq.inv.fromAt;
    $('rtmPqInvToAt').value = pq.inv.toAt;
    $('rtmPqInvFromAtWrap').hidden = pq.inv.from === 'inflow';
    $('rtmPqInvToAtWrap').hidden = pq.inv.to === 'inflow';
    $('rtmPqInvPhases').value = pq.inv.phases;
    $('rtmPqInvU').value = pq.inv.u;
    $('rtmPqInvRange').checked = pq.inv.range;
    $('rtmPqInvMinimal').checked = pq.inv.minimal;
    pqInvDraw();
  }

  function pqInvRead() {
    pq.inv.from = $('rtmPqInvFrom').value;
    pq.inv.to = $('rtmPqInvTo').value;
    pq.inv.fromAt = $('rtmPqInvFromAt').value.trim() || 'start';
    pq.inv.toAt = $('rtmPqInvToAt').value.trim() || 'end';
    pq.inv.phases = $('rtmPqInvPhases').value.trim();
    pq.inv.u = $('rtmPqInvU').value.trim();
    pq.inv.range = $('rtmPqInvRange').checked;
    pq.inv.minimal = $('rtmPqInvMinimal').checked;
    pqSave();
  }

  /** A water of the run as the inverse model is given it: what flows in, or a cell at the stored point nearest a time. */
  function pqInvPick(which, at, r) {
    if (which === 'inflow') {
      if (!r.model.inflow) return { error: 'The run has no water flowing in: choose a cell.' };
      return { pick: { state: Array.from(r.model.inflow), label: 'the water flowing in' } };
    }
    const n = r.model.fracture || 1;
    const cell = Number(which);
    if (!(which !== '' && Number.isInteger(cell) && cell >= 0 && cell < n)) return { error: 'Choose a water of the run to go from and one to go to.' };
    const word = String(at).trim().toLowerCase();
    let k;
    if (word === 'start' || word === 'the start' || word === '0') k = 0;
    else if (word === 'end' || word === 'the end') k = r.n - 1;
    else {
      const { times, bad } = parseTimes(at);
      if (bad.length || times.length !== 1) return { error: `"${at}" is no time of the run: start, end, or a time such as 2 d.` };
      k = nearestIndex(r.t, times[0]);
    }
    const where = n > 1 ? `cell ${cell}` : 'the water';
    const when = k === 0 ? 'as it starts' : k === r.n - 1 ? 'as the run ends' : `at ${fmtTime(r.t[k])}`;
    return { pick: { cell, k, label: `${where} ${when}` } };
  }

  async function pqInverse() {
    if (pq.busy) return;
    pqInvRead();
    const r = state.result;
    if (!r) { setStatus('Run the model first: an inverse model goes between two waters of a run.', 'warn'); return; }
    const a = pqInvPick(pq.inv.from, pq.inv.fromAt, r);
    const b = pqInvPick(pq.inv.to, pq.inv.toAt, r);
    if (a.error || b.error) { setStatus(a.error || b.error, 'error'); return; }
    if (a.pick.label === b.pick.label) { setStatus('From and to are the same water: choose two.', 'error'); return; }
    const u = pqNumber($('rtmPqInvU'));
    if (u === null || !(u < 1)) { setStatus('The uncertainty is a fraction of each total, from 0 to below 1: 0.05 is 5 %.', 'error'); return; }
    const phases = pq.inv.phases ? pq.inv.phases.split(/[,;]/).map((x) => x.trim()).filter(Boolean) : [];
    const water = pq.fill && pq.water.trim() ? { name: 'The water', text: pq.water } : null;
    pqBusy(true, 'PHREEQC is looking for inverse models…');
    const started = Date.now();
    try {
      const reply = await pqRequest({
        type: 'inverse', database: pqDatabase(), water,
        run: { t: r.t, states: r.states, temps: r.temps || null, n: r.n, width: r.width, model: r.model },
        modelText: (state.ran && state.ran.text) || state.text,
        options: { only: [a.pick, b.pick], inverse: { phases, uncertainty: u, range: pq.inv.range, minimal: pq.inv.minimal } },
      });
      pq.invResult = { ...reply.inverse, runNumber };
      pqInvDraw();
      const n = reply.inverse.models.length;
      const secs = ((Date.now() - started) / 1000).toFixed(1);
      if (n) setStatus(`PHREEQC found ${n} inverse model${n === 1 ? '' : 's'} in ${secs} s.`, 'ok');
      else setStatus('PHREEQC found no inverse model: no mixture of the phases named makes the one water of the other '
        + 'within the uncertainty. More phases, or a larger uncertainty, may find one.', 'warn');
    } catch (e) {
      setStatus(`PHREEQC could not work out inverse models: ${e.message}`, 'error');
    } finally {
      pqBusy(false);
    }
  }

  /** What PHREEQC found: the phases' mole transfers of each model as bars, and a table of each model. */
  function pqInvDraw() {
    const v = pq.invResult;
    const plot = $('rtmChartPqInv');
    $('rtmPqInvShow').hidden = !v;
    $('rtmPqInvOut').hidden = !v;
    if (!v) {
      if (typeof Plotly !== 'undefined') Plotly.purge(plot);
      plot.hidden = true;
      return;
    }
    const label = (n) => (v.waters.find((w) => w.n === n) || { label: `solution ${n}` }).label;
    const from = v.waters.slice(0, -1).map((w) => w.label).join(' and ');
    const to = v.waters[v.waters.length - 1].label;
    const nMin = v.models.filter((m) => m.minimal).length;
    $('rtmPqInvNote').textContent = `${v.models.length} model${v.models.length === 1 ? '' : 's'}`
      + `${v.minimal ? ', minimal ones only' : v.models.length ? `, ${nMin} of them minimal` : ''}: from ${from} to ${to}, `
      + `${v.balances.join(', ')} balanced to ${Number((v.uncertainty * 100).toPrecision(3))} %`
      + `${v.runNumber !== runNumber ? '; of the run before the latest one' : ''}`;
    const f3 = (x) => (x === 0 ? '0' : x.toExponential(3));
    const range = (x) => (v.range ? ` (${f3(x.min)} to ${f3(x.max)})` : '');
    const rows = v.models.map((m, i) => {
      const phases = m.phases.length ? m.phases.map((ph) => `${esc(ph.name)} ${f3(ph.value)}${range(ph)}`).join('<br>')
        : 'none: the waters are the same to within the uncertainty';
      const fractions = m.fractions.length > 2 || m.fractions.some((x) => x.value !== 1)
        ? m.fractions.map((x) => `${esc(label(x.n))} ${f3(x.value)}${range(x)}`).join('<br>') : '1 each';
      const deltas = m.solutions.flatMap((sl) => sl.balances.filter((bl) => bl.delta !== 0)
        .map((bl) => `${esc(bl.name)} in ${esc(label(sl.n))} ${bl.delta > 0 ? '+' : ''}${f3(bl.delta)}`));
      return `<tr><td>${i + 1}${m.minimal ? ', minimal' : ''}</td><td>${phases}</td><td>${fractions}</td>`
        + `<td>${deltas.length ? deltas.join('<br>') : 'none'}</td>`
        + `<td>${f3(m.residuals)}; ${f3(m.deltaOverU)}; ${f3(m.maxFraction)}</td></tr>`;
    });
    $('rtmPqInvOut').innerHTML = v.models.length
      ? `<table class="rtm-table rtm-pq-models"><thead><tr><th>Model</th><th>Phases, mol${v.range ? ' (from, to)' : ''}: `
        + 'dissolving above zero</th><th>Fractions of the waters</th><th>Adjusted within the uncertainty</th>'
        + '<th>Residuals; delta over uncertainty; largest fraction</th></tr></thead>'
        + `<tbody>${rows.join('')}</tbody></table>`
      : '<p class="warn">No model: no mixture of the phases named makes the one water of the other within the uncertainty.</p>';
    // Bars where a model moves a phase; none where none does.
    const moved = v.models.some((m) => m.phases.length);
    if (!moved || typeof Plotly === 'undefined' || state.tab !== 'phreeqc') {
      if (!moved) { if (typeof Plotly !== 'undefined') Plotly.purge(plot); plot.hidden = true; }
      return;
    }
    plot.hidden = false;
    const names = v.phases.map((ph) => ph.name);
    const traces = v.models.map((m, i) => {
      const at = names.map((nm) => m.phases.find((ph) => ph.name === nm) || null);
      const tr = { type: 'bar', name: `model ${i + 1}${m.minimal ? '' : ', not minimal'}`, x: names,
        y: at.map((ph) => (ph ? ph.value : null)), marker: { color: DG_PALETTE[i % DG_PALETTE.length] },
        hovertemplate: `model ${i + 1}: %{x} %{y:.3e} mol<extra></extra>` };
      if (v.range) {
        tr.error_y = { type: 'data', symmetric: false, thickness: 1.2, width: 4,
          array: at.map((ph) => (ph ? ph.max - ph.value : null)), arrayminus: at.map((ph) => (ph ? ph.value - ph.min : null)) };
      }
      return tr;
    });
    const layout = baseLayout();
    layout.barmode = 'group';
    layout.bargap = 0.5;
    layout.hovermode = 'closest';
    layout.xaxis.title = { text: 'phase', font: { size: 11 } };
    layout.yaxis.title = { text: 'mole transfer (mol), dissolving above zero', font: { size: 11 } };
    layout.yaxis.exponentformat = 'power';
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  async function pqInvCsv() {
    const v = pq.invResult;
    if (!v) { setStatus('Find inverse models first: there is no table yet.', 'warn'); return; }
    const label = (n) => (v.waters.find((w) => w.n === n) || { label: `solution ${n}` }).label;
    const rows = [];
    v.models.forEach((m, i) => {
      const add = (what, name, x, lo, hi) => rows.push([i + 1, m.minimal, what, name, x, v.range ? lo : null, v.range ? hi : null]);
      for (const x of m.fractions) add('fraction', label(x.n), x.value, x.min, x.max);
      for (const ph of m.phases) add('phase mole transfer (mol)', ph.name, ph.value, ph.min, ph.max);
      for (const rx of m.redox) add('redox mole transfer (mol)', rx.name, rx.value, null, null);
      for (const sl of m.solutions) for (const bl of sl.balances) if (bl.delta !== 0) add(`delta in ${label(sl.n)}`, bl.name, bl.delta, null, null);
      add('sum of residuals', '', m.residuals, null, null);
      add('sum of delta over uncertainty', '', m.deltaOverU, null, null);
      add('largest fractional adjustment', '', m.maxFraction, null, null);
    });
    const tab = { head: ['model', 'minimal', 'what', 'name', 'value', 'minimum', 'maximum'], rows };
    saidSaved(await saveBlob(new Blob([`${csvOf(tab)}\n`], { type: 'text/csv' }), `${fileStem()}_inverse.csv`));
  }

  /*
    A BATCH OVER A TABLE OF WATERS: one PHREEQC input run for every row of a
    table -- CSV, or a sheet of an Excel workbook, read by SheetJS the first
    time one is opened -- each {name} in it the row's value in the column of
    that name, the names in the table's first row. Every row runs on a clean
    slate in PHREEQC's worker (RtmPhreeqcEngine's batch), with the database
    the tab has chosen, and of the selected output the input defines the
    last row it gives is kept; a row PHREEQC refuses keeps what it said and
    the rest go on. The rows are sent in parts, run by as many PHREEQCs at
    once as the cores allow and put back in their order, so that the progress
    is the runs done and Stop keeps every part done. What it found is a table, the
    first rows shown and every row saved as CSV or Excel. With solids listed,
    each row runs once for each, {solid} the solid, a row's runs in one part,
    and what is shown is each row's run with the lowest value in a column of
    the selected output, the solid that gave it, and how each solid fared.
    The input, the rows asked for, the solids and the column are kept; the
    table and what it found are the visit's.
  */
  const PQ_XLSX_SRC = 'vendors/js/xlsx-0.20.3.full.min.js';
  const PQ_BATCH_PART = 200;
  const PQ_BATCH_SHOWN = 100;
  /** A table's rows from CSV or tab-separated text: the delimiter its first line has most of; quoted fields; decimal commas where the delimiter is not a comma. */
  function batchCsvRows(text) {
    const first = String(text).split(/\r?\n/).find((l) => l.trim()) || '';
    const count = (ch) => first.split(ch).length - 1;
    const sep = ['\t', ';', ','].reduce((b, ch) => (count(ch) > count(b) ? ch : b), ',');
    const rows = [];
    let row = [];
    let cell = '';
    let quoted = false;
    const t = String(text);
    for (let i = 0; i < t.length; i++) {
      const ch = t[i];
      if (quoted) {
        if (ch === '"' && t[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') quoted = false; else cell += ch;
      } else if (ch === '"' && !cell) quoted = true;
      else if (ch === sep) { row.push(cell); cell = ''; }
      else if (ch === '\n' || ch === '\r') {
        if (ch === '\r' && t[i + 1] === '\n') i++;
        row.push(cell); rows.push(row); row = []; cell = '';
      } else cell += ch;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    const comma = sep !== ',';
    return rows.map((r) => r.map((v) => {
      const x = v.trim();
      return comma && /^[-+]?\d+,\d+([eE][-+]?\d+)?$/.test(x) ? x.replace(',', '.') : x;
    }));
  }
  /** A table from its rows: the first with anything in it its names, the rest those with anything in them; values as text. */
  function batchTableOf(rows, name, more = {}) {
    const has = (r) => r.some((v) => v !== null && v !== undefined && String(v).trim() !== '');
    const text = (v) => (v === null || v === undefined ? '' : typeof v === 'number' ? String(v) : String(v).trim());
    const at = rows.findIndex(has);
    if (at < 0) return { name, ...more, columns: [], rows: [] };
    const seen = new Map();
    const columns = rows[at].map((v, k) => {
      let c = text(v) || `column ${k + 1}`;
      if (seen.has(c)) { seen.set(c, seen.get(c) + 1); c = `${c} (${seen.get(c)})`; } else seen.set(c, 1);
      return c;
    });
    const data = rows.slice(at + 1).filter(has).map((r) => columns.map((_, k) => text(r[k])));
    return { name, ...more, columns, rows: data };
  }
  /** An Excel sheet's rows, as SheetJS reads them: numbers as numbers, to go into PHREEQC's input at full precision. */
  function batchSheetRows(book, sheet) {
    return XLSX.utils.sheet_to_json(book.Sheets[sheet], { header: 1, raw: true, defval: null, blankrows: false });
  }
  async function pqBatchFileChosen(ev) {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    try {
      if (/\.xlsx?$/i.test(file.name)) {
        if (typeof XLSX === 'undefined') await loadScript(PQ_XLSX_SRC);
        const book = XLSX.read(await file.arrayBuffer(), { type: 'array' });
        const sheet = book.SheetNames[0];
        pq.batchTable = batchTableOf(batchSheetRows(book, sheet), file.name, { book, sheets: book.SheetNames, sheet });
      } else {
        pq.batchTable = batchTableOf(batchCsvRows(await pqFileText(file)), file.name);
      }
    } catch (e) {
      setStatus(`${file.name} could not be read as a table: ${e.message}`, 'error');
      return;
    }
    const t = pq.batchTable;
    // A start for the input where there is none: a SOLUTION with pH where the table has it, every column below it to take or leave.
    if (!pq.batch.text.trim() && t.columns.length) { pq.batch.text = batchStarter(t.columns); pq.batchStarter = pq.batch.text; pqSave(); }
    pqBatchRender();
    setStatus(t.rows.length ? `${t.name}${t.sheet ? `, sheet ${t.sheet}` : ''}: ${t.rows.length.toLocaleString()} row${t.rows.length === 1 ? '' : 's'} and `
      + `${t.columns.length} column${t.columns.length === 1 ? '' : 's'}, for this visit.` : `${t.name} has no rows under its first.`, t.rows.length ? 'ok' : 'warn');
  }
  /** A first input for a table: a SOLUTION, pH where it has a column so named, and each other column, commented, to put in or not. */
  function batchStarter(columns) {
    const ph = columns.find((c) => c === 'pH');
    const others = columns.filter((c) => c !== ph);
    // The element a column's name plainly is -- Ca, S(6), or Ca of "[Ca]tot (m)" -- and nothing where it is anything else.
    const isElement = (x) => !!(x && RtmModel.ATOMIC_WEIGHTS[x.replace(/\([+-]?\d+\)$/, '')]);
    const guess = (c) => {
      if (/^[A-Z][a-z]?(\([+-]?\d+\))?$/.test(c) && isElement(c)) return c;
      const m = /^\[([A-Z][a-z]?)\]/.exec(c);
      return m && isElement(m[1]) ? m[1] : '';
    };
    return ['# A water a row: {name} is the row\'s value in the column of that name.', 'SOLUTION 1', ' units mol/kgw',
      ...(ph ? [` pH {${ph}}`] : []), ...others.map((c) => `# ${guess(c) || ' '} {${c}}`),
      'SELECTED_OUTPUT 1', ' -reset false', ' -pH true', ' -ionic_strength true', 'END'].join('\n');
  }
  /** The rows asked for, 0-based: every one, or a list such as 1-100, 205 of the table's rows counted from 1; a string saying what is wrong. */
  function batchRowsAsked(spec, n) {
    const t = String(spec || '').trim();
    if (!t || /^all$/i.test(t)) return Array.from({ length: n }, (_, i) => i);
    const out = [];
    for (const part of t.split(/[,;\s]+/).filter(Boolean)) {
      const m = /^(\d+)(?:-(\d+))?$/.exec(part);
      if (!m) return `"${part}" is no row nor range of rows: write them as 1-100, 205`;
      const a = Number(m[1]);
      const b = m[2] ? Number(m[2]) : a;
      if (a < 1 || b < a || b > n) return `the table has rows 1 to ${n.toLocaleString()}: ${part} is not among them`;
      for (let i = a; i <= b; i++) out.push(i - 1);
    }
    return [...new Set(out)];
  }
  /** The names an input asks for as {name}, in the order it first does; not in a comment, from a # outside braces to the line's end. */
  function batchNames(text) {
    const names = [];
    for (const line of String(text).split('\n')) {
      for (const m of line.matchAll(/\{([^{}\n]+)\}|#/g)) {
        if (m[0] === '#') break;
        names.push(m[1]);
      }
    }
    return [...new Set(names)];
  }
  /** The selected output an input defines, the last of them; 1 where it gives no number; null where it has none. */
  function batchOutputOf(text) {
    const all = [...String(text).matchAll(/^\s*SELECTED_OUTPUT\b[ \t]*(\d*)/gim)];
    if (!all.length) return null;
    const n = all[all.length - 1][1];
    return n ? Number(n) : 1;
  }
  /**
    A batch's runs as units -- a water under one draw, or a row where nothing is drawn -- its runs together, one a
    solid; the run kept, with solids the one lowest in column col (the first where two are level) and without the one
    run where PHREEQC gave one; the runs refused, and how many were tried.
  */
  function batchUnits(v, col) {
    const out = [];
    let cur = null;
    for (const run of v.runs) {
      if (!cur || cur.row !== run.row || cur.draw !== run.draw) {
        cur = { row: run.row, draw: run.draw, drawn: run.drawn, runs: [], best: null, bests: null, refused: [], tried: 0 };
        out.push(cur);
      }
      cur.tried++;
      cur.runs.push(run);
      if (!run.values) cur.refused.push(run);
    }
    // The run lowest in column c among those given, the first where two are level.
    const lowest = (runs, c) => {
      const k = v.head.indexOf(c);
      let best = null;
      for (const r of runs) {
        const x = r.values && k >= 0 ? r.values[k] : undefined;
        if (typeof x === 'number' && Number.isFinite(x) && (!best || x < best.values[k])) best = r;
      }
      return best;
    };
    for (const u of out) {
      if (!v.solids) u.best = u.runs.find((r) => r.values) || null;
      else if (!v.groups) u.best = lowest(u.runs, col);
      else {
        // An element's lowest is of its own solids only: another's leave it where it was, which may well be lower.
        u.bests = v.groups.map((g) => lowest(u.runs.filter((r) => g.solids.includes(r.solid)), g.col));
        const at = v.groups.findIndex((g) => g.col === col);
        u.best = u.bests[at < 0 ? 0 : at];
      }
    }
    return out;
  }
  /** What the column's values are of: each row's lowest run, or each draw's, with solids; nothing more without. */
  const batchLowestOf = (v) => (!v.solids ? '' : v.draws ? ', the lowest of each draw' : ', the lowest of each row');
  /** What the spread is over: the waters, or the waters each drawn so many times. */
  const batchOver = (v) => (v.draws ? 'waters × draws' : 'waters');
  /**
    How the values of column col a batch gave spread: a value a unit -- with solids, its lowest run -- sorted, with
    the row, draw and solid each is of; the units that give none, refused or without a number there; and the smallest,
    5th percentile, median, 95th percentile and largest, a percentile between the two nearest values as Excel's
    PERCENTILE.INC and NumPy's percentile put it. Null where no unit gives a number.
  */
  function batchSpread(v, col) {
    const k = v.head.indexOf(col);
    const got = [];
    let none = 0;
    for (const u of batchUnits(v, col)) {
      const x = u.best && k >= 0 ? u.best.values[k] : undefined;
      if (typeof x === 'number' && Number.isFinite(x)) got.push({ x, row: u.row, draw: u.draw, solid: u.best.solid }); else none++;
    }
    if (!got.length) return null;
    got.sort((a, b) => a.x - b.x);
    const s = got.map((g) => g.x);
    const at = (q) => {
      const h = (s.length - 1) * q;
      const lo = Math.floor(h);
      return lo + 1 < s.length ? s[lo] + (h - lo) * (s[lo + 1] - s[lo]) : s[lo];
    };
    return { col, got, none, over: batchOver(v), n: s.length, min: s[0], p5: at(0.05), p50: at(0.5), p95: at(0.95), max: s[s.length - 1] };
  }
  /** The spread's numbers as rows of words and values, for the page and the workbook. */
  const batchSpreadRows = (sp) => [[sp.over, sp.n], ['smallest', sp.min], ['5th percentile', sp.p5], ['median', sp.p50],
    ['95th percentile', sp.p95], ['largest', sp.max], ...(sp.none ? [['left out, refused or with no number', sp.none]] : [])];
  /** What a batch ran, for the (i): its rows, with draws or solids its runs, and how many PHREEQC refused. */
  function batchFact(v) {
    const many = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
    const bad = v.runs.filter((r) => !r.values).length;
    const rows = new Set(v.runs.map((r) => r.row)).size;
    if (!v.solids && !v.draws) return `${many(rows, 'row')}, ${bad.toLocaleString()} refused`;
    return `${many(rows, 'row')}${v.draws ? `, ${v.draws} draws each` : ''}${v.solids ? `, each ${v.draws ? 'draw ' : ''}with ${many(v.solids.length, 'solid')}` : ''}`
      + `: ${many(v.runs.length, 'run')}, ${bad.toLocaleString()} refused`;
  }
  /**
    The solids a batch tries in turn as {solid}: a list, names apart by commas, semicolons or spaces; or a list for
    each element, "Ba: Barite, Witherite; Sr: Celestite, Strontianite", each element's lowest kept in its total,
    Ba(mol/kgw), and of its own solids only. Every solid once, in the order given. A string saying what is wrong.
  */
  function batchSolidGroups(spec) {
    const text = String(spec || '').trim();
    if (!text) return { solids: [], groups: null };
    const parts = text.split(';').map((p) => p.trim()).filter(Boolean);
    const head = (p) => /^([A-Z][a-z]?(?:\([+-]?\d+\))?)\s*:\s*(.*)$/.exec(p);
    const headed = parts.filter((p) => head(p));
    if (!headed.length) return { solids: [...new Set(text.split(/[,;\s]+/).filter(Boolean))], groups: null };
    if (headed.length < parts.length) {
      return `"${parts.find((p) => !head(p))}" is under no element: with solids listed for an element, list each under its own, as Ba: Barite, Witherite; Sr: Celestite`;
    }
    const groups = [];
    for (const p of parts) {
      const [, el, list] = head(p);
      if (!RtmModel.ATOMIC_WEIGHTS[el.replace(/\([+-]?\d+\)$/, '')]) return `"${p}": ${el} is no element`;
      const solids = [...new Set(list.split(/[,\s]+/).filter(Boolean))];
      if (!solids.length) return `"${p}": no solid listed for ${el}`;
      if (groups.some((g) => g.el === el)) return `${el} is listed twice`;
      groups.push({ el, col: `${el}(mol/kgw)`, solids });
    }
    return { solids: [...new Set(groups.flatMap((g) => g.solids))], groups };
  }
  /** Names as words: "Ba", "Ba and Sr", "U, Th and Np". */
  const batchAnd = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
  /**
    The values a batch draws: each a name, how it varies and its numbers, apart by semicolons -- "dU normal 0 0.5;
    dSi uniform -0.2 0.2; dK triangular -1 0 0.5" -- the name a {name} of the input. A string saying what is wrong.
  */
  function batchUncertain(spec) {
    const out = [];
    const takes = { normal: 'a mean and a standard deviation', uniform: 'the least and the most', triangular: 'the least, the likeliest and the most' };
    for (const part of String(spec || '').split(/[;\n]+/).map((p) => p.trim()).filter(Boolean)) {
      const [name, how, ...rest] = part.split(/[\s,]+/).filter(Boolean);
      const dist = String(how || '').toLowerCase();
      const x = rest.map(Number);
      const say = (why) => `"${part}": ${why}`;
      if (!takes[dist]) return say('say how it varies, normal, uniform or triangular, as dU normal 0 0.5');
      if (/[{}]/.test(name)) return say(`a name without braces, as dU, written {dU} in the input`);
      if (x.length !== (dist === 'triangular' ? 3 : 2) || x.some((n) => !Number.isFinite(n))) return say(`${dist} takes ${takes[dist]}`);
      if (dist === 'normal' && x[1] < 0) return say('a standard deviation below nought');
      if (dist === 'uniform' && x[0] > x[1]) return say('the least above the most');
      if (dist === 'triangular' && !(x[0] <= x[1] && x[1] <= x[2])) return say('the likeliest not between the least and the most');
      if (out.some((u) => u.name === name)) return say(`${name} is named twice`);
      out.push({ name, dist, x });
    }
    return out;
  }
  /** A whole number from a field, lo or more; dflt where the field is empty; null where it is not one. */
  function batchWhole(text, lo, dflt) {
    const t = String(text || '').trim();
    if (!t) return dflt;
    return /^\d+$/.test(t) && Number(t) >= lo && Number(t) <= 4294967295 ? Number(t) : null;
  }
  /**
    Numbers in [0, 1) for one draw of one water: mulberry32, started from the seed, the row and the draw mixed by
    MurmurHash3's finaliser, so that a water's draws are the same whichever other rows are run.
  */
  function batchRandom(seed, row, draw) {
    const mix = (h) => {
      h = Math.imul(h ^ (h >>> 16), 0x85ebca6b);
      h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
      return (h ^ (h >>> 16)) >>> 0;
    };
    let a = mix(mix(mix((seed + 0x9e3779b9) >>> 0) ^ row) ^ draw);
    return () => {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  /** One value drawn as u says: Box and Muller's for a normal, the inverse of the distribution for a triangular. */
  function batchDrawOne(u, rand) {
    const [a, b, c] = u.x;
    if (u.dist === 'uniform') return a + (b - a) * rand();
    if (u.dist === 'normal') return a + b * Math.sqrt(-2 * Math.log(1 - rand())) * Math.cos(2 * Math.PI * rand());
    if (c === a) return a;
    const p = rand();
    return p < (b - a) / (c - a) ? a + Math.sqrt(p * (c - a) * (b - a)) : c - Math.sqrt((1 - p) * (c - a) * (c - b));
  }
  /** The column whose lowest a batch with solids keeps: the one chosen, else the first total of an element, else the first in mol/kgw, else the last. */
  function batchLowestColumn(v) {
    // Solids for each element: one of their totals, the first unless another is chosen.
    if (v.groups) return v.groups.some((g) => g.col === pq.batch.lowest) ? pq.batch.lowest : v.groups[0].col;
    if (v.head.includes(pq.batch.lowest)) return pq.batch.lowest;
    return v.head.find((h) => /^[A-Z][a-z]?(\([+-]?\d+\))?\(mol\/kgw\)$/.test(h)) || v.head.find((h) => /\(mol\/kgw\)$/.test(h))
      || v.head[v.head.length - 1] || '';
  }

  function pqBatchRender() {
    const t = pq.batchTable;
    const ta = $('rtmPqBatchText');
    if (ta.value !== pq.batch.text) ta.value = pq.batch.text;
    $('rtmPqBatchRows').value = pq.batch.rows;
    $('rtmPqBatchSolids').value = pq.batch.solids;
    $('rtmPqBatchUncertain').value = pq.batch.uncertain;
    $('rtmPqBatchDraws').value = pq.batch.draws;
    $('rtmPqBatchSeed').value = pq.batch.seed;
    // How many draws and from what seed mean something only once there is something to draw.
    $('rtmPqBatchDrawsWrap').hidden = !pq.batch.uncertain.trim();
    const shown = 6;
    const sg = batchSolidGroups(pq.batch.solids);
    const solids = typeof sg === 'string' ? [] : sg.solids;
    const uncertain = batchUncertain(pq.batch.uncertain);
    const draws = Array.isArray(uncertain) && uncertain.length ? batchWhole(pq.batch.draws, 1, 10) : null;
    const asked = t && (solids.length || draws) ? batchRowsAsked(pq.batch.rows, t.rows.length) : null;
    const s = (n) => (n === 1 ? '' : 's');
    let runs = '';
    if (Array.isArray(asked) && asked.length) {
      const rows = `${asked.length.toLocaleString()} row${s(asked.length)} to run`;
      const k = solids.length;
      if (draws) {
        runs = ` ${rows}, ${draws} draws each${k ? `, each draw with ${k} solid${s(k)}` : ''}: ${(asked.length * draws * (k || 1)).toLocaleString()} runs.`;
      } else runs = ` ${rows}, each with ${k} solid${s(k)}: ${(asked.length * k).toLocaleString()} runs.`;
    }
    $('rtmPqBatchTable').textContent = !t
      ? 'No table yet: CSV, or a sheet of an Excel workbook, a water a row and the columns\' names in the first.'
      : `${t.name}${t.sheet ? `, sheet ${t.sheet}` : ''}: ${t.rows.length.toLocaleString()} row${s(t.rows.length)}; `
        + `columns ${t.columns.slice(0, shown).join(', ')}${t.columns.length > shown ? ` and ${t.columns.length - shown} more` : ''}.${runs}`;
    $('rtmPqBatchSheetWrap').hidden = !(t && t.sheets && t.sheets.length > 1);
    if (t && t.sheets) {
      $('rtmPqBatchSheet').innerHTML = t.sheets.map((nm) => `<option value="${esc(nm)}"${nm === t.sheet ? ' selected' : ''}>${esc(nm)}</option>`).join('');
    }
    const go = $('rtmPqBatchGo');
    go.textContent = pq.batchRunning ? 'Stop' : pq.batch.rows.trim() ? 'Run the rows asked for' : 'Run every row';
    go.disabled = pq.busy && !pq.batchRunning;
    pqBatchDraw();
  }

  async function pqBatchRun() {
    if (pq.batchRunning) { pq.batchStop = true; setStatus('Stopping once the parts running now are done…'); return; }
    if (pq.busy) return;
    const t = pq.batchTable;
    const text = pq.batch.text;
    const fail = (msg) => setStatus(msg, 'error');
    if (!t) { fail('Open a table of waters first: CSV, or an Excel workbook.'); return; }
    if (!text.trim()) { fail('Write the PHREEQC input to run for each row, {name} for its value in the column of that name.'); return; }
    const user = batchOutputOf(text);
    if (user === null) { fail('The input has no SELECTED_OUTPUT: say there what to keep of each row\'s run, -totals, -pH and the like, or a USER_PUNCH.'); return; }
    const names = batchNames(text);
    const sg = batchSolidGroups(pq.batch.solids);
    if (typeof sg === 'string') { fail(`Solids: ${sg}.`); return; }
    const { solids, groups } = sg;
    const uncertain = batchUncertain(pq.batch.uncertain);
    if (typeof uncertain === 'string') { fail(`Uncertain: ${uncertain}.`); return; }
    const drawn = uncertain.map((u) => u.name);
    if (solids.length && !names.includes('solid')) {
      fail('Solids are listed, but the input has no {solid}: write it where each solid goes, as {solid} 0 10 under EQUILIBRIUM_PHASES.');
      return;
    }
    if (!solids.length && names.includes('solid') && !t.columns.includes('solid') && !drawn.includes('solid')) {
      fail('The input asks for {solid}: list under Solids the solids to try, each in turn.');
      return;
    }
    const draws = uncertain.length ? batchWhole(pq.batch.draws, 1, 10) : null;
    if (uncertain.length && draws === null) { fail('Draws: a whole number from 1, as 10.'); return; }
    const seed = uncertain.length ? batchWhole(pq.batch.seed, 0, 1) : null;
    if (uncertain.length && seed === null) { fail('Seed: a whole number from 0, as 1.'); return; }
    for (const u of uncertain) {
      if (u.name === 'solid' && solids.length) { fail('Uncertain: solid is the name of the solid tried; name the value drawn otherwise.'); return; }
      if (t.columns.includes(u.name)) { fail(`Uncertain: ${u.name} is a column of the table too; name the value drawn otherwise.`); return; }
      if (!names.includes(u.name)) { fail(`The input has no {${u.name}}: write it where the value drawn goes, in a log_k or after -add_logk.`); return; }
    }
    const unknown = names.filter((n) => !(solids.length && n === 'solid') && !drawn.includes(n) && !t.columns.includes(n));
    if (unknown.length) {
      fail(`The input asks for ${unknown.map((n) => `{${n}}`).join(', ')}, but the table has no column so named; its columns: ${t.columns.join(', ')}.`);
      return;
    }
    const asked = batchRowsAsked(pq.batch.rows, t.rows.length);
    if (typeof asked === 'string') { fail(`Rows: ${asked}.`); return; }
    if (!asked.length) { fail('The table has no rows to run.'); return; }
    // A unit is a water under one draw, a row where nothing is drawn; it runs once for each solid, {solid} the solid,
    // its values drawn once for all of them. The values drawn and the solid are columns more; a part is whole units.
    const each = solids.length ? solids : [null];
    const columns = [...t.columns, ...drawn, ...(solids.length ? ['solid'] : [])];
    const units = [];
    for (const row of asked) for (let d = 0; d < (draws || 1); d++) units.push({ row, draw: draws ? d : null });
    const perPart = Math.max(1, Math.floor(PQ_BATCH_PART / each.length));
    const total = units.length * each.length;
    const several = solids.length || draws;
    const doing = (n) => (several ? `Running ${n.toLocaleString()} of ${total.toLocaleString()} runs`
      : `Running row ${n.toLocaleString()} of ${total.toLocaleString()}`);
    pq.batchRunning = true;
    pq.batchStop = false;
    pqBusy(true, several ? `Running ${total.toLocaleString()} runs through PHREEQC…`
      : `Running ${asked.length.toLocaleString()} row${asked.length === 1 ? '' : 's'} through PHREEQC…`);
    pqBatchRender();
    const started = Date.now();
    const head = [];
    const at = new Map();
    const runs = [];
    let version = '';
    let database = '';
    let stopped = false;
    // The parts, run by as many PHREEQCs at once as pqLanes allows -- PHREEQC's own worker and copies of it started for
    // the batch -- or one after another on the page where there are no workers; put back in their order however they end.
    const parts = [];
    for (let p = 0; p < units.length; p += perPart) parts.push(units.slice(p, p + perPart));
    pqStart();
    const lanes = pq.worker ? [pq.worker] : [null];
    const extra = [];
    if (pq.worker) {
      for (let i = 1; i < Math.min(pqLanes(), parts.length); i++) {
        const w = pqExtraWorker();
        if (!w) break;
        extra.push(w);
        lanes.push(w);
      }
    }
    const together = lanes.length > 1 ? `, ${lanes.length} at a time` : '';
    try {
      const results = new Array(parts.length);
      const doneIn = new Array(parts.length).fill(0);
      let next = 0;
      let failure = null;
      const progress = () => {
        const n = doneIn.reduce((a, x) => a + x, 0);
        setProgress(Math.min(1, n / total));
        setStatus(`${doing(n)} through PHREEQC${together}…`);
      };
      const runPart = async (i, worker) => {
        const jobs = [];
        for (const un of parts[i]) {
          let values = null;
          if (draws) {
            const rand = batchRandom(seed, un.row, un.draw);
            values = uncertain.map((u) => batchDrawOne(u, rand));
          }
          for (const solid of each) jobs.push({ ...un, drawn: values, solid });
        }
        const message = { type: 'batch', database: pqDatabase(), template: text, columns, user,
          rows: jobs.map((j) => [...t.rows[j.row], ...(j.drawn ? j.drawn.map(String) : []), ...(j.solid === null ? [] : [j.solid])]) };
        const onProgress = (msg) => { doneIn[i] = msg.done; progress(); };
        const reply = worker ? await pqRequestOn(worker, message, onProgress) : await pqRequest(message, onProgress);
        doneIn[i] = jobs.length;
        progress();
        results[i] = { jobs, reply };
      };
      // Each lane takes the next part when it is done with one; Stop, or a part that fails, ends them all once their parts are in.
      const lane = async (worker) => {
        while (!failure && !pq.batchStop && next < parts.length) {
          const i = next++;
          try { await runPart(i, worker); } catch (e) { failure = failure || e; }
        }
      };
      await Promise.all(lanes.map(lane));
      if (failure) throw failure;
      stopped = next < parts.length;
      for (let i = 0; i < next; i++) {
        const { jobs, reply } = results[i];
        version = reply.version;
        database = reply.database;
        const map = reply.head.map((h) => {
          if (!at.has(h)) { at.set(h, head.length); head.push(h); }
          return at.get(h);
        });
        const said = new Map(reply.errors);
        reply.rows.forEach((r, k) => {
          const values = r ? [] : null;
          if (r) r.forEach((x, j) => { values[map[j]] = x; });
          const j = jobs[k];
          runs.push({ row: j.row, draw: j.draw, drawn: j.drawn, solid: j.solid, values, said: r ? null : (said.get(k) || 'refused') });
        });
      }
      const seconds = (Date.now() - started) / 1000;
      pq.batchResult = { head, runs, names, table: t.name, sheet: t.sheet || null, asked: asked.length,
        solids: solids.length ? solids : null, groups, uncertain: draws ? uncertain : null, draws, seed, stopped, seconds, version, database, text,
        source: t, rowsSpec: pq.batch.rows };
      pq.batchLook = null;
      const bad = runs.filter((r) => !r.values).length;
      const done = new Set(runs.map((r) => r.row)).size;
      const per = [draws ? `${draws} draws each` : '',
        solids.length ? `each ${draws ? 'draw ' : ''}with ${solids.length} solid${solids.length === 1 ? '' : 's'}`
          + `${groups ? ` for ${batchAnd(groups.map((g) => g.el))}` : ''}` : ''].filter(Boolean);
      // An element whose total the selected output does not give has no lowest: said, with what to add.
      const missing = groups && runs.length ? groups.filter((g) => !head.includes(g.col)) : [];
      setStatus(`${done.toLocaleString()} of ${asked.length.toLocaleString()} row${asked.length === 1 ? '' : 's'}`
        + `${per.map((x) => `, ${x}`).join('')}${per.length ? ',' : ''} run through PHREEQC `
        + `${version} with ${database}${together ? `${together},` : ''} in ${seconds.toFixed(1)} s${stopped ? ', then stopped' : ''}`
        + `${bad ? `; ${bad.toLocaleString()}${several ? ` run${bad === 1 ? '' : 's'}` : ''} refused by PHREEQC, each with what it said` : ''}`
        + `${missing.length ? `; the selected output has no ${batchAnd(missing.map((g) => g.col))}: add ${batchAnd(missing.map((g) => g.el))} to its -totals` : ''}.`,
      bad || stopped || missing.length ? 'warn' : 'ok');
    } catch (e) {
      setStatus(`The batch could not be run: ${e.message}`, 'error');
    } finally {
      for (const w of extra) { pqWorkerFailed(w, 'the batch ended'); w.terminate(); }
      pq.batchRunning = false;
      pq.batchStop = false;
      setProgress(null);
      pqBusy(false);
      pqBatchRender();
    }
  }

  /**
    What the batch found: a note, and its first units as a table, a unit PHREEQC refused with what it said. With draws,
    each draw's number and the values drawn. With solids, each unit's run lowest in the column chosen and the solid that
    gave it, and above them how each solid fared.
  */
  function pqBatchDraw() {
    const v = pq.batchResult;
    $('rtmPqBatchShow').hidden = !v;
    const box = $('rtmPqBatchOut');
    box.hidden = !v;
    pqBatchSpread();
    pqBatchAgainst();
    pqBatchMap();
    pqBatchLookDraw(false);
    pqBatchKeptDraw();
    if (!v) { box.innerHTML = ''; return; }
    const num = (x) => (x === null || x === undefined ? '' : typeof x === 'number' ? (x === 0 ? '0' : fit4(x)) : String(x));
    const cell = (x) => `<td${typeof x === 'number' ? ` data-v="${x}"` : ''}>${esc(num(x))}</td>`;
    const cells = (values) => v.head.map((_, k) => cell(values[k])).join('');
    const many = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
    const bad = v.runs.filter((r) => !r.values).length;
    const where = `${v.table}${v.sheet ? `, sheet ${v.sheet}` : ''}`;
    // The column chosen: with solids, the one each unit's lowest run is lowest in; the one whose spread is drawn either way.
    const col = batchLowestColumn(v);
    $('rtmPqBatchLowestWrap').hidden = !v.head.length;
    // With solids for each element, every element's lowest is in the table: the choice is only which one's spread is drawn.
    $('rtmPqBatchLowestLabel').textContent = v.solids && !v.groups ? 'Lowest in' : 'Spread of';
    $('rtmPqBatchLowest').innerHTML = (v.groups ? v.groups.map((g) => g.col) : v.head)
      .map((h) => `<option value="${esc(h)}"${h === col ? ' selected' : ''}>${esc(h)}</option>`).join('');
    $('rtmPqBatchRunsItem').hidden = !v.solids;
    $('rtmPqBatchCsvItem').dataset.hint = v.solids ? `the lowest for each ${v.draws ? 'draw' : 'row'}` : `every ${v.draws ? 'draw' : 'row'}`;
    const units = batchUnits(v, col);
    const rows = new Set(units.map((u) => u.row)).size;
    const drawHead = v.draws ? ['draw', ...v.uncertain.map((u) => u.name)].map((h) => `<th>${esc(h)}</th>`).join('') : '';
    const drawCells = (u) => (v.draws ? `<td>${u.draw + 1}</td>${u.drawn.map(cell).join('')}` : '');
    const shown = units.length > PQ_BATCH_SHOWN;
    const forEls = v.groups ? ` for ${batchAnd(v.groups.map((g) => g.el))}` : '';
    if (!v.solids && !v.draws) {
      const n = units.length;
      $('rtmPqBatchNote').textContent = `${many(n, 'row')} of ${where}${v.stopped ? `, stopped after ${n.toLocaleString()} of ${v.asked.toLocaleString()}` : ''}; `
        + `${many(v.head.length, 'column')} of selected output${bad ? `; ${bad.toLocaleString()} refused` : ''}`
        + `${shown ? `; the first ${PQ_BATCH_SHOWN} shown, Export has every row` : ''}.`;
    } else if (!v.draws) {
      $('rtmPqBatchNote').textContent = `${many(rows, 'row')} of ${where}, each with ${many(v.solids.length, 'solid')}${forEls}: ${many(v.runs.length, 'run')}`
        + `${v.stopped ? `, stopped after ${rows.toLocaleString()} of ${v.asked.toLocaleString()} rows` : ''}${bad ? `; ${many(bad, 'run')} refused` : ''}`
        + `${shown ? `; the first ${PQ_BATCH_SHOWN} rows shown, Export has every row and run` : ''}.`;
    } else {
      $('rtmPqBatchNote').textContent = `${many(rows, 'row')} of ${where}, ${v.draws} draws each`
        + `${v.solids ? `, each draw with ${many(v.solids.length, 'solid')}${forEls}` : ''}: ${many(v.runs.length, 'run')}, seed ${v.seed}`
        + `${v.stopped ? `, stopped after ${rows.toLocaleString()} of ${v.asked.toLocaleString()} rows` : ''}${bad ? `; ${many(bad, 'run')} refused` : ''}`
        + `${shown ? `; the first ${PQ_BATCH_SHOWN} draws shown, Export has every one${v.solids ? ' and every run' : ''}` : ''}.`;
    }
    if (!v.solids) {
      const body = units.slice(0, PQ_BATCH_SHOWN).map((u) => `<tr${batchPick(u)}><td>${u.row + 1}</td>${drawCells(u)}${u.best ? cells(u.best.values)
        : `<td class="rtm-pq-batch-error" colspan="${Math.max(1, v.head.length)}">${esc(u.refused[0].said)}</td>`}</tr>`).join('');
      box.innerHTML = `<table><thead><tr><th>row</th>${drawHead}${v.head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>`;
      return;
    }
    if (v.groups) { box.innerHTML = batchGroupsHtml(v, units, { cell, drawHead, drawCells, many, bad }); return; }
    // Each solid: in how many units it held the column lowest, how many of its runs PHREEQC refused, and what it said first.
    const per = new Map(v.solids.map((sd) => [sd, { lowest: 0, refused: 0, runs: 0, said: '' }]));
    for (const r of v.runs) {
      const p = per.get(r.solid);
      p.runs++;
      if (!r.values) { p.refused++; if (!p.said) p.said = r.said; }
    }
    for (const u of units) if (u.best) per.get(u.best.solid).lowest++;
    // What PHREEQC said, only where it refused a run.
    const summary = `<table class="rtm-pq-batch-solids"><thead><tr><th>solid</th><th>lowest in</th><th>refused</th>${bad ? '<th>what PHREEQC said first</th>' : ''}`
      + '</tr></thead><tbody>' + v.solids.map((sd) => {
        const p = per.get(sd);
        return `<tr><td>${esc(sd)}</td><td>${p.lowest.toLocaleString()} of ${many(units.length, v.draws ? 'draw' : 'row')}</td>`
          + `<td>${p.refused.toLocaleString()} of ${many(p.runs, 'run')}</td>${bad ? `<td class="rtm-pq-said">${esc(p.said)}</td>` : ''}</tr>`;
      }).join('') + '</tbody></table>';
    const anyRefused = units.some((u) => u.refused.length);
    const key = v.head.indexOf(col);
    const body = units.slice(0, PQ_BATCH_SHOWN).map((u) => {
      const refused = anyRefused ? `<td>${esc(u.refused.map((r) => r.solid).join(', '))}</td>` : '';
      if (u.best) return `<tr${batchPick(u)}><td>${u.row + 1}</td>${drawCells(u)}<td>${esc(u.best.solid)}</td>${cells(u.best.values)}${refused}</tr>`;
      const why = u.refused.length === u.tried ? `every solid refused: ${u.refused[0].said}` : `no run gave ${col}`;
      return `<tr${batchPick(u)}><td>${u.row + 1}</td>${drawCells(u)}<td class="rtm-pq-batch-error" colspan="${v.head.length + 1}">${esc(why)}</td>${refused}</tr>`;
    }).join('');
    box.innerHTML = `${summary}<table><thead><tr><th>row</th>${drawHead}<th>solid</th>`
      + `${v.head.map((h, k) => `<th${k === key ? ' class="rtm-pq-batch-key"' : ''}>${esc(h)}</th>`).join('')}`
      + `${anyRefused ? '<th>refused</th>' : ''}</tr></thead><tbody>${body}</tbody></table>`;
  }

  /**
    A batch with solids for each element, as the page shows it: above, each element's solids, in how many units each
    was the lowest, how many of its runs PHREEQC refused and what it said first; below, each unit with every element's
    lowest and the solid that gave it, and the solids refused in it.
  */
  function batchGroupsHtml(v, units, { cell, drawHead, drawCells, many, bad }) {
    const per = new Map(v.solids.map((sd) => [sd, { refused: 0, runs: 0, said: '' }]));
    for (const r of v.runs) {
      const p = per.get(r.solid);
      p.runs++;
      if (!r.values) { p.refused++; if (!p.said) p.said = r.said; }
    }
    const unitWord = v.draws ? 'draw' : 'row';
    const summary = `<table class="rtm-pq-batch-solids"><thead><tr><th>element</th><th>solid</th><th>lowest in</th><th>refused</th>`
      + `${bad ? '<th>what PHREEQC said first</th>' : ''}</tr></thead><tbody>`
      + v.groups.flatMap((g, gi) => g.solids.map((sd) => {
        const p = per.get(sd);
        const lowest = units.filter((u) => u.bests[gi] && u.bests[gi].solid === sd).length;
        return `<tr><td>${esc(g.el)}</td><td>${esc(sd)}</td><td>${lowest.toLocaleString()} of ${many(units.length, unitWord)}</td>`
          + `<td>${p.refused.toLocaleString()} of ${many(p.runs, 'run')}</td>${bad ? `<td class="rtm-pq-said">${esc(p.said)}</td>` : ''}</tr>`;
      })).join('') + '</tbody></table>';
    const anyRefused = units.some((u) => u.refused.length);
    const head = v.groups.map((g) => `<th>${esc(g.el)}: solid</th><th class="rtm-pq-batch-key">${esc(g.col)}</th>`).join('');
    const body = units.slice(0, PQ_BATCH_SHOWN).map((u) => {
      const each = v.groups.map((g, gi) => {
        const b = u.bests[gi];
        if (b) return `<td>${esc(b.solid)}</td>${cell(b.values[v.head.indexOf(g.col)])}`;
        const mine = u.runs.filter((r) => g.solids.includes(r.solid));
        const why = mine.length && mine.every((r) => !r.values) ? `every solid refused: ${mine[0].said}` : `no run gave ${g.col}`;
        return `<td class="rtm-pq-batch-error" colspan="2">${esc(why)}</td>`;
      }).join('');
      return `<tr${batchPick(u)}><td>${u.row + 1}</td>${drawCells(u)}${each}${anyRefused ? `<td>${esc(u.refused.map((r) => r.solid).join(', '))}</td>` : ''}</tr>`;
    }).join('');
    return `${summary}<table><thead><tr><th>row</th>${drawHead}${head}${anyRefused ? '<th>refused</th>' : ''}</tr></thead><tbody>${body}</tbody></table>`;
  }

  /**
    How the column chosen spreads: for each value the share of the units -- the waters, or the waters each under its
    draws -- at or below it, a step a unit, on a log axis where the values are all above nought and span a factor of
    ten or more; the median and the 95th percentile marked, each label on the side of its line that has room; the
    numbers beside it. Drawn only where it is seen -- the Batch tab, which draws it again when it is shown.
  */
  function pqBatchSpread() {
    const v = pq.batchResult;
    const box = $('rtmPqBatchSpread');
    const plot = $('rtmChartPqBatch');
    const sp = v ? batchSpread(v, batchLowestColumn(v)) : null;
    box.hidden = !sp;
    if (!sp) {
      if (typeof Plotly !== 'undefined') Plotly.purge(plot);
      $('rtmPqBatchStats').innerHTML = '';
      return;
    }
    const f = (x) => (x === 0 ? '0' : fit4(x));
    // The batch kept, beside this one, where it has a result in the same column.
    const kept = batchKeptBeside();
    const ksp = kept && batchHas(kept, sp.col) ? batchSpread(kept, sp.col) : null;
    const shown = (x, i) => (i === 0 || i === 6 ? x.toLocaleString() : esc(f(x)));
    const names = batchSpreadRows({ ...sp, none: Math.max(sp.none, ksp ? ksp.none : 0) }).map(([what]) => what);
    $('rtmPqBatchStats').innerHTML = `<caption>${esc(sp.col)}${batchLowestOf(v)}</caption>`
      + `${ksp ? '<thead><tr><th></th><td>this batch</td><td>kept</td></tr></thead>' : ''}<tbody>`
      + names.map((what, i) => `<tr><th scope="row">${what}</th><td>${shown(batchSpreadValues(sp)[i], i)}</td>`
        + `${ksp ? `<td>${shown(batchSpreadValues(ksp)[i], i)}</td>` : ''}</tr>`).join('')
      + '</tbody>';
    if (typeof Plotly === 'undefined' || state.tab !== 'batch') return;
    const c = themeColors();
    const muted = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || c.grid;
    // The axis holds this batch and the kept one: logarithmic where all of both are above nought and span a factor of ten.
    const lo = ksp ? Math.min(sp.min, ksp.min) : sp.min;
    const hi = ksp ? Math.max(sp.max, ksp.max) : sp.max;
    const log = lo > 0 && hi / lo >= 10;
    // The share at or below: nought up to the smallest, then a step up at each unit.
    const xs = [sp.got[0].x, ...sp.got.map((g) => g.x)];
    const ys = [0, ...sp.got.map((_, i) => ((i + 1) / sp.n) * 100)];
    const of = [sp.got[0], ...sp.got].map((g) => [`row ${g.row + 1}${g.draw !== null ? `, draw ${g.draw + 1}` : ''}${g.solid ? `, ${g.solid}` : ''}`,
      g.row, g.draw]);
    const line = (x) => ({ type: 'scatter', mode: 'lines', x: [x, x], y: [0, 100], line: { color: muted, width: 1, dash: 'dot' },
      hoverinfo: 'skip', showlegend: false });
    const traces = [
      { type: 'scatter', mode: 'lines', x: xs, y: ys, line: { shape: 'hv', width: 2, color: DG_PALETTE[0] }, customdata: of,
        hovertemplate: `%{x:.4g}: %{y:.1f} % of the ${sp.over} at or below<br>%{customdata[0]}<extra></extra>`, showlegend: false },
      line(sp.p50), line(sp.p95),
    ];
    if (ksp) {
      // The kept batch's curve, grey, behind this one's; its points not to be clicked, its waters not this batch's.
      traces[0].name = 'this batch';
      traces[0].showlegend = true;
      traces.unshift({ type: 'scatter', mode: 'lines', name: 'kept', x: [ksp.got[0].x, ...ksp.got.map((g) => g.x)],
        y: [0, ...ksp.got.map((_, i) => ((i + 1) / ksp.n) * 100)], line: { shape: 'hv', width: 2, color: muted },
        hovertemplate: `%{x:.4g}: %{y:.1f} % of the kept batch's ${ksp.over} at or below<extra></extra>` });
    }
    // The labels above the plot: each to the side of its line that has room, the median's a row higher where they would meet.
    const margin = { l: 70, r: 30, t: 30, b: 48 };
    const T = (x) => (log ? Math.log10(x) : x);
    const span = T(hi) - T(lo) || 1;
    const at = (x) => (T(x) - T(lo)) / span;
    const wide = Math.max(200, plot.clientWidth - margin.l - margin.r);
    const width = (text) => (text.length * 6 + 6) / wide;
    const marks = [{ x: sp.p50, text: `median ${f(sp.p50)}` }, { x: sp.p95, text: `95 %: ${f(sp.p95)}` }].map((m) => {
      const w = width(m.text);
      return { ...m, w, right: at(m.x) + w <= 1.03 };
    });
    if (at(marks[0].x) - marks[0].w >= -0.03) marks[0].right = false;
    const ends = (m) => (m.right ? [at(m.x), at(m.x) + m.w] : [at(m.x) - m.w, at(m.x)]);
    const [a0, a1] = ends(marks[0]);
    const [b0, b1] = ends(marks[1]);
    const meet = a0 < b1 && b0 < a1;
    if (meet) margin.t = 44;
    const annotations = marks.map((m, i) => ({ x: T(m.x), y: 1, xref: 'x', yref: 'paper', yanchor: 'bottom', showarrow: false,
      xanchor: m.right ? 'left' : 'right', xshift: m.right ? 3 : -3, yshift: meet && i === 0 ? 14 : 0, text: m.text,
      font: { size: 10, color: c.text } }));
    const layout = baseLayout();
    layout.hovermode = 'closest';
    if (ksp) {
      layout.showlegend = true;
      margin.b = 64;
    }
    layout.margin = margin;
    layout.annotations = annotations;
    layout.xaxis.type = log ? 'log' : 'linear';
    layout.xaxis.exponentformat = 'power';
    layout.xaxis.title = { text: `${sp.col}${batchLowestOf(v)}`, font: { size: 11 } };
    layout.yaxis.range = [0, 100];
    layout.yaxis.title = { text: `${sp.over} at or below (%)`, font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    // The numbers beside it, a column more with a batch kept, narrow its box: the chart is fitted to it again.
    Plotly.Plots.resize(plot);
    batchClickable(plot);
  }

  /**
    What a batch's result can be drawn against: the table's columns with numbers in them, while it is the table the
    batch ran (its rows the same), the values drawn, and PHREEQC's columns -- of the run kept for each unit, the one
    lowest with solids. Each with its key, the group it is listed under, and its value for a unit.
  */
  function batchAgainstOptions(v) {
    const out = [];
    const t = v.source;
    if (t) {
      const num = (x) => (x === '' || x === null || x === undefined ? NaN : Number(x));
      t.columns.forEach((c, k) => {
        if (t.rows.some((r) => Number.isFinite(num(r[k])))) out.push({ key: `table:${c}`, label: c, group: 'the table', of: (u) => num(t.rows[u.row][k]) });
      });
    }
    if (v.draws) v.uncertain.forEach((d, i) => out.push({ key: `drawn:${d.name}`, label: d.name, group: 'drawn', of: (u) => u.drawn[i] }));
    v.head.forEach((h, k) => out.push({ key: `out:${h}`, label: h, group: 'PHREEQC', of: (u) => (u.best ? u.best.values[k] : undefined) }));
    return out;
  }
  /** The one to draw against: the one chosen, else the first value drawn, else the table's pH, else its first column, else PHREEQC's first other than the result. */
  function batchAgainstPick(options, col) {
    const chosen = options.find((o) => o.key === pq.batch.against || o.label === pq.batch.against);
    return chosen || options.find((o) => o.group === 'drawn') || options.find((o) => o.key === 'table:pH')
      || options.find((o) => o.group === 'the table') || options.find((o) => o.label !== col) || options[0] || null;
  }

  /**
    A batch's result against a column: a point a unit -- a water, or a water under one draw -- its result (the column
    under Lowest in or Spread of) up the side and what it is drawn against along the bottom, each axis logarithmic where
    its values are all above nought and span a factor of ten or more; with solids a colour a solid, in the order they
    are listed, a legend naming them. Units with no number for either are left out and counted. Drawn only where it is
    seen -- the Batch tab, which draws it again when it is shown.
  */
  function pqBatchAgainst() {
    const v = pq.batchResult;
    const box = $('rtmPqBatchAgainst');
    const plot = $('rtmChartPqBatchX');
    const wrap = $('rtmPqBatchXWrap');
    const options = v ? batchAgainstOptions(v) : [];
    const col = v ? batchLowestColumn(v) : '';
    const pick = v ? batchAgainstPick(options, col) : null;
    wrap.hidden = !pick;
    if (pick) {
      const groups = [...new Set(options.map((o) => o.group))];
      $('rtmPqBatchX').innerHTML = groups.map((g) => `<optgroup label="${esc(g)}">${options.filter((o) => o.group === g)
        .map((o) => `<option value="${esc(o.key)}"${o === pick ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</optgroup>`).join('');
    }
    const units = pick ? batchUnits(v, col) : [];
    const k = v ? v.head.indexOf(col) : -1;
    const points = [];
    for (const u of units) {
      const y = u.best && k >= 0 ? u.best.values[k] : undefined;
      const x = pick.of(u);
      if (typeof y === 'number' && Number.isFinite(y) && typeof x === 'number' && Number.isFinite(x)) points.push({ x, y, u });
    }
    box.hidden = !points.length;
    if (!points.length) {
      if (typeof Plotly !== 'undefined') Plotly.purge(plot);
      return;
    }
    const left = units.length - points.length;
    const note = $('rtmPqBatchAgainstNote');
    note.hidden = !left;
    note.textContent = left ? `${left.toLocaleString()} of ${units.length.toLocaleString()} ${v.draws ? 'draws' : 'rows'} left out: `
      + `no number for ${pick.label} or ${col}.` : '';
    if (typeof Plotly === 'undefined' || state.tab !== 'batch') return;
    const logOf = (xs) => { const lo = Math.min(...xs); return lo > 0 && Math.max(...xs) / lo >= 10; };
    const many = points.length > 2000;
    const named = (p) => [`row ${p.u.row + 1}${p.u.draw !== null ? `, draw ${p.u.draw + 1}` : ''}`, p.u.row, p.u.draw];
    // A series a solid, in the order the solids are listed, so that a colour is always the same solid.
    const order = v.solids ? (v.groups ? v.groups[Math.max(0, v.groups.findIndex((g) => g.col === col))].solids : v.solids) : [null];
    const traces = order.map((sd, i) => {
      const mine = points.filter((p) => (sd === null ? true : p.u.best.solid === sd));
      return { type: many ? 'scattergl' : 'scatter', mode: 'markers', name: sd || col, x: mine.map((p) => p.x), y: mine.map((p) => p.y),
        customdata: mine.map(named), marker: { size: many ? 4 : 7, opacity: many ? 0.6 : 0.85, color: DG_PALETTE[i % DG_PALETTE.length] },
        hovertemplate: `${esc(pick.label)} %{x:.4g}<br>${esc(col)} %{y:.4g}<br>%{customdata[0]}${sd ? `, ${esc(sd)}` : ''}<extra></extra>` };
    }).filter((tr) => tr.x.length);
    // The batch kept, beside it: its points grey and faint behind, where it has the result and the same thing to draw it against.
    const kept = batchKeptBeside();
    const keptPoints = [];
    const kPick = kept && batchHas(kept, col) ? batchAgainstOptions(kept).find((o) => o.key === pick.key) : null;
    if (kPick) {
      const kk = kept.head.indexOf(col);
      for (const u of batchUnits(kept, col)) {
        const y = u.best && kk >= 0 ? u.best.values[kk] : undefined;
        const x = kPick.of(u);
        if (typeof y === 'number' && Number.isFinite(y) && typeof x === 'number' && Number.isFinite(x)) keptPoints.push({ x, y });
      }
    }
    if (keptPoints.length) {
      const muted = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || themeColors().grid;
      if (traces.length === 1 && !v.solids) traces[0].name = 'this batch';
      traces.unshift({ type: keptPoints.length > 2000 ? 'scattergl' : 'scatter', mode: 'markers', name: 'kept',
        x: keptPoints.map((p) => p.x), y: keptPoints.map((p) => p.y),
        marker: { size: keptPoints.length > 2000 ? 3 : 6, opacity: 0.45, color: muted },
        hovertemplate: `the batch kept: ${esc(pick.label)} %{x:.4g}<br>${esc(col)} %{y:.4g}<extra></extra>` });
    }
    const all = [...points, ...keptPoints];
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.showlegend = traces.length > 1;
    layout.margin = { l: 70, r: 30, t: 14, b: traces.length > 1 ? 64 : 48 };
    layout.xaxis.type = logOf(all.map((p) => p.x)) ? 'log' : 'linear';
    layout.xaxis.exponentformat = 'power';
    layout.xaxis.title = { text: `${pick.label}${pick.group === 'drawn' ? ', drawn' : ''}`, font: { size: 11 } };
    layout.yaxis.type = logOf(all.map((p) => p.y)) ? 'log' : 'linear';
    layout.yaxis.title = { text: `${col}${batchLowestOf(v)}`, font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    batchClickable(plot);
  }

  /*
    THE RESULT OVER THE WATERS' PLACES: each water at its place, two columns of
    the batch's table as the axes -- those named X and Y unless others are
    chosen, '-' for none -- and coloured by its result, light to dark on one
    hue (dark to light on the dark page, so that a high value always stands
    out), on a logarithmic key where the values are all above nought and span
    a factor of ten or more. With draws, a water's colour is the median of its
    draws, and a click on it looks at the draw nearest that median. Two
    columns named as places keep the map's scale the same both ways.
  */
  function batchMapColumns(v) {
    const t = v && v.source;
    if (!t) return [];
    const num = (x) => (x === '' || x === null || x === undefined ? NaN : Number(x));
    return t.columns.map((c, k) => ({ c, k })).filter(({ k }) => t.rows.some((r) => Number.isFinite(num(r[k]))));
  }

  function pqBatchMap() {
    const v = pq.batchResult;
    const box = $('rtmPqBatchMap');
    const plot = $('rtmChartPqBatchMap');
    const cols = batchMapColumns(v);
    box.hidden = cols.length < 2;
    // The map's formats in the Export menu, with the map.
    const offer = (on) => { for (const el of document.querySelectorAll('[data-batch-map]')) el.hidden = !on; };
    const off = () => { plot.hidden = true; offer(false); if (typeof Plotly !== 'undefined') Plotly.purge(plot); };
    if (box.hidden) { off(); return; }
    const place = /^[xy](\s|\(|_|$)/i;
    const pick = (saved, letter) => (saved === '-' ? '' : cols.some((o) => o.c === saved) ? saved
      : (cols.find((o) => o.c.toLowerCase()[0] === letter && place.test(o.c)) || {}).c || '');
    const cx = pick(pq.batch.mapX, 'x');
    const cy = pick(pq.batch.mapY, 'y');
    const fill = (id, chosen) => {
      $(id).innerHTML = `<option value="-"${chosen ? '' : ' selected'}>—</option>`
        + cols.map((o) => `<option value="${esc(o.c)}"${o.c === chosen ? ' selected' : ''}>${esc(o.c)}</option>`).join('');
    };
    fill('rtmPqBatchMapX', cx);
    fill('rtmPqBatchMapY', cy);
    if (!cx || !cy || cx === cy) { off(); return; }
    const col = batchLowestColumn(v);
    const k = v.head.indexOf(col);
    const kx = v.source.columns.indexOf(cx);
    const ky = v.source.columns.indexOf(cy);
    // Each water's value: its one run's, or with draws the median of its draws and the draw nearest it.
    const byRow = new Map();
    for (const u of batchUnits(v, col)) {
      const y = u.best && k >= 0 ? u.best.values[k] : undefined;
      if (typeof y !== 'number' || !Number.isFinite(y)) continue;
      if (!byRow.has(u.row)) byRow.set(u.row, []);
      byRow.get(u.row).push({ y, draw: u.draw });
    }
    const points = [];
    for (const [row, list] of byRow) {
      const x = Number(v.source.rows[row][kx]);
      const yy = Number(v.source.rows[row][ky]);
      if (!Number.isFinite(x) || !Number.isFinite(yy) || v.source.rows[row][kx] === '' || v.source.rows[row][ky] === '') continue;
      const s = list.map((d) => d.y).sort((a, b) => a - b);
      const h = (s.length - 1) / 2;
      const value = s.length % 2 ? s[h] : (s[Math.floor(h)] + s[Math.ceil(h)]) / 2;
      const near = list.reduce((a, d) => (Math.abs(d.y - value) < Math.abs(a.y - value) ? d : a), list[0]);
      points.push({ x, y: yy, value, row, draw: near.draw });
    }
    plot.hidden = !points.length;
    if (!points.length) { off(); return; }
    offer(true);
    if (typeof Plotly === 'undefined' || state.tab !== 'batch') return;
    const lo = Math.min(...points.map((p) => p.value));
    const hi = Math.max(...points.map((p) => p.value));
    const log = lo > 0 && hi / lo >= 10;
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    // One hue, light to dark; on the dark page dark to light: the high values the ones that stand out.
    const ramp = ['#c6dbef', '#6baed6', '#2171b5', '#08306b'];
    const scale = (dark ? [...ramp].reverse() : ramp).map((c, i, a) => [i / (a.length - 1), c]);
    // The key's decades: a value a hair off one (1.0000000000003e-3) still ticked there, the key's range reaching it.
    const ticks = [];
    if (log) for (let e = Math.ceil(Math.log10(lo) - 1e-6); e <= Math.floor(Math.log10(hi) + 1e-6); e++) ticks.push(e);
    const range = log && ticks.length ? { cmin: Math.min(Math.log10(lo), ticks[0]), cmax: Math.max(Math.log10(hi), ticks[ticks.length - 1]) } : {};
    const many = points.length > 2000;
    const what = `${col}${batchLowestOf(v)}${v.draws ? ', the median of its draws' : ''}`;
    const trace = { type: many ? 'scattergl' : 'scatter', mode: 'markers', x: points.map((p) => p.x), y: points.map((p) => p.y),
      customdata: points.map((p) => [`row ${p.row + 1}${p.draw !== null ? `, draw ${p.draw + 1} nearest its median` : ''}`, p.row, p.draw, p.value]),
      marker: { size: many ? 5 : 8, color: points.map((p) => (log ? Math.log10(p.value) : p.value)), colorscale: scale, ...range,
        colorbar: { title: { text: what, side: 'right', font: { size: 11 } }, thickness: 12, outlinewidth: 0,
          ...(log ? { tickvals: ticks, ticktext: ticks.map((e) => `10<sup>${e}</sup>`) } : { exponentformat: 'power' }) } },
      hovertemplate: `${esc(cx)} %{x:.4g}, ${esc(cy)} %{y:.4g}<br>${esc(col)} %{customdata[3]:.4g}<br>%{customdata[0]}<extra></extra>` };
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.margin = { l: 70, r: 20, t: 14, b: 48 };
    layout.xaxis.title = { text: cx, font: { size: 11 } };
    layout.yaxis.title = { text: cy, font: { size: 11 } };
    layout.xaxis.exponentformat = 'none';
    layout.yaxis.exponentformat = 'none';
    // Two columns named as places: the same scale both ways.
    if (place.test(cx) && place.test(cy)) { layout.yaxis.scaleanchor = 'x'; layout.yaxis.scaleratio = 1; }
    Plotly.react(plot, [trace], layout, PLOT_CONFIG);
    Plotly.Plots.resize(plot);
    batchClickable(plot);
  }

  /**
    The batch kept: the button that keeps the one shown, and the line saying what is kept -- this batch, which the next
    one will be drawn beside, or another, drawn beside this one where it has a result in the same column.
  */
  function pqBatchKeptDraw() {
    const v = pq.batchResult;
    const kept = pq.batchKept;
    const keep = $('rtmPqBatchKeep');
    keep.disabled = !v || kept === v;
    keep.textContent = v && kept === v ? 'Kept' : 'Keep this batch';
    $('rtmPqBatchKept').hidden = !kept || !v;
    if (!kept || !v) return;
    const many = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
    const col = batchLowestColumn(v);
    $('rtmPqBatchKeptText').textContent = kept === v ? 'This batch is kept: the next one you run is drawn beside it.'
      : `Beside it, the batch kept: ${many(new Set(kept.runs.map((r) => r.row)).size, 'row')} of ${kept.table}`
        + `${kept.sheet ? `, sheet ${kept.sheet}` : ''}${kept.draws ? `, ${kept.draws} draws each` : ''}`
        + `${kept.solids ? `, ${many(kept.solids.length, 'solid')}` : ''}, with ${kept.database}`
        + `${batchHas(kept, col) ? '' : `; it has no ${col}, so it is not drawn`}.`;
  }

  /** A row of the batch's table, to click for its water's whole output. */
  const batchPick = (u) => ` class="rtm-pq-batch-pick" data-on-click="rtm:pqBatchLook" data-row="${u.row}" data-draw="${u.draw === null ? '' : u.draw}"`;
  /** A batch chart's points, to click for their water's whole output: each point's row and draw are in its customdata. */
  function batchClickable(plot) {
    if (typeof plot.removeAllListeners === 'function') plot.removeAllListeners('plotly_click');
    plot.on('plotly_click', (ev) => {
      const at = ev && ev.points && ev.points[0] && ev.points[0].customdata;
      if (Array.isArray(at) && Number.isInteger(at[1])) pqBatchLook(at[1], at[2] === undefined ? null : at[2]);
    });
  }

  /*
    ONE WATER OF A BATCH IN FULL: a row of the table or a point of a chart
    clicked, that water is run again -- the input as the batch filled it, the
    same draw, with solids the solid that gave the lowest, or where every run
    was refused the first -- with what PHREEQC prints of it: its species, its
    saturation indices, what each phase did. Only with the database the batch
    ran with, from the batch's own table, which it keeps.
  */
  async function pqBatchLook(row, draw) {
    const v = pq.batchResult;
    if (!v) return;
    if (pq.busy) { setStatus('PHREEQC is busy: look at the water once it is done.', 'warn'); return; }
    if (v.database !== batchDatabaseName()) {
      setStatus(`The batch ran with ${v.database}: choose it again to look at one of its waters.`, 'warn');
      return;
    }
    const u = batchUnits(v, batchLowestColumn(v)).find((x) => x.row === row && x.draw === draw);
    if (!u) return;
    const run = u.best || u.refused[0] || u.runs[0];
    const drawnNames = v.draws ? v.uncertain.map((d) => d.name) : [];
    const columns = [...v.source.columns, ...drawnNames, ...(v.solids ? ['solid'] : [])];
    const values = [...v.source.rows[row], ...(run.drawn ? run.drawn.map(String) : []), ...(v.solids ? [run.solid] : [])];
    const what = `row ${row + 1}${draw !== null ? `, draw ${draw + 1}` : ''}${run.solid ? `, ${run.solid}` : ''}`;
    pqBusy(true, `Running ${what} again, for what PHREEQC prints of it…`);
    try {
      const reply = await pqRequest({ type: 'batchOne', database: pqDatabase(), template: v.text, columns, row: values,
        user: batchOutputOf(v.text) });
      pq.batchLook = { row, draw, what, refused: !!reply.refused,
        text: reply.refused ? `PHREEQC refused this run, and said:\n\n${reply.refused}\n\nThe input, as the batch filled it:\n\n${reply.input}\n` : reply.text };
      setStatus(`PHREEQC's output for ${what}${reply.refused ? ': it refused the run, and said why.' : '.'}`, reply.refused ? 'warn' : 'ok');
    } catch (e) {
      setStatus(`The water could not be run again: ${e.message}`, 'error');
    } finally {
      pqBusy(false);
    }
    pqBatchLookDraw(true);
  }

  function pqBatchLookDraw(scroll) {
    const look = pq.batchLook;
    const box = $('rtmPqBatchLook');
    box.hidden = !look;
    $('rtmPqBatchLookHint').hidden = !pq.batchResult || !!look;
    if (!look) return;
    $('rtmPqBatchLookTitle').textContent = `PHREEQC's output for ${look.what}`;
    $('rtmPqBatchLookText').textContent = look.text;
    if (scroll) box.scrollIntoView({ block: 'nearest' });
  }

  async function pqBatchLookSave() {
    const look = pq.batchLook;
    if (!look) return;
    const name = `${fileStem()}_batch_row${look.row + 1}${look.draw !== null ? `_draw${look.draw + 1}` : ''}.txt`;
    saidSaved(await saveBlob(new Blob([look.text], { type: 'text/plain' }), name));
  }

  /**
    Every row the batch ran, each with the table's values the input asked for, with draws the draw and the values drawn,
    what PHREEQC gave and what it said where it refused. With solids: CSV the lowest for each unit and the solids refused
    in it, 'runs' every run, Excel both. The workbook has the spread's numbers on a sheet of their own.
  */
  /**
    A batch's tables as Export saves them, its table's values from its own table: 'main' -- every row, or with solids
    each unit's lowest -- 'runs' with solids, every run; and what its input sheet says of it.
  */
  function batchTables(v) {
    const t = v.source;
    const drawnNames = v.draws ? v.uncertain.map((u) => u.name) : [];
    const asked = v.names.filter((n) => !(v.solids && n === 'solid') && !drawnNames.includes(n));
    const cols = t ? asked.map((n) => t.columns.indexOf(n)) : [];
    const given = cols.length ? asked : [];
    // A heading of PHREEQC's that a column of the table or a value drawn has too, pH say, said as PHREEQC's.
    const outHead = v.head.map((h) => (given.includes(h) || drawnNames.includes(h) ? `${h}, PHREEQC` : h));
    const fromTable = (row) => cols.map((k) => {
      const x = t.rows[row][k];
      return x !== '' && Number.isFinite(Number(x)) ? Number(x) : x;
    });
    const drawHead = v.draws ? ['draw', ...drawnNames] : [];
    const drawValues = (u) => (v.draws ? [u.draw + 1, ...u.drawn] : []);
    const out = (values) => v.head.map((_, k) => (values && values[k] !== undefined ? values[k] : null));
    const col = batchLowestColumn(v);
    let about = `the PHREEQC input each row of ${v.table} was run with, with ${v.database}`;
    if (v.draws) about += `, ${v.draws} draws a row of ${v.uncertain.map((u) => `${u.name} ${u.dist} ${u.x.join(' ')}`).join('; ')} from seed ${v.seed}`;
    if (!v.solids) {
      const head = ['row', ...given, ...drawHead, ...outHead, 'refused'];
      return { main: { head, rows: v.runs.map((r) => [r.row + 1, ...fromTable(r.row), ...drawValues(r), ...out(r.values), r.said]) }, runs: null, about };
    }
    const head = ['row', ...given, ...drawHead, 'solid', ...outHead, 'refused'];
    const refusedIn = (u) => u.refused.map((r) => `${r.solid}: ${r.said}`).join('; ') || null;
    // With solids for each element, a unit's lowest of every element and the solid that gave it.
    const lowHead = v.groups ? ['row', ...given, ...drawHead, ...v.groups.flatMap((g) => [`${g.el}: solid`, g.col]), 'refused'] : head;
    const lowest = batchUnits(v, col).map((u) => [u.row + 1, ...fromTable(u.row), ...drawValues(u),
      ...(v.groups ? v.groups.flatMap((g, gi) => (u.bests[gi] ? [u.bests[gi].solid, u.bests[gi].values[v.head.indexOf(g.col)]] : [null, null]))
        : [u.best ? u.best.solid : null, ...out(u.best && u.best.values)]), refusedIn(u)]);
    about += v.groups ? `, {solid} each of ${v.groups.map((g) => `${g.el}: ${g.solids.join(', ')}`).join('; ')} in turn, each element's lowest kept in its total`
      : `, {solid} each of ${v.solids.join(', ')} in turn, the lowest kept in ${col}`;
    return { main: { head: lowHead, rows: lowest },
      runs: { head, rows: v.runs.map((r) => [r.row + 1, ...fromTable(r.row), ...drawValues(r), r.solid, ...out(r.values), r.said]) }, about };
  }
  /** The batch kept, where there is one and it is not the one shown. */
  const batchKeptBeside = () => (pq.batchKept && pq.batchKept !== pq.batchResult ? pq.batchKept : null);
  /** Whether a batch has a result in column col: an element's total among its groups, or a column of its selected output. */
  const batchHas = (v, col) => (v.groups ? v.groups.some((g) => g.col === col) : v.head.includes(col));
  /** A spread's numbers in the order of batchSpreadRows: waters, smallest, the percentiles, largest, left out. */
  const batchSpreadValues = (x) => [x.n, x.min, x.p5, x.p50, x.p95, x.max, x.none];

  /**
    Every row the batch ran, each with the table's values the input asked for, with draws the draw and the values drawn,
    what PHREEQC gave and what it said where it refused. With solids: CSV the lowest for each unit and the solids refused
    in it, 'runs' every run, Excel both. The workbook has the spread's numbers on a sheet of their own, and where a batch
    is kept beside it, the kept one's table, input and spread too.
  */
  async function pqBatchSave(as) {
    const v = pq.batchResult;
    if (!v) { setStatus('Run a batch first: there is nothing to save yet.', 'warn'); return; }
    const tables = batchTables(v);
    const stem = `${fileStem()}_batch`;
    const csv = async (head, rows, name) => saidSaved(await saveBlob(new Blob([`${csvOf({ head, rows })}\n`], { type: 'text/csv' }), name));
    if (as === 'csv') { await csv(tables.main.head, tables.main.rows, v.solids ? `${stem}_lowest.csv` : `${stem}.csv`); return; }
    if (as === 'runs') { if (tables.runs) await csv(tables.runs.head, tables.runs.rows, `${stem}_runs.csv`); return; }
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') { setStatus('The Excel writer did not load; save as CSV instead.', 'error'); return; }
    const sheets = [[v.solids ? 'lowest' : 'batch', tables.main.head, tables.main.rows]];
    if (tables.runs) sheets.push(['runs', tables.runs.head, tables.runs.rows]);
    // The spread of the column chosen; with solids for each element, of every element's lowest, a column each; the kept
    // batch's beside them, where it has them.
    const col = batchLowestColumn(v);
    const kept = batchKeptBeside();
    const cols = v.groups ? v.groups.map((g) => g.col) : [col];
    const spreads = [
      ...cols.map((c) => [`${c}${batchLowestOf(v)}`, batchSpread(v, c)]),
      ...(kept ? cols.filter((c) => batchHas(kept, c)).map((c) => [`${c}, the batch kept`, batchSpread(kept, c)]) : []),
    ].filter(([, x]) => x);
    if (spreads.length) {
      const names = batchSpreadRows({ ...spreads[0][1], none: Math.max(...spreads.map(([, x]) => x.none)) || 0 }).map(([what]) => what);
      sheets.push(['spread', [`over the ${spreads[0][1].over}`, ...spreads.map(([h]) => h)],
        names.map((what, i) => [what, ...spreads.map(([, x]) => batchSpreadValues(x)[i])])]);
    }
    const xlsx = new XlsxWriter(`${stem}.xlsx`);
    for (const [name, head, rows] of sheets) xlsx.writeData(rows.map((r) => r.map((x) => (x === null ? '' : x))), name, { header: head });
    xlsx.writeData(v.text.split('\n').map((ln) => [ln]), 'input', { header: [tables.about] });
    if (kept) {
      const k = batchTables(kept);
      xlsx.writeData(k.main.rows.map((r) => r.map((x) => (x === null ? '' : x))), 'kept', { header: k.main.head });
      xlsx.writeData(kept.text.split('\n').map((ln) => [ln]), 'kept input', { header: [k.about] });
    }
    saidSaved(await saveBlob(await xlsx.save(), `${stem}.xlsx`));
  }

  /*
    A BATCH AS ONE PAGE, to keep or send: what was run -- the table, the rows,
    the database, PHREEQC's version, the solids, the values drawn, the input in
    full, and the batch kept beside it -- what came back -- the note, the
    spread's numbers, the solids and the rows as the tab shows them, its click
    handles left out -- and its charts as drawn, live, plotly.js in the file
    where it can be read, as a chart's own page has it. What is the batch's is
    escaped: the text as HTML, the charts as JSON written for a script.
  */
  async function pqBatchReport() {
    const v = pq.batchResult;
    if (!v) { setStatus('Run a batch first: there is nothing to report yet.', 'warn'); return; }
    const lib = await plotlyForPage();
    const c = themeColors();
    const many = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
    const col = batchLowestColumn(v);
    const kept = batchKeptBeside();
    const chosen = (id) => { const sel = $(id); return sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : ''; };
    // The charts as the tab draws them, those it shows.
    const charts = [
      [`The spread of ${col}${batchLowestOf(v)}`, 'rtmChartPqBatch', 340],
      [`${col} against ${chosen('rtmPqBatchX')}`, 'rtmChartPqBatchX', 360],
      [`The map over ${chosen('rtmPqBatchMapX')} and ${chosen('rtmPqBatchMapY')}`, 'rtmChartPqBatchMap', 480],
    ].map(([title, id, tall]) => {
      const plot = $(id);
      if (!plot || plot.hidden || plot.closest('[hidden]') || !plot.data || !plot.data.length) return null;
      const { width, height, ...rest } = plot.layout || {};
      return { title, tall, data: scriptJson(plot.data), layout: scriptJson({ ...rest, autosize: true }) };
    }).filter(Boolean);
    const bad = v.runs.filter((r) => !r.values).length;
    const rowsRun = new Set(v.runs.map((r) => r.row)).size;
    const settings = [
      ['Table', `${v.table}${v.sheet ? `, sheet ${v.sheet}` : ''}, ${many(v.source.rows.length, 'row')}`],
      ['Rows', `${v.rowsSpec || 'all'}: ${many(rowsRun, 'row')} run${v.stopped ? ', then stopped' : ''}`],
      ['Database', v.database],
      ['PHREEQC', v.version],
      ['Solids', v.groups ? v.groups.map((g) => `${g.el}: ${g.solids.join(', ')}`).join('; ') : v.solids ? v.solids.join(', ') : 'none'],
      ...(v.draws ? [['Uncertain', v.uncertain.map((u) => `${u.name} ${u.dist} ${u.x.join(' ')}`).join('; ')],
        ['Draws', `${v.draws} a row, from seed ${v.seed}`]] : []),
      [v.solids && !v.groups ? 'Lowest in' : 'Spread of', col],
      ['Runs', `${many(v.runs.length, 'run')} in ${v.seconds.toFixed(1)} s, ${bad.toLocaleString()} refused`],
    ];
    // The tables as the tab shows them, without what makes their rows clickable there.
    const out = $('rtmPqBatchOut').cloneNode(true);
    for (const tr of out.querySelectorAll('[data-on-click]')) {
      for (const a of ['data-on-click', 'data-row', 'data-draw']) tr.removeAttribute(a);
      tr.classList.remove('rtm-pq-batch-pick');
    }
    const stats = $('rtmPqBatchSpread').hidden ? '' : $('rtmPqBatchStats').outerHTML;
    const name = `${v.table.replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_')}_batch_report`;
    const title = `A batch over ${v.table}${v.sheet ? `, sheet ${v.sheet}` : ''}`;
    const day = new Date().toISOString().slice(0, 10);
    const version = (typeof Plotly !== 'undefined' && Plotly.version) || '';
    const config = scriptJson({ ...PLOT_CONFIG, toImageButtonOptions: { filename: name } });
    const library = !charts.length ? '' : lib && lib.text ? `<script>\n${lib.text}\n</script>`
      : lib ? `<script src="${esc(lib.src)}"${lib.integrity ? ` integrity="${esc(lib.integrity)}" crossorigin="anonymous"` : ''}></script>` : '';
    const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>
  html, body { margin: 0; background: ${esc(c.surface)}; color: ${esc(c.text)}; }
  body { font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1200px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
  h2 { font-size: 15px; font-weight: 600; margin: 24px 0 6px; }
  h3 { font-size: 13px; font-weight: 600; margin: 16px 0 4px; }
  p { margin: 0 0 8px; }
  .note { opacity: 0.8; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 3px 18px; margin: 0 0 10px; }
  dt { opacity: 0.75; }
  dd { margin: 0; }
  table { border-collapse: collapse; font-size: 12px; margin: 6px 0 12px; }
  th, td { padding: 2px 12px 2px 0; text-align: left; font-variant-numeric: tabular-nums; }
  thead th, thead td { border-bottom: 1px solid ${esc(c.grid)}; font-weight: 600; }
  td.rtm-pq-batch-error { border-left: 3px solid #e0731d; padding-left: 6px; }
  caption { text-align: left; font-weight: 600; padding-bottom: 4px; }
  .chart { width: 100%; }
  details { margin: 6px 0 10px; }
  summary { cursor: pointer; }
  pre { white-space: pre; overflow: auto; max-height: 420px; font: 12px/1.4 ui-monospace, Menlo, Consolas, monospace; }
  .made { margin-top: 18px; font-size: 12px; opacity: 0.7; }
</style>
</head>
<body>
<main>
<h1>${esc(title)}</h1>
<p class="note">${esc($('rtmPqBatchNote').textContent)}</p>
<h2>What was run</h2>
<dl>${settings.map(([k, x]) => `<dt>${esc(k)}</dt><dd>${esc(x)}</dd>`).join('')}</dl>
<details><summary>The PHREEQC input each row was run with</summary><pre>${esc(v.text)}</pre></details>
${kept ? `<p>${esc($('rtmPqBatchKeptText').textContent)}</p>
<details><summary>The kept batch's input</summary><pre>${esc(kept.text)}</pre></details>
` : ''}<h2>What came back</h2>
${charts.map((ch, i) => `<h3>${esc(ch.title)}</h3>\n<div class="chart" id="chart${i}" style="height:${ch.tall}px"></div>${i === 0 ? `\n${stats}` : ''}`).join('\n')}
${!charts.length && stats ? stats : ''}
<h3>The rows${v.solids ? ', each with the solid that gave the lowest' : ''}</h3>
${out.innerHTML}
<p class="made">Saved from rtm.html, kvotab.github.io/rtm.html, on ${day}: PHREEQC ${esc(v.version)} with ${esc(v.database)}${
  charts.length ? `; the charts drawn by plotly.js ${esc(version)} (MIT licence)${lib && lib.text ? ', which is in this file' : lib ? `, which this page loads from ${esc(new URL(lib.src).host)}` : ''}` : ''}.</p>
</main>
${library}
${charts.length ? `<script>\n${charts.map((ch, i) => `Plotly.newPlot('chart${i}', ${ch.data}, ${ch.layout}, ${config});`).join('\n')}\n</script>` : ''}
</body>
</html>
`;
    const saved = await saveBlob(new Blob([html], { type: 'text/html' }), `${name}.html`);
    if (!saved) return;
    if (!charts.length || (lib && lib.text)) setStatus(`Saved ${saved.name}: the batch as one page, to open in any browser.`, 'ok');
    else setStatus(`Saved ${saved.name}, linking plotly.js: it could not be read to go into the file, so the page needs the internet to draw its charts.`, 'warn');
  }

  /*
    A BATCH'S INPUT AS A FILE: the PHREEQC input, its settings above it as
    comments -- "# Solids: Calcite, Gypsum" -- so that the file is PHREEQC input
    still. Opened, the settings fill their fields, each the file does not give
    left empty, and leave the text; the table and the database it was saved
    with, which the page cannot open for it, are said where they are not the
    ones open. Saved, the settings are written afresh from the fields, any
    pasted into the text dropped, so that a file saved twice has them once.
  */
  const BATCH_HEAD = '# rtm.html batch settings:';
  const BATCH_KEYS = [['Table', null], ['Database', null], ['Rows', 'rows'], ['Solids', 'solids'], ['Uncertain', 'uncertain'],
    ['Draws', 'draws'], ['Seed', 'seed'], ['Lowest in', 'lowest'], ['Against', 'against']];
  /** The settings a batch input starts with, "# Key: value" among its first comments ("Spread of" read as "Lowest in"), and its text without them. */
  function batchSettingsOf(text) {
    const settings = {};
    const keep = [];
    let head = true;
    for (const line of String(text).replace(/\r\n?/g, '\n').split('\n')) {
      if (head && !/^\s*(#|$)/.test(line)) head = false;
      if (head) {
        if (line.trim() === BATCH_HEAD) continue;
        const m = /^\s*#\s*(Table|Database|Rows|Solids|Uncertain|Draws|Seed|Lowest in|Spread of|Against)\s*:\s*(.*?)\s*$/i.exec(line);
        if (m) {
          const said = m[1].toLowerCase() === 'spread of' ? 'lowest in' : m[1].toLowerCase();
          settings[BATCH_KEYS.find(([k]) => k.toLowerCase() === said)[0]] = m[2];
          continue;
        }
      }
      keep.push(line);
    }
    // The blank lines the settings stood among, at the top, go with them.
    while (keep.length && !keep[0].trim()) keep.shift();
    return { settings, text: keep.join('\n') };
  }
  /** The database the batch runs with, by name. */
  const batchDatabaseName = () => (pqDatabase() || { name: 'phreeqc.dat' }).name;
  /** The table open, as a batch input's settings name it. */
  const batchTableName = (t) => (t ? `${t.name}${t.sheet ? `, sheet ${t.sheet}` : ''}` : '');

  async function pqBatchInputChosen(ev) {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    let read;
    try {
      read = batchSettingsOf(await pqFileText(file));
    } catch (e) {
      setStatus(`${file.name} could not be read: ${e.message}`, 'error');
      return;
    }
    const { settings, text } = read;
    pq.batch.text = text;
    pq.batchStarter = null;
    for (const [key, field] of BATCH_KEYS) if (field) pq.batch[field] = settings[key] || '';
    pqSave();
    pqBatchRender();
    infoRefresh();
    // The column's name as the result's bar has it: Lowest in with solids, Spread of without.
    const said = (k) => (k === 'Lowest in' && !pq.batch.solids.trim() ? 'Spread of' : k);
    const given = BATCH_KEYS.filter(([k, f]) => f && settings[k]).map(([k]) => said(k));
    const other = [];
    if (settings.Table && settings.Table !== batchTableName(pq.batchTable)) other.push(`the table ${settings.Table}`);
    if (settings.Database && settings.Database !== batchDatabaseName()) other.push(`the database ${settings.Database}`);
    setStatus(`${file.name} opened: the input${given.length ? ` and its ${given.join(', ')}` : ''}.`
      + `${other.length ? ` It was saved for ${other.join(' and ')}; have ${other.length > 1 ? 'them' : 'it'} open before running.` : ''}`,
    other.length ? 'warn' : 'ok');
  }

  async function pqBatchSaveInput() {
    const text = batchSettingsOf(pq.batch.text).text.replace(/\s+$/, '');
    if (!text.trim()) { setStatus('Write or open an input first: there is nothing to save yet.', 'warn'); return; }
    const t = pq.batchTable;
    const values = { Table: batchTableName(t), Database: batchDatabaseName() };
    for (const [key, field] of BATCH_KEYS) if (field) values[key] = pq.batch[field];
    const said = (k) => (k === 'Lowest in' && !pq.batch.solids.trim() ? 'Spread of' : k);
    const head = [BATCH_HEAD, ...BATCH_KEYS.filter(([k]) => values[k]).map(([k]) => `# ${said(k)}: ${values[k]}`)];
    const stem = t ? t.name.replace(/\.[^.]+$/, '') : 'batch';
    saidSaved(await saveBlob(new Blob([`${head.join('\n')}\n\n${text}\n`], { type: 'text/plain' }), `${stem}_batch_input.txt`));
  }

  async function pqWaterChosen(ev) {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    pq.water = await pqFileText(file);
    $('rtmPqWater').value = pq.water;
    pqSave();
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'rtm:run': () => { run(); },
    'rtm:keepRun': () => keepRun(),
    'rtm:beside': (ev, el) => {
      besideId = Number(el.value) || null;
      drawTime();
      drawProfile();
      drawGradient();
      drawComp();
      if (state.tab === 'fit') drawFit();
    },
    'rtm:stop': () => stop(),
    'rtm:verify': () => { verify(); },
    'rtm:tab': (ev, el) => showTab(el.dataset.tab),
    'rtm:full': () => setFull(!document.documentElement.classList.contains('rtm-full')),
    'rtm:redraw': () => {
      const cell = $('rtmCell').value;
      state.cell = isFace(cell) ? cell : (Number(cell) || 0);
      state.cells = $('rtmCells').value;
      state.layer = Number($('rtmLayer').value) || 0;
      // An end has no layer to pick; the cells listed in Cells have.
      $('rtmLayerWrap').hidden = !(state.compiled && state.compiled.matrix) || (isFace(state.cell) && !cellsAsked().cells.length);
      state.yFrom = $('rtmYFrom').value;
      saveState();
      drawTime();
    },
    // Where each curve is half-way and what has come out of the column, under Against time.
    'rtm:btc': (ev, el) => {
      state.btc = !!el.checked;
      saveState();
      drawTime();
    },
    'rtm:every': (ev, el) => {
      state.every = !!el.checked;
      saveState();
      drawTime();
    },
    // A species in the table ticked, or unticked, as in the list.
    'rtm:everyPick': (ev, el) => {
      const name = el.dataset.key;
      if (state.picked.includes(name)) state.picked = state.picked.filter((x) => x !== name);
      else state.picked.push(name);
      renderSeriesList();
      saveState();
      drawTime();
    },
    'rtm:everyCopy': () => copyEvery(),
    // The run solved again more carefully and set against itself; and run again with that setting.
    'rtm:checkRun': () => { checkRun(); },
    'rtm:checkUse': () => checkUse(),
    // One time axis for Against time, Against distance and Gradient: the three selects as one.
    'rtm:timeIn': (ev, el) => {
      const before = timeAxis();
      const shownBefore = shownTime();
      // The model's own unit is no choice of its own: it follows the model.
      const v = el.value;
      state.timeIn = v === 'pv' || (SHOW_UNITS.some(([sym]) => sym === v) && v !== timeUnit().symbol) ? v : '';
      const after = timeAxis();
      const shownAfter = shownTime();
      // The same picture on the other axis: each "from" and the Times' bare numbers put on it; Composition's too.
      if (before.per !== after.per) retypeTimes(before, after);
      if (shownBefore.per !== shownAfter.per) retypeShown(shownBefore, shownAfter);
      // The panel says how long the run is, and a travel time: in the unit shown, written again.
      if (shownBefore.per !== shownAfter.per) renderFacts();
      renderTimeIn();
      saveState();
      drawTime();
      drawProfile();
      drawGradient();
    },
    // Against distance at the slider's one time; play moves it on through the run.
    'rtm:profileAt': (ev, el) => {
      const r = state.result;
      if (!r) return;
      profileStop();
      state.profileAt = r.t[Math.max(0, Math.min(r.n - 1, Math.round(Number(el.value)) || 0))];
      drawProfile();
    },
    'rtm:profileAtDone': () => saveState(),
    'rtm:profilePlay': () => profilePlay(),
    'rtm:profilePace': (ev, el) => {
      state.profilePace = PROFILE_PACES.includes(el.value) ? el.value : '10';
      saveState();
      // At the new pace from where it is.
      if (profilePlaying) { profileStop(); profilePlay(); }
    },
    'rtm:profileAll': () => {
      profileStop();
      state.profileAt = null;
      saveState();
      drawProfile();
    },
    // One unit for every chart of concentrations and the listing: the four selects as one.
    'rtm:concUnit': (ev, el) => {
      state.concUnit = CONC_UNITS[el.value] ? el.value : '';
      renderUnits();
      saveState();
      drawTime();
      drawProfile();
      drawGradient();
      drawComp();
    },
    'rtm:redrawGradient': () => {
      state.gradSpecies = $('rtmGradSpecies').value;
      state.gradLayer = Number($('rtmGradLayer').value) || 0;
      state.gradScale = $('rtmGradScale').value;
      state.gradView = $('rtmGradView').value;
      state.gradTMin = $('rtmGradTMin').value;
      state.gradCFrom = $('rtmGradCFrom').value;
      saveState();
      drawGradient();
      infoRefresh();
    },
    'rtm:redrawProfile': () => {
      state.profileSpecies = $('rtmProfileSpecies').value;
      const axis = $('rtmProfileAxis').value;
      // Switching what the picker means resets what it points at.
      if (axis !== state.profileAxis) { state.profileAxis = axis; state.profileLayer = 0; renderLayerPickers(); }
      else state.profileLayer = Number($('rtmProfileLayer').value) || 0;
      // Times typed: the Times again, not the slider's.
      if ($('rtmProfileTimes').value !== state.profileTimes) { profileStop(); state.profileAt = null; }
      state.profileTimes = $('rtmProfileTimes').value;
      state.profileYFrom = $('rtmProfileYFrom').value;
      saveState();
      drawProfile();
    },
    'rtm:redrawComp': () => {
      state.compView = $('rtmCompView').value;
      state.compElement = $('rtmCompElement').value;
      state.compIn = $('rtmCompIn').value;
      state.compAs = $('rtmCompAs').value;
      state.compAlong = $('rtmCompAlong').value;
      state.compCell = Number($('rtmCompCell').value) || 0;
      state.compLayer = Number($('rtmCompLayer').value) || 0;
      // At typed: At again, not the slider's.
      if ($('rtmCompTimes').value !== state.compTimes) { compStop(); state.compAt = null; }
      state.compTimes = $('rtmCompTimes').value;
      state.compTMin = $('rtmCompTMin').value;
      state.compPcaVars = $('rtmCompPcaVars').value.trim();
      state.compPcaLog = $('rtmCompPcaLog').checked;
      state.compBeside = $('rtmCompBeside').checked;
      state.compBudgetOf = $('rtmCompBudgetOf').value;
      state.compBudgetBy = ['lines', 'flows'].includes($('rtmCompBudgetBy').value) ? $('rtmCompBudgetBy').value : 'where';
      { const at = $('rtmCompBudgetAt').value; state.compBudgetAt = at === '' || at === 'column' ? 'column' : Number(at); }
      saveState();
      renderComp();
      drawComp();
      infoRefresh();
    },
    // The Composition tab at the slider's one time; play moves it on through the run.
    'rtm:compAt': (ev, el) => {
      const r = state.result;
      if (!r) return;
      compStop();
      state.compAt = r.t[Math.max(0, Math.min(r.n - 1, Math.round(Number(el.value)) || 0))];
      drawComp();
    },
    'rtm:compAtDone': () => saveState(),
    'rtm:compPlay': () => compPlay(),
    'rtm:compPace': (ev, el) => {
      state.compPace = PROFILE_PACES.includes(el.value) ? el.value : '10';
      saveState();
      if (compPlaying) { compStop(); compPlay(); }
    },
    'rtm:compAll': () => {
      compStop();
      state.compAt = null;
      saveState();
      drawComp();
    },
    'rtm:dgSettings': () => { readDg(); saveState(); renderDg(); infoRefresh(); },
    'rtm:dgGo': () => { readDg(); saveState(); renderDg(); dgGo(); },
    'rtm:dgRedraw': () => {
      const d = state.dg;
      d.show = $('rtmDgShow').value;
      d.el = $('rtmDgEl').value;
      d.in = $('rtmDgIn').value;
      d.q = $('rtmDgQ').value;
      d.satAt = Number($('rtmDgSat').value) || 0;
      saveState();
      renderDgShow();
      drawDg();
      infoRefresh();
    },
    'rtm:swSettings': () => { readSw(); saveState(); renderSw(); infoRefresh(); },
    'rtm:swGo': () => { readSw(); saveState(); renderSw(); swGo(); },
    'rtm:swRedraw': () => {
      const w = state.sw;
      w.show = $('rtmSwShow').value;
      w.key = $('rtmSwKey').value;
      w.of = $('rtmSwOf').value;
      w.logT = $('rtmSwLogT').checked;
      saveState();
      renderSwShow();
      drawSw();
      infoRefresh();
    },
    'rtm:fitSettings': () => { readFit(); saveState(); renderFit(); infoRefresh(); },
    'rtm:fitAdd': () => {
      readFit();
      if (state.fit.params.length < FIT_MAX) state.fit.params.push({ what: '', start: '' });
      // A new row takes the first choice not fitted already.
      const taken = new Set(state.fit.params.map((p) => p.what));
      const next = nextChoice(taken);
      const row = state.fit.params[state.fit.params.length - 1];
      if (!row.what && next) row.what = next;
      saveState();
      renderFit();
    },
    'rtm:fitRemove': (ev, el) => {
      readFit();
      state.fit.params.splice(Number(el.dataset.row), 1);
      saveState();
      renderFit();
    },
    'rtm:fitGo': () => { readFit(); saveState(); renderFit(); fitGo(); },
    'rtm:fitRedraw': () => { drawFit(); },
    'rtm:fitApply': () => fitApply(),
    'rtm:unSettings': () => { readUn(); saveState(); renderUn(); infoRefresh(); },
    'rtm:unAdd': () => {
      readUn();
      const taken = new Set(state.unc.rows.map((r) => r.what));
      const next = nextChoice(taken);
      if (next && state.unc.rows.length < UN_MAX) state.unc.rows.push({ what: next, ...unDefault(next) });
      saveState();
      renderUn();
    },
    'rtm:unRemove': (ev, el) => {
      readUn();
      state.unc.rows.splice(Number(el.dataset.row), 1);
      saveState();
      renderUn();
    },
    'rtm:unFromFit': () => unFromFit(),
    'rtm:unGo': () => { readUn(); saveState(); renderUn(); unGo(); },
    'rtm:unRedraw': () => {
      const u = state.unc;
      u.show = $('rtmUnShow').value;
      u.key = $('rtmUnKey').value;
      u.of = $('rtmUnOf').value;
      saveState();
      renderUnShow();
      drawUn();
      infoRefresh();
    },
    'rtm:pick': (ev, el) => {
      const name = el.value;
      if (el.checked) { if (!state.picked.includes(name)) state.picked.push(name); }
      else state.picked = state.picked.filter((x) => x !== name);
      el.closest('.rtm-item').classList.toggle('on', el.checked);
      saveState();
      drawTime();
    },
    'rtm:toggleGroup': (ev, el) => {
      const g = el.dataset.group;
      const open = el.getAttribute('aria-expanded') !== 'true';
      state.sections[`series:${g}`] = open;
      saveState();
      renderSeriesList();
    },
    'rtm:clearSeries': () => {
      state.picked = [];
      renderSeriesList();
      saveState();
      drawTime();
    },
    'rtm:downloadCsv': () => downloadCsv(),
    'rtm:export': (ev, el) => { exportPane(el.dataset.pane, el.dataset.as); },
    'rtm:toHdf5': () => { viewInHdf5Browser(); },
    'rtm:downloadHdf5': () => downloadHdf5(),
    'rtm:solverChanged': () => { readSolverControls(); updateSolverOptions(); saveState(); infoRefresh(); },
    'rtm:aboutMore': () => {
      aboutOpen = !aboutOpen;
      renderAbout();
      // The button is drawn anew: the reader's focus goes back to it.
      const btn = $('rtmAbout').querySelector('.rtm-about-more');
      if (btn) btn.focus();
    },
    'rtm:more': () => {
      const open = !state.sections[ADVANCED_KEY];
      state.sections[ADVANCED_KEY] = open;
      showAdvanced(open);
      saveState();
    },
    'rtm:textChanged': () => {
      state.text = $('rtmText').value;
      // Typing goes on with this text: the offer of the one put aside goes, the picker keeps it.
      showAside(null);
      // Synchronously, not on the compile's timer: the textarea's own text is
      // transparent while the colouring is on, so the coloured copy is what
      // the reader is watching themselves type.
      renderHighlight();
      scheduleCompile(400);
    },
    'rtm:syntaxToggle': (ev, el) => { state.syntax = !!el.checked; applySyntaxMode(); saveState(); },
    'rtm:lineNumbersToggle': (ev, el) => { state.lineNumbers = !!el.checked; applyLineNumbers(); saveState(); },
    'rtm:applyModel': () => { state.text = $('rtmText').value; scheduleCompile(0); },
    'rtm:resetModel': () => {
      const kept = putAside(RTM_DEFAULT_MODEL);
      setOpened({ text: RTM_DEFAULT_MODEL, kind: 'reset' });
      state.text = RTM_DEFAULT_MODEL;
      state.modelName = null;
      $('rtmText').value = state.text;
      renderHighlight();
      state.picked = [];
      showAside(kept);
      scheduleCompile(0);
    },
    'rtm:chooseExample': (ev, el) => {
      if (el.value.startsWith('aside:')) bringBack(Number(el.value.slice(6)));
      else chooseExample(el.value);
    },
    'rtm:bringBack': () => bringBack(0),
    'rtm:goLine': (ev, el) => goLine(Number(el.dataset.line)),
    'rtm:fixName': (ev, el) => fixName(Number(el.dataset.line), el.dataset.from, el.dataset.to),
    'rtm:goUse': (ev, el) => goUse(Number(el.dataset.line)),
    'rtm:changesToggle': () => { changesOpen = !changesOpen; showChanges(); },
    'rtm:changesCopy': () => copyChanges(),
    // Every line of the name's listed, until the caret goes to another name.
    'rtm:usesMore': () => {
      if (usesNow) usesOpen = `${usesNow.kind}|${usesNow.name}`;
      usesDrawn = null;
      showUses();
    },
    // Ready to save: its Save… a click of its own for the dialog to open out of; Cancel, or Escape, an answer.
    'rtm:saveReadyGo': () => {
      const r = saveReady;
      if (!r) return;
      r.asked = true;
      $('rtmSaveReady').close();
      window.showSaveFilePicker(r.options).then(r.resolve, r.reject);
    },
    'rtm:saveReadyCancel': () => $('rtmSaveReady').close(),
    'rtm:loadFile': () => $('rtmFile').click(),
    'rtm:fileChosen': (ev) => { fileChosen(ev); },
    'rtm:saveFile': () => saveFile(),
    'rtm:pqPanel': () => { pqShowPanel(!pq.open); pqSave(); },
    'rtm:pqWaterEdited': () => { pq.water = $('rtmPqWater').value; pqSave(); },
    'rtm:pqOpenWater': () => $('rtmPqWaterFile').click(),
    'rtm:pqWaterChosen': (ev) => { pqWaterChosen(ev); },
    'rtm:pqExample': () => {
      pq.water = PQ_EXAMPLE;
      $('rtmPqWater').value = PQ_EXAMPLE;
      pqSave();
    },
    'rtm:pqDbChosen': (ev, el) => {
      if (el.value === '__open') {
        pqRenderDatabases();
        $('rtmPqDbFile').click();
        return;
      }
      pq.db = el.value;
      pq.missingDb = null;
      pqRenderDatabases();
      pqSave();
      infoRefresh();
    },
    'rtm:pqDbFileChosen': (ev) => { pqDatabaseChosen(ev); },
    'rtm:pqSettings': () => { pqReadControls(); infoRefresh(); },
    'rtm:pqWrite': () => { pqWrite(); },
    'rtm:pqView': () => { pqView(); },
    'rtm:pqRedraw': () => {
      pq.cell = Number($('rtmPqCell').value) || 0;
      pq.logT = $('rtmPqLogT').checked;
      pq.mode = $('rtmPqMode').value === 'distance' ? 'distance' : 'time';
      pq.at = Number($('rtmPqTime').value);
      pqSave();
      // The controls follow the choice: a cell against time, a time against distance.
      if (pq.view) pqRenderView(); else pqDraw();
    },
    'rtm:pqCsv': () => pqCsv(),
    'rtm:pqInvSettings': () => { pqInvRead(); pqInvRender(); infoRefresh(); },
    'rtm:pqInverse': () => { pqInverse(); },
    'rtm:pqInvCsv': () => pqInvCsv(),
    // A batch over a table of waters.
    'rtm:pqBatchOpen': () => $('rtmPqBatchFile').click(),
    'rtm:pqBatchFileChosen': (ev) => { pqBatchFileChosen(ev); },
    'rtm:pqBatchSheet': (ev, el) => {
      const t = pq.batchTable;
      if (!t || !t.book) return;
      pq.batchTable = batchTableOf(batchSheetRows(t.book, el.value), t.name, { book: t.book, sheets: t.sheets, sheet: el.value });
      // The start the page wrote, not yet touched, follows the sheet.
      if (pq.batchStarter && pq.batch.text === pq.batchStarter && pq.batchTable.columns.length) {
        pq.batch.text = batchStarter(pq.batchTable.columns);
        pq.batchStarter = pq.batch.text;
        pqSave();
      }
      pqBatchRender();
    },
    'rtm:pqBatchSettings': () => {
      pq.batch.text = $('rtmPqBatchText').value;
      pq.batch.rows = $('rtmPqBatchRows').value.trim();
      pq.batch.solids = $('rtmPqBatchSolids').value.trim();
      pq.batch.uncertain = $('rtmPqBatchUncertain').value.trim();
      pq.batch.draws = $('rtmPqBatchDraws').value.trim();
      pq.batch.seed = $('rtmPqBatchSeed').value.trim();
      pqSave();
      pqBatchRender();
      infoRefresh();
    },
    // The batch as one page: what was run, what came back, its charts.
    'rtm:pqBatchReport': () => { pqBatchReport(); },
    // A batch kept, for the next ones to be drawn beside; let go.
    'rtm:pqBatchKeep': () => {
      if (!pq.batchResult) return;
      pq.batchKept = pq.batchResult;
      pqBatchDraw();
      setStatus('This batch is kept: the next one you run is drawn beside it.', 'ok');
    },
    'rtm:pqBatchForget': () => { pq.batchKept = null; pqBatchDraw(); },
    // One water of the batch in full, from a row of its table; saved; put away.
    'rtm:pqBatchLook': (ev, el) => { pqBatchLook(Number(el.dataset.row), el.dataset.draw === '' ? null : Number(el.dataset.draw)); },
    'rtm:pqBatchLookSave': () => { pqBatchLookSave(); },
    'rtm:pqBatchLookClose': () => { pq.batchLook = null; pqBatchLookDraw(false); },
    // The two columns the map is drawn over; '-' for none.
    'rtm:pqBatchMapAxes': () => {
      pq.batch.mapX = $('rtmPqBatchMapX').value;
      pq.batch.mapY = $('rtmPqBatchMapY').value;
      pqSave();
      pqBatchMap();
    },
    // What the second chart draws the result against.
    'rtm:pqBatchX': (ev, el) => {
      pq.batch.against = el.value;
      pqSave();
      pqBatchAgainst();
    },
    // The column whose lowest each row of a batch with solids shows.
    'rtm:pqBatchLowest': (ev, el) => {
      pq.batch.lowest = el.value;
      pqSave();
      pqBatchDraw();
    },
    'rtm:pqBatchOpenInput': () => $('rtmPqBatchInputFile').click(),
    'rtm:pqBatchInputChosen': (ev) => { pqBatchInputChosen(ev); },
    'rtm:pqBatchSaveInput': () => { pqBatchSaveInput(); },
    'rtm:pqBatchRun': () => { pqBatchRun(); },
    'rtm:pqBatchSave': (ev, el) => { pqBatchSave(el.dataset.as); },
  });

  /*
    THE LIST ON AGAINST TIME, AS TALL AS IT IS DRAGGED. The browser's own
    resize corner sets its height; the cap that keeps it short until then is
    lifted as a drag on that corner begins, from the height it has, so that
    the drag can take it anywhere. The height a drag leaves is kept, for the
    next visit too.
  */
  function initSeriesResize() {
    const list = $('rtmSeries');
    const apply = () => {
      list.classList.toggle('sized', state.seriesHeight > 0);
      list.style.height = state.seriesHeight > 0 ? `${state.seriesHeight}px` : '';
    };
    const atCorner = (ev) => {
      const b = list.getBoundingClientRect();
      return ev.clientX >= b.right - 18 && ev.clientY >= b.bottom - 18;
    };
    list.addEventListener('pointerdown', (ev) => {
      if (!atCorner(ev)) return;
      list.style.height = `${list.getBoundingClientRect().height}px`;
      list.classList.add('sized');
    });
    // A double click on the corner gives it back its own height.
    list.addEventListener('dblclick', (ev) => {
      if (!atCorner(ev)) return;
      state.seriesHeight = 0;
      apply();
      saveState();
    });
    // What the drag left, once it has stopped moving: a list sized, whose height changes, is kept at it.
    let keep = null;
    new ResizeObserver(() => {
      if (!list.classList.contains('sized') || !list.offsetHeight) return;
      clearTimeout(keep);
      keep = setTimeout(() => {
        const h = Math.round(list.getBoundingClientRect().height);
        if (h > 0 && h !== state.seriesHeight) { state.seriesHeight = h; saveState(); }
      }, 300);
    }).observe(list);
    apply();
  }

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  loadState();
  loadAside();
  migrateStoredText();
  // What the text is compared with: kept from the last visit, else the built-in model or the text as it now is.
  loadOpened();
  if (!opened) setOpened(state.text === RTM_DEFAULT_MODEL ? { text: state.text, kind: 'builtin' } : { text: state.text, kind: 'loaded' });
  $('rtmText').value = state.text;
  // scroll does not bubble, so it cannot be delegated like the rest.
  $('rtmText').addEventListener('scroll', () => {
    const pre = $('rtmHighlight');
    const ta = $('rtmText');
    if (pre && state.syntax) { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft; }
    if (state.lineNumbers) $('rtmLineNos').firstElementChild.style.transform = `translateY(${-ta.scrollTop}px)`;
  }, { passive: true });
  // Where the caret is: the name it is on, and where that is used (showUses). selectionchange comes to the
  // document, or to the textarea itself in the browsers that send it there; the rest are for those that send neither.
  for (const type of ['keyup', 'mouseup', 'focus', 'select', 'selectionchange']) {
    $('rtmText').addEventListener(type, scheduleUses);
  }
  document.addEventListener('selectionchange', () => {
    if (document.activeElement === $('rtmText')) scheduleUses();
  });
  applySyntaxMode();
  applyLineNumbers();
  renderExamples();
  $('rtmProfileTimes').value = state.profileTimes;
  writeSolverControls();
  updateSolverOptions();
  initSideResize();
  initFootResize();
  initSeriesResize();
  // Ready to save, closed without its Save…: a cancel.
  $('rtmSaveReady').addEventListener('close', () => {
    const r = saveReady;
    saveReady = null;
    if (r && !r.asked) r.reject(new DOMException('The file was not saved.', 'AbortError'));
  });
  initSections();
  initDrop();
  fullState();
  showAdvanced(!!state.sections[ADVANCED_KEY]);
  $('rtmGradScale').value = state.gradScale;
  $('rtmGradView').value = state.gradView;
  $('rtmGradTMin').value = state.gradTMin;
  $('rtmYFrom').value = state.yFrom;
  $('rtmProfileYFrom').value = state.profileYFrom;
  $('rtmGradCFrom').value = state.gradCFrom;
  $('rtmCells').value = state.cells;
  renderUnits();
  renderTimeIn();
  // The (i)s: "Read more in Help" shows the Help tab, and kvot-info.js then
  // scrolls it to the heading.
  if (typeof KvotInfo !== 'undefined') KvotInfo.setup({ topics: TOPICS, onMore: () => showTab('help') });
  setupMenus();
  pqLoad();
  pqWriteControls();
  if (pq.missingDb) {
    pqReport(`<p class="warn">${esc(pq.missingDb)} was the database last time. A database you open is not kept `
      + 'between visits, so phreeqc.dat is in use until it is opened again.</p>');
  }
  showTab(['profile', 'gradient', 'composition', 'diagram', 'sweep', 'fit', 'uncertainty', 'phreeqc', 'model', 'jacobian', 'help']
    .includes(state.tab)
    ? state.tab : 'time');
  window.addEventListener('resize', resize);
  compile();
}());
