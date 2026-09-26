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
  const WORKER_URL = 'resources/js/rtm-worker-entry.js?v=20260923f';
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
      maxOrder: 5, minOrder: 1, hmax: '0', jacobianMode: 'analytic', kappa: '1e-3',
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
    gradTMin: '1e-6',
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
        gradSpecies: state.gradSpecies, gradScale: state.gradScale,
        gradTMin: state.gradTMin,
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
      if (Number.isFinite(s.cell)) state.cell = s.cell;
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
      if (typeof s.gradTMin === 'string') state.gradTMin = s.gradTMin;
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
    if (/^julia_/.test(method) && typeof FacsimileOdeJulia === 'undefined') {
      return `${method} is not loaded on this page. Reload it, with a hard reload if that does `
        + 'not do it.';
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
        bits.push(`dual porosity: ${m.matrix.n} matrix layer${m.matrix.n === 1 ? '' : 's'} to `
          + `${m.matrix.total} m behind each cell, porosity ${m.matrix.porosity}, `
          + `${m.matrix.aw} m² of wall per m³ of water`
          + (m.matrix.enters.length ? ` · ${m.matrix.enters.join(', ')} enter${m.matrix.enters.length === 1 ? 's' : ''} the rock` : ' · nothing enters the rock'));
      }
      const moves = [];
      if (s.DIFFUSION) moves.push('diffusion');
      if (s.ADVECTION && s.VELOCITY) moves.push(`advection at ${s.VELOCITY} m/s`);
      bits.push(moves.length ? moves.join(' + ') : 'nothing moves');
      bits.push(`${s.LEFT} | ${s.RIGHT} boundaries`);
    }
    if (m.nequilibria) {
      bits.push(`${m.nequilibria} equilibri${m.nequilibria === 1 ? 'um' : 'a'}`
        + `, ${m.nconserved} conserved total${m.nconserved === 1 ? '' : 's'}`
        + (m.speciated ? ` · initial state equilibrated (${m.speciated.iterations} iterations)` : ''));
    }
    // The unit labels follow the model: a run in years should not be asked
    // for a "from" time in seconds.
    const u = timeUnit();
    $('rtmTendUnit').textContent = `${u.name}s; blank uses TEND from the text`;
    $('rtmHmaxUnit').textContent = `${u.name}s; 0: a tenth of the run for the NDF, no limit for the ports`;
    $('rtmTMinUnit').textContent = u.symbol;
    $('rtmGradTMinUnit').textContent = u.symbol;
    if (m.nparameters) bits.push(`${m.nparameters} parameter${m.nparameters === 1 ? '' : 's'}: ${m.parameters.join(', ')}`);
    if (m.tables && m.tables.length) bits.push(`${m.tables.length} table${m.tables.length === 1 ? '' : 's'}: ${m.tables.join(', ')}`);
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
    renderFacts();
    infoRefresh();
    renderSeriesList();
    renderCells();
    renderProfileSpecies();
    renderGradSpecies();
    drawTime();
    drawProfile();
    drawGradient();
    if (partial) return;
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
    setStatus(`Done in ${(ms / 1000).toFixed(2)} s — ${(st.nsteps || 0).toLocaleString()} steps `
      + `(${(st.nfailed || 0).toLocaleString()} rejected), ${reply.n.toLocaleString()} points kept, `
      + `${st.lu === 'refactor' ? 'sparse LU keeping its pivots' : st.sparse ? 'sparse LU' : 'dense LU'}.${drift}`, drift ? 'warn' : 'ok');
  }

  function stop() {
    if (!state.running) return;
    if (worker) { worker.terminate(); worker = null; workerKind = 'none'; pending.clear(); }
    state.running = false;
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
    const n = m.states;
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
    const bits = [`${n} × ${n}, ${m.nnz} non-zeros (${(100 * m.density).toFixed(2)} % of the matrix)`,
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

  function renderSeriesList() {
    const box = $('rtmSeries');
    const names = speciesNames();
    const picked = new Set(state.picked);
    // The title is the name alone, for one too long for its cell. Which
    // species do not move is in the (i) of this tab, pane:time.
    box.innerHTML = names.map((nm) => {
      const on = picked.has(nm);
      return `<label class="rtm-item${on ? ' on' : ''}" title="${esc(nm)}">`
        + `<input type="checkbox" value="${esc(nm)}"${on ? ' checked' : ''} data-on-change="rtm:pick">`
        + `<span>${esc(nm)}</span></label>`;
    }).join('');
  }

  function renderCells() {
    const sel = $('rtmCell');
    const m = state.compiled;
    const cells = m ? m.fracture : 1;
    if (state.cell >= cells) state.cell = 0;
    sel.innerHTML = Array.from({ length: cells }, (_, i) => {
      const x = m && m.centres ? ` (${m.centres[i].toExponential(2)} m)` : '';
      return `<option value="${i}"${i === state.cell ? ' selected' : ''}>${i}${x}</option>`;
    }).join('');
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
    $('rtmLayerWrap').hidden = nm === 0;
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

  function renderProfileSpecies() {
    const sel = $('rtmProfileSpecies');
    const names = speciesNames();
    if (!names.includes(state.profileSpecies)) state.profileSpecies = names[0] || '';
    sel.innerHTML = names.map((nm) => `<option value="${esc(nm)}"`
      + `${nm === state.profileSpecies ? ' selected' : ''}>${esc(nm)}</option>`).join('');
  }

  function renderGradSpecies() {
    const sel = $('rtmGradSpecies');
    const names = speciesNames();
    if (!names.includes(state.gradSpecies)) state.gradSpecies = names[0] || '';
    sel.innerHTML = names.map((nm) => `<option value="${esc(nm)}"`
      + `${nm === state.gradSpecies ? ' selected' : ''}>${esc(nm)}</option>`).join('');
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

  /** The value of one species in one cell at every stored time. */
  function series(name, cell, layer = state.layer) {
    const r = state.result;
    const ns = r.model.nspecies;
    const si = r.model.species.indexOf(name);
    if (si < 0) return null;
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
    const logT = $('rtmLogT').checked;
    const logY = $('rtmLogY').checked;
    const tmin = Number($('rtmTMin').value) || 0;
    const traces = [];
    for (const nm of state.picked) {
      const y = series(nm, state.cell);
      if (!y) continue;
      const xs = [];
      const ys = [];
      for (let i = 0; i < r.n; i++) {
        const t = r.t[i];
        if (logT && !(t >= tmin && t > 0)) continue;
        const v = y[i];
        if (logY && !(v > 0)) continue;
        xs.push(t);
        ys.push(v);
      }
      if (xs.length) traces.push({ name: nm, x: xs, y: ys, mode: 'lines', type: 'scatter' });
    }
    const layout = baseLayout();
    layout.xaxis.type = logT ? 'log' : 'linear';
    layout.xaxis.title = { text: `time (${timeUnit().symbol})`, font: { size: 11 } };
    layout.yaxis.type = logY ? 'log' : 'linear';
    layout.yaxis.title = { text: 'concentration', font: { size: 11 } };
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
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
    const stateIndex = (k) => (across ? (atCell * stride + k) : (k * stride + layer)) * ns + si;
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
      for (let k = 0; k < npts; k++) y.push(r.states[i * r.width + stateIndex(k)]);
      return { name: fmtTime(r.t[i]), x, y, mode: across ? 'lines+markers' : 'lines', type: 'scatter' };
    });
    const layout = baseLayout();
    layout.xaxis.title = { text: across ? `depth into the rock behind cell ${atCell} (m)`
      : 'distance from the left-hand face (m)', font: { size: 11 } };
    layout.yaxis.type = $('rtmProfileLog').checked ? 'log' : 'linear';
    layout.yaxis.title = { text: `${name} concentration`, font: { size: 11 } };
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
    const logC = $('rtmGradLogC').checked;

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
        const v = r.states[cols[k] * r.width + (c * stride + gl) * ns + si];
        if (logC) {
          if (v > 0) { row[k] = Math.log10(v); } else { row[k] = null; nonPositive++; }
        } else row[k] = v;
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
    const trace = {
      type: 'heatmap',
      x: cols.map((i) => r.t[i]),
      y: Array.from(r.model.centres),
      z,
      colorscale: state.gradScale,
      reversescale: state.gradScale === 'YlOrRd',
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
        title: { text: logC ? `log₁₀ ${name}` : name, side: 'right', font: { size: 11 } },
        thickness: 14, outlinewidth: 0, tickfont: { size: 10 },
        exponentformat: 'power',
      },
    };
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
     CSV
     --------------------------------------------------------------------- */
  function downloadCsv() {
    const r = state.result;
    if (!r) { setStatus('Run the model first: there is nothing to save yet.', 'error'); return; }
    const names = state.picked.length ? state.picked : r.model.species;
    const head = [`t (${timeUnit().symbol})`, ...names.map((n) => `${n} @ cell ${state.cell}`)];
    const lines = [head.join(',')];
    const cols = names.map((n) => series(n, state.cell));
    for (let i = 0; i < r.n; i++) {
      lines.push([r.t[i], ...cols.map((c) => (c ? c[i] : ''))].join(','));
    }
    downloadBlob(new Blob([lines.join('\n')], { type: 'text/csv' }), `rtm_cell${state.cell}.csv`);
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
     the HDF5 Browser in another tab, and the same file as a download. The
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
   * Opens the HDF5 Browser and hands it this run, without a file ever reaching
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
        + '“HDF5” beside it and open the file in the HDF5 Browser yourself.', 'error');
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
      setStatus(`Sending ${name} (${(bytes.length / 1048576).toFixed(1)} MB) to the HDF5 Browser…`);
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
      if (!answer.ok) throw new Error(answer.message || 'the HDF5 Browser refused the file');
      setStatus(`${name} is open in the HDF5 Browser.`, 'ok');
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
    if (name === 'jacobian') drawJacobianPattern();
  }

  function resize() {
    if (typeof Plotly === 'undefined') return;
    ['rtmChartTime', 'rtmChartProfile', 'rtmChartGradient'].forEach((id) => {
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
    s.maxOrder = parseInt($('rtmMaxOrder').value, 10) || 5;
    s.minOrder = parseInt($('rtmMinOrder').value, 10) || 1;
    s.hmax = $('rtmHmax').value.trim();
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
    $('rtmMaxOrder').value = String(s.maxOrder ?? 5);
    $('rtmMinOrder').value = String(s.minOrder ?? 1);
    $('rtmHmax').value = s.hmax ?? '0';
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
   * Which of the settings the built-in NDF reads -- facsimile.html's list,
   * less the two that are properties of its own model language (per-species
   * tolerances and reading negatives as zero), plus the stalled correction
   * this page takes and facsimile leaves off.
   */
  const BUILTIN_OPTIONS = ['bdf', 'rtol', 'atol', 'norm', 'maxOrder', 'hmax', 'matrix', 'jacobian',
    'belowTolRun', 'maxSteps', 'stagnationTol', 'autoAtol', 'nonNegative'];

  /** Whether `method` has the BDF formulas switch: the NDF, and QNDF. */
  function readsBdf(method) {
    const julia = typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method);
    return (julia ? FacsimileOdeJulia.options(method) : BUILTIN_OPTIONS).includes('bdf');
  }

  /** What the reader should see a setting called, when told it is not used: facsimile's words. */
  const OPTION_NAMES = {
    bdf: 'the BDF switch',
    rtol: 'the relative tolerance',
    atol: 'the absolute tolerance',
    norm: 'the error norm',
    maxOrder: 'the maximum order',
    minOrder: 'the minimum order',
    hmax: 'the maximum step',
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
    let allowed = BUILTIN_OPTIONS;
    let partial = {};
    if (typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method)) {
      allowed = FacsimileOdeJulia.options(method);
      partial = FacsimileOdeJulia.notes(method) || {};
    }
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
    const julia = typeof FacsimileOdeJulia !== 'undefined';
    const ids = Array.from($('rtmMethod').options, (o) => o.value);
    const reads = (id) => (id === 'ndf'
      ? BUILTIN_OPTIONS.includes(key)
      : julia && FacsimileOdeJulia.is(id) && FacsimileOdeJulia.options(id).includes(key));
    const name = (id) => (id === 'ndf' ? 'NDF' : FacsimileOdeJulia.label(id));
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
            'With a rock matrix, `dual porosity`: `MATRIX_CELLS` layers behind each cell to `MATRIX_DEPTH`, the `MATRIX_POROSITY`, the wall area per m³ of flowing water, and the species that have a `Dm=` and so enter the rock.',
            'What moves: `diffusion`, `advection` at the `VELOCITY`, or `nothing moves`.',
            'The two ends, `LEFT | RIGHT`, with `cauchy` and `outflow` read as the `robin` and `free` they mean.',
            'Equilibria and the totals they conserve, and whether `EQUILIBRATE` put the starting state on them.',
            'Parameters and tables by name, and a species held in some cells only.',
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
        lead: 'Which integrator solves the model. NDF is the page’s own and the right first choice. The other six are ported from DifferentialEquations.jl and run here in the page, on the same analytic Jacobian; nothing is downloaded.',
        sections: [{
          choices: [
            ['NDF', 'The numerical differentiation formulas of Shampine and Reichelt, as in MATLAB’s ode15s: variable order 1 to 5, on the sparse Jacobian. With **BDF formulas** under Advanced settings it runs as the plain BDF.', cur === 'ndf'],
            ['FBDF', 'Fixed-leading-coefficient BDF, variable order. It reuses one factorisation over many steps, which on a system of hundreds of equations is most of the cost: the one to try on a large column, and first when NDF will not get through.', cur === 'julia_fbdf'],
            ['QNDF', 'The same formulas as NDF, with the same κ, written by other people: the most direct check of the built-in solver. With **BDF formulas** it is QBDF.', cur === 'julia_qndf'],
            ['KenCarp4', 'A fourth-order diagonally implicit Runge–Kutta method (ESDIRK), L-stable. A middle course, cheap at moderate tolerances.', cur === 'julia_kencarp4'],
            ['RadauIIA5', 'Fully implicit, fifth order, L-stable: the most accurate per step and the least troubled by stiffness, the one to believe when two others disagree. It factorises its complex half densely, which is slow past a few thousand equations.', cur === 'julia_radau5'],
            ['Rodas5P', 'A Rosenbrock method, fifth order, with no Newton iteration at all, so nothing to fail to converge. The one to try when a run will not get past something.', cur === 'julia_rodas5p'],
            ['TRBDF2', 'Second order, L-stable, fast at loose tolerances on smooth problems. On sharp transients at a tight tolerance it can be far out and still report success.', cur === 'julia_trbdf2'],
          ],
        }, {
          heading: 'Keep in mind',
          text: 'The Julia ports keep a species non-negative by projecting each step back and nothing more, and do not read the stall tolerance. The canister radiolysis page’s Help describes them at more length.',
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
          ['0, for NDF', tend ? `a tenth of the run, ${fmtTime(tend / 10)}` : 'a tenth of the run'],
          ['0, for the Julia ports', 'no limit but the run itself'],
          ['Allowed', '0 or more'],
          ['Read by', readers('hmax')],
        ],
        sections: [{ text: `A limit costs steps wherever the solution is smooth, and every step counts against the step budget: a maximum of a millionth of the run needs a million steps, where the default budget is ${Number(SOLVER_DEFAULTS.maxSteps).toLocaleString('en')}.` }],
      };
    },

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
          ['This model', m ? `${m.states} numbers a point, ${mb(8 * m.states * pts)} at ${pts}` : null],
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
          'The NDF damps the derivative, so that a species at zero cannot be pushed further down; counts a violation in the error test; and projects an accepted step back to zero.',
          'The Julia ports do the last of the three only.',
        ] },
        { heading: 'Keep in mind', text: 'Switch it off to see whether the model itself drives a species below zero. A negative value then points at the model, a reaction that consumes a species its rate law does not read for one, rather than at the solver.' },
      ],
    }),

    'pane:time': () => {
      const m = state.compiled;
      const still = m && m.transport ? m.species.filter((_, i) => !m.mobile[i]) : [];
      return {
        kicker: 'Tab', title: 'Against time',
        lead: 'The species ticked in the list, at one cell, at every stored point of the run.',
        sections: [
          { heading: 'The toolbar', list: [
            '**Cell**: which cell of the column, with its centre in metres from the left-hand face. A batch is one cell and has no picker.',
            '**Layer**: with a rock matrix, the fracture or a layer of rock behind the cell, by the depth of its centre.',
            '**log time**, **log concentration**: logarithmic axes. A log axis cannot show zero, so t = 0, and values at or below zero, are left off.',
            '**from**: where a log time axis starts, a plain number in the model’s time unit. A stiff run’s first steps are femtoseconds long, and without it the chart opens on fifteen empty decades. A linear axis starts at 0 whatever it says.',
            '**clear**: unticks every species.',
            '**CSV**: the species ticked, or all of them when none is, at the cell and layer shown, a row per stored point.',
            '**View in HDF5 Browser**: the whole run as an HDF5 file, opened in the HDF5 Browser in a new tab without touching the disk. The browser has to let the page open a tab.',
            '**HDF5**: the same file, as a download.',
          ] },
          { heading: 'The list', text: [
            'A ticked species is filled in the accent colour. In a column a species diffuses when it has a `D`, and with `ADVECTION` and a `VELOCITY` the flow carries every species that is not `fixed`, whatever its `D`.',
            still.length ? `In this model these do not move: ${someOf(still)}.` : '',
          ].filter(Boolean) },
        ],
        more: more('Taking the run away with you', 'help-export'),
      };
    },

    'pane:profile': () => ({
      kicker: 'Tab', title: 'Against distance',
      lead: 'One species across the column at several times, a curve for each. It needs a run in transport mode: a batch has no distance.',
      sections: [
        { heading: 'The toolbar', list: [
          '**Species**: its own choice, apart from the ticks on Against time.',
          '**Across**: with a rock matrix, along the fracture at one layer, or into the rock behind one cell, with the fracture at depth 0.',
          '**Layer**, or **At cell** into the rock: which layer the curve runs along, or which cell the rock is behind.',
          '**Times**: a list such as `0, 1 h, 30 d, 500 y`, in s, min, h, d, a or y (both years of 365.25 days); a bare number is in the model’s own unit. Empty draws eight, spread evenly over the stored points, the last at the end of the run.',
          '**log concentration**: a logarithmic axis.',
        ] },
        { heading: 'Which times are drawn', text: 'Each time asked for is drawn at the nearest stored point; nothing is interpolated. The legend names the time drawn, and the note says which moved by more than 1 %, which could not be read and which lie past the end of the run.' },
      ],
      more: more('Reading the charts', 'help-charts'),
    }),

    'pane:gradient': () => {
      const cur = $('rtmGradScale').value;
      return {
        kicker: 'Tab', title: 'Gradient',
        lead: 'The whole run in one picture: time along x, distance from the left-hand face up y, and the concentration of one species as colour, a band per cell and a column per stored point. It needs a run in transport mode.',
        sections: [
          { heading: 'The toolbar', list: [
            '**Species**, and **Layer** with a rock matrix: what is drawn, along the fracture or along one layer of rock.',
            '**log time** and **from**: as on Against time. Without a from time the first femtoseconds take most of a log axis; the note says how many points it left off.',
            '**log concentration**: colours by log₁₀ c. Values at or below zero are left blank rather than put at the bottom of the scale, and the note counts them.',
            '**smooth**: interpolates between the cells. It looks better and claims a resolution the run has not got, which is why it is off.',
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
          '**colour the syntax**: paints comments, section headings, numbers, functions and the words that mean something where they stand. Turn it off for a very large model. The choice is kept.',
        ] },
        { heading: 'Keep in mind', text: 'A reload does not bring the built-in model back: the text stays in this browser until Reset, an example or a file replaces it.' },
      ],
      more: more('The model text', 'help-model-text'),
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
    saveState();
    compile();
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
    SPECIES: new Set(['fixed']),
    INITIAL: new Set(['all', 'matrix', 'fixed']),
    PARAMETERS: new Set(['all', 'matrix', 'fracture']),
    REACTIONS: new Set(['water', 'inventory']),
  };
  /** Names that mean something where they take a value: `NAME = ...`. */
  const HL_ASSIGN = {
    SPECIES: new Set(['d', 'dm', 'left', 'right', 'mass', 'r', 'rm']),
    REACTIONS: new Set(['k', 'kf', 'kb', 'r', 'rb', 'on']),
    EQUILIBRIUM: new Set(['k', 'logk', 'kf', 'kb']),
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
        if (/^\s*\(/.test(rest) && fns[lower]) html += hlSpan('fn', word);
        else if (takesValue && section === 'SETTINGS' && settings.names.has(lower)) html += hlSpan('key', word);
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
      const sec = /^\s*<\s*([A-Za-z]+)(?:\s+[^<>]*)?>\s*$/.exec(lines[i]);
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
    showTab('model');
    scheduleCompile(0);
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'rtm:run': () => { run(); },
    'rtm:stop': () => stop(),
    'rtm:verify': () => { verify(); },
    'rtm:tab': (ev, el) => showTab(el.dataset.tab),
    'rtm:redraw': () => {
      state.cell = Number($('rtmCell').value) || 0;
      state.layer = Number($('rtmLayer').value) || 0;
      saveState();
      drawTime();
    },
    'rtm:redrawGradient': () => {
      state.gradSpecies = $('rtmGradSpecies').value;
      state.gradLayer = Number($('rtmGradLayer').value) || 0;
      state.gradScale = $('rtmGradScale').value;
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
    'rtm:pick': (ev, el) => {
      const name = el.value;
      if (el.checked) { if (!state.picked.includes(name)) state.picked.push(name); }
      else state.picked = state.picked.filter((x) => x !== name);
      el.closest('.rtm-item').classList.toggle('on', el.checked);
      saveState();
      drawTime();
    },
    'rtm:clearSeries': () => {
      state.picked = [];
      renderSeriesList();
      saveState();
      drawTime();
    },
    'rtm:downloadCsv': () => downloadCsv(),
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
  showAdvanced(!!state.sections[ADVANCED_KEY]);
  $('rtmGradScale').value = state.gradScale;
  $('rtmGradTMin').value = state.gradTMin;
  // The (i)s: "Read more in Help" shows the Help tab, and kvot-info.js then
  // scrolls it to the heading.
  if (typeof KvotInfo !== 'undefined') KvotInfo.setup({ topics: TOPICS, onMore: () => showTab('help') });
  showTab(['profile', 'gradient', 'model', 'jacobian', 'help'].includes(state.tab)
    ? state.tab : 'time');
  window.addEventListener('resize', resize);
  compile();
}());
