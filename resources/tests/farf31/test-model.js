#!/usr/bin/env node
/* ==========================================================================
   THE FARF31 MODEL, AGAINST WHAT IT IS SUPPOSED TO REPRODUCE

   1. Closed forms: the inverse Gaussian of advection and dispersion without
      matrix interaction; the classical solution for diffusion into an
      infinite matrix under plug flow (and a very high Peclet number close to
      it); an infinite matrix at finite Pe by the subordination integral; the
      Bateman solution for chains whose members move alike (distinct, close
      and equal half-lives); the transmission T(0) and the mass balance. With
      sorption on the fracture surfaces (Rf = 1 + Ka aw): without a matrix
      h(t/Rf)/Rf e^(-lambda t); under plug flow the classical solution delayed
      by Rf tw; chains with one Rf, R and De, Bateman; the mass balance.
   2. The chain solution against TR 90-01's recursion (Appendix C,
      Proposition 3), written out independently here, with and without the
      fracture term.
   3. Made-up cases against ref/mpmath-ref.json, a 40-digit implementation of
      that recursion with mpmath's own inversion (gen-mpmath-ref.py): the
      four reference cases at the times of the original program's out.ts and
      out.response, a chain with fracture sorption, and nine tubes with a
      sharp front and a long slow tail (Pe 30 to 300, matrices that hold 0.1
      to 10 times the water) at times of their own; each response's integral
      against T(0), and the run's own mass balance.
      Then the real axis next to a singularity, the mass balance caught
      failing, and four sharp-front cases (Pe 1000 to 10 000) against de
      Hoog's method.
   4. With the reference cases present ($FARF31_REF, default
      ~/Downloads/Farf31-SKB-new/reference-cases): the page reproduces the
      original program's outputs for these made-up cases, its unit responses
      near their peaks and the releases of chain-dense, pulse-nozero and
      elem-ramp.
   5. The files: FARF31's input read, written and read back; the page's own
      KA_XX; out.ts and out.response in the original's layout.

       node resources/tests/farf31/test-model.js [--verbose]

   Exit status is 0 when every check passes.
   ========================================================================== */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
const M = require(path.join(jsDir, 'farf31-model.js'));
const IO = require(path.join(jsDir, 'farf31-io.js'));
const DATA = require(path.join(jsDir, 'farf31-data.js'));

const verbose = process.argv.includes('--verbose');
let checks = 0;
const failures = [];

function check(label, ok, detail) {
  checks++;
  const good = ok === true;
  if (!good || verbose) console.log(`${good ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!good) failures.push(label);
}
function below(label, err, tol) {
  check(label, err <= tol, `${err.toExponential(2)} (allowed ${tol.toExponential(0)})`);
}
const LN2 = Math.LN2;
const logGrid = (a, b, n) => Array.from({ length: n }, (_, k) => a * Math.pow(b / a, k / (n - 1)));

/** Largest relative error over the points where the exact value exceeds
    frac of its largest. */
function worstRel(ts, got, want, frac = 1e-6) {
  let pk = 0;
  for (const v of want) pk = Math.max(pk, Math.abs(v));
  let w = 0;
  ts.forEach((t, k) => { if (Math.abs(want[k]) > frac * pk) w = Math.max(w, Math.abs(got[k] - want[k]) / Math.abs(want[k])); });
  return w;
}

function oneNuclide(p, n) {
  const ctx = M.prepare(Object.assign({ eps: 0.005, rho: 2700 }, p, { nuclides: [Object.assign({ name: 'X', daughter: false }, n)] }));
  const ws = M.makeWorkspace(ctx);
  return { ctx, ws, ax: M.realAxis(ctx, ws, 0, 0, 1e-3, 1e12) };
}

const ig = (t, tw, Pe) => Math.sqrt(Pe * tw / (4 * Math.PI * t ** 3)) * Math.exp(-Pe * (tw - t) ** 2 / (4 * tw * t));
const neret = (u, k) => (u > 0 ? k / (2 * Math.sqrt(Math.PI) * u ** 1.5) * Math.exp(-k * k / (4 * u)) : 0);

/** Adaptive Gauss-Kronrod (7-15) on [a, b]. */
function quad(f, a, b, tol = 1e-12, depth = 0) {
  const xk = [0.991455371120813, 0.949107912342759, 0.864864423359769, 0.741531185599394, 0.586087235467691, 0.405845151377397, 0.207784955007898, 0];
  const wk = [0.022935322010529, 0.063092092629979, 0.104790010322250, 0.140653259715525, 0.169004726639267, 0.190350578064785, 0.204432940075298, 0.209482141084728];
  const wg = [0, 0.129484966168870, 0, 0.279705391489277, 0, 0.381830050505119, 0, 0.417959183673469];
  const c = 0.5 * (a + b), h = 0.5 * (b - a);
  let K = 0, G = 0;
  for (let q = 0; q < 8; q++) {
    const vals = q === 7 ? [f(c)] : [f(c - h * xk[q]), f(c + h * xk[q])];
    const s = vals.reduce((x, y) => x + y, 0);
    K += wk[q] * s; G += wg[q] * s;
  }
  K *= h; G *= h;
  if (Math.abs(K - G) <= tol * Math.abs(K) + 1e-300 || depth > 40) return K;
  return quad(f, a, c, tol, depth + 1) + quad(f, c, b, tol, depth + 1);
}

/** Bateman coefficient of the last member from the first, by a scaled matrix
    exponential (fine for equal decay constants). */
function bateman(lams, t) {
  const n = lams.length;
  const A = Array.from({ length: n }, (_, p) => Array.from({ length: n }, (__, q) => (p === q ? -lams[p] * t : p === q + 1 ? lams[q] * t : 0)));
  let nrm = 0;
  for (let p = 0; p < n; p++) nrm = Math.max(nrm, Math.abs(A[p][p]) + (p ? A[p][p - 1] : 0));
  const sq = Math.max(0, Math.ceil(Math.log2(nrm + 1e-300)) + 4);
  const B = A.map((r) => r.map((v) => v * Math.pow(2, -sq)));
  const mul = (X, Y) => X.map((r, p) => r.map((_, q) => { let s = 0; for (let k = 0; k < n; k++) s += X[p][k] * Y[k][q]; return s; }));
  let E = B.map((r, p) => r.map((_, q) => (p === q ? 1 : 0))), term = E.map((r) => r.slice());
  for (let k = 1; k < 30; k++) { term = mul(term, B).map((r) => r.map((v) => v / k)); E = E.map((r, p) => r.map((v, q) => v + term[p][q])); }
  for (let k = 0; k < sq; k++) E = mul(E, E);
  return E[n - 1][0];
}

/* ======================================================================
   1a. No matrix interaction: the inverse Gaussian (flux in, flux out)
   ====================================================================== */
console.log('\n--- no matrix: advection and dispersion ---');
for (const Pe of [0.5, 2, 10, 50, 300, 3000, 1e5]) {
  const tw = 100, th = 1e4, lam = LN2 / th;
  const { ctx, ws, ax } = oneNuclide({ tw, Pe, aw: 0, x0: 1 }, { thalf: th, kd: 0, de: 1e-5 });
  const ts = logGrid(tw / 30, tw * 30, 121);
  const want = ts.map((t) => Math.exp(-lam * t) * ig(t, tw, Pe));
  const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
  below(`inverse Gaussian, Pe = ${Pe}`, worstRel(ts, got, want, 1e-10), 1e-9);
  if (Pe <= 50) {
    const tal = ts.map((t) => M.invertTalbot(ctx, ws, ax, t).h);
    below(`  and Talbot's fixed contour, Pe = ${Pe}`, worstRel(ts, tal, want, 1e-6), 3e-6);
  }
  if (Pe <= 300) {
    const dh = ts.map((t) => M.invertDeHoog(ctx, ws, 0, 0, t));
    below(`  and de Hoog's method, Pe = ${Pe}`, worstRel(ts, dh, want, 1e-6), 1e-5);
  }
  const T0 = M.transferAtZero(ctx, ws, 0, 0);
  // exp(Pe/2 (1 - sqrt(1 + 4 tw lambda/Pe))), written without the cancellation
  below(`  T(0) = exp(Pe/2 (1 - sqrt(1 + 4 tw lambda/Pe))), Pe = ${Pe}`, Math.abs(T0 / Math.exp(-2 * tw * lam / (1 + Math.sqrt(1 + 4 * tw * lam / Pe))) - 1), 1e-14);
}
for (const [Pe, ka, aw] of [[10, 0.01, 500], [2, 1e-3, 2000], [300, 0.05, 100]]) {
  // sorption on the fracture surfaces, no matrix: T(s) = H(Rf (s + lambda)), h(t/Rf)/Rf e^(-lambda t)
  const tw = 100, th = 1e4, lam = LN2 / th, Rf = 1 + ka * aw;
  const { ctx, ws, ax } = oneNuclide({ tw, Pe, aw, x0: 1 }, { thalf: th, kd: 0, ka, de: 0 });
  const ts = logGrid(tw * Rf / 30, tw * Rf * 30, 121);
  const want = ts.map((t) => Math.exp(-lam * t) * ig(t / Rf, tw, Pe) / Rf);
  const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
  below(`fracture sorption, no matrix, Rf = ${Rf}, Pe = ${Pe}`, worstRel(ts, got, want, 1e-10), 1e-9);
  const T0 = M.transferAtZero(ctx, ws, 0, 0);
  below(`  T(0) with Rf = ${Rf}`, Math.abs(T0 / Math.exp(-2 * tw * Rf * lam / (1 + Math.sqrt(1 + 4 * tw * Rf * lam / Pe))) - 1), 1e-14);
}
{
  // the derivatives the Hermite interpolation uses
  const tw = 100, Pe = 10;
  const { ctx, ws, ax } = oneNuclide({ tw, Pe, aw: 0, x0: 1 }, { thalf: Infinity, kd: 0, de: 1e-5 });
  let w1 = 0, w2 = 0;
  for (const t of logGrid(20, 800, 40)) {
    const r = M.invertParabola(ctx, ws, ax, t);
    // d ln IG/dt = -3/(2t) - Pe/(4 tw) (1 - tw^2/t^2), d2 ln IG/dt2 = 3/(2t^2) - Pe tw/(2t^3)
    const g1 = -1.5 / t - Pe / (4 * tw) * (1 - tw * tw / (t * t)), g2 = 1.5 / (t * t) - Pe * tw / (2 * t ** 3);
    const d1 = ig(t, tw, Pe) * g1, d2 = ig(t, tw, Pe) * (g1 * g1 + g2);
    const sc = ig(tw, tw, Pe);
    w1 = Math.max(w1, Math.abs(r.dh - d1) / (Math.abs(d1) + 1e-3 * sc / tw));
    w2 = Math.max(w2, Math.abs(r.d2 - d2) / (Math.abs(d2) + 1e-3 * sc / tw / tw));
  }
  below("h' by the inversion of s T(s)", w1, 1e-9);
  below("h'' by the inversion of s^2 T(s)", w2, 1e-8);
}

