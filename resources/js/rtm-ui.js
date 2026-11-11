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
  const WORKER_URL = 'resources/js/rtm-worker-entry.js?v=20261111f';
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
    // What time is shown in on Against time, Against distance and Gradient: '' the model's own unit, 'pv' pore volumes.
    timeIn: '',
    // Against time at several cells: the list typed in Cells; empty for the one cell Cell chooses.
    cells: '',
    // Under Against time, where each curve is half-way and what has gone out of the column (breakthrough numbers).
    btc: false,
    // The composition tab: what it shows, of which element, in what, as what, along the run or the column, where.
    compView: 'where',
    compBeside: false,     // the water as PHREEQC lists it, with PHREEQC's own numbers beside
    compBudgetOf: '',      // a budget over the run: 'element:Ca' or 'species:X'
    compBudgetBy: 'where', // by where it is held, or by each <REACTIONS> line ('lines')
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
      y: { kind: '', sp: '', from: '-12', to: '16', n: '41' },
      show: 'shares', el: '', in: 'water', q: '',
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
    sideWidth: null,
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
        tab: state.tab, syntax: state.syntax, sideWidth: state.sideWidth, sections: state.sections,
        layer: state.layer, profileAxis: state.profileAxis, profileLayer: state.profileLayer,
        gradLayer: state.gradLayer,
        profileSpecies: state.profileSpecies, profileTimes: state.profileTimes, profileAt: state.profileAt, profilePace: state.profilePace,
        gradSpecies: state.gradSpecies, gradScale: state.gradScale, gradView: state.gradView,
        gradTMin: state.gradTMin, yFrom: state.yFrom, profileYFrom: state.profileYFrom, gradCFrom: state.gradCFrom,
        concUnit: state.concUnit, timeIn: state.timeIn, cells: state.cells, btc: state.btc,
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
      if (s.timeIn === '' || s.timeIn === 'pv') state.timeIn = s.timeIn;
      if (typeof s.cells === 'string') state.cells = s.cells;
      if (typeof s.btc === 'boolean') state.btc = s.btc;
      if (['where', 'listing', 'budget', 'piper', 'durov', 'schoeller', 'stiff', 'ussl', 'wilcox', 'pca'].includes(s.compView)) state.compView = s.compView;
      if (typeof s.compElement === 'string') state.compElement = s.compElement;
      if (typeof s.compBeside === 'boolean') state.compBeside = s.compBeside;
      if (typeof s.compBudgetOf === 'string') state.compBudgetOf = s.compBudgetOf;
      if (s.compBudgetBy === 'where' || s.compBudgetBy === 'lines') state.compBudgetBy = s.compBudgetBy;
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
          if (['pH', 'pe', 'Eh', 'la', 'ratio', 'tot', ...(key === 'y' ? ['', 'pHheld'] : [])].includes(ax.kind)) d[key].kind = ax.kind;
          for (const f of ['sp', 'from', 'to', 'n']) if (typeof ax[f] === 'string') d[key][f] = ax[f];
        }
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
   * A time in the model's own unit, written for a person.
   *
   * Scaled up the ladder when that reads better -- 5000 s is 1.39 h -- but
   * never below the model's own unit: a model written in years has nothing to
   * say about seconds, and "3.16e7 s" where the reader wrote 1 would answer a
   * question nobody asked.
   */
  const fmtTime = (t) => {
    const u = timeUnit();
    const s = t * u.seconds;
    const ladder = [[1, 's'], [60, 'min'], [3600, 'h'], [86400, 'd'], [365.25 * 86400, 'a']];
    let pick = Math.max(0, ladder.findIndex(([sec]) => sec === u.seconds));
    while (pick + 1 < ladder.length && Math.abs(s) >= ladder[pick + 1][0]) pick++;
    return `${(s / ladder[pick][0]).toPrecision(3)} ${ladder[pick][1]}`;
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
   * PV is pore volumes, where the water flows; inPv reads a bare number in
   * them too, as on a time axis shown in pore volumes (timeAxis).
   */
  function parseTimes(text, inPv = false) {
    const glued = String(text).replace(/(\d)\s+(s|min|h|d|a|y|pv)\b/gi, '$1$2');
    const times = [];
    const bad = [];
    const own = timeUnit().seconds;
    const tw = poreTime();
    for (const tok of glued.split(/[\s,;]+/).filter(Boolean)) {
      const m = /^([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(s|min|h|d|a|y|pv)?$/i.exec(tok);
      if (!m) { bad.push(tok); continue; }
      const unit = m[2] ? m[2].toLowerCase() : '';
      if (unit === 'pv' || (!unit && inPv)) {
        if (tw > 0) times.push(Number(m[1]) * tw);
        else bad.push(tok);
        continue;
      }
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
    TIME IN PORE VOLUMES, on Against time, Against distance and Gradient
    (Time in): the model's own unit, or -- where the water flows -- the pore
    volumes that have flowed into the column, t/t_w, t_w the time the water
    takes to cross it: TRAVEL_TIME, or LENGTH over the pore-water speed
    |VELOCITY|/POROSITY. The flow is one number for the whole run, so a pore
    volume is a fixed length of time and the axis is the time axis scaled. A
    run kept beside counts in its own: two runs at different speeds line up.
  */
  /** A pore volume of run r -- the time its water takes to cross the column, in its model's unit -- or 0 where it does not flow. */
  function poreTime(r = state.result) {
    const m = r ? r.model : state.compiled;
    return m && m.transport && m.travelTime > 0 ? m.travelTime : 0;
  }
  /**
   * The time axis run r is shown on: { pv, tw, sym, title, why } -- pv whether in pore volumes, tw a pore volume (0 where
   * the water does not flow), sym what a number on it is in, why the note's words where pore volumes are chosen and r has none.
   */
  function timeAxis(r = state.result) {
    const tw = poreTime(r);
    const sym = timeUnit().symbol;
    if (state.timeIn === 'pv' && tw > 0) return { pv: true, tw, sym: 'PV', title: 'pore volumes', why: '' };
    const m = r ? r.model : state.compiled;
    return { pv: false, tw, sym, title: `time (${sym})`,
      why: state.timeIn === 'pv' && m ? `time in ${timeUnit().name}s: ${m.transport ? 'the water does not flow' : 'a batch has no pore volumes'}` : '' };
  }
  /** Run r's stored times on the axis: its own, or its pore volumes, kept with the run. */
  function axisTimes(r, ax) {
    if (!ax.pv) return r.t;
    if (!r.pvAxis || r.pvAxis.tw !== ax.tw) r.pvAxis = { tw: ax.tw, x: Float64Array.from(r.t, (t) => t / ax.tw) };
    return r.pvAxis.x;
  }
  /** A time of the run, in the model's unit, for a person on the axis: 1.25 PV, or as fmtTime writes it. */
  const fmtOnAxis = (ax, t) => (ax.pv ? `${(t / ax.tw).toPrecision(3)} PV` : fmtTime(t));
  /** A number on the axis -- a "from" -- for a person. */
  const fmtAxisNumber = (ax, v) => (ax.pv ? `${Number(v.toPrecision(3))} PV` : fmtTime(v));

  // The Time in selects, on Against time, Against distance and Gradient, as one: what the run on show can be shown in.
  const TIME_SELECTS = ['rtmTimeInTime', 'rtmTimeInProfile', 'rtmTimeInGrad'];
  function renderTimeIn() {
    const r = state.result || (state.compiled ? { model: state.compiled } : null);
    const flows = poreTime(r) > 0;
    const html = `<option value="">${esc(timeUnit().name)}s</option>`
      + `<option value="pv"${flows ? '' : ' disabled'}>pore volumes${flows ? '' : ', where the water flows'}</option>`;
    const ax = timeAxis(r);
    for (const id of TIME_SELECTS) {
      const sel = $(id);
      if (!sel) continue;
      sel.innerHTML = html;
      sel.value = ax.pv ? 'pv' : '';
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
    const turn = (v) => {
      const t = from.pv ? v * from.tw : v;
      const x = Number((to.pv ? t / to.tw : t).toPrecision(6));
      return x !== 0 && (Math.abs(x) < 1e-3 || Math.abs(x) >= 1e6) ? x.toExponential() : String(x);
    };
    for (const id of ['rtmTMin', 'rtmGradTMin']) {
      const el = $(id);
      const v = Number(el.value);
      if (el.value.trim() && Number.isFinite(v)) el.value = turn(v);
    }
    state.gradTMin = $('rtmGradTMin').value;
    const times = $('rtmProfileTimes');
    times.value = times.value.replace(/(^|[\s,;])([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(?!\s*(?:s|min|h|d|a|y|pv)\b)(?=$|[\s,;])/gi,
      (all, lead, num) => `${lead}${turn(Number(num))}`);
    state.profileTimes = times.value;
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
      }
      $('rtmModelNote').textContent = m.warnings.join('  ');
      $('rtmModelNote').hidden = !m.warnings.length;
      infoRefresh();
      return true;
    } catch (e) {
      state.compiled = null;
      state.compileError = e;
      renderFacts();
      infoRefresh();
      if (!state.running) setStatus(`The model does not compile: ${e.message}${note}`, 'error');
      return false;
    }
  }

  function renderFacts() {
    const el = $('rtmFacts');
    const m = state.compiled;
    if (!m) { el.textContent = state.compileError ? 'Does not compile; see the Model tab.' : 'Not compiled yet.'; return; }
    const s = m.settings;
    const bits = [
      `${s.MODE === 'transport' ? 'transport' : 'batch'} · ${m.nspecies} species · ${m.nreactions} reactions`,
    ];
    if (m.transport) {
      // The layout in words: its kind, the number that shapes it, and a
      // pinned surface layer when there is one.
      const g = m.grid || { kind: s.GRID };
      const shape = g.kind === 'log' ? `log grid, last cell ${g.ratio}× the first`
        : g.kind === 'powerlaw' ? `power-law grid, exponent ${g.power}`
          : g.kind === 'faces' ? 'faces as given' : `${g.kind} grid`;
      bits.push(`${m.fracture} cells over ${m.length != null ? m.length : s.LENGTH} m, ${shape}`
        + (g.surface > 0 ? `, surface layer ${g.surface} m` : ''));
      if (m.matrix) {
        const x = m.matrix;
        // How the layers came out: the first, how they grow, and why the
        // first is what it is -- the thing a reader most needs to see of a
        // layout worked out for them.
        const why = { matched: 'worked out from the path', e: 'FARFCOMP’s rule', given: 'MATRIX_FIRST' }[x.rule] || '';
        bits.push(`dual porosity: ${x.n} matrix layer${x.n === 1 ? '' : 's'} to `
          + `${x.total} m behind each cell, ${x.grid}: the first ${fmtLength(x.thickness[0])} (${why})`
          + (x.n > 1 ? `, growing by ${x.ratio.toFixed(3)}` : '')
          + `; porosity ${x.porosity}, ${fmtNumber(x.aw)} m² of wall per m³ of water`
          + (x.enters.length ? ` · ${x.enters.join(', ')} enter${x.enters.length === 1 ? 's' : ''} the rock` : ' · nothing enters the rock'));
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
      if (s.PECLET > 0 && s.ADVECTION) moves.push(`Peclet number ${s.PECLET}`);
      bits.push(moves.length ? moves.join(' + ') : 'nothing moves');
      bits.push(`${s.LEFT} | ${s.RIGHT} boundaries`
        + (m.extra ? `, ${m.extra.n} cell${m.extra.n === 1 ? '' : 's'} past the right-hand end` : ''));
    }
    if (m.nequilibria) {
      const h = m.heldEquilibria;
      const a = m.activity;
      bits.push(`${m.nequilibria} equilibri${m.nequilibria === 1 ? 'um' : 'a'}`
        + `, ${m.nconserved} conserved total${m.nconserved === 1 ? '' : 's'}`
        + (m.speciated ? ` · initial state equilibrated (${m.speciated.iterations} iterations)` : '')
        + (h ? ` · ${h.relations === m.nequilibria ? 'all' : h.relations} held throughout the run, `
          + `${h.species} species algebraic in every cell`
          + (h.minerals ? `, ${h.minerals} mineral${h.minerals === 1 ? '' : 's'} at saturation while there is any` : '') : '')
        + (a ? ` · in activities, ${a.kind === 'davies' ? 'Davies' : a.kind === 'sit' ? 'SIT' : a.kind === 'pitzer' ? 'Pitzer'
          : a.kind === 'llnl' ? 'LLNL’s B-dot' : 'Debye–Hückel'} at `
          + `${typeof a.temperature === 'number' ? `${a.temperature} °C` : 'each cell’s temperature'} `
          + `(${a.ions} ion${a.ions === 1 ? '' : 's'}`
          + `${a.kind === 'sit' ? `, ${a.sit} pair${a.sit === 1 ? '' : 's'} in <SIT>` : ''}`
          + `${a.kind === 'pitzer' && a.pitzer ? `, ${a.pitzer.params} parameter${a.pitzer.params === 1 ? '' : 's'} in <PITZER>`
            + `${a.pitzer.macinnes ? ', MacInnes scaled' : ''}` : ''}`
          // Volumes that correct no log K say so, unless <CONDUCTANCE> makes the density of them.
          + `${a.volumes && !(a.volumes.idle && a.conductance) ? `, log K at ${a.volumes.idle ? '1 atm: the'
            : `the pressure from ${a.volumes.given}`} molar volume${a.volumes.given === 1 ? '' : 's'} in <VOLUMES>`
            + `${a.volumes.idle ? ' correct nothing' : ''}` : ''})`
          + `${a.conductance ? ' · the conductance, the density and the viscosity from <CONDUCTANCE>' : ''}` : '')
        + (m.exchange ? ` · ${m.exchange.species} species on the exchanger${m.exchange.exchangers.length === 1 ? ''
          : 's'} ${m.exchange.exchangers.join(', ')}, Gaines–Thomas` : '')
        + (m.surface ? ` · ${m.surface.species} species on ${m.surface.sites.length === 1 ? 'a surface'
          : `${m.surface.sites.length} kinds of surface site`} (${m.surface.sites.join(', ')}), each with its fraction `
          + 'of the sites for its activity'
          + (m.surface.potentials && m.surface.potentials.length ? `, ${m.surface.potentials.map((pp) => (pp.plane !== null
            && pp.plane !== undefined ? `CD-MUSIC's plane ${pp.plane} ` : 'the double layer\'s ')
            + `potential ${pp.name}${pp.psi ? ` at ${fmtMv(pp.psi)} to start with` : ''}`).join(', ')}` : '') : '')
        + (m.redox ? ` · ${m.redox.relations} relation${m.redox.relations === 1 ? '' : 's'} tied to the electron `
          + `${m.redox.name}${m.redox.pe ? `, pe ${fmtPe(m.redox.pe)} ${m.redox.fixed ? 'held' : 'at the start'}` : ''}` : '')
        + (m.gas ? ` · ${m.gas.species.join(', ')} in a gas phase ${m.gas.fixed === 'volume'
          ? `of ${fmtNumber(m.gas.volume)} L to each kg of water, each gas at n R T/V`
          : `at ${fmtNumber(m.gas.pressure)} atm, a bubble while the water holds its gases at that between them`}` : '')
        + (m.solidSolutions && m.solidSolutions.length ? ` · ${m.solidSolutions.map((ss) => `the solid solution ${ss.name} `
          + `(${ss.members.join(', ')}), ${ss.binary ? `a0 ${fmtNumber(ss.binary.a0)} and a1 ${fmtNumber(ss.binary.a1)} at 25 °C`
            + `${ss.binary.gap ? ', a miscibility gap' : ''}` : 'ideal'}`).join(', ')}, there while the water is `
          + 'saturated in it' : ''));
    }
    // The temperature, where it goes with the cell or the time, and the log K that follow it.
    const T = m.temperature;
    if (T && (T.varies || T.relations || T.phases)) {
      const range = T.start ? (T.start[0] === T.start[1] ? `${fmtNumber(T.start[0])} °C`
        : `${fmtNumber(T.start[0])} to ${fmtNumber(T.start[1])} °C`) : '';
      const how = !T.varies ? `${fmtNumber(T.given)} °C`
        : `TEMPERATURE = ${T.given}: ${range}${T.cells ? ' from cell to cell' : ''}`
          + `${T.clock ? `${T.cells ? ', ' : ' '}at the start, and it goes with time` : ''}`;
      const k = T.relations + T.phases;
      bits.push(`the temperature ${how}${k ? ` · ${k} log K ${k === 1 ? 'goes' : 'go'} with it, by dH or an analytic `
        + 'expression' : ''}`);
    }
    // The unit labels follow the model: a run in years should not be asked
    // for a "from" time in seconds.
    const u = timeUnit();
    $('rtmTendUnit').textContent = `${u.name}s; blank uses TEND from the text`;
    $('rtmHmaxUnit').textContent = `${u.name}s; 0: a tenth of the run for the NDF, no limit for the ports`;
    $('rtmH0Unit').textContent = `${u.name}s; 0: chosen from the derivative at the start`;
    // The charts' time: in the model's unit, or in pore volumes where the water flows; each "from" in it.
    renderTimeIn();
    if (m.nparameters) bits.push(`${m.nparameters} parameter${m.nparameters === 1 ? '' : 's'}: ${m.parameters.join(', ')}`);
    if (m.tables && m.tables.length) bits.push(`${m.tables.length} table${m.tables.length === 1 ? '' : 's'}: ${m.tables.join(', ')}`);
    // A release history, or anything else a rate law reads at the clock, and
    // the corners the run is started again at so that none is stepped over.
    if (m.clockTables && m.clockTables.length) {
      bits.push(`read at the clock: ${m.clockTables.map((c) => c.name).join(', ')}`
        + (m.breaks ? `, the run started again at ${m.breaks} corner${m.breaks === 1 ? '' : 's'} up to TEND` : ''));
    }
    // A species held in some cells only; one held everywhere is in its line.
    for (const h of m.held || []) {
      const c = h.cells;
      const contiguous = c.every((v, k) => k === 0 || v === c[k - 1] + 1);
      const where = c.length === 1 ? `cell ${c[0]}`
        : contiguous ? `cells ${c[0]}–${c[c.length - 1]}` : `${c.length} cells`;
      bits.push(`${h.species} held in ${where}`);
    }
    if (m.anyMass) bits.push('a mass matrix is in force');
    bits.push(`${m.states} equations, ${m.nnz} non-zeros`);
    bits.push(`TEND ${fmtTime(s.TEND)}`);
    el.textContent = bits.join('\n');
    el.style.whiteSpace = 'pre-line';
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
      out.tend = num(s.tend, `The simulated time must be a positive number of ${timeUnit().name}s`, (x) => x > 0);
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
  /** The kept run k's stored times on the time axis ax (timeAxis): in this run's unit, or in its own pore volumes; null where it has none. */
  function besideAxis(k, ax) {
    if (!ax.pv) return besideTimes(k);
    const tw = poreTime(k.r);
    return tw > 0 ? axisTimes(k.r, { pv: true, tw }) : null;
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
      yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid, exponentformat: 'power' },
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
    weight, the sulfate's as SO4. Without ACTIVITY a concentration is in
    whatever unit the text means: shown times 10^3, 10^6 or 10^9, and never
    weighed. pH, pe, an SI and the like are shown as they are. What has no
    such unit -- a pressure, an alkalinity in mg, a species with no formula
    in mg -- is left off a chart of several, which the note says, and a
    chart of one draws it as the model has it.
  */
  const CONC_UNITS = {
    mmol: { scale: 1e3, text: 'mmol/kgw', bare: '× 10³' },
    umol: { scale: 1e6, text: 'µmol/kgw', bare: '× 10⁶' },
    nmol: { scale: 1e9, text: 'nmol/kgw', bare: '× 10⁹' },
    mg: { scale: 1e3, mass: true, text: 'mg/kgw' },
    ug: { scale: 1e6, mass: true, text: 'µg/kgw' },
  };
  /**
   * The unit chosen, as run r can show it: { id, scale, mass, text, bare, why } -- id '' the model's own; text what an
   * axis says, '× 10³' without ACTIVITY (bare); why the note's words where a mass is the model's own for want of ACTIVITY.
   */
  function shownUnit(r = state.result) {
    const act = !!(r && r.model && r.model.activity);
    const u = CONC_UNITS[state.concUnit];
    const own = { id: '', scale: 1, mass: false, text: act ? 'mol/kgw' : '', bare: !act, why: '' };
    if (!u) return own;
    if (u.mass && !act) return { ...own, why: `in the model's own unit: ${u.text} needs ACTIVITY, whose concentrations are mol/kgw` };
    return { id: state.concUnit, scale: u.scale, mass: !!u.mass, text: act ? u.text : u.bare, bare: !act, why: '' };
  }
  /** A title in the unit shown: 'concentration (mg/kgw)', 'concentration × 10³' without ACTIVITY; in the model's own as it is. */
  const inUnit = (title, u) => (!u.id ? title : u.bare ? `${title} ${u.text}` : `${title} (${u.text})`);
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
    if (u.mass && !m.activity) return { why: 'no ACTIVITY' };
    if (k >= 0) {
      // The electron's state is its activity, a potential's exp(-F psi/RT): neither an amount.
      if ((m.redox && m.redox.name === key) || (m.surface && (m.surface.potentials || []).some((p) => p.name === key))) {
        return { why: 'no amount' };
      }
      if (!u.mass) return { f: u.scale };
      const M = m.masses ? m.masses[k] : null;
      return M > 0 ? { f: u.scale * M } : { why: 'no formula mass' };
    }
    if (q.unit === 'eq/kgw' && !u.mass) return { f: u.scale };
    if (q.unit !== 'mol/kgw') return { why: q.unit === 'eq/kgw' ? 'in equivalents' : `in ${q.unit || 'a unit of its own'}` };
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
    const act = !!(r && r.model.activity);
    const opts = [['', act ? 'mol/kgw' : 'as the model has them', false],
      ...Object.entries(CONC_UNITS).map(([id, x]) => [id, act ? x.text : x.mass ? `${x.text}, under ACTIVITY` : x.bare, !act && !!x.mass])];
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
    return `the log axis from ${f.at.toExponential()}${u && u.id && !u.bare ? ` ${u.text}` : ''}`
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
            if (kx.length && onRight && !right.includes(labelOf(nm))) right.push(labelOf(nm));
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
        if (onRight && !right.includes(labelOf(nm))) right.push(labelOf(nm));
        if (xs.length) {
          traces.push({ name, x: xs, y: ys, mode: 'lines', type: 'scatter', line: { color },
            ...(onRight ? { yaxis: 'y2' } : {}) });
        }
        // What <DATA> measured of it, at this cell and layer: points, in the unit shown, at their times on the axis.
        if (!face) {
          for (const d of measured('time', nm)) {
            if ((d.tab.cell || 0) !== cell || (d.tab.layer || 0) !== state.layer) continue;
            traces.push({ name: `${name}, measured`, x: ax.pv ? d.x.map((t) => t / ax.tw) : d.x, y: f === 1 ? d.y : d.y.map((v) => v * f),
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
    const flux = u.id && !u.bare ? `${u.text} · m/${timeUnit().symbol}` : `concentration · m/${timeUnit().symbol}`;
    layout.yaxis.title = { text: face
      ? `flux through the ${state.cell} end (${flux})${u.id && u.bare ? ` ${u.text}` : ''}` : inUnit('concentration', u), font: { size: 11 } };
    if (right.length) {
      const c = themeColors();
      layout.yaxis2 = { overlaying: 'y', side: 'right', gridcolor: c.grid, zeroline: false, linecolor: c.grid, showgrid: false,
        title: { text: right.join(', '), font: { size: 11 } } };
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
        out.push({ name: `${of.kind === 'element' ? `${of.name}, all of it` : labelOf(nm)}`, run: run.label, start, cin, gone,
          end: got.total[n - 1], made: got.byReactions[n - 1], share: start + cin > 0 ? gone / (start + cin) : null });
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
    const outHtml = out.map((o) => `<tr><td>${esc(o.name)}</td><td>${esc(o.run)}</td>${td(o.start)}${td(o.cin)}${td(o.gone)}`
      + `${td(o.end)}${td(o.made)}${td(o.share, o.share === null ? '' : `${esc((100 * o.share).toPrecision(3))} %`)}</tr>`).join('');
    const unitText = u.id && !u.bare ? ` (${u.text})` : '';
    box.innerHTML = (half.length ? `<table><thead><tr><th>Where each curve is half-way${esc(unitText)}</th><th>it starts at</th>`
      + '<th>the farthest it gets</th><th>half-way</th><th>in pore volumes</th><th>retardation</th></tr></thead>'
      + `<tbody>${halfHtml}</tbody></table>` : '')
      + (out.length ? '<table><thead><tr><th>What has come out of the column</th><th>run</th><th>there at the start</th>'
        + '<th>came in at the left</th><th>went out at the right</th><th>there at the end</th><th>made by reactions, net</th>'
        + `<th>gone out of what was there and came in</th></tr></thead><tbody>${outHtml}</tbody></table>` : '')
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
        'made by reactions, net', 'gone out of what was there and came in'],
      rows: out.map((o) => [o.name, o.run, o.start, o.cin, o.gone, o.end, o.made, o.share]) },
    };
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
    const suffix = u.id && shown && !own ? (u.bare ? ` ${u.text}` : ` (${u.text})`) : '';
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
    const asked = slider ? { times: [], bad: [] } : parseTimes(state.profileTimes, ax.pv);
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
    const asked = slider ? { times: [], bad: [] } : parseTimes(state.profileTimes, ax.pv);
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
      const meta = u.id && shown ? { meta: { unitSuffix: u.bare ? ` ${u.text}` : ` (${u.text})` } } : {};
      // Every value as it is, none at all on a log axis too: Plotly leaves it out there, and what is saved keeps it.
      const keep = (v) => (Number.isFinite(v) ? v * f : null);
      const quantity = runQuantity(r, key);
      const si = r.model.species.indexOf(key);
      const valueAt = (j, k) => keep(quantity ? (quantitySeries(key, cellAt(k)) || [])[j] : r.states[j * r.width + cellAt(k) * r.model.nspecies + si]);
      const y = Array.from({ length: npts }, (_, k) => valueAt(i, k));
      if (slider) (onRight ? spansR : spansL).push(spanOver(`${r.runKey}|${key}|${g.across}|${layer}|${g.atCell}|${f}`, r.n, npts, valueAt));
      if (onRight && !right.includes(labelOf(key))) right.push(labelOf(key));
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
        title: { text: right.join(', '), font: { size: 11 } } };
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
    const suffix = u.id && shown && !own ? (u.bare ? ` ${u.text}` : ` (${u.text})`) : '';
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
        || (state.compBudgetOf.startsWith('species:') && sp.includes(state.compBudgetOf.slice(8))))) {
        state.compBudgetOf = els.length ? `element:${els[0]}` : sp.length ? `species:${sp[0]}` : '';
      }
      const opt = (v, label) => `<option value="${esc(v)}"${v === state.compBudgetOf ? ' selected' : ''}>${esc(label)}</option>`;
      $('rtmCompBudgetOf').innerHTML = (els.length ? `<optgroup label="Elements">${els.map((e) => opt(`element:${e}`, e)).join('')}</optgroup>` : '')
        + (sp.length ? `<optgroup label="Species">${sp.map((x) => opt(`species:${x}`, x)).join('')}</optgroup>` : '');
    }
    document.querySelectorAll('[data-comp-hide]').forEach((el) => { el.hidden = el.dataset.compHide === view; });
    // By each reaction, where the model has <REACTIONS> lines: over the whole column, or at one of its cells.
    {
      const hasLines = !!(m && (m.quantities || []).some((q) => q.group === 'reactions'));
      const byLines = budget && hasLines && state.compBudgetBy === 'lines';
      $('rtmCompBudgetBy').value = hasLines ? state.compBudgetBy : 'where';
      $('rtmCompBudgetByWrap').hidden = !budget || !hasLines;
      const nfc = m ? m.fracture : 1;
      if (state.compBudgetAt !== 'column' && !(state.compBudgetAt >= 0 && state.compBudgetAt < nfc)) state.compBudgetAt = 'column';
      $('rtmCompBudgetAt').innerHTML = `<option value="column"${state.compBudgetAt === 'column' ? ' selected' : ''}>the whole column</option>`
        + Array.from({ length: column ? nfc : 0 }, (_, i) => `<option value="${i}"${i === state.compBudgetAt ? ' selected' : ''}>cell ${i}`
          + `${m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
      $('rtmCompBudgetAtWrap').hidden = !(byLines && column);
    }
    $('rtmCompAlongWrap').hidden = !column || listing || budget;
    const cells = m ? m.fracture : 1;
    if (!(state.compCell < cells)) state.compCell = 0;
    $('rtmCompCell').innerHTML = Array.from({ length: cells }, (_, i) => `<option value="${i}"${i === state.compCell ? ' selected' : ''}>`
      + `${i}${m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
    $('rtmCompCellWrap').hidden = (along !== 'time' && !listing) || cells < 2 || budget;
    const nm = m && m.matrix ? m.matrix.n : 0;
    if (state.compLayer > nm) state.compLayer = 0;
    $('rtmCompLayer').innerHTML = layerOptions(state.compLayer);
    $('rtmCompLayerWrap').hidden = nm === 0;
    // Along the run, the times are those the water is drawn at (where an element is needs none); across the column, one time.
    $('rtmCompTimesWrap').hidden = (along === 'time' && ['where', 'ussl', 'wilcox', 'pca'].includes(view) && !listing) || budget;
    $('rtmCompPcaVars').value = state.compPcaVars;
    $('rtmCompPcaLog').checked = state.compPcaLog;
    $('rtmCompBeside').checked = state.compBeside;
    $('rtmCompTimesLabel').textContent = along === 'time' && !listing ? 'Times' : 'At';
    $('rtmCompTimes').placeholder = along === 'time' && !listing ? 'spread over the run' : 'the end of the run';
    $('rtmCompTimes').value = state.compTimes;
    $('rtmCompLogTWrap').hidden = ((along !== 'time' || view === 'schoeller' || view === 'stiff') && !budget) || listing;
    $('rtmCompTMinWrap').hidden = $('rtmCompLogTWrap').hidden;
    $('rtmCompTMin').value = state.compTMin;
    $('rtmCompTMinUnit').textContent = timeUnit().symbol;
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
    const asked = parseTimes(state.compTimes);
    const still = compSliding(r) && state.compAt !== null;
    const atIndex = still ? nearestIndex(r.t, state.compAt) : asked.times.length ? nearestIndex(r.t, asked.times[0]) : r.n - 1;
    renderCompPlay(r, atIndex);
    const ctx = { r, plot, along, layer, cell, asked, atIndex, column, fail, note, still };
    empty.hidden = true;
    plot.hidden = false;
    if (state.compView === 'where') drawWhere(ctx);
    else if (state.compView === 'listing') drawListing(ctx);
    else if (state.compView === 'budget') drawBudget(ctx);
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

  /** What a budget can be of: every element a species holds, then every species. */
  function budgetChoices(m) {
    const C = compositionOf(m);
    const els = C ? C.elements.filter((e) => e.terms.length).map((e) => e.el) : [];
    const sp = ((m && m.species) || []).filter((nm) => nm !== 'e-');
    return { els, sp };
  }

  function drawBudget({ r, plot, fail, note }) {
    const { els, sp } = budgetChoices(r.model);
    let chosen = state.compBudgetOf;
    if (!chosen || !(els.includes(chosen.replace(/^element:/, '')) && chosen.startsWith('element:')
      || sp.includes(chosen.replace(/^species:/, '')) && chosen.startsWith('species:'))) {
      chosen = els.length ? `element:${els[0]}` : `species:${sp[0]}`;
    }
    const kind = chosen.startsWith('species:') ? 'species' : 'element';
    const name = chosen.slice(kind.length + 1);
    const key = `${r.runKey}|${kind}|${name}`;
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
    if (!idx.length) { fail(`Nothing is stored after ${fmtTime(Number(state.compTMin) || 0)}: lower the "from" time.`); return; }
    const c = themeColors();
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22', '#17becf'];
    const xs = idx.map((i) => r.t[i]);
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
    const layout = baseLayout();
    layout.xaxis.type = pick.logT ? 'log' : 'linear';
    layout.xaxis.title = { text: `time (${timeUnit().symbol})`, font: { size: 11 } };
    layout.yaxis.title = { text: got.transport ? "amount, concentration × m per m² of the water's cross-section" : 'amount per kg of water',
      font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    // What the note says: where it is at the end, what crossed the ends, and what the reactions made of it.
    const last = n - 1;
    const fmt = (v) => fmtNumber(v);
    const where = got.bands.filter((b) => b.values[last] !== 0)
      .map((b) => `${fmt(b.values[last])} ${b.name}${got.total[last] > 0 ? ` (${(100 * b.values[last] / got.total[last]).toFixed(1)} %)` : ''}`);
    let scale = 0;
    for (let i = 0; i < n; i++) scale = Math.max(scale, Math.abs(supplied[i]), Math.abs(got.total[i]));
    let off = 0;
    for (let i = 0; i < n; i++) off = Math.max(off, Math.abs(got.byReactions[i]));
    const rel = scale > 0 ? off / scale : 0;
    note.textContent = `${name}${kind === 'species' ? '' : ', all of it'} at the end: ${where.join(', ') || 'none in the column'}`
      + `${got.transport ? `; ${fmt(got.cumIn[last])} came in at the left and ${fmt(got.cumOut[last])} went out at the right` : ''}`
      + (rel < 1e-4 ? `; no reaction makes or takes any to speak of: what is left over, at most ${off.toExponential(1)}, ${rel.toExponential(1)}`
        + ' of what was there and came in, is the solver\'s and the summing over the stored points\''
        : `; made by reactions, net, ${fmt(got.byReactions[last])} by the end`);
    const unit = timeUnit().symbol;
    compTableNow = { head: [`t (${unit})`, ...got.bands.map((b) => b.name), ...(anyOut ? ['gone out at the right-hand end'] : []),
      ...(got.transport ? ['come in at the left-hand end'] : []), 'made by reactions, net', 'in the column, all of it'],
    name: `${fileStem()}_budget_${name.replace(/[^\w.-]+/g, '_')}`,
    rows: Array.from({ length: n }, (_, i) => [r.t[i], ...got.bands.map((b) => b.values[i]), ...(anyOut ? [got.cumOut[i]] : []),
      ...(got.transport ? [got.cumIn[i]] : []), got.byReactions[i], got.total[i]]) };
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
    if (!idx.length) { fail(`Nothing is stored after ${fmtTime(Number(state.compTMin) || 0)}: lower the "from" time.`); return; }
    if (ranked.length) {
      const named = ranked.slice(0, LINES_NAMED);
      const rest = ranked.slice(LINES_NAMED);
      const c = themeColors();
      const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22'];
      const xs = idx.map((i) => r.t[i]);
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
      layout.xaxis.title = { text: `time (${sym})`, font: { size: 11 } };
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
        + netRow('made by reactions, net, as the budget has it', made) : '')
      + '</tbody></table>'
      + `<p>Each reaction's rate of making it and of taking it summed over the stored points by the trapezoidal rule, ${esc(per)}; `
      + 'a line and one written apart that undoes it are one reaction, both lines given. '
      + (whole ? `${relRows.length ? 'Each relation\'s part is its extent, read off the balance of a species of its own, times what it '
        + 'makes of this. ' : ''}What none of them accounts for is ${restIs}.`
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
      : `the summing's error ${fmt(error)}, ${errText} of what was made and taken`) : '']
      .filter(Boolean).join('; ');
    // Saved: each line's rates and its sum at every stored point, each relation's part; in Excel, the table on a sheet of its own.
    const head = [`t (${sym})`];
    for (const { l } of ranked) {
      const who = `${l.name} (line${l.lines.length > 1 ? 's' : ''} ${l.lines.join(' and ')})`;
      head.push(`${who}, made per ${sym}`, `${who}, taken per ${sym}`, `${who}, net since the start`);
    }
    head.push('every reaction, net since the start');
    if (whole) {
      for (const { x } of relRows) head.push(`${x.name} (line ${x.line}), net since the start`);
      if (relRows.length) head.push('every relation, net since the start');
      head.push(together ? "the relations, together, with the summing's error" : "the summing's error", 'made by reactions, net, as the budget has it');
    }
    compTableNow = {
      head,
      name: `${fileStem()}_budget_${name.replace(/[^\w.-]+/g, '_')}_by_reaction${whole ? '' : `_cell${cellAt}${layer ? `_layer${layer}` : ''}`}`,
      rows: Array.from({ length: n }, (_, i) => {
        const row = [r.t[i]];
        let all = 0;
        for (const { l } of ranked) { row.push(l.made[i], l.taken[i], l.madeCum[i] + l.takenCum[i]); all += l.madeCum[i] + l.takenCum[i]; }
        row.push(all);
        if (whole) {
          let rs = 0;
          for (const { x } of relRows) { row.push(x.part[i]); rs += x.part[i]; }
          if (relRows.length) row.push(rs);
          row.push(bud.byReactions[i] - all - rs, bud.byReactions[i]);
        }
        return row;
      }),
      extra: [{ name: 'over the run', head: ['reaction or relation', 'line', 'made', 'taken', 'net', 'of what was made', 'of what was taken'],
        rows: [...ranked.map(({ l, made: mk, taken: tk }) => [l.name, l.lines.join(', '), mk, tk, mk + tk, share(mk, sumMade), share(tk, sumTaken)]),
          ['every reaction', null, sumMade, sumTaken, netLines, null, null],
          ...(whole ? [...relRows.map(({ x, part }) => [x.name, String(x.line), null, null, part, null, null]),
            ...(relRows.length ? [['every relation', null, null, null, relSum, null, null]] : []),
            [together ? "the relations, together, with the summing's error" : "the summing's error", null, null, null, together ? leftover : error, null, null],
            ['made by reactions, net, as the budget has it', null, null, null, made, null, null]] : [])] }],
    };
  }

  /** The stored points along the run a chart in time draws: after "from" on a log axis. */
  function compTimeIndices(r) {
    const logT = $('rtmCompLogT').checked;
    const tmin = Number(state.compTMin) || 0;
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
      if (!idx.length) { fail(`Nothing is stored after ${fmtTime(Number(state.compTMin) || 0)}: lower the "from" time.`); return; }
      const mc = modelCell(cell, layer);
      xs = idx.map((i) => r.t[i]);
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
    layout.xaxis.title = { text: along === 'time' ? `time (${timeUnit().symbol})` : 'distance from the left-hand face (m)',
      font: { size: 11 } };
    layout.yaxis.title = { text: percent ? `share of the ${E.el} ${where} (%)` : `${E.el} ${where} (concentration × count)`,
      font: { size: 11 } };
    if (percent) layout.yaxis.range = [0, 100];
    else if (sliding && runTop > 0) layout.yaxis.range = [0, 1.05 * runTop];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    const xHead = along === 'time' ? `t (${timeUnit().symbol})` : 'distance (m)';
    compTableNow = { head: [xHead, ...kept.map((b) => `${b.name}${percent ? ' (%)' : ''}`), `${E.el} ${where}, all of it`],
      rows: xs.map((x, j) => [x, ...shown.map((col) => col[j]), total[j]]),
      name: `rtm_${E.el}_${along === 'time' ? `cell${cell}` : 'column'}` };
    const bits = [along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}, ${npts} stored points`
      : `${npts} cells at ${fmtTime(r.t[atIndex])}${layer ? `, rock layer ${layer}` : ''}`,
    `${E.terms.length} species hold ${E.el} ${where}`];
    if (small.length > 1) bits.push(`${small.length} never come to 1 %, drawn as one band`);
    const bk = besideRun();
    if (bk) bits.push(besideNote(bk, 'bands that stack take no second run; the other views draw it'));
    if (along === 'distance' && !sliding && state.compTimes.trim() && Math.abs(r.t[atIndex] - parseTimes(state.compTimes).times[0])
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
        const tmin = Number(state.compTMin) || 0;
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
            color: logT ? Math.log10(r.t[i]) : r.t[i], i, mc });
        }
        colorTitle = logT ? `log₁₀ time (${timeUnit().symbol})` : `time (${timeUnit().symbol})`;
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
    const xHead = [`t (${timeUnit().symbol})`, 'cell', 'distance (m)'];
    compTableNow = {
      head: ['water', ...xHead, ...POLES.map((p) => `${p.label} (${unit.text})`), ...POLES.map((p) => `${p.label} (% of the ${p.cation ? 'cations' : 'anions'})`), 'type',
        ...(view === 'durov' ? ['pH', 'TDS (mg/kgw)'] : [])],
      rows: all.map((wt) => [wt.measured ? wt.label : `model, ${wt.label}`, wt.t, wt.cell, wt.x !== undefined ? wt.x : null,
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
      const tmin = Number(state.compTMin) || 0;
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
          pts.push({ sc: sc[i], sar: sar[i], color: logT ? Math.log10(r.t[i]) : r.t[i], label: fmtTime(r.t[i]), t: r.t[i], cell });
        }
      }
      colorTitle = logT ? `log₁₀ time (${timeUnit().symbol})` : `time (${timeUnit().symbol})`;
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
    compTableNow = { head: ['water', `t (${timeUnit().symbol})`, 'cell', 'distance (m)', 'SC (µS/cm)', 'SAR', 'class'], name: 'rtm_ussl',
      rows: [...pts.map((p) => [`model, ${p.label}`, p.t, p.cell, p.x === undefined ? null : p.x, p.sc, p.sar, usslClass(p.sc, p.sar)]),
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
        if (pt) pts.push({ ...pt, color: logT ? Math.log10(r.t[i]) : r.t[i], label: fmtTime(r.t[i]), t: r.t[i], cell });
      }
      colorTitle = logT ? `log₁₀ time (${timeUnit().symbol})` : `time (${timeUnit().symbol})`;
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
    compTableNow = { head: ['water', `t (${timeUnit().symbol})`, 'cell', 'distance (m)', 'cations (meq/kgw)', 'percent sodium (%)', 'class'],
      name: 'rtm_wilcox',
      rows: [...pts.map((p) => [`model, ${p.label}`, p.t, p.cell, p.x === undefined ? null : p.x, p.epm, p.na, wilcoxClass(p.epm, p.na)]),
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
          color: logT ? Math.log10(r.t[i]) : r.t[i] });
      }
      colorTitle = logT ? `log₁₀ time (${timeUnit().symbol})` : `time (${timeUnit().symbol})`;
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
      head: ['water', `t (${timeUnit().symbol})`, 'cell', 'distance (m)', ...pcs], name: `rtm_pca_${along === 'time' ? `cell${cell}` : 'column'}`,
      rows: [...usable.map((w, i) => [`model, ${w.label}`, w.t, w.cell, w.x === undefined ? null : w.x, ...scores[i]]),
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
    $('rtmDgYMore').hidden = !d.y.kind;
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
      ? [['predominance', 'the species that holds most of an element'], ['phase', 'the phase furthest over saturation, or at it'],
        ['stable', 'the phases of an element, the most stable per mole of it'],
        ...(lines ? [['couples', 'the redox couples, as lines']] : []), ['contour', 'a species or a quantity, as contours']]
      : [...(ladder ? [['ladder', 'the redox couples, as a ladder']] : []),
        ['shares', 'the species of an element, as shares'], ['logc', 'the species of an element, as log concentrations'],
        ['si', 'the saturation indices'], ['quantity', 'a species or a quantity']];
    const d = state.dg;
    if (!opts.some(([v]) => v === d.show)) d.show = opts[0][0];
    $('rtmDgShow').innerHTML = opts.map(([v, t]) => `<option value="${v}"${v === d.show ? ' selected' : ''}>${esc(t)}</option>`).join('');
    const C = dgResult.composition;
    // For the most stable phase, the elements two phases or more are made of; else those two species or more hold.
    const els = d.show === 'stable' ? dgStableElements()
      : C ? C.elements.filter((e) => (d.in === 'all' ? e.terms : e.terms.filter((tm) => tm[2] === 'water')).length > 1)
        .map((e) => e.el) : [];
    if (els.length && !els.includes(d.el)) d.el = els[0];
    $('rtmDgEl').innerHTML = els.length ? els.map((e) => `<option value="${esc(e)}"${e === d.el ? ' selected' : ''}>${esc(e)}</option>`).join('')
      : '<option value="">none</option>';
    $('rtmDgIn').value = d.in;
    const byEl = ['shares', 'logc', 'predominance', 'stable'].includes(d.show);
    $('rtmDgElWrap').hidden = !byEl;
    $('rtmDgInWrap').hidden = !(byEl || d.show === 'ladder' || d.show === 'couples') || d.show === 'stable';
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
  }

  async function dgGo() {
    if (dgBusy) return;
    if (!state.compiled) { setStatus('The model does not compile: there is nothing to work out a diagram of.', 'error'); return; }
    const d = state.dg;
    const axis = (ax) => ({ kind: ax.kind, species: ax.sp, from: Number(ax.from), to: Number(ax.to), n: Math.round(Number(ax.n)) });
    // The pH held at a number, where nothing varied is the pH: the water speciated at it at every point.
    const held = d.y.kind === 'pHheld';
    const axes = [axis(d.x), ...(d.y.kind && !held ? [axis(d.y)] : [])];
    const bad = axes.find((ax) => !Number.isFinite(ax.from) || !Number.isFinite(ax.to) || !(ax.n >= 2 && ax.n <= 400));
    if (bad) { setStatus('Each axis needs a from, a to and from 2 to 400 points.', 'error'); return; }
    const pHAt = held ? Number(String(d.y.from).trim() || NaN) : null;
    if (held && !Number.isFinite(pHAt)) { setStatus('The pH to hold the water at is a number: 7, say.', 'error'); return; }
    if (held && d.x.kind === 'pH') { setStatus('The pH is what is varied: it cannot be held as well.', 'error'); return; }
    const r = state.result;
    if (d.at === 'end' && !r) { setStatus('Run the model first: the water as it ends the run is what the run leaves.', 'error'); return; }
    const text = d.at === 'end' ? ((state.ran && state.ran.text) || state.text) : state.text;
    const stride = (state.compiled && state.compiled.stride) || 1;
    const ask = (withRun) => request({ type: 'diagram', text, at: d.at, cell: d.cell * stride, axes,
      ...(held ? { pHAt } : {}), ...(d.at === 'end' ? { runKey: r.runKey } : {}),
      ...(withRun ? { t: Float64Array.from(r.t), states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) },
    (p) => { setProgress(p.frac); setStatus(`Working out the diagram: ${p.done.toLocaleString()} of ${p.npts.toLocaleString()} points…`); });
    dgBusy = true;
    $('rtmDgGo').disabled = true;
    $('rtmStop').disabled = false;
    const started = Date.now();
    setStatus(`Working out the diagram: ${axes.reduce((n, ax) => n * ax.n, 1).toLocaleString()} points…`);
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      const said = `Diagram worked out in ${((Date.now() - started) / 1000).toFixed(2)} s: ${(reply.n1 * reply.n2).toLocaleString()} points`
        + `${reply.failed ? `, ${reply.failed.toLocaleString()} of which did not settle and are left blank` : ''}.`;
      // What the boundaries of a map are worked out from, and each map's once they are: null where they could not be.
      dgResult = { reply, axes, composition: state.compiled.composition, at: d.at, cell: d.cell, text, cellIndex: d.cell * stride,
        runKey: d.at === 'end' ? r.runKey : null, said, saidKind: reply.failed ? 'warn' : 'ok', bounds: new Map(), pHAt,
        ladders: new Map(), couples: new Map() };
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

  /** A value of a point: a species' concentration, or a quantity. */
  function dgValue(key, p) {
    const rp = dgResult.reply;
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
    const rp = dgResult.reply;
    const d = state.dg;
    const [ax, ay] = dgResult.axes;
    const where = `cell ${dgResult.cell} as it ${dgResult.at === 'end' ? 'ends the run' : 'starts'}`
      + `${rp.pHHeld !== null && rp.pHHeld !== undefined ? `, its pH held at ${rp.pHHeld.toFixed(3)}` : ''}`;
    const names = rp.species;
    const layout = baseLayout();
    layout.hovermode = 'closest';
    layout.xaxis.title = { text: dgLabel(ax), font: { size: 11 } };
    const xs = Array.from(rp.x);
    if (!rp.y && d.show === 'ladder') { drawDgLadder(plot, note, fail, where); return; }
    if (!rp.y) {
      const traces = [];
      const cols = [];
      if (d.show === 'shares' || d.show === 'logc') {
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
      cols.forEach(([label, y], q) => traces.push({ type: 'scatter', mode: 'lines', name: label, x: xs, y,
        line: { color: DG_PALETTE[q % DG_PALETTE.length], width: 1.8 },
        hovertemplate: `${esc(label)}: %{y:.4g}<extra></extra>` }));
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      dgTableNow = { head: [dgLabel(ax), ...cols.map(([label]) => label)], rows: xs.map((x, p) => [x, ...cols.map(([, y]) => y[p])]),
        name: `rtm_diagram_${ax.kind}` };
      note.textContent = `${where}; ${xs.length} points${rp.failed ? `, ${rp.failed} left blank: they did not settle` : ''}`;
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
      if (d.show === 'stable') return `${names2[at[p]]}, SI over its ${d.el} ${(share[p] + 0).toFixed(2)}`;
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
      : d.show === 'stable' ? `the phase most stable per mole of ${d.el}` : 'the phase furthest over saturation, or at it',
    d.show === 'predominance' ? 'its share (%)' : d.show === 'stable' ? `its SI over its ${d.el}` : 'its SI'],
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
    const settings = Object.entries(kinds).filter(([, spec]) => spec.kind === 'number' || spec.kind === 'int')
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
    try {
      const reply = await request({ type: 'each', text, solver, targets: targets.map((t) => ({ vary: t.vary, base: t.base,
        ...(t.k ? { up: t.up, down: t.down } : {}) })),
        delta: EACH_DELTA, cell: w.cell }, (p) => {
        setProgress(p.frac);
        setStatus(`Running ${p.run + 1} of ${p.runs}: ${fmtTime(p.t)} of ${fmtTime(p.tend)}, ${p.nsteps.toLocaleString()} steps`);
      });
      swResult = { kind: 'each', what, reply, targets, left, text };
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

  function renderSwShow() {
    $('rtmSwShowBar').hidden = !swResult;
    if (!swResult) return;
    const w = state.sw;
    if (swResult.kind === 'each') {
      w.show = 'ranked';
      const ks = swResult.targets.every((t) => t.k);
      $('rtmSwShow').innerHTML = `<option value="ranked" selected>each ${ks ? 'log K' : 'constant'}, by how much it moves it</option>`;
      if (!speciesNames().includes(w.key) && !(quantityOf(w.key) && !quantityOf(w.key).of)) w.key = speciesNames()[0] || '';
      $('rtmSwKey').innerHTML = pickerOptions(w.key, false);
      $('rtmSwOf').value = w.of;
      $('rtmSwOfWrap').hidden = false;
      $('rtmSwLogTWrap').hidden = true;
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
        const x = w.show === 'time' ? Array.from(run.t) : Array.from(run.centres);
        const keep = x.map((xx, i) => (w.show !== 'time' || !w.logT || xx > 0) && Number.isFinite(y[i]) && (!logY || y[i] > 0));
        return { type: 'scatter', mode: 'lines', name: swRunName(run), x: x.filter((_, i) => keep[i]), y: y.filter((_, i) => keep[i]),
          line: { color: swColour(runs.indexOf(run), runs.length), width: 1.6 } };
      });
      layout.xaxis.type = w.show === 'time' && w.logT ? 'log' : 'linear';
      layout.xaxis.title = { text: w.show === 'time' ? `time (${timeUnit().symbol})` : 'distance from the left-hand face (m)', font: { size: 11 } };
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
    return [...new Set(data.flatMap((tab) => tab.columns))];
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
    box.innerHTML = '<table><thead><tr><th>Fitted</th><th>from</th><th>to</th><th>standard error</th><th>about 95 %</th></tr></thead>'
      + `<tbody>${rows}</tbody></table>`
      + `<p>The misfit: the residuals' standard deviation ${r.sd !== null ? r.sd.toPrecision(3) : 'not known (as many numbers as points)'}`
      + ` over ${r.n} point${r.n === 1 ? '' : 's'} and ${r.np} number${r.np === 1 ? '' : 's'}; the sum of their squares from `
      + `${r.ssr0.toPrecision(4)} to ${r.ssr.toPrecision(4)} in ${r.runs} runs, ${esc(r.why)}`
      + `${r.skipped ? `; ${r.skipped} amount${r.skipped === 1 ? '' : 's'} at or below zero left out` : ''}.</p>${corr}`;
  }

  /** A fitted point's place, for a legend or a hover: the column, and its cell and time or its distance and time. */
  const fitWhere = (p) => {
    const stride = (state.compiled && state.compiled.stride) || 1;
    return p.kind === 'time' ? `cell ${Math.floor(p.cell / stride)}${p.cell % stride ? `, rock layer ${p.cell % stride}` : ''}`
      : `at ${fmtTime(p.t)}`;
  };

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
    $('rtmFitLogTWrap').hidden = show !== 'data' || !r.curves.some((c) => c.kind === 'time');
    $('rtmFitLogYWrap').hidden = show !== 'data';
    const layout = baseLayout();
    layout.hovermode = 'closest';
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const pointsTable = () => ({ head: ['column', 'where', 'time', 'distance (m)', 'measured', 'the run', 'residual'], name: 'rtm_fit',
      rows: r.points.map((p) => {
        const run = p.index ? p.value + p.residual : p.value * 10 ** p.residual;
        return [labelOf(p.key), fitWhere(p), p.t, p.x, p.value, run, p.residual];
      }) });
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
        return { type: 'scatter', mode: 'markers', name: labelOf(key), x: pts.map(([, i]) => i + 1), y: pts.map(([p]) => p.residual),
          marker: { size: 8, color: palette[q % palette.length] },
          text: pts.map(([p]) => `${esc(labelOf(p.key))}, ${esc(fitWhere(p))}, ${p.kind === 'time' ? fmtTime(p.t) : `${fmtNumber(p.x)} m`}`),
          hovertemplate: '%{text}: %{y:.4g}<extra></extra>' };
      });
      layout.xaxis.title = { text: 'the point measured, in the order of <DATA>', font: { size: 11 } };
      layout.yaxis.title = { text: 'residual: log₁₀(run / measured), or run − measured for pH, SI and the like', font: { size: 11 } };
      layout.shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: themeColors().text, width: 1, dash: 'dot' } }];
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      fitTableNow = pointsTable();
      note.textContent = `${r.n} points`;
      return;
    }
    // The run at the fitted numbers where it was measured, and the measurements: along the run at a cell where the tables
    // are in time, along the column at a time where they are in distance.
    const logT = $('rtmFitLogT').checked;
    const logY = $('rtmFitLogY').checked;
    const timeCurves = r.curves.filter((c) => c.kind === 'time');
    const curves = timeCurves.length ? timeCurves : r.curves;
    const along = timeCurves.length ? 'time' : 'distance';
    const several = new Set(curves.map((c) => (along === 'time' ? c.cell : c.t))).size > 1;
    const traces = [];
    let right = false;
    curves.forEach((c, q) => {
      const color = palette[q % palette.length];
      const where = several ? `, ${fitWhere(along === 'time' ? { kind: 'time', cell: c.cell } : { kind: 'distance', t: c.t })}` : '';
      const name = `${labelOf(c.key)}${where}`;
      const onRight = c.index;
      right = right || onRight;
      const keep = c.x.map((x, i) => (along !== 'time' || !logT || x > 0) && Number.isFinite(c.y[i]) && (onRight || !logY || c.y[i] > 0));
      traces.push({ type: 'scatter', mode: 'lines', name, x: c.x.filter((_, i) => keep[i]), y: c.y.filter((_, i) => keep[i]),
        line: { color, width: 1.8 }, ...(onRight ? { yaxis: 'y2' } : {}) });
      const pts = r.points.filter((p) => p.kind === along && p.key === c.key && (along === 'time' ? p.cell === c.cell : p.t === c.t));
      traces.push({ type: 'scatter', mode: 'markers', name: `${name}, measured`, x: pts.map((p) => (along === 'time' ? p.t : p.x)),
        y: pts.map((p) => p.value), marker: { size: 8, symbol: 'circle-open', color, line: { width: 1.6 } },
        ...(onRight ? { yaxis: 'y2' } : {}) });
    });
    layout.xaxis.type = along === 'time' && logT ? 'log' : 'linear';
    layout.xaxis.title = { text: along === 'time' ? `time (${timeUnit().symbol})` : 'distance from the left-hand face (m)', font: { size: 11 } };
    layout.yaxis.type = logY ? 'log' : 'linear';
    layout.yaxis.title = { text: 'concentration, or an amount of <OUTPUT>', font: { size: 11 } };
    if (right) {
      const c = themeColors();
      layout.yaxis2 = { overlaying: 'y', side: 'right', gridcolor: c.grid, zeroline: false, linecolor: c.grid, showgrid: false,
        title: { text: [...new Set(curves.filter((cv) => cv.index).map((cv) => labelOf(cv.key)))].join(', '), font: { size: 11 } } };
      layout.margin.r = 64;
    }
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    fitTableNow = pointsTable();
    note.textContent = `the run at the fitted numbers${r.curves.length > curves.length ? '; the tables in distance are in the CSV' : ''}`;
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
    ((m && m.data) || []).forEach((tab, table) => tab.columns.forEach((key, j) => {
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
    fitTableNow = { head: ['column', 'where', 'time', 'distance (m)', 'measured', ...runs.flatMap((run) => [run.label, `residual, ${run.label}`])],
      name: 'rtm_against_measured',
      rows: points.map((p, j) => [labelOf(p.key), p.kind === 'time' ? `cell ${p.cell}` : 'along the column',
        p.t === null ? r.t[r.n - 1] : p.t, p.x, p.value, ...runs.flatMap((run) => (run.rows[j] ? [run.rows[j].v, run.rows[j].res] : [null, null]))]),
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
    state.text = text;
    $('rtmText').value = text;
    renderHighlight();
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
      const X = xs.filter((_, i) => keep[i]);
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
          traces.push({ type: 'scatter', mode: 'markers', name: 'measured', x: d.x, y: d.y,
            marker: { size: 8, symbol: 'circle-open', color: c.text, line: { width: 1.6 } } });
        }
      }
      layout.xaxis.type = logT ? 'log' : 'linear';
      layout.xaxis.title = { text: u.show === 'time' ? `time (${timeUnit().symbol})` : 'distance from the left-hand face (m)', font: { size: 11 } };
      layout.yaxis.type = logY ? 'log' : 'linear';
      layout.yaxis.title = { text: yTitle, font: { size: 11 } };
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      unTableNow = { head: [u.show === 'time' ? `t (${timeUnit().symbol})` : 'distance (m)', ...UN_P.map((p) => `${labelOf(key)}, ${p} %`),
        ...(base ? [`${labelOf(key)}, the model as written`] : [])], name: `rtm_uncertainty_${u.show}`,
      rows: xs.map((x, i) => [x, ...bands.map((b) => b[i]), ...(base ? [runSeries(rp, base, key, where)[i]] : [])]) };
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
      In the unit shown, each concentration's header saying it; one that has
      none in it -- no formula to weigh, a pressure -- as the model has it,
      its header saying in what: mol/kgw under ACTIVITY.
    */
    const u = shownUnit(r);
    const shown = names.map((n) => shownAs(r, n, u));
    // At an end what crosses it, per m2 of the water's cross-section: the unit times m per the time unit.
    const per = face ? ` · m/${timeUnit().symbol}` : '';
    const own = (n) => (unitOf(n) || (r.model.activity && !isQuantity(n) ? ` (mol/kgw${per})` : ''));
    const headOf = (n, j, where) => {
      const sh = shown[j];
      if (!u.id || !sh) return `${labelOf(n)}${unitOf(n)} ${where}`;
      if (sh.why) return `${labelOf(n)}${own(n)} ${where}`;
      return `${labelOf(n)}${u.bare ? ` ${u.text}` : ` (${u.text}${per})`} ${where}`;
    };
    // Each key at each cell, in the order picked; in pore volumes, they come first, then the time.
    const ax = timeAxis(r);
    const at = face ? [state.cell] : tc.at;
    const head = [...(ax.pv ? ['pore volumes'] : []), `t (${timeUnit().symbol})`];
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
      rows.push([...(ax.pv ? [xr[i]] : []), r.t[i], ...cols.map((c) => (c && Number.isFinite(c[i]) ? c[i] : null))]);
    }
    // In Excel, the breakthrough numbers on sheets of their own where they are shown.
    const extra = state.btc && btcNow ? [btcNow.half, btcNow.out].filter((tb) => tb.rows.length) : [];
    return { head, rows, name: face ? `rtm_${state.cell}_end` : `rtm_cell${at.join('_')}`, ...(extra.length ? { extra } : {}) };
  }

  async function downloadCsv() {
    if (!state.result) { setStatus('Run the model first: there is nothing to save yet.', 'error'); return; }
    const tab = await timeTable();
    downloadBlob(new Blob([csvOf(tab)], { type: 'text/csv' }), `${tab.name}.csv`);
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
      inverse: 'rtmChartPqInv' }[pane]);
    if (as === 'txt') {
      if (!compTextNow) { setStatus('List a water first: Show the water, as PHREEQC lists it.', 'error'); return; }
      downloadBlob(new Blob([compTextNow], { type: 'text/plain' }), `${compTableNow.name}.txt`);
      return;
    }
    if (as === 'html') { await saveChartPage(plot, pane); return; }
    if (as === 'svg' || as === 'png') {
      if (!plot || plot.hidden || !plot.data) { setStatus('Draw something first: the chart is empty.', 'error'); return; }
      const box = plot.getBoundingClientRect();
      await Plotly.downloadImage(plot, { format: as, filename: `${fileStem()}_${pane}`,
        width: Math.max(400, Math.round(box.width)), height: Math.max(300, Math.round(box.height)) });
      return;
    }
    const tab = await paneTable(pane);
    if (!tab) { setStatus('Draw something first: the chart is empty.', 'error'); return; }
    if (as === 'csv') { downloadBlob(new Blob([csvOf(tab)], { type: 'text/csv' }), `${tab.name}.csv`); return; }
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') {
      setStatus('The Excel writer did not load; save as CSV instead.', 'error');
      return;
    }
    const xlsx = new XlsxWriter(`${tab.name}.xlsx`);
    xlsx.writeData(tab.rows.map((row) => row.map((v) => (v === null ? '' : v))), 'run', { header: tab.head });
    for (const more of tab.extra || []) xlsx.writeData(more.rows.map((row) => row.map((v) => (v === null ? '' : v))), more.name, { header: more.head });
    const text = (state.ran && state.ran.text) || state.text;
    xlsx.writeData(text.split('\n').map((ln) => [ln]), 'model', { header: ['the model text the run was made with'] });
    downloadBlob(await xlsx.save(), `${tab.name}.xlsx`);
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
    inverse: 'rtmPqInvNote' };
  const CHART_NAMES = { time: 'against time', profile: 'against distance', gradient: 'gradient', composition: 'composition',
    diagram: 'diagram', sweep: 'sweeps', fit: 'fit', uncertainty: 'uncertainty', phreeqc: 'through PHREEQC',
    inverse: 'inverse models through PHREEQC' };
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
    const text = (state.ran && state.ran.text) || state.text;
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
<details><summary>The model text the run was made with</summary><pre>${esc(text)}</pre></details>
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
    downloadBlob(new Blob([html], { type: 'text/html' }), `${name}.html`);
    if (lib.text) setStatus(`Saved ${name}.html: the chart as a page of its own, plotly.js in it, to open in any browser.`, 'ok');
    else {
      setStatus(`Saved ${name}.html, linking plotly.js from ${new URL(lib.src).host}: it could not be read to go into the file, `
        + 'so the page needs the internet to open.', 'warn');
    }
  }

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

  /** The same file, as a download. */
  function downloadHdf5() {
    if (!state.result) { setStatus('Run the model first: there is nothing to save yet.', 'error'); return; }
    const name = `${fileStem()}.h5`;
    try {
      const bytes = buildHdf5();
      downloadBlob(new Blob([bytes], { type: 'application/x-hdf5' }), name);
      setStatus(`${name} written (${(bytes.length / 1048576).toFixed(1)} MB).`, 'ok');
    } catch (e) {
      setStatus(`The HDF5 file could not be written: ${e.message}`, 'error');
    }
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
    if (name === 'phreeqc') { pqRenderView(); resize(); }
    if (name === 'jacobian') drawJacobianPattern();
  }

  function resize() {
    if (typeof Plotly === 'undefined') return;
    ['rtmChartTime', 'rtmChartProfile', 'rtmChartGradient', 'rtmChartComp', 'rtmChartDg', 'rtmChartSw', 'rtmChartFit', 'rtmChartUn',
      'rtmChartPq']
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
      handle.setPointerCapture(ev.pointerId);
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

  const TOPICS = {
    'sec:model': () => {
      const m = state.compiled;
      const warned = m ? m.warnings.length : 0;
      return {
        kicker: 'Section', title: 'Model',
        lead: 'What the text on the Model tab compiles to, read back from it. Nothing here is set in the panel: change the text, and this follows.',
        facts: [
          ['Compiles', '0.4 s after the last keystroke, or on Apply'],
          ['Warnings', m ? (warned ? `${warned}, listed under the text on the Model tab` : 'none')
            : (state.compileError ? 'the text does not compile; the status line says why' : 'not compiled yet')],
        ],
        sections: [{
          heading: 'Line by line',
          list: [
            '`batch` or `transport`, and how many species and reactions: `MODE`, `<SPECIES>` and `<REACTIONS>`.',
            'For a column, the cells: how many, over what length and how laid out, from `CELLS`, `LENGTH` and `GRID` with its `GRID_RATIO` or `GRID_POWER`, and a first cell pinned by `SURFACE_LAYER`.',
            'With a rock matrix, `dual porosity`: how many layers behind each cell, `matched` or `reference`, to `MATRIX_DEPTH`; the first layer, why it is that thick and how fast the rest grow; the `MATRIX_POROSITY`, the wall area per m³ of flowing water, and the species that have a `De=` and so enter the rock.',
            'What moves: `diffusion` (`Nernst-Planck diffusion` under `DIFFUSION = nernst-planck`, `down the activities` under `DIFFUSION_GRADIENT = activity`), `advection` at the `VELOCITY` with the travel time it makes (`limited advection` under `ADVECTION_SCHEME = limited`), the Peclet number, or `nothing moves`.',
            'The two ends, `LEFT | RIGHT`, with `cauchy` and `outflow` read as the `robin` and `free` they mean, and how many cells stand for the column past a `semi-infinite` end.',
            'Equilibria and the totals they conserve, and whether `EQUILIBRATE` put the starting state on them.',
            'Parameters and tables by name, and a species held in some cells only.',
            'The tables a rate law reads at the clock, `read at the clock`, and how many corners of theirs the run is started again at.',
            '`a mass matrix is in force`: a species has an `R=`, or a rock matrix gives it a capacity.',
            'The equations, species times cells with the rock layers counted; the non-zeros of the Jacobian; and `TEND`, in the model’s time unit.',
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
        lead: `How long to run, in the model’s own time unit, ${u.name}s. Blank runs to the TEND the model text gives.`,
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
            '**Time in**: the model’s own unit, or — where the water flows — pore volumes: the time over the time the water takes to cross the column, `TRAVEL_TIME`, or `LENGTH` over the pore water’s speed |`VELOCITY`|/`POROSITY`. One choice for Against time, Against distance and Gradient. A run kept beside is drawn in its own pore volumes, so that two runs at different speeds line up; what `<DATA>` measured is put on the axis by its time.',
            '**breakthrough numbers**, in a column: two tables under the chart. Of each curve drawn, where it starts, the farthest it gets from there and when, and when it is first half-way from the one to the other, read off every stored point; where the water flows, that time in pore volumes and the retardation it implies — those pore volumes over the share of the column the water has crossed to get there, 1 for what moves with the water. It is a front’s median, not its mean, and a front that spreads much moves it a little: set a species against a tracer of the same run. Of each species and each element’s total ticked, what has come out of the column, from its budget as the Composition tab keeps it: what was there at the start, what came in at the left, what went out at the right, what is there at the end, what reactions made or took, and the share gone out of what was there and came in. A run kept beside has its own rows; Excel has both tables on sheets of their own.',
            '**log time**, **log concentration**: logarithmic axes. A log axis cannot show zero, so t = 0, and values at or below zero, are left off.',
            '**from**, after log time: where a log time axis starts, a plain number in the model’s time unit, or in pore volumes where they are chosen; changing **Time in** turns it into the other. A stiff run’s first steps are femtoseconds long, and without it the chart opens on fifteen empty decades. A linear axis starts at 0 whatever it says.',
            '**from**, after log concentration: where a log concentration axis starts, a plain number such as `1e-10`; empty, it reaches the least drawn. A redox run’s species can span 150 decades, and a floor keeps the ones that matter readable. A curve below it drops out of view, and the note names any that lie wholly below; the CSV and Excel files have every value still. pH, pe and the like on the right are drawn as they are.',
            '**Units**: the unit the concentrations are shown in, one choice for every chart and the water’s listing. Under an `ACTIVITY`, mol/kgw, mmol, µmol or nmol per kgw, or mg or µg per kgw by the formula mass — a species by its name, a nuclide by its mass number, a mineral by its relation, an element’s total by its atomic weight; without one, the model’s own unit times 10³, 10⁶ or 10⁹. pH, pe and the like stay as they are; what has no such unit — a pressure, a species whose name is no formula in mg — is left off, and the note says which. The measured points, the run kept beside, the **from** of the log axis, the axis title and the CSV and Excel files are in it too.',
            '**clear**: unticks everything.',
            '**CSV**: what is ticked, or every species when nothing is, at the cell and layer shown, at each of the Cells, or through the end shown, a row per stored point; in pore volumes a column of them first, then the time.',
            '**Excel**: the same as a workbook, with the model text on a sheet of its own. **SVG** and **PNG**: the chart as a figure, at the size it is drawn.',
            SAVE_HTML,
            '**View in Data Browser**: the whole run as an HDF5 file, opened in the Data Browser in a new tab without touching the disk. The browser has to let the page open a tab.',
            '**HDF5**: the same file, as a download.',
          ] },
          { heading: 'The list', text: [
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
          '**Times**: a list such as `0, 1 h, 30 d, 500 y`, in s, min, h, d, a or y (both years of 365.25 days), or PV, pore volumes, where the water flows; a bare number is in the model’s own unit, or in pore volumes where they are chosen. Empty draws eight, spread evenly over the stored points, the last at the end of the run. With those ticked against time, the first time alone, and empty the end of the run.',
          '**Time in**: as on Against time, one choice for the three charts: the model’s own unit, or pore volumes. The legend, the slider and the note name each time in it; a run kept beside is drawn at the stored point nearest the same pore volume of its own. Changing it turns the bare numbers of Times into the other, so that the same curves are drawn.',
          '**log concentration**: a logarithmic axis, for an amount; pH, a saturation index or a share is drawn as it is.',
          '**from**: where the log concentration axis starts, a plain number such as `1e-10`; empty, it reaches the least drawn. What lies below drops out of view, and the note names any curve wholly below it; the CSV and Excel files have every value still.',
          '**Units**: as on Against time, one choice for every chart. A species or quantity with no such unit is drawn as the model has it, and the note says so; with those ticked against time it is left off.',
          '**The slider** under the bar: one time at a time, a stored point a step. The chart draws what Show has at that time — one curve, or those ticked against time — on axes that span the whole run, so that a front moves across a still frame. What `<DATA>` measured is faint, and as itself at the stored time nearest its own.',
          '**play**: moves the slider on from where it is, or from the start, at the **Pace** chosen: the whole run in 5, 10 or 30 s, evenly in time, or a stored point a frame, slower where the solver stored more; **pause** stops it. **back to Times** draws the Times again, and so does typing them.',
          '**CSV**, **Excel**: the curves drawn, a row per distance. **SVG**, **PNG**: the chart as a figure.',
          SAVE_HTML,
        ] },
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
            '**Time in**: as on Against time, the model’s own unit, or pore volumes where the water flows; a run kept beside in its own.',
            '**log time** and **from**: as on Against time. Without a from time the first femtoseconds take most of a log axis; the note says how many points it left off.',
            '**log concentration**: colours by log₁₀ c. Values at or below zero are left blank rather than put at the bottom of the scale, and the note counts them.',
            '**from**, after log concentration: where the colour scale starts, a plain number such as `1e-10`; empty, the least value there is. What lies below it takes its colour, or on a surface lies below the box; the CSV and Excel files have every value still.',
            '**Units**: as on Against time, one choice for every chart. A species or quantity with no such unit is drawn as the model has it, and the note says so.',
            '**smooth**: interpolates between the cells. It looks better and claims a resolution the run has not got, which is why it is off.',
            '**CSV**, **Excel**: the numbers drawn, a row per cell and a column per time. **SVG**, **PNG**: the picture.',
            SAVE_HTML,
          ] },
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
            ['a budget over the run', 'Of an element, or of one species (**Of**): what the column holds of it at each stored time — in the water, on an exchanger or a surface, in each mineral, in the rock — stacked, with what has gone out at the right-hand end on top; dashed, what was there at the start with what has come in at the left; the gap between them, what the reactions made of it, dotted on its own. Per m² of the water\'s cross-section in a column, per kg of water in a batch. What no reaction makes or takes closes to the solver\'s tolerance and the summing of the ends\' fluxes over the stored points, and the note says how far; a nuclide\'s decay, or a source among the reactions, shows as what the reactions made. **By** each reaction, where the model has `<REACTIONS>`: what each line makes of it and takes, a rate worked out as the solver\'s derivative works it out, a line and one written apart that undoes it as one reaction; stacked over the whole column or at a cell (**Over**), made above nought and taken below, the eight reactions that move most named; under the chart what each made and took over the run, and over the whole column what each relation moved, its extent read off the balance of a species of its own, and the summing\'s error left.', view === 'budget'],
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
            '**CSV**, **Excel**: the numbers drawn — each band, or each water\'s ions, shares and type, or its scores; for principal components Excel adds the loadings and the variance each component carries. **SVG**, **PNG**: the picture.',
            '**Text**, for the water as PHREEQC lists it: every block in PHREEQC\'s columns, to set beside its output; its CSV is the distribution of species, its Excel workbook every block on a sheet of its own.',
            SAVE_HTML,
          ] },
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
            'A mineral there stays at saturation while there is any of it. A point that settles neither from the point before it nor from the water is tried again from the point after it; one that still does not is left blank, and the status line counts them.',
            '**Work it out**: in the background; a grid of 101 × 41 takes a second or less.',
          ] },
          { heading: 'Show', list: two ? [
            '**the species that holds most of an element**, in the water or the whole cell: over pH and pe or Eh, a Pourbaix diagram, with the water\'s own limits, O₂ above and H₂ below at 1 atm and 25 °C: in volts 1.229 − 0.0592 pH and −0.0592 pH.',
            '**the phase furthest over saturation, or at it**: a mineral stability diagram.',
            '**the phases of an element, the most stable per mole of it**: each phase\'s saturation index over its count of the element — aluminium in a silicate — the largest the phase the rest would turn into, the element kept in the solids, whatever of it is dissolved: over log a(H4SiO4) and log a(K+)/a(H+), Garrels and Christ\'s diagram of K-feldspar, muscovite, kaolinite and gibbsite. A phase without the element that comes to saturation on the map, quartz say, is dotted across it where it does.',
            '**the redox couples, as lines**, over pH and pe or Eh: each couple of the redox ladder traced across the map, where the water holds as much of its element in either state — the textbooks\' diagram of a water\'s couples — a colour to each element and a dash to each couple, between where water gives way, the water itself marked. A couple that does not turn over on the map is said in the note.',
            '**a species or a quantity, as contours**: its log where it is an amount.',
            'A map\'s **boundaries** are found between the grid\'s points, the water speciated again there, to 1e-10; where three fields meet, the point is solved for. A field narrower than the grid can be missed.',
          ] : [
            '**the redox couples, as a ladder**, along pe or Eh with the pH held: each relation of <EQUILIBRIUM> with the electron in it between two valence states of an element — SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O — placed where it turns over, the pe at which this water holds as much of the element in the oxidised state as in the reduced one, in the water or the whole cell, found to 1e-10. Where water gives way, O₂ and H₂ at 1 atm and 25 °C, dashed; the water\'s own pe dotted. The note says which couples turn over outside the range.',
            '**the species of an element** as shares of it, or as log concentrations.',
            '**the saturation indices** of every phase and mineral.',
            '**a species or a quantity**: pH, a total, an <OUTPUT>, …',
          ] },
          { heading: 'Saving', list: ['**CSV**, **Excel**: a row per point, what is drawn there, or per couple of a ladder, its pe and its Eh; a map\'s Excel workbook has its boundaries on a sheet of their own. **SVG**, **PNG**: the picture.', SAVE_HTML] },
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
        ] },
        { heading: 'Saving', list: ['**CSV**, **Excel**: what is drawn, a row per value or per point. **SVG**, **PNG**: the picture.', SAVE_HTML] },
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
          'A number above zero is fitted in its logarithm, so it stays above zero; a log K and the temperature as they are. Give each a start above zero where it is fitted in its logarithm.',
        ] },
        { heading: 'How', list: [
          'Levenberg and Marquardt\'s least squares, each derivative from a run with one number moved a little, with the panel\'s solver settings. The run is read at exactly the times measured.',
          'An amount\'s residual is log₁₀ of the run over what was measured, so a factor of two counts the same at any size; pH, SI and the like count as their difference.',
          'The standard errors and correlations are the Jacobian\'s at the end, the residuals giving the scatter; about 95 % is 1.96 standard errors either way, as a factor for a number fitted in its logarithm.',
        ] },
        { heading: 'Then', list: [
          '**Show** the run at the fitted numbers with the measurements, the residuals, or the misfit as it fell.',
          '**the run against what was measured, one to one**, last in Show, with a fit or without one: each value measured set against the run’s at the same place and time — the run on show read between its stored points and its cells, linearly — on equal axes with the line of one to one, amounts on log axes with twice and half dashed, pH, SI and the like on their own. Under it, for each column: its points, the bias (the mean residual, for an amount shown as the factor the run is of what was measured), the spread (their root mean square), the sum of squares and the worst point; then all the columns together, as the Fit sums them. After a fit the fitted run is there as diamonds, at the times measured; a run kept beside, hollow.',
          '**Put the fitted values in the model**: each written into the text where it came from, to six figures.',
          '**CSV**, **Excel**: each point measured, the run there and its residual. **SVG**, **PNG**: the picture.',
          SAVE_HTML,
        ] },
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
        { heading: 'Saving', list: ['**CSV**, **Excel**: the percentiles at each time or cell, or each run\'s numbers and value; the indices with their intervals, Excel adding the runs. **SVG**, **PNG**: the picture.', SAVE_HTML] },
      ],
      more: more('Uncertainty', 'help-uncertainty'),
    }),

    'pane:model': () => ({
      kicker: 'Tab', title: 'Model',
      lead: 'The model the page solves, as text. It compiles 0.4 s after the last keystroke; the status line says what it compiled to or where it went wrong, and any warnings are listed under the text.',
      facts: [
        ['Examples', `${EXAMPLES.length} in ${new Set(EXAMPLES.map((e) => e.group)).size} groups`],
        ['A drop reads', `up to ${DROP_MAX_FILES} files, ${DROP_MAX_BYTES / 1048576} MB`],
        ['The text is kept', 'in this browser, between visits'],
      ],
      sections: [
        { heading: 'The toolbar', list: [
          '**Example**: loads one of the examples. The text is replaced without asking, and a line under the picker says what the model is and where it comes from.',
          '**Apply**: compiles the text now.',
          '**Reset to the built-in model**: water radiolysis and uranium dissolution at a spent-fuel surface, 127 reactions over 36 species. It too replaces the text without asking.',
          '**Open…**: a model text (`.rtm`, `.txt`), or skbrtm’s database files and the Python script that runs them (`.in`, `.py`), read as one model. Dropping files, or their folder, anywhere on the page does the same.',
          '**Save**: the text, as `model.rtm`.',
          '**From PHREEQC…**: opens a panel where PHREEQC speciates a water and the water, as PHREEQC leaves it, becomes the text. Its own (i) says how.',
          '**colour the syntax**: paints comments, section headings, numbers, functions and the words that mean something where they stand. Turn it off for a very large model. The choice is kept.',
        ] },
        { heading: 'Keep in mind', text: 'A reload does not bring the built-in model back: the text stays in this browser until Reset, an example, a file or a water from PHREEQC replaces it.' },
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
        { text: 'The choice is shared by the panel on the Model tab and the PHREEQC tab: one database for both directions.' },
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
          SAVE_HTML,
          'Which phases are supersaturated anywhere, and where and when.',
          'How far the activity coefficients of the model’s own equilibria moved along the run, in log K. That is how far constants made for the start have gone wrong; a model with `ACTIVITY` follows them, and then it says how close its own stay to PHREEQC’s.',
          'Each mineral of the model: the saturation index PHREEQC finds where the model has some of it, and where it has none.',
          'An exchanger or a surface of the model: how close what the run has on it is to what PHREEQC loads onto one of the same sites from the same water. The electron: how close the run’s valence states are to PHREEQC’s at the run’s pe. A gas phase: how close each gas’s partial pressure in the run, its fugacity for a real gas, is to the pressure PHREEQC finds the water holds it at.',
          'A water that is far from neutral, which usually means the model leaves out a counter-ion.',
        ] },
        { heading: 'Settings', text: '**Times per cell**: at most this many stored times, spread over the run (0 reads them all). **Cells**: a list such as `0, 5, 10-19`, or empty for all.' },
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
          '**CSV**: every number of every model.',
          SAVE_HTML,
        ] },
      ],
      more: more('Inverse models through PHREEQC', 'help-phreeqc-inverse'),
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
    sel.innerHTML = '<option value="">— choose one —</option>'
      + groups.map((g) => `<optgroup label="${esc(g.name)}">`
        + g.items.map((e) => `<option value="${esc(e.id)}">${esc(e.label)}</option>`).join('')
        + '</optgroup>').join('');
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
    state.text = e.text;
    $('rtmText').value = e.text;
    renderHighlight();
    about.textContent = e.about + (e.reference ? `  ${e.reference}` : '');
    about.hidden = false;
    state.result = null;
    state.verify = null;
    anotherModel();
    renderBeside();
    applyExampleView(e.view || null);
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

  /** Repaints the coloured copy and keeps it under the same part of the text. */
  function renderHighlight() {
    const pre = $('rtmHighlight');
    const ta = $('rtmText');
    if (!pre || !ta) return;
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
     Files
     --------------------------------------------------------------------- */
  function saveFile() {
    downloadBlob(new Blob([state.text], { type: 'text/plain' }), 'model.rtm');
  }

  /*
    Open… takes a model text, or skbrtm's databases: any of reaction.in,
    solutions.in, diffusion.in, sourceterm*.in and doserate*.in, and the
    Python script that runs them, which says which of them are read, in what
    order, and for how long. Those are converted to one model text by
    RtmImport, which writes at the top of it everything skbrtm itself would
    read differently.
  */
  async function fileChosen(ev) {
    const picked = Array.from((ev.target.files) || []);
    ev.target.value = '';
    if (!picked.length) return;
    openFiles(await Promise.all(picked.map(async (f) => ({ name: f.name, text: await f.text() }))));
  }

  /*
    DROPPED ON THE PAGE. A model text, skbrtm's files, or the folder they are
    in -- an skbrtm example's own folder, script and databases/ together --
    opens as Open... would open it. What is read is what either can use; a
    folder's notes, plots and results are passed over, and a folder is not
    followed without end.
  */
  const READABLE = /\.(rtm|txt|in|py)$/i;
  const DROP_MAX_FILES = 200;
  const DROP_MAX_BYTES = 20 * 1024 * 1024;

  /** The files under what was dropped, as {name, text}. */
  async function readDropped(entries, plain) {
    const out = [];
    let bytes = 0;
    let skipped = 0;
    const take = async (file, name) => {
      if (!READABLE.test(file.name)) return;
      if (out.length >= DROP_MAX_FILES || bytes + file.size > DROP_MAX_BYTES) { skipped++; return; }
      bytes += file.size;
      out.push({ name, text: await file.text() });
    };
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
    return { files: out, skipped };
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
      readDropped(entries, plain).then(({ files, skipped }) => {
        if (!files.length) {
          setStatus('Nothing here can be opened: a model text (.rtm, .txt), or skbrtm\'s databases and '
            + 'script (.in, .py), or the folder they are in.', 'warn');
          return;
        }
        openFiles(files);
        if (skipped) setStatus(`${skipped} file${skipped === 1 ? ' was' : 's were'} left out: a drop reads `
          + `${DROP_MAX_FILES} files and 20 MB at most.`, 'warn');
      }, (e) => setStatus(`The drop could not be read: ${e.message}`, 'error'));
    });
    window.addEventListener('dragend', done);
  }

  /** A model text, or skbrtm's files, however they arrived: [{name, text}]. */
  function openFiles(files) {
    const about = $('rtmExampleAbout');
    const skbrtm = typeof RtmImport !== 'undefined'
      && files.some((f) => /\.py$/i.test(f.name) || RtmImport.isDatabase(f.text));
    if (skbrtm) {
      let res;
      try {
        res = RtmImport.convert(files);
      } catch (e) {
        setStatus(`These could not be opened as skbrtm databases: ${e.message}`, 'error');
        return;
      }
      state.text = res.text;
      const n = files.filter((f) => /\.py$/i.test(f.name) || RtmImport.isDatabase(f.text)).length;
      about.textContent = `Opened ${n} skbrtm file${n === 1 ? '' : 's'} as one model.`
        + (res.warnings.length ? ` ${res.warnings.length} thing${res.warnings.length === 1 ? '' : 's'} that `
          + 'skbrtm would read differently, or that needs a look, are noted at the top of the text.' : '');
      about.hidden = false;
    } else {
      // A model file before any other text file that came with it.
      const pick = files.find((f) => /\.rtm$/i.test(f.name)) || files[0];
      if (files.length > 1) {
        setStatus(`One model text at a time: ${pick.name} was opened, the other ${files.length - 1} were not.`, 'warn');
      }
      state.text = pick.text;
      about.hidden = true;
    }
    $('rtmExample').value = '';
    $('rtmText').value = state.text;
    renderHighlight();
    anotherModel();
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
  const PQ_WORKER_URL = 'resources/js/rtm-phreeqc-worker.js?v=20261111e';
  const PQ_SCRIPTS = [
    'vendors/phreeqc/phreeqc.js?v=20261109l',
    'vendors/phreeqc/phreeqc-dat.js?v=20261107',
    'resources/js/rtm-phreeqc.js?v=20261110a',
    'resources/js/rtm-phreeqc-engine.js?v=20261110a',
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
        open: pq.open, inv: pq.inv,
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
    for (const id of ['rtmPqDb', 'rtmPqViewDb']) {
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
        // A worker that could not load its scripts. Whatever was waiting is
        // told so; from here on PHREEQC runs on the page.
        const why = (ev && ev.message) || 'its scripts did not load';
        pq.worker = null;
        pq.kind = 'inline';
        for (const entry of pq.pending.values()) entry.reject(new Error(`PHREEQC's worker stopped: ${why}`));
        pq.pending.clear();
      };
    } catch (e) {
      pq.worker = null;
      pq.kind = 'inline';
    }
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
      return new Promise((resolve, reject) => {
        pq.pending.set(id, { resolve, reject, onProgress });
        pq.worker.postMessage(full);
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
      // As an example is loaded: the text replaced outright, and said so below the panel.
      state.text = reply.text;
      $('rtmText').value = reply.text;
      renderHighlight();
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
    const x = rows.map((i) => (distance ? where(i) : T.t[i]));
    const traces = [{ name: 'pH, −log a(H+)', x, y: rows.map((i) => T.pH[i]), mode: 'lines', type: 'scatter',
      yaxis: 'y', line: { width: 2 } }];
    for (const p of v.phases) {
      traces.push({ name: p, x, y: rows.map((i) => T.si[p][i]), mode: 'lines', type: 'scatter', yaxis: 'y2' });
    }
    const layout = baseLayout();
    const c = themeColors();
    layout.xaxis = { ...layout.xaxis, type: logT ? 'log' : 'linear', anchor: 'y2',
      title: { text: distance ? `distance (m), at ${at > 0 ? fmtTime(at) : 'the start'}` : `time (${timeUnit().symbol})`,
        font: { size: 11 } } };
    layout.yaxis = { ...layout.yaxis, domain: [0.62, 1], exponentformat: 'none',
      title: { text: 'pH', font: { size: 11 } } };
    layout.yaxis2 = { gridcolor: c.grid, linecolor: c.grid, domain: [0, 0.52], anchor: 'x', zeroline: true,
      zerolinecolor: c.text, zerolinewidth: 1, title: { text: 'saturation index', font: { size: 11 } } };
    layout.margin = { ...layout.margin, b: 48 };
    layout.legend = { ...layout.legend, y: -0.16 };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  function pqCsv() {
    if (!pq.view) { setStatus('Look at a run through PHREEQC first: there is no table yet.', 'warn'); return; }
    downloadBlob(new Blob([pq.view.csv], { type: 'text/csv' }), `${fileStem()}_phreeqc.csv`);
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

  function pqInvCsv() {
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
    downloadBlob(new Blob([`${csvOf(tab)}\n`], { type: 'text/csv' }), `${fileStem()}_inverse.csv`);
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
    // One time axis for Against time, Against distance and Gradient: the three selects as one.
    'rtm:timeIn': (ev, el) => {
      const before = timeAxis();
      state.timeIn = el.value === 'pv' ? 'pv' : '';
      const after = timeAxis();
      // The same picture on the other axis: each "from" and the Times' bare numbers put on it.
      if (before.pv !== after.pv) retypeTimes(before, after);
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
      state.compBudgetBy = $('rtmCompBudgetBy').value === 'lines' ? 'lines' : 'where';
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
    'rtm:more': () => {
      const open = !state.sections[ADVANCED_KEY];
      state.sections[ADVANCED_KEY] = open;
      showAdvanced(open);
      saveState();
    },
    'rtm:textChanged': () => {
      state.text = $('rtmText').value;
      // Synchronously, not on the compile's timer: the textarea's own text is
      // transparent while the colouring is on, so the coloured copy is what
      // the reader is watching themselves type.
      renderHighlight();
      scheduleCompile(400);
    },
    'rtm:syntaxToggle': (ev, el) => { state.syntax = !!el.checked; applySyntaxMode(); saveState(); },
    'rtm:applyModel': () => { state.text = $('rtmText').value; scheduleCompile(0); },
    'rtm:resetModel': () => {
      state.text = RTM_DEFAULT_MODEL;
      $('rtmText').value = state.text;
      renderHighlight();
      state.picked = [];
      scheduleCompile(0);
    },
    'rtm:chooseExample': (ev, el) => chooseExample(el.value),
    'rtm:loadFile': () => $('rtmFile').click(),
    'rtm:fileChosen': (ev) => { fileChosen(ev); },
    'rtm:saveFile': () => saveFile(),
    'rtm:resetWidth': () => {
      state.sideWidth = DEFAULT_WIDTH;
      document.querySelector('.rtm').style.setProperty('--rtm-side-width', `${DEFAULT_WIDTH}px`);
      saveState();
      resize();
    },
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
  });

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  loadState();
  migrateStoredText();
  $('rtmText').value = state.text;
  // scroll does not bubble, so it cannot be delegated like the rest.
  $('rtmText').addEventListener('scroll', () => {
    const pre = $('rtmHighlight');
    if (pre && state.syntax) { pre.scrollTop = $('rtmText').scrollTop; pre.scrollLeft = $('rtmText').scrollLeft; }
  }, { passive: true });
  applySyntaxMode();
  renderExamples();
  $('rtmProfileTimes').value = state.profileTimes;
  writeSolverControls();
  updateSolverOptions();
  initSideResize();
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
