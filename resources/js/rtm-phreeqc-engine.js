/* ==========================================================================
   PHREEQC IN THE PAGE: IPHREEQC, COMPILED TO WEBASSEMBLY

   vendors/phreeqc/phreeqc.js is the USGS's IPhreeqc, compiled from its
   source unchanged (scripts/build-phreeqc-wasm.sh); it defines one factory,
   createPhreeqc. This turns what that factory makes into the ENGINE
   rtm-phreeqc.js asks for:

     const engine = await RtmPhreeqcEngine.create(createPhreeqc);
     engine.load(databaseText);           // throws PHREEQC's own message
     const rows = engine.run(inputText);  // selected output 99, header first

   Every value comes back at full precision and without a copy: IPhreeqc's
   GetSelectedOutputValue fills a VAR -- a type at byte 0 and the value at
   byte 8, a double, a 32-bit long or a pointer to a string in wasm32 -- which
   is read where it lies and then cleared. (GetSelectedOutputValue2 would
   strncpy every string into a buffer and pad the whole buffer with zeros on
   every call.) A long input is copied into the module's memory rather than
   handed over on its stack, which is a few megabytes at most.

   ONE GLOBAL: RtmPhreeqcEngine. Runs in a page, a Worker and Node.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  root.RtmPhreeqcEngine = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Var.h: the type of a VAR, and where its value sits (measured for wasm32).
  const TT_LONG = 2;
  const TT_DOUBLE = 3;
  const TT_STRING = 4;
  const VAR_BYTES = 16;
  const VAR_VALUE = 8;

  /**
   * @param {function} createPhreeqc  the factory vendors/phreeqc/phreeqc.js defines
   * @param {object} [moduleArgs]     handed to it (Emscripten's Module settings)
   */
  async function create(createPhreeqc, moduleArgs) {
    if (typeof createPhreeqc !== 'function') throw new Error('PHREEQC is not loaded');
    const M = await createPhreeqc(moduleArgs || {});
    const id = M._CreateIPhreeqc();
    if (id < 0) throw new Error('PHREEQC could not start an instance');
    M._SetErrorStringOn(id, 1);
    const vbuf = M._malloc(VAR_BYTES);
    M._VarInit(vbuf);
    let closed = false;
    let loaded = null;

    function withString(text, fn) {
      const n = M.lengthBytesUTF8(text) + 1;
      const p = M._malloc(n);
      M.stringToUTF8(text, p, n);
      try {
        return fn(p);
      } finally {
        M._free(p);
      }
    }

    function errors(count, what) {
      const msg = M.UTF8ToString(M._GetErrorString(id)).trim();
      return new Error(msg || `PHREEQC reported ${count} error${count === 1 ? '' : 's'} in ${what}`);
    }

    function alive() {
      if (closed) throw new Error('This PHREEQC has been closed');
    }

    return {
      version: M.UTF8ToString(M._GetVersionString()),

      /** Loads a database, replacing whatever was loaded and defined before. */
      load(text) {
        alive();
        const n = withString(String(text), (p) => M._LoadDatabaseString(id, p));
        if (n) {
          loaded = null;
          throw errors(n, 'the database');
        }
        loaded = text;
      },

      /** Whether a database is loaded. */
      get ready() { return loaded !== null; },

      /**
       * What PHREEQC warned about in the last run, one message per entry --
       * an element the database does not know is a warning, not an error,
       * and its concentration is then zero.
       */
      warnings() {
        alive();
        const text = M.UTF8ToString(M._GetWarningString(id)).trim();
        return text ? text.split(/\n(?=WARNING)/).map((s) => s.trim()).filter(Boolean) : [];
      },

      /**
       * Runs PHREEQC input and returns the rows of selected output `user`
       * (99 unless said), header first; values are numbers or strings.
       */
      run(text, user) {
        alive();
        if (loaded === null) throw new Error('Load a database into PHREEQC first');
        const n = withString(String(text), (p) => M._RunString(id, p));
        if (n) throw errors(n, 'the input');
        M._SetCurrentSelectedOutputUserNumber(id, user || 99);
        const nr = M._GetSelectedOutputRowCount(id);
        const nc = M._GetSelectedOutputColumnCount(id);
        const rows = [];
        for (let r = 0; r < nr; r++) {
          const row = new Array(nc);
          for (let c = 0; c < nc; c++) {
            M._GetSelectedOutputValue(id, r, c, vbuf);
            const type = M.getValue(vbuf, 'i32');
            if (type === TT_DOUBLE) row[c] = M.getValue(vbuf + VAR_VALUE, 'double');
            else if (type === TT_LONG) row[c] = M.getValue(vbuf + VAR_VALUE, 'i32');
            else if (type === TT_STRING) row[c] = M.UTF8ToString(M.getValue(vbuf + VAR_VALUE, '*'));
            else row[c] = null;
            M._VarClear(vbuf);
          }
          rows.push(row);
        }
        return rows;
      },

      /** Hands the instance's memory back. */
      close() {
        if (closed) return;
        closed = true;
        M._VarClear(vbuf);
        M._free(vbuf);
        M._DestroyIPhreeqc(id);
      },
    };
  }

  /* ======================================================================
     The jobs the page sends
     ====================================================================== */

  /** A view's rows as columns: what the page draws and keeps. */
  function compact(view) {
    const rows = view.rows;
    const col = (f) => rows.map((r) => (r.pq ? f(r.pq) : null));
    const si = {};
    for (const p of view.phases) si[p] = col((q) => (q.phases.has(p) ? q.phases.get(p) : null));
    return {
      t: rows.map((r) => r.t), cell: rows.map((r) => r.cell), layer: rows.map((r) => r.layer),
      pH: col((q) => q.pH), mH: col((q) => q.mH), mu: col((q) => q.mu), cb: col((q) => q.cb),
      aw: col((q) => q.aw), si,
    };
  }

  /**
   * Whether rtm.html's own compiler lands where PHREEQC is: the model
   * compiled, its EQUILIBRATE run on the conditional constants alone, every
   * species against PHREEQC's molality. Null where the compiler is not loaded.
   */
  function checkModel(res) {
    const Rtm = (typeof self !== 'undefined' && self.RtmModel)
      || (typeof globalThis !== 'undefined' && globalThis.RtmModel);
    if (!Rtm) return null;
    try {
      const m = Rtm.compile(res.text);
      const back = new Map([...res.names].map(([k, v]) => [v, k]));
      // A model holding its equilibria keeps ln C and the totals: its concentrations, then.
      const y = m.toConcentrations ? m.toConcentrations(m.initialState()) : m.initialState();
      let worst = 0;
      let where = null;
      m.speciesNames.forEach((n, i) => {
        // A mineral against the amount PHREEQC left of it.
        const ref = back.has(n) ? res.molal.get(back.get(n)) : (res.amounts && res.amounts.get(n));
        if (ref === undefined) return;
        const d = Math.abs(y[i] - ref) / Math.max(Math.abs(ref), 1e-15);
        if (d > worst) { worst = d; where = n; }
      });
      const converged = (m.speciated || []).every((c) => c.converged);
      return { worst, where, converged, warnings: m.warnings };
    } catch (e) {
      return { error: e.message };
    }
  }

  /**
   * The page's requests, answered with one engine started on the first and
   * kept. Each loads its database afresh, so nothing one input defines -- a
   * SOLUTION_SPECIES in a water, say -- is still there for the next.
   *
   *   {id, type: 'load', database}
   *     -> {type: 'done', version, database, species, phases}
   *   {id, type: 'toModel', database, water, options}
   *     -> {type: 'done', text, report, warnings, check, version}
   *   {id, type: 'view', database, water, run, modelText, options}
   *     -> {type: 'progress', done, total} ..., then
   *        {type: 'done', report, phases, table, csv, version}
   *   anything failing -> {type: 'error', error}
   *
   * `database` null means the built-in one, handed in as defaults.builtin.
   */
  function handler(createPhreeqc, defaults) {
    let starting = null;
    const builtin = { name: 'phreeqc.dat', text: (defaults && defaults.builtin) || '' };
    return async function handle(msg, post) {
      const answer = (o) => post({ id: msg.id, ...o });
      try {
        if (!starting) starting = create(createPhreeqc);
        const engine = await starting;
        const database = msg.database && typeof msg.database.text === 'string' ? msg.database : builtin;
        if (!database.text) throw new Error('No database: the built-in one did not load');
        engine.load(database.text);
        const P = (typeof self !== 'undefined' && self.RtmPhreeqc) || globalThis.RtmPhreeqc;
        if (msg.type === 'load') {
          // A database just opened, read once to say now rather than later whether it can be.
          const db = P.readDatabase(database.text);
          answer({ type: 'done', version: engine.version, database: database.name,
            species: db.reaction.size, phases: db.phases.length });
          return;
        }
        if (msg.type === 'toModel') {
          const res = P.waterToModel({ engine, database, water: msg.water, ...(msg.options || {}) });
          answer({ type: 'done', text: res.text, report: res.report, warnings: engine.warnings(),
            check: checkModel(res), version: engine.version, database: database.name });
          return;
        }
        if (msg.type === 'view') {
          const view = P.viewRun({
            engine, database, run: msg.run, modelText: msg.modelText, water: msg.water,
            ...(msg.options || {}),
            onProgress: (done, total) => post({ id: msg.id, type: 'progress', done, total }),
          });
          answer({ type: 'done', report: view.report, phases: view.phases, table: compact(view),
            csv: view.csv(), version: engine.version, database: database.name });
          return;
        }
        throw new Error(`Nothing here answers a request of type "${msg.type}"`);
      } catch (e) {
        answer({ type: 'error', error: String((e && e.message) || e) });
      }
    };
  }

  return { create, handler, compact };
}));
