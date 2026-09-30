/* ==========================================================================
   HDF5 BROWSER FOR VISUAL STUDIO CODE

   rb.html -- kvotab.se's HDF5 Browser -- as an editor for .h5, .hdf5 and
   .he5 files. The page runs in a webview as it runs on the site, from the
   same scripts, which build.mjs copies in; this is everything around it:

   * the editor: one webview per file opened, kept alive while its tab is
     hidden (the page holds the file, the tree and the chart);
   * files: read whole and posted to the page when small, or read a piece at
     a time by the reader (src/reader.mjs, a worker thread running h5wasm's
     Node build) when large, which the page asks through this host;
   * Save and Add Files, which in a webview need VS Code's own dialogs;
   * rereading a file when it changes on disk, and Open Together, which puts
     several files in one view for rb's intersect and union;
   * a file dropped on a view going into it as another file, as Add Files
     would add it, not into a view of its own (browserShowingBehind), and
     several files dropped at once going into one view (gatherInto);
   * updates: a newer version, released on kvotab.se, installed by itself
     once its signature is checked (src/update.js).

   The page may ask only about files this view was given, and is given
   tokens, never paths: what it is shown comes from a file that may have been
   written by anyone, and markup from such a file has run on the site before
   (see resources/js/kvot-safe.js), so this channel is kept that narrow.
   ========================================================================== */

'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { Worker } = require('worker_threads');
const { Updater } = require('./src/update');

const VIEW_TYPE = 'kvotab.hdf5Browser';
/** rb-lazy.js RB_LAZY_MIN_BYTES: from this size a file is read lazily. */
const LAZY_MIN_BYTES = 256 * 1024 * 1024;
/** kvot-safe.js KVOT_FILE_SIZE_LIMITS.dataset: the most the page reads whole. */
const WHOLE_MAX_BYTES = 1024 * 1024 * 1024;
/** What rb-lazy.js reads of a lazy file for its signature check. */
const HEAD_BYTES = 1024 * 1024 + 8;
/** A file being written is reread once it has been left alone this long. */
const RELOAD_QUIET_MS = 1500;
const HDF5_NAME = /\.(h5|hdf5|he5)$/i;
const READER_COMMANDS = new Set(['open', 'group', 'values', 'close']);
/** A browser hidden this recently by a file opened into its group is still the one showing there. */
const SHOWN_RECENTLY_MS = 2000;
/** The most files one drop on a page may add. */
const DROP_MAX_FILES = 64;
/** How long the editor VS Code opened for a file put into a browser instead may take to show; */
const ADD_INSTEAD_WAIT_MS = 2000;
/** and how long it is left showing before it is closed (Hdf5BrowserProvider.addInstead). */
const STAND_IN_MS = 300;
/** HDF5 files VS Code opens into a group this close together were opened together: a drop of several. */
const TOGETHER_MS = 2000;

/* ── the reader ───────────────────────────────────────────────────────── */

/**
 * The worker thread, shared by every view; started when a file is first
 * read lazily. If it stops, the files it held are gone with it, and asking
 * about one says so rather than reaching whatever the next thread opens.
 */
class Reader {
  constructor(build, log) {
    this.build = build;
    this.log = log;
    this.worker = null;
    this.generation = 0;
    this.pending = new Map();
    this.seq = 0;
  }

  start() {
    if (this.worker) return this.worker;
    this.generation++;
    const worker = new Worker(path.join(__dirname, 'src', 'reader.mjs'), {
      workerData: {
        h5wasmDir: path.join(__dirname, this.build.h5wasmNodeDir),
        pluginDir: path.join(__dirname, this.build.pluginDir)
      }
    });
    worker.on('message', (m) => {
      if (m.ready) {
        this.log.info('HDF5 reader started');
        return;
      }
      const p = this.pending.get(m.id);
      if (!p) return;
      this.pending.delete(m.id);
      if (m.err) p.reject(new Error(m.err));
      else p.resolve(m.ok);
    });
    worker.on('error', (e) => {
      this.log.error('The HDF5 reader failed:', e);
      this.stopped(worker, e);
    });
    worker.on('exit', (code) => this.stopped(worker, new Error(`the HDF5 reader stopped (exit ${code})`)));
    this.worker = worker;
    return worker;
  }

  stopped(worker, error) {
    if (this.worker !== worker) return;
    this.worker = null;
    for (const p of this.pending.values()) p.reject(error);
    this.pending.clear();
  }

