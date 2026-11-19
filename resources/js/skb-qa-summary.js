/* ==========================================================================
   SKB QC SUMMARY (skb_qa_summary.html)

   The QC review of the input data, read from three kinds of file:

   - source workbooks (the Excel folder): sheets with an ID column and the
     three review columns, QC reviewer, QC comment and QC status. Each row
     is a value; a parameter is an ID in a workbook, over one row or the
     rows of a time series.
   - input-set exports (the QC folder): one workbook per input set, the
     parameter file <set>.h5 a calculation case reads, with every value in
     it and the workbook, sheet and row it was read from. Tracing those
     back to the source workbooks gives each input set the QC state of the
     very rows it uses, after the set's own workbooks have overridden the
     common ones.
   - calculation cases (the config folder): TOML files, with link.toml and
     data.toml, which say which input sets each case reads.

   Workbooks are read by resources/js/skb-qa-read.mjs, in workers where the
   browser has them, a few at a time; .xls and .xlsb, which that reader
   cannot open, by SheetJS. Nothing leaves the browser.
   ========================================================================== */
'use strict';
const $ = (id) => document.getElementById(id);

/*
  The three review columns were headed QA and are now QC. Both spellings are
  read, QC first: five of the workbooks this was built for still carry the QA
  heading, and they hold real review data. Dropping a sheet over the letter in
  its heading would lose it without saying so. (skb-qa-read.mjs has the same
  rule; this copy serves the SheetJS reading.)
*/
const REVIEW_PREFIXES = ['qc', 'qa'];
const columnsFor = (prefix) => ['id', prefix + ' reviewer', prefix + ' comment', prefix + ' status'];
const reviewPrefix = (header) => REVIEW_PREFIXES.find((p) => columnsFor(p).every((key) => header.includes(key)));

/*
  The statuses a QC review moves through, in that order, which is the order
  they are listed and filtered in rather than the alphabetical one.

  A value outside this list is kept and shown after them, never dropped and
  never silently counted as approved: a status the page does not recognise is
  the thing most worth seeing.
*/
const STATUS_ORDER = ['Preliminary', 'In review', 'OK-PSAR', 'OK-UPSAR', 'OK-FSAR'];
const APPROVED = new Set(['ok-psar', 'ok-upsar', 'ok-fsar']);
const MIXED = 'Mixed';
const BLANK = '(Blank)';
/* The bars run from done to not started: approved, in review, preliminary, then what is not one status. */
const BAR_ORDER = ['OK-FSAR', 'OK-UPSAR', 'OK-PSAR', 'In review', 'Preliminary'];
const STATUS_STYLE = { 'OK-FSAR': 'fsar', 'OK-UPSAR': 'upsar', 'OK-PSAR': 'psar', 'In review': 'review', Preliminary: 'prelim', [MIXED]: 'mixed', [BLANK]: 'blank' };
const styleOf = (label) => STATUS_STYLE[label] || 'other';

const normalize = (v) => String(v ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
const display = (v) => String(v ?? '').trim() || BLANK;
/*
  The one spelling of a status, used for the bars, the filter, the table and
  the export alike. Case is not part of the vocabulary, so a cell reading
  "ok-fsar" is the OK-FSAR status - counted, filtered and shown as one thing.
  A value outside the vocabulary is passed through as typed, because there is
  nothing to canonicalise it to and hiding it would be the wrong answer.
*/
function statusLabel(v) {
  const raw = String(v ?? '').trim();
  if (!raw) return BLANK;
  return STATUS_ORDER.find((label) => normalize(label) === normalize(raw)) ?? raw;
}
const isApproved = (label) => APPROVED.has(normalize(label));

/* What the Folder column shows for a workbook added on its own. */
const NO_FOLDER = '<span class="no-folder" aria-label="no folder">—</span>';
/* The table holds a window over the matching rows rather than all of them:
   93 416 rows is 841 000 DOM nodes and near a second per render, and the way
   to a row is to filter, not to scroll past ninety thousand. */
const PAGE_SIZE = 500;

/*
  What a folder is searched for: Excel's own formats and TOML files. The rest
  is passed over, and so is what only looks like a workbook - the "~$" file
  Excel keeps beside each workbook it has open, and hidden files and folders,
  such as the "._" copies macOS leaves on shared drives. A folder is followed
  down to a depth no real tree reaches, which ends a loop of links, not a
  deep folder.
*/
const WORKBOOK = /\.(xlsx|xlsm|xlsb|xls)$/i;
const ZIPPED = /\.(xlsx|xlsm)$/i;
const TOML = /\.toml$/i;
const passedOver = (name) => name.startsWith('~$') || name.startsWith('.');
const MAX_DEPTH = 32;
const STAMP = '20261119';

/* ---- The state: what was read, and what is derived from it ---------------- */
/* A file is known by its path, its folder and its name together, so two
   workbooks of one name in two folders are two files. */
let rows = [], validSheets = [], loadedFiles = [], exportFiles = [];
let tomlFiles = [], cases = null, lib = null, libLoading = null;
let reader = null, readerLoading = null;
let snapshot = null, tableLimit = PAGE_SIZE, activeTab = 'overview';
/* Indexes over the rows, rebuilt whenever files arrive or go. */
let model = null;
/* The filters: a value set per list, the ID search and the two switches. */
const filters = { status: new Set(), reviewer: new Set(), folder: new Set(), file: new Set(), sheet: new Set(), set: new Set(), case: new Set() };
let filterVersion = 0, filterCache = null;
const expanded = { book: new Set(), set: new Set() };
const sortBy = { books: { key: 'path', dir: 1 }, sets: { key: 'state', dir: 1 } };

/*
  TOML files describe calculation cases, and link.toml and data.toml among
  them tie each case to the workbooks its data come from. The rules are in
  resources/js/skb-qa-config.mjs; the files are read with smol-toml. Both are
  loaded the first time a TOML file arrives, so a page that only ever reads
  workbooks never fetches them.
*/
function loadConfigLib() {
  return libLoading ??= Promise.all([import('../../vendors/js/smol-toml-1.9.0/index.js'), import('./skb-qa-config.mjs?v=20261119')])
    .then(([toml, model]) => lib = { toml, model }, (e) => { libLoading = null; throw e; });
}
function loadReader() {
  return readerLoading ??= import('./skb-qa-read.mjs?v=' + STAMP)
    .then((m) => reader = m, (e) => { readerLoading = null; throw e; });
}

/* ---- Small things ----------------------------------------------------------- */
/* One implementation, in resources/js/kvot-safe.js. */
const esc = (v) => kvotEscapeHtml(v);
const fmt = (n) => Number(n).toLocaleString('en-GB');
const share = (part, whole) => (whole ? 100 * part / whole : 0);
const pct = (part, whole) => {
  if (!whole) return '0 %';
  const p = share(part, whole);
  if (p > 0 && p < 0.1) return '< 0.1 %';
  if (p < 100 && p > 99.9) return '> 99.9 %';
  return `${p.toLocaleString('en-GB', { maximumFractionDigits: p < 10 ? 1 : 0 })} %`;
};
const plural = (n, one, many = one + 's') => `${fmt(n)} ${n === 1 ? one : many}`;
/* Paths compare a folder at a time, so a folder's files and subfolders sort
   together and below it. Numbers in names sort in numeric order. */
function comparePaths(a, b) {
  const x = a.split('/'), y = b.split('/');
  for (let i = 0; i < Math.min(x.length, y.length); i++) { const c = x[i].localeCompare(y[i], 'en', { numeric: true }); if (c) return c; }
  return x.length - y.length;
}
const folderOf = (path) => path.split('/').slice(0, -1).join('/');
const nameOf = (path) => path.split('/').pop();
/* The name first and the folder after it, so a narrow list clips the folder rather than the name. */
const withFolder = (path, what) => folderOf(path) ? `${what} (${folderOf(path)})` : what;
const sheetKey = (r) => `${r.path} › ${r.sheet}`;
/* A long file name may break after an underscore or a slash, not inside a word. */
const breakable = (name) => esc(name).replace(/([_/])/g, '$1<wbr>');

/* `files` are the ones that gave no data, each with its reason, listed under
   the message for whoever wants to know which they were. */
function showStatus(msg, error = false, files = [], progress = null) {
  $('status-text').textContent = msg;
  $('status').className = 'show' + (error ? ' error' : '');
  const list = $('status-files');
  list.hidden = !files.length; list.open = false;
  list.querySelector('ul').innerHTML = files.map((f) => `<li><span class="mono">${esc(f.path)}</span>: ${esc(f.why)}</li>`).join('');
  const bar = $('status-progress');
  bar.hidden = progress == null;
  if (progress != null) bar.firstElementChild.style.width = `${Math.max(0, Math.min(100, progress))}%`;
}
function hideStatus() { $('status').className = ''; }

/* ---- Getting files in ------------------------------------------------------------ */
/*
  A file chosen on its own comes without its folder: a browser tells a page a
  file's name but not where it lies. A folder, chosen or dropped, gives every
  file in it its path from that folder down, and that is the Folder column.
*/
const item = (file, path) => ({ file, name: file.name, folder: folderOf(path), path });
/* The list a file of this name goes in: workbooks, TOML files, or none. */
const listFor = (name, list, tomls) => WORKBOOK.test(name) ? list : TOML.test(name) ? tomls : null;
function chosenFiles(files) {
  const list = [], tomls = []; let others = 0;
  for (const file of files) {
    const path = file.webkitRelativePath || file.name;
    /* The folder chosen is read even when it is hidden; what is hidden inside it is not. */
    if (path.split('/').slice(1).some(passedOver) || passedOver(file.name)) continue;
    const into = listFor(file.name, list, tomls);
    if (into) into.push(item(file, path)); else others++;
  }
  return { list, tomls, others, failed: [] };
}
/* A drop's items are taken out while the drop event lasts: the browser takes
   them back once it has been handled. An item's entry is what holds a folder;
   one with none, such as a mail attachment, is taken as the file it is. */
const dropItems = (dt) => dt.items ? [...dt.items].filter((it) => it.kind === 'file').map((it) => ({ entry: it.webkitGetAsEntry?.() ?? null, file: it.getAsFile() })) : [...dt.files].map((file) => ({ entry: null, file }));
async function droppedFiles(items, job) {
  const list = [], tomls = [], failed = []; let others = 0;
  const walk = async (entry, depth) => {
    if (job.stopped || job.cleared) return;
    const path = entry.fullPath.replace(/^\//, '');
    if (entry.isFile) {
      if (passedOver(entry.name)) return;
      const into = listFor(entry.name, list, tomls);
      if (!into) { others++; return; }
      try { into.push(item(await new Promise((res, rej) => entry.file(res, rej)), path)); }
      catch (e) { failed.push({ path, why: `could not be opened: ${e.message}`, error: true }); }
    } else if (entry.isDirectory && !(depth && passedOver(entry.name))) {
      if (depth >= MAX_DEPTH) { failed.push({ path, why: `not looked into, ${MAX_DEPTH} folders down`, error: true }); return; }
      showStatus(`Looking through ${path}…`);
      const dir = entry.createReader();
      try {
        for (let batch; (batch = await new Promise((res, rej) => dir.readEntries(res, rej))).length;)
          for (const child of batch) await walk(child, depth + 1);
      } catch (e) { failed.push({ path, why: `could not be opened: ${e.message}`, error: true }); }
    }
  };
  for (const { entry, file } of items) {
    if (entry) await walk(entry, 0);
    else if (file && !passedOver(file.name)) { const into = listFor(file.name, list, tomls); if (into) into.push(item(file, file.name)); else others++; }
  }
  return { list, tomls, others, failed };
}

/*
  Workers read the workbooks, a few at a time, while the page takes their
  results in path order. A worker that cannot start - an old browser, a page
  opened from disk - hands its workbook back, and the page reads it itself.
*/
class ReadPool {
  constructor(size) {
    this.size = size; this.workers = []; this.idle = []; this.waiting = []; this.calls = new Map(); this.next = 1; this.broken = false;
  }
  run(book) {
    if (this.broken) return Promise.reject(new Error('no worker'));
    return new Promise((resolve, reject) => { this.waiting.push({ book, resolve, reject }); this.pump(); });
  }
  spawn() {
    const w = new Worker('./resources/js/skb-qa-worker.mjs?v=' + STAMP, { type: 'module' });
    w.onmessage = (ev) => {
      const call = this.calls.get(ev.data.id);
      if (!call) return;
      this.calls.delete(ev.data.id);
      this.idle.push(w);
      if (ev.data.error != null) call.reject(new Error(ev.data.error)); else call.resolve(ev.data.result);
      this.pump();
    };
    w.onerror = (ev) => {
      ev.preventDefault();
      this.broken = true;
      for (const [id, call] of this.calls) if (call.worker === w) { this.calls.delete(id); call.reject(new Error('no worker')); }
      for (const job of this.waiting.splice(0)) job.reject(new Error('no worker'));
    };
    return w;
  }
  pump() {
    while (this.waiting.length && !this.broken) {
      let w = this.idle.pop();
      if (!w) {
        if (this.workers.length >= this.size) return;
        try { w = this.spawn(); } catch (e) { this.broken = true; for (const job of this.waiting.splice(0)) job.reject(new Error('no worker')); return; }
        this.workers.push(w);
      }
      const job = this.waiting.shift(), id = this.next++;
      this.calls.set(id, { ...job, worker: w });
      w.postMessage({ id, book: { file: job.book.file, path: job.book.path, folder: job.book.folder, name: job.book.name } });
    }
  }
  close() {
    for (const w of this.workers) w.terminate();
    for (const call of this.calls.values()) call.reject(new Error('stopped'));
    for (const job of this.waiting) job.reject(new Error('stopped'));
    this.workers = []; this.idle = []; this.waiting = []; this.calls.clear();
  }
}
const poolSize = () => Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1));

/*
  The SheetJS reading, for .xls and .xlsb and for any workbook the streaming
  reader refuses. Most workbooks in a folder hold no QC columns, so the first
  row of each sheet is read first, and only the sheets whose header names the
  QC columns are then read in full. A sheet whose range starts below row 1 has
  its first row lower down, out of that first read's sight, so it is read in
  full and looked at.
*/
function readWithSheetJS(buffer, book) {
  const peek = XLSX.read(buffer, { type: 'array', sheetRows: 1 });
  const wanted = [];
  peek.SheetNames.forEach((name, i) => {
    const ws = peek.Sheets[name], ref = ws && (ws['!fullref'] || ws['!ref']);
    const header = () => (XLSX.utils.sheet_to_json(ws, { header: 1, defval: '', raw: false })[0] || []).map(normalize);
    if (!ref || XLSX.utils.decode_range(ref).s.r > 0 || reviewPrefix(header())) wanted.push(i);
  });
  const records = [], sheets = [];
  if (!wanted.length) return { records, sheets, exports: [] };
  const wb = XLSX.read(buffer, { type: 'array', cellDates: true, sheets: wanted });
  for (const i of wanted) {
    const sheetName = wb.SheetNames[i], ws = wb.Sheets[sheetName];
    const matrix = ws ? XLSX.utils.sheet_to_json(ws, { header: 1, defval: '', raw: false }) : [];
    const header = (matrix[0] || []).map(normalize);
    const prefix = reviewPrefix(header);
    if (!prefix) continue;
    const [idCol, reviewerCol, commentCol, statusCol] = columnsFor(prefix).map((key) => header.indexOf(key));
    /* The matrix starts at the sheet's first row, which need not be row 1. */
    const top = XLSX.utils.decode_range(ws['!ref']).s.r;
    sheets.push({ name: sheetName, kind: 'qc' });
    for (let r = 1; r < matrix.length; r++) {
      const cells = matrix[r] || [];
      const record = { folder: book.folder, file: book.name, path: book.path, sheet: sheetName, row: top + r + 1, id: cells[idCol] ?? '', reviewer: cells[reviewerCol] ?? '', comment: cells[commentCol] ?? '', status: cells[statusCol] ?? '' };
      if ([record.id, record.reviewer, record.comment, record.status].every((v) => String(v).trim() === '')) continue;
      records.push(record);
    }
  }
  return { records, sheets, exports: [] };
}

