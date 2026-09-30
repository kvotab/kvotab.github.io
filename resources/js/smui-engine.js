/* ==========================================================================
   SMUI.HTML: THE ENGINE, FROM THE PAGE'S SIDE

   Starts the worker (smui-worker.mjs) as soon as the page loads, reports
   its progress, and turns calls into promises:

       const r = await SM.engine.call('distribution.continuous', { column }, table);

   A call that names a table sends the table first if the worker has not
   got this version of it. Events: 'status', 'busy', 'log' (Python's
   output) and 'progress' ({ what, done, total }, from lines a backend
   prints as 'smui:progress <what> <done> <total>'). The worker runs one call at a time. A call that
   runs away can be stopped with restart(): the worker is terminated and
   loaded again, from the browser's cache.

   A function that needs a package beyond the four (scikit-learn for the
   predictive platforms) makes the worker load it on its first call; while
   it loads, `loading` holds a line for the status button, and afterwards
   `versions` has the package too.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { Emitter } = SM.util;

  const WORKER = './resources/js/smui-worker.mjs';

  // Loading longer than this (seconds), the page says what may be wrong.
  // The first visit downloads about 40 MB from jsDelivr: a firewall, a proxy
  // or a blocker can hold that without an error, and a worker that runs out
  // of memory stops without a word, so the status alone would say
  // "Loading…" for ever.
  const SLOW_AFTER = 90;

  // Does this browser start module workers? (One that ignores the type
  // option would load the worker as a classic script, which cannot import.)
  function moduleWorkers() {
    let reads = false;
    try { new Worker('data:text/javascript,', { get type() { reads = true; return 'module'; } }).terminate(); } catch (e) { /* reads says it all */ }
    return reads;
  }

  // The file a table's CSV is in, for the notebook: the name the reports'
  // code reads (util.code_head), with no folder in it.
  const csvName = (name) => `${String(name).replace(/[/\\]/g, '_')}.csv`;

  class Engine extends Emitter {
    constructor() {
      super();
      this.state = 'off';          // off, loading, ready, error
      this.text = '';
      this.loading = '';          // a package being loaded for a call, after the start
      this.versions = null;
      this.names = [];
      this.failed = [];
      this.worker = null;
      this.pending = new Map();
      this.sent = new Map();
      this.csvSent = new Map();     // table id -> the version whose CSV the notebook's files hold
      this.restarts = 0;
      this.seq = 0;
      this.busy = 0;
      this.version = '';
      this.startedAt = 0;
      this.elapsed = 0;          // seconds since the start, while loading
      this.slow = false;         // loading longer than SLOW_AFTER
      this.lastNews = 0;         // when the worker last said anything
      this.timer = null;
    }

    /* While loading: the time it has taken, for the status line, and past
       SLOW_AFTER the flag that makes the page explain. */
    _tick() {
      if (this.state !== 'loading') { clearInterval(this.timer); this.timer = null; return; }
      const now = performance.now();
      this.elapsed = Math.round((now - this.startedAt) / 1000);
      this.quiet = Math.round((now - this.lastNews) / 1000);
      if (this.elapsed >= SLOW_AFTER) this.slow = true;
      this.emit('status', this);
    }

    start(version = '') {
      if (this.worker) return;
      this.version = version;
      this.state = 'loading';
      this.text = 'Starting the Python engine…';
      this.startedAt = this.lastNews = performance.now();
      this.elapsed = 0;
      this.slow = false;
      this.emit('status', this);
      if (typeof WebAssembly !== 'object') { this._fail('This browser runs no WebAssembly (or it is turned off), so the Python engine cannot run here. A current Chrome, Edge, Firefox or Safari runs it.'); return; }
      if (!moduleWorkers()) { this._fail('This browser cannot start the Python engine: it has no module workers. A current Chrome, Edge, Firefox (114 or later) or Safari (15 or later) runs it.'); return; }
      clearInterval(this.timer);
      this.timer = setInterval(() => this._tick(), 1000);
      let w;
      try {
        w = new Worker(`${WORKER}?v=${encodeURIComponent(version)}`, { type: 'module' });
      } catch (e) {
        this._fail(`This browser cannot run module workers (${e.message}).`);
        return;
      }
      this.worker = w;
      w.onmessage = (ev) => this._onMessage(ev.data);
      w.onerror = (ev) => { ev.preventDefault?.(); this._fail(ev.message || 'the engine could not start'); };
      w.postMessage({ type: 'init', base: new URL('./', document.baseURI).href, version });
    }

    restart() {
      if (this.worker) this.worker.terminate();
      this.worker = null;
      this.sent.clear();
      this.csvSent.clear();
      this.restarts++;
      for (const [, p] of this.pending) p.reject(new Error('stopped'));
      this.pending.clear();
      this.busy = 0;
      this.loading = '';
      this.state = 'off';
      this.start(this.version);
    }

    ready() {
      if (this.state === 'ready') return Promise.resolve(this);
      if (this.state === 'error') return Promise.reject(new Error(this.text));
      return new Promise((resolve, reject) => {
        const off = this.on('status', (e) => {
          if (e.state === 'ready') { off(); resolve(this); }
          else if (e.state === 'error') { off(); reject(new Error(e.text)); }
        });
      });
    }

    has(name) { return this.names.includes(name); }

    /* Send the table if the worker lacks this version of it. This is where
       a table goes to Python: the values the analyses see, so a missing
       value code (Column Info) arrives missing (the table keeps codes out of
       c.values already; any that got in are masked here too), and the
       levels leave the codes out. The meta carries the column properties
       for a backend that wants them (data.value_labels(), data.meta()). */
    _sync(table) {
      if (!table || this.sent.get(table.id) === table.version) return;
      const meta = table.columns.map((c) => ({
        name: c.name, dataType: c.dataType, modelingType: c.modelingType,
        levels: c.isCategorical ? table.levels(c) : null, format: c.format || null,
        missingCodes: c.missingCodes ? c.missingCodes.slice() : null,
        valueLabels: c.valueLabels && SM.table.labelPairs ? SM.table.labelPairs(c) : null,
      }));
      const arrays = table.columns.map((c) => {
        const a = c.isNumeric ? Float64Array.from(c.values) : c.values.slice();
        if (c.missingCodes && c.missingCodes.length) {
          const codes = new Set(c.missingCodes);
          for (let i = 0; i < a.length; i++) if (a[i] != null && codes.has(a[i])) a[i] = c.isNumeric ? NaN : null;
        }
        return a;
      });
      // The number arrays are fresh copies: move them instead of copying again.
      // Python keys its fitted models by the version it is given: the data
      // version, so that a column added to the table keeps them.
      this.worker.postMessage({ type: 'table', id: table.id, version: table.dataVersion ?? table.version, meta, arrays }, arrays.filter((a) => a instanceof Float64Array).map((a) => a.buffer));
      this.sent.set(table.id, table.version);
    }

    async call(fn, payload = {}, table = null) {
      await this.ready();
      if (!this.names.includes(fn)) throw new Error(`the engine has no ${fn}`);
      this._sync(table);
      const id = ++this.seq;
      const body = table ? { table: table.id, table_name: table.name, ...payload } : payload;
      this.busy++;
      this.emit('busy', this.busy);
      try {
        const json = await new Promise((resolve, reject) => {
          this.pending.set(id, { resolve, reject, fn });
          this.worker.postMessage({ type: 'call', id, fn, payload: body });
        });
        // The code in a result reads the CSV, where a missing value code is
        // the code: it gets the line that makes it missing (SM.table.codedCode).
        const out = JSON.parse(json);
        return table && SM.table.codedResult ? SM.table.codedResult(out, table) : out;
      } finally {
        this.busy = Math.max(0, this.busy - 1);
        this.emit('busy', this.busy);
      }
    }

    /* A notebook cell (smui.notebook.run_cell). The page's tables go first, as
       for a call, and each one's CSV file, as the reports' code reads it
       ("<name>.csv", written as File > Export CSV writes it), when the
       worker lacks this version of it. info: { label, fresh } (see
       notebook.py). Resolves to { outputs, tables, count }. */
    async runCell(nb, code, { tables = [], current = null, label = 'cell', fresh = false } = {}) {
      await this.ready();
      const files = [];
      for (const t of tables) {
        this._sync(t);
        if (this.csvSent.get(t.id) === t.version) continue;
        files.push({ name: csvName(t.name), text: SM.io.toCsv(t, ',') });
        this.csvSent.set(t.id, t.version);
      }
      const info = { tables: tables.map((t) => ({ id: t.id, name: t.name })), current: current ? current.id : null, label, fresh };
      const id = ++this.seq;
      this.busy++;
      this.emit('busy', this.busy);
      try {
        const json = await new Promise((resolve, reject) => {
          this.pending.set(id, { resolve, reject, fn: 'notebook' });
          this.worker.postMessage({ type: 'nbrun', id, nb, code, files, info });
        });
        return JSON.parse(json);
      } finally {
        this.busy = Math.max(0, this.busy - 1);
        this.emit('busy', this.busy);
      }
    }

    /* A call that passes the bytes of a file (an ArrayBuffer, moved to the
       worker) as the Python function's `data` argument. */
    async callBytes(fn, payload, buffer) {
      await this.ready();
      if (!this.names.includes(fn)) throw new Error(`the engine has no ${fn}`);
      const id = ++this.seq;
      this.busy++;
      this.emit('busy', this.busy);
      try {
        const json = await new Promise((resolve, reject) => {
          this.pending.set(id, { resolve, reject, fn });
          this.worker.postMessage({ type: 'callb', id, fn, payload, bytes: buffer }, [buffer]);
        });
        return JSON.parse(json);
      } finally {
        this.busy = Math.max(0, this.busy - 1);
        this.emit('busy', this.busy);
      }
    }

    _onMessage(m) {
      this.lastNews = performance.now();
      if (m.type === 'status') {
        this.text = m.text;
        this.emit('status', this);
      } else if (m.type === 'ready') {
        this.state = 'ready';
        this.versions = m.versions;
        this.names = m.names;
        this.failed = m.failed || [];
        this.loadSeconds = (performance.now() - this.startedAt) / 1000;
        this.text = `statsmodels ${m.versions.statsmodels} ready`;
        this.emit('status', this);
      } else if (m.type === 'loading') {
        this.loading = m.text;
        this.emit('status', this);
      } else if (m.type === 'loaded') {
        this.loading = '';
        if (this.versions) Object.assign(this.versions, m.versions || {});
        this.emit('status', this);
      } else if (m.type === 'fatal') {
        this._fail(m.message, m.traceback);
      } else if (m.type === 'result' || m.type === 'error') {
        const p = this.pending.get(m.id);
        if (!p) return;
        this.pending.delete(m.id);
        if (m.type === 'result') p.resolve(m.json);
        else {
          const e = new Error(m.message);
          e.traceback = m.traceback;
          e.fn = p.fn;
          p.reject(e);
        }
      } else if (m.type === 'log') {
        this.emit('log', m);
        // 'smui:progress <what> <done> <total>' lines from a long calculation
        // (Mediation's simulations) become a progress event, not console text.
        const pm = /^smui:progress\s+(\S+)\s+(\d+)\s+(\d+)/.exec(m.text || '');
        if (pm) { this.emit('progress', { what: pm[1], done: +pm[2], total: +pm[3] }); return; }
        if (m.stream === 'stderr') console.warn('[python]', m.text); else console.log('[python]', m.text);
      }
    }

    _fail(text, traceback) {
      clearInterval(this.timer);
      this.timer = null;
      this.state = 'error';
      this.text = text;
      this.traceback = traceback;
      this.emit('status', this);
      for (const [, p] of this.pending) p.reject(new Error(text));
      this.pending.clear();
    }
  }

  SM.engine = new Engine();
  SM.engine.csvName = csvName;
}(typeof self !== 'undefined' ? self : this));
