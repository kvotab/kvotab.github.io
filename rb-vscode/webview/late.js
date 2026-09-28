/* ==========================================================================
   RB.HTML IN A VS CODE WEBVIEW: AFTER THE PAGE'S OWN SCRIPTS

   Files come from the extension instead of the page's file input:

   * one read whole (under 256 MB, or as the hdf5Browser.readLazily setting
     says) arrives as bytes and goes in through ingestHdf5Buffer, the entry
     point the file picker and the handoff use;
   * one read lazily arrives as a token, and goes in through registerLazyFile
     with a reader that asks the extension, whose worker thread answers as
     rb-lazy-worker.js answers in the page.

   Either way what follows is what the file input's handler does: the tree
   worker, the tabs, the ticker. Add Files asks the extension for VS Code's
   open dialog, which in a remote window shows the remote machine's files.
   A drop that reaches the page (only with Shift held; VS Code keeps other
   drags from a webview and the extension handles those) is files, which
   rb-dragdrop.js reads, or addresses from VS Code's Explorer, which go to
   the extension.
   ========================================================================== */

(function () {
  'use strict';

  const host = window.KvotVscodeHost;

  /** An ArrayBuffer of exactly these bytes, however they arrived. */
  function bufferOf(bytes) {
    if (bytes instanceof ArrayBuffer) return bytes;
    return bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
      ? bytes.buffer
      : bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  }

  async function openOne(f) {
    if (f.mode === 'lazy') {
      const check = validateHdf5Buffer(bufferOf(f.head));
      if (!check.ok) throw new Error(`${f.name}: ${check.reason}`);
      const call = (cmd, args) => host.lazy(f.token, cmd, args);
      await registerLazyFile(f.name, await call('open', {}), call, 'vscode:open');
    } else {
      await ingestHdf5Buffer(f.name, bufferOf(f.bytes), 'vscode:open');
    }
  }

  /** Files the extension sends: opened, reopened after a change, or added. */
  async function openFromHost(files, why) {
    const opened = [];
    const failed = [];
    showFileLoadTicker(0, files.length, why === 'changed' ? 'Reloading…' : 'Starting…');
    try {
      await waitForH5Wasm();
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        updateFileLoadTicker(i, files.length, why === 'changed' ? `${f.name} changed on disk` : f.name);
        try {
          await openOne(f);
          opened.push({ name: f.name, mode: f.mode });
        } catch (err) {
          failed.push({ name: f.name, message: String(err && err.message || err) });
          reportFailure('vscode:open', err, { userMessage: `Could not open ${f.name}.` });
        }
      }
      try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('vscode:open', _); }
      updateFileLoadTicker(files.length, files.length, 'Refreshing tree…');
      await updateTabs(true);
      hideFileLoadTicker();
    } catch (err) {
      hideFileLoadTicker();
      failed.push({ name: '*', message: String(err && err.message || err) });
      reportFailure('vscode:open', err, { userMessage: 'Opening the files failed.' });
    }
    host.post('status', { kind: 'opened', why, opened, failed });
  }

  // One batch at a time, in the order they came: a reload must not overtake
  // the open it replaces.
  let queue = Promise.resolve();
  host.on('open', (m) => {
    queue = queue.then(() => openFromHost(m.files || [], m.why || 'open'));
  });

  // The extension could not read it: empty, too large to read whole, gone.
  host.on('failed', (m) => {
    reportFailure('vscode:open', new Error(m.message), { userMessage: `Could not open ${m.name}` });
  });

  // Something to tell, not a failure: a drop of nothing the browser opens.
  host.on('notice', (m) => notifyUser(String(m.text || '')));

  host.on('closed', (m) => {
    // The file went away on disk; it stays on screen, but says so.
    notifyUser(`${m.name} was deleted or moved on disk. What is shown is what it held before.`);
  });

  // Add Files: VS Code's own open dialog, through the extension.
  KVOT_ACTIONS.openFilePicker = () => host.post('pick');

  /**
   * The files a drop names without carrying them: dragged from VS Code's
   * Explorer, which a webview is let see only with Shift held, a drop is a
   * list of addresses. The extension reads them, as for Add Files. Files
   * dragged from the Finder are files, and rb-dragdrop.js reads them itself.
   */
  function droppedAddresses(dt) {
    const lines = (type) => String(dt.getData(type) || '').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#'));
    let uris = lines('application/vnd.code.uri-list');
    if (!uris.length) uris = lines('text/uri-list');
    if (!uris.length) {
      try {
        const listed = JSON.parse(dt.getData('ResourceURLs') || '[]');
        if (Array.isArray(listed)) uris = listed.map(String);
      } catch (_) {
        ignoreFailure('vscode:drop', _);
      }
    }
    return [...new Set(uris)];
  }

  // Ahead of rb-dragdrop.js's own listener on the body, which stops the drop there.
  document.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    if (!dt || dt.files.length) return;
    const uris = droppedAddresses(dt);
    if (uris.length) host.post('drop', { uris });
  }, true);

  // The light/dark toggle build.mjs puts in the header (early.js switches).
  registerActions({ 'vscode:toggleTheme': () => host.toggleTheme() });

  document.addEventListener('DOMContentLoaded', () => host.post('ready', { build: host.config.build }));
})();
