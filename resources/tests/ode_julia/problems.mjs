/* ==========================================================================
   ode_julia / tests / problems

   The problems every solver in this package is checked against.

   Two kinds, and they answer different questions.

   A MANUFACTURED problem has an exact solution written down, so the error is
   known at every point rather than estimated. Running one at fixed steps and
   halving the step measures the *observed order of convergence*, which is the
   one test that actually proves a tableau was transcribed correctly: a single
   wrong digit in an eighth-order-accurate set of coefficients does not make
   the solver fail, it makes it quietly second order, and nothing else notices.

   The STIFF set is the standard one from Hairer and Wanner's second volume,
   the same problems every serious stiff solver is published against. They
   answer the other question: does the method survive a real stiff problem,
   with the step-size control and the Newton iteration doing their jobs.
   ========================================================================== */

/* --------------------------------------------------------------------------
   Manufactured: nonlinear, non-autonomous, with a known solution.

   Nonlinear so that the Jacobian matters; non-autonomous so that the df/dt
   term the Rosenbrock methods carry is exercised; and mildly stiff, so that
   the implicitness is doing something without the error being dominated by
   the stiffness.

       u₀' = −4·u₀·u₁ + g₀(t)
       u₁' =  u₀² − 6·u₁ + g₁(t)

   with g chosen so that  u(t) = [1 + ½sin t,  2 + 3/10·cos 2t]  solves it.

   `stiffness` scales the whole vector field. It matters for what the order
   test can honestly claim: the classical order of a method is a statement
   about the limit h·λ → 0, and every one-step method here loses order on a
   genuinely stiff problem -- that is order reduction, it is well documented,
   and Rodas5P is partly designed around it. Measured on this problem, Rodas5P
   shows a clean 5.00 at stiffness 0.01, about 4.9 and still climbing at 1, and
   between 3 and 4 at 100. So the order test runs the mild version, where a
   mistyped coefficient has nowhere to hide, and the stiff set below does the
   other job.
   -------------------------------------------------------------------------- */
export function manufacturedWith(stiffness) {
  const s = stiffness;
  return {
  name: `manufactured x${s}`,
  n: 2,
  u0: [1, 2.3],
  tspan: [0, 2],
  stiffness: s,
  exact(t, out = new Float64Array(2)) {
    out[0] = 1 + 0.5 * Math.sin(t);
    out[1] = 2 + 0.3 * Math.cos(2 * t);
    return out;
  },
  f(t, u, du) {
    const e0 = 1 + 0.5 * Math.sin(t);
    const e1 = 2 + 0.3 * Math.cos(2 * t);
    const de0 = 0.5 * Math.cos(t);
    const de1 = -0.6 * Math.sin(2 * t);
    const g0 = de0 + s * 4 * e0 * e1;
    const g1 = de1 - s * e0 * e0 + s * 6 * e1;
    du[0] = -s * 4 * u[0] * u[1] + g0;
    du[1] = s * u[0] * u[0] - s * 6 * u[1] + g1;
  },
  jac(t, u, J) {
    J.set(0, 0, -s * 4 * u[1]);
    J.set(0, 1, -s * 4 * u[0]);
    J.set(1, 0, s * 2 * u[0]);
    J.set(1, 1, -s * 6);
  },
  // df/dt at fixed u. Only the forcing depends on t, so this is g'(t).
  tgrad(t, u, dT) {
    const e0 = 1 + 0.5 * Math.sin(t);
    const e1 = 2 + 0.3 * Math.cos(2 * t);
    const de0 = 0.5 * Math.cos(t);
    const de1 = -0.6 * Math.sin(2 * t);
    dT[0] = -0.5 * Math.sin(t) + s * 4 * (de0 * e1 + e0 * de1);
    dT[1] = -1.2 * Math.cos(2 * t) - s * 2 * e0 * de0 + s * 6 * de1;
  },
  };
}

/** Mild enough that classical order is what is measured. */
export const manufactured = manufacturedWith(0.01);
/** Stiff enough to need an implicit method, with the answer still known. */
export const manufacturedStiff = manufacturedWith(100);