/*
  Reads come one after another, so a folder dropped while another is being
  read waits for it instead of mixing its rows in. Stop ends them between two
  workbooks and keeps what was read; Clear all ends them and keeps nothing.
*/
const jobs = new Set();
let queue = Promise.resolve();
function enqueue(gather) {
  const job = { stopped: false, cleared: false };
  jobs.add(job); $('stop-btn').hidden = false;
  queue = queue.then(async () => {
    try {
      if (job.stopped || job.cleared) return;
      showStatus('Reading…'); $('status').setAttribute('aria-busy', 'true'); $('status').scrollIntoView({ block: 'nearest' });
      await loadFiles(await gather(job), job);
    } catch (e) { showStatus(`The files could not be read: ${e.message}`, true); }
    finally { jobs.delete(job); $('stop-btn').hidden = !jobs.size; if (!jobs.size) $('status').removeAttribute('aria-busy'); }
  });
}

async function loadFiles({ list, tomls = [], others, failed }, job) {
  const books = list.sort((a, b) => comparePaths(a.path, b.path));
  if (!books.length && !tomls.length) {
    if (!job.stopped && !job.cleared) showStatus(`No workbook (.xlsx, .xlsm, .xlsb, .xls) and no TOML file among what was added${others ? `, only ${others} other file(s)` : ''}.`, true, failed);
    return;
  }
  const newRows = [], newSheets = [], newExports = [], read = [], readTomls = [], noData = [...failed];
  /* TOML files first: they are small, and say what the workbooks are for. */
  if (tomls.length) {
    showStatus(`Reading ${tomls.length} TOML file(s)…`);
    try { await loadConfigLib(); }
    catch (e) { for (const t of tomls) noData.push({ path: t.path, why: `not read: the TOML reader could not be loaded (${e.message})`, error: true }); }
    for (const t of lib ? tomls.sort((a, b) => comparePaths(a.path, b.path)) : []) {
      if (job.stopped || job.cleared) break;
      let data = null, error = null;
      try { data = lib.toml.parse(await t.file.text()); }
      catch (e) { error = String(e.message || e).split('\n')[0] + (e.line ? ` (line ${e.line}, column ${e.column})` : ''); }
      readTomls.push({ path: t.path, folder: t.folder, name: t.name, data, error });
      if (error) noData.push({ path: t.path, why: `could not be read as TOML: ${error}`, error: true });
    }
  }
  if (books.length && books.some((b) => ZIPPED.test(b.name))) { try { await loadReader(); } catch (e) { reader = null; } }
  /* Each workbook is started ahead of the one being taken, as many as there are workers. */
  const pool = reader && typeof Worker === 'function' ? new ReadPool(poolSize()) : null;
  const started = new Array(books.length);
  const start = (i) => {
    if (i >= books.length || started[i]) return;
    const book = books[i];
    const size = kvotFileTooLarge(book.file);
    if (size.tooLarge) { started[i] = Promise.resolve({ skipped: size.reason }); return; }
    if (!reader || !ZIPPED.test(book.name)) { started[i] = Promise.resolve({ fallback: 'SheetJS' }); return; }
    started[i] = (pool ? pool.run(book) : reader.readBook(book)).catch((e) => e.message === 'no worker' ? reader.readBook(book) : Promise.reject(e));
    started[i].catch(() => {});
  };
  try {
    for (const [n, book] of books.entries()) {
      if (job.stopped || job.cleared) break;
      showStatus(`Reading ${n + 1} of ${books.length}: ${book.path}`, false, [], books.length > 1 ? 100 * n / books.length : null);
      for (let k = n; k < n + (pool ? pool.size * 2 : 1); k++) start(k);
      let found;
      try {
        found = await started[n];
        if (found.skipped) { noData.push({ path: book.path, why: found.skipped, error: true }); continue; }
        if (found.fallback) found = readWithSheetJS(await book.file.arrayBuffer(), book);
      } catch (e) {
        if (job.cleared) break;
        noData.push({ path: book.path, why: `could not be read: ${e.message}`, error: true });
        continue;
      }
      read.push(book.path);
      const qc = found.sheets.filter((s) => s.kind === 'qc');
      if (!qc.length && !found.exports.length) noData.push({ path: book.path, why: 'no sheet with ID and the three QC columns, and not an input-set export' });
      for (const s of qc) newSheets.push(`${book.path}|||${s.name}`);
      for (const record of found.records) newRows.push(record);
      for (const e of found.exports) newExports.push({ ...e, path: book.path, folder: book.folder, name: book.name, set: book.name.replace(/\.[^.]+$/, '') });
      if (!pool) await new Promise((resolve) => setTimeout(resolve));
    }
  } finally {
    pool?.close();
  }
  if (job.cleared) return;
  /* A file read again replaces what it gave before, so a folder dropped a
     second time shows its workbooks as they are now, not twice over. */
  const again = new Set(read), againToml = new Set(readTomls.map((t) => t.path));
  const replaced = loadedFiles.filter((p) => again.has(p)).length + tomlFiles.filter((t) => againToml.has(t.path)).length;
  rows = rows.filter((r) => !again.has(r.path)).concat(newRows);
  validSheets = validSheets.filter((k) => !again.has(k.split('|||')[0])).concat(newSheets);
  loadedFiles = loadedFiles.filter((p) => !again.has(p)).concat(read);
  exportFiles = exportFiles.filter((e) => !again.has(e.path)).concat(newExports).sort((a, b) => a.set.localeCompare(b.set, 'en', { numeric: true }) || comparePaths(a.path, b.path));
  tomlFiles = tomlFiles.filter((t) => !againToml.has(t.path)).concat(readTomls);
  rebuildAll();
  $('workspace').classList.add('show');
  $('dropzone').classList.add('compact');
  if (!rows.length && (exportFiles.length || tomlFiles.length) && activeTab === 'overview') activeTab = exportFiles.length ? 'files' : 'cases';
  showTab(activeTab);
  const message = [];
  if (books.length) {
    const folders = new Set(books.filter((b) => again.has(b.path) && b.folder).map((b) => b.folder)).size;
    const values = newExports.reduce((n, e) => n + e.values, 0);
    const gave = [];
    if (newRows.length || !newExports.length) gave.push(`${newRows.length.toLocaleString('en-GB')} data point(s) added`);
    if (newExports.length) gave.push(`${newExports.length} input-set export(s) of ${fmt(values)} value(s)`);
    message.push((job.stopped ? `Stopped after ${read.length} of ${books.length} workbook(s)` : `${read.length} workbook(s) read`)
      + (folders ? ` from ${folders} folder(s)` : '') + `, ${gave.join(' and ')}.`);
  }
  if (readTomls.length) {
    const kinds = readTomls.filter((t) => !t.error).map((t) => t.name.toLowerCase());
    const named = ['link.toml', 'data.toml'].filter((n) => kinds.includes(n));
    const caseCount = kinds.filter((n) => !named.includes(n)).length;
    message.push(`${readTomls.length} TOML file(s) read: ${[`${caseCount} calculation case(s)`, ...named].join(', ')}.`);
  }
  if (replaced) message.push(`${replaced} had been read before, and what they gave then is replaced.`);
  if (noData.length) message.push(`${noData.length} gave no data.`);
  showStatus(message.join(' '), noData.some((f) => f.error) || (!rows.length && !tomlFiles.length && !exportFiles.length), noData);
}

/* ---- The model: parameters, traced exports, input sets and cases ----------------------- */
/*
  A parameter, not a row, is the unit of QC work: an ID in a workbook. An ID
  repeats in a sheet because it is a time series - lobj116.area.aqu is one
  parameter at sixty time points, and reviewing it is one job rather than
  sixty. The same ID in another workbook is another parameter: a variant's
  workbook gives its own value for it, which the variant's input set takes
  in place of the common one, and that value is reviewed in its own right.

  A parameter takes the status of its rows when they agree and Mixed when
  they do not, so a disagreement is visible rather than averaged away. It
  counts as approved only when every row carries an OK status - which is not
  the same as its label, since a parameter approved at PSAR in one row and
  FSAR in another is approved and Mixed at once.
*/
const paramKey = (r) => `${r.path}\u0000${normalize(r.id)}`;
function parameterIndex(data) {
  const byKey = new Map();
  for (const r of data) {
    const id = normalize(r.id);
    if (!id) continue;
    const key = `${r.path}\u0000${id}`;
    let e = byKey.get(key);
    if (!e) { e = { id: String(r.id).trim(), key, path: r.path, file: r.file, folder: r.folder, rows: 0, labels: new Set(), statuses: new Set(), reviewers: new Set(), named: new Set(), sheets: new Set(), blankStatus: 0, blankReviewer: 0 }; byKey.set(key, e); }
    e.rows++;
    const label = statusLabel(r.status);
    e.labels.add(label);
    if (label === BLANK) e.blankStatus++; else e.statuses.add(label);
    const who = display(r.reviewer);
    e.reviewers.add(who);
    if (who === BLANK) e.blankReviewer++; else e.named.add(who);
    e.sheets.add(r.sheet);
  }
  for (const e of byKey.values()) {
    e.status = e.labels.size === 1 ? [...e.labels][0] : MIXED;
    e.approved = !e.blankStatus && e.statuses.size > 0 && [...e.statuses].every(isApproved);
    e.why = [];
    if (e.labels.size > 1) e.why.push('rows disagree on status');
    else if (e.status === BLANK) e.why.push('no status');
    if (e.named.size > 1) e.why.push(`${e.named.size} reviewers`);
    if (!e.named.size) e.why.push('no reviewer');
    else if (e.blankReviewer) e.why.push('rows without a reviewer');
    e.flagged = e.why.length > 0;
  }
  return byKey;
}

/*
  The workbook read that an export's source is. An export names its sources
  by the path they had where it was made, such as
  /Users/someone/data/excel/base_case/x.xlsx; what counts is
  the part below the folder called excel, base_case/x.xlsx, which
  the workbook read must end with, whatever the folder above it is called
  here. Of several, the one in a folder called excel is taken, then the
  shortest path. A source outside an excel folder must end the same as the
  workbook read, as a whole.
*/
function workbookMatcher() {
  const byName = new Map();
  for (const p of new Set(loadedFiles)) { const k = nameOf(p).toLowerCase(); if (!byName.has(k)) byName.set(k, []); byName.get(k).push(p); }
  const cache = new Map();
  return (file) => {
    if (cache.has(file)) return cache.get(file);
    const lower = file.toLowerCase();
    const at = lower.lastIndexOf('/excel/');
    const tail = at >= 0 ? lower.slice(at + 7) : null;
    const found = (byName.get(nameOf(lower)) || []).filter((p) => {
      const q = p.toLowerCase();
      return tail != null ? q === tail || q.endsWith('/' + tail) : lower === q || lower.endsWith('/' + q);
    });
    const rank = (p) => (tail != null && (p.toLowerCase() === 'excel/' + tail || p.toLowerCase().endsWith('/excel/' + tail)) ? 0 : 1);
    found.sort((a, b) => rank(a) - rank(b) || a.length - b.length);
    cache.set(file, found[0] ?? null);
    return found[0] ?? null;
  };
}
/* The calculation-case code keeps source workbooks in a folder called excel; a
   value from anywhere else came from raw data. */
const inExcelFolder = (file) => /(^|\/)excel\//i.test(file);
/* An export's ID is the source ID with the sheet's name before it (unless
   data.toml says otherwise), and a double dot in the source ID is one dot. */
const sourceIdKey = (id) => normalize(id).replace(/\.\./g, '.');

function rebuildAll() {
  const n = rows.length;
  const rowAt = new Map(), byId = new Map();
  const params = [], paramByKey = new Map(), paramOf = new Int32Array(n).fill(-1);
  for (let i = 0; i < n; i++) {
    const r = rows[i];
    rowAt.set(`${r.path}\u0001${r.sheet}\u0001${r.row}`, i);
    const idKey = `${r.path}\u0001${r.sheet}\u0001${sourceIdKey(r.id)}`;
    let list = byId.get(idKey);
    if (!list) byId.set(idKey, list = []);
    list.push(i);
    if (!normalize(r.id)) continue;
    const key = paramKey(r);
    let p = paramByKey.get(key);
    if (p === undefined) { p = params.length; params.push({ key, path: r.path }); paramByKey.set(key, p); }
    paramOf[i] = p;
  }
  model = { rowAt, byId, params, paramByKey, paramOf, whole: parameterIndex(rows), members: new Map(), booksUsedBy: new Map() };
  traceExports();
  rebuildCases();
  invalidate();
}

/*
  Each value of an export, back to its row, by its ID in the sheet the export
  names:
  - an ID on one row is that row;
  - a time point of a time series is the next of the ID's rows: a series is
    exported a point at a time in the order of its rows, and the row the
    export gives a point is its place among the sheet's time series, not its
    row;
  - a value without a time on several rows is the row the export names, when
    that row holds the ID, and otherwise the last of them, the one the
    import kept.
  What cannot be traced is counted by why: raw data, a workbook that was not
  read, a sheet without the QC columns, or an ID no longer in its sheet.
*/
function traceExports() {
  const match = workbookMatcher(), qcSheets = new Set(validSheets);
  for (const e of exportFiles) {
    const t = { traced: 0, notFound: 0, noQc: 0, missing: 0, raw: 0, none: 0, sources: [], workbooks: new Map() };
    const hits = [];
    for (const src of e.sources) {
      const s = { file: src.file, values: src.values, linked: src.linked, kind: '', workbook: null, traced: 0, notFound: 0, noQc: 0 };
      t.sources.push(s);
      if (!src.file) { s.kind = 'none'; t.none += src.values; continue; }
      const wb = src.workbook ? match(src.file) : null;
      if (!wb) {
        s.kind = src.workbook && inExcelFolder(src.file) ? 'missing' : 'raw';
        t[s.kind] += src.values;
        continue;
      }
      s.kind = 'traced'; s.workbook = wb;
      const seen = new Map();
      for (let j = 0; j < src.row.length; j++) {
        const sheet = e.sheetTable[src.sheet[j]], id = e.idTable[src.id[j]];
        /* A sheet read without the QC columns has no QC row to give. */
        if (!qcSheets.has(`${wb}|||${sheet}`)) { s.noQc++; continue; }
        const base = `${wb}\u0001${sheet}\u0001`, key = normalize(id), prefix = normalize(sheet) + '.';
        const listKey = model.byId.has(base + key) ? base + key : key.startsWith(prefix) ? base + key.slice(prefix.length) : null;
        const list = listKey && model.byId.get(listKey);
        let i;
        if (!list) i = undefined;
        else if (list.length === 1) i = list[0];
        else if (src.point[j]) { const k = seen.get(listKey) || 0; seen.set(listKey, k + 1); i = list[Math.min(k, list.length - 1)]; }
        else { const named = model.rowAt.get(base + src.row[j]); i = named !== undefined && list.includes(named) ? named : list[list.length - 1]; }
        if (i === undefined) { s.notFound++; continue; }
        s.traced++;
        hits.push(i);
      }
      t.traced += s.traced; t.notFound += s.notFound; t.noQc += s.noQc;
      t.workbooks.set(wb, (t.workbooks.get(wb) || 0) + s.traced);
      /* Values of a workbook source that were not kept (none are, today) count as not found. */
      const unkept = src.values - src.row.length;
      if (unkept > 0) { s.notFound += unkept; t.notFound += unkept; }
    }
    e.rowIdx = Int32Array.from(new Set(hits)).sort();
    e.trace = t;
    /* Made from workbooks as they no longer are, or from some not read beside
       others that were. With no source workbook read at all, nothing can be told. */
    e.stale = t.notFound > 0 || (t.missing > 0 && rows.length > 0);
    for (const wb of t.workbooks.keys()) { if (!model.booksUsedBy.has(wb)) model.booksUsedBy.set(wb, []); model.booksUsedBy.get(wb).push(e); }
  }
}

