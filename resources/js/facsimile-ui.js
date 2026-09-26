/* ==========================================================================
   FACSIMILE.HTML: THE PAGE

   Settings column, tabs, charts, table, editor. The numerical work is done by
   facsimile-worker.js in a Web Worker; when a Worker cannot be created (the
   page opened from file://) the same handler runs inline.
   ========================================================================== */
/* global KVOT, Plotly, XlsxWriter, registerActions, reportFailure, notifyUser, kvotEscapeHtml, kvotCsvCell,
          kvotFormatBytes, FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS, FacsimileHDF5, handleFacsimileMessage,
          KvotInfo */
(function () {
  'use strict';

  const STORAGE_KEY = 'kvot-facsimile-v1';
  // Bump this whenever the entry's own contents change, as well as the stamps
  // on what it imports. A worker does not inherit the page's cache-busting, so
  // an entry whose imports changed while its own URL did not is served from
  // cache with the old import list, and the symptom is a solver that the page
  // offers and the worker has never heard of.
  const WORKER_URL = 'resources/js/facsimile-worker-entry.js?v=20260923f';
  const YEAR_S = 365.25 * 86400;

  const $ = (id) => document.getElementById(id);
  const esc = (v) => kvotEscapeHtml(v);

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const state = {
    text: FACSIMILE_DEFAULT_MODEL,
    presetId: '13g',
    solver: {
      method: 'ndf', bdf: false, rtol: '1e-5', atol: '1e-30', atolSpecies: '', norm: 'max',
      maxOrder: 5, minOrder: 1, hmaxYears: '0', matrix: 'auto', jacobianMode: 'analytic',
      kappa: '1e-3', maxJacAge: '20', maxSteps: '2000000', belowTolRun: '5',
      // rtm.html's two, which this page now offers too: left off, and the
      // engine's own store size.
      stagnationTol: '0', maxPoints: '20000',
      autoAtol: false, smoothEst: true, clamp: true, nonNegative: true,
    },
    syntax: true,            // colour the model text in the editor
    compiled: null,          // summary from the worker
    compileError: null,
    result: null,            // last run payload (or partial)
    ran: null,               // the model, settings and text that result came from
    running: false,
    verify: null,
    textDirty: false,
    sideWidth: null,         // px, when the reader has dragged the panel
    sections: {},            // which of the panel's sections are open
  };

  /** A cheap, stable fingerprint of a text. Not a checksum: only equality. */
  function stampOf(text) {
    const str = String(text);
    let h = 5381;
    for (let i = 0; i < str.length; i++) h = ((h * 33) ^ str.charCodeAt(i)) >>> 0;
    return `${str.length.toString(36)}-${h.toString(36)}`;
  }

  /** The <SETTINGS> lines of a text, as name -> the value as written. */
  function settingsOf(text) {
    const out = new Map();
    let inSettings = false;
    for (const raw of String(text).split('\n')) {
      const section = /^<\s*([A-Za-z][A-Za-z ]*?)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*>$/.exec(raw.trim());
      if (section) { inSettings = section[1].trim().toUpperCase() === 'SETTINGS'; continue; }
      if (!inSettings) continue;
      const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^#]*?)\s*(?:#.*)?$/.exec(raw);
      if (m) out.set(m[1], m[2].trim());
    }
    return out;
  }

  /**
   * The text with its whole <SETTINGS> section taken out.
   *
   * What is left is the model proper: the species, the reactions, the
   * equations. The panel only ever writes settings, so two texts whose
   * remainders are equal differ only in ways the panel put there -- which is
   * what makes it safe to rebuild one from the other.
   */
  function modelBody(text) {
    const kept = [];
    let inSettings = false;
    for (const raw of String(text).split('\n')) {
      const section = /^<\s*([A-Za-z][A-Za-z ]*?)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*>$/.exec(raw.trim());
      if (section) { inSettings = section[1].trim().toUpperCase() === 'SETTINGS'; }
      if (!inSettings) kept.push(raw);
    }
    return kept.join('\n');
  }

  /**
   * Bring a stored text forward to the built-in model it was based on.
   *
   * The page restores what was in the editor last time, drafts included, which
   * is right until the built-in model itself changes underneath it. Then the
   * stored copy wins for ever and nothing the reader does to the browser --
   * hard reload, cleared cache -- touches it, because it is in localStorage
   * and not the cache. A scenario that wants a setting the old text has no
   * line for then cannot be applied, which is how this is usually noticed.
   *
   * So: settings carried over onto the new text when nothing else was edited,
   * and the reader's own edits kept, with a word about it, when they were.
   */
  function migrateStoredText() {
    if (state.storedStamp === stampOf(FACSIMILE_DEFAULT_MODEL)) return;
    if (state.text === FACSIMILE_DEFAULT_MODEL) return;
    // Whether the model itself was edited. Recorded at save time against the
    // built-in model of that session, because it cannot be worked out here: a
    // stored body that differs from today's built-in one differs either
    // because the reader changed it or because the built-in did, and the two
    // look identical afterwards. A state stored before this was recorded
    // (`null`) is asked the question anyway, which errs towards keeping the
    // reader's text -- the answer that throws nothing away.
    const edited = state.storedEdited === null
      ? modelBody(state.text) !== modelBody(FACSIMILE_DEFAULT_MODEL)
      : state.storedEdited;
    if (edited) {
      state.textNote = 'Note: the built-in model has been updated since the text in the editor was '
        + 'saved, and that text is what you are looking at -- it is kept in this browser and a '
        + 'reload does not touch it. Reset, at the foot of the Model file section, takes the new '
        + 'one (and loses the text shown here, so save it first if you want it).';
      return;
    }
    let next = FACSIMILE_DEFAULT_MODEL;
    for (const [name, value] of settingsOf(state.text)) {
      const t = textWithSetting(next, name, value);
      if (t !== null) next = t;
    }
    // Reached only when the built-in model changed and the text differed from
    // it, so there is always something to say.
    state.text = next;
    state.textNote = 'The built-in model has been updated; your settings were carried over to it.';
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        text: state.text, presetId: state.presetId, solver: state.solver,
        sideWidth: state.sideWidth, sections: state.sections, syntax: state.syntax,
        // Which built-in model this text was written against. Without it a
        // stored text shadows the built-in one for ever: the page restores it
        // on every visit, so a hard reload with an empty cache changes
        // nothing, and a model that has since gained a setting cannot be
        // given one -- "the model text has no line for H2OPAIR".
        modelStamp: stampOf(FACSIMILE_DEFAULT_MODEL),
        // And whether the reader had edited the model itself, judged against
        // the built-in model of THAT session. Asking the question later, of a
        // built-in model that has since moved on, cannot tell an edit from an
        // update -- which is the whole difficulty.
        textEdited: modelBody(state.text) !== modelBody(FACSIMILE_DEFAULT_MODEL),
      }));
    } catch (e) { /* storage unavailable: nothing to do */ }
  }
  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (typeof s.text === 'string' && s.text.trim()) state.text = s.text;
      // Settings used to be kept beside the text rather than in it. A session
      // stored by that version has the reader's edits only in `overrides`, so
      // they are written into the text here instead of being dropped.
      if (s.overrides && typeof s.overrides === 'object') {
        for (const [name, value] of Object.entries(s.overrides)) {
          const next = textWithSetting(state.text, name, value);
          if (next !== null) state.text = next;
        }
      }
      state.storedStamp = typeof s.modelStamp === 'string' ? s.modelStamp : null;
      state.storedEdited = typeof s.textEdited === 'boolean' ? s.textEdited : null;
      if (typeof s.presetId === 'string') state.presetId = s.presetId;
      if (s.solver && typeof s.solver === 'object') Object.assign(state.solver, s.solver);
      if (Number.isFinite(s.sideWidth)) state.sideWidth = s.sideWidth;
      if (s.sections && typeof s.sections === 'object') state.sections = s.sections;
      if (typeof s.syntax === 'boolean') state.syntax = s.syntax;
    } catch (e) { /* a corrupt entry: start fresh */ }
  }

  /* ---------------------------------------------------------------------
     Worker (or inline fallback)
     --------------------------------------------------------------------- */
  let worker = null;
  let workerBroken = false;
  let workerKind = 'none';        // 'worker' | 'inline'
  let workerSolvers = null;       // what the worker says it can run, once asked
  const INLINE_NOTE = 'No background worker is available here, so a run holds the page '
    + 'while it lasts. Short runs are fine; the Julia ports are not offered.';
  let nextId = 1;
  const pending = new Map();   // id -> { resolve, reject, onProgress }

  /**
   * Get the work off the main thread if there is anywhere to put it.
   *
   * Running on the page itself is a last resort and a bad one: no repaint, so
   * the progress bar never moves, and no event loop, so Stop cannot be
   * clicked. A run of a second is a stutter; a Julia-port run on this model
   * can take minutes, and minutes on the main thread is a frozen tab.
   */
  function ensureWorker() {
    if (worker || workerBroken) return;
    if (typeof Worker === 'undefined') { workerBroken = true; workerKind = 'inline'; return; }
    try {
      worker = new Worker(WORKER_URL);
      workerKind = 'worker';
      worker.onmessage = (ev) => dispatch(ev.data);
      worker.onerror = (ev) => {
        reportFailure('facsimile worker', ev.message || ev);
        try { worker.terminate(); } catch (e) { /* ignore */ }
        worker = null;
        workerBroken = true;
        workerKind = 'inline';
        for (const [id, p] of pending) {
          pending.delete(id);
          p.reject(new Error('The background worker failed; the page will run inline instead'));
        }
        setStatus(INLINE_NOTE, 'error');
      };
      askCapabilities();
    } catch (e) {
      workerBroken = true;
      worker = null;
      workerKind = 'inline';
    }
  }

  /** Ask the worker what it can run, and remember the answer. */
  function askCapabilities() {
    workerSolvers = null;
    request({ type: 'capabilities' })
      .then((reply) => { workerSolvers = reply.solvers || null; })
      .catch(() => { workerSolvers = null; });
  }

  function dispatch(msg) {
    const p = pending.get(msg.id);
    if (!p) return;
    if (msg.type === 'progress') { if (p.onProgress) p.onProgress(msg); return; }
    pending.delete(msg.id);
    if (msg.type === 'error') { const err = new Error(msg.error.message); Object.assign(err, msg.error, { stage: msg.stage, trace: msg.trace, partial: msg.partial }); p.reject(err); }
    else p.resolve(msg);
  }

  function request(msg, onProgress) {
    ensureWorker();
    msg.id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(msg.id, { resolve, reject, onProgress, request: msg });
      if (worker) worker.postMessage(msg);
      else {
        // Inline: the handler replies synchronously through dispatch.
        setTimeout(() => {
          try { handleFacsimileMessage(msg, (m) => dispatch(m)); } catch (e) { pending.delete(msg.id); reject(e); }
        }, 0);
      }
    });
  }

  /**
   * Ends whatever the worker is doing, by ending the worker.
   *
   * Everything waiting on it is rejected as stopped rather than as failed:
   * some of those are compiles queued behind the run, and a compile that never
   * got its turn has nothing to say about the model.
   */
  function restartWorker() {
    if (worker) { try { worker.terminate(); } catch (e) { /* ignore */ } }
    worker = null;
    for (const [id, p] of pending) {
      pending.delete(id);
      p.reject(Object.assign(new Error('stopped'), { stopped: true }));
    }
  }

  /* ---------------------------------------------------------------------
     The settings, which live in the model text

     There is one copy of a setting and it is the line in the text. The panel
     on the left is a view of those lines: editing a field rewrites its line,
     and editing the line shows up in the field at the next compile. An earlier
     version kept the panel's values in a map beside the text, which meant the
     text said one thing and the run did another -- a setting typed over in the
     panel never reached the file you saved, and one typed into the text was
     silently ignored by the run.
     --------------------------------------------------------------------- */

  /**
   * The model text with one setting's value replaced.
   *
   * The line is found by name inside <SETTINGS> rather than by the line number
   * the compiler reported, so it still works when the text has been edited
   * since and the compile is a moment behind. Everything else on the line --
   * the name, the padding, the comment -- is left exactly as it was, and a
   * shorter value is padded so the comments stay in their column.
   *
   * @returns {string|null} the new text, or null when there is no such line
   */
  function textWithSetting(text, name, value) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(String(name))) return null;
    const lines = String(text).split('\n');
    const line = new RegExp(`^(\\s*${name}\\s*=\\s*)([^#]*?)(\\s*(?:#.*)?)$`);
    let inSettings = false;
    for (let i = 0; i < lines.length; i++) {
      const section = /^<\s*([A-Za-z][A-Za-z ]*?)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*>$/.exec(lines[i].trim());
      if (section) { inSettings = section[1].trim().toUpperCase() === 'SETTINGS'; continue; }
      if (!inSettings) continue;
      const m = line.exec(lines[i]);
      if (!m) continue;
      const current = m[2].trim();
      let next = String(value).trim();
      // Already that. Said as a number as well as a string, so that applying a
      // scenario whose 3.0E-3 the text spells 0.003 leaves the line alone
      // rather than reformatting every setting it touches.
      if (current === next) return String(text);
      const a = Number(current);
      const b = Number(next);
      if (Number.isFinite(a) && Number.isFinite(b) && a === b) return String(text);
      if (m[3].trim().startsWith('#') && next.length < m[2].length) next = next.padEnd(m[2].length);
      lines[i] = m[1] + next + m[3];
      return lines.join('\n');
    }
    return null;
  }

  /** Every setting of a preset, written into the text. */
  function textWithPreset(text, preset) {
    let out = text;
    const missing = [];
    for (const [name, value] of Object.entries(preset.settings || {})) {
      const next = textWithSetting(out, name, value);
      if (next === null) missing.push(name); else out = next;
    }
    return { text: out, missing };
  }

  /**
   * Puts new text in front of the reader without moving them.
   *
   * Assigning to a textarea's value sends the caret to the start and scrolls
   * to the top, which is a long way to be thrown when all that happened is
   * that a number changed in a panel on the other side of the page.
   */
  function setModelText(text) {
    const ta = $('facModelText');
    const { selectionStart, selectionEnd, scrollTop } = ta;
    state.text = text;
    ta.value = text;
    try { ta.setSelectionRange(selectionStart, selectionEnd); } catch (e) { /* not focused */ }
    ta.scrollTop = scrollTop;
    renderHighlight();
  }

  /**
   * Which preset these settings are, if any.
   *
   * Asked after every compile, so the scenario list answers for what the text
   * currently says however the text got that way -- typed into the panel,
   * typed into the model, or loaded from a file.
   */
  function matchingPreset(settings) {
    const byName = new Map((settings || []).map((s) => [s.name, s]));
    return FACSIMILE_PRESETS.find((p) => Object.entries(p.settings).every(([name, want]) => {
      const s = byName.get(name);
      if (!s) return false;
      // A table name or an expression is compared as it is written; a number
      // as a number, so that 1 and 1.0 are the same setting.
      if (typeof want === 'string' && !Number.isFinite(Number(want))) {
        return String(s.isTable ? s.value : s.expr).trim() === want.trim();
      }
      return Number(s.value) === Number(want);
    }));
  }

  function presetOptions() {
    const sel = $('facPreset');
    sel.innerHTML = '<option value="">— custom —</option>' + FACSIMILE_PRESETS.map((p) => `<option value="${esc(p.id)}">${esc(p.id)}</option>`).join('');
    sel.value = state.presetId || '';
    const p = FACSIMILE_PRESETS.find((x) => x.id === state.presetId);
    $('facPresetDesc').textContent = p ? p.label : 'Settings as typed below.';
    // Where the case is defined. Only the presets have one: settings typed by
    // hand are nobody's case, and claiming a citation for them would be wrong.
    const ref = $('facPresetRef');
    ref.textContent = p && p.reference ? p.reference : '';
    ref.hidden = !ref.textContent;
  }

  function renderSettings() {
    const box = $('facSettings');
    const m = state.compiled;
    if (!m) { box.innerHTML = '<p class="fac-muted">The model text does not compile; see the Model tab.</p>'; return; }
    // What the text says, always: this panel is a view of those lines. Each
    // row ends in an (i) whose topic is made from the line (caseTopic). What
    // the value works out to is in that topic, where a tooltip used to carry
    // it, and on the field as data-value, which is what the tests wait on.
    const html = m.settings.map((s) => {
      const value = s.expr;
      const label = s.comment ? s.comment : s.name;
      const id = `facSet-${s.name}`;
      const control = s.isTable
        ? `<select id="${esc(id)}" data-setting="${esc(s.name)}" data-value="${esc(String(s.value))}" data-on-change="fac:settingChanged">${m.tableNames.map((t) => `<option value="${esc(t)}"${t === value ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`
        : `<input type="text" id="${esc(id)}" data-setting="${esc(s.name)}" data-value="${esc(String(s.value))}" value="${esc(value)}" data-on-change="fac:settingChanged">`;
      return `<div class="fac-row"><label for="${esc(id)}">${esc(label)}<span class="fac-name">${esc(s.name)}</span></label>${control}`
        + `<span class="kvot-info-slot" data-info-key="${esc(`case:${s.name}`)}"></span></div>`;
    }).join('');
    // Rebuilding the panel takes the focus out of the field that was just
    // edited, which on Enter is the field the reader is still in.
    const focused = document.activeElement;
    const was = focused && focused.dataset ? focused.dataset.setting : null;
    box.innerHTML = html || '<p class="fac-muted">The model has no &lt;SETTINGS&gt; section.</p>';
    // The rows are new, and so may be the settings: the topics are registered
    // again, with one for each setting there now, and the new slots filled.
    setupInfo();
    if (was) {
      const again = box.querySelector(`[data-setting="${CSS.escape(was)}"]`);
      if (again) {
        again.focus();
        try { again.setSelectionRange(again.value.length, again.value.length); } catch (e) { /* a select */ }
      }
    }
  }

  function readSolverControls() {
    const s = state.solver;
    s.method = $('facMethod').value;
    s.bdf = $('facBdf').checked;
    s.rtol = $('facRtol').value.trim();
    s.atol = $('facAtol').value.trim();
    s.atolSpecies = $('facAtolSpecies').value;
    s.norm = $('facNorm').value;
    s.maxOrder = parseInt($('facMaxOrder').value, 10) || 5;
    s.minOrder = parseInt($('facMinOrder').value, 10) || 1;
    s.hmaxYears = $('facHmax').value.trim();
    s.matrix = $('facMatrix').value;
    s.jacobianMode = $('facJacobian').value;
    s.kappa = $('facKappa').value.trim();
    s.maxJacAge = $('facJacAge').value.trim();
    s.maxSteps = $('facMaxSteps').value.trim();
    s.belowTolRun = $('facBelowTol').value.trim();
    s.stagnationTol = $('facStagnation').value.trim();
    s.maxPoints = $('facMaxPoints').value.trim();
    s.autoAtol = $('facAutoAtol').checked;
    s.smoothEst = $('facSmoothEst').checked;
    s.clamp = $('facClamp').checked;
    s.nonNegative = $('facNonNeg').checked;
  }
  /**
   * Which of the page's solver settings the built-in NDF reads.
   *
   * Not the ones added for the ported solvers: they have no minimum order,
   * they decide for themselves how long to keep a Jacobian, their Newton
   * iteration has its own convergence test rather than a κ, and their error
   * estimate is not smoothed. Those four are genuinely not their settings,
   * rather than settings they happen to ignore.
   */
  const BUILTIN_OPTIONS = ['bdf', 'rtol', 'atol', 'atolSpecies', 'norm', 'maxOrder', 'hmax', 'matrix',
    'jacobian', 'belowTolRun', 'maxSteps', 'stagnationTol', 'autoAtol', 'clamp', 'nonNegative'];

  /** Whether `method` has the BDF formulas switch: the NDF, and QNDF. */
  function readsBdf(method) {
    const julia = typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method);
    return (julia ? FacsimileOdeJulia.options(method) : BUILTIN_OPTIONS).includes('bdf');
  }

  /** What the reader should see a setting called, when told it is not used. */
  const OPTION_NAMES = {
    bdf: 'the BDF switch',
    rtol: 'the relative tolerance',
    atol: 'the absolute tolerance',
    atolSpecies: 'per-species absolute tolerances',
    norm: 'the error norm',
    maxOrder: 'the maximum order',
    hmax: 'the maximum step',
    matrix: 'the choice of iteration matrix',
    jacobian: 'the choice of Jacobian',
    minOrder: 'the minimum order',
    kappa: 'the Newton tolerance',
    maxJacAge: 'how long a Jacobian is reused',
    maxSteps: 'the step budget',
    belowTolRun: 'accepting failing steps at the floor',
    stagnationTol: 'the stall tolerance',
    autoAtol: 'letting the absolute tolerance follow the solution',
    smoothEst: 'smoothing the error estimate',
    clamp: 'reading negatives as zero',
    nonNegative: 'keeping species non-negative',
  };

  /**
   * Show only the settings the chosen method actually reads.
   *
   * Each family declares its own set next to the code that passes the settings
   * on, which is the only place the answer can be kept honest. A knob that
   * does nothing is worse than a missing one, because nothing tells the reader
   * which it is -- so the ones that are hidden are also named underneath,
   * rather than simply vanishing.
   */
  function updateSolverOptions() {
    const method = $('facMethod').value;
    let allowed = BUILTIN_OPTIONS;
    let partial = {};
    if (typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method)) {
      allowed = FacsimileOdeJulia.options(method);
      partial = FacsimileOdeJulia.notes(method) || {};
    }
    const set = new Set(allowed);
    const dropped = [];
    document.querySelectorAll('[data-solver-opt]').forEach((el) => {
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
    // A setting that is read, but not in the way the same checkbox means for
    // the built-in solvers. Saying so is the point: the alternative is one
    // tick box that quietly means two different things.
    for (const key of Object.keys(partial)) {
      if (set.has(key)) lines.push(`${label} honours ${OPTION_NAMES[key]} ${partial[key]}.`);
    }
    // A complaint about what is in the per-species box goes first: it is the
    // one thing here that stops a run, so it should not be read last.
    const complaint = checkAtolSpecies();
    if (complaint) lines.unshift(complaint);
    const note = $('facSolverNote');
    if (!lines.length) { note.hidden = true; note.textContent = ''; return; }
    note.hidden = false;
    note.textContent = lines.join(' ');
  }

  /**
   * What to call the chosen method in prose: the menu's own text, without the
   * parenthetical that says where it came from. The option values are short
   * ids ('ndf', 'julia_fbdf') and reading one back to the reader mid-run is
   * not what they chose from. With the BDF formulas switch on it is the
   * method that runs: NDF as BDF, QNDF as QBDF.
   */
  function methodLabel() {
    const chosen = $('facMethod').selectedOptions[0];
    const name = chosen
      ? chosen.textContent.replace(/\s*[↓(].*$/, '').trim()
      : $('facMethod').value;
    return $('facBdf').checked && readsBdf($('facMethod').value) ? name.replace(/NDF$/, 'BDF') : name;
  }

  /** "a", "a and b", "a, b and c" -- or "a, b or c" when asked. */
  function listOf(items, conjunction = 'and') {
    if (items.length === 1) return items[0];
    return `${items.slice(0, -1).join(', ')} ${conjunction} ${items[items.length - 1]}`;
  }

  function writeSolverControls() {
    const s = state.solver;
    // A visit from before ode23s and SciPy's were taken off the menu has one
    // of them stored, and one from before the built-in solver was named for
    // its formulas has 'ode15s'. Assigning a value no option carries leaves
    // the select blank and the run then asks for a solver that is not there,
    // so anything unknown is put back on the NDF here -- and in state, or the
    // next save would store it again.
    const menu = $('facMethod');
    if (s.method === 'ode15s') s.method = 'ndf';
    // BDF and QBDF were entries of their own, and are now the BDF formulas
    // switch on the NDF and on QNDF: a visit that had one chosen gets that
    // method with the switch on, which is the same run.
    if (s.method === 'bdf') { s.method = 'ndf'; s.bdf = true; }
    if (s.method === 'julia_qbdf') { s.method = 'julia_qndf'; s.bdf = true; }
    if (!Array.prototype.some.call(menu.options, (o) => o.value === s.method)) s.method = 'ndf';
    menu.value = s.method;
    $('facBdf').checked = !!s.bdf;
    $('facRtol').value = s.rtol;
    $('facAtol').value = s.atol;
    $('facAtolSpecies').value = s.atolSpecies || '';
    $('facNorm').value = s.norm;
    $('facMaxOrder').value = String(s.maxOrder);
    $('facMinOrder').value = String(s.minOrder ?? 1);
    $('facHmax').value = s.hmaxYears;
    $('facMatrix').value = s.matrix;
    $('facJacobian').value = s.jacobianMode;
    $('facKappa').value = s.kappa ?? '1e-3';
    $('facJacAge').value = s.maxJacAge ?? '20';
    $('facMaxSteps').value = s.maxSteps ?? '2000000';
    $('facBelowTol').value = s.belowTolRun ?? '5';
    $('facStagnation').value = s.stagnationTol ?? '0';
    $('facMaxPoints').value = s.maxPoints ?? '20000';
    $('facAutoAtol').checked = !!s.autoAtol;
    $('facSmoothEst').checked = s.smoothEst !== false;
    $('facClamp').checked = !!s.clamp;
    $('facNonNeg').checked = !!s.nonNegative;
    updateSolverOptions();
    refreshInfo();
  }

  function setStatus(text, tone) {
    const el = $('facStatus');
    el.textContent = text;
    el.className = 'fac-status' + (tone === 'error' ? ' error' : tone === 'ok' ? ' ok' : '');
  }
  /**
   * The progress bar: how far, and whether anything is happening.
   *
   * `null` puts it away. Any other value shows it, moving the stripes -- the
   * fill alone is not enough, because a stiff case spends its first seconds
   * at a fraction that rounds to zero.
   */
  /**
   * The bar, as the share of the simulated time already solved.
   *
   * Never narrower than a sliver while a run is going on. The fill carries the
   * moving stripes that say the run is alive, and a run that is a thousandth
   * of one per cent through -- which is where a solver that is struggling
   * spends its time, and exactly when the reader most wants to know something
   * is still happening -- rounds to a width of zero and has nothing to animate.
   * An empty bar beside a running solver reads as a hung page.
   */
  const PROGRESS_MIN = 1.5;

  function setProgress(frac) {
    const bar = $('facProgress');
    if (frac == null) { bar.hidden = true; bar.classList.remove('working'); return; }
    bar.hidden = false;
    bar.classList.add('working');
    const pct = Math.max(PROGRESS_MIN, Math.min(100, 100 * frac));
    bar.firstElementChild.style.width = `${pct.toFixed(1)}%`;
  }

  /* ---------------------------------------------------------------------
     The panel itself: how wide it is, and which of it is open
     --------------------------------------------------------------------- */

  /** Between these the settings still fit and the charts still have a page. */
  const SIDE_MIN = 260;
  const SIDE_DEFAULT = 340;
  const sideMax = () => Math.max(SIDE_MIN, document.querySelector('.fac').getBoundingClientRect().width * 0.6);

  function applySideWidth(px) {
    const grid = document.querySelector('.fac');
    if (px == null) grid.style.removeProperty('--fac-side-width');
    else grid.style.setProperty('--fac-side-width', `${Math.round(px)}px`);
  }

  /**
   * Charts do not notice that their container changed width; they notice the
   * window changing. Plotly's `responsive` option listens for that, so the
   * drag ends by saying it happened -- which is what rb.html does too -- and
   * the charts on a tab that was hidden at the time are measured again when it
   * comes back.
   */
  function resizeCharts() {
    if (typeof Plotly === 'undefined') return;
    for (const id of ['chart1', 'chart2', 'chart3', 'chart4']) {
      const el = $(id);
      if (!el || !el.classList.contains('js-plotly-plot') || el.hidden) continue;
      // A chart on a tab that is not the one on screen has no width to be
      // measured against; it is measured when that tab comes back.
      if (!(el.getBoundingClientRect().width > 0)) continue;
      try { Plotly.Plots.resize(el); } catch (e) { /* not laid out yet */ }
    }
  }

  function initSideResize() {
    const handle = $('facResize');
    const side = $('facSide');
    let startX = 0;
    let startWidth = 0;

    const onMove = (ev) => {
      ev.preventDefault();
      const wanted = startWidth + (ev.clientX - startX);
      state.sideWidth = Math.max(SIDE_MIN, Math.min(wanted, sideMax()));
      applySideWidth(state.sideWidth);
    };
    const onUp = () => {
      handle.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      saveState();
      window.dispatchEvent(new Event('resize'));
      resizeCharts();
    };
    handle.addEventListener('mousedown', (ev) => {
      ev.preventDefault();
      startX = ev.clientX;
      startWidth = side.getBoundingClientRect().width;
      handle.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    handle.addEventListener('dblclick', () => {
      state.sideWidth = null;
      applySideWidth(null);
      saveState();
      window.dispatchEvent(new Event('resize'));
      resizeCharts();
    });
    if (state.sideWidth) applySideWidth(state.sideWidth);
  }

  /**
   * The sections of the panel, open or closed as they were left.
   *
   * Wired here rather than through the site's action dispatcher because
   * `toggle` is one of the events that does not bubble, so a delegated
   * listener on the document never sees it.
   */
  /**
   * The advanced half of the Solver panel, folded away by default.
   *
   * Method, rtol and atol are what a reader changes; the other fifteen are
   * there for when one of them is not enough, and arriving as a wall of them
   * makes the panel look harder than it is. Remembered between visits in the
   * same map as the <details> sections, under a key no section can take.
   *
   * The container is what carries `hidden`, not the rows: updateSolverOptions
   * owns each row's `hidden` -- it is how a setting the chosen method does not
   * read is taken away -- so sharing the attribute would have the two
   * overwrite each other on every redraw.
   */
  const ADVANCED_KEY = 'sec-solver-advanced';

  function showSolverAdvanced(open) {
    const box = $('facSolverAdvanced');
    const btn = $('facSolverMore');
    if (!box || !btn) return;
    box.hidden = !open;
    btn.textContent = open ? 'Hide advanced settings' : 'Advanced settings';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function initSolverAdvanced() {
    showSolverAdvanced(!!state.sections[ADVANCED_KEY]);
  }

  function toggleSolverAdvanced() {
    const open = !state.sections[ADVANCED_KEY];
    state.sections[ADVANCED_KEY] = open;
    showSolverAdvanced(open);
    saveState();
  }

  function initSections() {
    document.querySelectorAll('details.fac-sec').forEach((sec) => {
      if (Object.prototype.hasOwnProperty.call(state.sections, sec.id)) sec.open = !!state.sections[sec.id];
      sec.addEventListener('toggle', () => {
        state.sections[sec.id] = sec.open;
        saveState();
      });
    });
  }

  /* ---------------------------------------------------------------------
     Compile
     --------------------------------------------------------------------- */
  let compileTimer = null;
  let compileWanted = false;
  /**
   * Compiles once the typing stops.
   *
   * While a run is going the worker is busy with it -- it has one thread, and
   * a message sent now would sit in its queue until the run ended, or be
   * thrown away with it when the reader pressed Stop. So the wish is held and
   * granted when the run is over, and so is one that comes due after a run
   * has begun.
   */
  function scheduleCompile(delay = 400) {
    if (state.running) { compileWanted = true; return; }
    clearTimeout(compileTimer);
    compileTimer = setTimeout(() => {
      if (state.running) { compileWanted = true; return; }
      compile().catch((e) => reportFailure('compile', e));
    }, delay);
  }

  /** Whether a tab's pane is the one on screen. */
  const paneVisible = (name) => !$(`pane-${name}`).hidden;

  /**
   * Compiles the model text.
   *
   * `reveal` is what separates a compile the reader asked for -- Apply, Run,
   * Check Jacobian, opening a file -- from the one that follows their typing.
   * Only the first may move the caret to the line at fault. See `markLine`.
   */
  async function compile({ reveal = false } = {}) {
    saveState();
    // Read before the attempt, and reported whichever way it goes: a text kept
    // from an older built-in model often does not compile against the new one,
    // and that is precisely when the reader needs to hear that the text is a
    // stored one rather than being left with "X is not defined".
    const note = state.textNote ? ` ${state.textNote}` : '';
    state.textNote = null;
    try {
      const reply = await request({ type: 'compile', text: state.text, clampNegative: state.solver.clamp });
      state.compiled = reply.model;
      state.compileError = null;
      // The scenario the text now describes, whoever changed it.
      const preset = matchingPreset(reply.model.settings);
      state.presetId = preset ? preset.id : '';
      presetOptions();
      renderSettings();
      renderModelInfo();
      // Whether the model asks for output times is a property of the text,
      // so the row control answers for the text as it now stands rather than
      // waiting for the next run to redraw the table.
      syncRowsControls();
      // The Jacobian canvas and the generated code are worth a few hundred
      // kilobytes of work each; while the reader is typing in the editor both
      // panes are hidden, and switching to one redraws it anyway.
      if (paneVisible('jacobian')) drawJacobian();
      if (paneVisible('code')) showCode();
      if (!state.running) setStatus(`Model compiled: ${reply.model.nspecies} species, ${reply.model.nreactions} reactions, Jacobian with ${reply.model.nnz} non-zeros (${(100 * reply.model.density).toFixed(1)} % of the matrix). Ready to run.${note}`, 'ok');
      return true;
    } catch (e) {
      // Stopped on the way, not refused: the model text is whatever it was.
      if (e.stopped) return false;
      state.compileError = e;
      renderModelInfo();
      if (!state.running) {
        if (editingErrorLine()) setStatus(`Line ${e.line} is not finished yet.`, 'info');
        else setStatus(`The model text does not compile: ${e.message}${note}`, 'error');
      }
      if (reveal && e.line) markLine(e.line);
      return false;
    }
  }

  /** The 1-based line the caret sits on. */
  function caretLine(ta) {
    return ta.value.slice(0, ta.selectionStart).split('\n').length;
  }

  /**
   * Whether the caret is on the line the compiler is objecting to -- that is,
   * whether the reader is in the middle of writing the line it is about.
   * A half-typed line is not a mistake, and is not reported as one.
   */
  function editingErrorLine() {
    const e = state.compileError;
    const ta = $('facModelText');
    return !!(e && e.line && document.activeElement === ta && caretLine(ta) === e.line);
  }

  function renderModelInfo() {
    const el = $('facModelInfo');
    const ta = $('facModelText');
    const e = state.compileError;
    if (e) {
      const editing = editingErrorLine();
      // The red border, like the wording, waits until the line is left alone.
      ta.classList.toggle('error', !editing);
      el.innerHTML = editing
        ? `<span class="fac-muted">Line ${e.line} is not finished yet — ${esc(e.message.replace(/^Line \d+: /, ''))}</span>`
        : `<span class="err">${esc(e.message)}</span>`
          + (e.line ? ` <button type="button" class="fac-btn secondary small" data-on-click="fac:gotoError">go to line ${e.line}</button>` : '');
      return;
    }
    ta.classList.remove('error');
    const m = state.compiled;
    if (!m) { el.textContent = ''; return; }
    const warn = m.warnings.length ? `<br>Notes: ${esc(m.warnings.join('; '))}` : '';
    const extra = `${(m.rateNames || []).length ? `, ${m.rateNames.length} named reaction rate${m.rateNames.length === 1 ? '' : 's'}` : ''}`
      + `${m.nalgebraic ? `, ${m.nalgebraic} algebraic variable${m.nalgebraic === 1 ? '' : 's'}` : ''}`
      + `${(m.outputTimes || []).length ? `, ${m.outputTimes.length} output times` : ''}`;
    el.innerHTML = `${m.nspecies} species, ${m.nreactions} reactions, ${m.equations.length} equations, ${m.outputs.length} outputs, ${m.events.length} event${m.events.length === 1 ? '' : 's'}${extra}. `
      + `Jacobian: ${m.nnz} structurally non-zero entries of ${m.nspecies * m.nspecies} (${(100 * m.density).toFixed(1)} %), ${m.colours} column groups.${warn}`;
  }

  /* ---------------------------------------------------------------------
     Syntax colouring for the model editor

     A textarea cannot colour its own text, so the coloured copy is a <pre>
     underneath it and the textarea's own text is made transparent over it.
     That keeps native editing whole -- undo, spell-check off, selection,
     the caret, middle-click paste -- which a contenteditable div would not,
     and it is why the two boxes must agree on every metric that decides
     where a character lands: font, size, line height, padding, border and
     tab size are set together in facsimile.css.
     --------------------------------------------------------------------- */

  /** Words that mean something in a particular section. */
  const HL_KEYWORDS = {
    REACTIONS: new Set(['kf', 'kb', 'keq', 'rf', 'rb', 'rate']),
    EVENTS: new Set(['up', 'down', 'both', 'stop']),
    TIMES: new Set(['log', 'lin']),
  };
  const HL_TOKEN = /(\s+)|((?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|([=%:@])|([\s\S])/g;
  const hlSpan = (cls, text) => `<span class="hl-${cls}">${esc(text)}</span>`;

  /** One line of the model text as HTML, given the section it is in. */
  function highlightLine(raw, section) {
    if (!raw) return '';
    const trimmed = raw.trim();
    if (trimmed.startsWith('*')) return hlSpan('com', raw);          // FACSIMILE comment line
    if (/^\s*<[^<>]*>\s*$/.test(raw)) return hlSpan('sec', raw);
    // The comment is whatever follows the first of #, !! and ; -- the same
    // three the compiler strips, so what is greyed out is what is ignored.
    let cut = -1;
    for (const mark of ['#', '!!', ';']) {
      const at = raw.indexOf(mark);
      if (at >= 0 && (cut < 0 || at < cut)) cut = at;
    }
    const code = cut < 0 ? raw : raw.slice(0, cut);
    const comment = cut < 0 ? '' : raw.slice(cut);
    const keywords = HL_KEYWORDS[section] || null;
    const fns = typeof FacsimileModel !== 'undefined' ? FacsimileModel.FUNCTIONS : {};
    let html = '';
    HL_TOKEN.lastIndex = 0;
    let m;
    while ((m = HL_TOKEN.exec(code)) !== null) {
      if (m[1] !== undefined) { html += esc(m[1]); continue; }
      if (m[2] !== undefined) { html += hlSpan('num', m[2]); continue; }
      if (m[3] !== undefined) {
        const word = m[3];
        const lower = word.toLowerCase();
        const rest = code.slice(HL_TOKEN.lastIndex);
        if (/^\s*\(/.test(rest) && fns[lower]) html += hlSpan('fn', word);
        else if (keywords && keywords.has(lower)) html += hlSpan('key', word);
        else html += esc(word);
        continue;
      }
      if (m[4] !== undefined) { html += hlSpan('op', m[4]); continue; }
      html += esc(m[5]);
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
      const sec = /^\s*<\s*([A-Za-z][A-Za-z ]*?)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*>\s*$/.exec(lines[i]);
      if (sec) section = sec[1].trim().toUpperCase().replace(/\s+/g, ' ');
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
    const pre = $('facHighlight');
    const ta = $('facModelText');
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

  /** Turns the colouring on or off, and remembers which. */
  function applySyntaxMode() {
    const box = $('facCodeBox');
    const check = $('facSyntax');
    if (check) check.checked = !!state.syntax;
    if (box) box.classList.toggle('hl', !!state.syntax);
    renderHighlight();
  }

  /**
   * Puts the caret at the start of a line and scrolls it into view.
   *
   * A caret, deliberately, and never a selection: this is a textarea, and a
   * selected line is replaced wholesale by the next character typed. The first
   * version of this page selected the line at fault after every automatic
   * compile, so writing a new line at the end of the file selected what had
   * just been typed and the next keystroke wiped it. Nothing calls this now
   * except an action the reader took.
   */
  function markLine(line) {
    const ta = $('facModelText');
    const lines = ta.value.split('\n');
    let pos = 0;
    for (let i = 0; i < line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    try {
      ta.focus();
      ta.setSelectionRange(pos, pos);
      // Scroll the line into view: approximate by line height.
      const lh = parseFloat(getComputedStyle(ta).lineHeight) || 17;
      ta.scrollTop = Math.max(0, (line - 6) * lh);
    } catch (e) { /* selection unsupported */ }
  }

  /* ---------------------------------------------------------------------
     Run
     --------------------------------------------------------------------- */
  function solverPayload() {
    readSolverControls();
    const s = state.solver;
    const rtol = Number(s.rtol), atol = Number(s.atol);
    if (!(rtol > 0 && rtol < 1)) throw new Error('The relative tolerance must be a number between 0 and 1');
    if (!(atol >= 0)) throw new Error('The absolute tolerance must be a non-negative number');
    // Parsed here and sent as names, not as an array of 63 numbers: the worker
    // recompiles before it runs and resolves them against that compilation, so
    // a species list edited since the last compile cannot silently shift which
    // species a tolerance lands on.
    const { values: atolSpecies, errors } = FacsimileODE.parseSpeciesTolerances(s.atolSpecies);
    if (errors.length) throw new Error(`Per-species absolute tolerance: ${errors[0]}`);
    const unknown = unknownSpecies(atolSpecies);
    if (unknown.length) {
      throw new Error(`Per-species absolute tolerance: this model has no species called ${
        unknown.map((u) => `"${u}"`).join(', ')}`);
    }
    const hmaxYears = Number(s.hmaxYears || 0);
    if (!(hmaxYears >= 0)) throw new Error('The maximum step must be a non-negative number of years');
    const tendSetting = state.compiled && state.compiled.settings.find((x) => x.name === 'TEND');
    const tendYears = tendSetting ? Number(tendSetting.value) : 500;
    if (!(tendYears > 0)) throw new Error('TEND (the simulated time in years) must be positive');
    const kappa = Number(s.kappa);
    if (!(kappa > 0 && kappa < 1)) throw new Error('The Newton tolerance must be a number between 0 and 1');
    const maxJacAge = Math.round(Number(s.maxJacAge));
    if (!(maxJacAge >= 1)) throw new Error('A Jacobian must be reused for at least one step');
    const maxSteps = Math.round(Number(s.maxSteps));
    if (!(maxSteps >= 100)) throw new Error('The step budget must be at least 100');
    const belowTolRun = Math.round(Number(s.belowTolRun));
    if (!(belowTolRun >= 0)) {
      throw new Error('Accepting failing steps must be a count of zero or more');
    }
    const stagnationTol = Number(s.stagnationTol ?? 0);
    if (!(stagnationTol >= 0 && stagnationTol <= 1)) throw new Error('The stall tolerance must be a number from 0 to 1');
    const maxPoints = Math.round(Number(s.maxPoints ?? 20000));
    if (!(maxPoints >= 1000)) throw new Error('Points kept must be at least 1000');
    const minOrder = Math.min(s.minOrder, s.maxOrder);
    return {
      method: s.method, bdf: !!s.bdf, rtol, atol, atolSpecies, norm: s.norm, maxOrder: s.maxOrder, minOrder,
      hmaxSeconds: hmaxYears > 0 ? hmaxYears * YEAR_S : 0, matrix: s.matrix, jacobianMode: s.jacobianMode,
      kappa, maxJacAge, maxSteps, belowTolRun, stagnationTol, maxPoints,
      autoAtol: s.autoAtol, smoothEst: s.smoothEst, nonNegative: s.nonNegative, tendYears,
    };
  }

  /**
   * Read the per-species box, redden it if it cannot be used, and say why.
   *
   * Only the first complaint is reported. A list of them, rewritten on every
   * keystroke, is noise -- and fixing the first usually fixes the rest.
   *
   * @returns {string} the complaint, or '' when the box is usable
   */
  function checkAtolSpecies() {
    const box = $('facAtolSpecies');
    const { values, errors } = FacsimileODE.parseSpeciesTolerances(box.value);
    const unknown = errors.length ? [] : unknownSpecies(values);
    const complaint = errors.length
      ? `Per-species absolute tolerance, ${errors[0]}.`
      : (unknown.length
        ? `Per-species absolute tolerance: this model has no species called ${
          unknown.map((u) => `"${u}"`).join(', ')}.`
        : '');
    box.classList.toggle('bad', !!complaint);
    return complaint;
  }

  /**
   * Which of `overrides`' names are not species of the model last compiled.
   *
   * Advisory only -- the run recompiles and checks again, which is the check
   * that counts. This one is so that a typo is caught while it is being typed
   * rather than after a click.
   */
  function unknownSpecies(overrides) {
    const known = state.compiled && state.compiled.species;
    if (!known) return [];
    const set = new Set(known.map((x) => String(x).toUpperCase()));
    return Object.keys(overrides).filter((name) => !set.has(name.toUpperCase()));
  }

  /**
   * Whether this solver can be run here, and if not, why not.
   *
   * The Julia ports need a worker: on this model they can run for minutes, and
   * minutes on the main thread is a frozen tab with a Stop button nobody can
   * click. The built-in NDF is quick enough to run inline when there is no worker.
   */
  function methodRefusal(method) {
    // A model with algebraic variables is a differential-algebraic system.
    // Only the built-in NDF takes a mass matrix; the ported solvers would
    // integrate the constraint residuals as if they were rates of change,
    // which is a wrong answer rather than a slow one. Said before the run
    // rather than thrown part-way through it.
    const m = state.compiled;
    if (m && m.nalgebraic && method !== 'ndf') {
      return `This model has ${m.nalgebraic} algebraic variable${m.nalgebraic === 1 ? '' : 's'} `
        + `(${(m.algebraicNames || []).join(', ')}), which makes it a differential-algebraic `
        + 'system. The ported solvers do not take a mass matrix. Use NDF, with its BDF '
        + 'formulas or without.';
    }
    ensureWorker();
    // Where the run would happen first, because that explains the refusal
    // usefully; the stale-copy message is the fallback for a worker that is
    // missing something for a reason the placement does not account for.
    if (typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method)
      && workerKind !== 'worker') {
      return `${FacsimileOdeJulia.label(method)} can run for minutes on this model, and `
        + `there is nowhere to run it but the page itself. ${INLINE_NOTE} Use NDF.`;
    }
    if (worker && workerSolvers && !workerSolvers.includes(method)) {
      return `The background worker does not have ${method}. That usually means the browser `
        + 'is holding an older copy of it; reload the page, with a hard reload if that does '
        + 'not do it.';
    }
    return null;
  }

  async function run() {
    if (state.running) return;
    let solver;
    try { solver = solverPayload(); } catch (e) { setStatus(e.message, 'error'); return; }
    const refusal = methodRefusal(solver.method);
    if (refusal) { setStatus(refusal, 'error'); return; }
    // The run compiles the text itself, so a compile still waiting on its
    // timer -- a setting changed a moment ago -- has nothing left to do. Left
    // to fire, it queued behind the run in the worker and its "Model
    // compiled" replaced the run's "Done".
    clearTimeout(compileTimer);
    if (!(await compile({ reveal: true }))) return;
    // The text as it was run. It can be edited while the run is going, or
    // replaced by opening a file, and what is recorded about this run --
    // the model the HDF5 file carries -- has to be the text that produced it.
    const text = state.text;
    state.running = true;
    $('facRun').disabled = true;
    // The worker is about to be busy for as long as this takes; a Jacobian
    // check sent now would only queue behind it.
    $('facVerify').disabled = true;
    $('facStop').disabled = false;
    $('facStats').textContent = 'Running…';
    setProgress(0);
    setStatus(`Running ${methodLabel()}…`);
    const started = Date.now();
    try {
      const reply = await request(
        { type: 'run', text, clampNegative: state.solver.clamp, solver },
        (p) => {
          setProgress(p.frac);
          // What it has solved, of what was asked, and what that has cost so
          // far. A reader watching 13 of 500 years go by in a minute knows
          // what to do about it; a bar on its own does not tell them.
          const years = p.t / YEAR_S;
          setStatus(`Running ${methodLabel()}: ${years < 1 ? fmtTime(p.t) : `${years.toPrecision(3)} years`}`
            + ` of ${solver.tendYears}, ${p.nsteps.toLocaleString()} steps, ${p.seconds.toFixed(0)} s`);
        },
      );
      state.result = reply;
      // What this result came out of, kept beside it. The text and the settings
      // can be edited straight afterwards, and a file describing the run has to
      // describe the run that happened rather than the page as it now stands.
      state.ran = { model: state.compiled, solver, text, scenario: state.presetId || 'custom' };
      const st = reply.stats;
      setStatus(st.stoppedBy
        ? `Done in ${reply.seconds.toFixed(2)} s: the event “${st.stoppedBy.expr}” stopped the run at ${fmtTime(st.stoppedBy.t)}.`
        : `Done in ${reply.seconds.toFixed(2)} s.`, 'ok');
      $('facStats').innerHTML = statsHtml(st, reply.events);
      afterResult();
    } catch (e) {
      if (e.message === 'stopped') {
        setStatus('Stopped.', 'info');
        // The footer was set to "Running…" when the run began, and nothing
        // else writes it on this path: left alone it says a run is going on
        // long after it stopped, which is how the last one read.
        $('facStats').innerHTML = `<b>${esc(solver.method)}</b>: stopped before it finished.`;
      } else {
        setStatus(`${e.stage === 'compile' ? 'The model text does not compile: ' : 'The run failed: '}${e.message}`, 'error');
        const trace = e.trace && e.trace.length
          ? '<br>Last accepted steps before the failure (t in s, step h in s, order k, error/rtol):<br>'
            + e.trace.map((st) => `t=${st.t.toExponential(6)} h=${st.h.toExponential(2)} k=${st.k ?? '-'} err=${(st.err / solver.rtol).toExponential(1)}`).join('<br>')
          : '';
        if (e.partial) {
          state.result = { ...e.partial, stats: null, partialFailure: e.message, seconds: (Date.now() - started) / 1000 };
          state.ran = { model: state.compiled, solver, text, scenario: state.presetId || 'custom' };
          afterResult();
          const reached = e.partial.t && e.partial.n ? e.partial.t[e.partial.n - 1] : null;
          $('facStats').innerHTML = `<b>${esc(solver.method)}</b>: the run did not finish. `
            + `${(e.partial.n || 0).toLocaleString()} points kept`
            + (reached == null ? '' : `, up to t = ${fmtTime(reached)} of ${fmtTime(solver.tendYears * YEAR_S)}`)
            + `.<br>${esc(e.message)}${trace}`;
          notifyUser('The run failed part-way; the charts and the table show what was integrated before the failure.');
        } else {
          $('facStats').innerHTML = `<b>${esc(solver.method)}</b>: the run did not finish, and there is nothing to show.`
            + `<br>${esc(e.message)}${trace}`;
        }
      }
    } finally {
      state.running = false;
      $('facRun').disabled = false;
      $('facVerify').disabled = false;
      $('facStop').disabled = true;
      setProgress(null);
      if (compileWanted) { compileWanted = false; scheduleCompile(50); }
    }
  }

  function statsHtml(st, events) {
    const evs = (events || []).map((ev) => `event at t = ${fmtTime(ev.t)}: ${
      ev.stop ? `<b>the run stopped here</b>${ev.changed.length ? ` (${esc(ev.changed.join(', '))})` : ''}`
        : esc(ev.changed.join(', '))}`).join('<br>');
    // Said when it happened, because the table and the file then hold fewer
    // rows than the solver took steps, and that should not be a surprise.
    const kept = st.stride > 1
      ? ` <b>${st.points.toLocaleString()} points kept</b>, one in ${st.stride}`
      : ` ${st.points ? st.points.toLocaleString() : ''} points`;
    return `<b>${st.solver}</b>: ${st.nsteps.toLocaleString()} steps (${st.nfailed.toLocaleString()} rejected),`
      + `${kept}, ${st.nfevals.toLocaleString()} evaluations of f, ${st.npds} Jacobians, ${st.ndecomps} LU factorisations, ${st.nsolves.toLocaleString()} solves`
      + (st.nbelowtol ? `, <b>${st.nbelowtol} step${st.nbelowtol === 1 ? '' : 's'} accepted below tolerance</b>` : '')
      + (st.restarts ? `, <b>rebuilt ${st.restarts} time${st.restarts === 1 ? '' : 's'}</b> where the step size stalled` : '')
      + (st.negative ? `, ${st.negative} projections onto zero` : '')
      + `.<br>Iteration matrix I − hJ: <b>${st.lu === 'refactor' ? 'sparse LU keeping its pivots' : st.sparse ? 'sparse LU' : 'dense LU'}</b>`
      + (st.lu === 'refactor'
        ? ` (${st.fill} entries against ${st.n * st.n} dense, ${st.ordering} order; the pivots were chosen again ${st.repivots} time${st.repivots === 1 ? '' : 's'}${st.fallbacks ? `, and ${st.fallbacks} factorisation${st.fallbacks === 1 ? '' : 's'} went to the dense LU` : ''})`
        : st.fill != null ? ` (the sparse factor has ${st.fill} entries against ${st.n * st.n} dense, ${st.ordering} ordering)` : '')
      + `; Jacobian ${st.nnz} non-zeros of ${st.n}×${st.n}.`
      + (st.consistentStart && st.consistentStart.moved > 1e-12
        ? `<br>Algebraic start: the constraints were solved in ${st.consistentStart.iterations} iteration${
          st.consistentStart.iterations === 1 ? '' : 's'}, moving the algebraic variables by up to ${
          (100 * st.consistentStart.moved).toPrecision(3)} %.` : '')
      + (state.result && state.result.grid && state.result.grid.n
        ? `<br>Output grid: ${state.result.grid.n.toLocaleString()} of the ${
          (state.result.gridWanted || state.result.grid.n).toLocaleString()} times the model asks for.` : '')
      + (evs ? `<br>${evs}` : '');
  }

  function stop() {
    if (!state.running) return;
    restartWorker();
    state.running = false;
    $('facRun').disabled = false;
    $('facVerify').disabled = false;
    $('facStop').disabled = true;
    setProgress(null);
    setStatus('Stopped.', 'info');
  }

  function fmtTime(tSeconds) {
    if (tSeconds < 3600) return `${tSeconds.toPrecision(3)} s`;
    if (tSeconds < 30 * 86400) return `${(tSeconds / 3600).toPrecision(4)} h`;
    return `${(tSeconds / YEAR_S).toPrecision(4)} years`;
  }

  /* ---------------------------------------------------------------------
     Results: accessors
     --------------------------------------------------------------------- */
  /**
   * One named series, from the solver's own steps or from the output grid.
   *
   * The names -- which observable is in which column -- belong to the run and
   * are the same for both; only the rows differ, so `src` carries the numbers
   * and `state.result` carries the headings.
   */
  function column(name, src) {
    const r = state.result;
    if (!r) return null;
    const d = src || r;
    const k = r.observeNames.indexOf(name);
    if (k >= 0) {
      const out = new Float64Array(d.n);
      const w = r.observeNames.length;
      for (let i = 0; i < d.n; i++) out[i] = d.observed[i * w + k];
      return out;
    }
    const sp = r.species.indexOf(name.replace(/^\[state\] /, ''));
    if (sp >= 0) {
      const out = new Float64Array(d.n);
      const w = r.nspecies;
      for (let i = 0; i < d.n; i++) out[i] = d.states[i * w + sp];
      return out;
    }
    // The clock, for a model that does not report it itself. The canister
    // model defines TIMH and TIMY as outputs and those are used; a model of
    // one's own need not, and without this the time axis has no column and
    // every chart comes out empty.
    if (name === 'TIMH') return Float64Array.from(d.t, (v) => v / 3600);
    if (name === 'TIMY') return Float64Array.from(d.t, (v) => v / YEAR_S);
    return null;
  }

  /** Whether the reader has asked for the model's own output times. */
  function wantsGrid() {
    const r = state.result;
    return !!(r && r.grid && r.grid.n && $('facTableRows').value === 'times');
  }
  /** The rows the table and the exports are working from. */
  function tableSource() {
    const r = state.result;
    if (!r) return null;
    return wantsGrid() ? r.grid : r;
  }
  function seriesNames() {
    const r = state.result || (state.compiled && { observeNames: state.compiled.observeNames, species: state.compiled.species });
    if (!r) return [];
    return [...r.observeNames, ...r.species.map((s) => `[state] ${s}`)];
  }

  /**
   * The unit of one series, or '' when the model does not say.
   *
   * Species are the state itself and are always in the model's own unit.
   * Everything else is an output or an equation, whose unit is whatever its
   * comment in the model text put in brackets -- the same rule the HDF5 export
   * uses for its `unit` attributes, so the two cannot drift apart.
   */
  function seriesUnit(name) {
    if (name.startsWith('[state] ')) {
      // An algebraic variable is whatever its constraint makes it, so its
      // unit comes off that line's comment rather than being assumed.
      const bare = name.slice(8);
      const alg = ((state.compiled && state.compiled.algebraic) || []).find((a) => a.name === bare);
      if (alg) return typeof FacsimileHDF5 !== 'undefined' ? FacsimileHDF5.unitFromComment(alg.comment) : '';
      return 'mol/cm³';
    }
    const model = state.compiled;
    if (!model || typeof FacsimileHDF5 === 'undefined') return '';
    const entry = (model.outputs || []).find((o) => o.name === name)
      || (model.equations || []).find((e) => e.name === name)
      || (model.rates || []).find((x) => x.name === name);
    return entry ? FacsimileHDF5.unitFromComment(entry.comment) : '';
  }

  /** `NAME (unit)`, or just the name when there is no unit to give. */
  function seriesLabel(name) {
    const unit = seriesUnit(name);
    return unit ? `${name} (${unit})` : name;
  }

  /* ---------------------------------------------------------------------
     Charts
     --------------------------------------------------------------------- */
  function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
      text: cs.getPropertyValue('--text-primary').trim() || '#333',
      grid: cs.getPropertyValue('--border-color').trim() || '#ddd',
      muted: cs.getPropertyValue('--text-muted').trim() || '#888',
      surface: cs.getPropertyValue('--bg-surface').trim() || '#fff',
    };
  }
  function baseLayout(title) {
    const c = themeColors();
    return {
      title: title ? { text: title, font: { size: 12 } } : undefined,
      margin: { l: 60, r: 60, t: 10, b: 45 },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: c.text, size: 11 },
      legend: { orientation: 'h', y: -0.22, font: { size: 10 } },
      xaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      hovermode: 'x unified',
      // Said explicitly, because Plotly's default is a near-white box whatever
      // the page is: in dark mode that put this layout's light `font.color` on
      // a light background and the readings could not be read at all.
      hoverlabel: {
        bgcolor: c.surface,
        bordercolor: c.grid,
        font: { color: c.text, size: 11 },
      },
    };
  }
  const PLOT_CONFIG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['select2d', 'lasso2d'] };

  function xChoice() {
    const v = $('facXAxis').value;
    const years = v.startsWith('TIMY');
    const log = !v.endsWith('-lin');
    const typed = parseFloat($('facXMin').value);
    return {
      name: years ? 'TIMY' : 'TIMH',
      log,
      title: years ? 'time (years)' : 'time (h)',
      min: log && Number.isFinite(typed) && typed > 0 ? typed : 0,
    };
  }
  function xy(xcol, ycol, log, min) {
    // A name the current result does not carry gives an empty trace, which the
    // caller drops. Reading a missing column would throw here instead, and a
    // throw inside a redraw leaves every chart in the call half-drawn.
    if (!xcol || !ycol) return { x: [], y: [] };
    // For a log axis the t = 0 point cannot be drawn.
    const lo = log && min > 0 ? min : 0;
    const xs = [], ys = [];
    for (let i = 0; i < xcol.length; i++) {
      if (log && !(xcol[i] > 0)) continue;
      // Dropped rather than merely hidden behind the axis range: Plotly scales
      // y over every point a trace carries, visible or not, so leaving the
      // first microseconds in would keep deciding the height of the chart.
      if (xcol[i] < lo) continue;
      xs.push(xcol[i]); ys.push(ycol[i]);
    }
    return { x: xs, y: ys };
  }
  /**
   * The lower-end box only means anything on a log axis, so it is only shown
   * on one, and the unit beside it names the axis rather than the box. Called
   * for its own sake and not from xChoice, because drawCharts gives up early
   * when there is nothing to draw and the toolbar still has to be right.
   */
  function syncXControls() {
    const v = $('facXAxis').value;
    $('facXMinWrap').hidden = v.endsWith('-lin');
    $('facXMinUnit').textContent = v.startsWith('TIMY') ? 'years' : 'h';
  }
  /** Title, scale and -- on a log axis with a lower end asked for -- range. */
  function applyX(layout, x, xcol) {
    layout.xaxis.title = { text: x.title };
    if (!x.log) return;
    layout.xaxis.type = 'log';
    if (!(x.min > 0) || !xcol || !xcol.length) return;
    let hi = 0;
    for (let i = 0; i < xcol.length; i++) if (xcol[i] > hi) hi = xcol[i];
    if (hi > x.min) layout.xaxis.range = [Math.log10(x.min), Math.log10(hi)];
  }
  function eventShapes(xname) {
    const r = state.result;
    if (!r || !r.events || !r.events.length) return { shapes: [], annotations: [] };
    const c = themeColors();
    const shapes = [], annotations = [];
    r.events.forEach((ev) => {
      const x = xname === 'TIMY' ? ev.t / YEAR_S : ev.t / 3600;
      shapes.push({ type: 'line', x0: x, x1: x, y0: 0, y1: 1, yref: 'paper', line: { color: c.muted, width: 1, dash: 'dot' } });
      annotations.push({ x, y: 1, yref: 'paper', text: ev.changed.join(', '), showarrow: false, font: { size: 9, color: c.muted }, xanchor: 'left', yanchor: 'top' });
    });
    return { shapes, annotations };
  }
  /**
   * A column times a constant, or null if there is no column.
   *
   * Null-safe because the callers pass `column(name)` straight in, and a name
   * the model does not carry gives null: every other step of drawing a chart
   * already tolerates that, and this one used to throw inside the redraw and
   * leave the charts half-drawn. A model of one's own is unlikely to have
   * PRESSP in it.
   */
  function scaled(col, f) { return col ? Float64Array.from(col, (v) => v * f) : null; }

  function drawCharts() {
    syncXControls();
    const r = state.result;
    if (!r || typeof Plotly === 'undefined') return;
    const x = xChoice();
    const X = column(x.name);
    const logY = $('facLogY').checked;
    const note = $('facChartNote');
    note.textContent = r.partialFailure ? `Partial result: ${r.partialFailure}` : `${r.n} points.`;

    // 1. temperature, pressure x100, dose rate against years (linear)
    {
      const Xy = column('TIMY');
      const traces = [
        { name: 'temperature (°C)', ...xy(Xy, column('TMP'), false), mode: 'lines' },
        { name: 'pressure × 100 (atm)', ...xy(Xy, scaled(column('PRESSP'), 100), false), mode: 'lines' },
        { name: 'dose rate (Gy/h)', ...xy(Xy, column('DOSRP'), false), mode: 'lines' },
      ].filter((t) => t.y.length);
      // Said rather than left blank: these three charts are the canister
      // model's, and a model that reports none of their quantities is not
      // broken, it is simply a different model. The fourth chart is where it
      // draws itself.
      $('chart1Empty').hidden = traces.length > 0;
      const layout = baseLayout();
      layout.xaxis.title = { text: 'time (years)' };
      Object.assign(layout, eventShapes('TIMY'));
      Plotly.react('chart1', traces, layout, PLOT_CONFIG);
    }
    // 2. water, RH, oxygen, corrosion rates
    {
      const traces = [];
      const add = (name, col, axis, factor = 1) => { if (col) traces.push({ name, ...xy(X, factor === 1 ? col : scaled(col, factor), x.log, x.min), mode: 'lines', yaxis: axis }); };
      add('total water (g)', column('H2OTOTAL'), 'y');
      add('liquid water (g)', column('H2OMASSL'), 'y');
      const added = column('H2OADDED');
      if (added && Math.max(...added) > 0) add('released from rods (g)', added, 'y');
      add('relative humidity (%)', column('H2ORH'), 'y', 100);
      add('O₂ (mol)', column('O2MOL'), 'y2');
      add('oxic corrosion, O₂ used (mol cm⁻³ s⁻¹)', column('dDUMO2'), 'y2');
      add('anoxic corrosion, H₂ made (mol cm⁻³ s⁻¹)', column('dDUMH2'), 'y2');
      const layout = baseLayout();
      applyX(layout, x, X);
      layout.yaxis.title = { text: 'water (g), RH (%)' };
      layout.yaxis2 = { title: { text: 'O₂ (mol), rates' }, overlaying: 'y', side: 'right', type: logY ? 'log' : 'linear', gridcolor: 'rgba(0,0,0,0)', exponentformat: 'power' };
      Object.assign(layout, eventShapes(x.name));
      const drawn = traces.filter((t) => t.y.length);
      $('chart2Empty').hidden = drawn.length > 0;
      Plotly.react('chart2', drawn, layout, PLOT_CONFIG);
    }
    // 3. species amounts
    {
      const traces = [];
      const add = (name, col, axis, factor = 1) => { if (col) traces.push({ name, ...xy(X, factor === 1 ? col : scaled(col, factor), x.log, x.min), mode: 'lines', yaxis: axis }); };
      add('HNO₃', column('HNO3MOL'), 'y');
      add('HNO₂', column('HNO2MOL'), 'y');
      add('NH₃', column('NH3MOL'), 'y');
      add('N₂', column('N2MOL'), 'y');
      add('H₂O₂', column('H2O2MOL'), 'y');
      add('H₂', column('H2MOL'), 'y');
      add('O₂', column('O2MOL'), 'y');
      add('water vapour (mol)', column('H2OMOL'), 'y2');
      add('liquid water (mol)', column('H2OMASSL'), 'y2', 1 / 18);
      add('all water (mol)', column('H2OTOTAL'), 'y2', 1 / 18);
      const layout = baseLayout();
      applyX(layout, x, X);
      layout.yaxis.title = { text: 'amount (mol)' }; layout.yaxis.type = logY ? 'log' : 'linear'; layout.yaxis.exponentformat = 'power';
      layout.yaxis2 = { title: { text: 'water (mol)' }, overlaying: 'y', side: 'right', gridcolor: 'rgba(0,0,0,0)' };
      Object.assign(layout, eventShapes(x.name));
      const drawn3 = traces.filter((t) => t.y.length);
      $('chart3Empty').hidden = drawn3.length > 0;
      Plotly.react('chart3', drawn3, layout, PLOT_CONFIG);
    }
    drawCustom();
  }

  function selectedSeries() {
    return Array.from(document.querySelectorAll('#facSeries input:checked')).map((el) => el.value);
  }
  /**
   * The fourth chart is the only one that is emptied and rebuilt while the
   * page is in use, so it keeps its "nothing ticked yet" message in a separate
   * element rather than inside the plot itself.
   *
   * Writing that message into the plot div is what the first version did, and
   * it cost the chart from the second tick onwards: emptying the div removes
   * the SVG, Plotly still holds its own record of the graph, and the next
   * `react` then patches an SVG that is no longer in the document. It reports
   * the new traces in `gd.data` and draws none of them, so the chart goes
   * blank and stays blank however many series are ticked afterwards. Plotly is
   * told to let go of the div instead, which is what `purge` is for.
   */
  function drawCustom() {
    if (typeof Plotly === 'undefined') return;
    const plot = $('chart4');
    const empty = $('chart4Empty');
    const r = state.result;
    const names = selectedSeries();
    // Before the early return below, not after it: clearing the last series
    // takes that path, and the chips have to go with it.
    syncSeriesMarks();
    renderSeriesChips();
    if (!r || !names.length) {
      Plotly.purge(plot);
      plot.hidden = true;
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    plot.hidden = false;
    const x = xChoice();
    const X = column(x.name);
    const traces = names.map((nm) => ({ name: seriesLabel(nm), ...xy(X, column(nm), x.log, x.min), mode: 'lines' })).filter((t) => t.y.length);
    const layout = baseLayout();
    applyX(layout, x, X);
    layout.yaxis.type = $('facCustomLog').checked ? 'log' : 'linear'; layout.yaxis.exponentformat = 'power';
    Object.assign(layout, eventShapes(x.name));
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }
  /** What a series is called in the list: species lose the `[state] ` tag. */
  function seriesShortName(name) {
    return name.startsWith('[state] ') ? name.slice(8) : name;
  }

  /**
   * The series, in three groups.
   *
   * A hundred and thirty names in one wrapping list is a wall: the outputs the
   * model was written to report, the equations behind them and the state
   * itself all read alike, and nothing says which is which. They are three
   * different kinds of thing and the list says so.
   */
  /** The observable names of a result or a freshly compiled model. */
  function observed0(r) { return r.observeNames || []; }

  function seriesGroups() {
    const r = state.result || (state.compiled
      && { observeNames: state.compiled.observeNames, species: state.compiled.species });
    if (!r) return [];
    const model = state.compiled;
    const isEquation = new Set(((model && model.equations) || [])
      .filter((e) => !e.substitution).map((e) => e.name));
    const isRate = new Set((model && model.rateNames) || []);
    // An algebraic variable is a state variable, but it is not a species and
    // is not integrated: what the solver does with it is solve for it.
    const isAlgebraic = new Set((model && model.algebraicNames) || []);
    const state0 = (r.species || []);
    return [
      ['Outputs', observed0(r).filter((n) => !isEquation.has(n) && !isRate.has(n))],
      ['Equations', observed0(r).filter((n) => isEquation.has(n))],
      ['Reaction rates', observed0(r).filter((n) => isRate.has(n))],
      ['Species', state0.filter((sp) => !isAlgebraic.has(sp)).map((sp) => `[state] ${sp}`)],
      ['Algebraic', state0.filter((sp) => isAlgebraic.has(sp)).map((sp) => `[state] ${sp}`)],
    ].filter(([, list]) => list.length);
  }

  function renderSeriesList() {
    const box = $('facSeries');
    const current = new Set(selectedSeries());
    const filter = ($('facSeriesFilter').value || '').trim().toLowerCase();
    // Matched against what is shown, not the internal value: the `[state] `
    // tag is not on screen any more, so filtering by it would hide and show
    // names for a reason the reader cannot see.
    const hidden = (nm) => filter && !`${seriesShortName(nm)} ${seriesUnit(nm)}`
      .toLowerCase().includes(filter);
    box.innerHTML = seriesGroups().map(([title, names]) => {
      const items = names.map((nm) => {
        const unit = seriesUnit(nm);
        const label = seriesShortName(nm);
        // Ticking a series concerns the fourth chart alone; redrawing the other
        // three as well is a few hundred thousand points of wasted work per tick.
        return `<label class="fac-item${current.has(nm) ? ' on' : ''}"${hidden(nm) ? ' hidden' : ''} title="${
          esc(label + (unit ? ` (${unit})` : ''))}"><input type="checkbox" value="${esc(nm)}"${
          current.has(nm) ? ' checked' : ''} data-on-change="fac:redrawCustom"><span class="fac-nm">${
          esc(label)}</span>${unit ? `<span class="fac-unit">${esc(unit)}</span>` : ''}</label>`;
      }).join('');
      const shown = names.filter((nm) => !hidden(nm)).length;
      return `<section class="fac-group"${shown ? '' : ' hidden'}><h4>${esc(title)}<span class="fac-count">${
        shown === names.length ? names.length : `${shown} of ${names.length}`}</span></h4><div class="fac-grid">${items}</div></section>`;
    }).join('');
    renderSeriesChips();
  }

  /**
   * What is ticked, above the list and one click from being un-ticked.
   *
   * The list is a scrolling box of a hundred and thirty; without this the only
   * way to see what a chart is drawing is to scroll it and look for ticks.
   */
  function renderSeriesChips() {
    const box = $('facSeriesChips');
    if (!box) return;
    const picked = selectedSeries();
    box.hidden = !picked.length;
    box.innerHTML = picked.map((nm) => {
      const unit = seriesUnit(nm);
      return `<button type="button" class="fac-chip" data-series="${esc(nm)}" data-on-click="fac:unpickSeries" title="Remove ${
        esc(seriesShortName(nm))} from the chart">${esc(seriesShortName(nm))}${
        unit ? `<span class="fac-unit">${esc(unit)}</span>` : ''}<span class="fac-chip-x" aria-hidden="true">\u00d7</span></button>`;
    }).join('');
  }

  /** Keeps the pills' selected look in step with their checkboxes. */
  function syncSeriesMarks() {
    document.querySelectorAll('#facSeries .fac-item').forEach((el) => {
      const input = el.querySelector('input');
      el.classList.toggle('on', !!(input && input.checked));
    });
  }

  /* ---------------------------------------------------------------------
     Table and exports
     --------------------------------------------------------------------- */
  function tableColumns() {
    const r = state.result;
    const mode = $('facTableCols').value;
    const outputs = r.observeNames;
    const species = r.species.map((s) => `[state] ${s}`);
    if (mode === 'species') return ['TIMH', ...species];
    if (mode === 'all') return [...outputs, ...species];
    return outputs;
  }
  function rowIndices(mode, src) {
    const r = src || state.result;
    if (mode === 'times') return Array.from({ length: r.n }, (_, i) => i);
    if (mode === 'all' || r.n <= Number(mode)) return Array.from({ length: r.n }, (_, i) => i);
    const want = Number(mode);
    const t = r.t;
    let first = 1;
    while (first < r.n && !(t[first] > 0)) first++;
    const idx = new Set([0]);
    if (first < r.n) {
      const a = Math.log10(t[first]), b = Math.log10(t[r.n - 1]);
      let j = first;
      for (let k = 0; k < want; k++) {
        const target = Math.pow(10, a + (b - a) * k / (want - 1));
        while (j < r.n - 1 && t[j] < target) j++;
        idx.add(j);
      }
    }
    idx.add(r.n - 1);
    return [...idx].sort((p, q) => p - q);
  }
  function renderTable() {
    const r = state.result;
    const table = $('facTable');
    if (!r) { table.innerHTML = ''; $('facTableNote').textContent = 'Run the model to fill the table.'; return; }
    const src = tableSource();
    const cols = tableColumns();
    const rows = rowIndices($('facTableRows').value, src);
    const data = cols.map((c) => column(c, src));
    let html = '<thead><tr>' + cols.map((c) => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>';
    for (const i of rows) {
      html += '<tr>' + data.map((col) => `<td>${fmtNum(col[i])}</td>`).join('') + '</tr>';
    }
    table.innerHTML = html + '</tbody>';
    $('facTableNote').textContent = wantsGrid()
      ? `${rows.length} of the ${r.gridWanted || src.n} times the model asks for, interpolated between solver steps.`
      : `${rows.length} of ${src.n} rows shown.`;
    syncRowsControls();
  }
  function fmtNum(v) {
    if (!Number.isFinite(v)) return String(v);
    if (v === 0) return '0';
    const a = Math.abs(v);
    return a >= 1e-3 && a < 1e6 ? v.toPrecision(6).replace(/\.?0+$/, '') : v.toExponential(4);
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function fileStem() { return `canister_${state.presetId || 'custom'}`; }

  function downloadCsv() {
    const r = state.result;
    if (!r) { notifyUser('Run the model first.'); return; }
    const src = tableSource();
    const cols = tableColumns();
    const data = cols.map((c) => column(c, src));
    const lines = [['TIMS', ...cols].map(kvotCsvCell).join(',')];
    for (let i = 0; i < src.n; i++) lines.push([src.t[i], ...data.map((col) => col[i])].map((v) => kvotCsvCell(String(v))).join(','));
    downloadBlob(new Blob([lines.join('\n')], { type: 'text/csv' }), `${fileStem()}.csv`);
  }

  /**
   * The row controls say what the buttons beside them will write.
   *
   * The CSV and Excel files hold every solver step unless the model has a
   * <TIMES> section and the reader has asked for it, and a button that says
   * "all steps" while writing a hundred interpolated rows would be lying.
   */
  function syncRowsControls() {
    const r = state.result;
    const opt = $('facTableRows').querySelector('option[value="times"]');
    const times = (state.compiled && state.compiled.outputTimes && state.compiled.outputTimes.length) || 0;
    if (opt) {
      opt.hidden = !times;
      opt.disabled = !(r && r.grid && r.grid.n);
      opt.textContent = times ? `at the model's output times (${times})` : 'at the model\u2019s output times';
      if (opt.hidden && $('facTableRows').value === 'times') $('facTableRows').value = '200';
    }
    const csv = $('facCsvBtn');
    if (csv) csv.textContent = wantsGrid() ? 'Download CSV (output times)' : 'Download CSV (all steps)';
  }

  async function downloadXlsx() {
    const r = state.result;
    if (!r) { notifyUser('Run the model first.'); return; }
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') { notifyUser('The Excel writer did not load; use CSV instead.'); return; }
    try {
      const xlsx = new XlsxWriter(`${fileStem()}.xlsx`);
      const settings = (state.compiled ? state.compiled.settings : []).map((s) => [s.name, s.isTable ? s.value : Number(s.value), s.comment || '']);
      const s = state.solver;
      settings.push(['METHOD', s.method, 'Solver'],
        ...(readsBdf(s.method) ? [['BDF', s.bdf ? 'TRUE' : 'FALSE', 'BDF formulas: every κ of the NDF zero']] : []),
        ['RTOL', Number(s.rtol), 'Relative tolerance'], ['ATOL', Number(s.atol), 'Absolute tolerance (mol/cm3)'],
        ['ATOLSPECIES', (s.atolSpecies || '').replace(/\s*\n\s*/g, '; ').trim(), 'Per-species absolute tolerance'],
        ['NORM', s.norm, 'Error norm'],
        ['SCENARIO', state.presetId || 'custom', 'Scenario'],
        ['REFERENCE', (FACSIMILE_PRESETS.find((x) => x.id === state.presetId) || {}).reference || '', 'Where the case is defined'],
        ['DATE', new Date().toISOString(), 'Time of simulation'], ['SIMULATIONTIME', r.seconds ?? '', 'Seconds'],
        ['ROWS', wantsGrid() ? 'output times' : 'solver steps', 'What the DATA and STATES sheets hold']);
      if (r.stats) settings.push(['STEPS', r.stats.nsteps, 'Accepted steps'], ['MATRIX', r.stats.lu || (r.stats.sparse ? 'sparse' : 'dense'), 'Iteration matrix']);
      xlsx.writeData(settings, 'SETTINGS', { header: ['SETTING', 'VALUE', 'DESCRIPTION'] });
      const src = tableSource();
      const outCols = r.observeNames.map((c) => column(c, src));
      const dataRows = [];
      for (let i = 0; i < src.n; i++) dataRows.push([src.t[i], ...outCols.map((col) => col[i])]);
      xlsx.writeData(dataRows, 'DATA', { header: ['TIMS', ...r.observeNames] });
      const spCols = r.species.map((sp) => column(`[state] ${sp}`, src));
      const stateRows = [];
      for (let i = 0; i < src.n; i++) stateRows.push([src.t[i], ...spCols.map((col) => col[i])]);
      xlsx.writeData(stateRows, 'STATES', { header: ['TIME', ...r.species] });
      await xlsx.save();
    } catch (e) {
      reportFailure('downloadXlsx', e, { userMessage: 'The Excel file could not be written' });
    }
  }

  /* ---------------------------------------------------------------------
     Handing a run to the HDF5 Browser
     --------------------------------------------------------------------- */

  /** Where the browser is: a sibling page, so the handoff is same-origin. */
  const HDF5_BROWSER = 'rb.html';
  /** How long to wait for the tab to say it is listening, and then to answer. */
  const HANDOFF_READY_MS = 45000;
  const HANDOFF_OPEN_MS = 60000;

  /** The run as HDF5 bytes, described by the model that produced it. */
  function buildHdf5() {
    const ran = state.ran || { model: state.compiled, solver: {}, text: state.text, scenario: state.presetId || 'custom' };
    const preset = FACSIMILE_PRESETS.find((x) => x.id === ran.scenario);
    return FacsimileHDF5.resultFile(state.result, ran.model, {
      scenario: ran.scenario, reference: preset ? preset.reference : '',
      solver: ran.solver, text: ran.text,
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
    if (!state.result) { notifyUser('Run the model first: there is nothing to send yet.'); return; }
    const origin = window.location.origin;
    const win = window.open(`${HDF5_BROWSER}#handoff=${encodeURIComponent(origin)}`, '_blank');
    if (!win) {
      notifyUser('The browser blocked the new tab. Allow pop-ups for this page, or use '
        + '“Download HDF5” on the Table tab and open the file in the HDF5 Browser yourself.');
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
      setStatus(`The handoff failed: ${e.message}. “Download HDF5” on the Table tab `
        + 'writes the same file.', 'error');
    } finally {
      window.removeEventListener('message', onMessage);
    }
  }

  /** The same file, as a download. */
  function downloadHdf5() {
    if (!state.result) { notifyUser('Run the model first.'); return; }
    try {
      const bytes = buildHdf5();
      downloadBlob(new Blob([bytes], { type: 'application/x-hdf5' }), `${fileStem()}.h5`);
    } catch (e) {
      reportFailure('downloadHdf5', e, { userMessage: 'The HDF5 file could not be written' });
    }
  }

  /* ---------------------------------------------------------------------
     Jacobian tab
     --------------------------------------------------------------------- */
  function drawJacobian() {
    const canvas = $('facJacCanvas');
    const m = state.compiled;
    const info = $('facJacInfo');
    if (!m) { info.textContent = ''; return; }
    const n = m.pattern.n;
    const size = 504;
    const cell = Math.max(1, Math.floor(size / n));
    canvas.width = cell * n; canvas.height = cell * n;
    const ctx = canvas.getContext('2d');
    const c = themeColors();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const { colPtr, rowIdx } = m.pattern;
    for (let j = 0; j < n; j++) {
      for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
        const i = rowIdx[k];
        ctx.fillStyle = i === j ? '#bb6c5d' : c.text;
        ctx.fillRect(j * cell, i * cell, cell, cell);
      }
    }
    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const j = Math.floor((ev.clientX - rect.left) / rect.width * n);
      const i = Math.floor((ev.clientY - rect.top) / rect.height * n);
      if (i < 0 || j < 0 || i >= n || j >= n) return;
      let present = false;
      for (let k = colPtr[j]; k < colPtr[j + 1]; k++) if (rowIdx[k] === i) present = true;
      $('facJacHover').textContent = `row ${m.species[i]} (d[${m.species[i]}]/dt), column ${m.species[j]}: ${present ? 'structurally non-zero' : 'zero'}`;
    };
    const st = state.result && state.result.stats;
    let html = `<p><b>${n} × ${n}</b> matrix, <b>${m.nnz}</b> structurally non-zero entries (${(100 * m.density).toFixed(1)} %). Rows are the species' equations, columns the species differentiated with respect to; the diagonal is drawn in the accent colour.</p>`
      + `<p>A finite-difference Jacobian through this pattern needs <b>${m.colours}</b> evaluations of the model (one per group of columns that share no row) instead of ${n}. The analytic one needs none: its values come from the derivative code, see the <em>Code</em> tab.</p>`;
    if (st && st.lu === 'refactor') {
      html += `<p>Last run: the iteration matrix I − hJ was factorised as a <b>sparse LU that keeps its pivots</b>. Its factor holds ${st.fill} entries against ${n * n} for the dense matrix (${(100 * st.fill / (n * n)).toFixed(0)} %, ${st.ordering} order). Each factorisation repeats the same eliminations and checks every pivot; the pivots were chosen again ${st.repivots} time${st.repivots === 1 ? '' : 's'} where one failed the check${st.fallbacks ? `, and ${st.fallbacks} factorisation${st.fallbacks === 1 ? '' : 's'} went to the dense LU` : ''}.</p>`;
    } else if (st) html += `<p>Last run: the iteration matrix I − hJ was factorised <b>${st.sparse ? 'sparsely' : 'densely'}</b>. ${st.fill != null ? `A sparse LU factor of it holds ${st.fill} entries against ${n * n} for the dense matrix (${(100 * st.fill / (n * n)).toFixed(0)} %, ${st.ordering} ordering), which is why ${st.sparse ? 'the sparse path was kept' : 'the dense factorisation was cheaper'}.` : ''}</p>`;
    if (state.verify) html += verifyHtml(state.verify);
    else html += '<p class="fac-muted">Press <em>Check Jacobian</em> to compare the analytic entries with finite differences.</p>';
    info.innerHTML = html;
  }

  function verifyHtml(v) {
    let html = '<h4>Check against finite differences</h4>';
    for (const c of v.checks) {
      html += `<p><b>${esc(c.label)}</b>: ${c.checked} resolvable entries compared, <b>${c.ndiscrepancies}</b> differ by more than 0.1 %`;
      if (c.outsidePattern) html += `; a numerical entry outside the pattern at (${esc(c.outsidePattern.row)}, ${esc(c.outsidePattern.col)}) = ${c.outsidePattern.numeric.toExponential(2)}`;
      html += '.';
      if (c.discrepancies.length) {
        html += '<br>' + c.discrepancies.map((d) => `d[${esc(d.row)}]/d${esc(d.col)}: analytic ${d.analytic.toExponential(4)}, numeric ${d.numeric.toExponential(4)}`).join('<br>');
      }
      html += '</p>';
    }
    html += '<p class="fac-muted">An entry counts as resolvable when its effect on the rate over the perturbation exceeds 10⁻⁹ of the rate; below that a finite difference is round-off. With a negative concentration the clamped value and the kept derivative disagree by design.</p>';
    return html;
  }

  async function verify() {
    if (!(await compile({ reveal: true }))) return;
    setStatus('Checking the Jacobian…');
    try {
      const reply = await request({ type: 'verify', text: state.text, clampNegative: state.solver.clamp });
      state.verify = reply;
      drawJacobian();
      showTab('jacobian');
      const bad = reply.checks.reduce((s, c) => s + c.ndiscrepancies, 0);
      setStatus(bad ? `Jacobian check: ${bad} entries differ from finite differences; see the Jacobian tab.` : 'Jacobian check: every resolvable entry agrees with finite differences.', bad ? 'error' : 'ok');
    } catch (e) {
      setStatus(`The check failed: ${e.message}`, 'error');
    }
  }

  /* ---------------------------------------------------------------------
     Code tab, tabs, files
     --------------------------------------------------------------------- */
  function showCode() {
    const m = state.compiled;
    const which = $('facCodeSelect').value;
    $('facCode').textContent = m && m.sources[which] ? m.sources[which] : '';
  }
  function showTab(name) {
    document.querySelectorAll('.fac-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.fac-pane').forEach((p) => { p.hidden = p.id !== `pane-${name}`; });
    if (name === 'charts') { drawCharts(); resizeCharts(); }
    if (name === 'table') renderTable();
    if (name === 'jacobian') drawJacobian();
    if (name === 'code') showCode();
  }
  function afterResult() {
    renderSeriesList();
    drawCharts();
    renderTable();
    drawJacobian();
  }

  function applyModelText() {
    state.text = $('facModelText').value;
    state.textDirty = false;
    compile({ reveal: true });
  }

  /*
    A model file is a few tens of kilobytes of text; the canister model is
    under 50 kB. Past this it is something else with the right ending -- a
    solver log, an output listing -- and reading it would hold the page while
    the editor coloured every line.
  */
  const MODEL_FILE_LIMIT = 16 * 1024 * 1024;

  /**
   * Reads a model file into the editor and compiles it: what Open… does, and
   * what dropping a file on the page does.
   */
  function openModelFile(file) {
    if (file.size > MODEL_FILE_LIMIT) {
      notifyUser(`${file.name} was not opened: it is ${kvotFormatBytes(file.size)}, and a model file `
        + `can be at most ${kvotFormatBytes(MODEL_FILE_LIMIT)}.`);
      return;
    }
    file.text().then((text) => {
      setModelText(text);
      // Held while a run has the worker, as an edit typed into the text is:
      // sent now, the compile would wait behind the run, and be thrown away
      // with it if Stop were pressed.
      if (state.running) scheduleCompile();
      else compile({ reveal: true });
      showTab('model');
    }).catch((e) => reportFailure('loadFile', e, { userMessage: 'The file could not be read' }));
  }

  function loadFile() {
    const input = $('facFileInput');
    input.onchange = () => {
      const file = input.files && input.files[0];
      if (!file) return;
      openModelFile(file);
      input.value = '';
    };
    input.click();
  }

  /** The endings Open… offers, read off the file input so the two agree. */
  function modelFileEndings() {
    return $('facFileInput').accept.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  }

  /**
   * Opens what was dropped, if it is one model file.
   *
   * Stricter than Open…, whose dialog is a choice the reader made. A drop can
   * be a slip -- the wrong file picked up off the desktop, or several -- and
   * what it replaces is the text in the editor, which may be the only copy.
   */
  function openDropped(files) {
    if (files.length > 1) {
      notifyUser(`Drop one model file at a time: that was ${files.length} files.`);
      return;
    }
    const file = files[0];
    const endings = modelFileEndings();
    if (!endings.some((end) => file.name.toLowerCase().endsWith(end))) {
      notifyUser(`${file.name} was not opened: only a ${listOf(endings, 'or')} file is read as a model. `
        + 'Rename it if it is one.');
      return;
    }
    openModelFile(file);
  }

  /**
   * A file dropped anywhere on the page opens as a model, not just one dropped
   * on the editor: the browser's own answer to a file dropped where nothing
   * takes it is to leave the page and show the file.
   *
   * Only a drag that carries files is the page's business. Text dragged within
   * the editor, or into it from elsewhere, is left to the browser.
   */
  function initDrop() {
    const overlay = $('facDrop');
    let depth = 0;
    const carriesFiles = (ev) => !!ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes('Files');
    const show = (on) => { overlay.hidden = !on; };
    document.addEventListener('dragenter', (ev) => {
      if (!carriesFiles(ev)) return;
      ev.preventDefault();
      depth += 1;
      show(true);
    });
    // Shown again on every dragover, not only on entering: the count can be
    // reset under a drag that is still going on, and dragover keeps coming for
    // as long as one is.
    document.addEventListener('dragover', (ev) => {
      if (!carriesFiles(ev)) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'copy';
      show(true);
    });
    // Each element the pointer crosses sends an enter and then a leave, so the
    // count is back at zero only when the drag has left the page.
    document.addEventListener('dragleave', (ev) => {
      if (!carriesFiles(ev)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) show(false);
    });
    document.addEventListener('drop', (ev) => {
      if (!carriesFiles(ev)) return;
      ev.preventDefault();
      depth = 0;
      show(false);
      if (ev.dataTransfer.files.length) openDropped(ev.dataTransfer.files);
    });
    // The count goes wrong when an element the pointer entered is taken out
    // from under it -- a run finishing mid-drag redraws the charts and the
    // footer -- because the leave that would have balanced it never comes. A
    // page is sent no mouse events while a drag is over it, so the first one
    // afterwards means the drag is done.
    document.addEventListener('mousemove', () => {
      if (depth || !overlay.hidden) { depth = 0; show(false); }
    });
  }
  function saveFile() {
    const text = $('facModelText').value;
    downloadBlob(new Blob([text], { type: 'text/plain' }), `${fileStem()}.fac`);
  }
  function resetModel() {
    // The built-in text carries the 13g settings, so there is nothing to apply
    // on top of it; the compile below works out that that is the scenario.
    setModelText(FACSIMILE_DEFAULT_MODEL);
    const p = FACSIMILE_PRESETS.find((x) => x.id === '13g');
    state.solver = { method: 'ndf', bdf: false, rtol: String(p.solver.rtol), atol: '1e-30', norm: 'max', maxOrder: 5, hmaxYears: '0', matrix: 'auto', jacobianMode: 'analytic', clamp: true, nonNegative: true };
    writeSolverControls();
    compile();
  }

  /* ---------------------------------------------------------------------
     The (i): what each setting, heading and toolbar is

     A small (i) at the right-hand edge opens a panel over the right-hand side
     of the window with what the thing is, what its choices do and where the
     Help says more (resources/js/kvot-info.js does the panel). It replaces
     the hover tooltips these controls had, which cannot be read while a field
     is being edited, hold a sentence or two, and do not work on touch or from
     the keyboard.

     A topic that marks the choice in force, or shows a value, is a function:
     it is called each time its panel opens, and again by KvotInfo.refresh()
     when a setting changes under an open panel. Which methods read a solver
     setting is worked out from the declarations updateSolverOptions uses
     (BUILTIN_OPTIONS, FacsimileOdeJulia.options), so the panel and its (i)s
     cannot disagree about it. The case settings are the model's own, so
     their topics are made from the compiled lines (caseTopic) and registered
     again after every compile (setupInfo).
     --------------------------------------------------------------------- */
  const more = (label, id) => ({ label, id });
  const isPort = (method) => typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method);

  /** The methods on the menu that read `key`, by the menu's own names. */
  function readers(key) {
    const menu = Array.from($('facMethod').options);
    const names = menu
      .filter((o) => (isPort(o.value) ? FacsimileOdeJulia.options(o.value) || [] : BUILTIN_OPTIONS).includes(key))
      .map((o) => o.textContent.replace(/\s*\(.*$/, '').trim());
    if (!names.length) return 'none';
    return names.length === menu.length ? 'every method' : listOf(names);
  }

  /** What each method on the menu is, and what it costs on this model. */
  const METHOD_NOTES = {
    ndf: 'This page’s own: the numerical differentiation formulas of Shampine and Reichelt, of orders 1 to 5. The one to use: a 500-year case takes a second or two. With BDF formulas ticked it runs the plain backward differentiation formulas. The only method that takes a model with algebraic variables.',
    julia_fbdf: 'A multistep formula of variable order that reuses one matrix factorisation across many steps. About as quick as the NDF on this model, and an independent check that costs nothing.',
    julia_qndf: 'The same numerical differentiation formulas as the NDF, written by other people: the most direct check there is on it. With BDF formulas ticked it runs as QBDF. About three times the steps of the NDF on this model.',
    julia_kencarp4: 'A diagonally implicit Runge–Kutta method of order 4, cheap at moderate and loose tolerances. The dearest here that finishes: about ten times the steps of the NDF.',
    julia_radau5: 'Fully implicit, order 5 in three stages, and the least troubled by stiffness: the one to believe when two others disagree. It does not get through this model at an absolute tolerance of 1e-30.',
    julia_rodas5p: 'A Rosenbrock method: one linear solve per stage and no Newton iteration, so nothing that can fail to converge. It does not get through this model at 1e-30; at 1e-20 it takes a few hundred steps.',
    julia_trbdf2: 'Second order, L-stable and diagonally implicit: fast at loose tolerances. About five times the steps of the NDF on this model.',
  };

  const TOPICS = {
    'sec:scenario': () => {
      const p = FACSIMILE_PRESETS.find((x) => x.id === state.presetId);
      const inReport = FACSIMILE_PRESETS.filter((x) => /^SKB TR-22-15, Table 3-1/.test(x.reference || '')).length;
      return {
        kicker: 'Section', title: 'Scenario',
        lead: 'The cases of SKB’s study of the gas in an intact canister. Choosing one writes its settings into the `<SETTINGS>` lines of the model text, a line at a time, so a model you have edited keeps every change but its settings.',
        facts: [['Scenarios', String(FACSIMILE_PRESETS.length)], ['From TR-22-15, Table 3-1', String(inReport)], ['Now', p ? p.id : 'custom']],
        sections: [
          { heading: 'Choosing one', list: [
            'writes each of its settings into its line, keeping the comment',
            'sets the relative tolerance to the one the Python port’s tests ran that case at, from 1e-3 to 1e-5',
            'puts `H2OPAIR` back to 0, the water model the published cases were run with',
            'leaves the method and the other solver settings as they were',
          ] },
          { heading: 'custom', text: 'The list follows the text: after every compile it shows the scenario whose settings the text holds, or custom when it holds none of them. Typing over a setting, in the panel or in the text, makes the case custom.' },
          { heading: 'Where each is defined', text: 'The line under the description: the case and the results section of TR-22-15, or, for a variant the report does not have, the note or the FACSIMILE file it comes from. It goes with the run into the HDF5 file and the Excel file.' },
          { heading: 'Keep in mind', text: 'A setting is written only where the text has a line for it. One with no line is named and left out, and the case then reads as custom.' },
        ],
        more: more('What this page does', 'help-about'),
      };
    },
    'sec:file': {
      kicker: 'Section', title: 'Model file',
      lead: 'The model is a text, shown and edited on the Model tab. This section reads one in, writes it out, or goes back to the built-in one.',
      facts: [['Largest file', '16 MB']],
      sections: [
        { list: [
          '**Open…** reads a model file into the editor and compiles it. Dropping a file anywhere on the page does the same, one file at a time, ending in `.fac`, `.txt` or `.in`.',
          '**Save as .fac** writes the text in the editor, named after the scenario: `canister_13g.fac`, or `canister_custom.fac` for a case of your own.',
          '**Reset** puts back the built-in model text, which carries the settings of 13g, and every solver setting at its default.',
        ] },
        { heading: 'Kept between visits', text: 'The text, the settings, the solver settings and which sections are folded are kept in this browser’s storage, not its cache, so a reload does not reset them; Reset does. When the built-in model has changed since, a text you had not edited is moved onto the new one with your settings carried over, and one you had edited is kept, with a word in the status line. Nothing leaves your machine.' },
      ],
      more: more('Files', 'help-files'),
    },
    'sec:case': () => {
      const m = state.compiled;
      const p = FACSIMILE_PRESETS.find((x) => x.id === state.presetId);
      return {
        kicker: 'Section', title: 'Case settings',
        lead: 'The `<SETTINGS>` lines of the model text, a row each. A setting has one copy, and it is the line: typing in a field rewrites its line, comment and all, and editing the line shows in the field at the next compile. So the file you save is the case you ran.',
        facts: [['Settings', m ? String(m.settings.length) : ''], ['Scenario', p ? p.id : 'custom']],
        sections: [
          { heading: 'A value is', list: [
            'a number',
            'an expression of earlier settings and the constants, such as `PCAR = 1 - PCAIR`',
            'for a profile, the name of a `<TABLE>`, which is then offered as a list',
          ] },
          { heading: 'The label', text: 'The comment on the line. A unit in brackets in it is the unit the HDF5 file records for the setting.' },
          { heading: 'Keep in mind', text: 'Typing over a setting makes the case custom, and choosing a scenario writes its settings over yours. The page reads `TEND` as the length of the run, and runs a model with no `TEND` line for 500 years.' },
        ],
        more: more('The model file', 'help-model-file'),
      };
    },
    'sec:solver': {
      kicker: 'Section', title: 'Solver',
      lead: 'Which integrator solves the model, and how closely. Method and the two tolerances are what a reader changes; the rest is under Advanced settings, for when those are not enough.',
      sections: [
        { text: 'Only the settings the chosen method reads are shown, and a line under them names the ones it does not. They are kept in this browser between visits; Reset, in the Model file section, puts them back to their defaults.' },
        { heading: 'Two choices that are not settings', list: [
          'The NDF solves its Newton corrections in variables scaled by `max(|y|, atol/rtol)`. The concentrations span forty orders of magnitude, and unscaled, the pivoting is decided by the largest coefficients and the corrections for the trace species come out wrong.',
          'It takes at least two Newton iterations a step. At the humidity switch a Jacobian formed a step earlier can damp the first correction by a factor 1e6 while the residual is still far from zero.',
        ] },
      ],
      more: more('Solver settings', 'help-solver'),
    },
    'set:method': () => {
      const v = $('facMethod').value;
      return {
        kicker: 'Solver', title: 'Method',
        lead: 'The integrator. Every one is a stiff solver handed the model’s analytic sparse Jacobian; they differ in their formulas, and on this model in what they cost. The Julia ports are methods of DifferentialEquations.jl, ported to JavaScript: nothing is downloaded, and they run in the page as the NDF does.',
        facts: [['Default', 'NDF']],
        sections: [
          { choices: Array.from($('facMethod').options).map((o) => [o.textContent.trim(), METHOD_NOTES[o.value] || '', o.value === v]) },
          { heading: 'Keep in mind', list: [
            'The Julia ports need a background worker. Where none can start, as in a copy of the page opened from a file, they are refused rather than run on the page, where a run of minutes is a frozen tab.',
            'A model with an `<ALGEBRAIC>` section runs on the NDF only. The ports take no mass matrix and would integrate the constraint residuals as if they were rates of change.',
            'The costs are for the 500-year case 13g at the page’s defaults, and say nothing about accuracy: every method that finishes agrees on the water left.',
          ] },
        ],
        more: more('The Julia ports', 'help-julia'),
      };
    },
    'set:rtol': {
      kicker: 'Solver', title: 'Relative tolerance',
      lead: 'The error a step may make, as a fraction of each quantity’s own size: 1e-5 is about five significant digits. Tighter is slower and more accurate.',
      facts: [['Default', '1e-5'], ['Allowed', 'above 0, below 1'], ['The scenarios', '1e-3 to 1e-5']],
      sections: [
        { heading: 'How it is used', text: 'The error of each species is compared with `rtol·max(|y|, atol/rtol)`: a species above `atol/rtol` is judged against itself, one below it against the absolute tolerance.' },
        { heading: 'Choosing a scenario', text: 'sets it to the tolerance the Python port’s tests ran that case at.' },
        { heading: 'Keep in mind', text: 'The water left after 500 years is not converged at 1e-5. On 13g it scatters between 36 and 66 g at tolerances from 1e-4 to 1e-6, not even monotonically, and settles at 65.94 g from 1e-7 down. If the number matters, tighten this to 1e-7 and check that it stops moving.' },
      ],
      more: more('Read the table for cost, not for accuracy', 'help-converged'),
    },
    'set:atol': {
      kicker: 'Solver', title: 'Absolute tolerance',
      lead: 'The error allowed on a small concentration, in mol/cm³: a species below `atol/rtol` may be out by this much, so set it below the smallest concentration that matters.',
      facts: [['Default', '1e-30 mol/cm³'], ['Allowed', '0 or more']],
      sections: [
        { text: 'The Python port used 1e-100 and below: purely relative control down to nothing, which is why it took minutes. 1e-30 leaves the species below it unresolved, which is where the physics stops mattering.' },
        { heading: 'Keep in mind', text: 'A looser one makes every method cheaper here, and is worth trying before a method is given up on: Rodas5P, which does not get through this model at 1e-30, solves it in a few hundred steps at 1e-20. For a few species on their own, use the per-species tolerance under Advanced settings.' },
      ],
      more: more('Solver settings: tolerances', 'help-tolerances'),
    },
    'set:bdf': () => ({
      kicker: 'Solver', title: 'BDF formulas',
      lead: 'Runs the plain backward differentiation formulas: the NDF with every κ set to zero. On QNDF it gives QBDF.',
      facts: [['Default', 'off'], ['κ of the NDF', '−0.185, −1/9, −0.0823, −0.0415 and 0 at orders 1 to 5'], ['Read by', readers('bdf')]],
      sections: [
        { text: 'κ is how far each numerical differentiation formula departs from the backward differentiation formula of the same order. The BDF are a little more stable and a little less accurate per step: on this model about 6 % more steps for the same answer.' },
        { heading: 'When to tick it', text: 'To see what the κ terms buy on a problem, or to match a result someone else worked out with BDF. The NDF run as BDF gets through all but one of the 39 scenarios. The one it misses stops where the water supply is cut off, and letting the absolute tolerance follow the solution gets it through.' },
        { heading: 'Not the Newton tolerance', text: 'The κ of the Newton tolerance, further down, is another number: how closely a Julia port solves each stage.' },
      ],
      more: more('Solver settings: method', 'help-method'),
    }),
    'set:atolSpecies': () => ({
      kicker: 'Solver', title: 'Per-species absolute tolerance',
      lead: 'An absolute tolerance of their own for the species named, one `SPECIES VALUE` a line. Every species not listed keeps the absolute tolerance above.',
      facts: [['Default', 'none'], ['Read by', readers('atolSpecies')]],
      sections: [
        { heading: 'Writing it', list: [
          '`H2O 1e-12`, `OH = 1e-22` or `OH: 1e-22`; several on a line, with commas or semicolons between them',
          '`#` or `!` starts a comment',
          'names are matched against the compiled model, in any case',
          'a line that is not a name and a number, a negative value or a name the model does not have is named under the panel, and Run refuses it',
        ] },
        { heading: 'Two things to know first', list: [
          'It does nothing for a species that is never small. The weight is `max(|y|, atol/rtol)`, so at rtol 1e-5 and atol 1e-30 anything above 1e-25 is judged against itself, and its own atol never enters.',
          'Relaxing the fast trace species, the obvious use, backfires on this model. Taking the ions `E`, `HP`, `O2M`, `H3OP` and `NOP` from 1e-30 to 1e-20 cost about twelve times the steps. A tolerance above a species’ own size hides it from the error test, and the step controller then asks for steps the Newton iteration cannot solve.',
        ] },
      ],
      more: more('Solver settings: per-species absolute tolerance', 'help-atol-species'),
    }),
    'set:norm': () => {
      const n = state.compiled ? state.compiled.nspecies : 0;
      const v = $('facNorm').value;
      return {
        kicker: 'Solver', title: 'Error norm',
        lead: 'How the errors of the species, each divided by its own tolerance, are made into the one number a step is accepted or rejected on.',
        facts: [['Default', 'max'], ['Read by', readers('norm')]],
        sections: [
          { choices: [
            ['max', 'The largest of them: the worst-resolved species decides the step. What the numerical differentiation formulas were published with.', v === 'max'],
            ['rms', 'Their root mean square, as CVODE and SUNDIALS take it: longer steps and a looser answer.', v === 'rms'],
          ] },
          { heading: 'How far apart', text: n
            ? `With one of this model’s ${n} species out by exactly one unit of tolerance and the rest exact, max reads 1 and rejects the step, while rms reads 1/√${n} = ${(1 / Math.sqrt(n)).toFixed(3)} and accepts it.`
            : 'With one of n species out by exactly one unit of tolerance and the rest exact, max reads 1 and rejects the step, while rms reads 1/√n and accepts it.' },
          { heading: 'Keep in mind', text: 'The trace species here sit forty orders of magnitude below the main ones, and it is they the choice is about. rms makes the methods far cheaper on this model, and is worth trying before a method is given up on. RadauIIA5 does not read it: it measures its error against Hairer’s own transformed tolerances, in a norm of its own.' },
        ],
        more: more('Solver settings: error norm', 'help-norm'),
      };
    },
    'set:maxOrder': () => ({
      kicker: 'Solver', title: 'Maximum order',
      lead: 'The highest order the variable-order formulas may reach, from 1 to 5. Lower is steadier through a discontinuity and slower on a smooth stretch.',
      facts: [['Default', '5'], ['Read by', readers('maxOrder')]],
      sections: [{ text: 'Only the multistep formulas have an order to cap. The one-step methods, Rodas5P, KenCarp4, TRBDF2 and RadauIIA5 (fixed at order 5 in three stages), do not show it.' }],
      more: more('Which settings apply', 'help-apply'),
    }),
    'set:minOrder': () => ({
      kicker: 'Solver', title: 'Minimum order',
      lead: 'The lowest order the variable-order formulas may drop to. Set it to the maximum to hold the order fixed; a minimum above the maximum is read as the maximum.',
      facts: [['Default', '1'], ['Read by', readers('minOrder')]],
      sections: [{ text: 'The NDF has no minimum and does not show it: it starts at order 1 and chooses its order from its own error estimates.' }],
      more: more('Which settings apply', 'help-apply'),
    }),
    'set:hmax': {
      kicker: 'Solver', title: 'Maximum step',
      lead: 'The longest step the solver may take, in years.',
      facts: [['Default', '0'], ['0, for the NDF', 'a tenth of the time it is integrating: the run, or what is left of it after an event'], ['0, for the Julia ports', 'no limit']],
      sections: [
        { heading: 'When to set it', text: 'Where the model changes faster than its output can show and the solver steps over the change, and to catch an event whose trigger moves faster than the solution. A crossing is found from the sign of the trigger at the two ends of a step: an excursion that goes out and comes back inside one step is not seen at all, and one that is seen can be placed on an interpolant too coarse for it. On sin(t) against 0.9 the second crossing comes out at 3.01 where it belongs at 2.02. A cap makes the solver look more often.' },
        { heading: 'Keep in mind', text: 'A small cap makes a long run long: 1e-4 years over 500 years is five million steps.' },
      ],
      more: more('Events at a list of values', 'help-events'),
    },
    'set:matrix': () => {
      const v = $('facMatrix').value;
      return {
        kicker: 'Solver', title: 'Iteration matrix',
        lead: 'How I − hJ, the matrix every implicit step solves with, is factorised. The choice changes what a step costs, not the answer beyond round-off.',
        facts: [['Default', 'auto'], ['Read by', readers('matrix')]],
        sections: [
          { choices: [
            ['auto', 'Measures the fill of one sparse factorisation, then tries the sparse LU that keeps its pivots and takes it wherever it costs no more than the sparse or the dense LU would. Right almost always.', v === 'auto'],
            ['sparse LU, pivots kept', 'Chooses its pivots from the values once, among entries at least a tenth of the largest in their column and in an order that keeps the factor small. It then repeats the same eliminations on every later matrix, checking that each pivot is still at least a hundredth of the largest entry below it. A pivot that fails is chosen again from there on, and a matrix it cannot factor goes to the dense or the sparse LU.', v === 'refactor'],
            ['sparse LU', 'Gilbert–Peierls with partial pivoting, the pivots chosen afresh for every matrix, in the natural or the reverse Cuthill–McKee column order, whichever filled in less on a trial.', v === 'sparse'],
            ['dense LU', 'The whole n × n matrix, with partial pivoting: the cheaper one once a sparse factor fills in past about a third of it.', v === 'dense'],
          ] },
          { heading: 'On this model', text: 'The kept-pivot LU needs about 6,000 multiply-adds per factorisation against 85,000 for the dense LU, which makes a step about 30 % cheaper; measured against a run at rtol 1e-9, its errors are the same. The steps themselves are not: here a change at the level of round-off, from either LU, moves the run by several hundred steps either way.' },
          { heading: 'The Julia ports', text: 'They have no kept-pivot LU, and take that choice as their sparse LU. The Last run section says which LU a run used and how full its factor was.' },
        ],
        more: more('Solver settings: iteration matrix', 'help-matrix'),
      };
    },
    'set:jacobian': () => {
      const v = $('facJacobian').value;
      const m = state.compiled;
      return {
        kicker: 'Solver', title: 'Jacobian',
        lead: 'Where df/dy, the matrix every implicit step needs, comes from.',
        facts: [['Default', 'analytic, sparse'], ['Read by', readers('jacobian')]],
        sections: [
          { choices: [
            ['analytic, sparse', 'Derived from the equations when the text is compiled: every expression is emitted with its derivative with respect to each species it depends on, so a switch such as `ramp` contributes its true slope. Exact.', v === 'analytic'],
            ['finite differences', `Differenced, slower and less exact: the check to run when the analytic one is in doubt. The NDF differences through the analytic pattern, one evaluation of the model per group of columns that share no row${m ? ` (${m.colours} for the ${m.nspecies} species here)` : ''}. The Julia ports are then handed no pattern, and difference every column.`, v === 'numeric'],
          ] },
          { text: 'Check Jacobian, at the foot of the panel, compares the two at a few states without a run, and the Jacobian tab shows the result.' },
        ],
        more: more('The Jacobian', 'help-jacobian'),
      };
    },
    'set:kappa': () => ({
      kicker: 'Solver', title: 'Newton tolerance',
      lead: 'How closely each stage’s Newton iteration must converge, as a share of one unit of the error tolerance: the κ of DifferentialEquations.jl.',
      facts: [['Default', '1e-3'], ['DifferentialEquations.jl', '1e-2'], ['Allowed', 'above 0, below 1'], ['Read by', readers('kappa')]],
      sections: [
        { text: 'It is not a cosmetic knob. A loose tolerance leaves a stage half-solved, which corrupts the error estimate read off the stages, and the step-size controller then acts on a corrupted number: at 1e-2 that is enough in an ESDIRK’s stages. 1e-3 was measured to be both more accurate and cheaper on the standard stiff test problems.' },
        { heading: 'Not the κ of the NDF', text: 'The NDF does not read it: its Newton iteration stops once the error left is under 0.3 of rtol. The κ that the BDF formulas switch sets to zero is another thing again, the formulas’ departure from the BDF.' },
      ],
      more: more('Which settings apply: the Newton tolerance', 'help-kappa'),
    }),
    'set:maxJacAge': () => ({
      kicker: 'Solver', title: 'Jacobian reuse',
      lead: 'How many steps a Jacobian may be reused before it is formed again, however well the Newton iteration is converging; 1 forms it every step.',
      facts: [['Default', '20 steps'], ['At least', '1'], ['Read by', readers('maxJacAge')]],
      sections: [{ text: 'Reusing it is most of what makes a stiff solver cheap on a large model; reusing it too long costs Newton iterations instead. The NDF decides for itself when to form a new one. Rodas5P forms one every step: a Rosenbrock method’s Jacobian is part of the method, and a stale one changes its order, not only its speed.' }],
      more: more('Which settings apply', 'help-apply'),
    }),
    'set:belowTolRun': () => ({
      kicker: 'Solver', title: 'Steps at the floor',
      lead: 'What to do when a step at the smallest size the clock can represent fails anyway: a shorter step does not exist. 0 stops the run there and hands back what it had, which is the published rule. Above 0, that many such steps in a row are accepted, and the Last run section says in bold how many were.',
      facts: [['Default', '5'], ['The published rule', '0'], ['Read by', readers('belowTolRun')]],
      sections: [
        { text: '**This is a departure from the published method, not part of it.** Reaching the same point, a variable-order multistep code raises a tolerance-not-met error and returns, as every solver in DifferentialEquations.jl does.' },
        { heading: 'For and against', text: 'The error test is not always asking a sensible question: after a restart from an interpolated state, a species with a lifetime of femtoseconds is off its steady state by more than the tolerance, and no step size mends that; the implicit step itself does. Against it, a step known to be inaccurate is accepted. At 0 three of the built-in scenarios stop early; across all 39 the escape is used three times in total.' },
        { heading: 'For the NDF', text: 'The count covers steps whose Newton iteration will not converge at the floor as well as those that fail the error test.' },
      ],
      more: more('Solver settings: accept failing steps at the floor', 'help-floor'),
    }),
    'set:maxSteps': () => ({
      kicker: 'Solver', title: 'Step budget',
      lead: 'How many steps the solver may take before it gives up, says so, and hands back what it had integrated.',
      facts: [['Default', '2,000,000'], ['At least', '100'], ['Read by', readers('maxSteps')]],
      sections: [{ text: 'A run that reaches it has usually met something the model did not mean, rather than needing a larger budget. The count starts again after each event, where the run restarts.' }],
    }),
    'set:stagnationTol': () => ({
      kicker: 'Solver', title: 'Stall tolerance',
      lead: 'How large a Newton correction may be and still be taken once it has stopped shrinking, as a share of one unit of the tolerance, with a fresh Jacobian. 0 never takes one, and is this page’s default.',
      facts: [['Default', '0: never'], ['rtm.html', '0.5'], ['Allowed', '0 to 1'], ['Read by', readers('stagnationTol')]],
      sections: [
        { heading: 'When to raise it', text: 'Only for a model whose rates cancel so heavily that the correction cannot shrink any further: rate constants of 1e16 against concentrations of 1e-9, as rtm.html’s networks have. There the NDF otherwise rejects the step and cuts it, again and again, and a shorter step does not reduce round-off.' },
        { heading: 'Keep in mind', text: 'On a model that does not need it, it costs accuracy. On this one it made the 500-year water agree less well with SKB’s FACSIMILE result at every tolerance tried, which is why it is off here.' },
      ],
    }),
    'set:maxPoints': {
      kicker: 'Solver', title: 'Points kept',
      lead: 'How many points of the solution are kept for the charts, the table and the files. Past it the stored points are thinned as the run goes, to every second one and then every fourth, so that a long run still fits in memory. The solution itself is not affected.',
      facts: [['Default', '20,000'], ['At least', '1,000'], ['Read by', 'every method']],
      sections: [{ text: 'The two ends of the run and the state at each event are always kept, and the Last run section says when thinning happened: one in N beside the count of points. The model’s own output times are interpolated from every accepted step, not from the kept ones.' }],
      more: more('How much of a run is kept', 'help-kept'),
    },
    'set:autoAtol': () => ({
      kicker: 'Solver', title: 'Absolute tolerance follows the solution',
      lead: 'After every accepted step each species’ absolute tolerance is raised to rtol·|y| if that is larger, and never lowered again: each is judged against the largest it has ever been, rather than a floor fixed before the run.',
      facts: [['Default', 'off'], ['Read by', readers('autoAtol')]],
      sections: [
        { heading: 'For', text: 'A radical that rose to 1e-5 and has decayed to 1e-40 is otherwise still held to 1e-30, thirty-five orders below anything it ever was, and the step size pays for it.' },
        { heading: 'Against', text: 'It only ever loosens, so a species that peaked and fell is no longer controlled in its tail.' },
        { heading: 'On this model', text: 'It depends on the method. On the 500-year case it takes FBDF to about 60 % of its steps with the same answer, leaves the NDF slightly worse and doubles the work of QNDF. The Newton iteration keeps the tolerance the run started with, and what a species has reached is remembered across events.' },
      ],
      more: more('Solver settings: the absolute tolerance follows the solution', 'help-auto-atol'),
    }),
    'set:smoothEst': () => ({
      kicker: 'Solver', title: 'Smooth the error estimate',
      lead: 'Filters the error estimate through I − hJ, as Shampine proposed, so that a stiff component cannot inflate it and force a needlessly small step.',
      facts: [['Default', 'on'], ['Read by', readers('smoothEst')]],
      sections: [{ text: 'Only those three filter their estimate this way. The others do not read the setting, and it is not shown for them.' }],
    }),
    'set:clamp': () => ({
      kicker: 'Solver', title: 'Read negative concentrations as zero',
      lead: 'Every concentration in the rate laws is read as max(0, c), so a small negative excursion cannot drive a rate the wrong way. The solution itself may still dip below zero, unless the next setting stops it.',
      facts: [['Default', 'on'], ['Read by', readers('clamp')]],
      sections: [{ text: 'Not a solver setting at all: it changes the generated rate laws, so it is built into the derivative and the Jacobian every solver is handed, and applies to them all alike. Changing it compiles the model again. The Python port reads negatives as zero too.' }],
      more: more('Which settings apply: reading negatives as zero', 'help-clamp'),
    }),
    'set:nonNegative': () => {
      const port = isPort($('facMethod').value);
      return {
        kicker: 'Solver', title: 'Keep every species non-negative',
        lead: 'Keeps every species at or above zero. It is three things at once, and the two families do different amounts of it.',
        facts: [['Default', 'on'], ['Read by', readers('nonNegative')]],
        sections: [
          { choices: [
            ['NDF', 'All three: the derivative of a species at or below zero may not take it lower, a step that leaves a species negative by more than the tolerance is rejected, and what is left below zero is projected back. The Last run section counts the projections.', !port],
            ['Julia ports', 'The projection only: each accepted step is put back onto zero.', port],
          ] },
          { heading: 'Why it is on', text: 'With it every scenario of the study integrates in a second or two. A trace species that has drifted a little below zero is where the Newton iteration of a stiff solver comes to grief, because the derivative of the clamped rate law is zero on that side. The Python port ran without it and paid in tolerance and time.' },
          { heading: 'Keep in mind', text: 'An algebraic variable is never projected: its value is whatever satisfies its constraint.' },
        ],
        more: more('Solver settings: non-negative', 'help-nonneg'),
      };
    },
    'sec:run': {
      kicker: 'Section', title: 'Last run',
      lead: 'What the last run cost and how it was solved, from the solver’s own counts.',
      sections: [
        { list: [
          '**steps**: the accepted steps; **rejected**: attempts that failed, the error test or the Newton iteration, and were tried again',
          '**points**: the points of the solution kept, and **one in N** when the store was thinned (Points kept)',
          '**evaluations of f**, **Jacobians**, **LU factorisations** and **solves**: the work',
          '**accepted below tolerance**, in bold: steps at the floor taken although they failed (Steps at the floor)',
          '**projections onto zero**: species a step left negative and put back',
          '**Iteration matrix**: which LU the run used, the entries of its factor against the dense n², its ordering, and for the kept-pivot LU how often the pivots were chosen again',
          '**Algebraic start**, for a model with algebraic variables: how far the constraints moved their starting values',
          '**Output grid**: how many of the model’s output times the run reached',
          'the events: when each fired and what it changed, or that it stopped the run',
        ] },
        { text: 'A run that fails says how far it got, with its last accepted steps (the time t, the step h, the order k and the error over rtol), and the charts and the table show what was integrated before the failure.' },
      ],
      more: more('How much of a run is kept', 'help-kept'),
    },
    'pane:charts': {
      kicker: 'Tab', title: 'Charts',
      lead: 'The last run drawn four ways. The first three are the canister model’s: temperature, pressure and dose rate; water, relative humidity, oxygen and the two corrosion rates; and the amounts of the main species. The fourth draws whatever you tick.',
      facts: [['from, at first', '1e-4, in the unit of the axis']],
      sections: [
        { heading: 'The toolbar', list: [
          '**Time axis**: hours or years, log or linear, for every chart but the first, which is always in years on a linear axis',
          '**from**: the left-hand end of a log time axis, in its unit. The points before it are dropped rather than hidden, so the height of a chart is decided by what is shown; empty starts at the first point of the run. Not offered on a linear axis.',
          '**log amounts**: a log scale for the oxygen and corrosion axis of the second chart and for the amounts of the third',
          '**View in HDF5 Browser**: writes the run as an HDF5 file and opens it in the HDF5 Browser in a second tab. The file is handed across in memory: nothing is written to disk or uploaded.',
        ] },
        { heading: 'Keep in mind', text: 'An event is drawn as a dotted line, labelled with what it changed. A model that reports none of the first three charts’ quantities gets a note there instead; the fourth chart works for any model.' },
      ],
      more: more('Sending a run to the HDF5 Browser', 'help-hdf5'),
    },
    'pane:series': {
      kicker: 'Charts', title: 'Your own selection',
      lead: 'Any quantity of the last run, ticked in the list below, drawn against the time axis chosen above.',
      sections: [
        { heading: 'The list', list: [
          '**Outputs**: the `<OUTPUTS>` lines',
          '**Equations**: the `<EQUATIONS>` lines, the rate constants, the Gibbs energies and the corrosion switches among them',
          '**Reaction rates**: the reactions given a name with `rate =`',
          '**Species**: the state itself, in mol/cm³',
          '**Algebraic**: the variables of an `<ALGEBRAIC>` section, where there is one',
        ] },
        { text: 'Each name shows its unit, read off the comment on its line. What is ticked is repeated above the list, and each chip there removes its own series; **clear** unticks them all, **log y** switches the y axis, and the box filters the names and units shown.' },
        { heading: 'Keep in mind', text: 'The list offers what the last run produced, so a quantity added to the model text appears once it has been run.' },
      ],
    },
    'pane:table': () => {
      const times = (state.compiled && state.compiled.outputTimes && state.compiled.outputTimes.length) || 0;
      return {
        kicker: 'Tab', title: 'Table',
        lead: 'The last run as numbers, and the files to take it away in.',
        sections: [{ list: [
          '**Columns**: the outputs (the Excel file’s DATA sheet), the species in mol/cm³ (its STATES sheet), or both',
          `**Rows**: about 200 or 1000 rows spread evenly in log time, every step kept, or the model’s own output times${times ? `, ${times} here` : ', where it has a `<TIMES>` section'}. Those are the cubic through the accepted steps on either side and their derivatives, not a solver’s own interpolant, so every method gives the same grid.`,
          '**Download CSV**: the chosen columns at every kept step, or at the output times when those are chosen; the button says which',
          '**Download Excel**: SETTINGS, DATA and STATES sheets in the layout of the Python port, at the same rows',
          '**Download HDF5**: the file View in HDF5 Browser hands over, with the run, the case and the model text, for h5py or anything else that reads HDF5',
        ] }],
        more: more('Files', 'help-files'),
      };
    },
    'pane:model': {
      kicker: 'Tab', title: 'Model',
      lead: 'The model text itself: settings, constants, species, tables, equations, reactions, events, output times and outputs, in the sections the Help describes.',
      sections: [
        { list: [
          '**Apply changes** compiles the text. It is also compiled a moment after you stop typing, and before every run.',
          '**colour the syntax** paints comments, section headings, numbers, function names and the words that mean something where they stand: `kf` and `rate` in a reaction, `down` and `stop` in an event, `log` and `lin` in a time list. Turn it off for a very large model. Remembered between visits.',
        ] },
        { text: 'The text is checked as you type. A line you are still writing is reported quietly under the box and never selected; left alone, it becomes an error with a button that takes the caret to it. The line under the box counts what the model compiles to.' },
        { heading: 'Keep in mind', text: 'The Case settings are this text’s `<SETTINGS>` lines: a field typed in rewrites its line, and a line edited here shows in the field. The text is kept in this browser between visits.' },
      ],
      more: more('The model file', 'help-model-file'),
    },
    'pane:jacobian': () => {
      const m = state.compiled;
      return {
        kicker: 'Tab', title: 'Jacobian',
        lead: 'The pattern of df/dy the model compiles to. Rows are the species’ equations and columns the species they are differentiated with respect to; the diagonal is drawn in the accent colour, and pointing at a cell names it.',
        facts: m ? [['Size', `${m.nspecies} × ${m.nspecies}`], ['Structurally non-zero', `${m.nnz} (${(100 * m.density).toFixed(1)} %)`], ['Column groups', String(m.colours)]] : [],
        sections: [
          { text: 'Which entries can be non-zero is known before a number is computed, so the matrix is stored and factorised as a sparse one, and a finite-difference Jacobian through this pattern needs one evaluation of the model per group of columns that share no row, not one per species.' },
          { heading: 'Check Jacobian', text: 'The button at the foot of the panel compares the analytic entries with finite differences at the initial state and at three states with every species present, and lists the entries that differ by more than 0.1 %. An entry counts when its effect on the rate over the perturbation is more than 1e-9 of the rate; below that a finite difference is round-off.' },
          { text: 'After a run, the text beside the pattern says how the iteration matrix I − hJ was factorised and how full its factor was.' },
        ],
        more: more('The Jacobian', 'help-jacobian'),
      };
    },
    'pane:code': () => {
      const v = $('facCodeSelect').value;
      return {
        kicker: 'Tab', title: 'Code',
        lead: 'The JavaScript the model text is compiled to: the functions every solver calls.',
        sections: [
          { choices: [
            ['rhs', 'dy/dt, the rate of change of every species', v === 'rhs'],
            ['jac', 'the values of the sparse Jacobian, in compressed-column order over its pattern', v === 'jac'],
            ['observe', 'the equations and the outputs, for the table and the charts', v === 'observe'],
            ['events', 'the event triggers, whose crossings of zero the solver looks for', v === 'events'],
            ['init', 'the `<INITIAL>` section, evaluated once at t = 0', v === 'init'],
          ] },
          { text: 'A temporary is shared between a value and its derivatives. A long function is cut into parts, run one after another, because a browser will not optimise a function past about 60 KB of bytecode: whole, this model’s Jacobian ran about thirty times slower.' },
        ],
      };
    },
  };

  /*
    The case settings. Their rows are the model's own <SETTINGS> lines, so
    each topic is made from the line as compiled: its value, what that works
    out to, the built-in model's value and what the scenarios set it to. The
    built-in canister model's settings also get a sentence on what they do,
    read off the lines that use them -- but only while the line is still the
    built-in one, judged by its comment, so a setting of the same name in a
    model of one's own is not described as the canister's.
  */
  const CASE_NOTES = {
    DOSERI: 'The dose rate in the gas at closure. It decays as `exp(−LAMBDA·t)`, with `LAMBDA` = 7.33e-10 s⁻¹, a half-life of about 30 years, and drives every radiolysis reaction. The G-values need it in 100 eV cm⁻³ s⁻¹, which it is converted to with the density of the gas at closure.',
    STEELAREA: 'The area of steel that corrodes, in m². With the free gas volume it turns a corrosion rate in mm/y into moles of iron per cm³ of gas per second, so both corrosion rates scale with it.',
    VOLUME: 'The free gas volume of the canister, in m³. The water at closure, the corrosion and the release from failed rods are spread over it, and the amounts in mol and g that the charts show are the concentrations times it.',
    PRESSI: 'The pressure of the dry gas at closure, in atm, water vapour not included. With the temperature at t = 0 it gives the concentration of dry gas that the air and argon fractions share out. 1 atm is taken as 1.01e5 Pa, as in the FACSIMILE model.',
    PCAIR: 'The share of the dry gas that is air, taken as 20 % O₂ and 80 % N₂; the rest is argon, `PCAR`.',
    PCAR: 'The share of the dry gas that is argon. As `1 - PCAIR`, which is how the built-in model writes it, argon makes up the rest. At 0, as in 13g-fac, only the air is there, so with `PCAIR` at 0.03 the dry gas is 3 % of `PRESSI`.',
    H2OLQDI: 'All the water in the canister at closure, in grams, vapour and liquid together. What the gas cannot hold at the starting temperature is liquid; how that is modelled is `H2OPAIR`.',
    H2OPAIR: 'How liquid water is modelled.',
    H2OFINAL: 'How much water the failed rods release in all, in grams. An event stops the release when that much has been added, by setting `H2OINPUTR` to 0; with no release it has nothing to do.',
    H2OINPUTR: 'The rate at which failed rods release water into the gas, in g/day, until `H2OFINAL` grams have come out. 0 is no release.',
    TPROF: 'The canister temperature against time: the name of a `<TABLE>` of years and °C, interpolated linearly and clamped at its ends. The rate constants are evaluated at it as it changes, and so is the saturation vapour pressure of the water.',
    CORR_ON: 'Whether the steel insert corrodes.',
    RHLIM: 'The relative humidity, as a fraction (0.6 is 60 %), above which the steel corrodes at `AERCORRAT` and `ANCORRAT`; below it the rates are `AERCORRATRH` and `ANCORRATRH`. 0 is no limit: the full rates at any humidity.',
    AERCORRAT: 'The corrosion rate of the steel while oxygen remains, in mm/y, above the humidity limit: 4Fe + 2H₂O + 3O₂ = 4FeOOH, consuming oxygen and water.',
    ANCORRAT: 'The corrosion rate once the oxygen is gone, in mm/y, above the humidity limit: 3Fe + 4H₂O = Fe₃O₄ + 4H₂, consuming water and making hydrogen.',
    AERCORRATRH: 'The oxic corrosion rate below the humidity limit `RHLIM`, in mm/y, in place of `AERCORRAT`. 0 is no corrosion below the limit, and with `RHLIM` at 0 it is never used.',
    ANCORRATRH: 'The anoxic corrosion rate below the humidity limit `RHLIM`, in mm/y, in place of `ANCORRAT`. 0 is no corrosion below the limit, and with `RHLIM` at 0 it is never used.',
    RAMP_ORDER: 'The concentration, in mol/cm³, over which the oxic corrosion turns off as the oxygen runs out and the anoxic one takes over, and over which all corrosion stops as the water runs out. Each switch is about 1 well above it, about 0.37 at it and e⁻¹⁰⁰ at zero; smaller is sharper.',
    TEND: 'The length of the run, in years from closure (t = 0). The progress bar and the status line measure against it.',
  };

  /** The canister model's tables, for the choice of temperature profile. */
  const TABLE_NOTES = {
    TEMP_PWR: 'PWR fuel, from 110 °C at closure.',
    TEMP_BWR: 'BWR fuel, from 85 °C at closure.',
    TEMP_PWRLOW: 'PWR fuel with a lower starting temperature, from 70 °C.',
    VPH2O: 'The saturation vapour pressure of water against temperature: on the list because every table is, and not a profile in time.',
  };

  let builtInLines = null;
  /** The built-in model's <SETTINGS> lines: name -> { value, comment }. */
  function builtInSettings() {
    if (builtInLines) return builtInLines;
    builtInLines = new Map();
    let inSettings = false;
    for (const raw of String(FACSIMILE_DEFAULT_MODEL).split('\n')) {
      const section = /^<\s*([A-Za-z][A-Za-z ]*?)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*>$/.exec(raw.trim());
      if (section) { inSettings = section[1].trim().toUpperCase() === 'SETTINGS'; continue; }
      if (!inSettings) continue;
      const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^#]*?)\s*(?:#\s*(.*?))?\s*$/.exec(raw);
      if (m) builtInLines.set(m[1], { value: m[2].trim(), comment: (m[3] || '').trim() });
    }
    return builtInLines;
  }

  /** What a setting is called: its comment, without the unit or what follows a colon. */
  const settingTitle = (s) => String(s.comment || '').replace(/\s*\(.*$/, '').replace(/:.*$/, '').trim() || s.name;

  /** Which scenarios give a setting which value, as lines of a list. */
  function scenarioValues(name) {
    const groups = new Map();
    for (const p of FACSIMILE_PRESETS) {
      if (!Object.prototype.hasOwnProperty.call(p.settings, name)) continue;
      const v = String(p.settings[name]);
      if (!groups.has(v)) groups.set(v, []);
      groups.get(v).push(p.id);
    }
    // Named where there are few, counted where there are many. Said as
    // "scenario 12" rather than "in 12", which would read as a count.
    const total = FACSIMILE_PRESETS.length;
    return [...groups].sort((a, b) => b[1].length - a[1].length).map(([v, ids]) => {
      if (ids.length === total) return `\`${v}\` in every one`;
      if (ids.length > 8) return `\`${v}\` in ${ids.length} of the ${total}`;
      return `\`${v}\` in scenario${ids.length === 1 ? '' : 's'} ${listOf(ids)}`;
    });
  }

  /** The topic of one case setting, made from its line when the panel opens. */
  function caseTopic(name) {
    return () => {
      const m = state.compiled;
      const s = m && m.settings.find((x) => x.name === name);
      if (!s) return { kicker: 'Case settings', title: name, lead: 'The model text has no line for this setting any more.' };
      const built = builtInSettings().get(name);
      const canister = !!(built && CASE_NOTES[name] && built.comment === String(s.comment || '').trim());
      const unit = s.isTable || typeof FacsimileHDF5 === 'undefined' ? '' : FacsimileHDF5.unitFromComment(s.comment);
      const worksOut = !s.isTable && String(s.expr).trim() !== String(s.value) && Number(s.expr) !== Number(s.value);
      const v = s.isTable ? s.value : Number(s.value);
      const sections = [];
      const lead = canister ? CASE_NOTES[name] : 'A line of the `<SETTINGS>` section of the model text. Typing in the field rewrites the line; editing the line changes the field at the next compile.';
      let link = null;
      if (canister && name === 'H2OPAIR') {
        sections.push({ choices: [
          ['0', 'One species `H2O` holds all the water, and the part above the saturation concentration `H2OEQ` is liquid (the `@H2O = min(H2O, H2OEQ)` line), so the gas is saturated while any liquid is left. What every scenario sets.', v === 0],
          ['1', 'FACSIMILE’s own: a separate liquid species `H2OLIQ` and its fast pair, condensation first order in the vapour and evaporation zeroth order at `1E6·H2OEQ`, switched off once the liquid is gone. One species and two reactions more.', v === 1],
        ] }, { heading: 'Keep in mind', text: 'The two agree when the answer has converged, 65.94 g of water after 500 years of 13g at rtol 1e-8, but not before it: at rtol 1e-5 they read 65.93 and 63.00 g.' });
        link = more('Differences from the FACSIMILE original', 'help-h2opair');
      } else if (canister && name === 'CORR_ON') {
        sections.push({ choices: [
          ['1', 'The steel corrodes: with oxygen while oxygen and water remain, consuming both, and without once the oxygen is gone, consuming water and making hydrogen.', v === 1],
          ['0', 'No corrosion, as in the zero-corrosion variants.', v === 0],
        ] });
      } else if (canister && name === 'TPROF') {
        // The profiles first; the vapour-pressure table is on the list only
        // because every table is.
        const tables = (m.tableNames || []).slice().sort((a, b) => (a === 'VPH2O') - (b === 'VPH2O'));
        sections.push({ heading: 'The tables', choices: tables.map((t) => [t, TABLE_NOTES[t] || 'A table of the model.', s.value === t]) });
        link = more('The model file', 'help-model-file');
      } else if (canister && name === 'RHLIM') {
        sections.push({ heading: 'Keep in mind', text: 'The switch turns over within about 1e-7 of the humidity. It is what makes this model hard to integrate, and why the water left after 500 years is not converged at the default tolerance: small differences early decide which side of it a run comes down on.' });
        link = more('Read the table for cost, not for accuracy', 'help-converged');
      }
      const values = scenarioValues(name);
      if (values.length) sections.push({ heading: 'In the scenarios', list: values });
      return {
        kicker: 'Case settings', title: settingTitle(s), lead,
        facts: [
          ['Line', `${name} = ${s.expr}`],
          ['Unit', unit],
          ['Works out to', worksOut ? String(s.value) : ''],
          ['Built-in model (13g)', built ? built.value : ''],
        ],
        sections,
        more: link,
      };
    };
  }

  /**
   * Registers every topic, the fixed ones and one for each case setting of
   * the model now compiled, and fills the slots. Called at boot and after
   * each compile: the case settings come and go with the model text, and the
   * shared module takes its topics in one go.
   */
  function setupInfo() {
    if (typeof KvotInfo === 'undefined') return;
    const topics = Object.assign({}, TOPICS);
    for (const s of (state.compiled && state.compiled.settings) || []) topics[`case:${s.name}`] = caseTopic(s.name);
    KvotInfo.setup({ topics, onMore: () => showTab('help') });
    // A setting's panel left open after its line went away has nothing to show.
    const open = KvotInfo.current();
    if (open && !topics[open]) KvotInfo.close();
    else KvotInfo.refresh();
  }

  /** Redraws an open panel whose topic reads the controls. */
  const refreshInfo = () => { if (typeof KvotInfo !== 'undefined') KvotInfo.refresh(); };

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'fac:choosePreset': (ev, el) => {
      const p = FACSIMILE_PRESETS.find((x) => x.id === el.value);
      if (!p) { presetOptions(); return; }
      // Into the text, a line at a time: a model that has been edited keeps
      // every change but its settings.
      const { text, missing } = textWithPreset(state.text, p);
      setModelText(text);
      state.solver.rtol = String(p.solver.rtol);
      $('facRtol').value = state.solver.rtol;
      if (missing.length) {
        notifyUser(`The model text has no line for ${missing.join(', ')} in its `
          + '<SETTINGS> section, so that part of the scenario was not applied.');
      }
      compile();
    },
    'fac:settingChanged': (ev, el) => {
      const name = el.dataset.setting;
      const next = textWithSetting(state.text, name, el.value);
      if (next === null) {
        notifyUser(`There is no ${name} line in the <SETTINGS> section to change.`);
        return;
      }
      setModelText(next);
      scheduleCompile(150);
    },
    'fac:solverMore': () => toggleSolverAdvanced(),
    'fac:solverChanged': () => {
      readSolverControls();
      updateSolverOptions();
      refreshInfo();
      saveState();
      if (!state.running) scheduleCompile(150);
    },
    'fac:run': () => { run(); },
    'fac:stop': () => { stop(); },
    'fac:verify': () => { verify(); },
    'fac:loadFile': () => loadFile(),
    'fac:saveFile': () => saveFile(),
    'fac:resetModel': () => resetModel(),
    'fac:tab': (ev, el) => showTab(el.dataset.tab),
    'fac:redraw': () => drawCharts(),
    'fac:redrawCustom': () => drawCustom(),
    'fac:filterSeries': () => renderSeriesList(),
    'fac:clearSeries': () => { document.querySelectorAll('#facSeries input:checked').forEach((el) => { el.checked = false; }); drawCustom(); },
    'fac:unpickSeries': (ev, el) => {
      const input = document.querySelector(`#facSeries input[value="${CSS.escape(el.dataset.series)}"]`);
      if (input) input.checked = false;
      drawCustom();
    },
    'fac:renderTable': () => renderTable(),
    'fac:downloadCsv': () => downloadCsv(),
    'fac:downloadXlsx': () => { downloadXlsx(); },
    'fac:toHdf5': () => { viewInHdf5Browser(); },
    'fac:downloadHdf5': () => downloadHdf5(),
    'fac:applyModel': () => applyModelText(),
    'fac:modelEdited': () => {
      state.textDirty = true; state.text = $('facModelText').value;
      // Synchronously, not on the compile's timer: the textarea's own text is
      // transparent while the colouring is on, so the coloured copy is what
      // the reader is watching themselves type.
      renderHighlight();
      scheduleCompile(800);
    },
    'fac:syntaxToggle': (ev, el) => { state.syntax = !!el.checked; applySyntaxMode(); saveState(); },
    // Moving the caret changes nothing about the text, but it does change
    // whether the line the compiler objected to is the one being written.
    'fac:modelCaret': () => { if (state.compileError) renderModelInfo(); },
    'fac:gotoError': () => { if (state.compileError && state.compileError.line) markLine(state.compileError.line); },
    'fac:showCode': () => { showCode(); refreshInfo(); },
    'fac:noop': () => {},
  });

  document.documentElement.addEventListener('kvot-theme-change', () => { if (state.result) drawCharts(); drawJacobian(); });
  window.addEventListener('beforeunload', saveState);

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  loadState();
  migrateStoredText();
  $('facModelText').value = state.text;
  // scroll does not bubble, so it cannot be delegated like the rest.
  $('facModelText').addEventListener('scroll', () => {
    const pre = $('facHighlight');
    if (pre && state.syntax) { pre.scrollTop = $('facModelText').scrollTop; pre.scrollLeft = $('facModelText').scrollLeft; }
  }, { passive: true });
  applySyntaxMode();
  writeSolverControls();
  presetOptions();
  initSideResize();
  initSections();
  initSolverAdvanced();
  // The (i)s of the fixed rows now, and of the case settings once the model
  // has compiled and renderSettings has made their rows.
  setupInfo();
  initDrop();
  showTab('charts');
  compile().then(() => renderSeriesList());
})();
