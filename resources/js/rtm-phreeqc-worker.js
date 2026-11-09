/* ==========================================================================
   RTM.HTML: THE WORKER PHREEQC RUNS IN

   A classic worker of its own, started the first time the page asks PHREEQC
   anything, so that the 2.4 MB of PHREEQC are fetched only by someone
   who uses it, and a long look at a run through PHREEQC leaves the page and
   the solver's worker free. The jobs are RtmPhreeqcEngine.handler's.

   Version stamps: bump this file's OWN stamp, in rtm-ui.js, whenever the list
   below changes -- a Worker does not inherit the page's cache-busting.
   ========================================================================== */
importScripts(
  '../../vendors/phreeqc/phreeqc.js?v=20261107',
  '../../vendors/phreeqc/phreeqc-dat.js?v=20261107',
  './facsimile-model.js?v=20261005',
  './rtm-model.js?v=20261109g',
  './rtm-phreeqc.js?v=20261109b',
  './rtm-phreeqc-engine.js?v=20261107b',
);

const handlePhreeqc = self.RtmPhreeqcEngine.handler(self.createPhreeqc, { builtin: self.PHREEQC_DAT });
self.onmessage = (ev) => { handlePhreeqc(ev.data, (message) => self.postMessage(message)); };