/* --------------------------------------------------------------------------
   Robertson (ROBER). Three species, an autocatalytic step, and time constants
   nine orders apart. y₂ peaks near 3.6e-5 and then decays, so it is also a
   test of whether the absolute tolerance is being applied sensibly.

     Hairer & Wanner II, IV.10; originally Robertson (1966).
   -------------------------------------------------------------------------- */
export const rober = {
  name: 'rober',
  n: 3,
  u0: [1, 0, 0],
  tspan: [0, 1e5],
  f(t, y, du) {
    const r1 = 0.04 * y[0];
    const r2 = 1e4 * y[1] * y[2];
    const r3 = 3e7 * y[1] * y[1];
    du[0] = -r1 + r2;
    du[1] = r1 - r2 - r3;
    du[2] = r3;
  },
  jac(t, y, J) {
    J.set(0, 0, -0.04); J.set(0, 1, 1e4 * y[2]); J.set(0, 2, 1e4 * y[1]);
    J.set(1, 0, 0.04); J.set(1, 1, -1e4 * y[2] - 6e7 * y[1]); J.set(1, 2, -1e4 * y[1]);
    J.set(2, 0, 0); J.set(2, 1, 6e7 * y[1]); J.set(2, 2, 0);
  },
};

/* --------------------------------------------------------------------------
   Van der Pol at μ = 1e6, in the standard non-stiff-variable form. The limit
   cycle has corners that a solver has to cut its step by six orders to get
   round, which is exactly what the step controller is for.
   -------------------------------------------------------------------------- */
export function vanderpol(mu = 1e6) {
  return {
    name: `vanderpol mu=${mu}`,
    n: 2,
    u0: [2, 0],
    tspan: [0, 2],
    mu,
    f(t, y, du) {
      du[0] = y[1];
      du[1] = mu * ((1 - y[0] * y[0]) * y[1] - y[0]);
    },
    jac(t, y, J) {
      J.set(0, 0, 0); J.set(0, 1, 1);
      J.set(1, 0, mu * (-2 * y[0] * y[1] - 1));
      J.set(1, 1, mu * (1 - y[0] * y[0]));
    },
  };
}

/* --------------------------------------------------------------------------
   HIRES: eight equations, "High Irradiance RESponse" of plant photomorphogenesis.
   Hairer & Wanner II, IV.10, problem (7.1).
   -------------------------------------------------------------------------- */
export const hires = {
  name: 'hires',
  n: 8,
  u0: [1, 0, 0, 0, 0, 0, 0, 0.0057],
  tspan: [0, 321.8122],
  f(t, y, du) {
    du[0] = -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007;
    du[1] = 1.71 * y[0] - 8.75 * y[1];
    du[2] = -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4];
    du[3] = 8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3];
    du[4] = -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6];
    du[5] = -280 * y[5] * y[7] + 0.69 * y[3] + 1.71 * y[4] - 0.43 * y[5] + 0.69 * y[6];
    du[6] = 280 * y[5] * y[7] - 1.81 * y[6];
    du[7] = -280 * y[5] * y[7] + 1.81 * y[6];
  },
};

/* --------------------------------------------------------------------------
   OREGO, the Oregonator: an oscillating reaction whose amplitude spans five
   decades, so a solver that loses the small values loses the oscillation.
   Hairer & Wanner II, IV.10, problem (7.2).
   -------------------------------------------------------------------------- */
export const orego = {
  name: 'orego',
  n: 3,
  u0: [1, 2, 3],
  tspan: [0, 360],
  f(t, y, du) {
    const s = 77.27;
    const w = 0.161;
    const q = 8.375e-6;
    du[0] = s * (y[1] + y[0] * (1 - q * y[0] - y[1]));
    du[1] = (y[2] - (1 + y[0]) * y[1]) / s;
    du[2] = w * (y[0] - y[2]);
  },
};

/* --------------------------------------------------------------------------
   E5: four equations, and the reason atol has to be taken seriously. The
   components fall to 1e-30 and below, and a solver using a relative measure
   alone chases them for ever.
   Hairer & Wanner II, IV.10, problem (7.3).
   -------------------------------------------------------------------------- */
