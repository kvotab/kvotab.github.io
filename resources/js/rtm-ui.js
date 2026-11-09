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
  const WORKER_URL = 'resources/js/rtm-worker-entry.js?v=20261109i';
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
    gradSpecies: '',
    gradScale: 'YlOrRd',
    gradView: 'map',       // the gradient as a map, as contours of it, or as a surface
    gradTMin: '1e-6',
    // The composition tab: what it shows, of which element, in what, as what, along the run or the column, where.
    compView: 'where',
    compElement: '',
    compIn: 'water',
    compAs: 'percent',
    compAlong: 'time',
    compCell: 0,
    compLayer: 0,
    compTimes: '',
    compTMin: '1e-6',
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
        profileSpecies: state.profileSpecies, profileTimes: state.profileTimes,
        gradSpecies: state.gradSpecies, gradScale: state.gradScale, gradView: state.gradView,
        gradTMin: state.gradTMin,
        compView: state.compView, compElement: state.compElement, compIn: state.compIn, compAs: state.compAs,
        compAlong: state.compAlong, compCell: state.compCell, compLayer: state.compLayer, compTimes: state.compTimes,
        compTMin: state.compTMin, dg: state.dg, sw: state.sw, fit: state.fit, unc: state.unc,
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
      if (typeof s.gradSpecies === 'string') state.gradSpecies = s.gradSpecies;
      if (typeof s.gradScale === 'string') state.gradScale = s.gradScale;
      if (['map', 'contour', 'surface'].includes(s.gradView)) state.gradView = s.gradView;
      if (typeof s.gradTMin === 'string') state.gradTMin = s.gradTMin;
      if (['where', 'piper', 'schoeller', 'stiff'].includes(s.compView)) state.compView = s.compView;
      if (typeof s.compElement === 'string') state.compElement = s.compElement;
      if (s.compIn === 'water' || s.compIn === 'all') state.compIn = s.compIn;
      if (s.compAs === 'percent' || s.compAs === 'amount') state.compAs = s.compAs;
      if (s.compAlong === 'time' || s.compAlong === 'distance') state.compAlong = s.compAlong;
      if (Number.isInteger(s.compCell) && s.compCell >= 0) state.compCell = s.compCell;
      if (Number.isInteger(s.compLayer) && s.compLayer >= 0) state.compLayer = s.compLayer;
      if (typeof s.compTimes === 'string') state.compTimes = s.compTimes;
      if (typeof s.compTMin === 'string') state.compTMin = s.compTMin;
      if (s.dg && typeof s.dg === 'object') {
        const d = state.dg;
        if (Number.isInteger(s.dg.cell) && s.dg.cell >= 0) d.cell = s.dg.cell;
        if (s.dg.at === 'start' || s.dg.at === 'end') d.at = s.dg.at;
        for (const key of ['x', 'y']) {
          const ax = s.dg[key];
          if (!ax || typeof ax !== 'object') continue;
          if (['pH', 'pe', 'la', 'tot', ...(key === 'y' ? [''] : [])].includes(ax.kind)) d[key].kind = ax.kind;
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
        if (['time', 'profile', 'spread', 'matters'].includes(s.unc.show)) u.show = s.unc.show;
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
   * "0, 1 h, 30 d, 500 y" -> seconds, plus whatever could not be read.
   *
   * A unit is glued to its number first, so that a space between the two does
   * not split them, and a bare list of numbers still separates on spaces.
   */
  function parseTimes(text) {
    const glued = String(text).replace(/(\d)\s+(s|min|h|d|a|y)\b/gi, '$1$2');
    const times = [];
    const bad = [];
    const own = timeUnit().seconds;
    for (const tok of glued.split(/[\s,;]+/).filter(Boolean)) {
      const m = /^([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(s|min|h|d|a|y)?$/i.exec(tok);
      if (!m) { bad.push(tok); continue; }
      // A bare number is in the model's own unit; a suffixed one is converted
      // into it, so "500 a" means the same thing whatever the model counts in.
      times.push((Number(m[1]) * (m[2] ? TIME_UNITS[m[2].toLowerCase()] : own)) / own);
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
          + `${a.volumes ? `, log K at ${a.volumes.idle ? '1 atm: the' : `the pressure from ${a.volumes.given}`} molar `
            + `volume${a.volumes.given === 1 ? '' : 's'} in <VOLUMES>${a.volumes.idle ? ' correct nothing' : ''}` : ''})` : '')
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
    $('rtmTMinUnit').textContent = u.symbol;
    $('rtmGradTMinUnit').textContent = u.symbol;
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
    state.compiled = reply.model;
    // A look at the run before this one, through PHREEQC, stays on its tab and says which run it is.
    runNumber++;
    renderFacts();
    infoRefresh();
    renderSeriesList();
    renderCells();
    renderProfileSpecies();
    renderGradSpecies();
    renderComp();
    renderDg();
    renderSw();
    renderFit();
    renderUn();
    drawTime();
    drawProfile();
    drawGradient();
    drawComp();
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
    if (!state.running && !dgBusy) return;
    if (worker) { worker.terminate(); worker = null; workerKind = 'none'; pending.clear(); }
    state.running = false;
    // A sweep or a diagram stopped with the worker: what waited on it never hears, so its buttons come back here.
    swBusy = false;
    dgBusy = false;
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
    water's pH, pe and ionic strength, element totals, saturation indices,
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
  const GROUP_ORDER = ['water', 'totals', 'saturation', 'gases', 'exchange', 'surface', 'outputs', 'activities'];
  const GROUP_LABELS = { species: 'Species', water: 'The water', totals: 'Totals in the water', saturation: 'Saturation indices',
    gases: 'Gases', exchange: 'On the exchanger', surface: 'On the surface', outputs: 'From <OUTPUT>', activities: 'Log activities' };
  // Shut until opened: the log activities, one a solute.
  const GROUP_SHUT = new Set(['activities']);
  /** A key as the charts and their legends name it: a species its name, a quantity its label. */
  const labelOf = (key) => (isQuantity(key) ? quantityOf(key).label : key);
  /** Which axis a key goes on: the left for a species and an amount, the right for the rest. */
  const axisOf = (key) => (isQuantity(key) && quantityOf(key).axis === 'index' ? 'index' : 'conc');

  /** The groups a picker offers, in order: the species, then each group of quantities that has any. */
  function pickerGroups() {
    const groups = [{ id: 'species', items: speciesNames().map((nm) => ({ key: nm, label: nm })) }];
    for (const g of GROUP_ORDER) {
      const items = quantityList().filter((q) => q.group === g).map((q) => ({ key: q.key, label: q.label }));
      if (items.length) groups.push({ id: g, items });
    }
    return groups;
  }

  /** <optgroup>s of every key a one-quantity chart can show, `chosen` selected. */
  function pickerOptions(chosen) {
    return pickerGroups().map((g) => `<optgroup label="${esc(GROUP_LABELS[g.id])}">${g.items.map((it) => `<option value="`
      + `${esc(it.key)}"${it.key === chosen ? ' selected' : ''}>${esc(it.label)}</option>`).join('')}</optgroup>`).join('');
  }

  function renderSeriesList() {
    const box = $('rtmSeries');
    const picked = new Set(state.picked);
    const groups = pickerGroups();
    // The title is the name alone, for one too long for its cell. Which
    // species do not move is in the (i) of this tab, pane:time. With
    // quantities beside the species, each group has a heading across the grid,
    // and one long group (the log activities) is shut until it is opened.
    box.innerHTML = groups.map((g) => {
      const shut = groups.length > 1 && (state.sections[`series:${g.id}`] === undefined
        ? GROUP_SHUT.has(g.id) : !state.sections[`series:${g.id}`]);
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
    The quantities of the run on show, worked out in the worker from the
    model and the stored concentrations it kept, and kept here: key|cell ->
    the value at every stored point, cell counted as the model counts its
    cells, rock layers included.
  */
  let qCache = new Map();
  let qCacheRun = null;
  const qAsked = new Set();
  const qFailed = new Set();
  function quantityCache() {
    if (qCacheRun !== state.result) { qCache = new Map(); qCacheRun = state.result; qAsked.clear(); qFailed.clear(); }
    return qCache;
  }
  /** Whether a quantity in a model cell is still to come: neither kept nor given up on. */
  const quantityPending = (key, cell) => !quantityCache().has(`${key}|${cell}`) && !qFailed.has(`${key}|${cell}`);

  /** A quantity's values in model cell `cell`, or null until worked out (fetchQuantities). */
  function quantitySeries(key, cell) {
    return quantityCache().get(`${key}|${cell}`) || null;
  }

  /**
   * Has the worker work out the quantities `keys` in model cells `cells` at
   * every stored point of the run, unless they are kept or asked for
   * already, and draws the charts again once they come. A worker started
   * again since the run has lost it, and the run is sent with the question.
   * One that fails is not asked again for this run: the status says why.
   */
  async function fetchQuantities(keys, cells) {
    const r = state.result;
    if (!r || !keys.length || !cells.length) return;
    const cache = quantityCache();
    const want = [];
    for (const k of keys) for (const c of cells) if (!cache.has(`${k}|${c}`) && !qAsked.has(`${k}|${c}`)) want.push([k, c]);
    if (!want.length) return;
    want.forEach(([k, c]) => qAsked.add(`${k}|${c}`));
    const wk = [...new Set(want.map(([k]) => k))];
    const wc = [...new Set(want.map(([, c]) => c))];
    const ask = (withRun) => request({ type: 'quantities', runKey: r.runKey, keys: wk, cells: wc,
      ...(withRun ? { text: (state.ran && state.ran.text) || state.text, t: Float64Array.from(r.t),
        states: Float64Array.from(r.states), n: r.n, width: r.width } : {}) });
    try {
      let reply = await ask(false);
      if (reply.missing) reply = await ask(true);
      if (qCacheRun !== r) return;
      const nc = reply.cells.length;
      reply.keys.forEach((k, q) => reply.cells.forEach((c, j) => {
        cache.set(`${k}|${c}`, reply.values.subarray((q * nc + j) * reply.n, (q * nc + j + 1) * reply.n));
      }));
      drawTime();
      drawProfile();
      drawGradient();
    } catch (e) {
      want.forEach(([k, c]) => qFailed.add(`${k}|${c}`));
      setStatus(`Could not work out ${wk.map(labelOf).join(', ')}: ${e.message}`, 'error');
    }
  }

  /** The model cell a chart's cell and layer are: the fracture cell, then its rock layers. */
  const modelCell = (cell, layer) => {
    const r = state.result;
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
    renderLayerPickers();
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
    // An end of the column has no rock behind it.
    $('rtmLayerWrap').hidden = nm === 0 || isFace(state.cell);
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

  // The distance and gradient charts' pickers: every species, then every quantity, grouped.
  function renderProfileSpecies() {
    const names = speciesNames();
    if (!names.includes(state.profileSpecies) && !quantityOf(state.profileSpecies)) state.profileSpecies = names[0] || '';
    $('rtmProfileSpecies').innerHTML = pickerOptions(state.profileSpecies);
  }

  function renderGradSpecies() {
    const names = speciesNames();
    if (!names.includes(state.gradSpecies) && !quantityOf(state.gradSpecies)) state.gradSpecies = names[0] || '';
    $('rtmGradSpecies').innerHTML = pickerOptions(state.gradSpecies);
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
  function series(name, cell, layer = state.layer) {
    const r = state.result;
    // A quantity: as the worker worked it out, or null until it has (fetchQuantities). An end has none.
    if (isQuantity(name)) return isFace(cell) ? null : quantitySeries(name, modelCell(cell, layer));
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

  function drawTime() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartTime');
    const empty = $('rtmTimeEmpty');
    const r = state.result;
    if (!r || !state.picked.length) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = r ? 'Tick a species to draw it.' : 'Run the model, then tick a species to draw it.';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    // The quantities picked that the worker has still to work out: asked for, and drawn when they come.
    const face = isFace(state.cell);
    const missing = face ? [] : state.picked.filter((k) => isQuantity(k) && quantityPending(k, modelCell(state.cell, state.layer)));
    if (missing.length) fetchQuantities(missing, [modelCell(state.cell, state.layer)]);
    const logT = $('rtmLogT').checked;
    const logY = $('rtmLogY').checked;
    const tmin = Number($('rtmTMin').value) || 0;
    const traces = [];
    const right = [];
    const skipped = [];
    // Each key its colour, its measured points the same: Plotly's own ten, in the order picked.
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    for (const [pickIndex, nm] of state.picked.entries()) {
      const color = palette[pickIndex % palette.length];
      const y = series(nm, state.cell);
      if (!y) { if (face && isQuantity(nm)) skipped.push(labelOf(nm)); continue; }
      // An amount goes on the left with the species, log or not; pH, SI and the like on the right, linear.
      const onRight = axisOf(nm) === 'index';
      const xs = [];
      const ys = [];
      for (let i = 0; i < r.n; i++) {
        const t = r.t[i];
        if (logT && !(t >= tmin && t > 0)) continue;
        const v = y[i];
        if (!Number.isFinite(v) || (logY && !onRight && !(v > 0))) continue;
        xs.push(t);
        ys.push(v);
      }
      if (onRight) right.push(labelOf(nm));
      if (xs.length) {
        traces.push({ name: labelOf(nm), x: xs, y: ys, mode: 'lines', type: 'scatter', line: { color },
          ...(onRight ? { yaxis: 'y2' } : {}) });
      }
      // What <DATA> measured of it, at this cell and layer: points.
      if (!face) {
        for (const d of measured('time', nm)) {
          if ((d.tab.cell || 0) !== state.cell || (d.tab.layer || 0) !== state.layer) continue;
          traces.push({ name: `${labelOf(nm)}, measured`, x: d.x, y: d.y, mode: 'markers', type: 'scatter',
            marker: { size: 8, symbol: 'circle-open', color, line: { width: 1.6 } }, ...(onRight ? { yaxis: 'y2' } : {}) });
        }
      }
    }
    const layout = baseLayout();
    layout.xaxis.type = logT ? 'log' : 'linear';
    layout.xaxis.title = { text: `time (${timeUnit().symbol})`, font: { size: 11 } };
    layout.yaxis.type = logY ? 'log' : 'linear';
    // An end's flux is per m2 of the water's cross-section, positive to the right.
    layout.yaxis.title = { text: face
      ? `flux through the ${state.cell} end (concentration · m/${timeUnit().symbol})` : 'concentration', font: { size: 11 } };
    if (right.length) {
      const c = themeColors();
      layout.yaxis2 = { overlaying: 'y', side: 'right', gridcolor: c.grid, zeroline: false, linecolor: c.grid, showgrid: false,
        title: { text: right.join(', '), font: { size: 11 } } };
      layout.margin.r = 64;
    }
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    $('rtmTimeNote').textContent = [missing.length ? `working out ${missing.map(labelOf).join(', ')}…` : '',
      skipped.length ? `${skipped.join(', ')}: a quantity of the water, which an end has none of` : ''].filter(Boolean).join('; ');
  }

  function drawProfile() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartProfile');
    const empty = $('rtmProfileEmpty');
    const r = state.result;
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
    const valueAt = (i, k) => (quantity ? (quantitySeries(name, cellAt(k)) || [])[i] : r.states[i * r.width + stateIndex(k)]);
    // Either the times the reader asked for, or eight spread over the run: a
    // profile is only readable with a handful of curves on it.
    const asked = parseTimes(state.profileTimes);
    const picks = [];
    const past = [];
    if (asked.times.length) {
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
    const traces = picks.map((i) => {
      const y = [];
      for (let k = 0; k < npts; k++) y.push(valueAt(i, k));
      return { name: fmtTime(r.t[i]), x, y, mode: across ? 'lines+markers' : 'lines', type: 'scatter' };
    });
    // What <DATA> measured of it along the column: points, at the time each table says, the end of the run unless it says.
    if (!across) {
      for (const d of measured('distance', name)) {
        const at = d.tab.at !== null ? d.tab.at : r.t[r.n - 1];
        traces.push({ name: `measured, ${fmtTime(at)}`, x: d.x, y: d.y, mode: 'markers', type: 'scatter',
          marker: { size: 8, symbol: 'circle-open', color: themeColors().text, line: { width: 1.6 } } });
      }
    }
    const layout = baseLayout();
    layout.xaxis.title = { text: across ? `depth into the rock behind cell ${atCell} (m)`
      : 'distance from the left-hand face (m)', font: { size: 11 } };
    // pH, SI and the like are drawn as they are; an amount log or not, as the box says.
    const index = quantity && axisOf(name) === 'index';
    layout.yaxis.type = $('rtmProfileLog').checked && !index ? 'log' : 'linear';
    const q = quantity ? quantityOf(name) : null;
    layout.yaxis.title = { text: q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : `${name} concentration`,
      font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    /*
      The run is stored thinned, so a wanted time lands on the nearest point
      that was kept. The legend shows the time drawn rather than the time
      asked for, and this says so when the two are not the same.
    */
    const bits = [across ? `${nm} layers to ${r.model.matrix.total} m, the fracture at depth 0`
      : `${r.model.fracture} cells over ${r.model.length} m${nm && layer ? `, rock layer ${layer}` : ''}`];
    if (asked.bad.length) bits.push(`could not read ${asked.bad.join(', ')}`);
    if (past.length) bits.push(`${past.map(fmtTime).join(', ')} past the end of the run`);
    if (asked.times.length && picks.length) {
      const off = asked.times.filter((w) => {
        const got = r.t[nearestIndex(r.t, w)];
        return Math.abs(got - w) > 0.01 * Math.max(w, 1e-300);
      });
      if (off.length) bits.push(`nearest stored time used for ${off.map(fmtTime).join(', ')}`);
    }
    $('rtmProfileNote').textContent = bits.join('; ');
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
    const valueAt = (i, c) => (quantity ? (quantitySeries(name, c * stride + gl) || [])[i]
      : r.states[i * r.width + (c * stride + gl) * ns + si]);

    /*
      A log time axis cannot show t = 0, and a stiff run's first steps are
      femtoseconds -- fifteen decades in which nothing has happened yet. So the
      same "from" the time chart has, and the note says what it left out.
    */
    const tmin = Number($('rtmGradTMin').value) || 0;
    const cols = [];
    for (let i = 0; i < r.n; i++) if (!logT || (r.t[i] > 0 && r.t[i] >= tmin)) cols.push(i);
    if (!cols.length) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      empty.textContent = `Nothing is stored after ${fmtTime(tmin)}: lower the "from" time.`;
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
    layout.xaxis.title = { text: `time (${timeUnit().symbol})`, font: { size: 11 } };
    layout.yaxis.title = { text: 'distance from the left-hand face (m)', font: { size: 11 } };
    // Distance up the page from zero at the origin, the ordinary way round.
    // As a map, as contours of it, or as a surface over time and distance.
    const view = state.gradView || 'map';
    const title = q ? `${q.label}${q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''}` : name;
    const trace = {
      type: view === 'contour' ? 'contour' : view === 'surface' ? 'surface' : 'heatmap',
      x: cols.map((i) => r.t[i]),
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
        ? 't = %{x:.3e} s<br>x = %{y:.3e} m<br>log₁₀ c = %{z:.3f}<extra></extra>'
        : 't = %{x:.3e} s<br>x = %{y:.3e} m<br>c = %{z:.4e}<extra></extra>',
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
      const ax = (text, type) => ({ title: { text, font: { size: 11 } }, type, gridcolor: c.grid, color: c.text });
      layout.scene = { xaxis: ax(`time (${timeUnit().symbol})`, logT ? 'log' : 'linear'), yaxis: ax('distance (m)', 'linear'),
        zaxis: ax(logC ? `log₁₀ ${title}` : title, 'linear'), camera: { eye: { x: -1.6, y: -1.6, z: 1.0 } } };
      layout.margin = { l: 0, r: 0, t: 10, b: 0 };
    }
    Plotly.react(plot, [trace], layout, PLOT_CONFIG);
    const bits = [`${cells} cells × ${cols.length} stored times${gl ? `, rock layer ${gl}` : ''}`];
    if (Number.isFinite(lo)) {
      bits.push(logC ? `10^${lo.toFixed(2)} to 10^${hi.toFixed(2)}`
        : `${lo.toExponential(3)} to ${hi.toExponential(3)}`);
    } else bits.push('nothing to show: every value is zero or below');
    if (logT && cols.length < r.n) {
      bits.push(`${r.n - cols.length} earlier points left off (t = 0 cannot go on a log axis)`);
    }
    if (nonPositive) bits.push(`${nonPositive} values at or below zero left blank`);
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
    $('rtmCompAlongWrap').hidden = !column;
    const cells = m ? m.fracture : 1;
    if (!(state.compCell < cells)) state.compCell = 0;
    $('rtmCompCell').innerHTML = Array.from({ length: cells }, (_, i) => `<option value="${i}"${i === state.compCell ? ' selected' : ''}>`
      + `${i}${m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : ''}</option>`).join('');
    $('rtmCompCellWrap').hidden = along !== 'time' || cells < 2;
    const nm = m && m.matrix ? m.matrix.n : 0;
    if (state.compLayer > nm) state.compLayer = 0;
    $('rtmCompLayer').innerHTML = layerOptions(state.compLayer);
    $('rtmCompLayerWrap').hidden = nm === 0;
    // Along the run, the times are those the water is drawn at (where an element is needs none); across the column, one time.
    $('rtmCompTimesWrap').hidden = along === 'time' && view === 'where';
    $('rtmCompTimesLabel').textContent = along === 'time' ? 'Times' : 'At';
    $('rtmCompTimes').placeholder = along === 'time' ? 'spread over the run' : 'the end of the run';
    $('rtmCompTimes').value = state.compTimes;
    $('rtmCompLogTWrap').hidden = along !== 'time' || view === 'schoeller' || view === 'stiff';
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
    const fail = (text) => {
      Plotly.purge(plot);
      plot.hidden = true;
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
    // Across the column, one time: the first asked for, or the end of the run.
    const asked = parseTimes(state.compTimes);
    const atIndex = asked.times.length ? nearestIndex(r.t, asked.times[0]) : r.n - 1;
    const ctx = { r, plot, along, layer, cell, asked, atIndex, column, fail, note };
    empty.hidden = true;
    plot.hidden = false;
    if (state.compView === 'where') drawWhere(ctx);
    else drawWaters(ctx);
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
  function drawWhere({ r, plot, along, layer, cell, atIndex, fail, note }) {
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
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    const xHead = along === 'time' ? `t (${timeUnit().symbol})` : 'distance (m)';
    compTableNow = { head: [xHead, ...kept.map((b) => `${b.name}${percent ? ' (%)' : ''}`), `${E.el} ${where}, all of it`],
      rows: xs.map((x, j) => [x, ...shown.map((col) => col[j]), total[j]]),
      name: `rtm_${E.el}_${along === 'time' ? `cell${cell}` : 'column'}` };
    const bits = [along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}, ${npts} stored points`
      : `${npts} cells at ${fmtTime(r.t[atIndex])}${layer ? `, rock layer ${layer}` : ''}`,
    `${E.terms.length} species hold ${E.el} ${where}`];
    if (small.length > 1) bits.push(`${small.length} never come to 1 %, drawn as one band`);
    if (along === 'distance' && state.compTimes.trim() && Math.abs(r.t[atIndex] - parseTimes(state.compTimes).times[0])
      > 0.01 * Math.abs(r.t[atIndex] || 1)) bits.push('the nearest stored time');
    note.textContent = bits.join('; ');
  }

  /**
   * The water's major ions, from the model and from <DATA>: as a Piper
   * diagram, a path through the run or along the column; as a Schoeller
   * diagram, a line per water; or as Stiff diagrams, one per water.
   */
  function drawWaters({ r, plot, along, layer, cell, asked, atIndex, fail, note }) {
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
      if (view === 'piper') {
        // The path through the run: every stored point after "from", a few hundred at most.
        const { idx, logT } = compTimeIndices(r);
        const step = Math.max(1, Math.ceil(idx.length / 300));
        const take = idx.filter((_, j) => j % step === 0 || j === idx.length - 1);
        for (const i of take) {
          waters.push({ w: waterAt(r, terms, unit.scale, i, mc), t: r.t[i], cell, label: fmtTime(r.t[i]),
            color: logT ? Math.log10(r.t[i]) : r.t[i] });
        }
        colorTitle = logT ? `log₁₀ time (${timeUnit().symbol})` : `time (${timeUnit().symbol})`;
      } else {
        // The times asked for, or six spread over the run.
        const picks = asked.times.length ? [...new Set(asked.times.map((tt) => nearestIndex(r.t, tt)))]
          : [...new Set(Array.from({ length: 6 }, (_, k) => Math.round(((k + 1) / 6) * (r.n - 1))))];
        if (!asked.times.length && r.t[0] === 0) picks.unshift(0);
        for (const i of [...new Set(picks)]) waters.push({ w: waterAt(r, terms, unit.scale, i, mc), t: r.t[i], cell, label: fmtTime(r.t[i]) });
      }
    } else {
      const nf = r.model.fracture;
      const cells = view === 'piper' ? Array.from({ length: nf }, (_, k) => k)
        : [...new Set(Array.from({ length: Math.min(6, nf) }, (_, k) => Math.round((k * (nf - 1)) / Math.max(1, Math.min(6, nf) - 1))))];
      for (const k of cells) {
        waters.push({ w: waterAt(r, terms, unit.scale, atIndex, k * stride + layer), t: r.t[atIndex], cell: k,
          x: r.model.centres[k], label: `cell ${k}, ${fmtNumber(Number(r.model.centres[k].toPrecision(3)))} m`, color: r.model.centres[k] });
      }
      colorTitle = 'distance (m)';
    }
    const measuredHere = measuredWaters(along, cell, layer, unit.scale);
    const all = [...waters, ...measuredHere];
    for (const wt of all) { wt.f = poleShares(wt.w); }
    const drawable = waters.filter((wt) => wt.f);
    if (!drawable.length) { fail('No water here has both cations and anions among the major ions to draw.'); return; }
    const xHead = [`t (${timeUnit().symbol})`, 'cell', 'distance (m)'];
    compTableNow = {
      head: ['water', ...xHead, ...POLES.map((p) => `${p.label} (${unit.text})`), ...POLES.map((p) => `${p.label} (% of the ${p.cation ? 'cations' : 'anions'})`), 'type'],
      rows: all.map((wt) => [wt.measured ? wt.label : `model, ${wt.label}`, wt.t, wt.cell, wt.x !== undefined ? wt.x : null,
        ...POLES.map((p) => wt.w[p.key]), ...POLES.map((p) => (wt.f ? 100 * wt.f[p.key] : null)), wt.f ? faciesOf(wt.f) : null]),
      name: `rtm_${view}_${along === 'time' ? `cell${cell}` : 'column'}`,
    };
    const where = along === 'time' ? `cell ${cell}${layer ? `, rock layer ${layer}` : ''}` : `the column at ${fmtTime(r.t[atIndex])}`;
    const bits = [];
    if (view === 'piper') {
      drawPiper(plot, drawable, measuredHere.filter((wt) => wt.f), colorTitle, c);
      const first = drawable[0];
      const last = drawable[drawable.length - 1];
      bits.push(along === 'time'
        ? `${where}: ${faciesOf(first.f)} at ${first.t <= r.t[Math.min(2, r.n - 1)] ? 'the start' : fmtTime(first.t)}`
          + `${drawable.length > 1 ? `, ${faciesOf(last.f)} at ${fmtTime(last.t)}` : ''}`
        : `${where}: ${faciesOf(first.f)} in cell ${first.cell}${drawable.length > 1 ? `, ${faciesOf(last.f)} in cell ${last.cell}` : ''}`);
    } else if (view === 'schoeller') {
      drawSchoeller(plot, drawable, measuredHere.filter((wt) => wt.f), unit, c);
      bits.push(`${where}: ${drawable.length} water${drawable.length === 1 ? '' : 's'}`);
    } else {
      drawStiff(plot, drawable, measuredHere.filter((wt) => wt.f), unit, c);
      bits.push(`${where}: ${drawable.length} water${drawable.length === 1 ? '' : 's'}`);
    }
    if (measuredHere.length) bits.push(`${measuredHere.length} measured`);
    if (missing.length) bits.push(`the model has no ${missing.join(', ')}`);
    if (asked.bad.length) bits.push(`could not read ${asked.bad.join(', ')}`);
    note.textContent = bits.join('; ');
  }

  function drawPiper(plot, waters, measured, colorTitle, c) {
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

  function drawSchoeller(plot, waters, measured, unit, c) {
    const palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
    const labels = POLES.map((p) => p.label);
    // On a log axis a pole the water has none of is a gap.
    const ys = (wt) => POLES.map((p) => (wt.w[p.key] > 0 ? wt.w[p.key] : null));
    const traces = waters.map((wt, q) => ({ type: 'scatter', mode: 'lines+markers', name: wt.label, x: labels, y: ys(wt),
      line: { color: palette[q % palette.length], width: 1.6 }, marker: { size: 6 },
      hovertemplate: `${esc(wt.label)}: %{x} %{y:.4g} ${esc(unit.text)}<extra></extra>` }));
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
    // A line between the cations and the anions.
    layout.shapes = [{ type: 'line', xref: 'x', yref: 'paper', x0: 2.5, x1: 2.5, y0: 0, y1: 1, line: { color: c.grid, width: 1, dash: 'dot' } }];
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  /**
   * Stiff diagrams, one per water, on one scale so that their sizes compare:
   * the cations to the left of zero -- Na + K, Ca, Mg from the top -- and
   * the anions to the right -- Cl, HCO3 + CO3, SO4 -- the points joined.
   */
  function drawStiff(plot, waters, measured, unit, c) {
    const all = [...waters, ...measured].slice(0, 12);
    const n = all.length;
    const cols = n <= 3 ? n : n <= 4 ? 2 : n <= 6 ? 3 : 4;
    const rows = Math.ceil(n / cols);
    let most = 0;
    for (const wt of all) for (const p of POLES) most = Math.max(most, wt.w[p.key]);
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

     The water of one cell held at each point of a range of pH, pe, a
     species' activity or an element's total -- or of two ranges -- and
     speciated there by the model's relations, in the worker (rtmDiagram in
     rtm-worker.js). What comes back is every point's concentrations and
     every quantity, so each way of drawing it is drawn here without asking
     again.
     --------------------------------------------------------------------- */
  // Where each kind of axis starts and ends unless it is given, and what it is called.
  const DG_RANGES = { pH: ['2', '12'], pe: ['-12', '16'], la: ['-10', '-2'], tot: ['-8', '-2'] };
  const dgLabel = (ax) => (ax.kind === 'pH' ? 'pH' : ax.kind === 'pe' ? 'pe' : ax.kind === 'la' ? `log a(${ax.species})`
    : `log total ${ax.species} in the cell (mol/kgw)`);
  let dgResult = null;
  let dgTableNow = null;
  let dgBusy = false;

  /** The species an activity can be held of, the solutes; the elements a total can be given of. */
  function dgChoices(kind) {
    const m = state.compiled;
    if (!m) return [];
    if (kind === 'la') return (m.solutes || []).filter((nm) => nm !== 'H2O');
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
    $('rtmDgGo').disabled = dgBusy;
  }

  /** The show menu for what was worked out: a range of one thing, or a grid of two. */
  function renderDgShow() {
    const bar = $('rtmDgShowBar');
    bar.hidden = !dgResult;
    if (!dgResult) return;
    const two = !!dgResult.reply.y;
    const opts = two
      ? [['predominance', 'the species that holds most of an element'], ['phase', 'the phase furthest over saturation, or at it'],
        ['contour', 'a species or a quantity, as contours']]
      : [['shares', 'the species of an element, as shares'], ['logc', 'the species of an element, as log concentrations'],
        ['si', 'the saturation indices'], ['quantity', 'a species or a quantity']];
    const d = state.dg;
    if (!opts.some(([v]) => v === d.show)) d.show = opts[0][0];
    $('rtmDgShow').innerHTML = opts.map(([v, t]) => `<option value="${v}"${v === d.show ? ' selected' : ''}>${esc(t)}</option>`).join('');
    const C = dgResult.composition;
    const els = C ? C.elements.filter((e) => (d.in === 'all' ? e.terms : e.terms.filter((tm) => tm[2] === 'water')).length > 1)
      .map((e) => e.el) : [];
    if (els.length && !els.includes(d.el)) d.el = els[0];
    $('rtmDgEl').innerHTML = els.length ? els.map((e) => `<option value="${esc(e)}"${e === d.el ? ' selected' : ''}>${esc(e)}</option>`).join('')
      : '<option value="">none</option>';
    $('rtmDgIn').value = d.in;
    const byEl = ['shares', 'logc', 'predominance'].includes(d.show);
    $('rtmDgElWrap').hidden = !byEl;
    $('rtmDgInWrap').hidden = !byEl;
    $('rtmDgQWrap').hidden = !(d.show === 'quantity' || d.show === 'contour');
    if (!speciesNames().includes(d.q) && !quantityOf(d.q)) d.q = quantityOf('pH') ? 'pH' : (speciesNames()[0] || '');
    $('rtmDgQ').innerHTML = pickerOptions(d.q);
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
    const axes = [axis(d.x), ...(d.y.kind ? [axis(d.y)] : [])];
    const bad = axes.find((ax) => !Number.isFinite(ax.from) || !Number.isFinite(ax.to) || !(ax.n >= 2 && ax.n <= 400));
    if (bad) { setStatus('Each axis needs a from, a to and from 2 to 400 points.', 'error'); return; }
    const r = state.result;
    if (d.at === 'end' && !r) { setStatus('Run the model first: the water as it ends the run is what the run leaves.', 'error'); return; }
    const text = d.at === 'end' ? ((state.ran && state.ran.text) || state.text) : state.text;
    const stride = (state.compiled && state.compiled.stride) || 1;
    const ask = (withRun) => request({ type: 'diagram', text, at: d.at, cell: d.cell * stride, axes,
      ...(d.at === 'end' ? { runKey: r.runKey } : {}),
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
      dgResult = { reply, axes, composition: state.compiled.composition, at: d.at, cell: d.cell };
      setProgress(null);
      setStatus(`Diagram worked out in ${((Date.now() - started) / 1000).toFixed(2)} s: ${(reply.n1 * reply.n2).toLocaleString()} points`
        + `${reply.failed ? `, ${reply.failed.toLocaleString()} of which did not settle and are left blank` : ''}.`,
      reply.failed ? 'warn' : 'ok');
      renderDgShow();
      drawDg();
    } catch (e) {
      setProgress(null);
      setStatus(`The diagram could not be worked out: ${e.message}`, 'error');
    } finally {
      dgBusy = false;
      $('rtmDgGo').disabled = false;
      $('rtmStop').disabled = !state.running;
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
    const ys = Array.from(rp.y);
    const n1 = rp.n1;
    const n2 = rp.n2;
    layout.yaxis.title = { text: dgLabel(ay), font: { size: 11 } };
    layout.margin.r = 30;
    const shapes = [];
    // Water's own limits on a pe-pH diagram, at 25 C and one atmosphere: O2 above, H2 below.
    const pePh = (ax.kind === 'pH' && ay.kind === 'pe') || (ax.kind === 'pe' && ay.kind === 'pH');
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
      ...dgWaterLines(pePh, xs, ys)], { ...layout, shapes }, PLOT_CONFIG);
      dgTableNow = { head: [`${dgLabel(ay)} \\ ${dgLabel(ax)}: ${title}`, ...xs], rows: ys.map((y, j) => [y, ...z[j]]),
        name: `rtm_diagram_${ax.kind}_${ay.kind}` };
      note.textContent = `${where}; ${n1} × ${n2} points${rp.failed ? `, ${rp.failed} left blank: they did not settle` : ''}`;
      return;
    }
    // A map of names: at each point, the species holding most of the element, or the phase furthest over saturation.
    const names2 = [];
    const at = new Array(n1 * n2).fill(-1);
    const share = new Array(n1 * n2).fill(null);
    if (d.show === 'predominance') {
      const terms = dgTerms(d.el);
      if (terms.length < 2) { fail(`No two species hold ${d.el || 'an element'} ${d.in === 'all' ? 'in the cell' : 'in the water'}.`); return; }
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
        const [k, , wh] = terms[best];
        const label = wh === 'water' ? names[k] : `${names[k]} (${WHERE_LABELS[wh]})`;
        let c = names2.indexOf(label);
        if (c < 0) { c = names2.length; names2.push(label); }
        at[p] = c;
        share[p] = sum > 0 ? (100 * most) / sum : null;
      }
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
    }
    const m = names2.length;
    const colors = names2.map((nm, c) => (nm === 'none over saturation' ? themeColors().grid : DG_PALETTE[c % DG_PALETTE.length]));
    const scale = m === 1 ? [[0, colors[0]], [1, colors[0]]] : colors.flatMap((col, c) => [[c / m, col], [(c + 1) / m, col]]);
    const z = ys.map((_, j) => xs.map((_, i) => (at[j * n1 + i] >= 0 ? at[j * n1 + i] : null)));
    const text = ys.map((_, j) => xs.map((_, i) => {
      const p = j * n1 + i;
      if (at[p] < 0) return 'did not settle';
      return d.show === 'predominance' ? `${names2[at[p]]}: ${share[p] === null ? '' : `${share[p].toFixed(1)} %`}`
        : `${names2[at[p]]}${names2[at[p]] === 'none over saturation' ? `, the nearest SI ${share[p].toFixed(2)}` : `, SI ${(share[p] + 0).toFixed(2)}`}`;
    }));
    // Each field's name at the point of it nearest its middle.
    const annotations = names2.map((nm, c) => {
      let si = 0;
      let sj = 0;
      let cnt = 0;
      for (let p = 0; p < n1 * n2; p++) if (at[p] === c) { si += p % n1; sj += Math.floor(p / n1); cnt++; }
      const ci = si / cnt;
      const cj = sj / cnt;
      let bestP = -1;
      let gap = Infinity;
      for (let p = 0; p < n1 * n2; p++) {
        if (at[p] !== c) continue;
        const g = (p % n1 - ci) ** 2 + (Math.floor(p / n1) - cj) ** 2;
        if (g < gap) { gap = g; bestP = p; }
      }
      return { x: xs[bestP % n1], y: ys[Math.floor(bestP / n1)], text: esc(nm), showarrow: false,
        font: { size: 11, color: '#111' }, bgcolor: 'rgba(255,255,255,0.7)', borderpad: 2 };
    });
    layout.annotations = annotations;
    Plotly.react(plot, [{ type: 'heatmap', x: xs, y: ys, z, text, zmin: -0.5, zmax: m - 0.5, colorscale: scale, showscale: false,
      hovertemplate: `${esc(dgLabel(ax))} %{x:.3g}<br>${esc(dgLabel(ay))} %{y:.3g}<br>%{text}<extra></extra>` },
    ...dgWaterLines(pePh, xs, ys)], layout, PLOT_CONFIG);
    const counts = names2.map((nm, c) => [nm, at.filter((v) => v === c).length]);
    dgTableNow = { head: [dgLabel(ax), dgLabel(ay), d.show === 'predominance' ? `the species holding most of the ${d.el}`
      : 'the phase furthest over saturation, or at it', d.show === 'predominance' ? 'its share (%)' : 'its SI'],
    rows: at.map((c, p) => [xs[p % n1], ys[Math.floor(p / n1)], c >= 0 ? names2[c] : null, share[p]]),
    name: `rtm_diagram_${d.show}` };
    note.textContent = `${where}; ${n1} × ${n2} points: ${counts.map(([nm, k]) => `${nm} ${k}`).join(', ')}`
      + `${rp.failed ? `; ${rp.failed} left blank: they did not settle` : ''}`;
  }

  /**
   * On a pe-pH diagram, where water itself gives way, at 25 C and one
   * atmosphere: above pe + pH = 20.78 it gives off oxygen (O2 + 4H+ + 4e- =
   * 2H2O, log K 83.12), below pe + pH = 0 hydrogen -- the same two lines
   * whichever way round the axes are.
   */
  function dgWaterLines(pePh, xs, ys) {
    if (!pePh) return [];
    const c = themeColors();
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [lo, hi] = [Math.min(...ys), Math.max(...ys)];
    return [[20.78, 'water and O₂ at 1 atm, 25 °C'], [0, 'water and H₂ at 1 atm']].flatMap(([sum, name]) => {
      const xa = Math.max(x0, sum - hi);
      const xb = Math.min(x1, sum - lo);
      if (!(xa < xb)) return [];
      return [{ type: 'scatter', mode: 'lines', x: [xa, xb], y: [sum - xa, sum - xb], showlegend: false,
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
    if (all.length && !all.includes(w.what)) w.what = (all.find((v) => v === 'setting:VELOCITY' && m && m.transport)
      || all.find((v) => v.startsWith('parameter:')) || all.find((v) => v.startsWith('initial:')) || all[0]);
    if (w.what2 && !all.includes(w.what2)) w.what2 = '';
    const opts = (chosen) => groups.map((g) => `<optgroup label="${esc(g.label)}">${g.items.map((it) => `<option value="${esc(it.value)}"`
      + `${it.value === chosen ? ' selected' : ''}>${esc(it.label)}</option>`).join('')}</optgroup>`).join('');
    $('rtmSwWhat').innerHTML = opts(w.what);
    $('rtmSwWhat2').innerHTML = `<option value=""${w.what2 ? '' : ' selected'}>nothing else</option>${opts(w.what2)}`;
    $('rtmSwValues').value = w.values;
    $('rtmSwValues2').value = w.values2;
    $('rtmSwMore2').hidden = !w.what2;
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

  function renderSwShow() {
    $('rtmSwShowBar').hidden = !swResult;
    if (!swResult) return;
    const w = state.sw;
    const two = swResult.vary.length === 2;
    const column = swResult.reply.runs.some((r) => r.ok && r.nf > 1);
    const opts = [
      ...(two ? [['lines', 'against the first varied, a curve for each of the second'], ['contour', 'over the two, as contours'],
        ['surface', 'over the two, as a surface']] : [['summary', 'against what was varied']]),
      ['time', 'against time, a curve per run'], ...(column ? [['profile', 'along the column at the end, a curve per run']] : []),
    ];
    if (!opts.some(([v]) => v === w.show)) w.show = opts[0][0];
    $('rtmSwShow').innerHTML = opts.map(([v, t]) => `<option value="${v}"${v === w.show ? ' selected' : ''}>${esc(t)}</option>`).join('');
    if (!speciesNames().includes(w.key) && !quantityOf(w.key)) w.key = speciesNames()[0] || '';
    $('rtmSwKey').innerHTML = pickerOptions(w.key);
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
    $('rtmFitShowBar').hidden = !r;
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

  function drawFit() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('rtmChartFit');
    const empty = $('rtmFitEmpty');
    const note = $('rtmFitNote');
    fitTableNow = null;
    if (!fitResult) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      note.textContent = '';
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const r = fitResult;
    const show = $('rtmFitShow').value;
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
    if (!speciesNames().includes(u.key) && !quantityOf(u.key)) u.key = speciesNames()[0] || '';
    $('rtmUnKey').innerHTML = pickerOptions(u.key);
    $('rtmUnOf').value = u.of;
    $('rtmUnOfWrap').hidden = u.show === 'time' || u.show === 'profile';
    $('rtmUnLogTWrap').hidden = u.show !== 'time';
    $('rtmUnLogYWrap').hidden = u.show === 'matters' || (isQuantity(u.key) && quantityOf(u.key).axis === 'index');
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
    const face = isFace(state.cell);
    const keys = face ? [] : names.filter((k) => isQuantity(k));
    if (keys.length) await fetchQuantities(keys, [modelCell(state.cell, state.layer)]);
    // At a cell the layer shown, at an end what crosses it.
    const where = face ? `through the ${state.cell} end`
      : `@ cell ${state.cell}${state.layer > 0 && r.model.matrix ? ` rock ${state.layer}` : ''}`;
    const unitOf = (k) => { const q = isQuantity(k) ? quantityOf(k) : null; return q && q.unit && !q.label.includes(q.unit) ? ` (${q.unit})` : ''; };
    const head = [`t (${timeUnit().symbol})`, ...names.map((n) => `${labelOf(n)}${unitOf(n)} ${where}`)];
    const cols = names.map((n) => series(n, state.cell));
    const rows = [];
    for (let i = 0; i < r.n; i++) rows.push([r.t[i], ...cols.map((c) => (c && Number.isFinite(c[i]) ? c[i] : null))]);
    return { head, rows, name: face ? `rtm_${state.cell}_end` : `rtm_cell${state.cell}` };
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
      return { head: [`distance (m) \\ time (${timeUnit().symbol}): ${title}`, ...grid.x], name,
        rows: grid.y.map((y, j) => [y, ...grid.z[j].map((v) => (v === null || v === undefined ? null : v))]) };
    }
    const xs = [...new Set(data.flatMap((tr) => Array.from(tr.x || [])))].sort((a, b) => a - b);
    const xTitle = (plot.layout && plot.layout.xaxis && plot.layout.xaxis.title && plot.layout.xaxis.title.text) || 'x';
    const cols = data.map((tr) => {
      const m = new Map();
      Array.from(tr.x || []).forEach((x, i) => m.set(x, tr.y[i]));
      return m;
    });
    return { head: [xTitle, ...data.map((tr) => tr.name)], name,
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
    return chartTable(plot, `rtm_${pane}_${String(pane === 'profile' ? state.profileSpecies : state.gradSpecies).replace(/[^\w.-]+/g, '_')}`);
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
      diagram: 'rtmChartDg', sweep: 'rtmChartSw', fit: 'rtmChartFit', uncertainty: 'rtmChartUn' }[pane]);
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
    const text = (state.ran && state.ran.text) || state.text;
    xlsx.writeData(text.split('\n').map((ln) => [ln]), 'model', { header: ['the model text the run was made with'] });
    downloadBlob(await xlsx.save(), `${tab.name}.xlsx`);
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
    document.querySelectorAll('.rtm-tabs button').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === name);
    });
    document.querySelectorAll('.rtm-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    saveState();
    // Plotly needs telling once its div stops being display:none.
    if (name === 'time') { drawTime(); resize(); }
    if (name === 'profile') { drawProfile(); resize(); }
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

    'pane:time': () => {
      const m = state.compiled;
      const still = m && m.transport ? m.species.filter((_, i) => !m.mobile[i]) : [];
      return {
        kicker: 'Tab', title: 'Against time',
        lead: 'What is ticked in the list, at one cell, at every stored point of the run: species, and what the run comes to besides them — pH, totals, saturation indices and the rest.',
        sections: [
          { heading: 'The toolbar', list: [
            '**Cell**: which cell of the column, with its centre in metres from the left-hand face; or, after the cells, the **flux through the left end** or **the right end**: what crosses it per m² of the water’s cross-section, positive to the right, which at an outlet is the release. A batch is one cell and has no picker.',
            '**Layer**: with a rock matrix, the fracture or a layer of rock behind the cell, by the depth of its centre.',
            '**log time**, **log concentration**: logarithmic axes. A log axis cannot show zero, so t = 0, and values at or below zero, are left off.',
            '**from**: where a log time axis starts, a plain number in the model’s time unit. A stiff run’s first steps are femtoseconds long, and without it the chart opens on fifteen empty decades. A linear axis starts at 0 whatever it says.',
            '**clear**: unticks everything.',
            '**CSV**: what is ticked, or every species when nothing is, at the cell and layer shown or through the end shown, a row per stored point.',
            '**Excel**: the same as a workbook, with the model text on a sheet of its own. **SVG** and **PNG**: the chart as a figure, at the size it is drawn.',
            '**View in Data Browser**: the whole run as an HDF5 file, opened in the Data Browser in a new tab without touching the disk. The browser has to let the page open a tab.',
            '**HDF5**: the same file, as a download.',
          ] },
          { heading: 'The list', text: [
            'A ticked entry is filled in the accent colour. The species come first, then what the model can be read as besides them, in groups that open and shut: the water (pH, pe, ionic strength, a(H2O), charge balance), the totals of each element in the water, saturation indices, gases, what is on an exchanger or a surface, the text’s `<OUTPUT>`, and under an `ACTIVITY` the log activities, shut until opened. They are worked out from the stored concentrations with the model’s own activity model, the first time they are asked for.',
            'An amount goes on the left-hand axis with the species, log or not; pH, pe, a saturation index, a log activity or a share on the right, as it is. What `<DATA>` measured of something ticked is drawn as points beside it, at the cell its table names.',
            'In a column a species diffuses when it has a `D`, and with `ADVECTION` and a `VELOCITY` the flow carries every species that is not `fixed`, whatever its `D`.',
            still.length ? `In this model these do not move: ${someOf(still)}.` : '',
          ].filter(Boolean) },
        ],
        more: more('Taking the run away with you', 'help-export'),
      };
    },

    'pane:profile': () => ({
      kicker: 'Tab', title: 'Against distance',
      lead: 'One species, or one quantity, across the column at several times, a curve for each. It needs a run in transport mode: a batch has no distance.',
      sections: [
        { heading: 'The toolbar', list: [
          '**Show**: its own choice, apart from the ticks on Against time: a species, or a quantity of the water — pH, a total, a saturation index, a share of an exchanger, an `<OUTPUT>`. What `<DATA>` measured of it along the column is drawn as points.',
          '**Across**: with a rock matrix, along the fracture at one layer, or into the rock behind one cell, with the fracture at depth 0.',
          '**Layer**, or **At cell** into the rock: which layer the curve runs along, or which cell the rock is behind.',
          '**Times**: a list such as `0, 1 h, 30 d, 500 y`, in s, min, h, d, a or y (both years of 365.25 days); a bare number is in the model’s own unit. Empty draws eight, spread evenly over the stored points, the last at the end of the run.',
          '**log concentration**: a logarithmic axis, for an amount; pH, a saturation index or a share is drawn as it is.',
          '**CSV**, **Excel**: the curves drawn, a row per distance. **SVG**, **PNG**: the chart as a figure.',
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
            '**As**: a map, contours of it with their values on them, or a surface in three dimensions, the value up, which the mouse turns.',
            '**log time** and **from**: as on Against time. Without a from time the first femtoseconds take most of a log axis; the note says how many points it left off.',
            '**log concentration**: colours by log₁₀ c. Values at or below zero are left blank rather than put at the bottom of the scale, and the note counts them.',
            '**smooth**: interpolates between the cells. It looks better and claims a resolution the run has not got, which is why it is off.',
            '**CSV**, **Excel**: the numbers drawn, a row per cell and a column per time. **SVG**, **PNG**: the picture.',
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
        lead: 'What the water is made of, from the stored concentrations and what each species is made of: where an element is, and the water\'s major ions as the Piper, Schoeller and Stiff diagrams draw them.',
        sections: [
          { heading: 'Show', choices: [
            ['where an element is', 'Each species with any of the element, as its share of all of it, stacked to 100 %, or as its amount: in the water, or in the whole cell, on an exchanger or a surface, in a mineral and a gas too. A species that never comes to 1 % is drawn with the others like it, as one band.', view === 'where'],
            ['a Piper diagram', 'The cations\' shares in the triangle on the left, the anions\' on the right, and the two together in the diamond: a path through the run at one cell, coloured by time, or along the column at one time, coloured by distance.', view === 'piper'],
            ['a Schoeller diagram', 'Each water a line through its six major ions, in equivalents on a log axis: the same shape is the same water diluted.', view === 'schoeller'],
            ['Stiff diagrams', 'Each water a polygon, cations to the left of zero and anions to the right, on one scale so that their sizes compare.', view === 'stiff'],
          ] },
          { heading: 'The major ions', list: [
            'Ca and Mg are twice their dissolved totals, **Na + K** the two together, Cl its total, **SO₄** twice the sulfur in sulfate — a species with four O to each S, so not HS⁻ — and **HCO₃ + CO₃** the carbonate\'s alkalinity, HCO₃⁻ one and CO₃⁻² two. A total is everything dissolved: CaHCO₃⁺ counts in Ca and in the carbonate.',
            'In meq/kgw under an ACTIVITY, whose concentrations are mol/kgw; otherwise the concentrations times the charge.',
            'Measured waters come from <DATA>, by the names the model gives them: tot(Ca) or Ca+2, alk(CO3) or HCO3- and CO3-2. One the table has no column for counts as none.',
          ] },
          { heading: 'The toolbar', list: [
            '**Along**, in a column: the run at one **Cell**, or the column at one time, **At**.',
            '**Times**: the waters a Schoeller or Stiff diagram draws, six spread over the run unless given; a Piper draws every stored point.',
            '**CSV**, **Excel**: the numbers drawn — each band, or each water\'s ions, shares and type. **SVG**, **PNG**: the picture.',
          ] },
        ],
        more: more('Reading the charts', 'help-composition'),
      };
    },

    'pane:diagram': () => {
      const two = !!(dgResult && dgResult.reply.y);
      return {
        kicker: 'Tab', title: 'Diagrams',
        lead: 'The model\'s own chemistry, as PhreePlot draws PHREEQC\'s: the water of one cell held at each point of a range — a pH, a pe, a species\' activity or an element\'s total, or two of them — and speciated there by the relations of <EQUILIBRIUM>.',
        sections: [
          { heading: 'What is worked out', list: [
            '**The water of cell**, **as it starts** or **ends the run**: the water held. Its totals stay as they are, but for what is varied; there is no charge balance, as in PHREEQC\'s SOLUTION.',
            '**Vary**: **pH**, the activity of H+; **pe**, the electron\'s; **log activity of** a species dissolved; **log total of** an element in the cell, mol/kgw. **and** a second one makes a grid.',
            'A mineral there stays at saturation while there is any of it. A point that does not settle is left blank, and the status line counts them.',
            '**Work it out**: in the background; a grid of 101 × 41 takes a second or less.',
          ] },
          { heading: 'Show', list: two ? [
            '**the species that holds most of an element**, in the water or the whole cell: over pH and pe, a Pourbaix diagram, with the water\'s own limits, O₂ above and H₂ below at 1 atm and 25 °C.',
            '**the phase furthest over saturation, or at it**: a mineral stability diagram.',
            '**a species or a quantity, as contours**: its log where it is an amount.',
          ] : [
            '**the species of an element** as shares of it, or as log concentrations.',
            '**the saturation indices** of every phase and mineral.',
            '**a species or a quantity**: pH, a total, an <OUTPUT>, …',
          ] },
          { heading: 'Saving', list: ['**CSV**, **Excel**: a row per point, what is drawn there. **SVG**, **PNG**: the picture.'] },
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
          '**keeping cell**: the cell whose every species and quantity is kept along each run; along the column, each run\'s end is kept whole.',
          'A run that fails says why on the status line, and the rest go on. Stop stops them all.',
        ] },
        { heading: 'Show', list: [
          '**against what was varied**: a species or a quantity at the cell, its value at the end, its largest or its smallest, a point per run; over two, a curve for each value of the second, contours or a surface.',
          '**against time, a curve per run**, at the cell; **along the column at the end, a curve per run**. The curves go from dark to light as the value grows.',
        ] },
        { heading: 'Saving', list: ['**CSV**, **Excel**: what is drawn, a row per value or per point. **SVG**, **PNG**: the picture.'] },
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
          '**Put the fitted values in the model**: each written into the text where it came from, to six figures.',
          '**CSV**, **Excel**: each point measured, the run there and its residual. **SVG**, **PNG**: the picture.',
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
          '**what matters**: Spearman\'s rank correlation of each number drawn with that value, from −1 to 1.',
        ] },
        { heading: 'Saving', list: ['**CSV**, **Excel**: the percentiles at each time or cell, or each run\'s numbers and value. **SVG**, **PNG**: the picture.'] },
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
    if (!v) return;
    if (v.picked) state.picked = v.picked.slice();
    if (Number.isInteger(v.cell)) state.cell = v.cell;
    if (typeof v.logT === 'boolean') $('rtmLogT').checked = v.logT;
    if (typeof v.logY === 'boolean') $('rtmLogY').checked = v.logY;
    if (v.grad) {
      if (v.grad.species) state.gradSpecies = v.grad.species;
      if (v.grad.view) { state.gradView = v.grad.view; $('rtmGradView').value = v.grad.view; }
    }
    if (v.comp) for (const [k, val] of Object.entries(v.comp)) state[`comp${k[0].toUpperCase()}${k.slice(1)}`] = val;
    if (v.dg) {
      for (const [k, val] of Object.entries(v.dg)) {
        if (k === 'x' || k === 'y') Object.assign(state.dg[k], val);
        else state.dg[k] = val;
      }
    }
    if (v.sw) Object.assign(state.sw, v.sw);
  }

  /** After a run, the view an example asked for: its tab, and a diagram or a sweep worked out there. */
  function openExampleView() {
    const v = pendingView;
    pendingView = null;
    if (!v || !v.tab) return;
    showTab(v.tab);
    // After the run has let go of the worker: a sweep waits for no run.
    setTimeout(() => {
      if (v.tab === 'diagram' && v.go) dgGo();
      if (v.tab === 'sweep' && v.go) swGo();
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
  const PQ_WORKER_URL = 'resources/js/rtm-phreeqc-worker.js?v=20261109i';
  const PQ_SCRIPTS = [
    'vendors/phreeqc/phreeqc.js?v=20261107',
    'vendors/phreeqc/phreeqc-dat.js?v=20261107',
    'resources/js/rtm-phreeqc.js?v=20261109b',
    'resources/js/rtm-phreeqc-engine.js?v=20261107b',
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
        open: pq.open,
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
    'rtm:stop': () => stop(),
    'rtm:verify': () => { verify(); },
    'rtm:tab': (ev, el) => showTab(el.dataset.tab),
    'rtm:full': () => setFull(!document.documentElement.classList.contains('rtm-full')),
    'rtm:redraw': () => {
      const cell = $('rtmCell').value;
      state.cell = isFace(cell) ? cell : (Number(cell) || 0);
      state.layer = Number($('rtmLayer').value) || 0;
      // An end has no layer to pick.
      $('rtmLayerWrap').hidden = !(state.compiled && state.compiled.matrix) || isFace(state.cell);
      saveState();
      drawTime();
    },
    'rtm:redrawGradient': () => {
      state.gradSpecies = $('rtmGradSpecies').value;
      state.gradLayer = Number($('rtmGradLayer').value) || 0;
      state.gradScale = $('rtmGradScale').value;
      state.gradView = $('rtmGradView').value;
      state.gradTMin = $('rtmGradTMin').value;
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
      state.profileTimes = $('rtmProfileTimes').value;
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
      state.compTimes = $('rtmCompTimes').value;
      state.compTMin = $('rtmCompTMin').value;
      saveState();
      renderComp();
      drawComp();
      infoRefresh();
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
