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
  const WORKER_URL = 'resources/js/rtm-worker-entry.js?v=20260923b';
  const DEFAULT_WIDTH = 330;

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    text: typeof RTM_DEFAULT_MODEL === 'string' ? RTM_DEFAULT_MODEL : '',
    solver: {
      method: 'ndf', tend: '', rtol: '1e-6', atol: '1e-20', matrix: 'auto', norm: 'max',
      maxSteps: '500000', maxPoints: '4000', nonNegative: true, autoAtol: false,
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
      return true;
    } catch (e) {
      state.compiled = null;
      state.compileError = e;
      renderFacts();
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
    const out = {
      method: s.method,
      rtol: num(s.rtol, 'The relative tolerance must be between 0 and 1', (x) => x > 0 && x < 1),
      atol: num(s.atol, 'The absolute tolerance must be a non-negative number', (x) => x >= 0),
      matrix: s.matrix,
      norm: s.norm,
      maxSteps: num(s.maxSteps, 'The step budget must be at least 100', (x) => x >= 100),
      maxPoints: num(s.maxPoints, 'Points kept must be at least 10', (x) => x >= 10),
      nonNegative: s.nonNegative,
      autoAtol: s.autoAtol,
    };
    if (String(s.tend).trim()) {
      out.tend = num(s.tend, `The simulated time must be a positive number of ${timeUnit().name}s`, (x) => x > 0);
    }
    return out;
  }

  async function run() {
    if (state.running) return;
    /*
      A compile is scheduled a moment after the last keystroke, and run()
      compiles anyway. Leaving the scheduled one to fire meant it landed after
      the run had finished and replaced "Done in 0.6 s ..." with "Compiled:
      ...", which reads as though nothing had been run at all.
    */
    clearTimeout(compileTimer);
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    const refusal = methodRefusal(solver.method);
    if (refusal) { setStatus(refusal, 'error'); return; }
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

  function methodLabel() {
    const chosen = $('rtmMethod').selectedOptions[0];
    return chosen ? chosen.textContent.replace(/\s*\(.*$/, '').trim() : state.solver.method;
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
    box.innerHTML = names.map((nm) => {
      const on = picked.has(nm);
      const immobile = state.compiled && state.compiled.transport && !state.compiled.mobile[names.indexOf(nm)];
      return `<label class="rtm-item${on ? ' on' : ''}" title="${esc(nm)}${immobile ? ' — does not move' : ''}">`
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
    s.tend = $('rtmTend').value.trim();
    s.rtol = $('rtmRtol').value.trim();
    s.atol = $('rtmAtol').value.trim();
    s.matrix = $('rtmMatrix').value;
    s.norm = $('rtmNorm').value;
    s.maxSteps = $('rtmMaxSteps').value.trim();
    s.maxPoints = $('rtmMaxPoints').value.trim();
    s.nonNegative = $('rtmNonNeg').checked;
    s.autoAtol = $('rtmAutoAtol').checked;
  }

  function writeSolverControls() {
    const s = state.solver;
    const menu = $('rtmMethod');
    if (!Array.prototype.some.call(menu.options, (o) => o.value === s.method)) s.method = 'ndf';
    menu.value = s.method;
    $('rtmTend').value = s.tend;
    $('rtmRtol').value = s.rtol;
    $('rtmAtol').value = s.atol;
    $('rtmMatrix').value = s.matrix;
    $('rtmNorm').value = s.norm;
    $('rtmMaxSteps').value = s.maxSteps;
    $('rtmMaxPoints').value = s.maxPoints;
    $('rtmNonNeg').checked = !!s.nonNegative;
    $('rtmAutoAtol').checked = !!s.autoAtol;
  }

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
    'rtm:solverChanged': () => { readSolverControls(); saveState(); },
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
  initSideResize();
  initSections();
  initDrop();
  showAdvanced(!!state.sections[ADVANCED_KEY]);
  $('rtmGradScale').value = state.gradScale;
  $('rtmGradTMin').value = state.gradTMin;
  showTab(['profile', 'gradient', 'model', 'jacobian', 'help'].includes(state.tab)
    ? state.tab : 'time');
  window.addEventListener('resize', resize);
  compile();
}());
