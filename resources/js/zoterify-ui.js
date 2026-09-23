/* ==========================================================================
   ZOTERIFY.HTML: THE PAGE

   Wiring only. Finding citations is zoterify-parse.js, matching them
   zoterify-match.js, reading the library zoterify-zotero.js and editing the
   document zoterify-docx.js. This file keeps the state, runs the analysis,
   records the choices made while reviewing, and saves.

   A choice is made for a reference -- "Smith & Jones 2020" -- and holds for
   every place the document cites it (the parser's ref.key).

   The document is read afresh from the original bytes both when analysing
   and when saving, with the same options, so the offsets the parser found
   are offsets into exactly the text the writer edits; save() checks that.

   One global: ZFPage, a window on the state for the browser test.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => kvotEscapeHtml(s);
  const STORAGE_KEY = 'kvot-zf-v2';
  const DEFAULT_WIDTH = 340;
  const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  const LEVEL_NAMES = ['lenient', 'balanced', 'strict'];

  const SQLJS = {
    js: 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.14.2/sql-wasm.min.js',
    jsIntegrity: 'sha384-ua6rbgEfbwIWlrG1MxSagm4g3MI0VYpCkQQCjt6CtFL345h8/3ttwVWpyKiRzt/9',
    wasm: 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.14.2/sql-wasm.wasm',
    wasmIntegrity: 'sha384-x0YkuPkDHnKTZcB1JO4eb6j5+eU36aka+jBA6tOKTFaTz98b9V7fPT0QgZ9qyQW2',
  };

  const newChoices = () => ({
    chosen: new Map(),     // ref key -> itemId, picked among the candidates offered
    picked: new Map(),     // ref key -> itemId, found by searching the library
    dismissed: new Set(),  // ref key: none of the candidates is right
    unlinked: new Set(),   // ref key: the automatic match is wrong
  });

  const state = {
    doc: null,        // { name, bytes, inventory }
    db: null,         // { name, bytes, walName, walBytes, sqldb, info, items, walFrames, walNote, walMode }
    pendingWal: null, // a -wal file chosen before its database
    run: null,        // the last analysis
    choices: newChoices(),
    report: null,
    lastSaved: null,
    busy: false,
    settings: {
      author: 'Zoterify', track: true, keepTracking: true, recodeOther: true, recodeZotero: false, comment: true, summary: true,
      v: 2, level: 1, yearTolerance: 1, tab: 'review', sideWidth: null, sections: {},
    },
  };

  /* ---------------------------------------------------------------------
     Settings, remembered in this browser
     --------------------------------------------------------------------- */
  function saveSettings() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.settings)); } catch (e) { /* storage unavailable */ }
  }

  function loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (!s || typeof s !== 'object') return;
      const t = state.settings;
      if (typeof s.author === 'string' && s.author.trim()) t.author = s.author.slice(0, 80);
      for (const k of ['track', 'keepTracking', 'recodeOther', 'recodeZotero']) if (typeof s[k] === 'boolean') t[k] = s[k];
      // The comment options were off by default before version 2 of these
      // settings; an "off" stored then was the old default, not a choice.
      if (s.v >= 2) for (const k of ['comment', 'summary']) if (typeof s[k] === 'boolean') t[k] = s[k];
      if ([0, 1, 2].includes(s.level)) t.level = s.level;
      if ([0, 1, 2].includes(s.yearTolerance)) t.yearTolerance = s.yearTolerance;
      if (['review', 'linked', 'all', 'refs', 'help'].includes(s.tab)) t.tab = s.tab;
      if (Number.isFinite(s.sideWidth)) t.sideWidth = s.sideWidth;
      if (s.sections && typeof s.sections === 'object') t.sections = s.sections;
    } catch (e) { /* a corrupt entry: start fresh */ }
  }

  function writeControls() {
    const t = state.settings;
    $('zfAuthor').value = t.author;
    $('zfTrack').checked = t.track;
    $('zfKeepTracking').checked = t.keepTracking;
    $('zfRecodeOther').checked = t.recodeOther;
    $('zfRecodeZotero').checked = t.recodeZotero;
    $('zfComment').checked = t.comment;
    $('zfSummaryComment').checked = t.summary;
    $('zfLevel').value = t.level;
    $('zfYearTolerance').value = t.yearTolerance;
    $('zfAuthor').disabled = !t.track && !t.comment && !t.summary;
  }

  function readControls() {
    const t = state.settings;
    t.author = $('zfAuthor').value.trim().slice(0, 80) || 'Zoterify';
    t.track = $('zfTrack').checked;
    t.keepTracking = $('zfKeepTracking').checked;
    t.recodeOther = $('zfRecodeOther').checked;
    t.recodeZotero = $('zfRecodeZotero').checked;
    t.comment = $('zfComment').checked;
    t.summary = $('zfSummaryComment').checked;
    t.level = Number($('zfLevel').value);
    t.yearTolerance = Number($('zfYearTolerance').value);
    $('zfAuthor').disabled = !t.track && !t.comment && !t.summary;
  }

  const recodeOptions = () => ({
    endnote: state.settings.recodeOther, mendeley: state.settings.recodeOther, zotero: state.settings.recodeZotero,
  });

  /* ---------------------------------------------------------------------
     Status, progress, small helpers
     --------------------------------------------------------------------- */
  function setStatus(text, tone) {
    const el = $('zfStatus');
    el.textContent = text;
    el.className = `zf-status${tone ? ` ${tone}` : ''}`;
  }

  function setProgress(fraction) {
    const track = $('zfProgressTrack');
    if (fraction === null) { track.hidden = true; return; }
    track.hidden = false;
    $('zfProgress').style.width = `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%`;
  }

  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
  const plural = (n, one, many) => `${n.toLocaleString('en')} ${n === 1 ? one : (many || `${one}s`)}`;
  const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
  const pct = (x) => `${Math.round(x * 100)}%`;

  function download(name, data, type) {
    const blob = new Blob([data], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function updateButtons() {
    $('zfAnalyse').disabled = state.busy || !state.doc || !state.db || !state.db.sqldb;
    $('zfSave').disabled = state.busy || !state.run;
    $('zfExport').disabled = state.busy || !state.run;
  }

  function loadScript(src, integrity) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.integrity = integrity;
      s.crossOrigin = 'anonymous';
      s.onload = resolve;
      s.onerror = () => reject(new Error(`${src} could not be loaded`));
      document.head.appendChild(s);
    });
  }

  let sqlPromise = null;
  function loadSql() {
    if (!sqlPromise) {
      sqlPromise = (async () => {
        if (typeof initSqlJs !== 'function') await loadScript(SQLJS.js, SQLJS.jsIntegrity);
        const res = await fetch(SQLJS.wasm, { integrity: SQLJS.wasmIntegrity, mode: 'cors', credentials: 'omit' });
        if (!res.ok) throw new Error(`the SQLite library could not be fetched (HTTP ${res.status})`);
        return initSqlJs({ wasmBinary: await res.arrayBuffer() }); // eslint-disable-line no-undef
      })().catch((e) => { sqlPromise = null; throw e; });
    }
    return sqlPromise;
  }

  /* ---------------------------------------------------------------------
     Opening the two files
     --------------------------------------------------------------------- */
  async function addFiles(files) {
    const list = Array.from(files || []);
    // The database before its -wal file, whatever order they came in.
    list.sort((a, b) => Number(/-wal$/i.test(a.name)) - Number(/-wal$/i.test(b.name)));
    for (const f of list) {
      const name = f.name.toLowerCase();
      if (/\.(docx|docm)$/.test(name)) await openDoc(f);
      else if (/-wal$/.test(name)) await openWal(f);
      else if (/\.(sqlite|sqlite3|db)$/.test(name)) await openDb(f);
      else if (/\.(doc|odt|rtf|pdf)$/.test(name)) setStatus(`${f.name}: only Word .docx documents can be read. Save it as .docx in Word first.`, 'error');
      else setStatus(`${f.name} is neither a .docx document nor an SQLite database.`, 'error');
    }
  }

  async function openDoc(file) {
    const size = kvotFileTooLarge(file);
    if (size.tooLarge) { setStatus(size.reason, 'error'); return; }
    setStatus(`Reading ${file.name}…`);
    try {
      const bytes = await file.arrayBuffer();
      const pkg = await ZFDocx.open(bytes, JSZip);
      const analysed = ZFDocx.analyse(pkg, { recode: recodeOptions() });
      state.doc = { name: file.name, bytes, inventory: ZFDocx.inventory(pkg, analysed) };
      invalidate();
      renderDocInfo();
      setStatus(state.db ? 'Press Analyse.' : 'Now open your zotero.sqlite.', 'ok');
    } catch (e) {
      setStatus(`${file.name}: ${e.message}`, 'error');
    }
    updateButtons();
  }

  async function openDb(file) {
    const size = kvotFileTooLarge(file, KVOT_FILE_SIZE_LIMITS.dataset);
    if (size.tooLarge) { setStatus(size.reason, 'error'); return; }
    if (state.db && state.db.sqldb) state.db.sqldb.close();
    state.db = { name: file.name, bytes: new Uint8Array(await file.arrayBuffer()), walName: '', walBytes: null };
    if (state.pendingWal) {
      Object.assign(state.db, state.pendingWal);
      state.pendingWal = null;
    }
    await openLibrary();
  }

  async function openWal(file) {
    const walBytes = new Uint8Array(await file.arrayBuffer());
    if (!state.db) {
      state.pendingWal = { walName: file.name, walBytes };
      setStatus(`${file.name} will be read with the database; now open zotero.sqlite.`);
      return;
    }
    Object.assign(state.db, { walName: file.name, walBytes });
    if (state.db.sqldb) state.db.sqldb.close();
    await openLibrary();
  }

  async function openLibrary() {
    const db = state.db;
    setStatus(`Opening ${db.name}…`);
    setProgress(0.1);
    try {
      const SQL = await loadSql();
      setProgress(0.4);
      await tick();
      db.walMode = db.bytes[18] === 2;
      const prep = ZFZotero.prepareDatabase(db.bytes, db.walBytes);
      db.sqldb = new SQL.Database(prep.bytes);
      db.walFrames = prep.walFrames;
      db.walNote = prep.walNote;
      db.info = ZFZotero.readInfo(db.sqldb);
      setProgress(0.7);
      await tick();
      db.items = ZFZotero.readItems(db.sqldb, db.info);
      fillScope();
      invalidate();
      renderDbInfo();
      setStatus(state.doc ? 'Press Analyse.' : 'Now open the Word document.', 'ok');
    } catch (e) {
      if (db.sqldb) { try { db.sqldb.close(); } catch (e2) { /* already gone */ } }
      db.sqldb = null;
      setStatus(`${db.name}: ${e.message}`, 'error');
      renderDbInfo();
    }
    setProgress(null);
    updateButtons();
  }

  function fillScope() {
    const sel = $('zfScope');
    const { info, items } = state.db;
    const count = (lib) => items.filter((it) => it.libraryId === lib).length;
    const parts = [`<option value="">All libraries (${items.length.toLocaleString('en')})</option>`];
    const libs = info.libraries.filter((l) => l.type === 'user' || l.type === 'group');
    if (libs.length > 1) {
      for (const l of libs) parts.push(`<option value="lib:${l.libraryID}">${esc(l.name)} (${count(l.libraryID).toLocaleString('en')})</option>`);
    }
    if (info.collections.length) {
      parts.push('<optgroup label="Collections, with their subcollections">');
      for (const c of info.collections) {
        const label = libs.length > 1 ? `${c.libraryName} / ${c.path}` : c.path;
        parts.push(`<option value="col:${c.id}">${esc(label)} (${c.itemCount})</option>`);
      }
      parts.push('</optgroup>');
    }
    sel.innerHTML = parts.join('');
    sel.disabled = false;
  }

  function scopeFromSelect() {
    const v = $('zfScope').value;
    if (v.startsWith('lib:')) return { libraryID: Number(v.slice(4)) };
    if (v.startsWith('col:')) return { collectionId: Number(v.slice(4)) };
    return {};
  }

  function renderDocInfo() {
    const box = $('zfDocInfo');
    const d = state.doc;
    if (!d) { box.hidden = true; return; }
    const inv = d.inventory;
    const k = inv.fieldsByKind;
    const bits = [plural(inv.paragraphs - inv.footnoteParagraphs, 'paragraph')];
    if (inv.footnoteParagraphs) bits.push(`${plural(inv.footnoteParagraphs, 'paragraph')} in notes`);
    const cites = [];
    if (k.zotero) cites.push(plural(k.zotero, 'Zotero citation'));
    if (k.endnote) cites.push(plural(k.endnote, 'EndNote citation'));
    if (k.mendeley) cites.push(plural(k.mendeley, 'Mendeley citation'));
    const lines = [
      `<div class="zf-file-name">${esc(d.name)}</div>`,
      `<div class="zf-file-meta">${esc(bits.join(', '))}</div>`,
      `<div class="zf-file-meta">${inv.revisions ? `${plural(inv.revisions, 'tracked change')} already in it, kept as they are.` : 'No tracked changes in it yet.'} Track Changes is ${inv.trackingOn ? 'on' : 'off'}.</div>`,
    ];
    if (cites.length) lines.push(`<div class="zf-file-meta">Already coded: ${esc(cites.join(', '))}.</div>`);
    box.innerHTML = lines.join('');
    box.hidden = false;
  }

  function renderDbInfo() {
    const box = $('zfDbInfo');
    const db = state.db;
    if (!db) { box.hidden = true; return; }
    const lines = [`<div class="zf-file-name">${esc(db.name)}${db.walName ? ` + ${esc(db.walName)}` : ''}</div>`];
    if (db.sqldb && db.items) {
      const libs = db.info.libraries.filter((l) => l.type === 'user' || l.type === 'group');
      lines.push(`<div class="zf-file-meta">${plural(db.items.length, 'citable item')} in ${esc(libs.map((l) => l.name).join(' and '))}.</div>`);
      if (db.walName) {
        lines.push(`<div class="zf-file-meta">${db.walFrames ? `${plural(db.walFrames, 'page')} of recent changes replayed from the WAL file.` : esc(`The WAL file: ${db.walNote || 'nothing to replay'}.`)}</div>`);
      } else if (db.walMode) {
        lines.push('<div class="zf-file-warn">If Zotero is running, add zotero.sqlite-wal from the same folder: without it, items added since Zotero last saved to the database are not seen.</div>');
      }
    }
    box.innerHTML = lines.join('');
    box.hidden = false;
  }

  /** New files: the old results no longer describe them. */
  function invalidate() {
    state.run = null;
    state.choices = newChoices();
    state.report = null;
    renderAll();
  }

  /* ---------------------------------------------------------------------
     Analysis
     --------------------------------------------------------------------- */
  async function analyse() {
    if (!state.doc || !state.db || !state.db.sqldb || state.busy) return;
    readControls();
    saveSettings();
    state.busy = true;
    updateButtons();
    const t0 = performance.now();
    try {
      const options = {
        recode: recodeOptions(),
        level: LEVEL_NAMES[state.settings.level],
        yearTolerance: state.settings.yearTolerance,
        scope: scopeFromSelect(),
      };
      setStatus('Reading the document…');
      setProgress(0.02);
      await tick();
      const pkg = await ZFDocx.open(state.doc.bytes, JSZip);
      const analysed = ZFDocx.analyse(pkg, { recode: options.recode });
      const inventory = ZFDocx.inventory(pkg, analysed);
      const parsed = ZFParse.parseDocument(analysed.paras);

      setStatus(`Found ${plural(parsed.refs.length, 'reference')}. Reading the library…`);
      setProgress(0.1);
      await tick();
      const library = ZFZotero.readItems(state.db.sqldb, state.db.info, options.scope);
      const matcher = ZFMatch.createMatcher(library, { level: options.level, yearTolerance: options.yearTolerance });

      setStatus(`Matching ${plural(parsed.refs.length, 'reference')} against ${plural(library.length, 'item')}…`);
      const results = [];
      for (let i = 0; i < parsed.refs.length; i++) {
        results.push(matcher.match(parsed.refs[i]));
        if (i % 25 === 24) {
          setProgress(0.15 + 0.85 * (i / parsed.refs.length));
          await tick();
        }
      }
      const kept = options.recode.zotero ? [] : inventory.existingZotero;
      const alsoCited = kept.flatMap((e) => e.items.map((it) => [it.surname, it.year])).filter(([s]) => s);
      state.run = {
        options, parsed, results, library, inventory,
        labels: locationLabels(analysed.models),
        paraTexts: analysed.paras.map((p) => p.text),
        shown: analysed.models.map((m) => m.shown),
        uncited: ZFParse.uncitedEntries(parsed, alsoCited),
        byId: new Map(library.map((it) => [it.itemId, it])),
        indexOf: new Map(parsed.refs.map((r, i) => [r, i])),
        ms: performance.now() - t0,
      };
      state.choices = newChoices();
      state.report = null;
      const c = counts();
      setStatus(`${plural(parsed.refs.length, 'reference')} in ${plural(parsed.groups.length, 'citation')}: ${c.resolved} resolved, ${c.review} to decide, ${c.missing} not found`
        + ` (${(state.run.ms / 1000).toFixed(1)} s). ${c.review || c.missing ? 'Work through “To review”, then save.' : 'Save the document.'}`,
      c.review || c.missing ? 'warn' : 'ok');
      if (state.settings.tab === 'help') state.settings.tab = 'review';
      showTab(state.settings.tab);
    } catch (e) {
      state.run = null;
      setStatus(`The analysis failed: ${e.message}`, 'error');
      reportFailure('zoterify.analyse', e);
    } finally {
      state.busy = false;
      setProgress(null);
      updateButtons();
      renderAll();
    }
  }

  /** "¶ 12", "footnote", "endnote" for every paragraph. */
  function locationLabels(models) {
    let body = 0;
    return models.map((m) => (m.story === 'body' ? `¶ ${++body}` : m.story));
  }

  /* ---------------------------------------------------------------------
     Choices
     --------------------------------------------------------------------- */

  /** The item reference i resolves to after the user's choices, or null. */
  function resolve(i) {
    const run = state.run;
    const r = run.results[i];
    const key = r.ref.key;
    const c = state.choices;
    if (c.picked.has(key)) return { item: run.byId.get(c.picked.get(key)), how: 'picked' };
    if (c.chosen.has(key)) return { item: run.byId.get(c.chosen.get(key)), how: 'chosen' };
    if (r.status === 'matched' && !c.unlinked.has(key)) return { item: r.item, how: 'matched' };
    return null;
  }

  /** Where reference i stands, for the lists. */
  function statusOf(i) {
    const r = resolve(i);
    if (r) return r.how;
    const res = state.run.results[i];
    if (state.choices.unlinked.has(res.ref.key)) return 'unlinked';
    if (state.choices.dismissed.has(res.ref.key)) return 'dismissed';
    return res.status;
  }

  const STATUS = {
    matched: ['matched', 'ok'], chosen: ['chosen', 'ok'], picked: ['picked by hand', 'ok'],
    ambiguous: ['choose', 'amb'], year: ['year differs', 'sug'], possible: ['possible', 'sug'],
    none: ['not found', 'none'], dismissed: ['none of those', 'none'], unlinked: ['unlinked', 'none'],
  };
  const TO_DECIDE = new Set(['ambiguous', 'year', 'possible']);

  /** One entry per reference key, in document order, with its count. */
  function distinct() {
    const seen = new Map();
    state.run.results.forEach((r, i) => {
      const k = r.ref.key;
      if (seen.has(k)) seen.get(k).count++;
      else seen.set(k, { i, count: 1 });
    });
    return [...seen.values()];
  }

  function counts() {
    let resolved = 0;
    let review = 0;
    let missing = 0;
    for (const { i } of distinct()) {
      const s = statusOf(i);
      if (STATUS[s][1] === 'ok') resolved++;
      else if (TO_DECIDE.has(s)) review++;
      else missing++;
    }
    return { resolved, review, missing };
  }

  /* ---------------------------------------------------------------------
     Rendering
     --------------------------------------------------------------------- */
  const multiLibrary = () => new Set(state.run.library.map((it) => it.libraryId)).size > 1;
  const libraryName = (id) => ((state.db.info.libraries.find((l) => l.libraryID === id) || {}).name || '');

  function itemLine(item) {
    if (!item) return '<span class="zf-itemline">(the item is not in the library any more)</span>';
    const names = item.authors.length ? item.authors : item.editors;
    let who = names.slice(0, 3).join('; ');
    if (names.length > 3) who += ' et al.';
    const lib = multiLibrary() ? ` · ${libraryName(item.libraryId)}` : '';
    return `<span class="zf-itemline">${esc(who || '—')} <span class="zf-year">(${esc(item.year || 'n.d.')})</span> ${esc(clip(item.title, 120))} <span class="zf-key">${esc(item.key)}${esc(lib)}</span></span>`;
  }

  const groupOf = (i) => state.run.parsed.groups[state.run.results[i].ref.group];

  function context(i) {
    const g = groupOf(i);
    const text = state.run.shown[g.para] || '';
    const a = Math.max(0, g.authorStart - 90);
    const b = Math.min(text.length, g.end + 70);
    return `<div class="zf-context">${esc((a > 0 ? '…' : '') + text.slice(a, g.authorStart))}<mark>${esc(text.slice(g.authorStart, g.end))}</mark>${esc(text.slice(g.end, b) + (b < text.length ? '…' : ''))}</div>`;
  }

  function where(i, count) {
    return `<span class="zf-where">${esc(state.run.labels[groupOf(i).para])}${count > 1 ? ` · ${count}×` : ''}</span>`;
  }

  function entryHint(ref) {
    return ref.entry ? `<div class="zf-hint"><b>Reference list:</b> ${esc(clip(ref.entry.text, 240))}</div>` : '';
  }

  // How a candidate was found when it was by a number rather than by name.
  const BY = { report: 'report number · ', designation: 'designation · ' };
  const noteHint = (r) => (r.note ? `<div class="zf-hint">${esc(r.note)}</div>` : '');

  function candidateList(i, r, note) {
    return `<ul class="zf-cands">${r.candidates.map((c) => `<li>${itemLine(c.item)}<span class="zf-conf">${BY[c.by] || (c.entryConfirmed ? 'title in list · ' : '')}${pct(c.confidence)}</span><button type="button" class="zf-btn tiny" data-on-click="zf:choose" data-row="${i}" data-item="${c.item.itemId}">Use</button></li>`).join('')}</ul>${note || ''}`;
  }

  function searchBox(i) {
    return `<div class="zf-search"><input type="search" placeholder="Search the library: author, year, title words" data-row="${i}" data-on-input="zf:search" aria-label="Search the library for this reference"></div><ul class="zf-cands" id="zfSearch${i}"></ul>`;
  }

  function reviewItem(i, count, tone, body, actions) {
    const r = state.run.results[i];
    return `<div class="zf-item ${tone}"><div class="zf-item-head"><span class="zf-cite">${esc(r.ref.label)}</span>${where(i, count)}<span class="zf-spacer"></span>${actions || ''}</div>${context(i)}${body}</div>`;
  }

  function renderReview() {
    const host = $('zfReview');
    const run = state.run;
    $('zfReviewEmpty').hidden = !!run;
    $('zfSummary').hidden = !run;
    if (!run) { host.innerHTML = ''; return; }
    const c = counts();
    $('zfSummary').innerHTML = [
      [run.parsed.refs.length, 'references cited'],
      [c.resolved, 'resolved'],
      [c.review, 'to decide'],
      [c.missing, 'not found'],
      [run.uncited.length, 'uncited entries'],
    ].map(([n, label]) => `<div class="zf-stat"><b>${n.toLocaleString('en')}</b><span>${label}</span></div>`).join('');

    const buckets = { ambiguous: [], year: [], possible: [], none: [] };
    for (const { i, count } of distinct()) {
      const s = statusOf(i);
      if (buckets[s]) buckets[s].push([i, count]);
      else if (s === 'dismissed' || s === 'unlinked') buckets.none.push([i, count]);
    }
    const none = (i) => `<button type="button" class="zf-btn tiny secondary" data-on-click="zf:dismiss" data-row="${i}">None of these</button>`;
    const out = [];
    if (buckets.ambiguous.length) {
      out.push('<h3 class="zf-group-title">Choose the item<small>more than one fits equally well</small></h3>');
      for (const [i, count] of buckets.ambiguous) {
        const r = run.results[i];
        out.push(reviewItem(i, count, 'amb', entryHint(r.ref) + noteHint(r) + candidateList(i, r), none(i)));
      }
    }
    if (buckets.year.length) {
      out.push('<h3 class="zf-group-title">The year differs<small>the authors fit an item from another year</small></h3>');
      for (const [i, count] of buckets.year) {
        const r = run.results[i];
        out.push(reviewItem(i, count, 'sug', entryHint(r.ref) + noteHint(r) + candidateList(i, r), none(i)));
      }
    }
    if (buckets.possible.length) {
      out.push('<h3 class="zf-group-title">Possible matches<small>only looser fits, of any year</small></h3>');
      for (const [i, count] of buckets.possible) {
        const r = run.results[i];
        out.push(reviewItem(i, count, 'sug', entryHint(r.ref) + noteHint(r) + candidateList(i, r) + searchBox(i), none(i)));
      }
    }
    if (buckets.none.length) {
      out.push('<h3 class="zf-group-title">Not found<small>search the library, or leave it as text</small></h3>');
      for (const [i, count] of buckets.none) {
        const r = run.results[i];
        const s = statusOf(i);
        const hints = [];
        if (s === 'unlinked') hints.push(`<div class="zf-hint">You unlinked the match: ${itemLine(r.item)} <button type="button" class="zf-btn tiny secondary" data-on-click="zf:undo" data-row="${i}">Restore</button></div>`);
        if (s === 'dismissed') hints.push(`<div class="zf-hint">None of the items offered. <button type="button" class="zf-btn tiny secondary" data-on-click="zf:undo" data-row="${i}">Undo</button></div>`);
        if (r.ref.num !== null && !r.ref.entry) hints.push('<div class="zf-hint">The reference list has no entry with this number.</div>');
        out.push(reviewItem(i, count, 'none', entryHint(r.ref) + noteHint(r) + hints.join('') + searchBox(i)));
      }
    }
    if (!out.length) out.push('<p class="zf-empty">Nothing left to decide: every reference is resolved. Save the document.</p>');
    host.innerHTML = out.join('');
  }

  function renderLinked() {
    const host = $('zfLinked');
    const run = state.run;
    $('zfLinkedEmpty').hidden = !!run;
    renderReport();
    if (!run) { host.innerHTML = ''; return; }
    const rows = [];
    for (const { i, count } of distinct()) {
      const r = resolve(i);
      if (!r) continue;
      const res = run.results[i];
      const action = r.how === 'matched'
        ? `<button type="button" class="zf-btn tiny secondary" data-on-click="zf:unlink" data-row="${i}">Unlink</button>`
        : `<button type="button" class="zf-btn tiny secondary" data-on-click="zf:undo" data-row="${i}">Undo</button>`;
      const cand = res.candidates.find((c) => r.item && c.item.itemId === r.item.itemId);
      const conf = r.how === 'picked' || !cand ? '' : `${BY[cand.by] || ''}${pct(cand.confidence)}`;
      rows.push(`<tr><td class="nowrap"><b>${esc(res.ref.label)}</b>${count > 1 ? ` <span class="zf-where">${count}×</span>` : ''}</td><td>${itemLine(r.item)}</td><td><span class="zf-status-tag ok">${esc(STATUS[r.how][0])}</span></td><td class="num">${conf}</td><td>${action}</td></tr>`);
    }
    host.innerHTML = rows.length
      ? `<table class="zf-table"><thead><tr><th>Reference</th><th>Zotero item</th><th>How</th><th>Fit</th><th></th></tr></thead><tbody>${rows.join('')}</tbody></table>`
      : '<p class="zf-empty">No reference is resolved yet.</p>';
  }

  function renderReport() {
    const host = $('zfSaveReport');
    const rep = state.report;
    if (!rep) { host.innerHTML = ''; return; }
    const n = rep.written.reduce((k, w) => k + w.group.refs.length, 0);
    const parts = [`<div class="zf-report${rep.skipped.length ? ' warn' : ''}"><h4>Saved ${esc(rep.fileName)}</h4>`
      + `${plural(n, 'reference')} written as ${plural(rep.written.length, 'Zotero citation')}${rep.track ? `, each a tracked change by “${esc(rep.author)}”` : ''}.`
      + ` Track Changes is ${rep.keepTracking ? 'on' : 'off'} in the saved document.`];
    if (rep.summarised) parts.push(' A comment at the start of the document says what was done and what was not.');
    if (rep.skipped.length) {
      const commented = rep.skipped.filter((s) => s.commented).length;
      parts.push(`<br>${plural(rep.skipped.length, 'place')} left as text${commented ? `, ${commented === rep.skipped.length ? 'each' : commented} with a Word comment saying why` : ''}:<ul>`);
      for (const s of rep.skipped.slice(0, 60)) {
        parts.push(`<li><b>${esc(clip(s.group.text, 120))}</b> <span class="zf-where">${esc(state.run.labels[s.group.para])}</span>: ${esc(s.reason)}.</li>`);
      }
      if (rep.skipped.length > 60) parts.push(`<li>and ${rep.skipped.length - 60} more.</li>`);
      parts.push('</ul>');
    }
    parts.push('</div>');
    host.innerHTML = parts.join('');
  }

  function renderAllTab() {
    const host = $('zfAll');
    const run = state.run;
    $('zfAllEmpty').hidden = !!run;
    if (!run) { host.innerHTML = ''; return; }
    const rows = run.results.map((res, i) => {
      const s = statusOf(i);
      const r = resolve(i);
      const [label, tone] = STATUS[s];
      const item = r ? r.item : (res.candidates[0] ? res.candidates[0].item : null);
      return `<tr><td class="nowrap">${esc(run.labels[groupOf(i).para])}</td><td><b>${esc(res.ref.label)}</b></td><td><span class="zf-status-tag ${tone}">${esc(label)}</span></td><td>${item ? itemLine(item) : ''}</td></tr>`;
    });
    host.innerHTML = `<table class="zf-table"><thead><tr><th>Where</th><th>Reference</th><th>State</th><th>Zotero item</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  function renderRefs() {
    const host = $('zfRefs');
    const run = state.run;
    $('zfRefsEmpty').hidden = !!run;
    if (!run) { host.innerHTML = ''; return; }
    const list = run.parsed.list;
    const out = ['<div class="zf-refs"><h3>The reference list</h3>'];
    if (!list) {
      out.push('<p>No reference list was recognised: neither a heading such as “References” or “Referenser” with entries under it, nor a long run of entries. Every paragraph was searched for citations.</p>');
    } else {
      const end = list.end === null ? 'It runs to the end of the document.' : `It ends before ${esc(run.labels[list.end])}: “${esc(clip(run.shown[list.end], 70))}”; what follows is searched for citations again.`;
      out.push(`<p>It begins at ${esc(run.labels[list.start])}: “${esc(clip(run.shown[list.start], 90))}”, with ${plural(list.entries.length, 'entry', 'entries')}. ${end} Paragraphs inside it are not searched for citations.</p>`);
    }
    out.push(`<h3>Entries nothing cites<small class="zf-where"> ${run.uncited.length}</small></h3>`);
    out.push(run.uncited.length ? `<ol class="zf-reflist">${run.uncited.map((e) => `<li>${esc(e.text)}</li>`).join('')}</ol>` : '<p>Every entry that was read is cited somewhere.</p>');
    const kept = run.options.recode.zotero ? [] : run.inventory.existingZotero;
    out.push(`<h3>Zotero citations already in the document<small class="zf-where"> ${kept.length}</small></h3>`);
    if (kept.length) {
      out.push('<p>Left as they are, and counted as cited above.</p><ul class="zf-reflist">');
      for (const e of kept.slice(0, 300)) out.push(`<li>${esc(e.items.map((it) => `${it.surname || '?'} ${it.year || ''}`.trim()).join('; ') || '(no item data)')}</li>`);
      out.push('</ul>');
    } else {
      out.push('<p>None.</p>');
    }
    out.push('</div>');
    host.innerHTML = out.join('');
  }

  function renderTabCounts() {
    const run = state.run;
    const set = (tab, n, attention) => {
      const b = document.querySelector(`.zf-tabs button[data-tab="${tab}"]`);
      const old = b.querySelector('.zf-count');
      if (old) old.remove();
      if (n === null) return;
      const span = document.createElement('span');
      span.className = `zf-count${attention ? ' attention' : ''}`;
      span.textContent = n.toLocaleString('en');
      b.appendChild(span);
    };
    if (!run) { ['review', 'linked', 'all', 'refs'].forEach((t) => set(t, null)); return; }
    const c = counts();
    set('review', c.review + c.missing, c.review + c.missing > 0);
    set('linked', c.resolved, false);
    set('all', run.results.length, false);
    set('refs', run.uncited.length, run.uncited.length > 0);
  }

  function renderAll() {
    renderReview();
    renderLinked();
    renderAllTab();
    renderRefs();
    renderTabCounts();
    updateButtons();
  }

  function showTab(name) {
    state.settings.tab = name;
    document.querySelectorAll('.zf-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.zf-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    saveSettings();
  }

  /* ---------------------------------------------------------------------
     Saving and the report
     --------------------------------------------------------------------- */
  // Why a reference is left unresolved, for the comment on its citation.
  const UNRESOLVED = {
    none: 'not found in the Zotero library',
    dismissed: 'none of the items offered was the right one',
    unlinked: 'its match was unlinked',
    ambiguous: 'several items fit, and none was chosen',
    year: 'an item from another year fits, but it was not confirmed',
    possible: 'only loose matches were found, and none was chosen',
  };
  const NOT_FOUND = new Set(['none', 'dismissed', 'unlinked']);

  /** The lines of the comment on a citation left as text. */
  function commentLines(group, reason, refused) {
    if (refused) return [`Zoterify matched this citation to the Zotero library but could not convert it: ${reason}.`];
    if (group.problem) return [`Zoterify read this as an in-text citation but left it as text: ${group.problem}.`];
    const run = state.run;
    const lines = ['Zoterify read this as an in-text citation but left it as text.'];
    const seen = new Set();
    let resolved = 0;
    group.refs.forEach((ref, k) => {
      if (group.items[k]) { resolved++; return; }
      if (seen.has(ref.key)) return;
      seen.add(ref.key);
      const i = run.indexOf.get(ref);
      const note = run.results[i].note;
      lines.push(`${ref.label}: ${UNRESOLVED[statusOf(i)] || 'not resolved'}.${note ? ` ${note}` : ''}`);
    });
    if (resolved) {
      lines.push(`${resolved === 1 ? 'The other reference in it was' : `The other ${resolved} references in it were`} matched; a citation is converted only when all its references are.`);
    }
    return lines;
  }

  /** Why each place was left as text, in words, counted. */
  function leftAsText(skipped) {
    const run = state.run;
    const count = { missing: 0, undecided: 0, problem: 0, refused: 0 };
    for (const s of skipped) {
      const g = s.group;
      if (g.problem) count.problem++;
      else if (g.items.every(Boolean)) count.refused++;
      else if (g.refs.some((ref, k) => !g.items[k] && NOT_FOUND.has(statusOf(run.indexOf.get(ref))))) count.missing++;
      else count.undecided++;
    }
    return [
      [count.missing, 'with a reference not found in the library'], [count.undecided, 'with a reference not yet decided'],
      [count.refused, 'that could not be replaced safely'], [count.problem, 'with a year that has no author'],
    ].filter(([n]) => n).map(([n, what]) => `${n.toLocaleString('en')} ${what}`).join(', ');
  }

  /** The lines of the comment at the start of the document. */
  function summaryLines(result) {
    const run = state.run;
    const s = state.settings;
    const d = new Date();
    const two = (n) => String(n).padStart(2, '0');
    const when = `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
    const scope = $('zfScope').selectedOptions[0];
    const lines = [
      `Zoterify, ${when}: this document was matched against ${state.db.name} (${scope ? scope.textContent : 'all libraries'}), with ${LEVEL_NAMES[s.level]} matching.`,
      `Found: ${plural(run.parsed.refs.length, 'reference')} in ${plural(run.parsed.groups.length, 'in-text citation')}.`,
    ];
    const n = result.written.reduce((k, w) => k + w.group.refs.length, 0);
    lines.push(`Converted: ${plural(n, 'reference')} in ${plural(result.written.length, 'Zotero citation')}${s.track ? `, each a tracked change by ${s.author}` : ''}.`);
    if (result.skipped.length) {
      lines.push(`Left as text: ${plural(result.skipped.length, 'citation')} (${leftAsText(result.skipped)})${s.comment ? '; each has a comment saying why' : ''}.`);
    } else {
      lines.push('Left as text: none.');
    }
    const kept = run.options.recode.zotero ? 0 : run.inventory.existingZotero.length;
    if (kept) lines.push(`Left as they were: ${plural(kept, 'Zotero citation')} already in the document.`);
    const list = run.parsed.list;
    if (!list) lines.push('No reference list was found, so none was checked.');
    else if (!run.uncited.length) lines.push(`Reference list: ${plural(list.entries.length, 'entry', 'entries')}, every one cited.`);
    else {
      const shown = run.uncited.slice(0, 10).map((e) => clip(e.text, 90)).join(' | ');
      lines.push(`Reference list: ${plural(list.entries.length, 'entry', 'entries')}; ${plural(run.uncited.length, 'entry is', 'entries are')} cited nowhere: ${shown}${run.uncited.length > 10 ? ' | …' : ''}`);
    }
    lines.push('Not read: text boxes, headers and footers.');
    if (s.track) lines.push('In Word, accept the tracked changes before pressing Refresh in Zotero’s tab.');
    return lines;
  }

  async function save() {
    const run = state.run;
    if (!run || state.busy) return;
    readControls();
    saveSettings();
    const s = state.settings;
    const all = run.parsed.groups.map((g) => {
      const items = g.refs.map((ref) => { const r = resolve(run.indexOf.get(ref)); return r ? r.item : null; });
      return Object.assign({}, g, { items });
    });
    // Unresolved citations go to the writer only to be commented or counted.
    const groups = s.comment || s.summary ? all : all.filter((g) => g.items.some(Boolean));
    if (!all.some((g) => g.items.some(Boolean)) && !s.comment && !s.summary) {
      setStatus('Nothing is resolved yet, so there is nothing to write.', 'warn');
      return;
    }
    state.busy = true;
    updateButtons();
    setStatus('Writing the Zotero citations…');
    setProgress(0.3);
    await tick();
    try {
      const pkg = await ZFDocx.open(state.doc.bytes, JSZip);
      const analysed = ZFDocx.analyse(pkg, { recode: run.options.recode });
      const same = analysed.paras.length === run.paraTexts.length && analysed.paras.every((p, k) => p.text === run.paraTexts[k]);
      if (!same) throw new Error('the document reads differently now than when it was analysed; press Analyse again');
      const result = await ZFDocx.writeCitations(pkg, analysed, groups, {
        track: s.track, keepTracking: s.keepTracking, author: s.author, recode: run.options.recode,
        commentText: s.comment ? commentLines : null, summaryText: s.summary ? summaryLines : null,
      });
      setProgress(0.8);
      const bytes = await ZFDocx.save(pkg);
      const fileName = `${state.doc.name.replace(/\.(docx|docm)$/i, '')}_zotero.${/\.docm$/i.test(state.doc.name) ? 'docm' : 'docx'}`;
      state.lastSaved = bytes;
      download(fileName, bytes, DOCX_TYPE);
      state.report = Object.assign(result, { fileName, track: s.track, author: s.author, keepTracking: s.keepTracking });
      const n = result.written.reduce((k, w) => k + w.group.refs.length, 0);
      const commented = result.skipped.filter((k) => k.commented).length;
      setStatus(`Saved ${fileName}: ${plural(n, 'reference')} in ${plural(result.written.length, 'Zotero citation')}`
        + `${result.skipped.length ? `; ${plural(result.skipped.length, 'place')} left as text${commented ? `, ${commented === result.skipped.length ? 'each' : commented} with a comment` : ''} (see “Resolved”)` : ''}`
        + `${result.summarised ? '; a summary comment at the start' : ''}.`
        + ' In Word, accept the changes, then press Refresh in the Zotero tab.', result.skipped.length ? 'warn' : 'ok');
      renderLinked();
    } catch (e) {
      setStatus(`Saving failed: ${e.message}`, 'error');
      reportFailure('zoterify.save', e);
    } finally {
      state.busy = false;
      setProgress(null);
      updateButtons();
    }
  }

  /** Every reference and where it stands, then the uncited entries, as CSV. */
  function exportCsv() {
    const run = state.run;
    if (!run) return;
    const itemText = (item) => (item ? `${(item.authors.length ? item.authors : item.editors).slice(0, 3).join('; ')} (${item.year || 'n.d.'}) ${item.title}` : '');
    const rows = [['where', 'citation', 'reference', 'state', 'zotero key', 'zotero item', 'reference list entry']];
    run.results.forEach((res, i) => {
      const r = resolve(i);
      const g = groupOf(i);
      rows.push([run.labels[g.para], g.text, res.ref.label, STATUS[statusOf(i)][0], r ? r.item.key : '', itemText(r ? r.item : null),
        res.ref.entry ? res.ref.entry.text : '']);
    });
    for (const e of run.uncited) rows.push([run.labels[e.para], '', '', 'uncited entry', '', '', e.text]);
    const csv = rows.map((row) => row.map(kvotCsvCell).join(',')).join('\r\n');
    download(`${state.doc.name.replace(/\.(docx|docm)$/i, '')}_zoterify.csv`, `﻿${csv}\r\n`, 'text/csv;charset=utf-8');
  }

  /* ---------------------------------------------------------------------
     The panel, the drop zone and the drag handle
     --------------------------------------------------------------------- */
  function initSideResize() {
    const handle = $('zfResize');
    const root = $('zf');
    if (state.settings.sideWidth) root.style.setProperty('--zf-side-width', `${state.settings.sideWidth}px`);
    let dragging = false;
    handle.addEventListener('pointerdown', (ev) => { dragging = true; handle.classList.add('active'); handle.setPointerCapture(ev.pointerId); });
    handle.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      const w = Math.max(260, Math.min(640, ev.clientX - root.getBoundingClientRect().left));
      state.settings.sideWidth = Math.round(w);
      root.style.setProperty('--zf-side-width', `${state.settings.sideWidth}px`);
    });
    const end = () => { if (!dragging) return; dragging = false; handle.classList.remove('active'); saveSettings(); };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('dblclick', () => {
      state.settings.sideWidth = DEFAULT_WIDTH;
      root.style.setProperty('--zf-side-width', `${DEFAULT_WIDTH}px`);
      saveSettings();
    });
  }

  function initSections() {
    document.querySelectorAll('details.zf-sec').forEach((sec) => {
      if (Object.prototype.hasOwnProperty.call(state.settings.sections, sec.id)) sec.open = !!state.settings.sections[sec.id];
      sec.addEventListener('toggle', () => { state.settings.sections[sec.id] = sec.open; saveSettings(); });
    });
  }

  function initDrop() {
    const root = $('zf');
    let depth = 0;
    root.addEventListener('dragenter', (ev) => { ev.preventDefault(); depth++; root.classList.add('dragging'); });
    root.addEventListener('dragover', (ev) => { ev.preventDefault(); });
    root.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) root.classList.remove('dragging'); });
    root.addEventListener('drop', (ev) => {
      ev.preventDefault();
      depth = 0;
      root.classList.remove('dragging');
      if (ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files.length) {
        addFiles(ev.dataTransfer.files).catch((e) => reportFailure('zoterify.drop', e, { userMessage: 'The dropped file could not be read.' }));
      }
    });
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  const rowKey = (el) => state.run.results[Number(el.dataset.row)].ref.key;

  registerActions({
    'zf:tab': (ev, el) => showTab(el.dataset.tab),
    'zf:openDoc': () => $('zfDocFile').click(),
    'zf:docChosen': async (ev, el) => { const files = Array.from(el.files || []); el.value = ''; await addFiles(files); },
    'zf:openDb': () => $('zfDbFile').click(),
    'zf:dbChosen': async (ev, el) => { const files = Array.from(el.files || []); el.value = ''; await addFiles(files); },
    'zf:optionChanged': () => {
      readControls();
      saveSettings();
      if (state.run) setStatus('The changed setting takes effect when you press Analyse again; the choices made so far are then cleared.', 'warn');
    },
    'zf:trackChanged': () => { readControls(); saveSettings(); },
    'zf:analyse': () => analyse(),
    'zf:save': () => save(),
    'zf:export': () => exportCsv(),
    'zf:choose': (ev, el) => {
      const k = rowKey(el);
      state.choices.chosen.set(k, Number(el.dataset.item));
      state.choices.dismissed.delete(k);
      renderAll();
    },
    'zf:dismiss': (ev, el) => {
      const k = rowKey(el);
      state.choices.dismissed.add(k);
      state.choices.chosen.delete(k);
      renderAll();
    },
    'zf:unlink': (ev, el) => { state.choices.unlinked.add(rowKey(el)); renderAll(); },
    'zf:undo': (ev, el) => {
      const k = rowKey(el);
      for (const m of ['chosen', 'picked']) state.choices[m].delete(k);
      for (const m of ['dismissed', 'unlinked']) state.choices[m].delete(k);
      renderAll();
    },
    'zf:search': (ev, el) => {
      const i = Number(el.dataset.row);
      const out = $(`zfSearch${i}`);
      const q = el.value.trim();
      const hits = q.length >= 2 ? ZFMatch.searchLibrary(state.run.library, q, 8) : [];
      out.innerHTML = hits.map((item) => `<li>${itemLine(item)}<span></span><button type="button" class="zf-btn tiny" data-on-click="zf:pick" data-row="${i}" data-item="${item.itemId}">Use</button></li>`).join('')
        || (q.length >= 2 ? '<li><span class="zf-hint">Nothing in the library has all of those words.</span></li>' : '');
    },
    'zf:pick': (ev, el) => {
      const k = rowKey(el);
      state.choices.picked.set(k, Number(el.dataset.item));
      state.choices.dismissed.delete(k);
      state.choices.unlinked.delete(k);
      renderAll();
    },
  });

  /* ---------------------------------------------------------------------
     Start
     --------------------------------------------------------------------- */
  loadSettings();
  writeControls();
  initSideResize();
  initSections();
  initDrop();
  showTab(state.settings.tab);
  renderAll();

  window.ZFPage = Object.freeze({ getState: () => state, addFiles, analyse, save, resolve, statusOf });
}());
