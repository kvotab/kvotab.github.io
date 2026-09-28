/* ==========================================================================
   RB.HTML IN A VS CODE WEBVIEW: BEFORE THE PAGE'S OWN SCRIPTS

   The page's scripts run here unchanged; what differs is the frame around
   them, and this puts back what they expect of a browser tab.

   * Workers. A webview's resources are on another origin, so new Worker(url)
     throws, and a worker made some other way cannot fetch them either: VS
     Code's service worker answers no request from a worker (it finds no
     webview for it, and the request times out after 30 s). So a worker is
     made from its source, which build.mjs bundles, behind a preamble that
     sends the worker's fetches of h5wasm and the plugins to this page, which
     can fetch them, and hands back blob URLs. The integrity pins still apply:
     the worker fetches the blob with them.
   * The CDNs. Everything the page loads from a CDN is bundled, and a fetch of
     a CDN address goes to the bundled copy. The Content-Security-Policy lets
     nothing else out.
   * Saving. A download (an <a download> clicked) becomes the extension's Save
     dialog. The page revokes its blob URL straight after the click, so the
     Blob is taken hold of when the URL is made.
   * The theme is VS Code's, followed as it changes, unless the reader has
     chosen light or dark with the header's toggle.
   * prompt(), confirm() and alert() show nothing in a webview; they say so
     in the log instead of failing silently.

   The channel to the extension is kept in here. The page is given the few
   things it needs (window.KvotVscodeHost), not the channel itself.
   ========================================================================== */