/* ======================================================================
   1b. Plug flow and an infinite matrix: the classical closed form
   ====================================================================== */
console.log('\n--- infinite matrix: the classical solution ---');
for (const [kd, de, aw, th] of [[0, 1e-6, 500, 1e7], [0.01, 5e-6, 1500, 7.6e4], [1, 4e-6, 800, Infinity], [2, 4e-6, 800, 432.6], [0.001, 1e-3, 1e4, 1e5]]) {
  const tw = 100, eps = 0.005, R = eps + kd * 2700, k = tw * aw * Math.sqrt(de * R), lam = isFinite(th) ? LN2 / th : 0;
  const { ctx, ws, ax } = oneNuclide({ tw, Pe: Infinity, aw, x0: Infinity, eps }, { thalf: th, kd, de });
  const up = k * k / 6;
  const ts = logGrid(up * 1e-3, up * 1e4, 141).map((u) => tw + u);
  const want = ts.map((t) => Math.exp(-lam * t) * neret(t - tw, k));
  const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
  below(`Pe = infinity, Kd ${kd}, De ${de}, aw ${aw}, T½ ${th}`, worstRel(ts, got, want, 1e-6), 1e-9);
  check(`  nothing before tw`, M.invertParabola(ctx, ws, ax, tw * 0.999).h === 0);
}
for (const [kd, de, aw, th, ka] of [[0.01, 5e-6, 1500, 7.6e4, 0.002], [1, 4e-6, 800, Infinity, 0.01]]) {
  // and with sorption on the fracture surfaces: the same, delayed by Rf tw
  const tw = 100, eps = 0.005, R = eps + kd * 2700, k = tw * aw * Math.sqrt(de * R), lam = isFinite(th) ? LN2 / th : 0, Rf = 1 + ka * aw;
  const { ctx, ws, ax } = oneNuclide({ tw, Pe: Infinity, aw, x0: Infinity, eps }, { thalf: th, kd, ka, de });
  const up = k * k / 6;
  const ts = logGrid(up * 1e-3, up * 1e4, 141).map((u) => tw * Rf + u);
  const want = ts.map((t) => Math.exp(-lam * t) * neret(t - tw * Rf, k));
  const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
  below(`Pe = infinity with fracture sorption, Rf = ${Rf}, Kd ${kd}`, worstRel(ts, got, want, 1e-6), 1e-9);
  check(`  nothing before Rf tw`, M.invertParabola(ctx, ws, ax, tw * Rf * 0.999).h === 0 && M.invertTalbot(ctx, ws, ax, tw * Rf * 0.999).h === 0);
}
{
  // plug flow moves a chain with one delay: members held back differently by the fracture are refused
  const base = { tw: 50, Pe: Infinity, aw: 400, eps: 0.005, x0: Infinity };
  let msg = '';
  try { M.prepare(Object.assign({}, base, { nuclides: [{ name: 'A', thalf: 100, kd: 0.1, ka: 0.01, de: 1e-6, daughter: true }, { name: 'B', thalf: 1e3, kd: 0.1, ka: 0, de: 1e-6 }] })); } catch (e) { msg = e.message; }
  check('plug flow with two fracture retardations in one chain is refused', /same fracture retardation/.test(msg), msg);
  const ctx = M.prepare(Object.assign({}, base, { nuclides: [{ name: 'A', thalf: 100, kd: 0.1, ka: 0.01, de: 1e-6, daughter: true }, { name: 'B', thalf: 1e3, kd: 0.3, ka: 0.01, de: 2e-6 }] }));
  check('  one retardation for the chain: the delay is Rf tw', M.pairDelay(ctx, 1, 0) === 50 * 5);
}
{
  // a very high Peclet number approaches the closed form where the matrix spreads the pulse far more than dispersion
  const tw = 100, kd = 0.01, de = 5e-6, aw = 1500, eps = 0.005, R = eps + kd * 2700, k = tw * aw * Math.sqrt(de * R);
  const { ctx, ws, ax } = oneNuclide({ tw, Pe: 1e6, aw, x0: Infinity, eps }, { thalf: Infinity, kd, de });
  const up = k * k / 6;
  const ts = logGrid(up * 1e-2, up * 1e3, 81).map((u) => tw + u);
  const want = ts.map((t) => neret(t - tw, k));
  const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
  below('Pe = 1e6 against the plug-flow closed form', worstRel(ts, got, want, 1e-4), 1e-3);
}
{
  // finite Pe and an infinite matrix: h(t) = e^-lam t int_0^t IG(u) K(u, t-u) du (subordination)
  const tw = 50, Pe = 8, kd = 0.005, de = 2e-6, aw = 400, eps = 0.004, th = 3e4;
  const R = eps + kd * 2700, lam = LN2 / th, c = aw * Math.sqrt(de * R);
  const { ctx, ws, ax } = oneNuclide({ tw, Pe, aw, x0: Infinity, eps }, { thalf: th, kd, de });
  const ts = logGrid(20, 2e4, 25);
  const want = ts.map((t) => Math.exp(-lam * t) * quad((u) => (u > 0 && u < t ? ig(u, tw, Pe) * neret(t - u, c * u) : 0), 0, t, 1e-12));
  const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
  below('finite Pe, infinite matrix, against the subordination integral', worstRel(ts, got, want, 1e-6), 1e-7);
}

