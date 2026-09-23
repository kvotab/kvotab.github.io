/* ==========================================================================
   ode_julia / solvers / radau-tableau

   GENERATED -- do not edit by hand.
   Written by scripts/gen-radau-tableau.py from RadauIIA5Tableau in
   OrdinaryDiffEqFIRK/src/firk_tableaus.jl.

   The three-stage Radau IIA collocation method, order 5, L-stable, stiffly
   accurate. Hairer & Wanner, Solving ODEs II, section IV.8.

   T and TI are the change of basis that diagonalises the inverse of the
   Butcher matrix; gamma is its real eigenvalue and alpha +/- i*beta the
   complex pair. T32 = 1 and T33 = 0 by Hairer's normalisation and are not
   stored -- the step writes them in. c3 = 1, which is what makes the method
   stiffly accurate. e1, e2, e3 weight the stages in the error estimate.
   ========================================================================== */

export const RadauIIA5Tableau = {
  name: 'RadauIIA5',
  stages: 3,
  order: 5,
  errorOrder: 3,
  T11: 9.1232394870892942792e-2,
  T12: -0.14125529502095420843e0,
  T13: -3.0029194105147424492e-2,
  T21: 0.24171793270710701896e0,
  T22: 0.20412935229379993199e0,
  T23: 0.38294211275726193779e0,
  T31: 0.96604818261509293619e0,
  TI11: 4.325579890063155351e0,
  TI12: 0.33919925181580986954e0,
  TI13: 0.54177053993587487119e0,
  TI21: -4.1787185915519047273e0,
  TI22: -0.32768282076106238708e0,
  TI23: 0.47662355450055045196e0,
  TI31: -0.50287263494578687595e0,
  TI32: 2.5719269498556054292e0,
  TI33: -0.59603920482822492497e0,
  c1: 0.15505102572168222,
  c2: 0.6449489742783178,
  c3: 1,
  gamma: 3.6378342527444962,
  alpha: 2.6810828736277523,
  beta: 3.0504301992474105,
  e1: -10.048809399827414,
  e2: 1.382142733160748,
  e3: -0.3333333333333333,
};
