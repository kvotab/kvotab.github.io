/* ==========================================================================
   RTM.HTML: WHAT THE WORKER STARTS

   A classic worker: it brings in the files below and wires the handler to
   onmessage. Classic rather than a module because nothing here needs one and
   a classic worker starts in more browsers.

   Version stamps: bump this file's OWN stamp, in rtm-ui.js, whenever the list
   below changes. A Worker does not inherit the page's cache-busting, so an
   entry whose imports moved on while its own URL did not is served from cache
   with the old list, and the page then offers solvers the worker has never
   heard of. The page asks the worker what it can run, to catch exactly that.
   ========================================================================== */
importScripts(
  './facsimile-model.js?v=20260920',
  './facsimile-solver.js?v=20260921',
  './ode-julia.js?v=20260920',
  './facsimile-ode-julia.js?v=20260920',
  './rtm-model.js?v=20260923',
  './rtm-worker.js?v=20260923',
);

self.onmessage = (ev) => self.handleRtmMessage(
  ev.data, (message, transfer) => self.postMessage(message, transfer || []),
);