/* ======================================================================
   1c. Chains whose members move alike: h_ij(t) = h(t) B_ij(t)
   ====================================================================== */
console.log('\n--- chains: the Bateman solution ---');
{
  const tw = 1000, Pe = 20, th = [3000, 700, 5000, 1e4];
  const nucs = th.map((t, q) => ({ name: `N${q}`, thalf: t, kd: 0.3, de: 1e-5, daughter: q < th.length - 1 }));
  const ctx = M.prepare({ tw, Pe, aw: 0, eps: 0.01, x0: 1, nuclides: nucs });
  const ws = M.makeWorkspace(ctx);
  const lams = th.map((t) => LN2 / t);
  for (const [i, j] of [[1, 0], [2, 0], [3, 0], [3, 1]]) {
    const ax = M.realAxis(ctx, ws, i, j, 1, 1e7);
    const ts = logGrid(tw / 8, tw * 12, 90);
    const want = ts.map((t) => ig(t, tw, Pe) * bateman(lams.slice(j, i + 1), t));
    const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
    below(`no matrix, ${nucs[i].name} from ${nucs[j].name}`, worstRel(ts, got, want, 1e-8), 1e-9);
  }
}
for (const [label, th, ka] of [['distinct half-lives', [3000, 700, 5000, 1e4], 0], ['close half-lives', [3000, 3000.3, 3000, 3000.0001], 0], ['equal half-lives', [1e4, 1e4, 1e4], 0],
  ['distinct half-lives, fracture sorption', [3000, 700, 5000, 1e4], 0.002], ['equal half-lives, fracture sorption', [1e4, 1e4, 1e4], 0.004]]) {
  const tw = 100, Pe = 10, aw = 1000, x0 = 0.5, de = 1e-5, kd = 0.01, eps = 0.005;
  const nucs = th.map((t, q) => ({ name: `N${q}`, thalf: t, kd, ka, de, daughter: q < th.length - 1 }));
  const ctx = M.prepare({ tw, Pe, aw, eps, x0, nuclides: nucs });
  const ws = M.makeWorkspace(ctx);
  const one = oneNuclide({ tw, Pe, aw, eps, x0 }, { thalf: Infinity, kd, ka, de });
  const lams = th.map((t) => LN2 / t);
  const n = th.length;
  for (const [i, j] of [[n - 1, 0], [1, 0]]) {
    const ax = M.realAxis(ctx, ws, i, j, 1, 1e7);
    const ts = logGrid(10, 1e5, 60);
    const want = ts.map((t) => M.invertParabola(one.ctx, one.ws, one.ax, t).h * bateman(lams.slice(j, i + 1), t));
    const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
    below(`matrix, ${label}, ${nucs[i].name} from ${nucs[j].name}`, worstRel(ts, got, want, 1e-6), 1e-7);
  }
}

/* ======================================================================
   1d. Mass balance and the transmission
   ====================================================================== */
console.log('\n--- mass balance ---');
{
  // a stable daughter: every atom leaves as the parent or as the daughter
  const ctx = M.prepare({ tw: 80, Pe: 10, aw: 800, eps: 0.004, x0: 0.8, nuclides: [
    { name: 'P1', thalf: 2000, kd: 0.05, de: 3e-6, daughter: true }, { name: 'D1', thalf: Infinity, kd: 0.2, de: 3e-6 }] });
  const ws = M.makeWorkspace(ctx);
  const T11 = M.transferAtZero(ctx, ws, 0, 0), T21 = M.transferAtZero(ctx, ws, 1, 0);
  below('T11(0) + T21(0) = 1 with a stable daughter', Math.abs(T11 + T21 - 1), 1e-12);
  // the integral of each computed response against T(0)
  for (const [i, j] of [[0, 0], [1, 0]]) {
    const ax = M.realAxis(ctx, ws, i, j, 1e-3, 1e12);
    const sup = M.responseSupport(ctx, ax, 1e-3, 1e12);
    const r = M.computeResponse(ctx, ws, ax, sup.tLo, sup.tHi, { peakEstimate: Math.exp(sup.logPeak) });
    below(`integral of h${i + 1}${j + 1} = T(0) (${r.t.length} samples)`, Math.abs(r.integral / M.transferAtZero(ctx, ws, i, j) - 1), 1e-8);
  }
}
{
  // the same with sorption on the fracture surfaces, both members held back differently
  const ctx = M.prepare({ tw: 80, Pe: 10, aw: 800, eps: 0.004, x0: 0.8, nuclides: [
    { name: 'P1', thalf: 2000, kd: 0.05, ka: 0.003, de: 3e-6, daughter: true }, { name: 'D1', thalf: Infinity, kd: 0.2, ka: 0.01, de: 3e-6 }] });
  const ws = M.makeWorkspace(ctx);
  below('with fracture sorption: T11(0) + T21(0) = 1', Math.abs(M.transferAtZero(ctx, ws, 0, 0) + M.transferAtZero(ctx, ws, 1, 0) - 1), 1e-12);
  for (const [i, j] of [[0, 0], [1, 0]]) {
    const ax = M.realAxis(ctx, ws, i, j, 1e-3, 1e12);
    const sup = M.responseSupport(ctx, ax, 1e-3, 1e12);
    const r = M.computeResponse(ctx, ws, ax, sup.tLo, sup.tHi, { peakEstimate: Math.exp(sup.logPeak) });
    below(`  integral of h${i + 1}${j + 1} = T(0) with fracture sorption`, Math.abs(r.integral / M.transferAtZero(ctx, ws, i, j) - 1), 1e-8);
  }
}
{
  // a long constant release reaches rate * T(0)
  const input = {
    params: { tw: 50, Pe: 20, aw: 500, eps: 0.004, x0: 0.5 },
    nuclides: [{ name: 'I129', thalf: 1.57e7, kd: 0, de: 1e-6, source: true }],
    series: { I129: [[0, 2], [1e7, 2]] },
    settings: { tEnd: 2e6, evalTimes: [1e6, 1.5e6], check: false },
  };
  const res = M.run(input);
  const T0 = res.responses[0].T0;
  below('a constant release reaches its rate times T(0)', Math.abs(res.at.out[0][0] / (2 * T0) - 1), 1e-9);
}
{
  // a short rectangular pulse of 1 mol gives the unit response
  const p = { tw: 150, Pe: 10, aw: 1200, eps: 0.003, x0: 2 };
  const nuc = { name: 'Ni59', thalf: 7.6e4, kd: 0.02, de: 4e-6, source: true };
  const t1 = 500, d = 1e-3;
  const times = logGrid(2e3, 1e6, 30);
  const res = M.run({ params: p, nuclides: [nuc], series: { Ni59: [[t1, 0], [t1, 1 / d], [t1 + d, 1 / d], [t1 + d, 0]] }, settings: { evalTimes: times, check: false } });
  const { ctx, ws, ax } = oneNuclide(p, nuc);
  const want = times.map((t) => M.invertParabola(ctx, ws, ax, t - t1 - d / 2).h);
  below('a 0.001-year pulse of 1 mol gives the unit response', worstRel(times, Array.from(res.at.out[0]), want, 1e-6), 1e-6);
}

