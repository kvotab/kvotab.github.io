/* ==========================================================================
   distributions.html: THE WORKER

   The jobs that can take seconds, off the page's thread: fitting every
   family to a sample (with progress), the draws of a Monte Carlo
   expression, and the Sample tab's draws (with progress). Messages:
   { id, type: 'fit' | 'mc' | 'sample', payload } in;
   { id, type: 'progress' | 'result' | 'error', ... } out.
   ========================================================================== */

import { fitAll } from './fit.js';
import { runMonteCarlo } from './mc.js';
import { sampleJob } from './sampling.js';

self.onmessage = (ev) => {
  const { id, type, payload } = ev.data || {};
  try {
    if (type === 'fit') {
      let lastPost = 0;
      const out = fitAll(payload.values, payload.opts, (done, total, label) => {
        const now = Date.now();
        if (now - lastPost > 60 || done === total) { lastPost = now; self.postMessage({ id, type: 'progress', done, total, label }); }
      });
      self.postMessage({ id, type: 'result', result: out });
    } else if (type === 'mc') {
      const r = runMonteCarlo(payload.specs, payload.expr, payload.n, payload.seed, payload.scheme);
      self.postMessage({ id, type: 'result', result: r }, [r.values.buffer]);
    } else if (type === 'sample') {
      const r = sampleJob(payload, (done, total, label) => self.postMessage({ id, type: 'progress', done, total, label }));
      self.postMessage({ id, type: 'result', result: r }, r.columns.filter((c) => c.values).map((c) => c.values.buffer));
    } else {
      self.postMessage({ id, type: 'error', message: `Unknown job ${type}` });
    }
  } catch (e) {
    self.postMessage({ id, type: 'error', message: e && e.message ? e.message : String(e) });
  }
};
