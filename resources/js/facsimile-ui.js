/* ==========================================================================
   FACSIMILE.HTML: THE PAGE

   Settings column, tabs, charts, table, editor. The numerical work is done by
   facsimile-worker.js in a Web Worker; when a Worker cannot be created (the
   page opened from file://) the same handler runs inline.
   ========================================================================== */
/* global KVOT, Plotly, XlsxWriter, registerActions, reportFailure, notifyUser, kvotEscapeHtml, kvotCsvCell,
          FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS, FacsimileHDF5, handleFacsimileMessage */
(function () {
  'use strict';

  const STORAGE_KEY = 'kvot-facsimile-v1';
  // Bump this whenever the entry's own contents change, as well as the stamps
  // on what it imports. A worker does not inherit the page's cache-busting, so
  // an entry whose imports changed while its own URL did not is served from
  // cache with the old import list, and the symptom is a solver that the page
  // offers and the worker has never heard of.
  const WORKER_URL = 'resources/js/facsimile-worker-entry.js?v=20260917zd';
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
      method: 'ndf', rtol: '1e-5', atol: '1e-30', atolSpecies: '', norm: 'max',
      maxOrder: 5, minOrder: 1, hmaxYears: '0', matrix: 'auto', jacobianMode: 'analytic',
      kappa: '1e-3', maxJacAge: '20', maxSteps: '2000000', belowTolRun: '5',
      autoAtol: false, smoothEst: true, clamp: true, nonNegative: true,
    },
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
        sideWidth: state.sideWidth, sections: state.sections,
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
    // What the text says, always: this panel is a view of those lines.
    const html = m.settings.map((s) => {
      const value = s.expr;
      const label = s.comment ? s.comment : s.name;
      const control = s.isTable
        ? `<select data-setting="${esc(s.name)}" data-on-change="fac:settingChanged">${m.tableNames.map((t) => `<option value="${esc(t)}"${t === value ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`
        : `<input type="text" data-setting="${esc(s.name)}" value="${esc(value)}" data-on-change="fac:settingChanged" title="${esc(`${s.name} = ${s.value}`)}">`;
      return `<div class="fac-row"><label>${esc(label)}<span class="fac-name">${esc(s.name)}</span></label>${control}</div>`;
    }).join('');
    // Rebuilding the panel takes the focus out of the field that was just
    // edited, which on Enter is the field the reader is still in.
    const focused = document.activeElement;
    const was = focused && focused.dataset ? focused.dataset.setting : null;
    box.innerHTML = html || '<p class="fac-muted">The model has no &lt;SETTINGS&gt; section.</p>';
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
    s.autoAtol = $('facAutoAtol').checked;
    s.smoothEst = $('facSmoothEst').checked;
    s.clamp = $('facClamp').checked;
    s.nonNegative = $('facNonNeg').checked;
  }
  /**
   * Which of the page's solver settings the built-in NDF and BDF read.
   *
   * Not the ones added for the ported solvers: they have no minimum order,
   * they decide for themselves how long to keep a Jacobian, their Newton
   * iteration has its own convergence test rather than a κ, and their error
   * estimate is not smoothed. Those four are genuinely not their settings,
   * rather than settings they happen to ignore.
   */
  const BUILTIN_OPTIONS = ['rtol', 'atol', 'atolSpecies', 'norm', 'maxOrder', 'hmax', 'matrix',
    'jacobian', 'belowTolRun', 'maxSteps', 'autoAtol', 'clamp', 'nonNegative'];

  /** What the reader should see a setting called, when told it is not used. */
  const OPTION_NAMES = {
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
   * not what they chose from.
   */
  function methodLabel() {
    const chosen = $('facMethod').selectedOptions[0];
    return chosen
      ? chosen.textContent.replace(/\s*[↓(].*$/, '').trim()
      : $('facMethod').value;
  }

  /** "a", "a and b", "a, b and c". */
  function listOf(items) {
    if (items.length === 1) return items[0];
    return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
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
    if (!Array.prototype.some.call(menu.options, (o) => o.value === s.method)) s.method = 'ndf';
    menu.value = s.method;
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
    $('facAutoAtol').checked = !!s.autoAtol;
    $('facSmoothEst').checked = s.smoothEst !== false;
    $('facClamp').checked = !!s.clamp;
    $('facNonNeg').checked = !!s.nonNegative;
    updateSolverOptions();
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
   * granted when the run is over.
   */
  function scheduleCompile(delay = 400) {
    if (state.running) { compileWanted = true; return; }
    clearTimeout(compileTimer);
    compileTimer = setTimeout(() => { compile().catch((e) => reportFailure('compile', e)); }, delay);
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
    el.innerHTML = `${m.nspecies} species, ${m.nreactions} reactions, ${m.equations.length} equations, ${m.outputs.length} outputs, ${m.events.length} event${m.events.length === 1 ? '' : 's'}. `
      + `Jacobian: ${m.nnz} structurally non-zero entries of ${m.nspecies * m.nspecies} (${(100 * m.density).toFixed(1)} %), ${m.colours} column groups.${warn}`;
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
    const minOrder = Math.min(s.minOrder, s.maxOrder);
    return {
      method: s.method, rtol, atol, atolSpecies, norm: s.norm, maxOrder: s.maxOrder, minOrder,
      hmaxSeconds: hmaxYears > 0 ? hmaxYears * YEAR_S : 0, matrix: s.matrix, jacobianMode: s.jacobianMode,
      kappa, maxJacAge, maxSteps, belowTolRun, autoAtol: s.autoAtol, smoothEst: s.smoothEst,
      nonNegative: s.nonNegative, tendYears,
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
    ensureWorker();
    // Where the run would happen first, because that explains the refusal
    // usefully; the stale-copy message is the fallback for a worker that is
    // missing something for a reason the placement does not account for.
    if (typeof FacsimileOdeJulia !== 'undefined' && FacsimileOdeJulia.is(method)
      && workerKind !== 'worker') {
      return `${FacsimileOdeJulia.label(method)} can run for minutes on this model, and `
        + `there is nowhere to run it but the page itself. ${INLINE_NOTE} Use NDF or BDF.`;
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
    if (!(await compile({ reveal: true }))) return;
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
        { type: 'run', text: state.text, clampNegative: state.solver.clamp, solver },
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
      state.ran = { model: state.compiled, solver, text: state.text, scenario: state.presetId || 'custom' };
      const st = reply.stats;
      setStatus(`Done in ${reply.seconds.toFixed(2)} s.`, 'ok');
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
          state.ran = { model: state.compiled, solver, text: state.text, scenario: state.presetId || 'custom' };
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
    const evs = (events || []).map((ev) => `event at t = ${fmtTime(ev.t)}: ${esc(ev.changed.join(', '))}`).join('<br>');
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
      + `.<br>Iteration matrix I − hJ: <b>${st.sparse ? 'sparse LU' : 'dense LU'}</b>` + (st.fill != null ? ` (the sparse factor has ${st.fill} entries against ${st.n * st.n} dense, ${st.ordering} ordering)` : '')
      + `; Jacobian ${st.nnz} non-zeros of ${st.n}×${st.n}.` + (evs ? `<br>${evs}` : '');
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
  function column(name) {
    const r = state.result;
    if (!r) return null;
    const k = r.observeNames.indexOf(name);
    if (k >= 0) {
      const out = new Float64Array(r.n);
      const w = r.observeNames.length;
      for (let i = 0; i < r.n; i++) out[i] = r.observed[i * w + k];
      return out;
    }
    const s = r.species.indexOf(name.replace(/^\[state\] /, ''));
    if (s >= 0) {
      const out = new Float64Array(r.n);
      const w = r.nspecies;
      for (let i = 0; i < r.n; i++) out[i] = r.states[i * w + s];
      return out;
    }
    return null;
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
    if (name.startsWith('[state] ')) return 'mol/cm³';
    const model = state.compiled;
    if (!model || typeof FacsimileHDF5 === 'undefined') return '';
    const entry = (model.outputs || []).find((o) => o.name === name)
      || (model.equations || []).find((e) => e.name === name);
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
  function scaled(col, f) { return Float64Array.from(col, (v) => v * f); }

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
      Plotly.react('chart2', traces.filter((t) => t.y.length), layout, PLOT_CONFIG);
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
      Plotly.react('chart3', traces.filter((t) => t.y.length), layout, PLOT_CONFIG);
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
  function seriesGroups() {
    const r = state.result || (state.compiled
      && { observeNames: state.compiled.observeNames, species: state.compiled.species });
    if (!r) return [];
    const model = state.compiled;
    const isEquation = new Set(((model && model.equations) || [])
      .filter((e) => !e.substitution).map((e) => e.name));
    const observed = r.observeNames || [];
    return [
      ['Outputs', observed.filter((n) => !isEquation.has(n))],
      ['Equations', observed.filter((n) => isEquation.has(n))],
      ['Species', (r.species || []).map((sp) => `[state] ${sp}`)],
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
  function rowIndices(mode) {
    const r = state.result;
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
    const cols = tableColumns();
    const rows = rowIndices($('facTableRows').value);
    const data = cols.map((c) => column(c));
    let html = '<thead><tr>' + cols.map((c) => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>';
    for (const i of rows) {
      html += '<tr>' + data.map((col) => `<td>${fmtNum(col[i])}</td>`).join('') + '</tr>';
    }
    table.innerHTML = html + '</tbody>';
    $('facTableNote').textContent = `${rows.length} of ${r.n} rows shown.`;
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
    const cols = tableColumns();
    const data = cols.map((c) => column(c));
    const lines = [['TIMS', ...cols].map(kvotCsvCell).join(',')];
    for (let i = 0; i < r.n; i++) lines.push([r.t[i], ...data.map((col) => col[i])].map((v) => kvotCsvCell(String(v))).join(','));
    downloadBlob(new Blob([lines.join('\n')], { type: 'text/csv' }), `${fileStem()}.csv`);
  }

  async function downloadXlsx() {
    const r = state.result;
    if (!r) { notifyUser('Run the model first.'); return; }
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') { notifyUser('The Excel writer did not load; use CSV instead.'); return; }
    try {
      const xlsx = new XlsxWriter(`${fileStem()}.xlsx`);
      const settings = (state.compiled ? state.compiled.settings : []).map((s) => [s.name, s.isTable ? s.value : Number(s.value), s.comment || '']);
      const s = state.solver;
      settings.push(['METHOD', s.method, 'Solver'], ['RTOL', Number(s.rtol), 'Relative tolerance'], ['ATOL', Number(s.atol), 'Absolute tolerance (mol/cm3)'],
        ['ATOLSPECIES', (s.atolSpecies || '').replace(/\s*\n\s*/g, '; ').trim(), 'Per-species absolute tolerance'],
        ['NORM', s.norm, 'Error norm'],
        ['SCENARIO', state.presetId || 'custom', 'Scenario'],
        ['REFERENCE', (FACSIMILE_PRESETS.find((x) => x.id === state.presetId) || {}).reference || '', 'Where the case is defined'],
        ['DATE', new Date().toISOString(), 'Time of simulation'], ['SIMULATIONTIME', r.seconds ?? '', 'Seconds']);
      if (r.stats) settings.push(['STEPS', r.stats.nsteps, 'Accepted steps'], ['MATRIX', r.stats.sparse ? 'sparse' : 'dense', 'Iteration matrix']);
      xlsx.writeData(settings, 'SETTINGS', { header: ['SETTING', 'VALUE', 'DESCRIPTION'] });
      const outCols = r.observeNames.map((c) => column(c));
      const dataRows = [];
      for (let i = 0; i < r.n; i++) dataRows.push([r.t[i], ...outCols.map((col) => col[i])]);
      xlsx.writeData(dataRows, 'DATA', { header: ['TIMS', ...r.observeNames] });
      const spCols = r.species.map((sp) => column(`[state] ${sp}`));
      const stateRows = [];
      for (let i = 0; i < r.n; i++) stateRows.push([r.t[i], ...spCols.map((col) => col[i])]);
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
    if (st) html += `<p>Last run: the iteration matrix I − hJ was factorised <b>${st.sparse ? 'sparsely' : 'densely'}</b>. ${st.fill != null ? `A sparse LU factor of it holds ${st.fill} entries against ${n * n} for the dense matrix (${(100 * st.fill / (n * n)).toFixed(0)} %, ${st.ordering} ordering), which is why ${st.sparse ? 'the sparse path was kept' : 'the dense factorisation was cheaper'}.` : ''}</p>`;
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

  function loadFile(ev) {
    const input = $('facFileInput');
    input.onchange = () => {
      const file = input.files && input.files[0];
      if (!file) return;
      file.text().then((text) => {
        setModelText(text);
        compile({ reveal: true });
        showTab('model');
      }).catch((e) => reportFailure('loadFile', e, { userMessage: 'The file could not be read' }));
      input.value = '';
    };
    input.click();
    void ev;
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
    state.solver = { method: 'ndf', rtol: String(p.solver.rtol), atol: '1e-30', norm: 'max', maxOrder: 5, hmaxYears: '0', matrix: 'auto', jacobianMode: 'analytic', clamp: true, nonNegative: true };
    writeSolverControls();
    compile();
  }

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
      saveState();
      if (!state.running) scheduleCompile(150);
    },
    'fac:run': () => { run(); },
    'fac:stop': () => { stop(); },
    'fac:verify': () => { verify(); },
    'fac:loadFile': (ev) => loadFile(ev),
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
    'fac:modelEdited': () => { state.textDirty = true; state.text = $('facModelText').value; scheduleCompile(800); },
    // Moving the caret changes nothing about the text, but it does change
    // whether the line the compiler objected to is the one being written.
    'fac:modelCaret': () => { if (state.compileError) renderModelInfo(); },
    'fac:gotoError': () => { if (state.compileError && state.compileError.line) markLine(state.compileError.line); },
    'fac:showCode': () => showCode(),
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
  writeSolverControls();
  presetOptions();
  initSideResize();
  initSections();
  initSolverAdvanced();
  showTab('charts');
  compile().then(() => renderSeriesList());
})();
