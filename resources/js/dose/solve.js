/*
  Solving the compartment system of an intake and integrating the dose.

  The activities q(t) obey dq/dt = A(age) q, linear with coefficients that
  change with age: every transfer rate is a table over reference ages,
  interpolated linearly between them (ICRP 56 onwards; ORNL/TM-2001/190 8.2).
  Activities are carried in becquerels, not atoms, so that a short-lived
  daughter in equilibrium with its parent is of the parent's size instead of
  vanishingly small (decay then enters as lambda_daughter * branch * q_parent).

  The equivalent dose in each target is

      H_T = sum_c ∫ q_c(t) SEE_c(T; age(t)) dt      (x 86400, t in days)

  and SEE changes with age as the body grows. Between two reference ages it is
  one polynomial in age for every source and target alike: linear (ICRP 60;
  in the first year, in the weight of firstYearWeight), or the cubic of PCHIP
  (ICRP 103 between the reference phantoms), which in Bernstein form is

      SEE(u) = sum_j b_j B_j(u),   B_0 = (1-u)^3, B_1 = 3u(1-u)^2, B_2 = 3u^2(1-u), B_3 = u^3,
      b_0 = SEE_lo, b_1 = SEE_lo + h SEE'_lo / 3, b_2 = SEE_hi - h SEE'_hi / 3, b_3 = SEE_hi

  with u the fraction of the interval, h its length (a linear stretch is
  1 - w and w on b_0 = SEE_lo and b_3 = SEE_hi). So

      H_T = sum over stretches, sum_g sum_j b_j(g, T) ∫ B_j(u(t)) q_g(t) dt

  with q_g the activity of the compartments of a group that share their SEE
  (a member in a source region). The integrator carries those integrals, four
  per group (two for ICRP 60), and the doses of all targets are put together
  from them at the end of each stretch -- exactly, for the polynomial: no
  quadrature of sampled dose rates (which is what DCAL's EPACAL does, with a
  monotone spline). The basis functions are not negative and add up to one,
  and PCHIP keeps b_1 and b_2 between b_0 and b_3, so every term of a dose is
  positive and the integrals' relative accuracy is the doses'; their sum over
  j is the group's number of transformations.

  Carrying the doses themselves instead (one equation per target, one value
  per compartment and target in the matrix) is what this did until October
  2026: the matrix then was some ten times larger (226Ra: 52,170 values,
  49,200 of them dose rates; now 5,622), and a run three to four times
  longer. The results differ by the integrator's tolerance (e by at most
  1.4e-6 of its value over 544 cases at six ages; compare-engines.mjs).

  The integrator is the NDF/BDF of resources/js/ode with the exact sparse
  Jacobian. It is restarted at every age where a rate or SEE table has a kink,
  so that no step straddles one.
*/
import { ndf } from '../ode/solvers/ndf.js';
import { cscFromTriplets } from '../ode/core/sparse.js';
import { lerp } from './see60.js';
import { pchipSlopes } from './see103.js';

const DAY = 86400;

/** Index of the interval of `xs` (sorted) that holds x, and the weight within it. */
function bracket(xs, x) {
  const n = xs.length;
  if (n === 1 || x <= xs[0]) return [0, 0];
  if (x >= xs[n - 1]) return [n - 2, 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= x) lo = m; else hi = m; }
  return [lo, (x - xs[lo]) / (xs[hi] - xs[lo])];
}

/*
  The weight of the 1-year phantom between birth and age 1 (ICRP 158, eqs.
  2.15 and 2.16, after the growth curves of ICRP 89): organs grow fastest in
  the first months, so a linear weight in age would hold the newborn's
  values far too long. t is the age in years.

      x = t^(0.3 + 0.7 (1 - t)^10)     t < 100/365
      x = t^(0.16 + 0.84 (1 - t)^5)    100/365 <= t < 1

  Just below 100 d, x = 0.6536 -- the factor DCAL's newborn mass file
  (REGMASS.A00) cites for its 3-month values -- and from 100 d the second
  branch gives 0.6528; the weighting reproduces the ICRP 72 dose coefficients
  for the 3-month-old, which a linear weight (0.274) overestimates by up to a
  quarter.
*/
export function firstYearWeight(ageDays) {
  const t = ageDays / 365;
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  const e = t < 100 / 365 ? 0.3 + 0.7 * (1 - t) ** 10 : 0.16 + 0.84 * (1 - t) ** 5;
  return t ** e;
}

