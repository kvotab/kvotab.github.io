/* ==========================================================================
   ENSDF DATABASES: THE RELEASES ON THE SITE, THE ONES OPENED, NNDC'S ARCHIVE

   Where a page that reads ENSDF gets its database from. The Chart of
   Nuclides (ensdf.html) and Radionuclide Decay Chains (rdc.html) both use
   it, so a release opened on one is offered on the other.

     releases()       the releases built into the site, newest first, from
                      resources/data/ensdf/releases.js (scripts/gen-ensdf.mjs)
     builtinSource()  one of them: its summary, and its per-mass details as
                      they are asked for
     archive()        every release in NNDC's archive, from
                      resources/data/ensdf/nndc.js (scripts/gen-ensdf-archive.mjs)
     read()           files a visitor opened -- a release zip as NNDC
                      publishes it, or ENSDF text -- read in a worker, never
                      uploaded, and kept in this browser (IndexedDB) so that
                      the menu can offer them again
     IDB              the databases kept in this browser

   NNDC's server sends no CORS header, so a page cannot fetch a release from
   the archive by itself: the visitor downloads it and opens it.

   Built-in data arrive as scripts calling KVOT_ENSDF_DATA(id, part, data),
   not as JSON: a page opened from the file system may load a script but not
   fetch a file.

   One global, KVOT_ENSDF_SOURCES, besides that callback. Opening files needs
   ensdf-parse.js on the page as well, for where a worker cannot start.
   ========================================================================== */