export const e5 = {
  name: 'e5',
  n: 4,
  u0: [1.76e-3, 0, 0, 0],
  tspan: [0, 1e13],
  f(t, y, du) {
    const A = 7.89e-10;
    const B = 1.1e7;
    const C = 1.13e9;
    const M = 1e6;
    const prod1 = A * y[0];
    const prod2 = B * y[0] * y[2];
    const prod3 = C * y[2] * y[3];
    const prod4 = M * C * y[1] * y[2];
    du[0] = -prod1 - prod2;
    du[1] = prod1 - prod4;
    du[2] = prod1 - prod2 + prod3 - prod4;
    du[3] = prod2 - prod3;
  },
};

/* --------------------------------------------------------------------------
   Pollution: twenty equations, twenty-five reactions, an air-pollution model.
   The one problem here big enough for the sparse path to be worth taking.
   Hairer & Wanner II, IV.10, problem (7.4); Verwer (1994).
   -------------------------------------------------------------------------- */
const POLLU_K = [
  0.35, 0.266e2, 0.123e5, 0.86e-3, 0.82e-3, 0.15e5, 0.13e-3, 0.24e5, 0.165e5, 0.9e4,
  0.22e-1, 0.12e5, 0.188e1, 0.163e5, 0.48e7, 0.35e-3, 0.175e-1, 0.1e9, 0.444e12, 0.124e4,
  0.21e1, 0.578e1, 0.474e-1, 0.178e4, 0.312e1,
];

export const pollution = {
  name: 'pollution',
  n: 20,
  u0: (() => {
    const y = new Float64Array(20);
    y[1] = 0.2; y[3] = 0.04; y[6] = 0.1; y[7] = 0.3; y[8] = 0.01;
    y[16] = 0.007;
    return Array.from(y);
  })(),
  tspan: [0, 60],
  f(t, y, du) {
    const k = POLLU_K;
    const r = new Array(25);
    r[0] = k[0] * y[0];
    r[1] = k[1] * y[1] * y[3];
    r[2] = k[2] * y[4] * y[1];
    r[3] = k[3] * y[6];
    r[4] = k[4] * y[6];
    r[5] = k[5] * y[6] * y[5];
    r[6] = k[6] * y[8];
    r[7] = k[7] * y[8] * y[5];
    r[8] = k[8] * y[10] * y[1];
    r[9] = k[9] * y[10] * y[0];
    r[10] = k[10] * y[12];
    r[11] = k[11] * y[9] * y[1];
    r[12] = k[12] * y[13];
    r[13] = k[13] * y[0] * y[5];
    r[14] = k[14] * y[2];
    r[15] = k[15] * y[3];
    r[16] = k[16] * y[3];
    r[17] = k[17] * y[15];
    r[18] = k[18] * y[15];
    r[19] = k[19] * y[16] * y[5];
    r[20] = k[20] * y[18];
    r[21] = k[21] * y[18];
    r[22] = k[22] * y[0] * y[3];
    r[23] = k[23] * y[18] * y[0];
    r[24] = k[24] * y[19];
    du[0] = -r[0] - r[9] - r[13] - r[22] - r[23] + r[1] + r[2] + r[8] + r[10] + r[11]
      + r[21] + r[24];
    du[1] = -r[1] - r[2] - r[8] - r[11] + r[0] + r[20];
    du[2] = -r[14] + r[0] + r[16] + r[18] + r[21];
    du[3] = -r[1] - r[15] - r[16] - r[22] + r[14];
    du[4] = -r[2] + 2 * r[3] + r[5] + r[6] + r[12] + r[19];
    du[5] = -r[5] - r[7] - r[13] - r[19] + r[2] + 2 * r[17];
    du[6] = -r[3] - r[4] - r[5] + r[12];
    du[7] = r[3] + r[4] + r[5] + r[6];
    du[8] = -r[6] - r[7];
    du[9] = -r[11] + r[6] + r[8];
    du[10] = -r[8] - r[9] + r[7] + r[10];
    du[11] = r[8];
    du[12] = -r[10] + r[9];
    du[13] = -r[12] + r[11];
    du[14] = r[13];
    du[15] = -r[17] - r[18] + r[15];
    du[16] = -r[19];
    du[17] = r[19];
    du[18] = -r[20] - r[21] - r[23] + r[16] + r[24];
    du[19] = -r[24] + r[23];
  },
};

export const stiffProblems = [rober, hires, orego, pollution];
