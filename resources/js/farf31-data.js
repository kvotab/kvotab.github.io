/* ==========================================================================
   FARF31.HTML: CHAINS AND EXAMPLES

   Half-lives (years) of the nuclides the presets use, rounded from the
   evaluated nuclear data (ENSDF/NUBASE) -- well-known values, enough for a
   far-field calculation; edit them on the Input tab if a case needs others.
   The four actinide chains are the long-lived members of the decay series,
   with the short-lived members left out (FARF31 takes unbranched chains
   only). The examples are made up for trying the page; they are not data
   from any safety assessment. Ka, the sorption on the fracture surfaces, is
   the page's addition (0 where it is left out).

   ONE GLOBAL: Farf31Data.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.Farf31Data = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const HALF_LIFE = {
    Cm248: 3.48e5, Cm247: 1.56e7, Cm246: 4706, Cm245: 8423,
    Am243: 7370, Am241: 432.6,
    Pu244: 8.0e7, Pu242: 3.75e5, Pu240: 6561, Pu239: 24110,
    Np237: 2.144e6,
    U238: 4.468e9, U236: 2.342e7, U235: 7.04e8, U234: 2.455e5, U233: 1.592e5,
    Pa231: 32760, Th232: 1.40e10, Th230: 7.54e4, Th229: 7880, Th228: 1.912,
    Ac227: 21.77, Ra228: 5.75, Ra226: 1600, Pb210: 22.2, Po210: 0.3789,
    C14: 5700, Cl36: 3.01e5, Ca41: 1.02e5, Ni59: 7.6e4, Ni63: 101.2, Se79: 3.27e5,
    Sr90: 28.79, Zr93: 1.61e6, Nb94: 2.03e4, Mo93: 4.0e3, Tc99: 2.111e5,
    Pd107: 6.5e6, Ag108m: 438, Sn126: 2.30e5, I129: 1.57e7, Cs135: 2.3e6,
    Cs137: 30.08, Sm151: 90, Ho166m: 1200,
  };

  const PRESETS = [
    { id: '4n2', label: 'Uranium series 4N+2: Cm246 → Pu242 → U238 → U234 → Th230 → Ra226 → Pb210', chain: ['Cm246', 'Pu242', 'U238', 'U234', 'Th230', 'Ra226', 'Pb210'] },
    { id: '4n1', label: 'Neptunium series 4N+1: Cm245 → Am241 → Np237 → U233 → Th229', chain: ['Cm245', 'Am241', 'Np237', 'U233', 'Th229'] },
    { id: '4n3', label: 'Actinium series 4N+3: Cm247 → Am243 → Pu239 → U235 → Pa231 → Ac227', chain: ['Cm247', 'Am243', 'Pu239', 'U235', 'Pa231', 'Ac227'] },
    { id: '4n0', label: 'Thorium series 4N: Cm248 → Pu244 → Pu240 → U236 → Th232 → Ra228 → Th228', chain: ['Cm248', 'Pu244', 'Pu240', 'U236', 'Th232', 'Ra228', 'Th228'] },
    { id: 'ra', label: 'Ra226 → Pb210 → Po210', chain: ['Ra226', 'Pb210', 'Po210'] },
    { id: 'fp', label: 'Fission and activation products (each alone)', singles: ['C14', 'Cl36', 'Ni59', 'Se79', 'Sr90', 'Nb94', 'Tc99', 'Pd107', 'Sn126', 'I129', 'Cs135', 'Cs137'] },
  ];

  /* Examples: made-up parameters. Each is a complete case. */
  const EXAMPLES = [
    {
      id: 'single', label: 'One weakly sorbing nuclide, constant release',
      casename: 'example1', diffusivity: 'SINGLE',
      params: { tw: 80, Pe: 10, aw: 800, awMode: 'aw', eps: 0.004, de: 2e-6, x0: 1, rho: 2700 },
      nuclides: [{ name: 'I129', thalf: 1.57e7, kd: 0, de: 2e-6, daughter: false, source: true }],
      series: { I129: [[0, 1e-3], [1e5, 1e-3]] },
    },
    {
      id: 'pulse', label: 'A sorbing nuclide, a 100-year pulse',
      casename: 'example2', diffusivity: 'SINGLE',
      params: { tw: 150, Pe: 10, aw: 1200, awMode: 'aw', eps: 0.003, de: 4e-6, x0: 2, rho: 2700 },
      nuclides: [{ name: 'Ni59', thalf: 7.6e4, kd: 0.02, de: 4e-6, daughter: false, source: true }],
      series: { Ni59: [[500, 0], [500, 2e-3], [600, 2e-3], [600, 0]] },
    },
    {
      id: 'radium', label: 'Ra226 → Pb210, element-specific diffusivity',
      casename: 'example3', diffusivity: 'ELEMENT_SPECIFIC',
      params: { tw: 40, Pe: 25, aw: 2000, awMode: 'aw', eps: 0.003, de: 3e-6, x0: 0.5, rho: 2700 },
      nuclides: [
        { name: 'Ra226', thalf: 1600, kd: 0.01, de: 3e-6, daughter: true, source: true },
        { name: 'Pb210', thalf: 22.2, kd: 0.1, de: 6e-6, daughter: false, source: false },
      ],
      series: { Ra226: [[0, 1e-4], [3e4, 1e-4], [3e4, 0]] },
    },
    {
      id: 'np', label: '4N+1 chain with in-growth, F-factor given',
      casename: 'example4', diffusivity: 'SINGLE',
      params: { tw: 100, Pe: 10, aw: 1000, F: 1e5, awMode: 'F', eps: 0.004, de: 3e-6, x0: 2, rho: 2700 },
      nuclides: [
        { name: 'Am241', thalf: 432.6, kd: 1.0, de: 3e-6, daughter: true, source: true },
        { name: 'Np237', thalf: 2.144e6, kd: 0.05, de: 3e-6, daughter: true, source: true },
        { name: 'U233', thalf: 1.592e5, kd: 0.1, de: 3e-6, daughter: true, source: false },
        { name: 'Th229', thalf: 7880, kd: 0.5, de: 3e-6, daughter: false, source: false },
      ],
      series: {
        Am241: [[0, 5e-3], [2e3, 2e-3], [2e4, 0]],
        Np237: [[0, 1e-4], [1e5, 1e-4], [1e6, 5e-5]],
      },
    },
    {
      id: 'fracture', label: 'Sorption on the fracture surfaces: Cs135 with Ka, beside a non-sorbing Cl36',
      casename: 'example6', diffusivity: 'SINGLE',
      params: { tw: 100, Pe: 10, aw: 500, awMode: 'aw', eps: 0.004, de: 3e-6, x0: 1, rho: 2700 },
      nuclides: [
        { name: 'Cs135', thalf: 2.3e6, kd: 0.01, ka: 0.004, de: 3e-6, daughter: false, source: true },
        { name: 'Cl36', thalf: 3.01e5, kd: 0, ka: 0, de: 3e-6, daughter: false, source: true },
      ],
      series: { Cs135: [[0, 1e-4], [5e4, 1e-4]], Cl36: [[0, 1e-4], [5e4, 1e-4]] },
    },
    {
      id: 'u', label: 'U238 → U234 → Th230 → Ra226: one element twice',
      casename: 'example5', diffusivity: 'SINGLE',
      params: { tw: 60, Pe: 10, aw: 1500, awMode: 'aw', eps: 0.004, de: 3e-6, x0: Infinity, rho: 2700 },
      nuclides: [
        { name: 'U238', thalf: 4.468e9, kd: 0.03, de: 3e-6, daughter: true, source: true },
        { name: 'U234', thalf: 2.455e5, kd: 0.03, de: 3e-6, daughter: true, source: true },
        { name: 'Th230', thalf: 7.54e4, kd: 0.3, de: 3e-6, daughter: true, source: false },
        { name: 'Ra226', thalf: 1600, kd: 0.01, de: 3e-6, daughter: false, source: false },
      ],
      series: { U238: [[0, 1e-3], [1e6, 1e-3]], U234: [[0, 2e-4], [1e6, 2e-4]] },
    },
  ];

  function halfLife(name) {
    const k = Object.keys(HALF_LIFE).find((n) => n.toLowerCase() === String(name).toLowerCase());
    return k ? HALF_LIFE[k] : null;
  }

  return { HALF_LIFE, PRESETS, EXAMPLES, halfLife };
}));
