/* ==========================================================================
   ode_julia / solvers / esdirk-tableaus

   GENERATED -- do not edit by hand.
   Written by scripts/gen-esdirk-tableaus.py from a checked transcription of
   OrdinaryDiffEqSDIRK's TRBDF2Tableau (sdirk_tableaus.jl) and
   KenCarp4ESDIRKIMEXTableau (imex_tableaus.jl, the one the solver actually
   uses -- a second, unreferenced KenCarp4Tableau exists in sdirk_tableaus.jl
   and differs in one Newton-seed coefficient).

   Both are ESDIRK: the first stage is explicit (a[0][0] = 0), every later
   stage has the same diagonal gamma, and both are stiffly accurate, so the
   solution is the last stage value and f at the end of the step comes free.

   `a` is the full lower triangle INCLUDING the diagonal. `alpha` holds the
   weights that seed each stage's Newton iterate from the stages already
   solved; they cost nothing and save an iteration or two per stage.

   TRBDF2: 2nd order, 3 stages. A trapezoidal half-step followed by a BDF2
     half-step, so that both halves reuse one factorisation.
     Hosea & Shampine (1996), Applied Numerical Mathematics 20, 21-37.

   KenCarp4: 4th order, 6 stages. The implicit half of the additive
     ARK4(3)6L[2]SA pair; used here on its own.
     Kennedy & Carpenter (2003), Applied Numerical Mathematics 44, 139-181.

   The generator checks, and refuses to write, unless every row of `a` sums to
   its `c`, `b` sums to 1, `btilde` sums to 0 and the diagonal is constant.
   ========================================================================== */

export const TRBDF2Tableau = {
  name: 'TRBDF2',
  stages: 3,
  order: 2,
  errorOrder: 2,
  gamma: 0.2928932188134524,
  a: [
    [0.0, 0.0, 0.0],
    [0.2928932188134524, 0.2928932188134524, 0.0],
    [0.3535533905932738, 0.3535533905932738, 0.2928932188134524],
  ],
  b: [0.3535533905932738, 0.3535533905932738, 0.2928932188134524],
  btilde: [-0.1380711874576984, 0.3333333333333333, -0.19526214587563495],
  c: [0.0, 0.5857864376269049, 1.0],
  alpha: [
    [],
    [1.0],
    [-0.7071067811865476, 1.7071067811865475],
  ],
  stifflyAccurate: true,
};

export const KenCarp4Tableau = {
  name: 'KenCarp4',
  stages: 6,
  order: 4,
  errorOrder: 3,
  gamma: 0.25,
  a: [
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [0.25, 0.25, 0.0, 0.0, 0.0, 0.0],
    [0.137776, -0.055776, 0.25, 0.0, 0.0, 0.0],
    [0.14463686602698217, -0.22393190761334475, 0.4492950415863626, 0.25, 0.0, 0.0],
    [0.09825878328356477, -0.5915442428196704, 0.8101210538282996, 0.283164405707806, 0.25, 0.0],
    [0.15791629516167136, 0.0, 0.18675894052400077, 0.6805652953093346, -0.27524053099500667, 0.25],
  ],
  b: [0.15791629516167136, 0.0, 0.18675894052400077, 0.6805652953093346, -0.27524053099500667, 0.25],
  btilde: [-0.0032044943984591762, 0.0, 0.0024462511366794577, 0.02148007591958727, -0.043946868068572426, 0.02322503541076487],
  c: [0.0, 0.5, 0.332, 0.62, 0.85, 1.0],
  alpha: [
    [],
    [1.0],
    [0.336, 0.664],
    [-0.24, 1.24, 0.0],
    [0.442914622496517, 1.1021454786279974, -2.211335150636112, 1.6662750495115974],
    [0.3023685651044848, 0.866907907246413, -1.1872321570453404, -0.4149773501111751, 1.4329330348056177],
  ],
  stifflyAccurate: true,
};
