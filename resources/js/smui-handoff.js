/* ==========================================================================
   SMUI.HTML: FILES HANDED OVER BY ANOTHER PAGE

   The HDF5 Browser (rb.html) sends its tree's selection here as an HDF5
   file that never touches the disk (rb-smui.js): it opens this page with
   #handoff=<its origin>, this page says { kvot: 'smui-ready' } to it once
   it is listening (and again each second until something comes: the
   sender may still be packaging), and the file arrives as a transferred
   ArrayBuffer, { kvot: 'smui-open', name, buffer }. It opens as a dropped
   file does (SM.hdf5.open), every table in it at once unless that would be
   too many or too wide, when the Open HDF5 dialog asks. The answer is
   { kvot: 'smui-opened', tables } or { kvot: 'smui-error', message }.

   The sender may come back with another file: it asks { kvot: 'smui-ping' }
   and is answered 'smui-ready', so one tab gathers what it is sent. While
   it packages, { kvot: 'smui-progress', text } says what it is doing.

   Taken only with the #handoff hash, only from ALLOWED origins (this
   page's own, and a local server), only HDF5 bytes (smui-hdf5.js checks
   the signature), and up to MAX_BYTES. rb-handoff.js is the same protocol
   into rb.html.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});

  /* Origins allowed to hand files here. Never '*': any page holding a
     reference to this tab could then put tables into it. */
  const ALLOWED = [root.location.origin, 'http://localhost:8080'];
  const MAX_BYTES = 2 * 1024 * 1024 * 1024;
  const PING_MS = 1000;
  const PROGRESS_EVERY_MS = 1200;

  /* '#handoff' or '#handoff=<the sender's origin>', read once at load. */
  function readHash() {
    const m = /^#handoff(?:=(.*))?$/.exec(String(root.location.hash || ''));
    if (!m) return null;
    let declared = null;
    if (m[1]) {
      try { declared = new URL(decodeURIComponent(m[1])).origin; } catch (e) { declared = null; }
    }
    return { declared };
  }

  const allowed = (origin, declared) => !!origin && origin !== 'null' && ALLOWED.includes(origin) && (!declared || origin === declared);

  /* A name for the file: one line, no path, an HDF5 extension. */
  function cleanName(name) {
    let s = String(name == null ? '' : name).replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, ' ').replace(/[\\/]/g, '_').trim();
    if (!s || s === '.' || s === '..') s = 'handoff.h5';
    if (s.length > 120) s = s.slice(0, 120);
    if (!/\.(h5|hdf5|he5|nc|mat)$/i.test(s)) s += '.h5';
    return s;
  }

  function reply(event, message) {
    try { if (event.source) event.source.postMessage(message, event.origin); } catch (e) { /* the sender is gone */ }
  }

  async function receive(event) {
    const data = event.data;
    const buffer = data.buffer;
    if (!(buffer instanceof ArrayBuffer)) { reply(event, { kvot: 'smui-error', message: 'no file in the message' }); return; }
    if (buffer.byteLength > MAX_BYTES) { reply(event, { kvot: 'smui-error', message: 'the file is larger than this page takes (2 GB)' }); return; }
    const name = cleanName(data.name);
    SM.whenApp(async (app) => {
      try {
        const file = new File([buffer], name, { type: 'application/x-hdf5' });
        const tables = await SM.hdf5.open(app, file, { state: 'all-or-ask' });
        reply(event, { kvot: 'smui-opened', tables: tables.map((t) => t.name) });
      } catch (e) {
        const message = String((e && e.message) || e);
        SM.ui.toast(`${name}: ${message}`, { error: true });
        reply(event, { kvot: 'smui-error', message });
      }
    });
  }

  function start() {
    const hash = readHash();
    if (!hash) return;
    let heard = false;
    let lastProgress = 0;
    root.addEventListener('message', (event) => {
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      const kind = data.kvot;
      if (kind !== 'smui-open' && kind !== 'smui-ping' && kind !== 'smui-progress') return;
      if (!allowed(event.origin, hash.declared)) return;
      heard = true;
      if (kind === 'smui-ping') { reply(event, { kvot: 'smui-ready' }); return; }
      if (kind === 'smui-progress') {
        const now = Date.now();
        if (now - lastProgress < PROGRESS_EVERY_MS || typeof data.text !== 'string') return;
        lastProgress = now;
        const text = data.text.replace(/\s+/g, ' ').trim().slice(0, 160);
        SM.whenApp(() => SM.ui.toast(text));
        return;
      }
      receive(event);
    });
    // said to the opener until anything comes: a sender that is still
    // packaging may not be listening yet
    const target = root.opener || null;
    if (!target) return;
    const to = hash.declared && ALLOWED.includes(hash.declared) ? hash.declared : '*';
    const announce = () => { try { target.postMessage({ kvot: 'smui-ready' }, to); } catch (e) { /* the opener is gone */ } };
    announce();
    const pinger = root.setInterval(() => { if (heard || target.closed) root.clearInterval(pinger); else announce(); }, PING_MS);
    SM.whenApp(() => { if (!heard) SM.ui.toast('Waiting for the HDF5 Browser to send its selection…'); });
  }

  SM.handoff = Object.freeze({ ALLOWED, cleanName });
  start();
}(typeof self !== 'undefined' ? self : this));