/**
 * @param {object} sys   from assemble60/assemble103: {members, comps, transfers, decays, init}
 * @param {object} dose  {phantomAges: number[], columns: Array<Array<Float64Array>> (per comp,
 *                        per phantom age: SEE per target; compartments with the same SEE may
 *                        share the array), nTargets, groups: Array<number[]> (comp indices whose
 *                        activity counts toward each reported region), interp: 'icrp103' | 'linear',
 *                        functionals: Float64Array[] (optional; weights of the targets' doses, such
 *                        as those that make the effective dose), byCompartment (optional: a dose
 *                        group for every compartment, so that the functionals' shares are each
 *                        compartment's -- the Model tab's boxes; more integrals, the same doses)}
 * @param {object} opt   {intakeAge, period (days), outputs: number[] (days after intake), rtol}
 * @returns {{H: Float64Array, U: number[], q: Float64Array, series, stats, doseGroups, parts}} the
 *   dose to each target (Sv per Bq), the transformations in each group, the activities at the end,
 *   and at each output time the state as [activities, doses, transformations / 86400]; with
 *   functionals, each output's `parts` and the committed `parts` hold every functional's share of
 *   each dose group (doseGroups: {member, region, comps}), group by group, functional by functional,
 *   and each output's `rates` how fast those shares grow there (per day).
 */
