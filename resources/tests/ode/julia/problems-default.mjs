/* ==========================================================================
   ode_julia / tests / problems-default

   The problems the automatic algorithm is compared with OrdinaryDiffEq on.
   scripts/gen-ode-default-ref.jl writes the same problems out in Julia --
   every equation, parameter and starting state here has its twin there, and
   the two files are to be changed together -- and runs DifferentialEquations
   .jl on them for ref/default.json.

   Every problem has its exact Jacobian, on both sides. Without one Julia
   differences J with a step of √eps·max(|u|, 1), which on Robertson is
   larger than y₂ itself: its Rodas5P then needs 2308 steps at reltol 1e-8
   where with the exact J it needs 270, and a comparison would be of two
   Jacobians, not of two integrators.

   A mix chosen to steer the switch every way it can go: non-stiff throughout
   (Kepler), stiff from the start and small (Robertson, HIRES, the
   Oregonator), stiff with non-stiff stretches (van der Pol at μ = 1000),
   and stiff and large enough for FBDF (51 to 500 states) and for the Krylov
   FBDF (over 500): diffusion, and a chain of decays whose rates span eight
   decades -- the shape of a compartment model.
   ========================================================================== */

/** J(i, j) = v into whichever storage the integrator hands over: dense, or CSC through the pattern. */
function put(J, i, j, v) {
  if (!J.values) { J.set(i, j, v); return; }
  for (let k = J.colPtr[j]; k < J.colPtr[j + 1]; k++) {
    if (J.rowIdx[k] === i) { J.values[k] = v; return; }
  }
  if (v !== 0) throw new Error(`J(${i}, ${j}) is outside the pattern`);
}

export const rober = {
  name: 'rober', n: 3, u0: [1, 0, 0], tspan: [0, 1e5],
  f(t, y, du) {
    du[0] = -0.04 * y[0] + 1e4 * y[1] * y[2];
    du[1] = 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1];
    du[2] = 3e7 * y[1] * y[1];
  },
  jac(t, y, J) {
    put(J, 0, 0, -0.04); put(J, 0, 1, 1e4 * y[2]); put(J, 0, 2, 1e4 * y[1]);
    put(J, 1, 0, 0.04); put(J, 1, 1, -1e4 * y[2] - 6e7 * y[1]); put(J, 1, 2, -1e4 * y[1]);
    put(J, 2, 0, 0); put(J, 2, 1, 6e7 * y[1]); put(J, 2, 2, 0);
  },
};

export const vdp1000 = {
  name: 'vdp1000', n: 2, u0: [2, 0], tspan: [0, 3000],
  f(t, y, du) {
    du[0] = y[1];
    du[1] = 1000 * ((1 - y[0] * y[0]) * y[1]) - y[0];
  },
  jac(t, y, J) {
    put(J, 0, 0, 0); put(J, 0, 1, 1);
    put(J, 1, 0, -2000 * y[0] * y[1] - 1); put(J, 1, 1, 1000 * (1 - y[0] * y[0]));
  },
};

export const hires = {
  name: 'hires', n: 8, u0: [1, 0, 0, 0, 0, 0, 0, 0.0057], tspan: [0, 321.8122],
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
  jac(t, y, J) {
    for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) put(J, i, j, 0);
    put(J, 0, 0, -1.71); put(J, 0, 1, 0.43); put(J, 0, 2, 8.32);
    put(J, 1, 0, 1.71); put(J, 1, 1, -8.75);
    put(J, 2, 2, -10.03); put(J, 2, 3, 0.43); put(J, 2, 4, 0.035);
    put(J, 3, 1, 8.32); put(J, 3, 2, 1.71); put(J, 3, 3, -1.12);
    put(J, 4, 4, -1.745); put(J, 4, 5, 0.43); put(J, 4, 6, 0.43);
    put(J, 5, 3, 0.69); put(J, 5, 4, 1.71); put(J, 5, 5, -280 * y[7] - 0.43);
    put(J, 5, 6, 0.69); put(J, 5, 7, -280 * y[5]);
    put(J, 6, 5, 280 * y[7]); put(J, 6, 6, -1.81); put(J, 6, 7, 280 * y[5]);
    put(J, 7, 5, -280 * y[7]); put(J, 7, 6, 1.81); put(J, 7, 7, -280 * y[5]);
  },
};