  call(cmd, args) {
    const worker = this.start();
    return new Promise((resolve, reject) => {
      const id = ++this.seq;
      this.pending.set(id, { resolve, reject });
      worker.postMessage({ id, cmd, args });
    });
  }

  dispose() {
    const worker = this.worker;
    this.worker = null;
    if (worker) worker.terminate();
  }
}

/* ── helpers ──────────────────────────────────────────────────────────── */

function newToken() {
  return crypto.randomBytes(12).toString('base64url');
}

/**
 * Exactly these bytes, as a plain Uint8Array. VS Code knows a typed array by
 * its constructor's name, and workspace.fs.readFile hands back a Node Buffer:
 * posted as it is, it went through JSON as {type: 'Buffer', data: [...]}, a
 * number per byte. A window onto part of a larger buffer is copied, because
 * VS Code would send the whole buffer under it.
 */
function compact(bytes) {
  return bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
    ? new Uint8Array(bytes.buffer, 0, bytes.byteLength)
    : new Uint8Array(bytes);
}

async function readHead(uri) {
  const handle = await fs.promises.open(uri.fsPath, 'r');
  try {
    const buffer = Buffer.alloc(HEAD_BYTES);
    const { bytesRead } = await handle.read(buffer, 0, HEAD_BYTES, 0);
    return new Uint8Array(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + bytesRead));
  } finally {
    await handle.close();
  }
}

/** The editor tab of an HDF5 Browser on `uri`, in the group of `column` if it has one there, or null. */
function tabOf(uri, column) {
  const key = uri.toString();
  const groups = vscode.window.tabGroups.all.slice().sort((a, b) => (b.viewColumn === column) - (a.viewColumn === column));
  for (const group of groups) {
    for (const tab of group.tabs) {
      if (tab.input instanceof vscode.TabInputCustom && tab.input.viewType === VIEW_TYPE && tab.input.uri.toString() === key) return tab;
    }
  }
  return null;
}

/** What the editor VS Code opened for a file shows for the moment before it closes. */
function standInHtml(name) {
  return '<!DOCTYPE html><html><head><meta charset="utf-8">'
    + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
    + '<style>body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;'
    + 'font-family:var(--vscode-font-family);font-size:var(--vscode-font-size);'
    + 'color:var(--vscode-descriptionForeground);background:var(--vscode-editor-background)}</style>'
    + `</head><body>Adding ${escapeAttribute(name)} to the HDF5 Browser\u2026</body></html>`;
}