/* ======================================================================
   2. The chain solution against TR 90-01's recursion (double precision,
      well separated nuclides). With fracture sorption the recursion takes
      F_k = Rf_k (s + lambda_k) + aw De_k h_k tanh(h_k x0) and the parent's
      term Rf_(i-1) P_(i-1,j,k); Ka = 0 is the recursion as printed.
   ====================================================================== */
console.log('\n--- chains: TR 90-01, Appendix C, Proposition 3 ---');
function recursionTR9001(c, sr, si) {
  // complex helpers on [re, im]
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]], sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const mul = (a, b) => [a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]];
  const div = (a, b) => { const d = b[0] * b[0] + b[1] * b[1]; return [(a[0] * b[0] + a[1] * b[1]) / d, (a[1] * b[0] - a[0] * b[1]) / d]; };
  const sc = (a, x) => [a[0] * x, a[1] * x];
  const sqrt = (a) => { const r = Math.hypot(a[0], a[1]); const re = Math.sqrt((r + a[0]) / 2); const im = Math.sign(a[1] || 1) * Math.sqrt((r - a[0]) / 2); return [re, im]; };
  const exp = (a) => [Math.exp(a[0]) * Math.cos(a[1]), Math.exp(a[0]) * Math.sin(a[1])];
  const tanh = (a) => { const e = exp(sc(a, -2)); return div(sub([1, 0], e), add([1, 0], e)); };
  const s = [sr, si];
  const N = c.nuclides.length;
  const lam = c.nuclides.map((n) => LN2 / n.thalf), R = c.nuclides.map((n) => c.eps + n.kd * 2700), De = c.nuclides.map((n) => n.de);
  const Rf = c.nuclides.map((n) => 1 + (n.ka || 0) * c.aw);
  const h = lam.map((l, k) => sqrt(sc(add(s, [l, 0]), R[k] / De[k])));
  const th = h.map((x) => mul(x, tanh(sc(x, c.x0))));
  const F = th.map((x, k) => add(sc(add(s, [lam[k], 0]), Rf[k]), sc(x, c.aw * De[k])));
  const H = F.map((f) => exp(sc(sub([1, 0], sqrt(add([1, 0], sc(f, 4 * c.tw / c.Pe)))), c.Pe / 2)));
  const out = [];
  for (let j = 0; j < N; j++) {
    const P = { [`${j},${j}`]: [1, 0] }, Q = { [`${j},${j},${j}`]: [1, 0] };
    out.push({ i: j, j, v: H[j] });
    for (let i = j + 1; i < N; i++) {
      const Kd = {};
      for (let l = j; l < i; l++) Kd[l] = sc(div(sub(th[l], th[i]), sub(mul(h[l], h[l]), mul(h[i], h[i]))), c.aw * R[i - 1]);
      for (let k = j; k < i; k++) {
        let acc = sc(P[`${i - 1},${k}`], Rf[i - 1]);
        for (let l = k; l < i; l++) acc = add(acc, mul(Q[`${i - 1},${k},${l}`], Kd[l]));
        P[`${i},${k}`] = mul(div([lam[i - 1], 0], sub(F[i], F[k])), acc);
      }
      let sum = [0, 0];
      for (let k = j; k < i; k++) sum = add(sum, P[`${i},${k}`]);
      P[`${i},${i}`] = sc(sum, -1);
      for (let k = j; k < i; k++) {
        let qs = [0, 0];
        for (let l = k; l < i; l++) {
          Q[`${i},${k},${l}`] = sc(div(Q[`${i - 1},${k},${l}`], sub(mul(h[i], h[i]), mul(h[l], h[l]))), R[i - 1] * lam[i - 1] / De[i]);
          qs = add(qs, Q[`${i},${k},${l}`]);
        }
        Q[`${i},${k},${i}`] = sub(P[`${i},${k}`], qs);
      }
      Q[`${i},${i},${i}`] = P[`${i},${i}`];
      let v = [0, 0];
      for (let k = j; k <= i; k++) v = add(v, mul(P[`${i},${k}`], H[k]));
      out.push({ i, j, v });
    }
  }
  return out;
}
{
  const c = { tw: 150, Pe: 15, aw: 800, eps: 0.005, x0: 1.5, nuclides: [
    { name: 'Am241', thalf: 432.6, kd: 2.0, de: 4e-6, daughter: true }, { name: 'Np237', thalf: 2.144e6, kd: 0.1, de: 5e-6, daughter: true },
    { name: 'U233', thalf: 1.592e5, kd: 0.05, de: 3e-6, daughter: true }, { name: 'Th229', thalf: 7340, kd: 1.0, de: 6e-6 }] };
  const ctx = M.prepare(c);
  const ws = M.makeWorkspace(ctx);
  let worst = 0;
  for (const [sr, si] of [[1e-3, 2e-3], [5e-6, 1e-5], [-2e-7, 3e-6], [0.02, -0.05]]) {
    for (const e of recursionTR9001(c, sr, si)) {
      const got = M.transfer(ctx, ws, sr, si, e.i, e.j);
      const d = Math.hypot(got[0] - e.v[0], got[1] - e.v[1]) / Math.hypot(e.v[0], e.v[1]);
      if (Math.hypot(e.v[0], e.v[1]) > 1e-250) worst = Math.max(worst, d);
    }
  }
  below('T_ij(s) against the recursion, element-specific De, four complex s', worst, 1e-11);
  // and with sorption on the fracture surfaces, a different Ka per element
  const cf = JSON.parse(JSON.stringify(c));
  cf.nuclides.forEach((n, q) => { n.ka = [0.004, 0.001, 0, 0.02][q]; });
  const ctf = M.prepare(cf), wsf = M.makeWorkspace(ctf);
  let wf = 0;
  for (const [sr, si] of [[1e-3, 2e-3], [5e-6, 1e-5], [-2e-7, 3e-6], [0.02, -0.05], [0, 0]]) {
    for (const e of recursionTR9001(cf, sr, si)) {
      const got = M.transfer(ctf, wsf, sr, si, e.i, e.j);
      if (Math.hypot(e.v[0], e.v[1]) > 1e-250) wf = Math.max(wf, Math.hypot(got[0] - e.v[0], got[1] - e.v[1]) / Math.hypot(e.v[0], e.v[1]));
    }
  }
  below('  and with fracture sorption (Ka per element)', wf, 1e-11);
}

/* ======================================================================
   3. Made-up cases against the 40-digit solution
   ====================================================================== */
const CASES = {
  single: { params: { tw: 50, Pe: 20, aw: 500, eps: 0.004, x0: 0.5 }, nuclides: [{ name: 'I129', thalf: 1.57e7, kd: 0, de: 1e-6, source: true }], series: { I129: [[0, 1], [1e6, 1]] } },
  pulse: { params: { tw: 200, Pe: 5, aw: 1500, eps: 0.003, x0: 3 }, nuclides: [{ name: 'Ni59', thalf: 7.6e4, kd: 0.01, de: 5e-6, source: true }], series: { Ni59: [[1000, 0], [1000.1, 1], [1100, 1], [1100.1, 0], [1e7, 0]] } },
  elem: { params: { tw: 30, Pe: 50, aw: 3000, eps: 0.002, x0: 0.2 }, nuclides: [{ name: 'Ra226', thalf: 1600, kd: 0.02, de: 2e-6, source: true, daughter: true }, { name: 'Pb210', thalf: 22.2, kd: 0.5, de: 8e-6 }], series: { Ra226: [[0, 1e-3], [2e4, 1e-3], [2e4, 0], [1e6, 0]] } },
  chain: { params: { tw: 150, Pe: 15, aw: 800, eps: 0.005, x0: 1.5 }, nuclides: [
    { name: 'Am241', thalf: 432.6, kd: 2.0, de: 4e-6, daughter: true, source: true }, { name: 'Np237', thalf: 2.144e6, kd: 0.1, de: 4e-6, daughter: true },
    { name: 'U233', thalf: 1.592e5, kd: 0.05, de: 4e-6, daughter: true, source: true }, { name: 'Th229', thalf: 7340, kd: 1.0, de: 4e-6 }],
    series: { Am241: [[0, 1e-2], [1e3, 5e-3], [1e4, 1e-4], [1e5, 0]], U233: [[0, 2e-4], [1e6, 2e-4]] } },
};
const mp = JSON.parse(fs.readFileSync(path.join(__dirname, 'ref', 'mpmath-ref.json'), 'utf8'));
// the case with sorption on the fracture surfaces carries its own input
for (const [name, rec] of Object.entries(mp.cases)) if (!CASES[name] && rec.input) CASES[name] = rec.input;
const refDir = process.env.FARF31_REF || path.join(os.homedir(), 'Downloads', 'Farf31-SKB-new', 'reference-cases');