export function integrate(sys, dose, opt) {
  const n = sys.comps.length;
  const nT = dose.nTargets;
  const groups = dose.groups || [];
  const nU = groups.length;
  const a0 = opt.intakeAge;
  const tEnd = opt.period;
  const pa = dose.phantomAges;
  const icrp103 = dose.interp === 'icrp103';
  const firstYear = pa[0] === 0 && pa[1] === 365 && dose.firstYear !== false;
  const M = icrp103 ? 4 : 2; // basis functions per group

  /* --- the rates, as a function of age ------------------------------------ */
  const tr = sys.transfers.map((x) => ({
    from: x.from, to: x.to,
    ages: x.ages && x.rates.length > 1 ? Float64Array.from(x.ages) : null,
    rates: Float64Array.from(x.rates),
  }));
  const lambda = sys.members.map((m) => m.lambda);
  const decays = sys.decays.map((d) => ({ from: d.from, to: d.to, k: lambda[sys.comps[d.to].member] * d.b }));
  const rateAt = (x, age) => (x.ages ? lerp(x.ages, x.rates, age) : x.rates[0]);

  /* --- the dose groups ------------------------------------------------------ */
  // The compartments of a reported group that share their SEE: by the column
  // array itself, so a caller that gives each compartment its own copy gets
  // a group per compartment, still right.
  const uOf = new Int32Array(n).fill(-1);
  groups.forEach((g, gi) => { for (const c of g) uOf[c] = gi; });
  const any = (cols) => cols.some((col) => col.some((v) => v !== 0));
  const dg = []; // {cols, u, comps}
  const byCols = new Map();
  for (let c = 0; c < n; c++) {
    const cols = dose.columns[c];
    if (uOf[c] < 0 && !any(cols)) continue; // neither dose nor a count to keep
    const by = dose.byCompartment ? c : cols; // a key of its own: a group of its own
    let byU = byCols.get(by);
    if (!byU) byCols.set(by, byU = new Map());
    let g = byU.get(uOf[c]);
    if (g === undefined) { g = dg.length; byU.set(uOf[c], g); dg.push({ cols, u: uOf[c], comps: [] }); }
    dg[g].comps.push(c);
  }
  const G = dg.length;
  const N = n + G * M;
  // PCHIP slopes of each group's SEE over the phantom ages, per target.
  const slopes = icrp103 ? dg.map(({ cols }) => {
    const v = new Float64Array(pa.length), d = new Float64Array(pa.length), out = new Float64Array(pa.length * nT);
    for (let T = 0; T < nT; T++) {
      for (let p = 0; p < pa.length; p++) v[p] = cols[p][T];
      pchipSlopes(pa, v, d);
      for (let p = 0; p < pa.length; p++) out[p * nT + T] = d[p];
    }
    return out;
  }) : null;

  /* --- the sparsity pattern ----------------------------------------------- */
  const I = [], J = [];
  const slot = new Map(); // "i,j" -> triplet position
  const at = (i, j) => {
    const k = `${i},${j}`;
    let p = slot.get(k);
    if (p === undefined) { p = I.length; I.push(i); J.push(j); slot.set(k, p); }
    return p;
  };
  for (let c = 0; c < n; c++) at(c, c);
  const trSlots = tr.map((x) => ({ diag: at(x.from, x.from), off: x.to >= 0 ? at(x.to, x.from) : -1 }));
  const dcSlots = decays.map((d) => at(d.to, d.from));
  const nzA = I.length; // the rates and decays, the diagonal first; the integrals follow
  // Integral j of group g: row n + g*M + j, the basis function's value in the
  // column of each of the group's compartments.
  const basisSlots = Array.from({ length: M }, () => []);
  dg.forEach((g, gi) => { for (let j = 0; j < M; j++) for (const c of g.comps) basisSlots[j].push(at(n + gi * M + j, c)); });
  for (let k = n; k < N; k++) at(k, k); // a zero diagonal keeps every row in the pattern
  const nz = I.length;
  const csc = cscFromTriplets(N, N, Int32Array.from(I), Int32Array.from(J), new Float64Array(nz).fill(1));
  // The integrator takes a pattern as {n, nnz, colPtr, rowIdx}.
  const pattern = { n: N, nnz: csc.nnz, colPtr: csc.colptr, rowIdx: csc.rowind.subarray(0, csc.nnz) };
  // Map each triplet to its place in the CSC value array.
  const pos = new Int32Array(nz);
  for (let p = 0; p < nz; p++) {
    const j = J[p], i = I[p];
    let q = pattern.colPtr[j];
    while (pattern.rowIdx[q] !== i) q++;
    pos[p] = q;
  }
  const basisAt = basisSlots.map((list) => Int32Array.from(list, (p) => pos[p]));

  /* --- a stretch between two kinks ---------------------------------------- */
  // Its SEE: the interval of the phantom ages it lies in and how SEE runs
  // there, and each group's Bernstein coefficients b_j per target.
  const last = pa.length - 1;
  const stretch = { mode: 'linear', kp: 0, h: 0 };
  const coef = new Float64Array(G * nT * M);
  const setStretch = (ageMid) => {
    const [kp] = bracket(pa, ageMid);
    const mode = pa.length > 1 && kp === 0 && firstYear ? 'first'
      : icrp103 && kp > 0 && ageMid < pa[last] ? 'cubic' : 'linear';
    const h = pa.length > 1 ? pa[kp + 1] - pa[kp] : 0;
    Object.assign(stretch, { mode, kp, h });
    const hiP = pa.length > 1 ? kp + 1 : kp;
    coef.fill(0);
    dg.forEach(({ cols }, g) => {
      const lo = cols[kp], hi = cols[hiP];
      for (let T = 0; T < nT; T++) {
        const k = (g * nT + T) * M;
        coef[k] = lo[T];
        coef[k + M - 1] = hi[T];
        if (mode === 'cubic') {
          coef[k + 1] = lo[T] + h * slopes[g][kp * nT + T] / 3;
          coef[k + 2] = hi[T] - h * slopes[g][hiP * nT + T] / 3;
        }
      }
    });
  };
  const B = new Float64Array(M);
  const basis = (age) => {
    if (stretch.mode === 'cubic') {
      const u = (age - pa[stretch.kp]) / stretch.h, v = 1 - u;
      B[0] = v * v * v; B[1] = 3 * u * v * v; B[2] = 3 * u * u * v; B[3] = u * u * u;
      return;
    }
    let w = stretch.mode === 'first' ? firstYearWeight(age) : stretch.h > 0 ? (age - pa[stretch.kp]) / stretch.h : 0;
    w = Math.min(1, Math.max(0, w));
    B.fill(0);
    B[0] = 1 - w;
    B[M - 1] += w;
  };
  // The doses at the end of a part of a stretch, from those at its start and
  // the integrals' growth over it.
  const dosesFrom = (H0, Is, Ie, out) => {
    out.set(H0);
    for (let g = 0; g < G; g++) {
      for (let j = 0; j < M; j++) {
        const dI = Ie[n + g * M + j] - Is[n + g * M + j];
        if (dI === 0) continue;
        const base = g * nT * M + j;
        for (let T = 0; T < nT; T++) out[T] += DAY * coef[base + T * M] * dI;
      }
    }
    return out;
  };
  // The functionals' share of each dose group: per stretch, each functional's
  // weights of the targets applied to the group's coefficients, so that a
  // share grows with the integrals just as the doses do.
  const F = dose.functionals || [];
  const K = F.length;
  const fw = new Float64Array(G * K * M);
  const setShares = () => {
    fw.fill(0);
    for (let g = 0; g < G; g++) {
      for (let k = 0; k < K; k++) {
        const f = F[k];
        for (let j = 0; j < M; j++) {
          let v = 0;
          for (let T = 0; T < nT; T++) if (f[T]) v += f[T] * coef[(g * nT + T) * M + j];
          fw[(g * K + k) * M + j] = v;
        }
      }
    }
  };
  const sharesFrom = (P0, Is, Ie, out) => {
    out.set(P0);
    for (let g = 0; g < G; g++) {
      for (let j = 0; j < M; j++) {
        const dI = Ie[n + g * M + j] - Is[n + g * M + j];
        if (dI === 0) continue;
        for (let k = 0; k < K; k++) out[g * K + k] += DAY * fw[(g * K + k) * M + j] * dI;
      }
    }
    return out;
  };
  // How fast the shares grow at a time: each functional's weights applied to
  // the group's SEE there, times the group's activity, per day.
  const ratesAt = (t, yt, out) => {
    basis(a0 + t);
    for (let g = 0; g < G; g++) {
      let q = 0;
      for (const c of dg[g].comps) q += yt[c];
      for (let k = 0; k < K; k++) {
        let v = 0;
        for (let j = 0; j < M; j++) v += fw[(g * K + k) * M + j] * B[j];
        out[g * K + k] = DAY * v * q;
      }
    }
    return out;
  };
  // The number of transformations in each reported group: the integrals of
  // its dose groups added up (the basis functions add up to one).
  const countsOf = (y, out) => {
    out.fill(0);
    dg.forEach((g, gi) => {
      if (g.u < 0) return;
      for (let j = 0; j < M; j++) out[g.u] += y[n + gi * M + j];
    });
    return out;
  };

  /* --- the matrix at a time ------------------------------------------------ */
  const vals = new Float64Array(nzA); // triplet order
  const cscVals = new Float64Array(pattern.nnz);
  let cachedT = NaN;
  const build = (t) => {
    if (t === cachedT) return;
    cachedT = t;
    vals.fill(0);
    const age = a0 + t;
    for (let c = 0; c < n; c++) vals[c] = -lambda[sys.comps[c].member]; // diagonal slots come first
    for (let k = 0; k < tr.length; k++) {
      const r = rateAt(tr[k], age);
      if (!r) continue;
      vals[trSlots[k].diag] -= r;
      if (trSlots[k].off >= 0) vals[trSlots[k].off] += r;
    }
    for (let k = 0; k < decays.length; k++) vals[dcSlots[k]] += decays[k].k;
    for (let p = 0; p < nzA; p++) cscVals[pos[p]] = vals[p];
    basis(age);
    for (let j = 0; j < M; j++) {
      const v = B[j], list = basisAt[j];
      for (let k = 0; k < list.length; k++) cscVals[list[k]] = v;
    }
  };

  const f = (t, y, out) => {
    build(t);
    out.fill(0);
    // y' = M y, column by column.
    const { colPtr, rowIdx } = pattern;
    for (let j = 0; j < N; j++) {
      const yj = y[j];
      if (yj === 0) continue;
      for (let q = colPtr[j]; q < colPtr[j + 1]; q++) out[rowIdx[q]] += cscVals[q] * yj;
    }
    return out;
  };
  const jacobian = { pattern, evaluate: (t) => { build(t); return cscVals; } };

  /* --- integrate stretch by stretch ---------------------------------------- */
  const kinks = new Set([0, tEnd]);
  const addKink = (age) => { const t = age - a0; if (t > 0 && t < tEnd) kinks.add(t); };
  for (const x of tr) if (x.ages) x.ages.forEach(addKink);
  pa.forEach(addKink);
  const breaks = [...kinks].sort((p, q) => p - q);
  const outputs = (opt.outputs || []).filter((t) => t > 0 && t < tEnd).sort((p, q) => p - q);

  const y = new Float64Array(N);
  for (const [c, v] of sys.init) y[c] += v;
  const abstol = new Float64Array(N);
  abstol.fill(opt.atolQ ?? 1e-14, 0, n);
  abstol.fill(opt.atolI ?? 1e-14, n, N);
  const H = new Float64Array(nT), Hpart = new Float64Array(nT), U = new Float64Array(nU);
  const P = new Float64Array(G * K), Ppart = new Float64Array(G * K);
  // The series in the shape it always had: activities, doses, transformations / 86400;
  // and the functionals' shares and their rates, when asked for.
  const point = (t, yt, Ht, Pt) => {
    const v = new Float64Array(n + nT + nU);
    v.set(yt.subarray(0, n));
    v.set(Ht, n);
    countsOf(yt, U);
    v.set(U, n + nT);
    return K ? { t, y: v, parts: Float64Array.from(Pt), rates: new Float64Array(G * K) } : { t, y: v };
  };
  const series = [point(0, y, H, P)];
  const stats = { steps: 0, segments: 0, failed: 0, equations: N, nonzeros: pattern.nnz };
  for (let s = 0; s + 1 < breaks.length; s++) {
    const t0 = breaks[s], t1 = breaks[s + 1];
    setStretch(a0 + (t0 + t1) / 2);
    if (K) setShares();
    if (K && s === 0) ratesAt(0, y, series[0].rates);
    cachedT = NaN; // the same time in a new stretch is another matrix
    const y0 = Float64Array.from(y);
    const span = [t0, ...outputs.filter((t) => t > t0 && t < t1), t1];
    const res = ndf(f, span, y, {
      rtol: opt.rtol ?? 1e-6, abstol, jacobian, maxOrder: 5,
      hmax: Math.max(t1 - t0, 1e-9), maxSteps: 2e5, denseBelow: 0,
    });
    for (let k = 1; k < res.t.length; k++) {
      const p = point(res.t[k], res.y[k], dosesFrom(H, y0, res.y[k], Hpart), K ? sharesFrom(P, y0, res.y[k], Ppart) : P);
      if (K) ratesAt(res.t[k], res.y[k], p.rates);
      series.push(p);
    }
    y.set(res.y[res.y.length - 1]);
    dosesFrom(H, y0, y, Hpart);
    H.set(Hpart);
    if (K) { sharesFrom(P, y0, y, Ppart); P.set(Ppart); }
    stats.steps += res.stats?.nsteps ?? 0;
    stats.failed += res.stats?.nfailed ?? 0;
    stats.segments++;
  }
  countsOf(y, U);
  return {
    H: Float64Array.from(H),                // Sv per Bq intake
    U: Array.from(U, (v) => v * DAY),       // transformations per Bq intake
    q: Float64Array.from(y.subarray(0, n)),
    series, stats,
    doseGroups: dg.map((g) => ({ member: sys.comps[g.comps[0]].member, region: sys.comps[g.comps[0]].region, kind: sys.comps[g.comps[0]].kind, comps: g.comps })),
    parts: K ? Float64Array.from(P) : null,
  };
}
