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
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { Emitter } = SM.util;

  const WORKER = './resources/js/smui-worker.mjs';

  class Engine extends Emitter {
    constructor() {
      super();
      this.state = 'off';          // off, loading, ready, error
      this.text = '';
      this.versions = null;
      this.names = [];
      this.failed = [];
      this.worker = null;
      this.pending = new Map();
      this.sent = new Map();
      this.seq = 0;
      this.busy = 0;
      this.version = '';
      this.startedAt = 0;
    }

    start(version = '') {
      if (this.worker) return;
      this.version = version;
      this.state = 'loading';
      this.text = 'Starting the Python engine…';
      this.startedAt = performance.now();
      this.emit('status', this);
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
      for (const [, p] of this.pending) p.reject(new Error('stopped'));
      this.pending.clear();
      this.busy = 0;
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

    /* Send the table if the worker lacks this version of it. */
    _sync(table) {
      if (!table || this.sent.get(table.id) === table.version) return;
      const meta = table.columns.map((c) => ({
        name: c.name, dataType: c.dataType, modelingType: c.modelingType,
        levels: c.isCategorical ? table.levels(c) : null, format: c.format || null,
      }));
      const arrays = table.columns.map((c) => (c.isNumeric ? Float64Array.from(c.values) : c.values.slice()));
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
      this.state = 'error';
      this.text = text;
      this.traceback = traceback;
      this.emit('status', this);
      for (const [, p] of this.pending) p.reject(new Error(text));
      this.pending.clear();
    }
  }

  SM.engine = new Engine();
}(typeof self !== 'undefined' ? self : this));