(function () {
  'use strict';

  const config = JSON.parse(document.querySelector('meta[name="kvot-vscode"]').content);
  const MEDIA = config.media;
  const codec = window.KvotVscodeCodec;
  const vscode = acquireVsCodeApi();

  /* ── an extension older than these files ──────────────────────────────── */

  /*
    A .vsix of the same version installed over the one running replaces these
    files at once, while the extension that serves the page stays the one the
    window started with until it is reloaded. Its page, with its old list of
    scripts, then runs the new ones, and parts went missing: "Download Excel"
    failed with downloadChartDataAsExcel not defined (2026-09-28). build.mjs
    writes its build in here; the extension says which build it started with.
  */
  const FILES = { stamp: '__RB_VSCODE_STAMP__', built: '__RB_VSCODE_BUILT__' };
  if (!FILES.built.startsWith('__')
      && (config.built ? config.built !== FILES.built : config.build !== FILES.stamp)) {
    post('log', { level: 'warn', text: `the page's files are build ${FILES.stamp}, the extension serving it is ${config.build}: reload the window` });
    const show = () => {
      const bar = document.createElement('div');
      bar.className = 'rb-vscode-stale';
      bar.setAttribute('role', 'alert');
      Object.assign(bar.style, {
        position: 'fixed', top: '0', left: '0', right: '0', zIndex: '100000', padding: '8px 40px 8px 12px',
        font: '13px var(--vscode-font-family, sans-serif)', color: 'var(--vscode-foreground, #ccc)',
        background: 'var(--vscode-inputValidation-warningBackground, #5f4a0e)',
        borderBottom: '1px solid var(--vscode-inputValidation-warningBorder, #b89500)'
      });
      bar.textContent = 'The HDF5 Browser was updated while this window was open. Run "Developer: Reload Window" '
        + 'from the Command Palette to use the new version: until then parts of it may not work.';
      const close = document.createElement('button');
      close.type = 'button';
      close.textContent = '×';
      close.title = 'Close';
      close.setAttribute('aria-label', 'Close');
      Object.assign(close.style, { position: 'absolute', right: '8px', top: '4px', font: 'inherit', fontSize: '16px',
        background: 'none', border: '0', color: 'inherit', cursor: 'pointer' });
      close.addEventListener('click', () => bar.remove());
      bar.appendChild(close);
      document.body.prepend(bar);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', show);
    else show();
  }

  /* ── the channel ──────────────────────────────────────────────────────── */

  const listeners = new Map();   // type -> [fn]
  const pending = new Map();     // id -> { resolve, reject }
  let seq = 0;

  function post(type, payload = {}) {
    vscode.postMessage(Object.assign({ type }, payload));
  }

  function request(type, payload = {}) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      post(type, Object.assign({ id }, payload));
    });
  }

  window.addEventListener('message', (event) => {
    // The extension's messages arrive through the webview's own host frame.
    if (event.origin !== window.location.origin) return;
    const m = event.data;
    if (!m || typeof m.type !== 'string') return;
    if (m.type === 'answer') {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.err) p.reject(new Error(m.err));
      else p.resolve(codec.decode(m.ok));
      return;
    }
    for (const fn of listeners.get(m.type) || []) {
      try {
        fn(m);
      } catch (e) {
        console.error(`HDF5 Browser: handling "${m.type}" failed`, e);
      }
    }
  });

  /* ── the log ──────────────────────────────────────────────────────────── */

  let logged = 0;
  function log(level, parts) {
    if (logged++ > 500) return;
    const text = parts.map(p => (p instanceof Error ? (p.stack || p.message) : typeof p === 'string' ? p : safeJson(p))).join(' ');
    post('log', { level, text: text.slice(0, 4000) });
  }
  function safeJson(v) {
    try { return JSON.stringify(v); } catch (_) { return String(v); }
  }
  for (const level of ['error', 'warn']) {
    const original = console[level].bind(console);
    console[level] = (...parts) => { log(level, parts); original(...parts); };
  }
  window.addEventListener('error', (e) => log('error', [e.error || e.message || 'error']));
  window.addEventListener('unhandledrejection', (e) => log('error', ['unhandled rejection:', e.reason]));
  document.addEventListener('securitypolicyviolation', (e) => {
    log('error', [`blocked by the Content-Security-Policy: ${e.violatedDirective} ${e.blockedURI || ''}`]);
  });
  window.prompt = () => { log('warn', ['prompt() was called; a webview shows nothing for it']); return null; };
  window.confirm = () => { log('warn', ['confirm() was called; a webview shows nothing for it']); return false; };
  window.alert = (m) => { log('warn', ['alert() was called; a webview shows nothing for it:', String(m)]); };

  /* ── the CDNs ─────────────────────────────────────────────────────────── */

  const CDN = /^https:\/\/(cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|cdn\.plot\.ly)\//;

  /** The bundled copy of a CDN address, or null for anything else. */
  function bundled(url) {
    return CDN.test(url) ? `${MEDIA}/vendor/${url.slice('https://'.length).split(/[?#]/)[0]}` : null;
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = function fetch(input, init) {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input && input.url;
    const local = url ? bundled(url) : null;
    return realFetch(local || input, init);
  };

  /* ── workers ──────────────────────────────────────────────────────────── */

  // Runs in every worker before its own script. Kept as a function so it is
  // checked as code; its text is what goes into the worker.
  function preamble(CDN_SOURCE) {
    const CDN = new RegExp(CDN_SOURCE);
    let port = null;
    let seq = 0;
    const pending = new Map();
    const waiting = [];
    self.addEventListener('message', function takePort(event) {
      if (!event.data || !event.data.__kvotVscodePort) return;
      // The page's first message is this port; the worker's own script never sees it.
      event.stopImmediatePropagation();
      self.removeEventListener('message', takePort);
      port = event.data.__kvotVscodePort;
      port.onmessage = (e) => {
        const p = pending.get(e.data.id);
        if (!p) return;
        pending.delete(e.data.id);
        if (e.data.error) p.reject(new Error(e.data.error));
        else p.resolve(e.data.url);
      };
      waiting.splice(0).forEach(fn => fn());
    });
    const ask = url => new Promise((resolve, reject) => {
      const send = () => {
        const id = ++seq;
        pending.set(id, { resolve, reject });
        port.postMessage({ id, url });
      };
      if (port) send();
      else waiting.push(send);
    });
    const realFetch = self.fetch.bind(self);
    self.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : input && input.url;
      if (url && CDN.test(url)) return ask(url).then(blobUrl => realFetch(blobUrl, init));
      return realFetch(input, init);
    };
  }
  const PREAMBLE = `(${preamble.toString()})(${JSON.stringify(CDN.source)});\n`;

  const blobUrls = new Map();   // CDN address -> Promise of a blob: URL of the bundled copy
  function serveWorkerFetch(event) {
    const { id, url } = event.data || {};
    const port = event.target;
    const local = bundled(url);
    if (!local) {
      port.postMessage({ id, error: `not bundled: ${url}` });
      return;
    }
    if (!blobUrls.has(url)) {
      blobUrls.set(url, realFetch(local)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status} for the bundled copy of ${url}`);
          return r.blob();
        })
        .then(blob => URL.createObjectURL(blob)));
    }
    blobUrls.get(url).then(
      blobUrl => port.postMessage({ id, url: blobUrl }),
      (e) => {
        blobUrls.delete(url);
        port.postMessage({ id, error: String(e && e.message || e) });
      });
  }

  const RealWorker = window.Worker;
  function Worker(url, options) {
    const key = new URL(String(url), `${MEDIA}/`).pathname.slice(new URL(`${MEDIA}/`).pathname.length);
    const sources = window.KVOT_VSCODE_WORKER_SOURCES || {};
    if (!Object.prototype.hasOwnProperty.call(sources, key)) {
      throw new Error(`HDF5 Browser: no bundled worker for ${url} (build.mjs bundles the workers the page names)`);
    }
    const blob = new Blob([PREAMBLE, sources[key], `\n//# sourceURL=${MEDIA}/${key}`], { type: 'text/javascript' });
    // Not revoked: the worker may not have read it yet, and a page makes two workers at most.
    const worker = new RealWorker(URL.createObjectURL(blob), options);
    const channel = new MessageChannel();
    channel.port1.onmessage = serveWorkerFetch;
    worker.postMessage({ __kvotVscodePort: channel.port2 }, [channel.port2]);
    return worker;
  }
  Worker.prototype = RealWorker.prototype;
  window.Worker = Worker;

  /* ── saving ───────────────────────────────────────────────────────────── */

  const blobsByUrl = new Map();
  const realCreateObjectURL = URL.createObjectURL;
  const realRevokeObjectURL = URL.revokeObjectURL;
  URL.createObjectURL = function createObjectURL(obj) {
    const url = realCreateObjectURL.call(URL, obj);
    if (obj instanceof Blob) blobsByUrl.set(url, obj);
    return url;
  };
  URL.revokeObjectURL = function revokeObjectURL(url) {
    blobsByUrl.delete(url);
    return realRevokeObjectURL.call(URL, url);
  };

  function dataUrlBytes(href) {
    const comma = href.indexOf(',');
    const head = href.slice(5, comma);
    const body = href.slice(comma + 1);
    if (/;base64$/i.test(head)) {
      const bin = atob(body);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    return new TextEncoder().encode(decodeURIComponent(body));
  }

  /** Hand a download to the extension. Called during the click, before the page revokes the URL. */
  function saveDownload(name, href) {
    const blob = href.startsWith('blob:') ? blobsByUrl.get(href) : null;
    if (href.startsWith('blob:') && !blob) {
      log('error', [`a download of ${name} was lost: its blob was not seen being made`]);
      return;
    }
    const bytes = blob ? blob.arrayBuffer().then(b => new Uint8Array(b)) : Promise.resolve(dataUrlBytes(href));
    bytes.then(
      b => post('save', { name: String(name || 'download'), bytes: b }),
      e => log('error', [`preparing ${name} for saving failed:`, e]));
  }

  const isDownload = a => a.hasAttribute('download') && /^(blob|data):/i.test(a.href);
  const realClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function click() {
    if (isDownload(this)) {
      saveDownload(this.getAttribute('download'), this.href);
      return;
    }
    return realClick.call(this);
  };
  document.addEventListener('click', (e) => {
    const a = e.target && e.target.closest ? e.target.closest('a[download]') : null;
    if (a && isDownload(a)) {
      e.preventDefault();
      saveDownload(a.getAttribute('download'), a.href);
    }
  }, true);

  /* ── the theme ────────────────────────────────────────────────────────── */

  function vscodeTheme() {
    const c = document.body ? document.body.classList : null;
    if (!c) return null;
    if (c.contains('vscode-light') || c.contains('vscode-high-contrast-light')) return 'light';
    if (c.contains('vscode-dark') || c.contains('vscode-high-contrast')) return 'dark';
    return null;
  }

  /*
    The theme the page is in: 'auto' follows VS Code's; 'light' and 'dark' are
    the reader's own choice, made with the header's toggle and kept by the
    extension in the hdf5Browser.theme setting, so that every view and every
    later session has it.
  */
  let themeMode = config.theme === 'light' || config.theme === 'dark' ? config.theme : 'auto';

  function shownTheme() {
    return themeMode === 'auto' ? vscodeTheme() : themeMode;
  }

  function applyTheme() {
    const theme = shownTheme();
    if (!theme) return;
    const html = document.documentElement;
    // data-theme-default is what site.js falls back to; data-theme is what the
    // page is drawn in, and rb's MutationObserver recolours the chart on it.
    if (html.getAttribute('data-theme-default') !== theme) html.setAttribute('data-theme-default', theme);
    if (html.getAttribute('data-theme') !== theme) {
      html.setAttribute('data-theme', theme);
      html.dispatchEvent(new CustomEvent('kvot-theme-change', { detail: { theme } }));
    }
    const toggle = document.querySelector('.rb-theme-toggle');
    if (toggle) {
      const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
      toggle.title = themeMode === 'auto' ? `${label} (now following VS Code's theme)` : label;
      toggle.setAttribute('aria-label', label);
    }
  }

  function setThemeMode(mode) {
    themeMode = mode === 'light' || mode === 'dark' ? mode : 'auto';
    applyTheme();
  }

  /**
   * The header's toggle: the other theme. Choosing the one VS Code is in is
   * going back to following it, so that is 'auto' again, not a fixed choice.
   */
  function toggleTheme() {
    const next = shownTheme() === 'dark' ? 'light' : 'dark';
    setThemeMode(next === vscodeTheme() ? 'auto' : next);
    post('theme', { mode: themeMode });
  }

  // The setting changed, here or in another view, or in Settings.
  listeners.set('theme', [m => setThemeMode(m.mode)]);

  // site.js prefers a theme chosen on the site over the page's default; the
  // choosing is done here, so nothing it stored may override it.
  try { localStorage.removeItem('kvot-theme'); } catch (_) { /* no storage */ }
  // The same switch the page reads for a file dropped into it.
  try {
    if (config.readLazily === 'always' || config.readLazily === 'never') localStorage.setItem('kvot-rb-lazy', config.readLazily);
    else localStorage.removeItem('kvot-rb-lazy');
  } catch (_) { /* no storage: the size rule */ }

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme();
    // VS Code's theme is on the body's class, and changes with it.
    new MutationObserver(applyTheme).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  });

  /* ── what the page is given ───────────────────────────────────────────── */

  window.KvotVscodeHost = Object.freeze({
    /** Tell the extension something; nothing comes back. */
    post,
    /** Ask the extension's reader about a file it opened: rbLazyCall's shape. */
    lazy: (token, cmd, args) => request('lazy', { token, cmd, args: args || {} }),
    /** Run fn for each message of this type from the extension. */
    on(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    log,
    config,
    /** Switch between light and dark (the header's toggle). */
    toggleTheme
  });
})();