/* An input set's name, the key it is known by in the filter. */
const setKey = (name) => String(name).toLowerCase();
/* The input sets the page knows: from the exports read, and from link.toml. */
function knownSets() {
  const out = new Map();
  for (const e of exportFiles) {
    const k = setKey(e.set);
    if (!out.has(k)) out.set(k, { key: k, name: e.set, exports: [], link: false });
    out.get(k).exports.push(e);
  }
  for (const config of cases?.configs || []) {
    if (!config.link) continue;
    for (const set of Object.keys(config.link.defs)) {
      const k = setKey(set);
      if (!out.has(k)) out.set(k, { key: k, name: set, exports: [], link: true });
      else out.get(k).link = true;
    }
  }
  return [...out.values()].sort((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
}
/*
  The rows an input set uses: exactly those its exports trace to, when an
  export of it was read; otherwise the sheets of its data files, as link.toml
  and data.toml name them.
*/
function setMembers(key) {
  if (model.members.has('s:' + key)) return model.members.get('s:' + key);
  let out;
  const exps = exportFiles.filter((e) => setKey(e.set) === key);
  if (exps.length) {
    out = new Set();
    for (const e of exps) for (const i of e.rowIdx) out.add(i);
  } else {
    const keys = new Set();
    for (const config of cases?.configs || []) {
      if (!config.link) continue;
      const name = Object.keys(config.link.defs).find((s) => setKey(s) === key);
      if (!name) continue;
      for (const src of cases.model.setSources(config.link.defs, name, config.link.lists).sources) for (const k of cases.resolveSource(config, cases.model.dataSource(config.data?.defs, src)).keys) keys.add(k);
    }
    out = new Set();
    if (keys.size) rows.forEach((r, i) => { if (keys.has(`${r.path}|||${r.sheet}`)) out.add(i); });
  }
  model.members.set('s:' + key, out);
  return out;
}
/* A case's rows are those of the input sets its parameter files are built as. */
function caseMembers(c) {
  if (model.members.has('c:' + c.key)) return model.members.get('c:' + c.key);
  const out = new Set();
  for (const pf of c.inputs.files) for (const i of setMembers(setKey(pf.file.replace(/\.h5$/i, '')))) out.add(i);
  model.members.set('c:' + c.key, out);
  return out;
}
/* What a case's QC is counted from: its exports, or data.toml's sheets, or nothing. */
function caseSource(c) {
  const names = c.inputs.files.map((pf) => setKey(pf.file.replace(/\.h5$/i, '')));
  if (!names.length) return 'none';
  if (names.every((k) => exportFiles.some((e) => setKey(e.set) === k))) return 'export';
  return 'toml';
}

/*
  The calculation cases, each with the workbooks and sheets its data files
  are read from. Rebuilt whenever TOML files or workbooks arrive or go, since
  either changes which workbook a data file finds.
*/
function rebuildCases() {
  if (!lib || !tomlFiles.length) { cases = null; return; }
  const M = lib.model;
  const configs = M.buildConfigs(tomlFiles);
  const loaded = [...new Set(loadedFiles)];
  const qcSheets = new Set(validSheets);
  const sheetsOf = new Map();
  for (const key of validSheets) { const i = key.indexOf('|||'), path = key.slice(0, i); if (!sheetsOf.has(path)) sheetsOf.set(path, []); sheetsOf.get(path).push(key.slice(i + 3)); }
  const resolved = new Map();
  /* A data file as read here: the workbook found for it, and the sheets of
     that workbook it takes (all, unless data.toml names them). */
  const resolveSource = (config, src) => {
    const id = `${config.folder}\u0000${src.name}`;
    if (resolved.has(id)) return resolved.get(id);
    const wb = M.findWorkbook(src.workbook, loaded, config.folder);
    const wanted = src.sheets && src.sheets.map((n) => n.toLowerCase());
    const sheets = wb.path ? (sheetsOf.get(wb.path) || []).filter((sheet) => !wanted || wanted.includes(sheet.toLowerCase())) : [];
    const out = { ...src, found: wb.path, others: wb.others, keys: sheets.map((sheet) => `${wb.path}|||${sheet}`).filter((k) => qcSheets.has(k)) };
    resolved.set(id, out);
    return out;
  };
  const many = configs.length > 1, list = [];
  for (const config of configs) {
    for (const c of config.cases) {
      const inputs = M.caseInputs(config, c);
      const data = inputs.data.map((src) => resolveSource(config, src));
      list.push({ key: c.path, name: c.name, label: many && config.folder ? `${c.name} (${config.folder})` : c.name, config, file: c, inputs, data, keys: [...new Set(data.flatMap((d) => d.keys))] });
    }
  }
  cases = { model: M, configs, list, resolveSource, checks: configs.map((config) => [config, M.configChecks(config, loaded.length ? loaded : null)]) };
}

/* ---- Filters ------------------------------------------------------------------------------- */
const FACETS = [
  { key: 'status', label: 'Status', title: 'QC status', of: (r) => statusLabel(r.status) },
  { key: 'reviewer', label: 'Reviewer', title: 'QC reviewer', of: (r) => display(r.reviewer) },
  { key: 'folder', label: 'Folder', title: 'Folder', tree: true },
  { key: 'file', label: 'Workbook', title: 'Source workbook', of: (r) => r.path },
  { key: 'sheet', label: 'Sheet', title: 'Sheet', of: sheetKey },
  { key: 'set', label: 'Input set', title: 'Input set', member: true },
  { key: 'case', label: 'Case', title: 'Calculation case', member: true },
];
const facetOf = (key) => FACETS.find((f) => f.key === key);
function facetShown(key) {
  if (key === 'folder') return rows.some((r) => r.folder);
  if (key === 'set') return exportFiles.length > 0 || !!cases?.configs.some((c) => c.link);
  if (key === 'case') return !!cases?.list.length;
  return rows.length > 0;
}
/* Every value a list offers, whatever the other filters: [{ value, label, sub, depth, style }]. */
function facetOptions(key) {
  if (key === 'status') {
    const present = new Set(rows.map((r) => statusLabel(r.status)));
    const rank = (v) => { const i = STATUS_ORDER.indexOf(v); return i < 0 ? (v === BLANK ? 99 : STATUS_ORDER.length) : i; };
    return [...present].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b, 'en')).map((v) => ({ value: v, label: v, style: styleOf(v) }));
  }
  if (key === 'reviewer') return [...new Set(rows.map((r) => display(r.reviewer)))].sort((a, b) => (a === BLANK) - (b === BLANK) || a.localeCompare(b, 'en')).map((v) => ({ value: v, label: v }));
  if (key === 'folder') {
    /* Each folder holding a workbook, and every folder above it, so a branch
       can be chosen whole. Indented by depth, the list reads as the tree it is. */
    const folders = new Set();
    for (const r of rows) for (let f = r.folder; f && !folders.has(f); f = folderOf(f)) folders.add(f);
    return [...folders].sort(comparePaths).map((f) => ({ value: f, label: nameOf(f), depth: f.split('/').length - 1 }));
  }
  if (key === 'file') return [...new Set(rows.map((r) => r.path))].sort(comparePaths).map((p) => ({ value: p, label: nameOf(p), sub: folderOf(p) }));
  if (key === 'sheet') {
    const seen = new Map();
    for (const r of rows) { const k = sheetKey(r); if (!seen.has(k)) seen.set(k, r); }
    return [...seen.keys()].sort(comparePaths).map((k) => { const r = seen.get(k); return { value: k, label: `${r.file} › ${r.sheet}`, sub: r.folder }; });
  }
  if (key === 'set') return knownSets().map((s) => ({ value: s.key, label: s.name, sub: s.exports.length ? (s.exports.some((e) => e.stale) ? 'export out of date' : '') : 'no export read: by data.toml' }));
  if (key === 'case') return (cases?.list || []).map((c) => ({ value: c.key, label: c.label }));
  return [];
}
const facetLabel = (key, value) => facetOptions(key).find((o) => o.value === value)?.label ?? value;

/* Does row i pass the filter of one list? */
function facetTester(key) {
  const sel = filters[key];
  if (!sel.size) return null;
  if (key === 'folder') return (i) => { for (let f = rows[i].folder; f; f = folderOf(f)) if (sel.has(f)) return true; return false; };
  if (key === 'set' || key === 'case') {
    const mask = new Uint8Array(rows.length);
    for (const v of sel) {
      const members = key === 'set' ? setMembers(v) : (() => { const c = cases?.list.find((x) => x.key === v); return c ? caseMembers(c) : new Set(); })();
      for (const i of members) mask[i] = 1;
    }
    return (i) => mask[i] === 1;
  }
  const of = facetOf(key).of;
  return (i) => sel.has(of(rows[i]));
}
/*
  The column filters pick rows; the two parameter switches then keep or drop a
  row by what its parameter looks like as a whole. Both are decided against
  every row the parameter has, not only the ones that survived the column
  filters - a parameter is not suddenly of one mind because a filter hid the
  row that disagreed.
*/
function rowMask(except = null) {
  const n = rows.length, mask = new Uint8Array(n);
  const tests = FACETS.filter((f) => f.key !== except).map((f) => facetTester(f.key)).filter(Boolean);
  const q = normalize($('id-search').value);
  const wantFlagged = $('flagged-only').checked, wantChanged = $('changed-only').checked && snapshot;
  const pFlag = wantFlagged || wantChanged ? paramFlags() : null;
  outer: for (let i = 0; i < n; i++) {
    for (const t of tests) if (!t(i)) continue outer;
    if (q && !normalize(rows[i].id).includes(q)) continue;
    if (pFlag) {
      const p = model.paramOf[i];
      if (p < 0) continue;
      if (wantFlagged && !(pFlag[p] & 1)) continue;
      if (wantChanged && !(pFlag[p] & 2)) continue;
    }
    mask[i] = 1;
  }
  return mask;
}
/* For each parameter: 1 when it needs attention, 2 when it moved since the snapshot. */
function paramFlags() {
  if (model.flags && model.flagsFor === snapshot) return model.flags;
  const flags = new Uint8Array(model.params.length);
  model.params.forEach((p, k) => {
    const e = model.whole.get(p.key);
    if (!e) return;
    if (e.flagged) flags[k] |= 1;
    if (snapshot && movement(e)) flags[k] |= 2;
  });
  model.flags = flags; model.flagsFor = snapshot;
  return flags;
}
function invalidate() { filterVersion++; filterCache = null; }
/* The filters as one value: the lists change only through rerender(), the fields and switches also by hand. */
const filterSignature = () => `${filterVersion}|${$('id-search').value}|${$('flagged-only').checked}|${$('changed-only').checked}`;
function filterState() {
  if (filterCache && filterCache.version === filterSignature()) return filterCache;
  const mask = rowMask();
  const list = [];
  for (let i = 0; i < rows.length; i++) if (mask[i]) list.push(rows[i]);
  filterCache = { version: filterSignature(), mask, list, index: parameterIndex(list) };
  return filterCache;
}
function filtered() { return filterState().list; }
const anyFilter = () => FACETS.some((f) => filters[f.key].size) || !!normalize($('id-search').value) || $('flagged-only').checked || ($('changed-only').checked && !!snapshot);

/* How many parameters each value of a list would keep, with the other filters as they are. */
function facetCounts(key) {
  const mask = rowMask(key), counts = new Map();
  const add = (value, p) => { let s = counts.get(value); if (!s) counts.set(value, s = new Set()); s.add(p); };
  if (key === 'set' || key === 'case') {
    for (const o of facetOptions(key)) {
      const members = key === 'set' ? setMembers(o.value) : caseMembers(cases.list.find((c) => c.key === o.value));
      const s = new Set();
      for (const i of members) if (mask[i] && model.paramOf[i] >= 0) s.add(model.paramOf[i]);
      counts.set(o.value, s);
    }
  } else {
    const of = key === 'folder' ? null : facetOf(key).of;
    for (let i = 0; i < rows.length; i++) {
      if (!mask[i]) continue;
      const p = model.paramOf[i];
      if (p < 0) continue;
      if (of) add(of(rows[i]), p);
      else for (let f = rows[i].folder; f; f = folderOf(f)) add(f, p);
    }
  }
  return new Map([...counts].map(([k, s]) => [k, s.size]));
}
function setFilter(key, values) {
  filters[key] = new Set(values);
  rerender();
}
function clearFilters() {
  for (const f of FACETS) filters[f.key].clear();
  $('id-search').value = '';
  $('flagged-only').checked = false;
  $('changed-only').checked = false;
  rerender();
}

/* The filter buttons and the line of chips saying what is in force. */
function renderFilterBar() {
  const box = $('facets');
  box.innerHTML = FACETS.filter((f) => facetShown(f.key)).map((f) => {
    const n = filters[f.key].size;
    return `<button type="button" class="qc-facet${n ? ' active' : ''}" data-facet="${f.key}" aria-haspopup="dialog" aria-expanded="false">${esc(f.label)}${n ? ` <span class="qc-facet-n">${n}</span>` : ''}</button>`;
  }).join('');
  const chips = [];
  for (const f of FACETS) {
    const sel = [...filters[f.key]];
    if (!sel.length) continue;
    const names = sel.map((v) => facetLabel(f.key, v));
    const text = names.length > 3 ? `${names.slice(0, 2).join(', ')} and ${names.length - 2} more` : names.join(', ');
    chips.push(`<span class="qc-chip" title="${esc(names.join(', '))}"><span class="qc-chip-text"><b>${esc(f.label)}:</b> ${esc(text)}</span><button type="button" data-unfilter="${f.key}" aria-label="Remove the ${esc(f.label.toLowerCase())} filter">×</button></span>`);
  }
  const q = $('id-search').value.trim();
  if (q) chips.push(`<span class="qc-chip"><span class="qc-chip-text"><b>ID contains:</b> ${esc(q)}</span><button type="button" data-unfilter="search" aria-label="Clear the ID search">×</button></span>`);
  if ($('flagged-only').checked) chips.push('<span class="qc-chip"><span class="qc-chip-text">Needing attention</span><button type="button" data-unfilter="flagged" aria-label="Show every parameter">×</button></span>');
  if ($('changed-only').checked && snapshot) chips.push('<span class="qc-chip"><span class="qc-chip-text">Changed since the snapshot</span><button type="button" data-unfilter="changed" aria-label="Show every parameter">×</button></span>');
  const line = $('active-filters');
  line.hidden = !chips.length;
  line.innerHTML = chips.length ? `<span class="qc-active-label">Showing only</span>${chips.join('')}<button type="button" class="link-btn" id="clear-filters">Clear filters</button>` : '';
}

