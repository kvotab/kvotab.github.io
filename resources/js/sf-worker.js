/* ==========================================================================
   SIMPLEFUNCTIONS.HTML: THE MONTE CARLO OFF THE MAIN THREAD

   One message in: {id, data, options, waters, runCfg}. Progress messages
   while it runs ({type: 'progress', done, n}), then one {type: 'done',
   result} with the arrays transferred, or {type: 'error', message}. The
   page compiles the same dataset with the same options, so the indices in
   the result mean the same there.
   ========================================================================== */
'use strict';

self.importScripts('./sf-model.js?v=20260925');

self.onmessage = (ev) => {
  const { id, data, options, waters, runCfg } = ev.data || {};
  try {
    const plan = self.SFModel.compile(data, options);
    const errors = plan.issues.filter((i) => i.severity === 'error');
    if (errors.length) throw new Error(`${errors[0].where}: ${errors[0].message}`);
    const runner = self.SFModel.createRunner(plan, waters, runCfg);
    let last = 0;
    while (runner.done < runner.n) {
      runner.step(1000);
      const now = Date.now();
      if (now - last > 120) { self.postMessage({ id, type: 'progress', done: runner.done, n: runner.n }); last = now; }
    }
    const res = runner.result();
    const buffers = new Set();
    const add = (a) => { if (a && a.buffer && !buffers.has(a.buffer)) buffers.add(a.buffer); };
    res.S.forEach(add);
    res.control.forEach(add);
    if (res.solidS) res.solidS.forEach((list) => list.forEach(add));
    add(res.waterIndex);
    add(res.diag.siCalcite);
    add(res.diag.Eh);
    add(res.diag.Fe);
    if (res.inputs) res.inputs.values.forEach(add);
    self.postMessage({ id, type: 'done', result: res }, Array.from(buffers));
  } catch (e) {
    self.postMessage({ id, type: 'error', message: e && e.message ? e.message : String(e) });
  }
};