console.log('\n--- made-up cases against the 40-digit solution ---');
let totalMs = 0;
for (const [name, c0] of Object.entries(CASES)) {
  const mref = mp.cases[name];
  const c = JSON.parse(JSON.stringify(c0));
  const evalTimes = [];
  for (const vals of Object.values(mref.outputs)) for (const [t] of vals) evalTimes.push(t);
  c.settings = { evalTimes, allResponses: true };
  const t0 = Date.now();
  const res = M.run(c);
  if (['single', 'pulse', 'elem', 'chain'].includes(name)) totalMs += Date.now() - t0;
  const tail = name.startsWith('tail-');
  let off = 0;
  for (const [nuc, vals] of Object.entries(mref.outputs)) {
    const i = res.names.indexOf(nuc);
    const got = vals.map((v, q) => res.at.out[i][off + q]);
    off += vals.length;
    if (vals.every((v) => !(v[1] > 1e-300))) { check(`${name} ${nuc}: all zero, as the reference`, got.every((g) => g < 1e-40)); continue; }
    if (!tail) {
      below(`${name} ${nuc}: release at ${vals.length} times`, worstRel(vals.map((v) => v[0]), got, vals.map((v) => v[1]), 1e-6), 2e-8);
      continue;
    }
    // A long tail after a step down: late in it the release is the part of
    // the response between t - 2e4 and t, where the response is held to
    // 1e-13 of its peak; so relative near the peak, absolute in the tail,
    // up to the run's end
    const k = vals.map((v, q) => q).filter((q) => vals[q][0] <= res.tEnd);
    const want = k.map((q) => vals[q][1]), gk = k.map((q) => got[q]), pk = Math.max(...want);
    below(`${name} ${nuc}: release at ${k.length} times, above 1e-4 of the peak`, worstRel(k.map((q) => vals[q][0]), gk, want, 1e-4), 2e-8);
    below(`${name} ${nuc}: release at the same times, absolute, over the peak`, Math.max(...gk.map((g, q) => Math.abs(g - want[q]))) / pk, 1e-10);
  }
  check(`${name}: every response meets its mass balance (the run's own check)`, res.balance && res.balance.failed.length === 0, JSON.stringify(res.balance && res.balance.failed));
  for (const [key, T0] of Object.entries(mref.T0)) {
    const [i, j] = key.split(',').map(Number);
    const r = res.responses.find((q) => q.i === i && q.j === j);
    below(`${name} T(0) of ${res.names[i]} from ${res.names[j]}`, Math.abs(r.T0 / T0 - 1), 1e-12);
    if (T0 > 1e-30) below(`${name} integral of that response = T(0)`, Math.abs(r.integral / T0 - 1), 1e-7);
  }
  const ctx = M.prepare(Object.assign({}, c.params, { nuclides: c.nuclides }));
  const ws = M.makeWorkspace(ctx);
  for (const r of mref.responses) {
    const ax = M.realAxis(ctx, ws, r.i, r.j, 1e-3, 1e12);
    const ts = r.values.map((v) => v[0]);
    const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
    if (r.values.every((v) => !(v[1] > 1e-300))) continue;
    below(`${name} unit response ${res.names[r.i]} from ${res.names[r.j]} at ${ts.length} times`, worstRel(ts, got, r.values.map((v) => v[1]), 1e-6), 1e-9);
  }
  check(`${name}: the de Hoog check agrees`, res.check.worst < 1e-5, res.check.worst.toExponential(2));
}
check('the four reference cases in well under a second together', totalMs < 1500, `${totalMs} ms`);

/* ======================================================================
   3b. Robustness: the real axis next to a singularity, the mass balance,
       high Peclet numbers
   ====================================================================== */