/* The list a filter button opens. */
let openFacet = null;
function openFacetList(key, button) {
  const pop = $('facet-pop');
  if (typeof pop.showPopover !== 'function') return;
  openFacet = key;
  const f = facetOf(key);
  const options = facetOptions(key), counts = facetCounts(key), sel = filters[key];
  const long = options.length > 8;
  const hint = { folder: 'A folder takes its subfolders along.', set: 'The rows each input set uses: traced from its export, or the sheets data.toml names when none was read.', case: 'The rows of the input sets the case reads.', sheet: 'Sheets with ID and the three QC columns.' }[key] || '';
  pop.innerHTML = `<div class="qc-pop-head"><span class="qc-pop-title">${esc(f.title)}</span><span class="muted">parameters</span></div>`
    + (hint ? `<div class="qc-pop-hint">${esc(hint)}</div>` : '')
    + (long ? `<div class="qc-pop-find"><input type="search" placeholder="Find in the list" aria-label="Find in the list" autocomplete="off"></div>` : '')
    + `<ul class="qc-pop-list" role="group" aria-label="${esc(f.title)}">${options.map((o) => {
      const n = counts.get(o.value) || 0;
      const sw = o.style ? `<i class="opt-sw sw${o.style === 'blank' ? ' blank' : ''}" style="--c:var(--st-${o.style})"></i>` : '<i class="opt-sw none"></i>';
      const indent = o.depth ? ` style="padding-left:${6 + 14 * o.depth}px"` : '';
      return `<li class="${n ? '' : 'zero'}" data-text="${esc((o.label + ' ' + (o.sub || '')).toLowerCase())}"><label${indent}><input type="checkbox" value="${esc(o.value)}"${sel.has(o.value) ? ' checked' : ''}>${sw}<span class="opt-text">${esc(o.label)}${o.sub ? ` <span class="opt-sub">${esc(o.sub)}</span>` : ''}</span><span class="opt-n">${fmt(n)}</span></label></li>`;
    }).join('')}</ul>`
    + `<div class="qc-pop-empty" hidden>Nothing in the list matches.</div>`
    + `<div class="qc-pop-foot"><span>${sel.size ? `${sel.size} chosen` : 'None chosen: all are shown'}</span><button type="button" class="link-btn" data-pop-clear>Clear</button></div>`;
  pop.setAttribute('aria-label', `Filter by ${f.title.toLowerCase()}`);
  placePopover(pop, button, false);
  for (const b of document.querySelectorAll('.qc-facet')) b.setAttribute('aria-expanded', String(b === button));
  if (!pop.matches(':popover-open')) pop.showPopover();
  placePopover(pop, button, true);
  (pop.querySelector('.qc-pop-find input') || pop.querySelector('.qc-pop-list input'))?.focus({ preventScroll: true });
}
/* Under its button, left edges together, or above it where the window has no room below. */
function placePopover(pop, button, measured) {
  const r = button.getBoundingClientRect(), w = document.documentElement.clientWidth;
  if (!measured) {
    pop.style.top = `${Math.round(r.bottom + 4)}px`;
    pop.style.left = `${Math.max(8, Math.round(r.left))}px`;
    pop.style.right = 'auto';
    return;
  }
  const m = pop.getBoundingClientRect();
  if (m.right > w - 8) pop.style.left = `${Math.max(8, Math.round(w - 8 - m.width))}px`;
  if (m.bottom > window.innerHeight - 8 && r.top - m.height - 4 > 8) pop.style.top = `${Math.round(r.top - 4 - m.height)}px`;
}
function placeMenu(menu, button) {
  const r = button.getBoundingClientRect();
  menu.style.top = `${Math.round(r.bottom + 4)}px`;
  menu.style.right = `${Math.max(8, Math.round(document.documentElement.clientWidth - r.right))}px`;
  menu.style.left = 'auto';
}

/* ---- Rendering ---------------------------------------------------------------------------- */
/* Any change to what is being shown starts the window again at the top. */
function rerender() { tableLimit = PAGE_SIZE; invalidate(); render(); }
function render() {
  if (!model) return;
  const st = filterState();
  /* The Folder column, and its filter, only once some workbook came with its folder. */
  $('workspace').classList.toggle('no-folders', !rows.some((r) => r.folder));
  $('workspace').classList.toggle('no-cases', !cases?.list.length);
  renderLoaded();
  renderFilterBar();
  renderTabCounts(st);
  if (activeTab === 'overview') renderOverview(st);
  else if (activeTab === 'files') renderFiles(st);
  else if (activeTab === 'rows') renderRows(st);
  else if (activeTab === 'cases') renderCases(st);
  fitBarLabels();
}
function renderLoaded() {
  /* The snapshot switch only once there is a snapshot to compare with, and
     the switches and the search only once there are rows to narrow. */
  $('changed-toggle').hidden = !snapshot || !rows.length;
  $('flagged-only').closest('label').hidden = !rows.length;
  $('id-search').closest('.qc-search').hidden = !rows.length;
  const sourcePaths = new Set(rows.map((r) => r.path)), exportPaths = new Set(exportFiles.map((e) => e.path));
  const sources = sourcePaths.size;
  const others = new Set(loadedFiles.filter((p) => !sourcePaths.has(p) && !exportPaths.has(p))).size;
  const pills = [];
  if (sources) pills.push(`<span class="qc-pill"><b>${fmt(sources)}</b> source workbook${sources === 1 ? '' : 's'}</span>`);
  if (exportFiles.length) pills.push(`<span class="qc-pill"><b>${fmt(exportFiles.length)}</b> input-set export${exportFiles.length === 1 ? '' : 's'}</span>`);
  if (tomlFiles.length) pills.push(`<span class="qc-pill"><b>${fmt(tomlFiles.length)}</b> TOML file${tomlFiles.length === 1 ? '' : 's'}</span>`);
  if (others > 0) pills.push(`<button type="button" class="qc-pill qc-pill-btn" id="notes-btn" popovertarget="notes-pop"><b>${fmt(others)}</b> workbook${others === 1 ? '' : 's'} without QC columns</button>`);
  const folderCount = new Set(loadedFiles.map(folderOf).filter(Boolean)).size;
  $('file-info').innerHTML = pills.join('') + (folderCount ? `<span class="muted">in ${plural(folderCount, 'folder')}</span>` : '');
}
/* A view shows only once there is something for it: rows for the overview and
   the data points, rows or exports for the files, TOML files for the cases. */
const tabAvailable = (name) => name === 'cases' ? !!cases : name === 'files' ? rows.length > 0 || exportFiles.length > 0 : rows.length > 0;
function renderTabCounts(st) {
  for (const name of ['overview', 'files', 'rows', 'cases']) $(`tab-btn-${name}`).hidden = !tabAvailable(name);
  const books = new Set(st.list.map((r) => r.path)).size;
  $('files-count').textContent = fmt(books + visibleExports(st).length);
  $('rows-count').textContent = fmt(st.list.length);
  $('cases-count').textContent = cases ? fmt(cases.list.length) : '';
}
function showTab(name) {
  const tabs = { overview: 'tab-overview', files: 'tab-files', rows: 'tab-rows', cases: 'tab-cases' };
  if (!tabs[name] || (model && !tabAvailable(name))) name = ['overview', 'files', 'cases'].find(tabAvailable) || 'overview';
  activeTab = name;
  for (const [key, id] of Object.entries(tabs)) {
    const on = key === name;
    $(`tab-btn-${key}`).setAttribute('aria-selected', String(on));
    $(`tab-btn-${key}`).tabIndex = on ? 0 : -1;
    $(id).hidden = !on;
  }
  render();
}

/* The status of each parameter, counted in bar order: [label, count] for those present. */
function statusCounts(params) {
  const counts = new Map();
  for (const e of params) counts.set(e.status, (counts.get(e.status) || 0) + 1);
  const rest = [...counts.keys()].filter((k) => !BAR_ORDER.includes(k) && k !== MIXED && k !== BLANK).sort((a, b) => a.localeCompare(b, 'en'));
  return [...BAR_ORDER, ...rest, MIXED, BLANK].filter((k) => counts.get(k)).map((k) => [k, counts.get(k)]);
}
/* A bar of the parts of one whole: a status per part, in bar order; tall ones print their share inside. */
function segBar(parts, { tall = false, dense = false, what = 'parameters', label = '' } = {}) {
  const total = parts.reduce((n, [, c]) => n + c, 0);
  if (!total) return '<div class="seg-empty" role="img" aria-label="nothing to count"></div>';
  const aria = parts.map(([k, n]) => `${k} ${fmt(n)}`).join(', ');
  return `<div class="seg${tall ? ' tall' : ''}${dense ? ' dense' : ''}" role="img" aria-label="${esc((label ? label + ': ' : '') + aria)}">` + parts.map(([k, n]) => {
    const style = styleOf(k);
    const tip = `${k}: ${fmt(n)} ${what} (${pct(n, total)})`;
    return `<span class="seg-part ${style}" style="--n:${n};--c:var(--st-${style});--ink:var(--st-ink-${style})" data-tip="${esc(tip)}"${tall ? ' tabindex="0"' : ''}>${tall ? `<span class="seg-label">${esc(pct(n, total))}</span>` : ''}</span>`;
  }).join('') + '</div>';
}
/* A share printed inside a part that cannot hold it is not printed at all. */
function fitBarLabels() {
  for (const label of document.querySelectorAll('.seg.tall .seg-label')) {
    label.hidden = false;
    const part = label.parentElement;
    if (label.offsetWidth + 12 > part.clientWidth) label.hidden = true;
  }
}
/* Approved against the rest, for a line of a table. */
function shareBar(ok, total) {
  if (!total) return '<div class="seg-empty"></div>';
  const tip = (what, n) => `${what}: ${fmt(n)} of ${fmt(total)} (${pct(n, total)})`;
  return `<div class="seg dense" role="img" aria-label="${esc(`${fmt(ok)} of ${fmt(total)} approved`)}">`
    + (ok ? `<span class="seg-part" style="--n:${ok};--c:var(--st-upsar)" data-tip="${esc(tip('Approved', ok))}"></span>` : '')
    + (total - ok ? `<span class="seg-part" style="--n:${total - ok};--c:var(--st-prelim)" data-tip="${esc(tip('Not approved', total - ok))}"></span>` : '') + '</div>';
}
const approvedText = (params) => {
  const n = params.length, ok = params.filter((e) => e.approved).length;
  return n ? `${fmt(ok)} of ${plural(n, 'parameter')} approved` : 'no parameter';
};

/* ---- Overview ------------------------------------------------------------------------------ */
function renderOverview(st) {
  const data = st.list, params = [...st.index.values()];
  const approved = params.filter((e) => e.approved).length;
  const counts = statusCounts(params);
  const review = counts.find(([k]) => k === 'In review')?.[1] || 0;
  const flagged = params.filter((e) => model.whole.get(e.key)?.flagged).length;
  $('ok-percent').textContent = pct(approved, params.length);
  $('status-note').textContent = params.length
    ? `${fmt(approved)} of ${plural(params.length, 'parameter')} approved (OK-PSAR, OK-UPSAR or OK-FSAR), ${fmt(review)} in review.`
    : 'No parameter matches the filters.';
  $('status-bar').innerHTML = segBar(counts, { tall: true, label: 'QC status of the parameters' });
  $('status-legend').innerHTML = counts.map(([k, n]) => {
    const style = styleOf(k), filterable = k !== MIXED;
    const body = `<i class="sw${style === 'blank' ? ' blank' : ''}" style="--c:var(--st-${style})"></i>${esc(k)} <span class="lg-n">${fmt(n)}</span>`;
    return `<li>${filterable ? `<button type="button" data-status="${esc(k)}" title="Show only ${esc(k)}">${body}</button>` : body}</li>`;
  }).join('');

  const books = new Set(data.map((r) => r.path)).size, sheets = new Set(data.map((r) => `${r.path}|||${r.sheet}`)).size;
  const reviewers = new Set(params.flatMap((e) => [...e.named]));
  $('count-ids').textContent = fmt(params.length);
  $('count-rows-sub').textContent = `${fmt(data.length)} row${data.length === 1 ? '' : 's'}`;
  $('count-books').textContent = fmt(books);
  $('count-sheets-sub').textContent = plural(sheets, 'sheet');
  $('count-reviewers').textContent = fmt(reviewers.size);
  $('count-comments-sub').textContent = `${fmt(data.filter((r) => String(r.comment).trim()).length)} rows with a comment`;
  $('count-flagged').textContent = fmt(flagged);
  $('count-flagged').closest('.tile').classList.toggle('flagged', flagged > 0);
  $('count-flagged-sub').textContent = flagged ? 'see the list below' : 'nothing to look at';
  $('tile-sets').hidden = !exportFiles.length;
  if (exportFiles.length) {
    const vis = visibleExports(st);
    const stale = vis.filter((x) => x.e.stale).length;
    $('count-sets').textContent = fmt(vis.length);
    $('count-sets-sub').innerHTML = `${fmt(vis.length - stale)} up to date` + (stale ? ` · <button type="button" class="link-btn" data-goto-tab="files">${fmt(stale)} out of date</button>` : '');
  }
  renderMatrix(st.index);
  renderConflicts(st.index);
  renderSnapshot(st.index);
}