const OS = 77.27;
const OW = 0.161;
const OQ = 8.375e-6;
export const orego = {
  name: 'orego', n: 3, u0: [1, 2, 3], tspan: [0, 360],
  f(t, y, du) {
    du[0] = OS * (y[1] + y[0] * (1 - OQ * y[0] - y[1]));
    du[1] = (y[2] - (1 + y[0]) * y[1]) / OS;
    du[2] = OW * (y[0] - y[2]);
  },
  jac(t, y, J) {
    put(J, 0, 0, OS * (1 - 2 * OQ * y[0] - y[1])); put(J, 0, 1, OS * (1 - y[0])); put(J, 0, 2, 0);
    put(J, 1, 0, -y[1] / OS); put(J, 1, 1, -(1 + y[0]) / OS); put(J, 1, 2, 1 / OS);
    put(J, 2, 0, OW); put(J, 2, 1, 0); put(J, 2, 2, -OW);
  },
};

const KEPLER_E = 0.6;
export const kepler = {
  name: 'kepler', n: 4,
  u0: [1 - KEPLER_E, 0, 0, Math.sqrt((1 + KEPLER_E) / (1 - KEPLER_E))],
  tspan: [0, 20],
  f(t, y, du) {
    const r2 = y[0] * y[0] + y[1] * y[1];
    const r3 = r2 * Math.sqrt(r2);
    du[0] = y[2];
    du[1] = y[3];
    du[2] = -y[0] / r3;
    du[3] = -y[1] / r3;
  },
  jac(t, y, J) {
    const r2 = y[0] * y[0] + y[1] * y[1];
    const r = Math.sqrt(r2);
    const r3 = r2 * r;
    const r5 = r3 * r2;
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) put(J, i, j, 0);
    put(J, 0, 2, 1); put(J, 1, 3, 1);
    put(J, 2, 0, -1 / r3 + 3 * y[0] * y[0] / r5); put(J, 2, 1, 3 * y[0] * y[1] / r5);
    put(J, 3, 0, 3 * y[0] * y[1] / r5); put(J, 3, 1, -1 / r3 + 3 * y[1] * y[1] / r5);
  },
};

/** 1-D diffusion on n interior points, zero at both ends: linear, stiff, every state moving. */
export function heat(n) {
  const dx = 1 / (n + 1);
  const c = 1 / (dx * dx);
  const u0 = Array.from({ length: n }, (_, j) => {
    const x = (j + 1) * dx;
    return Math.sin(Math.PI * x) + 0.5 * Math.sin(3 * Math.PI * x);
  });
  const colPtr = new Int32Array(n + 1);
  const rows = [];
  for (let j = 0; j < n; j++) {
    if (j > 0) rows.push(j - 1);
    rows.push(j);
    if (j < n - 1) rows.push(j + 1);
    colPtr[j + 1] = rows.length;
  }
  return {
    name: `heat${n}`, n, u0, tspan: [0, 0.1],
    jacPattern: { colPtr, rowIdx: Int32Array.from(rows) },
    f(t, u, du) {
      for (let i = 0; i < n; i++) {
        const l = i > 0 ? u[i - 1] : 0;
        const r = i < n - 1 ? u[i + 1] : 0;
        du[i] = (l - 2 * u[i] + r) / (dx * dx);
      }
    },
    jac(t, u, J) {
      for (let i = 0; i < n; i++) {
        if (i > 0) put(J, i, i - 1, c);
        put(J, i, i, -2 * c);
        if (i < n - 1) put(J, i, i + 1, c);
      }
    },
  };
}

/**
 * A chain of n compartments, one unit in the first, rates from 1e4 down to
 * 1e-4: what a compartment model is, stripped down. The states down the
 * chain start empty and are reached one after another.
 */