console.log('\n--- the real axis, the mass balance, high Peclet numbers ---');
{
  // A step input into this tube once gave an all-zero release: next to the
  // rightmost singularity the scan kept evaluating the transform where
  // rounding had taken over, found a negative tilted mean there, and every
  // saddle search stopped on it.
  const c = mp.cases['tail-30-1'].input;
  const ctx = M.prepare(Object.assign({}, c.params, { nuclides: c.nuclides }));
  const ws = M.makeWorkspace(ctx);
  const ax = M.realAxis(ctx, ws, 0, 0, ctx.tw * 1e-6, 1e12);
  let mono = ax.D.length > 10;
  for (let k = 0; k < ax.D.length; k++) if (!(ax.D[k] > 0) || (k && !(ax.D[k] < ax.D[k - 1]))) mono = false;
  check('the real axis of the tail case: the tilted mean positive and falling throughout', mono);
  const ts = logGrid(10, 1e5, 21);
  check('  and a saddle at every time from 10 to 1e5 a', ts.every((t) => { const q = M.saddleAt(ax, t); return q && isFinite(q.s) && isFinite(q.w); }));
  const res = M.run(Object.assign({}, c, { settings: {} }));
  const r = res.responses[0];
  let pk = 0; for (const v of res.out[0]) pk = Math.max(pk, v);
  check('  the step input gives its release (peak near the input rate 1 mol/a)', pk > 0.99 && pk < 1.0001, pk.toPrecision(6));
  below('  and the response carries what leaves the tube by its last time', Math.abs(r.integral - r.expected) / r.T0, 1e-8);
  // the run's own check: a response that misses part of the pulse is caught
  const halved = M.massBalance(ctx, ws, ax, Object.assign({}, r, { integral: r.integral / 2 }), 1e-6);
  const cut = M.massBalance(ctx, ws, ax, Object.assign({}, r, { t: r.t.filter((t) => t <= 300), integral: 0.9 }), 1e-6);
  check('the mass balance: the response as computed passes', M.massBalance(ctx, ws, ax, r, 1e-6).ok === true);
  check('  half of it fails', halved.ok === false && Math.abs(halved.rel - 0.5) < 1e-6, halved.rel.toPrecision(4));
  check('  one that ends at 300 a is held to what leaves by then (0.9838) and fails at 0.9', cut.ok === false && Math.abs(cut.expected - 0.98377) < 1e-4, cut.expected.toPrecision(6));
  check('  the run as computed reports nothing', res.balance.failed.length === 0 && res.notes.length === 0, JSON.stringify(res.notes));
  // a response grid far too coarse to hold the response (one point a
  // decade, at most a dozen): the run tries again and then says so
  const bad = M.run(Object.assign({}, c, { settings: { respPerDecade: 1, respMaxPts: 12, check: false } }));
  check('  a response too coarse to integrate is reported in the run\'s notes', bad.balance.failed.length === 1 && /integrates to .* leaves the tube/.test(bad.notes.join(' ')), bad.notes.join(' '));
}
{
  // The automatic end of the output: from the responses themselves, as far
  // as 1e12 a. A long-lived member held back by a matrix that fills over
  // 3e9 a releases well past a billion years (the end was once capped there).
  const long = M.run({ params: { tw: 1000, Pe: 10, aw: 100, eps: 0.005, x0: 1, rho: 2700 },
    nuclides: [{ name: 'U235', thalf: 7.04e8, kd: 1.1, de: 1e-6, source: true }], series: { U235: [[0, 1], [1e4, 1]] } });
  let pk = 0; for (const v of long.out[0]) pk = Math.max(pk, v);
  const last = long.out[0][long.out[0].length - 1] / pk;
  check('the automatic end follows a release that lasts past 1e9 a to below 1e-9 of its peak, no note', long.tEnd > 3e9 && last < 1e-9 && long.notes.length === 0, `end ${long.tEnd.toPrecision(3)} a, ${last.toExponential(1)} of the peak there`);
  // an infinite matrix and a stable nuclide: the release never ends, and the
  // page's limit says so
  const endless = M.run({ params: { tw: 1000, Pe: 10, aw: 100, eps: 0.005, x0: Infinity, rho: 2700 },
    nuclides: [{ name: 'X', thalf: Infinity, kd: 1.1, de: 1e-6, source: true }], series: { X: [[0, 1], [1e4, 1]] } });
  check('  a release that never ends stops at the limit, 1e12 a, and the Summary says so', endless.tEnd === 1e12 && /stops at 1\.00e\+12 a, the page's limit/.test(endless.notes.join(' ')), endless.notes.join(' '));
  check('  its response still carries what has left by its last time', endless.balance.failed.length === 0);
}
{
  // Plug flow (Pe = infinity): nothing arrives before the delay, and the grids
  // are logarithmic in t minus the delay. A matrix that fills at once makes the
  // response a spike 0.4 a after a delay of 120 a (it once fell between the
  // points of a grid logarithmic in t, and the response came out zero); a
  // daughter born near the outlet arrives within a hair of the delay (what
  // arrives before the first grid time is kept as a point mass).
  const spike = M.run({ params: { tw: 119.84, Pe: Infinity, aw: 380.5, eps: 1.085e-4, x0: 0.0817, rho: 2700 },
    nuclides: [{ name: 'X', thalf: 2.727e5, kd: 0, de: 3.157e-3, source: true }], series: { X: [[0, 1], [3333, 1]] } });
  const r = spike.responses[0];
  check('plug flow, a matrix that fills at once: the spike is found, 0.40 a after the delay', Math.abs(r.tPeak - 120.244) < 0.005, r.tPeak.toFixed(4));
  below('  and it carries T(0)', Math.abs(r.integral / r.T0 - 1), 1e-8);
  check('  the de Hoog check agrees', spike.check.worst < 1e-5, spike.check.worst.toExponential(2));
  const hair = M.run({ params: { tw: 50.27, Pe: Infinity, aw: 0.3922, eps: 1.888e-4, x0: Infinity, rho: 2700 }, nuclides: [
    { name: 'P', thalf: 13.05, kd: 3.703e-4, de: 1.508e-6, daughter: true, source: true }, { name: 'D', thalf: 8.216e5, kd: 0, de: 1.508e-6 }],
  series: { P: [[0, 1], [1, 1]] } });
  const d = hair.responses.find((x) => x.i === 1);
  check('plug flow, a daughter born near the outlet: the part before the first grid time is kept', d.m0 > 1e-3, d.m0.toExponential(3));
  below('  and the response carries what has left by its last time', Math.abs(d.integral - d.expected) / d.T0, 1e-8);
}
{
  // Made-up cases with sharp fronts (Pe 1000 to 10 000) and matrices that
  // hold far more than the water, some with a daughter that the matrix holds
  // back much longer than its parent. Their transforms reach e^(Pe/2) at the
  // fracture's branch point; a contour that bends into that region, or a
  // saddle placed far off on a coarse real axis, gave values off by many
  // orders of magnitude. Against de Hoog's method with twice its usual terms
  // (good to about 1e-12 of each peak: compared above 1e-4 of it).
  const HARD = {
    'Pe 1000, chain, deep matrix': { params: { tw: 23.36, Pe: 1000, aw: 6.508, eps: 0.00755, x0: 64.52 }, nuclides: [
      { name: 'P1', thalf: 57.49, kd: 0, de: 4.153e-6, daughter: true, source: true }, { name: 'D1', thalf: 55.24, kd: 0.05558, de: 4.153e-6 }] },
    'Pe 10000, thin matrix': { params: { tw: 1227.2, Pe: 1e4, aw: 0.125, eps: 0.003466, x0: 0.502 }, nuclides: [
      { name: 'X1', thalf: Infinity, kd: 0, de: 1.108e-4, source: true }] },
    'Pe 3000, chain, daughter held 20 times longer': { params: { tw: 890.08, Pe: 3000, aw: 1002.5, eps: 0.000611, x0: 0.1608 }, nuclides: [
      { name: 'P1', thalf: 5992.8, kd: 0, de: 0.00119, daughter: true, source: true }, { name: 'D1', thalf: 1.006e7, kd: 5.084e-5, de: 0.00119 }] },
    'Pe 3000, 5 mm matrix': { params: { tw: 2.549, Pe: 3000, aw: 105.07, eps: 0.001107, x0: 0.00506 }, nuclides: [
      { name: 'X1', thalf: Infinity, kd: 0.0003797, de: 1.498e-7, source: true }] },
  };
  for (const [label, c0] of Object.entries(HARD)) {
    const c = Object.assign({ series: { [c0.nuclides[0].name]: [[0, 1], [1, 1]] }, settings: { tEnd: 1e13 } }, c0);
    c.params = Object.assign({ rho: 2700 }, c.params);
    const t0 = Date.now();
    const res = M.run(c);
    const ms = Date.now() - t0;
    let worstBal = 0;
    for (const r of res.responses) if (r.T0 > 1e-30) worstBal = Math.max(worstBal, Math.abs(r.integral - r.expected) / r.T0);
    below(`${label}: every response carries what leaves the tube`, worstBal, 1e-6);
    const ctx = M.prepare(Object.assign({}, c.params, { nuclides: c.nuclides }));
    const ws = M.makeWorkspace(ctx);
    const mH = 2 * M.deHoogTerms(ctx);
    let worst = 0;
    for (const r of res.responses) {
      const idx = [];
      for (let k = 0; k < r.t.length; k++) if (r.h[k] > 1e-4 * r.peak) idx.push(k);
      const step = Math.max(1, Math.floor(idx.length / 30));
      for (let q = 0; q < idx.length; q += step) {
        const k = idx[q], v = M.invertDeHoog(ctx, ws, r.i, r.j, r.t[k], { M: mH });
        worst = Math.max(worst, Math.abs(v - r.h[k]) / r.h[k]);
      }
    }
    below(`  its responses against de Hoog with ${mH} terms, above 1e-4 of each peak`, worst, 1e-7);
    check(`  and the run's own check against de Hoog`, res.check.worst < 1e-5, res.check.worst.toExponential(2));
    check(`  in a few seconds at most`, ms < 8000, `${ms} ms`);
  }
}

/* ======================================================================
   4. The original program's outputs for the made-up reference cases
   ====================================================================== */
const PRESENT = ['single', 'pulse', 'elem', 'chain', 'chain-dense', 'pulse-nozero', 'elem-ramp'].filter((name) => fs.existsSync(path.join(refDir, name, 'in.dat')));
if (PRESENT.length) {
  console.log('\n--- the original program\'s outputs for the made-up reference cases ---');
  const load = (name) => {
    const read = (f) => fs.readFileSync(path.join(refDir, name, f), 'utf8');
    const dat = IO.readDat(read('in.dat')), par = IO.readPar(read('in.par')), ts = IO.readTs(read('in.ts'));
    IO.applyPar(dat, par);
    return { read, dat, par, ts, params: { tw: par.TW, Pe: par.PECLET, aw: par.ASPEC, eps: par.EPS, x0: par.PENDEP } };
  };
  // its unit responses near their peaks (those that carry more than 1e-10 of a pulse)
  for (const name of PRESENT) {
    const L = load(name);
    if (!fs.existsSync(path.join(refDir, name, 'out.response'))) continue;
    const ctx = M.prepare(Object.assign({}, L.params, { nuclides: L.dat.nuclides }));
    const ws = M.makeWorkspace(ctx);
    for (const blk of IO.readOutResponse(L.read('out.response'))) {
      if (blk.pts.length < 3 || !blk.pts.some((q) => q[1] > 0) || !(M.transferAtZero(ctx, ws, blk.i, blk.j) > 1e-10)) continue;
      const ax = M.realAxis(ctx, ws, blk.i, blk.j, 1e-3, 1e12);
      const ts = blk.pts.map((q) => q[0]);
      const got = ts.map((t) => M.invertParabola(ctx, ws, ax, t).h);
      below(`${name}: its unit response ${ctx.names[blk.i]} from ${ctx.names[blk.j]}, above half the peak`, worstRel(ts, got, blk.pts.map((q) => q[1]), 0.5), 5e-3);
    }
  }
  // the releases of the cases whose inputs are sampled densely
  for (const name of PRESENT.filter((n) => ['chain-dense', 'pulse-nozero', 'elem-ramp'].includes(n))) {
    const L = load(name);
    const outTs = Object.entries(IO.readOutTs(L.read('out.ts'))).filter(([, rows]) => rows.some((r) => r[1] > 0));
    const evalTimes = [];
    for (const [, rows] of outTs) for (const r of rows) evalTimes.push(r[0]);
    const res = M.run({ params: L.params, nuclides: L.dat.nuclides, series: L.ts.series, settings: { evalTimes, check: false } });
    let off = 0;
    for (const [nuc, rows] of outTs) {
      const i = res.names.findIndex((n) => n.toUpperCase() === nuc);
      const got = rows.map((r, q) => res.at.out[i][off + q]);
      off += rows.length;
      const ts6 = rows.map((r) => r[0]), want = rows.map((r) => r[1]);
      below(`${name} ${nuc}: its release, above half the peak`, worstRel(ts6, got, want, 0.5), 5e-3);
      below(`${name} ${nuc}: its release, above 1e-2 of the peak`, worstRel(ts6, got, want, 1e-2), 2e-2);
    }
  }
} else {
  console.log(`\n(no reference cases in ${refDir}: the original program's outputs are not compared)`);
}

/* ======================================================================
   5. The files
   ====================================================================== */
console.log('\n--- files ---');
{
  const fx = path.join(__dirname, 'fixture');
  const dat = IO.readDat(fs.readFileSync(path.join(fx, 'in.dat'), 'utf8'));
  const par = IO.readPar(fs.readFileSync(path.join(fx, 'in.par'), 'utf8'));
  const ts = IO.readTs(fs.readFileSync(path.join(fx, 'in.ts'), 'utf8'));
  const prm = IO.readPrm(fs.readFileSync(path.join(fx, 'uchain31.prm'), 'utf8'));
  check('in.dat: three nuclides, a chain, two sources', JSON.stringify(dat.nuclides.map((n) => [n.name, n.daughter, n.source])) === JSON.stringify([['U238', true, true], ['U234', true, true], ['Th230', false, false]]));
  check('in.dat: keywords', dat.casename === 'uchain' && dat.print === 'DEBUG' && dat.diffusivity === 'SINGLE');
  const w = IO.applyPar(dat, par);
  check('in.par: KDR_U2 reaches both uranium isotopes', dat.nuclides[0].kd === 0.03 && dat.nuclides[1].kd === 0.03 && dat.nuclides[2].kd === 0.3 && !w.length);
  check('in.ts: two series, a step kept', ts.order.join() === 'U238,U234' && ts.series.U238.length === 3 && ts.series.U238[1][0] === ts.series.U238[2][0]);
  check('prm: TALBOT, RELINT, BQMIN, NPMIN read', prm.settings.method === 'talbot' && prm.settings.relint === 1e-3 && prm.settings.bqMin === 1e-3 && prm.settings.npMin === 32);
  const kase = { print: dat.print, casename: dat.casename, diffusivity: dat.diffusivity, params: { tw: par.TW, Pe: par.PECLET, aw: par.ASPEC, eps: par.EPS, de: par.DE, x0: par.PENDEP, rho: 2700 }, nuclides: dat.nuclides, series: ts.series, settings: prm.settings };
  const d2 = IO.readDat(IO.writeDat(kase)), p2 = IO.readPar(IO.writePar(kase)), t2 = IO.readTs(IO.writeTs(kase)), m2 = IO.readPrm(IO.writePrm(kase));
  IO.applyPar(d2, p2);
  check('written and read back: in.dat', JSON.stringify(d2.nuclides) === JSON.stringify(dat.nuclides));
  check('written and read back: in.par', p2.TW === par.TW && p2.PECLET === par.PECLET && p2.ASPEC === par.ASPEC && p2.EPS === par.EPS && p2.DE === par.DE && p2.PENDEP === par.PENDEP);
  check('written and read back: in.ts', JSON.stringify(t2.series) === JSON.stringify(ts.series));
  check('written and read back: the .prm', m2.settings.method === 'talbot' && m2.settings.relint === 1e-3);
  // FARF31's own syntax: a bare line picks the routine, RHOP the density, NPMAX at most 128
  const p1 = IO.readPrm('STEAMR\nRHOP 1350.\nRELINT 1.0E-03\n');
  check('prm: STEAMR read as the default method, with a note; RHOP as the density', p1.settings.method === 'parabola' && p1.notes.length === 1 && p1.settings.rho === 1350 && p1.settings.relint === 1e-3);
  check('prm: the page\'s METHOD line wins over FARF31\'s bare line', IO.readPrm('BROMEX\nMETHOD PARABOLA\n').settings.method === 'parabola' && IO.readPrm('BROMEX\n').settings.method === 'dehoog');
  const w1 = IO.writePrm({ params: { rho: 1350 }, settings: { method: 'talbot', npMax: 2500, npMin: 20, relint: 1e-2 } });
  check('prm written for FARF31: BROMEX, RHOP, no NPMAX beyond 128', /^BROMEX$/m.test(w1) && /^METHOD TALBOT$/m.test(w1) && /^RHOP 1350\.$/m.test(w1) && !/NPMAX/.test(w1) && /^NPMIN 20$/m.test(w1), w1.replace(/\n/g, ' | '));
  check('prm written for FARF31: plain ASCII', /^[\x00-\x7f]*$/.test(w1));
  // element-specific diffusivity
  const d3 = IO.readDat('DIFFUSIVITY ELEMENT_SPECIFIC\nRa226 1600. 1 1\nPb210 22.2 0 0\n');
  IO.applyPar(d3, IO.readPar('TW 30.\nPECLET 50.\nASPEC 3000.\nEPS 0.002\nPENDEP 0.2\nKDR_Ra 0.02\nKDR_Pb 0.5\nDE_Ra 2.0E-6\nDE_Pb 8.0E-6\n'));
  check('DE_XX per element, keys in any case', d3.nuclides[0].de === 2e-6 && d3.nuclides[1].de === 8e-6 && d3.nuclides[1].kd === 0.5);
  // the page's own KA_XX: read per element key, 0 where absent, written only when one is not zero
  const d4 = IO.readDat('U238 4.468E9 1 1\nU234 2.455E5 1 0\nTh230 7.54E4 0 0\n');
  const w4 = IO.applyPar(d4, IO.readPar('TW 60.\nPECLET 12.\nASPEC 1500.\nEPS 0.004\nDE 3.0E-6\nPENDEP 2.\nKDR_U2 0.03\nKDR_TH 0.3\nKA_U2 0.002\n'));
  check('in.par KA_U2: Ka on both uranium isotopes, 0 for thorium, no warning', d4.nuclides[0].ka === 0.002 && d4.nuclides[1].ka === 0.002 && d4.nuclides[2].ka === 0 && !w4.length, w4.join(' | '));
  const kase4 = { diffusivity: 'SINGLE', params: { tw: 60, Pe: 12, aw: 1500, eps: 0.004, de: 3e-6, x0: 2 }, nuclides: d4.nuclides };
  const par4 = IO.writePar(kase4);
  const back4 = IO.readDat('U238 4.468E9 1 1\nU234 2.455E5 1 0\nTh230 7.54E4 0 0\n');
  IO.applyPar(back4, IO.readPar(par4));
  check('KA_ lines written and read back', /^KA_U2 0\.002$/m.test(par4) && /^KA_TH 0\.0$/m.test(par4) && back4.nuclides.map((n) => n.ka).join() === '0.002,0.002,0', par4.replace(/\n/g, ' | '));
  check('no KA_ lines when every Ka is 0 (FARF31\'s format)', !/KA_/.test(IO.writePar(Object.assign({}, kase4, { nuclides: d4.nuclides.map((n) => Object.assign({}, n, { ka: 0 })) }))));
  let kmsg = '';
  try { IO.readPar('KA_U2 -1\n'); } catch (e) { kmsg = e.message; }
  check('a negative Ka is refused with its line', /line 1/.test(kmsg), kmsg);
  // FARF31's F: any two of TW, ASPEC and F
  const pf = IO.readPar('TW 50.\nF 1.0E+05\nPECLET 10.\nEPS 0.005\nDE 1e-6\nPENDEP 1.\nKDR_I1 0.\n');
  const pg = IO.readPar('ASPEC 2000.\nF 1.0E+05\nPECLET 10.\nEPS 0.005\nDE 1e-6\nPENDEP 1.\nKDR_I1 0.\n');
  let fmsg = '';
  try { IO.readPar('TW 50.\nASPEC 2000.\nF 1.0E+05\n'); } catch (e) { fmsg = e.message; }
  check('in.par F: ASPEC = F/TW, TW = F/ASPEC, all three refused', pf.ASPEC === 2000 && pg.TW === 50 && /only two/.test(fmsg), fmsg);
  // errors name the line
  let msg = '';
  try { IO.readDat('PRINT ON\nU238 4.5e9 1\n'); } catch (e) { msg = e.message; }
  check('a short nuclide line is refused with its line number', /line 2/.test(msg), msg);
  try { msg = ''; IO.readTs('U238\n0 1\n10 2\n5 3\n'); } catch (e) { msg = e.message; }
  check('decreasing times in in.ts are refused', /decrease/.test(msg), msg);
  check('Fortran D exponents', IO.fnum('1.5D-3') === 1.5e-3 && IO.fnum('50.') === 50 && Number.isNaN(IO.fnum('abc')));
  // out.ts and out.response in FARF31's layout
  const res = M.run({ params: { tw: 50, Pe: 20, aw: 500, eps: 0.004, x0: 0.5 }, nuclides: [{ name: 'I129', thalf: 1.57e7, kd: 0, de: 1e-6, source: true }], series: { I129: [[0, 1], [1e6, 1]] }, settings: { check: false } });
  const out = IO.writeOutTs(res, { bqMin: 1e-3, date: new Date(2026, 8, 25, 23, 47, 15) });
  const L = out.split('\n');
  check('out.ts: the header lines of FARF31', L[0] === ' Run made on  Sep. 25,   26  (23:47:15)' && L[2] === '  Output migration rate from stream tube:' && L[4] === '      Time (a)                  Rate' && L[5] === '                       (mol/a)         (Bq/a)' && L[6] === '  Nuclide' && L[7] === '  I129  ');
  check('out.ts: data lines as 3X,E12.6,4X,E12.6,4X,E12.6', /^ {3}\d\.\d{6}E[-+]\d\d {4}\d\.\d{6}E[-+]\d\d {4}\d\.\d{6}E[-+]\d\d$/.test(L[8]), L[8]);
  const back = IO.readOutTs(out);
  check('out.ts read back', back.I129 && back.I129.length > 50);
  const bq = back.I129[10][2] / back.I129[10][1];
  check('Bq/a per mol/a with FARF31\'s constants', Math.abs(bq / (LN2 / (1.57e7 * 365.2422 * 86400) * 6.022045e23) - 1) < 1e-6, String(bq));
  const orsp = IO.writeOutResponse(res).split('\n');
  check('out.response: the block header', /^ NPRESP\(MPRES= {11}1 ,MSUB= {11}1 \)= +\d+$/.test(orsp[0]), orsp[0]);
  check('out.response: E20.4 columns', /^ {10}0\.\d{4}E[-+]\d\d {10}0\.\d{4}E[-+]\d\d$/.test(orsp[1]), orsp[1]);
  check('out.response: the integral line', orsp.some((l) => /^Integrated curve for I129 {12}0\.1000E\+01$/.test(l)));
  check('Fortran E20.4 formatting', IO.fe(1.0032) === '          0.1003E+01' && IO.fe(6.317e-19) === '          0.6317E-18' && IO.fe(0) === '          0.0000E+00');
}
{
  // shapes
  const pts = M.seriesFromShapes([{ kind: 'pulse', t1: 100, duration: 10, amount: 5 }]);
  check('a pulse shape: 0.5 mol/a for 10 years, steps at both ends', JSON.stringify(pts) === JSON.stringify([[100, 0], [100, 0.5], [110, 0.5], [110, 0]]));
  const ex = M.seriesFromShapes([{ kind: 'exponential', t1: 0, t2: 1e4, rate: 1, halfTime: 2e3 }]);
  let werr = 0;
  for (let q = 0; q + 1 < ex.length; q++) {
    const tm = 0.5 * (ex[q][0] + ex[q + 1][0]);
    if (ex[q][0] === ex[q + 1][0]) continue;
    werr = Math.max(werr, Math.abs(0.5 * (ex[q][1] + ex[q + 1][1]) - Math.exp(-LN2 * tm / 2e3)));
  }
  below('an exponential shape within 1e-4 of the curve', werr, 1e-4);
  const s = M.normaliseSeries([[0, 1], [10, 1], [10, 0], [20, 0]]);
  check('a series: mass, first and last non-zero', Math.abs(s.mass - 10) < 1e-12 && s.tFirst === 0 && s.tLast === 10);
}
{
  // presets and examples are well formed and run
  for (const ex of DATA.EXAMPLES) {
    const p = Object.assign({}, ex.params);
    const aw = p.awMode === 'F' ? p.F / p.tw : p.aw;
    const res = M.run({ params: { tw: p.tw, Pe: p.Pe, aw, eps: p.eps, x0: p.x0, rho: p.rho }, nuclides: ex.nuclides.map((n) => Object.assign({}, n, { de: ex.diffusivity === 'SINGLE' ? p.de : n.de })), series: ex.series, settings: { check: false } });
    check(`example "${ex.label}" runs`, res.times.length > 20 && res.peaks.some((q) => q.rate > 0));
  }
  check('every preset nuclide has a half-life', DATA.PRESETS.every((p) => (p.chain || p.singles).every((n) => DATA.halfLife(n) > 0)));
}
{
  // a negative travel time: an empty output, as in FARF31
  const res = M.run({ params: { tw: -1, Pe: 10, aw: 1000, eps: 0.005, x0: 1 }, nuclides: [{ name: 'I129', thalf: 1.57e7, kd: 0, de: 1e-6, source: true }], series: { I129: [[0, 1], [10, 1]] } });
  check('tw < 0 gives an empty output', res.empty === true && res.times.length === 0);
  let msg = '';
  try { M.prepare({ tw: 10, Pe: Infinity, aw: 0, eps: 0.005, x0: 1, nuclides: [{ name: 'X', thalf: 1, kd: 0, de: 1e-6 }] }); } catch (e) { msg = e.message; }
  check('plug flow without matrix diffusion is refused', /delta function/.test(msg), msg);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed${failures.length ? `; FAILED: ${failures.join('; ')}` : ''}.`);
process.exit(failures.length ? 1 : 0);