function formatBytes(n) {
  const units = ['bytes', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(1) : n} ${units[i]}`;
}

/** A name from the page, made fit to offer as a file name. */
function safeFileName(name) {
  const clean = String(name == null ? '' : name).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim().slice(0, 200);
  return clean && clean !== '.' && clean !== '..' ? clean : 'download';
}

function saveFilters(name) {
  const ext = path.extname(name).slice(1).toLowerCase();
  const known = { csv: 'CSV', xlsx: 'Excel workbook', png: 'PNG image', json: 'JSON' };
  return known[ext] ? { [known[ext]]: [ext] } : undefined;
}

function escapeAttribute(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function themeKind() {
  const kind = vscode.window.activeColorTheme.kind;
  return kind === vscode.ColorThemeKind.Light || kind === vscode.ColorThemeKind.HighContrastLight ? 'light' : 'dark';
}

const THEME_MODES = new Set(['auto', 'light', 'dark']);

/** hdf5Browser.theme: 'auto' (VS Code's theme) unless light or dark was chosen. */
function themeMode() {
  const mode = vscode.workspace.getConfiguration('hdf5Browser').get('theme', 'auto');
  return THEME_MODES.has(mode) ? mode : 'auto';
}

/* ── one view ─────────────────────────────────────────────────────────── */

class View {
  constructor(provider, documentUri, panel) {
    this.provider = provider;
    this.documentUri = documentUri;
    this.panel = panel;
    this.files = new Map();     // token -> { token, uri, name, watcher, timer }
    this.handles = new Map();   // handle -> { token, generation, fid }
    this.nextHandle = 0;
    this.ready = false;
    this.hiddenAt = 0;          // when another editor last covered it (Hdf5BrowserProvider.browserShowingBehind)
    this.disposed = false;
    this.subscriptions = [];
  }

  get webview() {
    return this.panel.webview;
  }

  async start() {
    this.webview.options = {
      enableScripts: true,
      // The page's own files and nothing else: the HDF5 files come through
      // this host, so the page cannot read anything in the workspace itself.
      localResourceRoots: [vscode.Uri.joinPath(this.provider.context.extensionUri, 'media')]
    };
    this.subscriptions.push(this.webview.onDidReceiveMessage(m => this.receive(m)));
    this.subscriptions.push(this.panel.onDidChangeViewState((e) => {
      if (!e.webviewPanel.visible) this.hiddenAt = Date.now();
    }));
    this.webview.html = this.provider.html(this.webview);
  }

  post(message) {
    return this.webview.postMessage(message);
  }

  /** Files to show in this view; each is sent once the page is ready. */
  add(uris, why) {
    const fresh = [];
    for (const uri of uris) {
      if ([...this.files.values()].some(f => f.uri.toString() === uri.toString())) continue;
      const file = { token: newToken(), uri, name: this.uniqueName(uri), watcher: null, timer: null };
      this.files.set(file.token, file);
      this.watch(file);
      fresh.push(file);
    }
    if (this.ready && fresh.length) this.send(fresh, why);
  }

  /** rb keys files by name, so two results.h5 from two runs get their folder's name added. */
  uniqueName(uri) {
    const base = path.posix.basename(uri.path);
    const taken = new Set([...this.files.values()].map(f => f.name));
    if (!taken.has(base)) return base;
    const ext = path.posix.extname(base);
    const stem = ext ? base.slice(0, -ext.length) : base;
    const folder = path.posix.basename(path.posix.dirname(uri.path)) || 'file';
    let name = `${stem} (${folder})${ext}`;
    for (let n = 2; taken.has(name); n++) name = `${stem} (${folder} ${n})${ext}`;
    return name;
  }

  readLazily(uri, size) {
    // The reader reads with Node, so it can reach a file on this machine's
    // disk (in a remote window, the remote one's); anything else is read whole.
    if (uri.scheme !== 'file') return false;
    const setting = vscode.workspace.getConfiguration('hdf5Browser').get('readLazily', 'auto');
    if (setting === 'always') return true;
    if (setting === 'never') return false;
    return size >= LAZY_MIN_BYTES;
  }

  async payload(file) {
    const { size } = await vscode.workspace.fs.stat(file.uri);
    if (size === 0) throw new Error(`${file.name} is empty.`);
    if (this.readLazily(file.uri, size)) {
      return { token: file.token, name: file.name, size, mode: 'lazy', head: await readHead(file.uri) };
    }
    if (size > WHOLE_MAX_BYTES) {
      throw new Error(`${file.name} is ${formatBytes(size)}; more than ${formatBytes(WHOLE_MAX_BYTES)} is not read whole.`
        + (file.uri.scheme === 'file' ? ' Set "HDF5 Browser: Read Lazily" to auto or always to open it.' : ''));
    }
    const bytes = compact(await vscode.workspace.fs.readFile(file.uri));
    return { token: file.token, name: file.name, size, mode: 'whole', bytes };
  }

  async send(files, why) {
    const ready = [];
    for (const file of files) {
      try {
        ready.push(await this.payload(file));
      } catch (e) {
        const message = e && e.message ? e.message : String(e);
        this.provider.log.error(`Could not open ${file.uri.fsPath || file.uri.toString()}: ${message}`);
        this.post({ type: 'failed', name: file.name, message });
        this.provider.event({ type: 'failed', name: file.name, message });
      }
    }
    if (ready.length) await this.post({ type: 'open', why, files: ready });
  }

  watch(file) {
    const folder = vscode.Uri.joinPath(file.uri, '..');
    const pattern = new vscode.RelativePattern(folder, path.posix.basename(file.uri.path));
    let watcher;
    try {
      watcher = vscode.workspace.createFileSystemWatcher(pattern);
    } catch (e) {
      this.provider.log.warn(`Cannot watch ${file.uri.toString()} for changes: ${e.message || e}`);
      return;
    }
    const later = () => {
      clearTimeout(file.timer);
      file.timer = setTimeout(() => this.changed(file), RELOAD_QUIET_MS);
    };
    watcher.onDidChange(later);
    watcher.onDidCreate(later);
    watcher.onDidDelete(() => {
      clearTimeout(file.timer);
      this.post({ type: 'closed', name: file.name });
    });
    file.watcher = watcher;
  }

  changed(file) {
    if (!this.files.has(file.token) || !this.ready) return;
    this.provider.log.info(`${file.name} changed on disk; reading it again`);
    this.send([file], 'changed');
  }

  async receive(m) {
    if (!m || typeof m.type !== 'string') return;
    try {
      switch (m.type) {
        case 'ready': return this.onReady(m);
        case 'lazy': return this.answer(m.id, () => this.lazy(m));
        case 'save': return await this.save(m);
        case 'pick': return await this.pick();
        case 'drop': return this.dropped(m);
        case 'status': return this.status(m);
        case 'theme': return await this.provider.setThemeMode(m.mode);
        case 'log': return this.pageLog(m);
        default: this.provider.log.warn(`Ignored a "${m.type}" message from the page`);
      }
    } catch (e) {
      this.provider.log.error(`Handling "${m.type}" from the page failed:`, e);
      vscode.window.showErrorMessage(`HDF5 Browser: ${e && e.message ? e.message : e}`);
    }
  }

  onReady(m) {
    if (this.ready) {
      // The page was reloaded and holds nothing now: send every file again,
      // and let go of what the reader held for the old page.
      for (const [handle, h] of this.handles) this.release(handle, h);
    }
    this.ready = true;
    this.provider.log.info(`Page ready (${m.build || 'unknown build'}) for ${this.documentUri.toString()}`);
    this.provider.event({ type: 'ready', document: this.documentUri.fsPath });
    this.send([...this.files.values()], 'open');
  }

  async answer(id, fn) {
    let reply;
    try {
      reply = { type: 'answer', id, ok: await fn() };
    } catch (e) {
      reply = { type: 'answer', id, err: e && e.message ? e.message : String(e) };
    }
    this.post(reply);
  }

  async lazy({ token, cmd, args }) {
    const file = this.files.get(token);
    if (!file) throw new Error('that file is not open in this view');
    if (!READER_COMMANDS.has(cmd)) throw new Error(`unknown command ${cmd}`);
    const reader = this.provider.reader;
    if (cmd === 'open') {
      const opened = await reader.call('open', { file: file.uri.fsPath });
      // The page is given a handle of this host's, never the reader's own
      // number, so it cannot reach a file of another view or of a reader
      // started after this one stopped.
      const handle = ++this.nextHandle;
      this.handles.set(handle, { token, generation: reader.generation, fid: opened.fid });
      opened.fid = handle;
      return opened;
    }
    const h = this.handles.get(args && args.fid);
    if (!h || h.token !== token) throw new Error('that file is not open in this view');
    if (h.generation !== reader.generation || !reader.worker) {
      this.handles.delete(args.fid);
      throw new Error('the HDF5 reader was restarted; close the file and open it again');
    }
    const answer = await reader.call(cmd, Object.assign({}, args, { fid: h.fid }));
    if (cmd === 'close') this.handles.delete(args.fid);
    return answer;
  }

  release(handle, h) {
    this.handles.delete(handle);
    const reader = this.provider.reader;
    if (h.generation === reader.generation && reader.worker) {
      reader.call('close', { fid: h.fid }).catch(() => { /* gone already */ });
    }
  }

  defaultFolder() {
    const first = this.files.values().next().value;
    if (first) return vscode.Uri.joinPath(first.uri, '..');
    const folders = vscode.workspace.workspaceFolders;
    return folders && folders.length ? folders[0].uri : undefined;
  }

  async save({ name, bytes }) {
    if (!(bytes instanceof Uint8Array)) throw new Error('nothing to save');
    const fileName = safeFileName(name);
    const folder = this.defaultFolder();
    const target = this.provider.takeTestSave(fileName) || await vscode.window.showSaveDialog({
      defaultUri: folder ? vscode.Uri.joinPath(folder, fileName) : undefined,
      filters: saveFilters(fileName),
      title: `Save ${fileName}`
    });
    if (!target) return;
    await vscode.workspace.fs.writeFile(target, bytes);
    this.provider.log.info(`Saved ${target.fsPath} (${formatBytes(bytes.byteLength)})`);
    this.provider.event({ type: 'saved', path: target.fsPath, bytes: bytes.byteLength });
    const openable = /\.(csv|json)$/i.test(target.path);
    const choice = await vscode.window.showInformationMessage(`Saved ${path.posix.basename(target.path)}.`, ...(openable ? ['Open'] : []));
    if (choice === 'Open') await vscode.commands.executeCommand('vscode.open', target);
  }

  async pick() {
    const uris = this.provider.takeTestPick() || await vscode.window.showOpenDialog({
      canSelectMany: true,
      canSelectFiles: true,
      canSelectFolders: false,
      defaultUri: this.defaultFolder(),
      filters: { 'HDF5 files': ['h5', 'hdf5', 'he5'], 'All files': ['*'] },
      openLabel: 'Add',
      title: 'Add HDF5 files'
    });
    if (uris && uris.length) this.add(uris, 'added');
  }

  /**
   * Files dropped on the page as addresses: dragged from VS Code's Explorer
   * with Shift held, the only way such a drag reaches a webview. Files dragged
   * from the Finder arrive as files and the page reads them itself. What is
   * added is what Add Files could add; only HDF5 names are taken, since the
   * addresses come from the page.
   */
  dropped({ uris }) {
    const list = [];
    for (const s of Array.isArray(uris) ? uris.slice(0, DROP_MAX_FILES) : []) {
      let uri;
      try {
        uri = vscode.Uri.parse(String(s), true);
      } catch (_) {
        continue;
      }
      if (HDF5_NAME.test(uri.path)) list.push(uri);
    }
    this.provider.event({ type: 'dropped', files: list.map(u => u.fsPath || u.toString()) });
    if (list.length) this.add(list, 'added');
    else this.post({ type: 'notice', text: 'Only .h5, .hdf5 and .he5 files can be added.' });
  }

  status(m) {
    if (m.kind === 'opened') {
      const opened = (m.opened || []).map(f => `${f.name} (${f.mode === 'lazy' ? 'read lazily' : 'in memory'})`);
      if (opened.length) this.provider.log.info(`Opened ${opened.join(', ')}`);
      for (const f of m.failed || []) this.provider.log.error(`Could not open ${f.name}: ${f.message}`);
    }
    this.provider.event(Object.assign({}, m, { type: 'status' }));
  }

  pageLog(m) {
    const text = String(m.text || '').slice(0, 4000);
    if (m.level === 'error') this.provider.log.error(`[page] ${text}`);
    else this.provider.log.warn(`[page] ${text}`);
    this.provider.event({ type: 'log', level: m.level, text });
  }

  dispose() {
    this.disposed = true;
    for (const [handle, h] of this.handles) this.release(handle, h);
    for (const file of this.files.values()) {
      clearTimeout(file.timer);
      if (file.watcher) file.watcher.dispose();
    }
    this.files.clear();
    for (const s of this.subscriptions) s.dispose();
    this.subscriptions = [];
  }
}

/* ── the editor ───────────────────────────────────────────────────────── */

class Hdf5BrowserProvider {
  constructor(context, build, reader, log) {
    this.context = context;
    this.build = build;
    this.reader = reader;
    this.log = log;
    this.views = new Map();          // document URI -> View
    this.pendingExtras = new Map();  // document URI -> URIs to add once its view exists
    this.opening = new Set();        // document URIs the extension is opening a view of its own for
    this.tabOpenedAt = new Map();    // 'column|uri' -> when VS Code opened a tab of an HDF5 file there
    this.gatherers = new Map();      // column -> { view, until }: a browser taking the tabs opened with its file
    this.template = fs.readFileSync(path.join(__dirname, 'media', 'index.html'), 'utf8');
    this.testHooks = null;
  }

  openCustomDocument(uri) {
    return { uri, dispose() {} };
  }

  /**
   * The browser a file just opened should go into instead of a view of its
   * own, or null.
   *
   * A file dropped on a browser, from the Explorer or from the Finder, never
   * reaches the page: VS Code keeps a drag that starts in its window, or
   * crosses it, out of every webview unless Shift is held, and opens the file
   * as another editor in the group it was dropped on. So a file opened pinned
   * into a group where a browser was showing a moment ago goes into that
   * browser, as Add Files would put it there. A double-click in the Explorer
   * while a browser shows is taken the same way. Opened on its own: a preview
   * (a single click in the Explorer), what the extension opens itself (Open
   * Together), a drop on the edge of a group (VS Code opens a new group for
   * it), and everything when hdf5Browser.addToOpenBrowser is off.
   */
  browserShowingBehind(panel, uri) {
    if (!vscode.workspace.getConfiguration('hdf5Browser').get('addToOpenBrowser', true)) return null;
    if (this.opening.has(uri.toString())) return null;
    const tab = tabOf(uri, panel.viewColumn);
    if (tab && tab.isPreview) return null;
    const now = Date.now();
    let best = null;
    for (const view of this.views.values()) {
      if (view.panel.viewColumn !== panel.viewColumn) continue;
      const shown = view.panel.visible ? now : view.hiddenAt;
      if (!shown || now - shown > SHOWN_RECENTLY_MS) continue;
      if (!best || shown > best.shown) best = { view, shown };
    }
    return best ? best.view : null;
  }

  /*
    Several files dropped at once, or opened at once, VS Code opens as a tab
    each, and loads only the one it shows: the others wait, as tabs, to be
    clicked. So the browser the file it shows goes into takes the others too,
    the HDF5 tabs opened into its group within a moment and not yet loaded,
    and closes their tabs. Tabs VS Code restored from the last session were
    never seen being opened (the extension starts when VS Code has started:
    activationEvents onStartupFinished) and are left alone, as is a tab of a
    file with a browser of its own, a preview, and anything the extension
    opens itself.
  */

  /** VS Code opened tabs: note the HDF5 ones, and hand them to a browser gathering in their group. */
  tabsOpened(e) {
    const now = Date.now();
    for (const tab of e.opened) {
      if (!(tab.input instanceof vscode.TabInputCustom) || tab.input.viewType !== VIEW_TYPE) continue;
      const column = tab.group.viewColumn;
      this.tabOpenedAt.set(`${column}|${tab.input.uri.toString()}`, now);
      const g = this.gatherers.get(column);
      if (g && now <= g.until && !g.view.disposed && this.mayTake(tab)) this.take(g.view, [tab]);
    }
    for (const [k, t] of this.tabOpenedAt) if (now - t > 10 * TOGETHER_MS) this.tabOpenedAt.delete(k);
  }

  /** A tab a browser may take: an HDF5 file's, not loaded (the one shown loads itself), not a preview, not a browser of its own. */
  mayTake(tab, exceptUri) {
    if (!(tab.input instanceof vscode.TabInputCustom) || tab.input.viewType !== VIEW_TYPE) return false;
    const key = tab.input.uri.toString();
    if (exceptUri && key === exceptUri.toString()) return false;
    return !tab.isActive && !tab.isPreview && !this.views.has(key) && !this.opening.has(key);
  }

  /** From now until a moment on, `view` takes the HDF5 tabs opened into its group with the file at `uri`. */
  gatherInto(view, column, uri) {
    if (!vscode.workspace.getConfiguration('hdf5Browser').get('addToOpenBrowser', true)) return;
    const now = Date.now();
    const group = vscode.window.tabGroups.all.find(g => g.viewColumn === column);
    const already = group ? group.tabs.filter((tab) => {
      if (!this.mayTake(tab, uri)) return false;
      const at = this.tabOpenedAt.get(`${column}|${tab.input.uri.toString()}`);
      return at !== undefined && now - at <= TOGETHER_MS;
    }) : [];
    this.take(view, already);
    this.gatherers.set(column, { view, until: now + TOGETHER_MS });
  }

  /** `view` takes these tabs' files; the tabs are closed a moment later (see addInstead for why not at once). */
  take(view, tabs) {
    if (!tabs.length) return;
    const uris = tabs.map(t => t.input.uri);
    const column = tabs[0].group.viewColumn;
    view.add(uris, 'added');
    this.log.info(`${uris.map(u => path.posix.basename(u.path)).join(', ')} opened with ${path.posix.basename(view.documentUri.path)}; added to its HDF5 Browser`);
    this.event({ type: 'gathered', into: view.documentUri.fsPath, files: uris.map(u => u.fsPath) });
    setTimeout(async () => {
      for (const uri of uris) {
        const tab = tabOf(uri, column);
        if (!tab || tab.group.viewColumn !== column || this.views.has(uri.toString())) continue;
        try {
          await vscode.window.tabGroups.close(tab, true);
        } catch (_) {
          // closed already, by hand
        }
      }
    }, STAND_IN_MS);
  }

  /** The file goes into `view`; the editor VS Code opened for it says so, and is closed. */
  addInstead(view, uri, panel) {
    this.log.info(`${uri.fsPath || uri.toString()} was opened where an HDF5 Browser was showing; added to it`);
    view.add([uri], 'added');
    this.event({ type: 'addedInstead', into: view.documentUri.fsPath, file: uri.fsPath });
    this.gatherInto(view, panel.viewColumn, uri);
    panel.webview.html = standInHtml(path.posix.basename(uri.path));
    /*
      Closed a moment after it shows, not at once. Closed on the tick it
      showed, it left VS Code's handling of the drop that opened it
      unfinished, and the next drop on the browser reached nothing, neither
      the browser nor VS Code. 150 ms later was enough every time it was
      tried (test/test-drop.py), so it waits twice that.
    */
    const started = Date.now();
    const poll = setInterval(() => {
      if (!panel.visible && Date.now() - started < ADD_INSTEAD_WAIT_MS) return;
      clearInterval(poll);
      setTimeout(() => this.closeStandIn(view, uri, panel), STAND_IN_MS);
    }, 25);
  }

  /**
   * The group shows the browser again, the editor it showed before. A browser
   * still a preview is kept, or the next single click in the Explorer would
   * replace it, the file just added and all.
   */
  async closeStandIn(view, uri, panel) {
    try {
      const own = tabOf(uri, panel.viewColumn);
      if (own) await vscode.window.tabGroups.close(own, true);
      else panel.dispose();
    } catch (_) {
      // closed already, by hand
    }
    if (view.disposed) return;
    view.panel.reveal(view.panel.viewColumn);
    const tab = tabOf(view.documentUri, view.panel.viewColumn);
    if (tab && tab.isPreview) {
      await new Promise(resolve => setTimeout(resolve, 50));
      const active = vscode.window.tabGroups.activeTabGroup.activeTab;
      if (active && active.input instanceof vscode.TabInputCustom && active.input.uri.toString() === view.documentUri.toString()) {
        await vscode.commands.executeCommand('workbench.action.keepEditor');
      }
    }
  }

  async resolveCustomEditor(document, panel) {
    const key = document.uri.toString();
    const into = this.browserShowingBehind(panel, document.uri);
    if (into) {
      this.addInstead(into, document.uri, panel);
      return;
    }
    const view = new View(this, document.uri, panel);
    this.views.set(key, view);
    panel.onDidDispose(() => {
      view.dispose();
      if (this.views.get(key) === view) this.views.delete(key);
      for (const [column, g] of this.gatherers) if (g.view === view) this.gatherers.delete(column);
    });
    await view.start();
    view.add([document.uri], 'open');
    const tab = tabOf(document.uri, panel.viewColumn);
    if (!this.opening.has(key) && !(tab && tab.isPreview)) this.gatherInto(view, panel.viewColumn, document.uri);
    const extra = this.pendingExtras.get(key);
    if (extra) {
      this.pendingExtras.delete(key);
      view.add(extra, 'added');
    }
  }

  /** The Explorer's selection, in one view: the first file's, with the rest added. */
  async openTogether(uri, uris) {
    const chosen = (Array.isArray(uris) && uris.length ? uris : [uri]).filter(u => u && HDF5_NAME.test(u.path));
    const list = chosen.filter((u, i) => chosen.findIndex(v => v.toString() === u.toString()) === i);
    if (!list.length) {
      vscode.window.showWarningMessage('Select one or more .h5, .hdf5 or .he5 files.');
      return;
    }
    const [first, ...rest] = list;
    const view = this.views.get(first.toString());
    if (view) {
      view.panel.reveal();
      view.add(rest, 'added');
      return;
    }
    this.pendingExtras.set(first.toString(), rest);
    this.opening.add(first.toString());   // a view of their own, whatever is showing
    try {
      await vscode.commands.executeCommand('vscode.openWith', first, VIEW_TYPE);
    } finally {
      this.opening.delete(first.toString());
    }
  }

  /** The page's HTML for one webview, with its policy and its address for the bundled files. */
  html(webview) {
    const media = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, 'media')).toString();
    /*
      A policy source cannot name the resource host (it has a '+' in it, which
      a policy host may not), so it is VS Code's own wildcard with this
      extension's media folder as the path: the page's scripts, and no
      other file on the machine. ';' and ',' would end the source early.
    */
    const host = (webview.cspSource.split(/\s+/).find(s => /^https:\/\//.test(s)) || 'https://*.vscode-cdn.net').replace(/\/+$/, '');
    const folder = new URL(media).pathname.replace(/;/g, '%3B').replace(/,/g, '%2C');
    const src = `${host}${folder}/`;
    const csp = [
      "default-src 'none'",
      `script-src ${src} blob: 'wasm-unsafe-eval'`,
      `style-src ${src} 'unsafe-inline'`,
      `img-src ${src} data: blob:`,
      `font-src ${src} data:`,
      `connect-src ${src} blob: data:`,
      'worker-src blob:',
      "base-uri 'none'",
      "form-action 'none'",
      "frame-src 'none'",
      "object-src 'none'"
    ].join('; ');
    const theme = themeMode();
    const config = {
      media,
      build: this.build.stamp,
      built: this.build.built,   // early.js compares it with its own (an older extension still running after an update)
      readLazily: vscode.workspace.getConfiguration('hdf5Browser').get('readLazily', 'auto'),
      theme
    };
    return this.template
      .replace('{{CSP}}', () => escapeAttribute(csp))
      .replace('{{CONFIG}}', () => escapeAttribute(JSON.stringify(config)))
      .replace(/\{\{THEME\}\}/g, () => (theme === 'auto' ? themeKind() : theme))
      .replace(/\{\{MEDIA\}\}/g, () => media);
  }

  /** The header's toggle, from any view: kept in the setting, which every view then follows. */
  async setThemeMode(mode) {
    if (!THEME_MODES.has(mode)) throw new Error(`not a theme: ${mode}`);
    if (mode === themeMode()) return;
    await vscode.workspace.getConfiguration('hdf5Browser').update('theme', mode, vscode.ConfigurationTarget.Global);
  }

  /** Tell every open view what the theme setting is now. */
  themeChanged() {
    const mode = themeMode();
    for (const view of this.views.values()) view.post({ type: 'theme', mode });
    this.event({ type: 'theme', mode });
  }

  event(e) {
    if (this.testHooks) this.testHooks.event(e);
  }

  takeTestSave(name) {
    return this.testHooks ? this.testHooks.takeSave(name) : undefined;
  }

  takeTestPick() {
    return this.testHooks ? this.testHooks.takePick() : undefined;
  }
}

/* ── activation ───────────────────────────────────────────────────────── */

function activate(context) {
  const log = vscode.window.createOutputChannel('HDF5 Browser', { log: true });
  context.subscriptions.push(log);

  // First, so that a copy whose page cannot start still updates itself. A
  // copy run from its folder (development, the tests) looks only when asked.
  let provider = null;
  const updater = new Updater({ vscode, context, log, event: e => provider && provider.event(e) });
  context.subscriptions.push(vscode.commands.registerCommand('kvotab.hdf5Browser.checkForUpdates', () => updater.check(true)));
  if (context.extensionMode === vscode.ExtensionMode.Production) context.subscriptions.push(updater.start());

  let build;
  try {
    build = JSON.parse(fs.readFileSync(path.join(__dirname, 'media', 'build.json'), 'utf8'));
  } catch (e) {
    const message = 'HDF5 Browser is not built: run "node build.mjs" in its folder.';
    log.error(message, e);
    vscode.window.showErrorMessage(message);
    return;
  }
  log.info(`HDF5 Browser ${context.extension.packageJSON.version}, page ${build.stamp}`);

  const reader = new Reader(build, log);
  provider = new Hdf5BrowserProvider(context, build, reader, log);
  context.subscriptions.push(
    reader,
    vscode.window.registerCustomEditorProvider(VIEW_TYPE, provider, {
      webviewOptions: { retainContextWhenHidden: true },
      supportsMultipleEditorsPerDocument: false
    }),
    vscode.commands.registerCommand('kvotab.hdf5Browser.openTogether', (uri, uris) => provider.openTogether(uri, uris)),
    vscode.window.tabGroups.onDidChangeTabs(e => provider.tabsOpened(e)),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('hdf5Browser.theme')) provider.themeChanged();
    }),
    vscode.commands.registerCommand('kvotab.hdf5Browser.showLog', () => log.show())
  );

  // What test/runner.js drives in an integration test; an installed copy
  // (Production mode) gives nothing out.
  if (context.extensionMode !== vscode.ExtensionMode.Production) return { provider, log, viewType: VIEW_TYPE, updater };
  return undefined;
}

function deactivate() {}

module.exports = { activate, deactivate };