export function chain(n) {
  const k = Array.from({ length: n }, (_, i) => 10 ** (4 - 8 * i / (n - 1)));
  const colPtr = new Int32Array(n + 1);
  const rows = [];
  for (let j = 0; j < n; j++) {
    rows.push(j);
    if (j < n - 1) rows.push(j + 1);
    colPtr[j + 1] = rows.length;
  }
  return {
    name: `chain${n}`, n, u0: Array.from({ length: n }, (_, i) => (i === 0 ? 1 : 0)), tspan: [0, 100],
    jacPattern: { colPtr, rowIdx: Int32Array.from(rows) },
    f(t, u, du) {
      du[0] = -k[0] * u[0];
      for (let i = 1; i < n; i++) du[i] = k[i - 1] * u[i - 1] - k[i] * u[i];
    },
    jac(t, u, J) {
      for (let i = 0; i < n; i++) {
        put(J, i, i, -k[i]);
        if (i > 0) put(J, i, i - 1, k[i - 1]);
      }
    },
  };
}

/**
 * The comparisons: a problem, a method as Julia names it, and tolerances
 * (1e-3 and 1e-6 unless given). `exact` marks those on which OrdinaryDiffEq
 * and this package take the same steps -- the same number accepted and
 * rejected, and for the default algorithm the same method for every one --
 * which the test holds them to. Measured 2026-10-03 against OrdinaryDiffEq
 * 7.8.1: fifteen of the twenty-two.
 */
export const COMPARISONS = [
  { p: kepler, alg: 'Tsit5', exact: true },
  { p: kepler, alg: 'Vern7', reltol: 1e-8, abstol: 1e-10, exact: true },
  { p: kepler, alg: 'DefaultODEAlgorithm', exact: true },
  { p: kepler, alg: 'DefaultODEAlgorithm', reltol: 1e-8, abstol: 1e-10, exact: true },
  { p: rober, alg: 'Rosenbrock23', exact: true },
  { p: rober, alg: 'DefaultODEAlgorithm', exact: true },
  { p: rober, alg: 'DefaultODEAlgorithm', reltol: 1e-8, abstol: 1e-10, exact: true },
  { p: vdp1000, alg: 'DefaultODEAlgorithm', exact: true },
  { p: hires, alg: 'Rosenbrock23', exact: true },
  { p: hires, alg: 'DefaultODEAlgorithm', exact: true },
  { p: hires, alg: 'DefaultODEAlgorithm', reltol: 1e-8, abstol: 1e-10, exact: true },
  { p: orego, alg: 'DefaultODEAlgorithm', exact: true },
  { p: heat(30), alg: 'DefaultODEAlgorithm', exact: true },
  // The FBDF runs. OrdinaryDiffEq's composite never rejects an FBDF step
  // (see the test's header), and the port's FBDF predicts its first step
  // after a switch by an Euler step where OrdinaryDiffEq's predicts no
  // change: at 1e-3 that is two steps more here; at 1e-6, where
  // OrdinaryDiffEq's predictor would be rejected over and over, it is what
  // keeps the switch from going back and forth thousands of times.
  { p: heat(200), alg: 'DefaultODEAlgorithm' },
  { p: heat(700), alg: 'DefaultODEAlgorithm' },
  { p: heat(200), alg: 'DefaultODEAlgorithm', reltol: 1e-6, abstol: 1e-9 },
  { p: heat(600), alg: 'DefaultODEAlgorithm', reltol: 1e-6, abstol: 1e-9 },
  { p: chain(40), alg: 'DefaultODEAlgorithm', exact: true },
  { p: chain(40), alg: 'DefaultODEAlgorithm', reltol: 1e-6, abstol: 1e-9, exact: true },
  // On the chains of 120 and 800 Julia's FBDF also rides through steps the
  // port rejects, and stays stiff on its explicit method's stale estimate.
  { p: chain(120), alg: 'DefaultODEAlgorithm' },
  { p: chain(120), alg: 'DefaultODEAlgorithm', reltol: 1e-6, abstol: 1e-9 },
  { p: chain(800), alg: 'DefaultODEAlgorithm' },
];
