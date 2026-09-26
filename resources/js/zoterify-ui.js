/* ==========================================================================
   ZOTERIFY.HTML: THE PAGE

   Wiring only. Finding citations is zoterify-parse.js, matching them
   zoterify-match.js, reading the library zoterify-zotero.js and editing the
   document zoterify-docx.js. This file keeps the state, runs the analysis,
   records the choices made while reviewing, and saves. It also holds what
   the (i) beside each section, setting and tab says (TOPICS, shown by
   kvot-info.js).

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
      names: '', boldNames: true,
      v: 2, level: 1, yearTolerance: 1, tab: 'review', sideWidth: null, sections: {},
    },
  };
  const NAMES_MAX = 50000; // characters of the list of abbreviated names

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
      for (const k of ['track', 'keepTracking', 'recodeOther', 'recodeZotero', 'boldNames']) if (typeof s[k] === 'boolean') t[k] = s[k];
      if (typeof s.names === 'string') t.names = s.names.slice(0, NAMES_MAX);
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
    $('zfNames').value = t.names;
    $('zfBoldNames').checked = t.boldNames;
    $('zfLevel').value = t.level;
    $('zfYearTolerance').value = t.yearTolerance;
    $('zfAuthor').disabled = !t.track && !t.comment && !t.summary;
    renderNames();
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
    t.names = $('zfNames').value.slice(0, NAMES_MAX);
    t.boldNames = $('zfBoldNames').checked;
    t.level = Number($('zfLevel').value);
    t.yearTolerance = Number($('zfYearTolerance').value);
    $('zfAuthor').disabled = !t.track && !t.comment && !t.summary;
  }

  const recodeOptions = () => ({
    endnote: state.settings.recodeOther, mendeley: state.settings.recodeOther, zotero: state.settings.recodeZotero,
  });

  /* ---------------------------------------------------------------------
     The list of abbreviated names
     --------------------------------------------------------------------- */
  const TARGET = {
    report: (t) => `report number ${t.report}`, designation: (t) => `designation ${t.designation}`,
    key: (t) => `Zotero item ${t.key}`, author: (t) => t.text, words: (t) => `items with the words “${t.text}”`,
  };

  /** How each line of the list is read, under the box, as it is typed. */
  function renderNames() {
    const box = $('zfNamesInfo');
    const read = ZFParse.readNameList($('zfNames').value);
    const rows = read.problems.slice(0, 10).map((p) => `<li class="zf-names-problem">Line ${p.line}: ${esc(p.reason)}.</li>`);
    for (const n of read.names.slice(0, 100)) rows.push(`<li><b>${esc(n.name)}</b> → ${esc(TARGET[n.target.kind](n.target))}</li>`);
    if (read.names.length > 100) rows.push(`<li>and ${read.names.length - 100} more</li>`);
    box.innerHTML = rows.length ? `<ul>${rows.join('')}</ul>` : '';
    box.hidden = !rows.length;
  }

  /** The entries under "References with abbreviated names" in the analysed
      document whose names are not in the list yet, and can be added. */
  function namesNotListed() {
    const list = state.run && state.run.parsed.list;
    if (!list) return [];
    const have = new Set(ZFParse.readNameList(state.settings.names).names.map((n) => ZFParse.fold(n.name)));
    return list.entries.filter((e) => e.abbrev && !have.has(ZFParse.fold(e.abbrev)) && ZFParse.nameLine(e));
  }

  function renderNamesToAdd() {
    const box = $('zfNamesAdd');
    const missing = namesNotListed();
    box.hidden = !missing.length;
    box.innerHTML = missing.length
      ? `${esc(`The reference list has ${plural(missing.length, 'abbreviated name')} not in this list: ${clip(missing.map((e) => e.abbrev).join(', '), 140)}.`)}`
        + ` <button type="button" class="zf-btn tiny secondary" data-on-click="zf:addNames">Add ${missing.length === 1 ? 'it' : 'them'}</button>`
      : '';
  }

  function addListedNames() {
    const lines = namesNotListed().map(ZFParse.nameLine);
    if (!lines.length) return;
    const box = $('zfNames');
    const before = box.value.replace(/\s+$/u, '');
    box.value = `${before}${before ? '\n' : ''}${lines.join('\n')}\n`;
    readControls();
    saveSettings();
    renderNames();
    renderNamesToAdd();
    KvotInfo.refresh();
    setStatus(`${plural(lines.length, 'name')} added from the reference list. Press Analyse again to use ${lines.length === 1 ? 'it' : 'them'}.`, 'warn');
  }

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
      const SQL = await ZFZotero.loadSqlJs();
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
    KvotInfo.refresh();
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
      const parsed = ZFParse.parseDocument(analysed.paras, { names: ZFParse.readNameList(state.settings.names).names });

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
      // How many places cite each abbreviated name without its being in bold.
      const notBold = new Map();
      for (const r of parsed.refs) if (r.at && r.bold === false) notBold.set(r.key, (notBold.get(r.key) || 0) + 1);
      state.run = {
        options, parsed, results, library, inventory, notBold,
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
    const out = [];
    if (ref.target) out.push(`<div class="zf-hint"><b>Your list:</b> ${esc(ref.abbrev)} → ${esc(TARGET[ref.target.kind](ref.target))}</div>`);
    if (ref.entry) out.push(`<div class="zf-hint"><b>Reference list:</b> ${esc(clip(ref.entry.text, 240))}</div>`);
    return out.join('');
  }

  /** "abbreviated name · 2 of 3 not in bold", beside a reference by name. */
  function nameTag(i, count) {
    const ref = state.run.results[i].ref;
    if (!ref.abbrev) return '';
    const n = state.run.notBold.get(ref.key) || 0;
    const plain = !n ? '' : count > 1 ? ` · ${n} of ${count} not in bold` : ' · not in bold';
    return `<span class="zf-kind">abbreviated name${plain}</span>`;
  }

  // How a candidate was found when it was not by name.
  const BY = { report: 'report number · ', designation: 'designation · ', key: 'item key · ', words: 'words · ' };
  const noteHint = (r) => (r.note ? `<div class="zf-hint">${esc(r.note)}</div>` : '');

  function candidateList(i, r, note) {
    return `<ul class="zf-cands">${r.candidates.map((c) => `<li>${itemLine(c.item)}<span class="zf-conf">${BY[c.by] || (c.entryConfirmed ? 'title in list · ' : '')}${pct(c.confidence)}</span><button type="button" class="zf-btn tiny" data-on-click="zf:choose" data-row="${i}" data-item="${c.item.itemId}">Use</button></li>`).join('')}</ul>${note || ''}`;
  }

  function searchBox(i) {
    return `<div class="zf-search"><input type="search" placeholder="Search the library: author, year, title words" data-row="${i}" data-on-input="zf:search" aria-label="Search the library for this reference"></div><ul class="zf-cands" id="zfSearch${i}"></ul>`;
  }

  function reviewItem(i, count, tone, body, actions) {
    const r = state.run.results[i];
    return `<div class="zf-item ${tone}"><div class="zf-item-head"><span class="zf-cite">${esc(r.ref.label)}</span>${nameTag(i, count)}${where(i, count)}<span class="zf-spacer"></span>${actions || ''}</div>${context(i)}${body}</div>`;
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
      rows.push(`<tr><td class="nowrap"><b>${esc(res.ref.label)}</b>${count > 1 ? ` <span class="zf-where">${count}×</span>` : ''}${res.ref.abbrev ? `<br>${nameTag(i, count)}` : ''}</td><td>${itemLine(r.item)}</td><td><span class="zf-status-tag ok">${esc(STATUS[r.how][0])}</span></td><td class="num">${conf}</td><td>${action}</td></tr>`);
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
    const named = namedCitations(rep.written);
    if (named.citations) {
      parts.push(` ${plural(named.citations, 'citation')} by abbreviated name ${named.citations === 1 ? 'keeps its' : 'keep their'} text: Zotero leaves ${named.citations === 1 ? 'it' : 'them'} as written.`);
    }
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
      const plain = res.ref.at && res.ref.bold === false ? ' <span class="zf-kind">not in bold</span>' : '';
      return `<tr><td class="nowrap">${esc(run.labels[groupOf(i).para])}</td><td><b>${esc(res.ref.label)}</b>${plain}</td><td><span class="zf-status-tag ${tone}">${esc(label)}</span></td><td>${item ? itemLine(item) : ''}</td></tr>`;
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
    renderNamesToAdd();
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

  /** Of the citations written, those by abbreviated name, and how many of
      the names in them were not in bold. */
  function namedCitations(written) {
    const named = written.filter((w) => w.group.refs.some((r) => r.abbrev));
    return { citations: named.length, notBold: named.reduce((k, w) => k + w.group.refs.filter((r) => r.at && r.bold === false).length, 0) };
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
    const named = namedCitations(result.written);
    if (named.citations) {
      const now = named.notBold === 1 ? ' and now is' : ' and now are';
      const plain = !named.notBold ? '' : `; ${plural(named.notBold, 'name was', 'names were')} not in bold${s.boldNames ? now : ''}`;
      lines.push(`By abbreviated name: ${plural(named.citations, 'citation')}, each keeping the name as its text, which Zotero leaves as it is${plain}.`);
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
        track: s.track, keepTracking: s.keepTracking, author: s.author, recode: run.options.recode, boldNames: s.boldNames,
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
      KvotInfo.refresh();
      if (state.run) setStatus('The changed setting takes effect when you press Analyse again; the choices made so far are then cleared.', 'warn');
    },
    'zf:trackChanged': () => { readControls(); saveSettings(); KvotInfo.refresh(); },
    'zf:namesTyped': () => { renderNames(); KvotInfo.refresh(); },
    'zf:namesChanged': () => {
      readControls();
      saveSettings();
      renderNamesToAdd();
      KvotInfo.refresh();
      if (state.run) setStatus('The changed list takes effect when you press Analyse again; the choices made so far are then cleared.', 'warn');
    },
    'zf:addNames': () => addListedNames(),
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
     The (i) beside each section, setting and tab (kvot-info.js)

     What each one is, what its choices do, when to change it and where the
     Help says more. A topic that is a function is read each time its panel
     opens, so it marks the current choice; KvotInfo.refresh() redraws an
     open one when a setting changes. Inline markup: `code` and **bold**.
     --------------------------------------------------------------------- */
  const more = (label, id) => ({ label, id });
  const ticked = (id) => $(id).checked;
  const LATER = 'A change takes effect at the next Analyse, which clears the choices made so far.';
  const ON_SAVE = 'These settings apply when you save, without a new analysis.';

  const TOPICS = {
    'sec:doc': {
      kicker: 'Section', title: 'Word document',
      lead: 'The document whose citations are plain text. It is read here, in the browser, and never changed: saving gives you a copy.',
      facts: [['Files', '.docx, .docm'], ['Largest', kvotFormatBytes(KVOT_FILE_SIZE_LIMITS.document)]],
      sections: [
        { heading: 'What is read', list: [
          'The body text with its tables, the footnotes and the endnotes. Text boxes, headers and footers are not read.',
          'The text as it reads with every tracked change accepted: deleted text is left out, inserted text counts. Other people’s revisions stay in the document as they are.',
        ] },
        { heading: 'The box under it', text: 'How many paragraphs the document has, in the text and in notes; how many tracked changes it already holds and whether Track Changes is on; and how many citations are already Zotero, EndNote or Mendeley fields.' },
        { heading: 'Keep in mind', list: [
          'A .doc, .odt, .rtf or PDF cannot be read: save it as .docx in Word first.',
          'The document and the database can be dropped on the page together.',
          'Opening another document clears the analysis and the choices made.',
        ] },
      ],
      more: more('Working through a document', 'help-working'),
    },

    'sec:db': {
      kicker: 'Section', title: 'Zotero library',
      lead: 'Your Zotero database, read here with sql.js, SQLite compiled for the browser. The page only reads it: zotero.sqlite is not changed, and Zotero may stay open.',
      facts: [['Files', 'zotero.sqlite, and zotero.sqlite-wal'], ['Largest', kvotFormatBytes(KVOT_FILE_SIZE_LIMITS.dataset)]],
      sections: [
        { heading: 'The -wal file', text: [
          'While Zotero runs, its newest changes wait in `zotero.sqlite-wal`, in the same folder, and reach zotero.sqlite only now and then. Open the two together, or one after the other in either order: the page replays those changes, checking each page of them, and reads the library as Zotero shows it.',
          'Without it, items added or changed since Zotero last copied its changes into zotero.sqlite are missing or out of date. The box under the drop zone says so.',
        ] },
        { heading: 'What is read', list: [
          'Every item of My Library and of the group libraries: its creators, year, title and report number, and the data a Zotero citation carries.',
          'Left out: attachments, notes, annotations, items in the bin and feed items.',
        ] },
        { heading: 'Keep in mind', text: 'Opening another database clears the analysis and the choices made. Nothing of the library is kept after you leave the page.' },
      ],
      more: more('Working through a document', 'help-working'),
    },

    'set:scope': () => {
      const sel = $('zfScope');
      const v = sel.value;
      const chosen = sel.selectedOptions[0];
      return {
        kicker: 'Zotero library', title: 'Look for items in',
        lead: 'The items each reference is matched against, and those the search box under a reference looks through.',
        facts: state.db && state.db.sqldb && chosen ? [['Chosen', chosen.textContent]] : [],
        sections: [
          { choices: [
            ['All libraries', 'Every item of My Library and of every group library in the database. The default.', v === ''],
            ['One library', 'My Library alone, or one group library. Offered when the database has more than one.', v.startsWith('lib:')],
            ['A collection', 'The items filed in it and in all its subcollections. The number after a collection counts only what is filed in it directly.', v.startsWith('col:')],
          ] },
          { heading: 'When to narrow it', text: 'A project’s collection leaves out namesakes the document does not cite, so there are fewer choices to make. But an item outside it is neither matched nor offered, and the search does not find it: a reference to it comes out as not found.' },
          { heading: 'Keep in mind', list: [LATER, 'It is not remembered: each database opens at All libraries.'] },
        ],
      };
    },

    'sec:match': {
      kicker: 'Section', title: 'Matching',
      lead: 'How close an item must come before it is linked to a reference without asking you, and how far off its year may be for it to be offered.',
      sections: [
        { heading: 'How a reference is scored', list: [
          '**Name** — the cited authors against the item’s creators, by Jaro–Winkler similarity of the names with accents folded: “Öhman” and “Ohman” are one name. A second cited author is compared with the second creator, and the number of names counts: “Smith & Jones” fits a two-author item better than a one- or five-author one, and “Smith et al.” does not fit a single author.',
          '**Year** — the cited year against the item’s.',
          '**Reference list** — when the document’s list has the entry a citation points to, how much of the item’s title is in it. A title found there settles a choice between namesakes.',
        ] },
        { text: 'Only the items whose first creator begins with the same letter as the first cited name are scored, and those whose name the cited one abbreviates (“IPCC”).' },
        { heading: 'Found by number, not by name', text: 'A report number (“SKB TR-11-01”) or a designation (“SSMFS 2008:37”) is looked up in the items’ numbers and titles, whatever is set here. A work cited by a number that no item carries is only offered, never linked.' },
        { text: LATER },
      ],
      more: more('Working through a document, step 2', 'help-analyse'),
    },

    'set:level': () => {
      const L = ZFMatch.LEVELS;
      const at = LEVEL_NAMES[Number($('zfLevel').value)] || 'balanced';
      const row = (name) => [name[0].toUpperCase() + name.slice(1), `fit ${L[name].name.toFixed(2)} · ahead ${L[name].margin.toFixed(2)}`];
      return {
        kicker: 'Matching', title: 'How close a fit must be',
        lead: 'The least name similarity at which an item fits a reference (fit), and how far the best item must be ahead of the next to be linked without asking (ahead).',
        facts: [...LEVEL_NAMES.map(row), ['Default', 'balanced']],
        sections: [
          { choices: [
            ['Lenient', 'Links more on its own and asks less. It takes a name written another way, “Smyth” for “Smith”, when no other item comes near.', at === 'lenient'],
            ['Balanced', 'Right for most documents. Such a name is offered among the possible matches instead.', at === 'balanced'],
            ['Strict', 'Asks whenever two items are near: for a library with many similar names, when you would rather decide yourself.', at === 'strict'],
          ] },
          { heading: 'What the numbers mean', text: [
            'One cited name against an item with one creator: “Smith” and “Smyth” come to 0.89, “Andersson” and “Andersen” to 0.93, “Nilsson” and “Nilson” to 0.97.',
            'An item that fits and has the cited year is linked when it is the only one, when it is ahead of the next by the margin, or when its title is in the reference-list entry and the other’s is not; otherwise the items that fit nearly as well are offered for you to choose. With no such item, one within the year tolerance is offered to confirm, and failing that, items up to 0.06 short of a fit, whatever their year, as possible matches.',
          ] },
        ],
        more: more('Working through a document, step 2', 'help-analyse'),
      };
    },

    'set:yearTolerance': () => {
      const tol = Number($('zfYearTolerance').value);
      return {
        kicker: 'Matching', title: 'Offer items whose year is off by',
        lead: 'When no item of the cited year fits the authors, an item this many years away is offered under “The year differs”, for you to confirm. It is never linked without asking.',
        facts: [['Default', '1 year']],
        sections: [
          { choices: [
            ['nothing', 'Only the cited year. An item of another year whose authors fit still comes up, among the possible matches.', tol === 0],
            ['1 year', 'A year either way: a work cited by the year it was written and held in the library by the year it came out, or the other way round.', tol === 1],
            ['2 years', 'Two years either way.', tol === 2],
          ] },
          { heading: 'Years that are not numbers', list: [
            '“n.d.”, “u.å.” and “o.J.” fit an item without a date.',
            '“in press”, “forthcoming”, “unpublished”, “i tryck” and the like fit an item without a date, or one dated from two years ago on.',
          ] },
          { heading: 'Also', text: 'The report number at the end of a reference-list entry (“SKB, 2011. … SKB TR-11-01, …”) is taken only for an item whose creators fit the entry and whose year is this close to it.' },
        ],
        more: more('Working through a document, step 2', 'help-analyse'),
      };
    },

    'sec:names': {
      kicker: 'Section', title: 'Abbreviated names',
      lead: 'SKB’s reports cite some works by a name instead of an author and year — “the Data report”, “(Main report, Section 6.1)” — and list them under “References with abbreviated names”. A name has no author or year to match by, so this list says which work each one stands for.',
      sections: [
        { heading: 'What a listed name becomes', list: [
          'In a parenthesis, “(Data report, Section 6.1)”, a reference like any other, with its locator.',
          'In running text, “as the **Data report** shows”, a citation of its own: the name itself.',
          'Either way the citation keeps the name as its text. No citation style prints the name, so the citation is marked for Zotero to leave its text as written; the work still goes into the bibliography.',
        ] },
        { heading: 'In running text', text: 'SKB writes the names in bold. A name in bold is taken when it begins as listed; one not in bold only when it is written exactly as listed and stands inside a sentence: not at the start of a line, where it may begin a title, nor after a qualifier such as “SR-Site”, which makes it another work’s name. A name in a heading, in a table of contents or alone on its line is never taken.' },
        { heading: 'The document’s own list', text: 'A name entered under the document’s “References with abbreviated names” is found in a parenthesis without this list, but in running text only when it is listed here. After an analysis, **Add them** under the box copies the names not listed yet.' },
      ],
      more: more('Abbreviated names', 'help-names'),
    },

    'set:names': () => {
      const read = ZFParse.readNameList($('zfNames').value);
      return {
        kicker: 'Abbreviated names', title: 'Names and the works they stand for',
        lead: 'One per line: the name as it stands in the text, a colon or a tab, and the work it stands for — “Data report: SKB TR-10-52”.',
        facts: [['Names read', read.names.length.toLocaleString('en')], ['Lines not read', read.problems.length ? read.problems.length.toLocaleString('en') : 'none'], ['Longest list', `${NAMES_MAX.toLocaleString('en')} characters`]],
        sections: [
          { heading: 'The work, after the colon', list: [
            '`SKB TR-10-52` — an SKB report number, found in the items’ Report Number. Without “SKB”, `TR-10-52` is SKB’s report of that number if the library has it, otherwise any organisation’s.',
            '`SSMFS 2008:37` — a designation, found in the items’ numbers and titles.',
            '`ABCD2345` — a Zotero item key, eight capitals and digits, or a link that ends in `items/ABCD2345`.',
            '`SKB 2010` — an author and year, matched as a citation would be. Several items of that author and year leave you a choice to make; a report number names one work.',
            'Anything else — words of the title: the items that have all of them.',
          ] },
          { heading: 'Also read', list: [
            'An entry pasted from “References with abbreviated names”, such as “Data report, 2010. Data report for the safety assessment SR-Site. SKB TR-10-52, …”: the name, and its report number or else its title and year.',
            'A line that begins with # is a note, and is skipped.',
          ] },
          { heading: 'Keep in mind', list: [
            'Under the box, each line as it was read, and each line that could not be, with the reason. A name listed twice: the first is used.',
            `The list is kept in this browser for your next visit. ${LATER}`,
          ] },
        ],
        more: more('Abbreviated names', 'help-names'),
      };
    },

    'set:boldNames': () => {
      const on = ticked('zfBoldNames');
      return {
        kicker: 'Abbreviated names', title: 'Write the names in bold',
        lead: 'Whether the name in a citation by abbreviated name is made bold when the document is saved, as SKB writes such names.',
        facts: [['Default', 'ticked']],
        sections: [
          { choices: [
            ['Ticked', 'Each name is made bold where it stands, and only the name: in “(Data report, Section 3)” the brackets and the section keep their formatting. The summary comment counts the names that were not in bold and now are.', on],
            ['Unticked', 'The names keep the formatting they had.', !on],
          ] },
          { text: 'It applies when you save; it changes nothing in the matching and needs no new analysis. With the changes tracked, rejecting one in Word takes the bold away with the citation.' },
        ],
        more: more('Citations by abbreviated name', 'help-names-kept'),
      };
    },

    'sec:fields': {
      kicker: 'Section', title: 'Citations that are already fields',
      lead: 'A document may already hold citations inserted by a reference manager: Word fields whose code names the works they cite. The box under Word document counts them.',
      sections: [
        { heading: 'Recognised', list: ['Zotero — `ADDIN ZOTERO_ITEM`', 'EndNote — `ADDIN EN.CITE`, with its `EN.CITE.DATA`', 'Mendeley — `ADDIN CSL_CITATION`'] },
        { heading: 'Left as they are', text: 'A citation field that is not converted is not read for citations, and a plain-text citation that runs into one is not replaced. A bibliography inserted by any of the three is never changed.' },
        { text: LATER },
      ],
      more: more('When a citation is not written', 'help-refused'),
    },

    'set:recodeOther': () => {
      const on = ticked('zfRecodeOther');
      return {
        kicker: 'Citations that are already fields', title: 'Convert EndNote and Mendeley citations to Zotero',
        lead: 'Whether citations inserted with EndNote or Mendeley become Zotero citations too.',
        facts: [['Default', 'ticked']],
        sections: [
          { choices: [
            ['Ticked', 'The text each such citation shows is read like plain text and matched. When every reference in it is resolved, the whole field is replaced by a Zotero citation, its hidden EndNote data with it.', on],
            ['Unticked', 'They are left as they are, and their text is not read.', !on],
          ] },
          { heading: 'Keep in mind', list: ['An EndNote or Mendeley bibliography in the document is not touched.', 'A citation field that runs over more than one paragraph is not converted.'] },
        ],
        more: more('When a citation is not written', 'help-refused'),
      };
    },

    'set:recodeZotero': () => {
      const on = ticked('zfRecodeZotero');
      return {
        kicker: 'Citations that are already fields', title: 'Match Zotero citations again as well',
        lead: 'Whether the Zotero citations already in the document are matched against your library again.',
        facts: [['Default', 'unticked']],
        sections: [{ choices: [
          ['Unticked', 'They are left as they are, and not read. The works they cite count as cited when the reference list is checked for entries nothing cites, and the Reference list tab lists them.', !on],
          ['Ticked', 'Their text is read like plain text and matched, and each one whose references are all resolved is replaced by a new Zotero citation: for a document whose citations point at the items of another library, a colleague’s say, to link them to yours.', on],
        ] }],
      };
    },

    'sec:track': {
      kicker: 'Section', title: 'Track changes',
      lead: 'Each conversion is written as an editor would write it with Track Changes on: the old text struck through and the Zotero citation inserted, both by the author named here. Everything else in the document, other people’s revisions included, is left as it was.',
      sections: [
        { heading: 'In Word', list: [
          'Review → Show Markup → Specific People shows the page’s changes alone.',
          'Rejecting them gives back the text exactly as it was; accepting them leaves ordinary Zotero citations.',
          '**Accept them before you press Refresh** in Zotero’s tab. Zotero turns Track Changes off while it edits citations, and tracked citations can confuse it.',
        ] },
        { text: ON_SAVE },
      ],
      more: more('Accept before you refresh', 'help-accept'),
    },

    'set:track': () => {
      const on = ticked('zfTrack');
      return {
        kicker: 'Track changes', title: 'Record every conversion as a tracked change',
        lead: 'Whether the page’s own changes carry revision marks.',
        facts: [['Default', 'ticked']],
        sections: [
          { choices: [
            ['Ticked', 'Each conversion is a tracked deletion of the old text and a tracked insertion of the Zotero citation, by the author named below. Each can be accepted or rejected in Word.', on],
            ['Unticked', 'The citations are written in place with no revision marks: there is nothing to accept, and nothing to reject. Your original file, which the page does not change, is then the way back.', !on],
          ] },
          { text: 'Whether Track Changes stays on for your own editing is the last setting of this section.' },
        ],
        more: more('Accept before you refresh', 'help-accept'),
      };
    },

    'set:author': {
      kicker: 'Track changes', title: 'Author of the changes and comments',
      lead: 'The name Word shows on the page’s tracked changes and comments.',
      facts: [['Default', 'Zoterify'], ['Longest', '80 characters']],
      sections: [{ list: [
        'It is added to the document’s list of people, and the comments carry its initials: Z for Zoterify.',
        'Keep Zoterify to pick the page’s changes out with Specific People in Word; put your own name to make them yours.',
        'Left empty, it is Zoterify. The box is greyed out when no change is tracked and no comment written, as nothing then carries a name.',
        'It applies when you save, without a new analysis.',
      ] }],
      more: more('Working through a document, step 4', 'help-review'),
    },

    'set:keepTracking': () => {
      const on = ticked('zfKeepTracking');
      return {
        kicker: 'Track changes', title: 'Leave Track Changes switched on in the saved document',
        lead: 'Word’s own switch, for the editing done after the page’s.',
        facts: [['Default', 'ticked']],
        sections: [
          { choices: [
            ['Ticked', 'Track Changes is on when the saved document opens, so the edits made in it are tracked as well.', on],
            ['Unticked', 'Track Changes is off in the saved document, even if it was on in the one you opened.', !on],
          ] },
          { text: 'Whether the page’s own changes are tracked is the first setting of this section. The box under Word document says whether Track Changes is on in the document you opened.' },
        ],
        more: more('Accept before you refresh', 'help-accept'),
      };
    },

    'sec:comments': {
      kicker: 'Section', title: 'Comments in the document',
      lead: 'Word comments that say what the page left as text and why, so that the reasons go with the document.',
      sections: [{ list: [
        'They are by the author named under Track changes, with its initials.',
        'They are not tracked changes: rejecting the page’s changes leaves them.',
        'Review → Delete → Delete All Comments in Document removes everyone’s. With Show Markup → Specific People set to the page’s author alone, Delete All Comments Shown removes only these.',
        'Comments already in the document are kept.',
        ON_SAVE,
      ] }],
      more: more('Comments in the document', 'help-comments'),
    },

    'set:comment': () => {
      const on = ticked('zfComment');
      return {
        kicker: 'Comments in the document', title: 'Comment on each citation left as text',
        lead: 'A citation is left as text when a reference in it was not found or not decided, or when it cannot be replaced safely.',
        facts: [['Default', 'ticked']],
        sections: [
          { choices: [
            ['Ticked', 'Each one gets a comment over exactly its text saying why: which of its references were not found in the library, turned down, unlinked, left to choose or given a year not confirmed; that the others in it were matched, since a citation is converted only when all its references are; or what stopped the replacement, such as a footnote reference inside it.', on],
            ['Unticked', 'No comments on citations. The Resolved tab still lists the places left as text, with the reasons.', !on],
          ] },
          { text: 'A citation in a footnote or an endnote gets its comment on the note’s mark in the body text; the comment begins “In the footnote marked here” (or endnote) and quotes the citation.' },
        ],
        more: more('Comments in the document', 'help-comments'),
      };
    },

    'set:summary': () => {
      const on = ticked('zfSummaryComment');
      return {
        kicker: 'Comments in the document', title: 'Add a summary comment at the start of the document',
        lead: 'One comment on the first paragraph that sums up the run.',
        facts: [['Default', 'ticked']],
        sections: [
          { heading: 'What it says', list: [
            'When, the database and the libraries or collection matched against, and the matching setting.',
            'How many references and citations were found, and how many were converted.',
            'How many citations were left as text and why, those by abbreviated name, and the Zotero citations left as they were.',
            'The reference-list entries nothing cites, the first ten of them.',
            'What is not read — text boxes, headers and footers — and, with the changes tracked, to accept them before Refresh.',
          ] },
          { choices: [
            ['Ticked', 'Written at each save, by the author named under Track changes.', on],
            ['Unticked', 'No summary. On the page, the report at the top of the Resolved tab and the Reference list tab say much the same.', !on],
          ] },
        ],
        more: more('Comments in the document', 'help-comments'),
      };
    },

    'act:run': {
      kicker: 'Actions', title: 'Analyse, save, report',
      lead: 'The three steps of a run. The line under the buttons says what happened and what to do next.',
      sections: [
        { heading: 'Analyse', text: 'Reads the document, finds every citation and the reference list, and matches each reference against the library. It is ready once both files are open. Each time it starts afresh and clears the choices made so far, so press it again after changing a matching setting or the list of names, before deciding.' },
        { heading: 'Save document', text: 'Writes the resolved citations into a copy of the document, `name_zotero.docx`; your original is not changed. A citation is written only when every reference in it is resolved. Each save starts again from the document you opened, so you can decide more, change what applies on saving — Track changes, Comments, the bold — and save again.' },
        { heading: 'Report as CSV', text: 'Every reference, where it stands and the item it resolves to, and after them the reference-list entries nothing cites: `name_zoterify.csv`, with the columns where, citation, reference, state, zotero key, zotero item and reference list entry.' },
      ],
      more: more('Working through a document, step 3', 'help-save'),
    },

    'pane:review': {
      kicker: 'Tab', title: 'To review',
      lead: 'The references that need a decision from you. Each is listed once, however often it is cited, and a decision holds for every place it stands.',
      sections: [
        { heading: 'The groups', list: [
          '**Choose the item** — more than one item fits equally well: the same authors twice in a year, say.',
          '**The year differs** — the authors fit an item of another year, within the tolerance set under Matching.',
          '**Possible matches** — only looser fits, of any year.',
          '**Not found** — nothing near, or you turned down what was offered or unlinked a match. Search the library, or leave it as text.',
        ] },
        { heading: 'Each reference', list: [
          'The citation in its sentence; where it stands — ¶ 12 is the twelfth paragraph of the body text, counting headings, empty paragraphs and table cells — and how many times it is cited.',
          'Your list’s entry for a listed name, and the reference-list entry the citation points to.',
          'The items offered, each with how it was found — by report number, designation, item key or words, or by its title in the reference list — and its fit in per cent.',
          '**Use** takes an item; **None of these** moves the reference to Not found, where **Undo** brings the offers back.',
          'The search wants two characters or more and shows up to eight items. Every word must be in an item’s creators, year, title or number; a report number is looked up whole.',
        ] },
        { heading: 'The counts at the top', text: 'References cited counts every place a reference stands; resolved, to decide and not found count each reference once; uncited entries are the reference-list entries nothing cites. The number on the tab is to decide and not found together.' },
        { heading: 'Keep in mind', text: 'The decisions are kept only while the page is open, and a new Analyse clears them.' },
      ],
      more: more('Working through a document, step 2', 'help-analyse'),
    },

    'pane:linked': {
      kicker: 'Tab', title: 'Resolved',
      lead: 'The references linked to a Zotero item, which a save writes. Each is listed once, with how often it is cited.',
      sections: [
        { heading: 'Columns', list: [
          '**Reference** — as the page read it, with how many times it is cited, and whether it is an abbreviated name.',
          '**Zotero item** — its creators, year, title and key, and its library when there are several.',
          '**How** — matched by the page, chosen by you among the items offered, or picked by hand from a search.',
          '**Fit** — how it was found and its fit in per cent, as on To review; empty for an item picked by hand.',
        ] },
        { heading: 'Changing your mind', text: '**Unlink** a match that is wrong: the reference goes to To review, under Not found, where **Restore** brings the match back. **Undo** takes back a choice or a pick.' },
        { heading: 'After a save', text: 'A box at the top says what was written — how many references, in how many Zotero citations, by whom, and whether Track Changes is on — and lists the places left as text with the reason: a reference not resolved yet, or something in the text the page will not cut through, such as a footnote reference.' },
      ],
      more: more('When a citation is not written', 'help-refused'),
    },

    'pane:all': {
      kicker: 'Tab', title: 'All citations',
      lead: 'Every reference the page found, in document order, one row for each place it stands: to check that nothing was read as a citation that is not one, and that nothing was missed.',
      sections: [
        { list: [
          '**Where** — ¶ and the number of the paragraph in the body text, counting headings and table cells; or footnote, endnote.',
          '**Reference** — as the page read it: authors and year, a report number, a designation, a number in brackets or an abbreviated name; “not in bold” marks a listed name found without bold.',
          '**State** — matched, chosen or picked by hand; choose, year differs or possible; not found, none of those or unlinked.',
          '**Zotero item** — the item it resolves to or, until then, the best one offered.',
        ] },
        { text: 'Report as CSV holds the same rows, and the reference-list entries nothing cites.' },
      ],
      more: more('What is found', 'help-found'),
    },

    'pane:refs': {
      kicker: 'Tab', title: 'Reference list',
      lead: 'What the analysis made of the document’s reference list.',
      sections: [{ list: [
        '**The reference list** — where it begins and ends, and how many entries were read. Its paragraphs are not searched for citations; what comes after it, appendices say, is. When no list is recognised, every paragraph is searched.',
        '**Entries nothing cites** — the entries no citation points to. An entry named in running text, “the Data report”, counts as cited, and so does one whose first author and year a Zotero citation already in the document cites.',
        '**Zotero citations already in the document** — left as they are, each with the surname and year of every item it cites. None are listed when they are matched again, under Citations that are already fields.',
      ] }],
      more: more('The reference list', 'help-reflist'),
    },
  };

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
  KvotInfo.setup({ topics: TOPICS, onMore: () => showTab('help') });

  window.ZFPage = Object.freeze({ getState: () => state, addFiles, analyse, save, resolve, statusOf });
}());
