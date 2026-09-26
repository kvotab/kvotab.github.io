/* ==========================================================================
   FARF31.HTML: THE CALCULATION OFF THE MAIN THREAD

   One message in: {id, input}, the case as Farf31Model.run takes it.
   Progress messages while it runs ({type: 'progress', done, n, what}), then
   one {type: 'done', result} with the arrays transferred, or
   {type: 'error', message}.

   A Worker does not inherit the page's cache stamps: bump the one on the
   import below, and this file's own in farf31-ui.js (WORKER_URL), whenever
   farf31-model.js changes.
   ========================================================================== */
'use strict';

self.importScripts('./farf31-model.js?v=20260926d');

self.onmessage = (ev) => {
  const { id, input } = ev.data || {};
  try {
    let last = 0;
    const res = self.Farf31Model.run(input, (done, n, what) => {
      const now = Date.now();
      if (now - last > 100 || done === n) { self.postMessage({ id, type: 'progress', done, n, what }); last = now; }
    });
    const buffers = new Set();
    const add = (a) => { if (a && a.buffer && !buffers.has(a.buffer)) buffers.add(a.buffer); };
    add(res.times);
    res.out.forEach(add);
    res.bq.forEach(add);
    for (const r of res.responses) { add(r.t); add(r.h); add(r.dh); add(r.d2h); }
    if (res.at) { add(res.at.times); res.at.out.forEach(add); }
    self.postMessage({ id, type: 'done', result: res }, Array.from(buffers));
  } catch (e) {
    self.postMessage({ id, type: 'error', message: e && e.message ? e.message : String(e) });
  }
};
