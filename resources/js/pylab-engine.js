/* ==========================================================================
   PYLAB.HTML: THE ENGINE, FROM THE PAGE'S SIDE

   Starts the worker (pylab-worker.mjs) and turns its messages into
   promises and events:

       await PL.engine.run('x = 1:5', { silent })   -> { ok, ws, cwd, format }
       await PL.engine.call('complete', text, pos)  -> what worker_api returns
       await PL.engine.fs('read', { path })         -> text (or an ArrayBuffer)

   Events: 'status' (text while loading), 'ready', 'fatal', 'busy' (true or
   false), and the messages Python sends: 'out', 'figures', 'input',
   'request', 'dbg', 'dbgwait', 'cwd', 'files', 'edit', 'clc', 'raise', 'web',
   and 'pool' (a parfor loop's progress on the parallel pool).
   Runs are queued in the worker and done one at a time; calls and file
   operations are answered at once, also while a program runs (between its
   steps).
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { Emitter } = PL;

  const WORKER = './resources/js/pylab-worker.mjs';
  const SLOW_AFTER = 90;

  function moduleWorkers() {
    let reads = false;
    try { new Worker('data:text/javascript,', { get type() { reads = true; return 'module'; } }).terminate(); } catch (e) { /* reads says it all */ }
    return reads;
  }

  class Engine extends Emitter {
    constructor() {
      super();
      this.state = 'off';
      this.text = '';
      this.worker = null;
      this.seq = 0;
      this.pending = new Map();
      this.runs = 0;
      this.info = null;
      this.versions = null;
      this.version = '';
      this.startedAt = 0;
    }

    start(version) {
      this.version = version || '';
      if (typeof WebAssembly !== 'object' || !moduleWorkers()) {
        this.state = 'error';
        this.text = 'This browser cannot run the Python engine (it needs WebAssembly and module workers).';
        this.emit('fatal', this.text);
        return;
      }
      this.state = 'loading';
      this.startedAt = performance.now();
      const w = new Worker(`${WORKER}?v=${encodeURIComponent(this.version)}`, { type: 'module' });
      this.worker = w;
      w.onmessage = (ev) => this._message(ev.data);
      w.onerror = (ev) => {
        this.state = 'error';
        this.text = `The Python engine failed to start: ${ev.message || 'unknown error'}`;
        this.emit('fatal', this.text);
      };
      const base = new URL('./', location.href).href;
      w.postMessage({ type: 'init', base, version: this.version });
      this._slowTimer = setInterval(() => {
        if (this.state !== 'loading') { clearInterval(this._slowTimer); return; }
        const s = (performance.now() - this.startedAt) / 1000;
        if (s > SLOW_AFTER) this.emit('slow', s);
      }, 5000);
    }

    restart() {
      if (this.worker) this.worker.terminate();
      for (const p of this.pending.values()) p.reject(new Error('the engine was restarted'));
      this.pending.clear();
      this.runs = 0;
      this.emit('busy', false);
      this.emit('restart');
      this.start(this.version);
    }

    _message(m) {
      switch (m.type) {
        case 'status':
          this.text = m.text;
          this.emit('status', m.text);
          break;
        case 'ready':
          this.state = 'ready';
          this.info = m.info;
          this.versions = m.versions;
          this.emit('ready', m.info, m.versions);
          break;
        case 'fatal':
          this.state = 'error';
          this.text = m.message;
          this.emit('fatal', m.message);
          break;
        case 'py':
          this.emit(m.msg.type, m.msg);
          break;
        case 'done': {
          const p = this.pending.get(m.id);
          this.pending.delete(m.id);
          this.runs = Math.max(0, this.runs - 1);
          if (!this.runs) this.emit('busy', false);
          if (p) {
            if (m.error) p.reject(new Error(m.error)); else p.resolve(m.result);
          }
          this.emit('done', m.result);
          break;
        }
        case 'answer': {
          const p = this.pending.get(m.id);
          this.pending.delete(m.id);
          if (p) { if (m.error) p.reject(new Error(m.error)); else p.resolve(m.result); }
          break;
        }
        default:
          break;
      }
    }

    _send(msg, transfer) {
      const id = ++this.seq;
      msg.id = id;
      return new Promise((resolve, reject) => {
        this.pending.set(id, { resolve, reject });
        if (!this.worker) { reject(new Error('the engine is not running')); return; }
        this.worker.postMessage(msg, transfer || []);
      });
    }

    get busy() { return this.runs > 0; }

    run(code, opts = {}) {
      this.runs += 1;
      if (this.runs === 1) this.emit('busy', true);
      return this._send({ type: 'run', code, opts });
    }

    call(fn, ...args) {
      return this._send({ type: 'call', fn, args });
    }

    fs(op, args = {}, transfer) {
      return this._send(Object.assign({ type: 'fs', op }, args), transfer);
    }

    interrupt() {
      if (this.worker) this.worker.postMessage({ type: 'interrupt' });
    }

    reply(id, value) {
      if (this.worker) this.worker.postMessage({ type: 'reply', id, value });
    }
  }

  PL.engine = new Engine();
})(window);