(function () {
  'use strict';

  const DATA_DIR = './resources/data/ensdf/';
  /* A Worker does not inherit the page's cache-busting: bump this stamp
     whenever ensdf-worker.js or the scripts it imports change. */
  const WORKER_URL = './resources/js/ensdf-worker.js?v=20260923b';
  const OPEN_URL = './resources/js/ensdf-open.js?v=20260923';

  /* ---------------------------------------------------------------------
     Built-in data, delivered by <script>
     --------------------------------------------------------------------- */
  const waiting = new Map();
  window.KVOT_ENSDF_DATA = (id, part, payload) => {
    const k = `${id}|${part}`;
    const w = waiting.get(k);
    if (w) { waiting.delete(k); w.resolve(payload); }
  };

  function loadScriptData(id, part, url) {
    return new Promise((resolve, reject) => {
      const k = `${id}|${part}`;
      waiting.set(k, { resolve, reject });
      const s = document.createElement('script');
      s.src = url;
      s.async = true;
      s.onload = () => {
        s.remove();
        /* A script that loaded but never called back is not the data file. */
        if (waiting.has(k)) { waiting.delete(k); reject(new Error(`${url} did not contain the expected data`)); }
      };
      s.onerror = () => { s.remove(); waiting.delete(k); reject(new Error(`could not load ${url}`)); };
      document.head.appendChild(s);
    });
  }

  /** The releases built into the site, newest first: [{id, label, source, nuclides, datasets, newest}]. */
  const releases = () => loadScriptData('*', 'releases', `${DATA_DIR}releases.js`);

  /** NNDC's archive: {page, base, releases: [{id, label, files, parts?, missing?}]}, newest first. */
  const archive = () => loadScriptData('*', 'nndc', `${DATA_DIR}nndc.js`);

  /** A release built into the site, as a database: {key, label, kind, summary, detail(a)}. */
  function builtinSource(rel) {
    return loadScriptData(rel.id, 'summary', `${DATA_DIR}${rel.id}/summary.js`).then((summary) => ({
      key: `b:${rel.id}`, label: rel.label, kind: 'builtin', summary,
      detail: (a) => loadScriptData(rel.id, `a${a}`, `${DATA_DIR}${rel.id}/a/${String(a).padStart(3, '0')}.js`).catch(() => null),
    }));
  }

  /* ---------------------------------------------------------------------
     Opened databases: worker, or the page itself where there is none
     --------------------------------------------------------------------- */
  let worker = null;
  let workerFailed = false;
  let msgId = 0;
  const replies = new Map();

  function getWorker() {
    if (worker || workerFailed) return worker;
    try {
      worker = new Worker(WORKER_URL);
      worker.onmessage = (ev) => {
        const m = ev.data || {};
        const r = replies.get(m.id);
        if (!r) return;
        if (m.type === 'progress') { if (r.progress) r.progress(m); return; }
        replies.delete(m.id);
        if (m.type === 'error') r.reject(new Error(m.message));
        else r.resolve(m);
      };
      worker.onerror = (ev) => {
        /* A worker that cannot start (file://) fails here; fall back. */
        ev.preventDefault();
        workerFailed = true;
        worker = null;
        for (const [id, r] of replies) { replies.delete(id); r.reject(Object.assign(new Error('worker unavailable'), { retry: true })); }
      };
    } catch (e) {
      workerFailed = true;
      worker = null;
    }
    return worker;
  }

  function ask(msg, progress) {
    const w = getWorker();
    if (!w) return Promise.reject(Object.assign(new Error('worker unavailable'), { retry: true }));
    const id = ++msgId;
    return new Promise((resolve, reject) => {
      replies.set(id, { resolve, reject, progress });
      w.postMessage({ ...msg, id });
    });
  }

  /** Read files into a database, in the worker when there is one. */
  async function openFiles(files, progress) {
    try {
      const m = await ask({ type: 'open', files }, progress);
      return {
        summary: m.summary,
        detail: (a) => ask({ type: 'detail', a }).then((r) => r.detail),
      };
    } catch (e) {
      if (!e.retry) throw e;
      await ensureInlineReader();
      const res = await window.KVOT_ENSDF_OPEN.readFiles(files, progress);
      return { summary: res.summary, detail: (a) => Promise.resolve(res.details.get(a) || null) };
    }
  }

  function ensureInlineReader() {
    if (window.KVOT_ENSDF_OPEN) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = OPEN_URL;
      s.onload = resolve;
      s.onerror = () => reject(new Error('could not load ensdf-open.js'));
      document.head.appendChild(s);
    });
  }

  /* ---------------------------------------------------------------------
     Remembered databases (IndexedDB)
     --------------------------------------------------------------------- */
  const IDB = {
    db: null,
    open() {
      if (this.db) return Promise.resolve(this.db);
      return new Promise((resolve, reject) => {
        let req;
        try { req = indexedDB.open('kvot-ensdf', 1); } catch (e) { reject(e); return; }
        req.onupgradeneeded = () => req.result.createObjectStore('files', { keyPath: 'key' });
        req.onsuccess = () => { this.db = req.result; resolve(this.db); };
        req.onerror = () => reject(req.error || new Error('IndexedDB unavailable'));
      });
    },
    async tx(mode, fn) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const t = db.transaction('files', mode);
        const store = t.objectStore('files');
        const out = fn(store);
        t.oncomplete = () => resolve(out && out.result !== undefined ? out.result : out);
        t.onerror = () => reject(t.error);
        t.onabort = () => reject(t.error || new Error('aborted'));
      });
    },
    /** Every database kept: [{key, label, names, size, opened, files}]. */
    list() { return this.tx('readonly', (s) => s.getAll()); },
    put(rec) { return this.tx('readwrite', (s) => s.put(rec)); },
    remove(key) { return this.tx('readwrite', (s) => s.delete(key)); },
  };

  /**
   * Files a visitor opened, read into a database and kept in this browser
   * if it lets us.
   *
   * @param {File[]} files
   * @param {Object|null} rec - the record they were kept under, when they
   *   come back from IDB.list(); null for files just opened
   * @param {function} [progress] - called with {done, total}
   * @returns {Promise<{src: Object, key: string, stored: Array|null}>} src a
   *   database as builtinSource() gives one, its key 's:' + the record's key;
   *   for files just opened, stored is every database now kept -- or null
   *   where the browser would not keep this one, whose key is then 'o:' + key
   */
  async function read(files, rec, progress) {
    const res = await openFiles(files, progress);
    const r = res.summary.release;
    const key = rec ? rec.key : `${r.label}|${files.map((f) => `${f.name}:${f.size}`).join('|')}`;
    const src = { key: `s:${key}`, label: rec ? rec.label : r.label, kind: 'opened', summary: res.summary, detail: res.detail };
    let stored = null;
    if (!rec) {
      const size = files.reduce((t, f) => t + (f.size || 0), 0);
      try {
        await IDB.put({ key, label: r.label, names: files.map((f) => f.name), size, opened: Date.now(), files });
        stored = await IDB.list();
      } catch (e) {
        src.key = `o:${key}`;
      }
    }
    return { src, key, stored };
  }

  window.KVOT_ENSDF_SOURCES = { DATA_DIR, loadScriptData, releases, archive, builtinSource, openFiles, read, IDB };
})();
