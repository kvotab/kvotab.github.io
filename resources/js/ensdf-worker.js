/* ==========================================================================
   ENSDF.HTML: THE WORKER

   Holds a database the visitor opened. Messages in:

     { type: 'open',   id, files: [File, ...] }
     { type: 'detail', id, a }

   and out: { type: 'progress' | 'opened' | 'detail' | 'error', id, ... }.
   The details stay here and go to the page one mass number at a time, as
   the page asks for them; only the summary crosses in one piece.

   Version stamps: bump this file's own stamp in ensdf-ui.js whenever the
   list below changes. A Worker does not inherit the page's cache-busting.
   ========================================================================== */
/* global KVOT_ENSDF_OPEN */
importScripts('./ensdf-parse.js?v=20260922b', './ensdf-open.js?v=20260923');

let details = null;

self.onmessage = async (ev) => {
  const msg = ev.data || {};
  if (msg.type === 'open') {
    try {
      const res = await KVOT_ENSDF_OPEN.readFiles(msg.files, (p) => self.postMessage({ type: 'progress', id: msg.id, ...p }));
      details = res.details;
      self.postMessage({ type: 'opened', id: msg.id, summary: res.summary });
    } catch (e) {
      self.postMessage({ type: 'error', id: msg.id, message: (e && e.message) || String(e) });
    }
  } else if (msg.type === 'detail') {
    self.postMessage({ type: 'detail', id: msg.id, a: msg.a, detail: details ? details.get(msg.a) || null : null });
  }
};
