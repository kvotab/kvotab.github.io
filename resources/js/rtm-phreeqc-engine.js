/* ==========================================================================
   PHREEQC IN THE PAGE: IPHREEQC, COMPILED TO WEBASSEMBLY

   vendors/phreeqc/phreeqc.js is the USGS's IPhreeqc, compiled from its
   source unchanged (scripts/build-phreeqc-wasm.sh); it defines one factory,
   createPhreeqc. This turns what that factory makes into the ENGINE
   rtm-phreeqc.js asks for:

     const engine = await RtmPhreeqcEngine.create(createPhreeqc);
     engine.load(databaseText);           // throws PHREEQC's own message
     const rows = engine.run(inputText);  // selected output 99, header first
     const text = engine.printed(input);  // what PHREEQC prints of it

   Every value comes back at full precision and without a copy: IPhreeqc's
   GetSelectedOutputValue fills a VAR -- a type at byte 0 and the value at
   byte 8, a double, a 32-bit long or a pointer to a string in wasm32 -- which
   is read where it lies and then cleared. (GetSelectedOutputValue2 would
   strncpy every string into a buffer and pad the whole buffer with zeros on
   every call.) A long input is copied into the module's memory rather than
   handed over on its stack, which is a few megabytes at most.

   THE FILES AN INPUT WRITES TO READ BACK. PHREEQC reads `INCLUDE$ name` (or
   INCLUDE_FILE) as the lines of that file, and an input can write the file
   itself first: a SELECTED_OUTPUT -file whose USER_PUNCH punches PHREEQC
   input into it, or a DUMP -file -- PHREEQC's Examples 8, 20B and 21 do. An
   input that reads a file is run with the selected outputs and the dump it
   defines written to files, in a folder of the module's memory of its own
   that is emptied after the run: it reads what it wrote, and nothing a run
   before it left. PHREEQC writes and reads them itself, exactly as on a
   disk. Every other input runs as before and writes nothing.

     const text = engine.expand(input);   // each INCLUDE$ as PHREEQC read it

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
   * The logical lines of a PHREEQC input as PHREEQC reads them
   * (PHRQ_io::get_logical_line): a line ends at a newline, or at a ';' that
   * is not in a comment, a comment running from '#' to the end of its line;
   * a '\' with nothing but spaces after it on its line joins the next. Each
   * { at, end, line }: the line's characters from `at` to `end` in the text,
   * the comment and the joins taken out of `line`.
   */
  function logicalLines(text) {
    const out = [];
    const n = text.length;
    let i = 0;
    while (i < n) {
      const at = i;
      let line = '';
      let comment = false;
      for (; i < n; i++) {
        const c = text[i];
        if (c === '\n') break;
        if (comment) continue;
        if (c === '#') { comment = true; continue; }
        if (c === ';') break;
        if (c === '\\') {
          let k = i + 1;
          while (k < n && text[k] !== '\n' && /\s/.test(text[k])) k++;
          if (k < n && text[k] === '\n') { i = k; continue; }
        }
        line += c;
      }
      out.push({ at, end: i, line });
      i++;
    }
    return out;
  }

  /**
   * The INCLUDE$ (or INCLUDE_FILE) lines of an input: the first word of a
   * line, as PHREEQC takes it, starts with one of them, and the file's name
   * is the rest of the line. [{ at, end, name }], at..end the line's.
   */
  function includeLines(text) {
    if (!/include(\$|_file)/i.test(text)) return [];
    const out = [];
    for (const ln of logicalLines(String(text))) {
      const m = /^\s*(\S+)(.*)$/.exec(ln.line);
      if (!m) continue;
      const word = m[1].toLowerCase();
      if (!word.startsWith('include$') && !word.startsWith('include_file')) continue;
      const name = m[2].trim();
      if (name) out.push({ at: ln.at, end: ln.end, name });
    }
    return out;
  }

  /**
   * What an input writes files of when they are on: the numbers of its
   * SELECTED_OUTPUT blocks (1 unless numbered; under any of PHREEQC's names
   * for the keyword), and whether it has a DUMP.
   */
  function writersOf(text) {
    const selected = new Set();
    let dump = false;
    for (const ln of logicalLines(String(text))) {
      const m = /^\s*(\S+)\s*(\S*)/.exec(ln.line);
      if (!m) continue;
      const word = m[1].toLowerCase();
      if (/^select(ed)?_out(put)?$/.test(word)) {
        const k = parseInt(m[2], 10);
        selected.add(Number.isFinite(k) && k >= 0 ? k : 1);
      } else if (word === 'dump') {
        dump = true;
      }
    }
    return { selected: [...selected], dump };
  }

  /** An absolute path, the folder `cwd` the run is in: '.' and '..' taken out. */
  function resolvePath(cwd, name) {
    const parts = [];
    for (const p of `${name.startsWith('/') ? '' : cwd}/${name}`.split('/')) {
      if (!p || p === '.') continue;
      if (p === '..') parts.pop();
      else parts.push(p);
    }
    return `/${parts.join('/')}`;
  }

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
      let msg = M.UTF8ToString(M._GetErrorString(id)).trim();
      // A file to include that is not there: PHREEQC asks for its full path, which a page has none of.
      msg = msg.replace(/\**\s*Could not open include file (.*?)\.\s*\n\s*Please, write the full path to this file\.\s*\**/g,
        (m, name) => `Could not open the file ${name} the input includes (INCLUDE$): PHREEQC in the page has only the files `
          + 'an input writes itself before it reads them, with a SELECTED_OUTPUT -file or a DUMP -file; it reads no '
          + 'file from the disk.');
      return new Error(msg || `PHREEQC reported ${count} error${count === 1 ? '' : 's'} in ${what}`);
    }

    /*
      The files an input writes to read back (see the head of this file).
      `watch`, while such an input runs, records each file PHREEQC opens:
      what it reads, as it is when it is opened, and where it writes. A
      module built without the file switches runs such an input as any
      other, and PHREEQC says it cannot open the file.
    */
    const FS = M.FS && typeof M._SetSelectedOutputFileOn === 'function' && typeof M._SetDumpFileOn === 'function'
      ? M.FS : null;
    let folders = 0;
    let watch = null;
    if (FS) {
      const open = FS.open;
      FS.open = function (path, flags) {
        const stream = open.apply(this, arguments);
        if (watch && !watch.busy) {
          watch.busy = true;
          try {
            const at = resolvePath(FS.cwd(), String(typeof path === 'string' ? path : stream.path));
            const reads = typeof flags === 'string' ? !/[wa+]/.test(flags) : (flags & 3) === 0;
            if (!reads) watch.wrote.add(at);
            else if (FS.isFile(FS.stat(at).mode)) watch.read.push({ path: at, text: FS.readFile(at, { encoding: 'utf8' }) });
          } catch (e) {
            // Not a file to read: PHREEQC says what it could not.
          } finally {
            watch.busy = false;
          }
        }
        return stream;
      };
    }

    function removeTree(dir) {
      for (const name of FS.readdir(dir)) {
        if (name === '.' || name === '..') continue;
        const p = `${dir}/${name}`;
        if (FS.isDir(FS.stat(p).mode)) removeTree(p);
        else FS.unlink(p);
      }
      FS.rmdir(dir);
    }

    /**
     * PHREEQC's RunString of an input; one that reads a file (INCLUDE$) with
     * the selected outputs and the dump it defines written to files, in a
     * folder of its own emptied after it. `reads`, if given, gets each file
     * PHREEQC read, { path, text }, in the order it read them.
     * -> PHREEQC's count of errors
     */
    function runString(text, reads) {
      if (!FS || !includeLines(text).length) return withString(text, (p) => M._RunString(id, p));
      const { selected, dump } = writersOf(text);
      const files = (on) => {
        for (const n of selected) {
          M._SetCurrentSelectedOutputUserNumber(id, n);
          M._SetSelectedOutputFileOn(id, on);
        }
        if (dump) M._SetDumpFileOn(id, on);
      };
      const home = FS.cwd();
      const folder = `/phreeqc-run-${++folders}`;
      FS.mkdir(folder);
      FS.chdir(folder);
      watch = { read: [], wrote: new Set(), busy: false };
      const seen = watch;
      files(1);
      try {
        const n = withString(text, (p) => M._RunString(id, p));
        if (reads) reads.push(...seen.read);
        return n;
      } finally {
        files(0);
        watch = null;
        FS.chdir(home);
        removeTree(folder);
        // A file written outside the folder, at a path of its own.
        for (const p of seen.wrote) {
          try { FS.unlink(p); } catch (e) { /* gone with the folder */ }
        }
      }
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
        const n = runString(String(text));
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

      /**
       * Runs PHREEQC input and returns what PHREEQC prints of it, its output
       * file's text, for what it prints alone: the inverse models, which no
       * selected output row holds. The output is on for this run only.
       */
      printed(text) {
        alive();
        if (loaded === null) throw new Error('Load a database into PHREEQC first');
        if (typeof M._SetOutputStringOn !== 'function' || typeof M._GetOutputString !== 'function') {
          throw new Error('This copy of PHREEQC does not give what it prints: reload the page, with a hard reload if that does not do it');
        }
        M._SetOutputStringOn(id, 1);
        try {
          const n = runString(String(text));
          if (n) throw errors(n, 'the input');
          return M.UTF8ToString(M._GetOutputString(id));
        } finally {
          M._SetOutputStringOn(id, 0);
        }
      },

      /**
       * The input as PHREEQC reads it: each INCLUDE$ (or INCLUDE_FILE) line
       * given the lines PHREEQC read there, as the file was when PHREEQC
       * opened it -- what the input had written into it by then -- and so on
       * into what those lines include. One run of the input; one that reads
       * no file comes back as it is, without a run. `read`, if given, gets
       * each { name, text } read, in the order PHREEQC read them. Throws
       * PHREEQC's message where it fails, a file it cannot open among them.
       */
      expand(text, read) {
        alive();
        text = String(text);
        if (!includeLines(text).length) return text;
        if (loaded === null) throw new Error('Load a database into PHREEQC first');
        const reads = [];
        const n = runString(text, reads);
        if (n) throw errors(n, 'the input');
        let k = 0;
        const into = (t, cwd) => {
          let out = '';
          let from = 0;
          for (const inc of includeLines(t)) {
            const r = reads[k++];
            if (!r || r.path !== resolvePath(cwd, inc.name)) {
              throw new Error(`PHREEQC did not read ${inc.name} where the input includes it`);
            }
            if (read) read.push({ name: inc.name, text: r.text });
            out += `${t.slice(from, inc.at)}\n${into(r.text, cwd)}\n`;
            from = inc.end;
          }
          return out + t.slice(from);
        };
        // The folder the run was in: the one runString made last.
        return into(text, `/phreeqc-run-${folders}`);
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

  /*
    A BATCH: one PHREEQC input over the rows of a table. Each {name} in the
    input is the row's value in the column of that name. A row runs on a
    clean slate -- DELETE -all first, so that nothing a row before it saved
    is there for it -- and of selected output `user` the last row it gives
    is kept, by its headings, which the rows share as they come. What the
    input defines PHREEQC keeps from one run to the next -- its SELECTED_OUTPUT
    among them, which prints from the input's first calculation on once it
    is there -- so the input is run once with the first row before the rows,
    and what it gives let go: every row then runs as the rest do. A row
    PHREEQC refuses keeps the first line of what it said, and the rest go
    on. -> { head, rows: [values or null], errors: [[index, text]] }
  */
  /**
    One run of a batch again, with what PHREEQC prints of it: the input filled from the row given, on a clean slate and
    after the same warm-up as runBatch's, so that it runs as it did among the others; PHREEQC's output text, or what it
    said where it refused.
  */
  function runBatchOne(engine, { template, columns, row, user }) {
    const at = new Map((columns || []).map((c, k) => [c, k]));
    const input = String(template).replace(/\{([^{}\n]+)\}/g, (m, name) => (at.has(name) ? String(row[at.get(name)] ?? '') : m));
    const clean = 'DELETE\n -all\nEND\n';
    try { engine.run(`${clean}${input}\nEND\n`, user || 1); } catch (e) { /* said below, where it fails again */ }
    try {
      return { text: engine.printed(`${clean}${input}\nEND\n`), refused: null, input };
    } catch (e) {
      return { text: '', refused: String((e && e.message) || e), input };
    }
  }

  function runBatch(engine, { template, columns, rows, user }, onProgress) {
    const at = new Map((columns || []).map((c, k) => [c, k]));
    const head = [];
    const seen = new Map();
    const out = [];
    const errors = [];
    let last = Date.now();
    const fill = (row) => String(template).replace(/\{([^{}\n]+)\}/g, (m, name) => (at.has(name) ? String(row[at.get(name)] ?? '') : m));
    const clean = 'DELETE\n -all\nEND\n';
    if (rows && rows.length) {
      try { engine.run(`${clean}${fill(rows[0])}\nEND\n`, user || 1); } catch (e) { /* said when the row itself runs */ }
    }
    (rows || []).forEach((row, i) => {
      const text = fill(row);
      try {
        const got = engine.run(`${clean}${text}\nEND\n`, user || 1);
        if (got.length < 2) throw new Error(`selected output ${user || 1} has no row: the input asks PHREEQC for nothing it prints there`);
        const rec = [];
        got[0].forEach((name, k) => {
          const key = String(name);
          if (!seen.has(key)) { seen.set(key, head.length); head.push(key); }
          rec[seen.get(key)] = got[got.length - 1][k];
        });
        out.push(rec);
      } catch (e) {
        out.push(null);
        const said = String((e && e.message) || e).split('\n').map((l) => l.trim()).find(Boolean);
        errors.push([i, said || 'PHREEQC gave no reason']);
      }
      const now = Date.now();
      if (onProgress && now - last > 200) { last = now; onProgress(i + 1, rows.length); }
    });
    return { head, rows: out.map((r) => (r ? Array.from({ length: head.length }, (_, k) => (r[k] === undefined ? null : r[k])) : null)), errors };
  }

  /**
   * The page's requests, answered with one engine started on the first and
   * kept. Each loads its database afresh, so nothing one input defines -- a
   * SOLUTION_SPECIES in a water, say -- is still there for the next.
   *
   *   {id, type: 'load', database}
   *     -> {type: 'done', version, database, species, phases}
   *   {id, type: 'toModel', database, water, options}
   *     -> {type: 'done', text, report, warnings, check, version, beside}
   *     options.beside: PHREEQC's own TRANSPORT of the water too, its cells
   *     under <DATA> at the text's end; beside {tables, columns, rows, cells,
   *     times, seconds}, else null
   *   {id, type: 'view', database, water, run, modelText, options}
   *     -> {type: 'progress', done, total} ..., then
   *        {type: 'done', report, phases, table, csv, version}
   *   {id, type: 'inverse', database, water, run, modelText, options: {only, inverse, ...}}
   *     -> {type: 'done', inverse, version, database}
   *   {id, type: 'listing', database, water, run, modelText, options: {only: [one water]}}
   *     -> {type: 'done', species, phases, mu, pH, aw, tc, pe, percent, counted, skipped, unmapped, version, database}
   *   {id, type: 'batch', database, template, columns, rows, user}
   *     -> {type: 'progress', done, total} ..., then {type: 'done', head, rows, errors, version, database}
   *   {id, type: 'batchOne', database, template, columns, row, user}
   *     -> {type: 'done', text, refused, input, version, database}
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
        // The input as PHREEQC reads it, read once for the job: each INCLUDE$ of a file it writes itself, expanded.
        if (msg.water && msg.type !== 'load') msg = { ...msg, water: P.readBack({ engine, water: msg.water }).water };
        if (msg.type === 'load') {
          // A database just opened, read once to say now rather than later whether it can be.
          const db = P.readDatabase(database.text);
          answer({ type: 'done', version: engine.version, database: database.name,
            species: db.reaction.size, phases: db.phases.length });
          return;
        }
        if (msg.type === 'toModel') {
          const res = P.waterToModel({ engine, database, water: msg.water, ...(msg.options || {}) });
          // With options.beside, PHREEQC's own TRANSPORT of the input too, its cells under <DATA> at the model's end.
          let beside = null;
          if (msg.options && msg.options.beside && res.report && res.report.transport) {
            const warnings = engine.warnings();
            beside = P.transportBeside({ engine, database, water: msg.water, res });
            res.text = beside.modelText;
            beside = { ...beside, text: undefined, modelText: undefined, warnings };
          }
          // With options.besidePath, PHREEQC's own steps along the path the model runs, under <DATA> at its end.
          let besidePath = null;
          if (msg.options && msg.options.besidePath && res.report && res.report.path) {
            const warnings = engine.warnings();
            besidePath = P.pathBeside({ engine, database, water: msg.water, res });
            res.text = besidePath.modelText;
            besidePath = { ...besidePath, text: undefined, modelText: undefined, warnings };
          }
          const said = beside || besidePath;
          answer({ type: 'done', text: res.text, report: res.report, warnings: said ? said.warnings : engine.warnings(),
            check: checkModel(res), version: engine.version, database: database.name, beside, besidePath });
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
        if (msg.type === 'listing') {
          // One water of a run as PHREEQC speciates it, set beside the model's own listing: each species with its
          // molality and log gamma, each phase's SI, the water's; each under PHREEQC's name and the page's for it.
          const view = P.viewRun({
            engine, database, run: msg.run, modelText: msg.modelText, water: msg.water, ...(msg.options || {}), listing: true,
          });
          const r = view.rows[0];
          if (!r || !r.pq) throw new Error(`PHREEQC could not calculate the water: ${(r && r.error) || 'no reason given'}`);
          const q = r.pq;
          answer({ type: 'done', version: engine.version, database: database.name,
            species: [...q.species].map(([n, v]) => [n, P.rtmName(n), v[0], v[1]]),
            phases: [...q.phases].map(([n, si]) => [n, P.rtmName(n), si]),
            mu: q.mu, pH: q.pH, aw: q.aw, tc: q.tc, pe: q.pe, percent: q.percent,
            counted: view.counted, skipped: view.skipped, unmapped: view.unmapped });
          return;
        }
        if (msg.type === 'batch') {
          const res = runBatch(engine, msg, (done, total) => post({ id: msg.id, type: 'progress', done, total }));
          answer({ type: 'done', ...res, version: engine.version, database: database.name });
          return;
        }
        if (msg.type === 'batchOne') {
          answer({ type: 'done', ...runBatchOne(engine, msg), version: engine.version, database: database.name });
          return;
        }
        if (msg.type === 'inverse') {
          const view = P.viewRun({
            engine, database, run: msg.run, modelText: msg.modelText, water: msg.water, ...(msg.options || {}),
          });
          answer({ type: 'done', inverse: view.inverse, version: engine.version, database: database.name });
          return;
        }
        throw new Error(`Nothing here answers a request of type "${msg.type}"`);
      } catch (e) {
        answer({ type: 'error', error: String((e && e.message) || e) });
      }
    };
  }

  return { create, handler, compact, runBatch, runBatchOne, includeLines };
}));
