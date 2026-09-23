#!/usr/bin/env node
/*
  The ode_julia bundle is now one of the solver packages scripts/build-solvers.mjs
  builds, together with Kompartment's copy of it. This name is kept so that the
  instructions written before still work.
*/
await import('./build-solvers.mjs');
