/* ==========================================================================
   FACSIMILE.HTML: WHAT THE WORKER STARTS

   A classic worker. It was a module for a while, because Pyodide 0.28 and
   later refuse to load in anything else and the page offered SciPy's solvers
   through it. Those are gone, and with them the only reason to insist on a
   module worker -- which some browsers will not start at all, and which sent
   the page down to running on its own thread when they would not. Nothing
   here needs one.

   The four files below are ordinary scripts that each leave one object on the
   global, brought in for that effect in dependency order.

   Version stamps: bump this file's OWN stamp, in facsimile-ui.js, whenever the
   list below changes. A Worker does not inherit the page's cache-busting, so
   an entry whose imports moved on while its own URL did not is served from
   cache with the old list, and the page then offers solvers the worker has
   never heard of. The page asks the worker what it can run, to catch exactly
   that.
   ========================================================================== */
importScripts(
  './facsimile-model.js?v=20260917zd',
  './facsimile-solver.js?v=20260921',
  './ode-julia.js?v=20260917zd',
  './facsimile-ode-julia.js?v=20260917zd',
  './facsimile-worker.js?v=20260917zd',
);

self.onmessage = (ev) => self.handleFacsimileMessage(
  ev.data, (message, transfer) => self.postMessage(message, transfer || []),
);