/*
  Who holds what, which took one selection per person to answer before. A
  parameter with two reviewers is counted under both: the question is what is
  on each person's plate, and it is on both of theirs.
*/
function reviewerMatrix(index) {
  const present = new Set(), byReviewer = new Map();
  for (const e of index.values()) {
    present.add(e.status);
    for (const reviewer of e.reviewers) {
      let row = byReviewer.get(reviewer);
      if (!row) { row = { reviewer, total: 0, approved: 0, cells: new Map() }; byReviewer.set(reviewer, row); }
      row.total++; if (e.approved) row.approved++;
      row.cells.set(e.status, (row.cells.get(e.status) || 0) + 1);
    }
  }
  const tail = [...present].filter((v) => v !== MIXED && v !== BLANK && !STATUS_ORDER.includes(v)).sort((a, b) => a.localeCompare(b, 'en'));
  const columns = [...STATUS_ORDER.filter((s) => present.has(s)), ...tail];
  if (present.has(MIXED)) columns.push(MIXED);
  if (present.has(BLANK)) columns.push(BLANK);
  return { columns, rows: [...byReviewer.values()].sort((a, b) => b.total - a.total || a.reviewer.localeCompare(b.reviewer, 'en')) };
}
function renderMatrix(index) {
  const m = reviewerMatrix(index);
  if (!m.rows.length) { $('reviewer-matrix').innerHTML = '<div class="empty">Nothing to show.</div>'; return; }
  const head = '<tr><th>Reviewer</th>' + m.columns.map((c) => `<th><i class="sw${styleOf(c) === 'blank' ? ' blank' : ''}" style="--c:var(--st-${styleOf(c)})"></i>${esc(c)}</th>`).join('') + '<th>Total</th><th class="share">Approved</th></tr>';
  const body = m.rows.map((row) => {
    const cells = m.columns.map((c) => {
      const n = row.cells.get(c) || 0;
      /* Mixed is a parameter's label, not a row's, so its cells narrow to the reviewer alone. */
      const filterable = c !== MIXED;
      const what = filterable ? `${row.reviewer}, ${c}` : row.reviewer;
      return n ? `<td class="cell" data-reviewer="${esc(row.reviewer)}" data-status="${filterable ? esc(c) : ''}" title="Show ${esc(what)}">${fmt(n)}</td>` : '<td class="zero">0</td>';
    }).join('');
    return `<tr><td>${esc(row.reviewer)}</td>${cells}<td>${fmt(row.total)}</td><td class="share">${shareBar(row.approved, row.total)}</td></tr>`;
  }).join('');
  $('reviewer-matrix').innerHTML = `<div class="matrix-wrap"><table class="matrix"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

/* The parameters worth a second look, the most serious first: rows that
   disagree on status, no status, more than one reviewer, or none. */
function renderConflicts(index) {
  const flagged = [...index.values()].map((e) => model.whole.get(e.key)).filter((e) => e && e.flagged);
  if (!flagged.length) {
    $('conflict-body').innerHTML = '<div class="empty">Every parameter has one status and one reviewer.</div>';
    return;
  }
  const groups = [['rows disagree on status', 'Rows disagree on status'], ['no status', 'No status'], ['reviewers', 'More than one reviewer'], ['no reviewer', 'No reviewer named'], ['rows without a reviewer', 'Rows without a reviewer']]
    .map(([needle, label]) => [label, flagged.filter((e) => e.why.some((w) => w.includes(needle))).length]).filter(([, n]) => n);
  const rank = (e) => e.why[0] === 'rows disagree on status' ? 0 : e.why[0] === 'no status' ? 1 : 2;
  const list = flagged.sort((a, b) => rank(a) - rank(b) || b.rows - a.rows || a.id.localeCompare(b.id, 'en')).slice(0, 200);
  $('conflict-body').innerHTML = `<div class="flag-groups">${groups.map(([label, n]) => `<div class="flag-group">${esc(label)}<span class="fg-n">${fmt(n)}</span></div>`).join('')}</div>`
    + `<div class="flag-list">${list.map((e) => `<button type="button" class="flag-item" data-id="${esc(e.id)}" data-path="${esc(e.path)}"><span class="flag-id">${esc(e.id)}</span><span class="flag-why">${esc(e.why.join(' · '))}</span><span class="flag-where">${esc(e.path)}</span></button>`).join('')}</div>`
    + `<p class="note">${plural(flagged.length, 'parameter')} flagged${list.length < flagged.length ? `, the first ${list.length} listed` : ''}. Choose one to see its rows.</p>`;
}

function bars(target, items, total) { $(target).innerHTML = items.length ? items.map(([label, n]) => `<div class="bar-row"><div class="bar-label" title="${esc(label)}">${esc(label)}</div><div class="bar-track"><div class="bar" style="width:${total ? 100 * n / total : 0}%"></div></div><div class="bar-count">${fmt(n)}</div></div>`).join('') : '<div class="empty">Nothing to show.</div>'; }

/*
  A snapshot is the parameter statuses as they stood, written to a file the
  same way the CSV is - nothing leaves the browser, and a file can be kept
  beside the workbooks or passed to somebody else. Dropping files shows where
  the work stands; comparing against a snapshot shows which way it is going,
  which is the difference between a summary and keeping track.

  A version 2 snapshot keys a parameter by its workbook and ID; one of
  version 1 knew IDs only, and is compared ID by ID.
*/
function snapshotFrom(index) {
  const params = {};
  for (const [key, e] of index) params[key] = { path: e.path, id: e.id, status: e.status, reviewers: [...e.reviewers].sort() };
  return { kind: 'skb-qc-snapshot', version: 2, saved: new Date().toISOString(), count: index.size, params };
}
function download(blob, name) {
  const url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}
function saveSnapshot() {
  download(new Blob([JSON.stringify(snapshotFrom(parameterIndex(rows)))], { type: 'application/json' }), `skb_qc_snapshot_${new Date().toISOString().slice(0, 10)}.json`);
}
async function loadSnapshot(file) {
  try {
    const parsed = JSON.parse(await file.text());
    if (!parsed || parsed.kind !== 'skb-qc-snapshot' || !parsed.params) throw new Error('not a snapshot saved by this page');
    /* Each parameter of a version 2 snapshot also by its ID, to find it under another folder. */
    parsed.byId = new Map();
    if (parsed.version >= 2) for (const [key, p] of Object.entries(parsed.params)) { const id = normalize(p.id); if (!parsed.byId.has(id)) parsed.byId.set(id, []); parsed.byId.get(id).push({ key, ...p }); }
    snapshot = parsed;
    $('changed-only').disabled = false;
    showStatus(`Comparing with the snapshot of ${new Date(parsed.saved).toLocaleString('en-GB')} (${fmt(parsed.count)} parameters).`);
  } catch (e) {
    snapshot = null; $('changed-only').checked = false; $('changed-only').disabled = true;
    showStatus(`Could not read that snapshot: ${e.message}`, true);
  }
  if (model) { model.flags = null; rerender(); }
}
/* The snapshot's key for a parameter: its own, or, in a version 2 snapshot, that
   of its ID in a workbook whose path ends as its does (the folder added from
   higher up, or lower down, this time). */
function snapshotKey(e) {
  if (!snapshot) return null;
  if (!(snapshot.version >= 2)) { const k = normalize(e.id); return k in snapshot.params ? k : null; }
  if (e.key in snapshot.params) return e.key;
  const lower = e.path.toLowerCase();
  const near = (snapshot.byId.get(normalize(e.id)) || []).filter((p) => { const q = String(p.path).toLowerCase(); return q.endsWith('/' + lower) || lower.endsWith('/' + q); });
  return near.length === 1 ? near[0].key : null;
}
const snapshotRecord = (e) => { const k = snapshotKey(e); return k == null ? null : snapshot.params[k]; };
/* What became of one parameter since the snapshot: null when nothing did. */
function movement(e) {
  if (!snapshot) return null;
  const was = snapshotRecord(e);
  if (!was) return { kind: 'new', from: null, to: e.status };
  if (was.status !== e.status) return { kind: 'moved', from: was.status, to: e.status };
  const now = [...e.reviewers].sort().join(', '), before = (was.reviewers || []).join(', ');
  if (now !== before) return { kind: 'reviewer', from: before, to: now };
  return null;
}
function renderSnapshot(index) {
  $('snapshot-panel').hidden = !snapshot;
  if (!snapshot) return;
  const transitions = new Map(); let added = 0, reviewerChanges = 0;
  for (const e of index.values()) {
    const move = movement(e);
    if (!move) continue;
    if (move.kind === 'new') { added++; continue; }
    if (move.kind === 'reviewer') { reviewerChanges++; continue; }
    const key = `${move.from} → ${move.to}`;
    transitions.set(key, (transitions.get(key) || 0) + 1);
  }
  /* Parameters in the snapshot that this selection no longer contains. Only
     meaningful with no filters narrowing the set, so it says which it is. */
  const kept = new Set([...index.values()].map(snapshotKey).filter((k) => k != null));
  const gone = Object.keys(snapshot.params).filter((k) => !kept.has(k)).length;
  const when = new Date(snapshot.saved).toLocaleString('en-GB');
  const items = [...transitions].sort((a, b) => b[1] - a[1]);
  const total = items.reduce((n, [, c]) => n + c, 0);
  const lines = [`<p class="note" style="margin-top:0">The snapshot of ${esc(when)}, ${fmt(snapshot.count)} parameters${anyFilter() ? '; the filters narrow what is compared' : ''}.</p>`];
  if (items.length) lines.push('<div id="move-bars"></div>');
  const extra = [];
  if (added) extra.push(`<span class="move-in">${fmt(added)}</span> not in the snapshot`);
  if (gone) extra.push(`<span class="move-out">${fmt(gone)}</span> in the snapshot but not here`);
  if (reviewerChanges) extra.push(`${fmt(reviewerChanges)} changed reviewer`);
  if (!total && !extra.length) lines.push('<div class="empty">Nothing has moved.</div>');
  if (extra.length) lines.push(`<p class="note">${extra.join(' · ')}</p>`);
  $('snapshot-body').innerHTML = lines.join('');
  if (items.length) bars('move-bars', items, total);
}

/* ---- Files ---------------------------------------------------------------------------------- */
/* The source workbooks with rows that match, each with its parameters' statuses. */
function bookSummaries(st) {
  const byPath = new Map();
  for (const r of st.list) {
    let b = byPath.get(r.path);
    if (!b) { b = { path: r.path, folder: r.folder, file: r.file, rows: 0, sheets: new Map(), params: [] }; byPath.set(r.path, b); }
    b.rows++;
    b.sheets.set(r.sheet, (b.sheets.get(r.sheet) || 0) + 1);
  }
  for (const e of st.index.values()) byPath.get(e.path)?.params.push(e);
  return [...byPath.values()];
}
/* The input-set exports, each with the matching rows it traces to. */
function exportSummaries(st) {
  return st.exports ??= exportFiles.map((e) => ({ e, ...paramsOfRows(e.rowIdx, st) }));
}
/* The parameters (as the filters leave them) of these rows, and how many of the rows match. */
function paramsOfRows(members, st = filterState()) {
  const seen = new Set(), params = [];
  let matched = 0;
  for (const i of members) {
    if (!st.mask[i]) continue;
    matched++;
    const p = model.paramOf[i];
    if (p < 0 || seen.has(p)) continue;
    seen.add(p);
    const e = st.index.get(model.params[p].key);
    if (e) params.push(e);
  }
  return { matched, params };
}
function visibleExports(st) {
  const sets = filters.set;
  const filtering = anyFilter() && rows.length;
  return exportSummaries(st).filter((x) => (!sets.size || sets.has(setKey(x.e.set))) && (!filtering || x.matched > 0)).slice();
}
function sortRows(list, by, keyOf) {
  return list.sort((a, b) => {
    const x = keyOf(a, by.key), y = keyOf(b, by.key);
    const c = typeof x === 'string' ? comparePaths(x, y) : x - y;
    return by.dir * c || comparePaths(keyOf(a, 'name0'), keyOf(b, 'name0'));
  });
}
function sortHead(table, key, label, cls = '') {
  const by = sortBy[table];
  const sorted = by.key === key ? (by.dir > 0 ? 'ascending' : 'descending') : 'none';
  return `<th class="${cls}" aria-sort="${sorted}"><button type="button" class="sort" data-sort="${table}:${key}">${esc(label)}</button></th>`;
}
function reviewersText(params) {
  const counts = new Map();
  for (const e of params) for (const r of e.reviewers) counts.set(r, (counts.get(r) || 0) + 1);
  const list = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'en')).map(([r]) => r);
  return list.length > 3 ? `${list.slice(0, 2).join(', ')} +${list.length - 2}` : list.join(', ');
}
function renderFiles(st) {
  const books = bookSummaries(st);
  const keyOf = (b, k) => k === 'path' || k === 'name0' ? b.path : k === 'name' ? b.file : k === 'params' ? b.params.length : k === 'rows' ? b.rows : k === 'open' ? b.params.length - b.params.filter((e) => e.approved).length : 0;
  sortRows(books, sortBy.books, keyOf);
  const showSets = exportFiles.length > 0;
  $('books-section').hidden = !rows.length;
  $('books-info').textContent = rows.length ? `${plural(books.length, 'workbook')}${anyFilter() ? ' with rows that match' : ''}` : '';
  $('books-head').innerHTML = `<tr>${sortHead('books', 'path', 'Workbook')}<th>Sheets</th>${sortHead('books', 'params', 'Parameters', 'num')}${sortHead('books', 'rows', 'Rows', 'num')}${sortHead('books', 'open', 'QC status')}<th>Reviewers</th>${showSets ? '<th>Used in</th>' : ''}</tr>`;
  const cols = showSets ? 7 : 6;
  $('books-body').innerHTML = books.length ? books.map((b) => {
    const open = expanded.book.has(b.path);
    const sheets = [...b.sheets.keys()];
    const used = model.booksUsedBy.get(b.path) || [];
    const main = `<tr data-book="${esc(b.path)}"><td><button type="button" class="file-name" aria-expanded="${open}" data-open-book="${esc(b.path)}"><span class="fn">${esc(b.file)}</span></button>${b.folder ? `<span class="file-folder">${esc(b.folder)}</span>` : ''}</td>`
      + `<td>${sheets.length > 2 ? `${esc(sheets.slice(0, 2).join(', '))} +${sheets.length - 2}` : esc(sheets.join(', '))}</td>`
      + `<td class="num">${fmt(b.params.length)}</td><td class="num">${fmt(b.rows)}</td>`
      + `<td class="status-cell">${segBar(statusCounts(b.params), { label: approvedText(b.params) })}<div class="status-text">${esc(approvedText(b.params))}</div></td>`
      + `<td class="who">${esc(reviewersText(b.params))}</td>`
      + (showSets ? `<td class="who">${used.length ? plural(used.length, 'input set') : '<span class="muted">none read</span>'}</td>` : '') + '</tr>';
    return main + (open ? bookDetail(b, used, cols) : '');
  }).join('') : `<tr><td colspan="${cols}" class="empty">No source workbook has rows that match.</td></tr>`;

  $('sets-section').hidden = !exportFiles.length;
  $('sets-section').classList.toggle('qc-section-gap', rows.length > 0);
  if (!exportFiles.length) return;
  const vis = visibleExports(st);
  /* At first the exports that are up to date, by name, then those that are not. */
  const keyOfSet = (x, k) => k === 'name' || k === 'name0' ? x.e.set : k === 'state' ? (x.e.stale ? 1 : 0) : k === 'values' ? x.e.values : k === 'traced' ? share(x.e.trace.traced, x.e.values) : k === 'params' ? x.params.length : k === 'open' ? x.params.length - x.params.filter((e) => e.approved).length : 0;
  sortRows(vis, sortBy.sets, keyOfSet);
  const hiddenCount = exportFiles.length - vis.length;
  const stale = vis.filter((x) => x.e.stale).length;
  $('sets-info').textContent = `${plural(vis.length, 'export')}${anyFilter() && rows.length ? ' with values that match' : ''}${stale ? `, ${stale} out of date` : ''}`
    + (rows.length ? '' : ' — add the Excel folder to trace their values to the QC rows');
  const usedBy = casesBySet(), linked = new Set(knownSets().filter((s) => s.link).map((s) => s.key));
  $('sets-head').innerHTML = `<tr>${sortHead('sets', 'name', 'Input set')}${sortHead('sets', 'values', 'Values', 'num')}${sortHead('sets', 'traced', 'Traced to a QC row')}${sortHead('sets', 'params', 'Parameters', 'num')}${sortHead('sets', 'open', 'QC status')}${cases ? '<th>Cases</th>' : ''}</tr>`;
  const scols = cases ? 6 : 5;
  $('sets-body').innerHTML = vis.length ? vis.map((x) => {
    const e = x.e, t = e.trace, open = expanded.set.has(e.path);
    const caseNames = usedBy.get(setKey(e.set)) || [];
    const flags = [];
    if (t.missing && rows.length) flags.push(`<span class="flag warn">${fmt(t.missing)} from workbooks not read</span>`);
    if (t.notFound) flags.push(`<span class="flag bad">${fmt(t.notFound)} rows not in their workbook</span>`);
    if (t.noQc) flags.push(`<span class="flag warn">${fmt(t.noQc)} from sheets without QC columns</span>`);
    if (cases && !linked.has(setKey(e.set))) flags.push('<span class="flag plain">not in link.toml</span>');
    const untraced = [[t.raw + t.none, 'from raw data'], [t.missing, 'from workbooks not read'], [t.noQc, 'from sheets without QC columns'], [t.notFound, 'not found in their workbook']].filter(([n]) => n).map(([n, w]) => `${fmt(n)} ${w}`);
    const main = `<tr data-set="${esc(e.path)}"><td><button type="button" class="file-name" aria-expanded="${open}" data-open-set="${esc(e.path)}"><span class="fn">${esc(e.set)}</span></button><span class="file-folder">${esc(e.path)}</span>${flags.length ? `<div style="margin:4px 0 0 14px">${flags.join('')}</div>` : ''}</td>`
      + `<td class="num">${fmt(e.values)}</td>`
      + `<td>${fmt(t.traced)} <span class="muted">(${pct(t.traced, e.values)})</span>${untraced.length ? `<div class="trace-line">${esc(untraced.join(' · '))}</div>` : ''}</td>`
      + `<td class="num">${fmt(x.params.length)}</td>`
      + `<td class="status-cell">${x.params.length ? `${segBar(statusCounts(x.params), { label: approvedText(x.params) })}<div class="status-text">${esc(approvedText(x.params))}</div>` : `<span class="muted">${rows.length ? (t.traced ? 'no value matches' : 'none traced') : 'add the source workbooks'}</span>`}</td>`
      + (cases ? `<td class="who">${caseNames.length ? esc(caseNames.length > 4 ? `${caseNames.slice(0, 3).join(', ')} +${caseNames.length - 3}` : caseNames.join(', ')) : '<span class="muted">none</span>'}</td>` : '') + '</tr>';
    return main + (open ? setDetail(x, scols) : '');
  }).join('') : `<tr><td colspan="${scols}" class="empty">No input set has values that match.</td></tr>`;
  $('sets-hidden').hidden = !hiddenCount;
  $('sets-hidden').textContent = hiddenCount ? `${plural(hiddenCount, 'export')} not listed: ${filters.set.size ? 'not chosen in the Input set filter' : ''}${filters.set.size && anyFilter() ? ', or ' : ''}${anyFilter() ? 'no value that matches the filters' : ''}.` : '';
}
function casesBySet() {
  const out = new Map();
  for (const c of cases?.list || []) for (const pf of c.inputs.files) {
    const k = setKey(pf.file.replace(/\.h5$/i, ''));
    if (!out.has(k)) out.set(k, []);
    if (!out.get(k).includes(c.name)) out.get(k).push(c.name);
  }
  return out;
}
function bookDetail(b, used, cols) {
  const sheets = [...b.sheets].map(([sheet, n]) => {
    const ps = b.params.filter((e) => e.sheets.has(sheet));
    return `<tr><td>${esc(sheet)}</td><td class="num">${fmt(ps.length)}</td><td class="num">${fmt(n)}</td><td>${esc(approvedText(ps))}</td></tr>`;
  }).join('');
  const sets = used.map((e) => `<button type="button" class="link-btn" data-filter-set="${esc(setKey(e.set))}">${esc(e.set)}</button>`).join(', ');
  return `<tr class="detail"><td colspan="${cols}"><h3>Sheets</h3><table class="sub-table"><thead><tr><th>Sheet</th><th class="num">Parameters</th><th class="num">Rows</th><th>Approved</th></tr></thead><tbody>${sheets}</tbody></table>`
    + (used.length ? `<h3>Input sets that use its rows</h3><div>${sets}</div>` : '')
    + `<div class="detail-actions"><button type="button" class="btn small" data-filter-book="${esc(b.path)}">Filter to this workbook</button><button type="button" class="btn small" data-rows-book="${esc(b.path)}">Show its data points</button></div></td></tr>`;
}
function setDetail(x, cols) {
  const e = x.e;
  const kindText = { traced: 'traced', missing: 'workbook not read', raw: 'raw data', none: 'no source recorded' };
  const srcs = [...e.trace.sources].sort((a, b) => b.values - a.values).map((s) => {
    const name = s.workbook || s.file || '(no file recorded)';
    const state = s.kind === 'traced' ? `${fmt(s.traced)} traced${s.noQc ? `, <span class="lvl warning">${fmt(s.noQc)} in sheets without QC columns</span>` : ''}${s.notFound ? `, <span class="lvl warning">${fmt(s.notFound)} not found</span>` : ''}` : esc(kindText[s.kind]);
    const linked = s.linked.length ? `<span class="muted">${esc(s.linked.map(nameOf).join(', '))}</span>` : '';
    return `<tr><td class="mono" style="overflow-wrap:anywhere">${esc(name)}</td><td class="num">${fmt(s.values)}</td><td>${state}</td><td>${linked}</td></tr>`;
  }).join('');
  return `<tr class="detail"><td colspan="${cols}"><h3>Where its values come from</h3><table class="sub-table"><thead><tr><th>Source</th><th class="num">Values</th><th>Traced</th><th>Read as</th></tr></thead><tbody>${srcs}</tbody></table>`
    + `<div class="detail-actions"><button type="button" class="btn small" data-filter-set="${esc(setKey(e.set))}">Filter to this input set</button>${x.params.length ? `<button type="button" class="btn small" data-rows-set="${esc(setKey(e.set))}">Show its data points</button>` : ''}</div></td></tr>`;
}

/* ---- Data points ------------------------------------------------------------------------------ */
function renderRows(st) {
  const data = st.list;
  /* Only the window is built. filterState() itself costs a few ms; the second
     was all in the HTML for rows nobody had scrolled to. */
  const shown = Math.min(tableLimit, data.length);
  $('data-body').innerHTML = data.slice(0, shown).map((r) => {
    const label = statusLabel(r.status), style = styleOf(label);
    return `<tr><td class="folder path">${r.folder ? breakable(r.folder) : NO_FOLDER}</td><td class="path">${breakable(r.file)}</td><td>${esc(r.sheet)}</td><td class="mono num">${r.row}</td><td class="mono">${esc(r.id)}</td><td>${esc(display(r.reviewer))}</td><td><span class="badge"><i class="sw${style === 'blank' ? ' blank' : ''}" style="--c:var(--st-${style})"></i>${esc(label)}</span></td><td class="comment">${esc(r.comment)}</td></tr>`;
  }).join('');
  $('empty').hidden = data.length > 0;
  $('table-count').textContent = data.length
    ? `Showing ${shown.toLocaleString('en-GB')} of ${data.length.toLocaleString('en-GB')} row(s)` + (shown < data.length ? ' — narrow the filters, or show more.' : '')
    : '';
  $('more-btn').hidden = shown >= data.length;
  $('all-btn').hidden = shown >= data.length;
}

/* ---- Calculation cases ------------------------------------------------------------------------------ */
/* The QC state of the parameters in these rows, counted as the overview counts it, among the rows that match. */
const tallyOf = (members) => paramsOfRows(members).params;
const rowsOfKeys = (keys) => { const set = new Set(keys), out = new Set(); rows.forEach((r, i) => { if (set.has(`${r.path}|||${r.sheet}`)) out.add(i); }); return out; };
function tallyText(members) {
  const ps = tallyOf(members);
  if (!ps.length) return '<span class="muted">no QC rows</span>';
  const flagged = ps.filter((e) => model.whole.get(e.key)?.flagged).length;
  return esc(approvedText(ps)) + (flagged ? ` · ${fmt(flagged)} needing attention` : '');
}
function tallyCell(members, show, from) {
  if (!loadedFiles.length) return '<span class="muted">workbooks not read</span>';
  const ps = tallyOf(members);
  if (!ps.length) return `<span class="muted">${members.size ? 'no row matches' : 'no QC rows'}</span>`;
  const flagged = ps.filter((e) => model.whole.get(e.key)?.flagged).length;
  return `<div class="tally">${segBar(statusCounts(ps), { label: approvedText(ps) })}<div>${esc(approvedText(ps))}</div>`
    + (flagged ? `<div>${fmt(flagged)} needing attention</div>` : '')
    + (from ? `<div class="muted">${esc(from)}</div>` : '')
    + (show != null ? `<button type="button" class="link-btn" data-show="${show}">Filter to this case</button>` : '') + '</div>';
}
const isTableValue = (v) => v != null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Date);
/* What a case says about itself, as the table shows it: the top-level values
   as chips, and each section on a line of its own. */
const CASE_OWN = new Set(['info', 'repositories', 'radionuclides', 'parameter_files']);
function settingsCell(toml) {
  const M = cases.model, chips = [], lines = [];
  for (const [key, value] of Object.entries(toml)) {
    if (CASE_OWN.has(key)) continue;
    if (isTableValue(value)) {
      const inner = Object.entries(value).filter(([k]) => k !== 'parameter_files');
      lines.push(`<div class="section-line" title="${esc(inner.map(([k, v]) => `${k} = ${M.shortValue(v)}`).join('\n'))}"><b>${esc(key)}</b> ${esc(inner.map(([, v]) => M.shortValue(v)).join(' · '))}</div>`);
    } else chips.push(`<span class="chip">${esc(key)} ${esc(M.shortValue(value))}</span>`);
  }
  return chips.join('') + lines.join('') || '<span class="muted">—</span>';
}
function listLine(label, value) {
  const all = cases.model.asList(value).map(String);
  const text = !all.length ? '—' : all.length === 1 ? all[0] : `${all.length}: ${all.slice(0, 3).join(', ')}${all.length > 3 ? ', …' : ''}`;
  return `<div title="${esc(all.join(', '))}"><span class="muted">${label}</span> ${esc(text)}</div>`;
}
const noSet = (file) => `link.toml has no set called ${file.replace(/\.h5$/i, '')}`;
function parameterFilesCell(c) {
  if (!c.inputs.files.length) return '<span class="chip warn">none</span>';
  return c.inputs.files.map((pf) => `<div class="pf"><span class="mono">${pf.domain ? `[${esc(pf.domain)}] ` : ''}${esc(pf.file)}</span> `
    + (pf.set ? `<span class="set">→ ${esc(pf.set)}</span>${pf.errors.length ? ` <span class="chip bad" title="${esc(pf.errors.join('\n'))}">does not resolve</span>` : ''}`
      : `<span class="chip warn" title="${esc(noSet(pf.file))}">not built by link.toml</span>`) + '</div>').join('');
}
/* A data file's workbook was read, or it has raw data to stand in for it, or it lacks it. */
const lacksWorkbook = (d) => d.entry && !d.found && !d.raw;
function dataFilesCell(c) {
  if (!c.data.length) return '';
  const undefinedCount = c.data.filter((d) => !d.entry).length;
  let text = `${c.data.length} data file(s)`;
  if (loadedFiles.length) {
    const read = c.data.filter((d) => d.found).length, rawOnly = c.data.filter((d) => d.entry && !d.found && d.raw).length, missing = c.data.filter(lacksWorkbook).length;
    text += `, ${read} workbook(s) read` + (rawOnly ? `, ${rawOnly} from raw data only` : '') + (missing ? `, <span class="lvl warning">${missing} workbook(s) not read</span>` : '');
  }
  return `<div class="input-data">${text}` + (undefinedCount ? ` <span class="chip bad">${undefinedCount} not in data.toml</span>` : '') + '</div>';
}
function workbookCell(d) {
  if (!d.entry) return '<span class="chip bad">not in data.toml</span>';
  if (d.found) return `<span class="mono">${esc(d.found)}</span>` + (d.others.length ? ` <span class="chip warn" title="${esc(d.others.join('\n'))}">${d.others.length} more found</span>` : '');
  if (!loadedFiles.length) return `<span class="mono muted">${esc(d.workbook)}</span>`;
  return d.raw ? '<span class="muted">none: raw data only</span>' : `<span class="mono">${esc(d.workbook)}</span> <span class="chip warn">not read</span>`;
}
function caseRow(c, i) {
  const t = c.file.toml, members = caseMembers(c), source = caseSource(c);
  const from = source === 'export' ? 'traced from the exports' : source === 'toml' && members.size ? 'by data.toml, whole sheets' : '';
  return `<tr data-case="${i}"><td><button type="button" class="case-name" aria-expanded="false" data-i="${i}">${esc(c.name)}</button>`
    + (cases.configs.length > 1 && c.config.folder ? `<span class="case-folder">${esc(c.config.folder)}</span>` : '') + '</td>'
    + `<td><div class="case-info" data-info="${i}"></div></td><td>${parameterFilesCell(c)}${dataFilesCell(c)}</td>`
    + `<td>${c.data.length || members.size ? tallyCell(members, members.size ? i : null, from) : '<span class="muted">—</span>'}</td><td>${listLine('Repositories', t.repositories)}${listLine('Nuclides', t.radionuclides)}</td><td>${settingsCell(t)}</td></tr>`;
}
/* The whole of a case, opened under its row: what it says, where its
   parameter files come from, and its data files one by one. */
function caseDetail(c, i) {
  const t = c.file.toml, M = cases.model;
  const settings = Object.entries(t).filter(([k]) => k !== 'info').map(([k, v]) => isTableValue(v)
    ? Object.entries(v).map(([kk, vv]) => `<tr><th>[${esc(k)}] ${esc(kk)}</th><td>${esc(M.shortValue(vv))}</td></tr>`).join('')
    : `<tr><th>${esc(k)}</th><td>${esc(M.shortValue(v))}</td></tr>`).join('');
  const chains = c.inputs.files.map((pf) => {
    const head = `<span class="mono">${esc(pf.file)}</span>${pf.domain ? ` (for ${esc(pf.domain)})` : ''}`;
    if (!pf.set) return `<p>${head}: <span class="chip warn">${esc(noSet(pf.file))}</span></p>`;
    const steps = pf.steps.map((s) => `<li><b>${esc(s.set)}</b>: ${s.base ? `from ${s.baseList ? 'the list ' : ''}${esc(s.base)}` : `${s.files.length} data file(s) listed`}`
      + (s.skip.length ? `, without ${esc(s.skip.join(', '))}` : '') + (s.add.length ? `, with ${esc(s.add.join(', '))}` : '')
      + (s.groups.length ? `; only the groups ${esc(s.groups.join(', '))}` : '') + '</li>').join('');
    return `<p>${head} is the input set <b>${esc(pf.set)}</b>, of ${pf.sources.length} data file(s):</p><ol class="steps">${steps}</ol>`
      + (pf.errors.length ? `<p class="lvl error">${esc(pf.errors.join('; '))}</p>` : '');
  }).join('');
  const link = (name, j) => j >= 0 ? `<button type="button" class="link-btn" data-goto="${j}">${esc(name)}</button>` : `${esc(name)} <span class="chip warn">not read</span>`;
  const refs = M.caseReferences(t).map((r) => `${r.domain ? `[${esc(r.domain)}] ` : ''}${esc(r.key)}: ${link(r.name, cases.list.findIndex((x) => x.config === c.config && x.name === r.name))}`).join(' · ');
  const users = cases.list.map((x, j) => [x, j]).filter(([x]) => x.config === c.config && x !== c && M.caseReferences(x.file.toml).some((r) => r.name === c.name)).map(([x, j]) => link(x.name, j)).join(', ');
  const data = c.data.map((d) => `<tr><td class="mono">${esc(d.source)}</td><td>${workbookCell(d)}</td><td>${d.sheets ? esc(d.sheets.join(', ')) : '<span class="muted">all</span>'}</td>`
    + `<td>${d.raw ? `<span class="mono">${esc(d.raw)}</span>` : '<span class="muted">—</span>'}</td><td>${d.found ? tallyText(rowsOfKeys(d.keys)) : '<span class="muted">—</span>'}</td></tr>`).join('');
  return `<tr class="case-detail" data-detail="${i}"><td colspan="6"><div class="detail-grid"><div><h3>Description</h3><div class="case-info-full" data-full="${i}"></div>`
    + (refs ? `<h3>Takes results from</h3><p>${refs}</p>` : '') + (users ? `<h3>Its results are taken by</h3><p>${users}</p>` : '')
    + `</div><div><h3>Settings in ${esc(c.file.path)}</h3><table class="kv"><tbody>${settings}</tbody></table></div></div>`
    + `<h3>Input</h3>${chains || '<p class="muted">No parameter file.</p>'}`
    + (data ? `<table class="kv"><thead><tr><th>Data file</th><th>Workbook</th><th>Sheets</th><th>Raw data</th><th>QC</th></tr></thead><tbody>${data}</tbody></table>` : '')
    + (caseMembers(c).size ? `<p><button type="button" class="btn small" data-show="${i}">Filter to ${esc(c.name)}</button></p>` : '') + '</td></tr>';
}
function renderChecks() {
  const items = cases.checks.flatMap(([config, list]) => list.map((x) => ({ ...x, folder: config.folder })));
  const box = $('cases-checks'), count = (level) => items.filter((x) => x.level === level).length;
  box.classList.toggle('attention', count('error') + count('warning') > 0);
  if (!items.length) { box.innerHTML = '<p class="muted">Nothing in the configuration to look at.</p>'; return; }
  const parts = [['error', 'error(s)'], ['warning', 'warning(s)'], ['info', 'note(s)']].filter(([l]) => count(l)).map(([l, w]) => `${count(l)} ${w}`);
  box.innerHTML = `<details><summary>${items.length} thing(s) in the configuration to look at: ${parts.join(', ')}</summary><ul>`
    + items.map((x) => `<li><span class="lvl ${x.level}">${x.level}</span> ${esc(x.text)}${x.cases.length ? ` <span class="muted">(${esc(x.cases.join(', '))})</span>` : ''}${cases.configs.length > 1 ? ` <span class="muted">[${esc(x.folder || 'files added on their own')}]</span>` : ''}</li>`).join('') + '</ul></details>';
}
function renderSets() {
  const M = cases.model, out = [];
  for (const config of cases.configs) {
    if (!config.link || config.link.borrowed) continue;
    const users = new Map();
    for (const c of cases.list) if (c.config.link?.path === config.link.path) for (const pf of c.inputs.files) if (pf.set) { if (!users.has(pf.set)) users.set(pf.set, new Set()); users.get(pf.set).add(c.name); }
    for (const set of Object.keys(config.link.defs)) {
      const r = M.setSources(config.link.defs, set, config.link.lists), own = r.steps[r.steps.length - 1];
      const built = own && own.base ? `${esc(own.base)}${own.skip.length ? `, without ${esc(own.skip.join(', '))}` : ''}${own.add.length ? `, with ${esc(own.add.join(', '))}` : ''}` : `${own ? own.files.length : 0} listed`;
      const used = [...(users.get(set) || [])];
      const exported = exportFiles.some((e) => setKey(e.set) === setKey(set));
      out.push(`<tr><td class="mono">${esc(set)}</td><td>${built}${r.errors.length ? ` <span class="chip bad" title="${esc(r.errors.join('\n'))}">does not resolve</span>` : ''}</td>`
        + `<td title="${esc(r.sources.join(', '))}">${r.sources.length}</td><td>${used.length ? esc(used.join(', ')) : '<span class="muted">no case</span>'}</td><td>${loadedFiles.length ? tallyText(setMembers(setKey(set))) + (exported ? ' <span class="muted">(export)</span>' : '') : '<span class="muted">—</span>'}</td></tr>`);
    }
  }
  $('link-sets-body').innerHTML = out.join('') || '<tr><td colspan="5" class="muted">No link.toml was read.</td></tr>';
}
function renderDataFiles() {
  const M = cases.model, out = [], own = new Set(['path', 'sheet_names', 'raw_path', 'file_name']);
  for (const config of cases.configs) {
    if (!config.data || config.data.borrowed) continue;
    const inSets = new Map();
    if (config.link) for (const set of Object.keys(config.link.defs)) for (const src of M.setSources(config.link.defs, set, config.link.lists).sources) {
      const name = M.dataName(src, config.data.defs); if (!inSets.has(name)) inSets.set(name, new Set()); inSets.get(name).add(set);
    }
    for (const name of Object.keys(config.data.defs)) {
      const d = cases.resolveSource(config, M.dataSource(config.data.defs, name));
      const other = Object.entries(d.entry).filter(([k]) => !own.has(k)).map(([k, v]) => `${k} ${M.shortValue(v)}`);
      const sets = [...(inSets.get(name) || [])];
      out.push(`<tr><td class="mono">${esc(name)}</td><td>${workbookCell(d)}</td><td>${d.sheets ? esc(d.sheets.join(', ')) : '<span class="muted">all</span>'}</td>`
        + `<td>${d.raw ? `<span class="mono">${esc(d.raw)}</span>` : '<span class="muted">—</span>'}</td><td>${other.length ? esc(other.join(' · ')) : '<span class="muted">—</span>'}</td>`
        + `<td title="${esc(sets.join(', '))}">${sets.length ? esc(sets.length > 3 ? `${sets.slice(0, 3).join(', ')}, … (${sets.length})` : sets.join(', ')) : '<span class="muted">none</span>'}</td>`
        + `<td>${d.found ? tallyText(rowsOfKeys(d.keys)) : '<span class="muted">—</span>'}</td></tr>`);
    }
  }
  $('data-files-body').innerHTML = out.join('') || '<tr><td colspan="7" class="muted">No data.toml was read.</td></tr>';
}
function renderCases() {
  $('cases').hidden = !cases;
  if (!cases) return;
  const ownCount = (kind) => cases.configs.reduce((n, c) => n + (c[kind] && !c[kind].borrowed ? Object.keys(c[kind].defs).length : 0), 0);
  const where = cases.configs.length > 1 ? `, in ${cases.configs.length} folders` : cases.configs[0]?.folder ? ` — ${cases.configs[0].folder}` : '';
  $('cases-info').textContent = `${cases.list.length} calculation case(s), ${ownCount('link')} input set(s), ${ownCount('data')} data file(s)${where}`;
  renderChecks();
  const open = new Set([...$('cases-body').querySelectorAll('.case-name[aria-expanded=true]')].map((b) => +b.dataset.i));
  const body = $('cases-body');
  body.innerHTML = cases.list.map(caseRow).join('') || '<tr><td colspan="6" class="muted">No calculation case was read; link.toml and data.toml alone are below.</td></tr>';
  /* A description may carry markup (<b>, <i>): it is shown through the site's
     sanitiser, which keeps such tags and drops everything that could run. */
  cases.list.forEach((c, i) => body.querySelector(`[data-info="${i}"]`)?.append(kvotSanitizeHtml(String(c.file.toml.info ?? ''))));
  for (const i of open) toggleCase(i, true);
  renderSets(); renderDataFiles();
}
function toggleCase(i, open) {
  const tr = $('cases-body').querySelector(`tr[data-case="${i}"]`);
  if (!tr) return;
  const button = tr.querySelector('.case-name'), next = tr.nextElementSibling, isOpen = next?.classList.contains('case-detail');
  if (isOpen) { if (open !== true) { next.remove(); button.setAttribute('aria-expanded', 'false'); } return; }
  tr.insertAdjacentHTML('afterend', caseDetail(cases.list[i], i));
  tr.nextElementSibling.querySelector(`[data-full="${i}"]`).append(kvotSanitizeHtml(String(cases.list[i].file.toml.info ?? '')));
  button.setAttribute('aria-expanded', 'true');
}
/* A case's rows are those of its input sets: the case filter keeps them, and
   the rest of the page follows the filter as it always does. */
function showCaseRows(i) {
  filters.case = new Set([cases.list[i].key]);
  showTab('files');
  rerender();
  $('workspace').querySelector('.qc-filters').scrollIntoView({ block: 'start', behavior: 'smooth' });
}

/* ---- Exports ------------------------------------------------------------------------------ */
/*
  Quoting alone was not enough. The reviewer and comment columns come out of an
  uploaded workbook, and a cell someone had typed as "=HYPERLINK(...)" was
  written through unchanged — so opening the export in Excel ran it as a
  formula. kvotCsvCell forces such a value back to text.
*/
function csvCell(v) { return kvotCsvCell(v); }
const csvText = (table) => '﻿' + table.map((a) => a.map(csvCell).join(';')).join('\r\n');
function exportCsv() {
  const head = ['Folder', 'File', 'Sheet', 'Excel row', 'ID', 'QC reviewer', 'QC status', 'QC comment'];
  const body = filtered().map((r) => [r.folder, r.file, r.sheet, r.row, r.id, r.reviewer, statusLabel(r.status), r.comment]);
  download(new Blob([csvText([head, ...body])], { type: 'text/csv;charset=utf-8' }), 'skb_qc_filtered.csv');
}
function exportParamsCsv() {
  const st = filterState();
  const head = ['Folder', 'File', 'ID', 'Rows', 'QC status', 'Approved', 'QC reviewers', 'Sheets', 'Needing attention'];
  const body = [...st.index.values()].sort((a, b) => comparePaths(a.path, b.path) || a.id.localeCompare(b.id, 'en')).map((e) => [e.folder, e.file, e.id, e.rows, e.status, e.approved ? 'yes' : 'no', [...e.reviewers].join(', '), [...e.sheets].join(', '), (model.whole.get(e.key)?.why || []).join('; ')]);
  download(new Blob([csvText([head, ...body])], { type: 'text/csv;charset=utf-8' }), 'skb_qc_parameters.csv');
}
function exportFilesCsv() {
  const st = filterState();
  const head = ['Kind', 'Folder', 'File', 'Sheets', 'Parameters', 'Rows or values', 'Approved', 'In review', 'Preliminary', 'Other statuses', 'Traced to a QC row', 'From raw data', 'From workbooks not read', 'From sheets without QC columns', 'Not found in their workbook', 'QC reviewers'];
  const statusCols = (params) => {
    const c = new Map(statusCounts(params));
    const approved = params.filter((e) => e.approved).length, review = c.get('In review') || 0, prelim = c.get('Preliminary') || 0;
    return [approved, review, prelim, params.length - approved - review - prelim];
  };
  const body = [];
  for (const b of bookSummaries(st).sort((x, y) => comparePaths(x.path, y.path))) body.push(['Source workbook', b.folder, b.file, [...b.sheets.keys()].join(', '), b.params.length, b.rows, ...statusCols(b.params), '', '', '', '', '', reviewersText(b.params)]);
  for (const x of visibleExports(st)) { const t = x.e.trace; body.push(['Input set', x.e.folder, x.e.name, x.e.sheet, x.params.length, x.e.values, ...statusCols(x.params), t.traced, t.raw + t.none, t.missing, t.noQc, t.notFound, reviewersText(x.params)]); }
  download(new Blob([csvText([head, ...body])], { type: 'text/csv;charset=utf-8' }), 'skb_qc_files.csv');
}

function reset() {
  for (const job of jobs) job.cleared = true;
  rows = []; validSheets = []; loadedFiles = []; exportFiles = []; tomlFiles = []; cases = null; model = null; snapshot = null; tableLimit = PAGE_SIZE;
  for (const f of FACETS) filters[f.key].clear();
  expanded.book.clear(); expanded.set.clear();
  invalidate();
  $('file-input').value = ''; $('folder-input').value = ''; $('snapshot-input').value = '';
  $('workspace').className = ''; $('dropzone').classList.remove('compact');
  $('id-search').value = ''; $('flagged-only').checked = false; $('changed-only').checked = false; $('changed-only').disabled = true;
  $('cases').hidden = true; $('facets').innerHTML = ''; $('active-filters').hidden = true;
  activeTab = 'overview';
  hideStatus();
}

/* ---- The (i) panels ---------------------------------------------------------------------------- */
function infoTopics() {
  return {
    page: {
      kicker: 'This page', title: 'SKB QC summary',
      lead: 'How far the QC review of the input data has come, read from the workbooks themselves. Drop the Excel folder, the QC folder and the config folder — or the data folder that holds them — anywhere on the page.',
      sections: [
        { heading: 'What it reads', list: [
          '**Source workbooks** (the Excel folder): every sheet with an ID column and the three review columns QC reviewer, QC comment and QC status (or the older QA headings). Each row is a value.',
          '**Input-set exports** (the QC folder): one workbook per input set, with every value of the set and the workbook, sheet and row it was read from. Their values are traced back to the source rows, so each set shows the QC state of exactly what it uses.',
          '**Calculation cases** (the config folder): the cases’ TOML files with link.toml and data.toml, which say which input sets a case reads.',
        ] },
        { heading: 'Where to look', list: [
          '**Overview**: the share approved, who reviews what, and the parameters that need a look.',
          '**Files**: the workbooks and input sets with rows that match the filters, each with its parameters’ statuses. Open one for its sheets or its sources.',
          '**Data points**: every matching row, as it stands in its workbook.',
          '**Calculation cases**: each case with its input and the QC state of its data.',
        ] },
        { heading: 'Privacy', text: 'The files are read in this browser. Nothing is uploaded, even where the browser’s folder dialog speaks of uploading.' },
      ],
    },
    filters: {
      kicker: 'Filters', title: 'Narrowing what is shown',
      lead: 'Every view follows the filters. A list keeps the rows with any of the values chosen in it; the lists combine, so Status and Reviewer together keep one reviewer’s rows of those statuses.',
      sections: [
        { heading: 'The lists', list: [
          'The numbers beside a list’s values are the parameters each would keep, with the other filters as they are.',
          '**Folder** takes the folder’s subfolders along.',
          '**Input set** keeps the rows the set uses: traced from its export when one was read, otherwise the sheets data.toml names for its data files.',
          '**Case** keeps the rows of the input sets the case reads.',
        ] },
        { heading: 'The switches', list: [
          '**Needing attention** keeps the parameters flagged in the overview.',
          '**Changed since snapshot** keeps the parameters whose status or reviewers differ from a snapshot compared against (the Snapshot menu).',
          'Both are decided on all of a parameter’s rows, not only the ones the other filters leave.',
        ] },
        { text: 'Search ID keeps the rows whose ID holds the text, whatever its case.' },
      ],
    },
    status: {
      kicker: 'Overview', title: 'The share approved',
      lead: 'A parameter is an ID in a workbook: one row, or the rows of a time series. It is approved when every row of it carries OK-PSAR, OK-UPSAR or OK-FSAR.',
      sections: [
        { heading: 'Its status', list: [
          'The status its rows share, or **Mixed** when they differ, so a disagreement is shown rather than averaged away.',
          '**(Blank)** is a parameter with no status in any row.',
          'A status outside Preliminary, In review, OK-PSAR, OK-UPSAR and OK-FSAR is kept as written and listed after them, never counted as approved.',
        ] },
        { heading: 'The same ID in two workbooks', text: 'is two parameters: a variant’s workbook gives its own value, which the variant’s input set takes in place of the common one, and each value is reviewed where it stands.' },
        { text: 'The bar runs from approved to not started. Choose a status in the legend to show only it.' },
      ],
    },
    reviewers: {
      kicker: 'Overview', title: 'By QC reviewer',
      lead: 'The parameters on each reviewer’s list, by status. A parameter with two reviewers is counted under both.',
      sections: [{ text: 'Choose a number to filter to that reviewer and status.' }],
    },
    attention: {
      kicker: 'Overview', title: 'Needing attention',
      lead: 'Parameters whose rows tell different stories, or that nobody holds:',
      sections: [{ list: [
        '**Rows disagree on status**: a time series reviewed in part.',
        '**No status**: no row carries one.',
        '**More than one reviewer**: its rows name different people.',
        '**No reviewer named**, or **rows without a reviewer**.',
      ] }, { text: 'Choose one to see its rows.' }],
    },
    books: {
      kicker: 'Files', title: 'Source workbooks',
      lead: 'Each workbook with rows that match the filters: its sheets, parameters, rows and their statuses, its reviewers, and how many input sets use its rows.',
      sections: [{ text: 'Open a workbook for its sheets, the input sets that use it, and a filter to it alone. Column headings sort the list.' }],
    },
    sets: () => ({
      kicker: 'Files', title: 'Input sets',
      lead: 'Each input-set export read: the parameter file a calculation case reads, value by value, with the workbook, sheet and row each value came from.',
      sections: [
        { heading: 'Traced to a QC row', list: [
          'A value is traced to the row its export names when that row holds its ID, and otherwise to its ID’s rows in that sheet, in order: a time series is exported a time point at a time.',
          '**From raw data**: values read from raw data deliveries rather than a workbook in the Excel folder. They have no QC row.',
          '**From workbooks not read**: the export names a workbook in an Excel folder that is not among those read: not added, or no longer there.',
          '**Not found in their workbook**: the workbook was read, but the row and its ID are no longer in it.',
        ] },
        { heading: 'Out of date', text: 'An export with values from workbooks not read, or not found in theirs, was made from workbooks as they no longer are. Making it again from the current ones brings it up to date.' },
        { text: 'The parameters and statuses are those of the traced rows that match the filters.' },
      ],
    }),
    rowsview: {
      kicker: 'Data points', title: 'Every matching row',
      lead: 'One row per value, as it stands in its workbook: folder, workbook, sheet, Excel row, ID and the three review columns. 500 rows are shown at a time; narrow the filters, or show more.',
    },
    cases: {
      kicker: 'Calculation cases', title: 'Cases, their input and its QC',
      lead: 'Each case with the parameter files it reads, the input sets they are built as, and the QC state of the rows those sets use, among the rows that match the filters.',
      sections: [{ text: 'Where an export of a set was read, its rows are exactly those traced from it; otherwise they are the sheets of the set’s data files, as link.toml and data.toml name them. Open a case for its settings and how its input set is built.' }],
    },
    snapshot: {
      kicker: 'Snapshot', title: 'Keeping track',
      lead: 'A snapshot saves the status and reviewers of every parameter to a file. Compared against later, it shows which way the work has gone: the moves between statuses, new parameters, and changed reviewers.',
      sections: [{ text: 'With a snapshot compared, the switch Changed since snapshot keeps the parameters that moved.' }],
    },
  };
}

/* ---- Wiring ----------------------------------------------------------------------------------- */
const dz = $('dropzone'), fi = $('file-input'), di = $('folder-input');
/* A click or Enter on one of the zone's buttons is that button's own, and so is
   the click a button passes on to its input inside the zone; the zone takes
   only its own. Taking that click too had "Choose a folder" open the file
   chooser instead. */
dz.addEventListener('click', (e) => { if (!e.target.closest('button,input')) fi.click(); });
dz.addEventListener('keydown', (e) => { if (e.target === dz && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); fi.click(); } });
$('choose-btn').addEventListener('click', (e) => { e.stopPropagation(); fi.click(); });
$('folder-btn').addEventListener('click', (e) => { e.stopPropagation(); di.click(); });
/* Emptied once taken, so the same files or folder chosen again are read again. */
[fi, di].forEach((input) => input.addEventListener('change', () => { const files = [...input.files]; input.value = ''; if (files.length) enqueue(() => chosenFiles(files)); }));
$('stop-btn').addEventListener('click', () => { for (const job of jobs) job.stopped = true; });
/*
  Files and folders are taken wherever on the page they are dropped. A drop
  that missed the zone would otherwise have the browser open the file in the
  page's place, and everything read so far would go with it.
*/
let dragDepth = 0;
const carriesFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
document.addEventListener('dragenter', (e) => { if (carriesFiles(e)) { dragDepth++; dz.classList.add('drag-over'); } });
document.addEventListener('dragleave', (e) => { if (carriesFiles(e) && --dragDepth <= 0) { dragDepth = 0; dz.classList.remove('drag-over'); } });
document.addEventListener('dragover', (e) => { if (carriesFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
document.addEventListener('drop', (e) => {
  if (!carriesFiles(e)) return;
  e.preventDefault(); dragDepth = 0; dz.classList.remove('drag-over');
  const items = dropItems(e.dataTransfer);
  enqueue((job) => droppedFiles(items, job));
});

/* Tabs: a click, or the arrow keys between them. */
$('tabs').addEventListener('click', (e) => { const b = e.target.closest('[role=tab]'); if (b) showTab(b.dataset.tab); });
$('tabs').addEventListener('keydown', (e) => {
  const list = [...$('tabs').querySelectorAll('[role=tab]:not([hidden])')];
  const at = list.indexOf(document.activeElement);
  const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: list.length - 1 }[e.key];
  if (at < 0 || to === undefined) return;
  e.preventDefault();
  const b = list[(to + list.length) % list.length];
  b.focus(); showTab(b.dataset.tab);
});

/* The filter bar. A press on the button of the list that is open shuts the
   list by itself (the browser's light dismiss), so the click after it must
   not open it again. */
let pressedOpen = null;
$('facets').addEventListener('pointerdown', (e) => {
  const b = e.target.closest('.qc-facet');
  pressedOpen = b && $('facet-pop').matches(':popover-open') && openFacet === b.dataset.facet ? b.dataset.facet : null;
}, true);
$('facets').addEventListener('click', (e) => {
  const b = e.target.closest('.qc-facet');
  if (!b) return;
  const pop = $('facet-pop'), was = pressedOpen;
  pressedOpen = null;
  if (was === b.dataset.facet) { if (pop.matches(':popover-open')) pop.hidePopover(); return; }
  if (pop.matches(':popover-open') && openFacet === b.dataset.facet) { pop.hidePopover(); return; }
  openFacetList(b.dataset.facet, b);
});
$('facet-pop').addEventListener('change', (e) => {
  const box = e.target.closest('.qc-pop-list input[type=checkbox]');
  if (!box || !openFacet) return;
  const sel = filters[openFacet];
  if (box.checked) sel.add(box.value); else sel.delete(box.value);
  $('facet-pop').querySelector('.qc-pop-foot span').textContent = sel.size ? `${sel.size} chosen` : 'None chosen: all are shown';
  rerender();
  /* The buttons were drawn again: the list stays with the new one. */
  const b = $('facets').querySelector(`[data-facet="${openFacet}"]`);
  if (b) b.setAttribute('aria-expanded', 'true');
});
$('facet-pop').addEventListener('input', (e) => {
  if (!e.target.closest('.qc-pop-find')) return;
  const q = e.target.value.trim().toLowerCase();
  let any = false;
  for (const li of $('facet-pop').querySelectorAll('.qc-pop-list li')) { const on = !q || li.dataset.text.includes(q); li.hidden = !on; any ||= on; }
  $('facet-pop').querySelector('.qc-pop-empty').hidden = any;
});
$('facet-pop').addEventListener('click', (e) => {
  if (!e.target.closest('[data-pop-clear]') || !openFacet) return;
  filters[openFacet].clear();
  for (const box of $('facet-pop').querySelectorAll('.qc-pop-list input')) box.checked = false;
  $('facet-pop').querySelector('.qc-pop-foot span').textContent = 'None chosen: all are shown';
  rerender();
});
$('facet-pop').addEventListener('toggle', (e) => {
  if (e.newState !== 'closed') return;
  const key = openFacet;
  for (const b of document.querySelectorAll('.qc-facet')) b.setAttribute('aria-expanded', 'false');
  openFacet = null;
  /* Focus left in the list, or nowhere, goes back to its button. */
  const at = document.activeElement;
  if (key && (!at || at === document.body || $('facet-pop').contains(at))) $('facets').querySelector(`[data-facet="${key}"]`)?.focus({ preventScroll: true });
});
$('active-filters').addEventListener('click', (e) => {
  if (e.target.closest('#clear-filters')) { clearFilters(); return; }
  const b = e.target.closest('[data-unfilter]');
  if (!b) return;
  const what = b.dataset.unfilter;
  if (what === 'search') $('id-search').value = '';
  else if (what === 'flagged') $('flagged-only').checked = false;
  else if (what === 'changed') $('changed-only').checked = false;
  else filters[what].clear();
  rerender();
});
let searchTimer = 0;
$('id-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(rerender, 120); });
['flagged-only', 'changed-only'].forEach((id) => $(id).addEventListener('change', rerender));

/* The workbooks that gave nothing, listed under their pill. */
$('notes-pop').addEventListener('beforetoggle', (e) => {
  if (e.newState !== 'open') return;
  const sources = new Set(rows.map((r) => r.path)), exportsRead = new Set(exportFiles.map((x) => x.path));
  const list = [...new Set(loadedFiles)].filter((p) => !sources.has(p) && !exportsRead.has(p)).sort(comparePaths);
  $('notes-pop').innerHTML = `<div class="qc-pop-head"><span class="qc-pop-title">Workbooks without QC columns</span></div><div class="qc-pop-hint">Read, but with no sheet headed ID, QC reviewer, QC comment and QC status, and not an input-set export. An export that takes values from one of them cannot trace those values.</div><ul class="qc-note-list">${list.map((p) => `<li><span class="mono">${esc(p)}</span></li>`).join('')}</ul>`;
  const b = $('notes-btn');
  if (b) placeMenu($('notes-pop'), b);
});
/* The menus. */
for (const [menu, button] of [['export-menu', 'export-menu-btn'], ['snapshot-menu', 'snapshot-menu-btn']]) {
  $(menu).addEventListener('beforetoggle', (e) => { if (e.newState === 'open') placeMenu($(menu), $(button)); });
  $(menu).addEventListener('click', (e) => { if (e.target.closest('.qc-menu-item')) $(menu).hidePopover(); });
}
/* A scroll of the page leaves a list behind its button: it is shut instead. */
document.addEventListener('scroll', (e) => {
  for (const id of ['facet-pop', 'export-menu', 'snapshot-menu']) { const el = $(id); if (el.matches(':popover-open') && !el.contains(e.target)) el.hidePopover(); }
}, true);
$('export-btn').addEventListener('click', exportCsv);
$('export-params-btn').addEventListener('click', exportParamsCsv);
$('export-files-btn').addEventListener('click', exportFilesCsv);
$('snapshot-save-btn').addEventListener('click', saveSnapshot);
$('snapshot-load-btn').addEventListener('click', () => $('snapshot-input').click());
$('snapshot-input').addEventListener('change', () => { const f = $('snapshot-input').files[0]; $('snapshot-input').value = ''; if (f) loadSnapshot(f); });
$('reset-btn').addEventListener('click', reset);
$('more-btn').addEventListener('click', () => { tableLimit += PAGE_SIZE; render(); });
$('all-btn').addEventListener('click', () => { tableLimit = Infinity; render(); });

/* The views: a click that narrows sets the filters rather than opening something else. */
$('workspace').addEventListener('click', (e) => {
  const t = e.target;
  const go = t.closest('[data-goto-tab]');
  if (go) { showTab(go.dataset.gotoTab); return; }
  const legend = t.closest('#status-legend [data-status]');
  if (legend) { setFilter('status', [legend.dataset.status]); return; }
  const cell = t.closest('#reviewer-matrix td.cell');
  if (cell) {
    filters.reviewer = new Set([cell.dataset.reviewer]);
    filters.status = new Set(cell.dataset.status ? [cell.dataset.status] : []);
    rerender();
    return;
  }
  const flag = t.closest('.flag-item');
  if (flag) {
    $('id-search').value = flag.dataset.id;
    filters.file = new Set([flag.dataset.path]);
    showTab('rows'); rerender();
    return;
  }
  const sort = t.closest('button.sort');
  if (sort) {
    const [table, key] = sort.dataset.sort.split(':');
    const by = sortBy[table];
    if (by.key === key) by.dir = -by.dir; else { by.key = key; by.dir = key === 'path' || key === 'name' ? 1 : -1; }
    render();
    return;
  }
  const ob = t.closest('[data-open-book]');
  if (ob) { const p = ob.dataset.openBook; if (expanded.book.has(p)) expanded.book.delete(p); else expanded.book.add(p); render(); return; }
  const os = t.closest('[data-open-set]');
  if (os) { const p = os.dataset.openSet; if (expanded.set.has(p)) expanded.set.delete(p); else expanded.set.add(p); render(); return; }
  const fb = t.closest('[data-filter-book]');
  if (fb) { setFilter('file', [fb.dataset.filterBook]); return; }
  const rb = t.closest('[data-rows-book]');
  if (rb) { filters.file = new Set([rb.dataset.rowsBook]); showTab('rows'); rerender(); return; }
  const fs = t.closest('[data-filter-set]');
  if (fs) { setFilter('set', [fs.dataset.filterSet]); return; }
  const rs = t.closest('[data-rows-set]');
  if (rs) { filters.set = new Set([rs.dataset.rowsSet]); showTab('rows'); rerender(); return; }
});
/* A case opens under its row; a case named in another opens where it is; its filter button filters to it. */
$('cases').addEventListener('click', (e) => {
  const button = e.target.closest('button');
  if (!button || !cases) return;
  if (button.classList.contains('case-name')) toggleCase(+button.dataset.i);
  else if (button.dataset.goto != null) { toggleCase(+button.dataset.goto, true); $('cases-body').querySelector(`tr[data-case="${button.dataset.goto}"]`)?.scrollIntoView({ block: 'nearest' }); }
  else if (button.dataset.show != null) showCaseRows(+button.dataset.show);
});

/* The tooltip of the bars' parts. */
(function tooltips() {
  const tip = document.createElement('div');
  tip.id = 'qc-tip'; tip.hidden = true; tip.setAttribute('role', 'tooltip');
  document.body.append(tip);
  const show = (el, x, y) => {
    tip.textContent = el.dataset.tip; tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.max(8, Math.min(x + 12, document.documentElement.clientWidth - w - 8))}px`;
    tip.style.top = `${y + 16 + h > window.innerHeight ? y - h - 10 : y + 16}px`;
  };
  document.addEventListener('pointermove', (e) => { const el = e.target.closest?.('[data-tip]'); if (el) show(el, e.clientX, e.clientY); else tip.hidden = true; });
  document.addEventListener('focusin', (e) => { const el = e.target.closest?.('[data-tip]'); if (el) { const r = el.getBoundingClientRect(); show(el, r.left, r.bottom - 8); } });
  document.addEventListener('focusout', () => { tip.hidden = true; });
  document.addEventListener('scroll', () => { tip.hidden = true; }, true);
})();
window.addEventListener('resize', () => fitBarLabels());

if (typeof KvotInfo !== 'undefined') KvotInfo.setup({ topics: infoTopics(), morePrefix: '' });
