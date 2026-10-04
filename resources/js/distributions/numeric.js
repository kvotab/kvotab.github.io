/* ==========================================================================
   distributions.html: ROOTS, MINIMA AND INTEGRALS

   The numerical tools the distributions fall back on where a formula runs
   out: Brent's root finder and minimiser, Nelder-Mead for several
   parameters, Newton's method for a square system, adaptive Gauss-Kronrod
   quadrature on a finite interval, and tanh-sinh quadrature over (0, 1),
   which copes with the endpoint singularities of an integral over a
   quantile function.
   ========================================================================== */

import { EPS } from './special.js';

/* ---- one variable --------------------------------------------------------- */

/**
 * A root of f between a and b, where f(a) and f(b) differ in sign
 * (Brent 1973, the zeroin algorithm). Returns NaN if they do not.
 */
export function brentRoot(f, a, b, opts = {}) {
  const xtol = opts.xtol ?? 0;
  const rtol = opts.rtol ?? 4 * EPS;
  const maxIter = opts.maxIter ?? 200;
  let fa = opts.fa ?? f(a);
  let fb = opts.fb ?? f(b);
  if (fa === 0) return a;
  if (fb === 0) return b;
  if (!((fa < 0 && fb > 0) || (fa > 0 && fb < 0))) return NaN;
  let c = a;
  let fc = fa;
  let d = b - a;
  let e = d;
  for (let it = 0; it < maxIter; it++) {
    if ((fb > 0 && fc > 0) || (fb < 0 && fc < 0)) {
      c = a; fc = fa; d = b - a; e = d;
    }
    if (Math.abs(fc) < Math.abs(fb)) {
      a = b; b = c; c = a;
      fa = fb; fb = fc; fc = fa;
    }
    const tol = 2 * rtol * Math.abs(b) + 0.5 * xtol;
    const m = 0.5 * (c - b);
    if (Math.abs(m) <= tol || fb === 0) return b;
    if (Math.abs(e) >= tol && Math.abs(fa) > Math.abs(fb)) {
      let p;
      let q;
      const s = fb / fa;
      if (a === c) {
        p = 2 * m * s;
        q = 1 - s;
      } else {
        const qq = fa / fc;
        const r = fb / fc;
        p = s * (2 * m * qq * (qq - r) - (b - a) * (r - 1));
        q = (qq - 1) * (r - 1) * (s - 1);
      }
      if (p > 0) q = -q; else p = -p;
      if (2 * p < Math.min(3 * m * q - Math.abs(tol * q), Math.abs(e * q))) {
        e = d;
        d = p / q;
      } else {
        d = m;
        e = m;
      }
    } else {
      d = m;
      e = m;
    }
    a = b;
    fa = fb;
    b += Math.abs(d) > tol ? d : (m > 0 ? tol : -tol);
    fb = f(b);
    if (Number.isNaN(fb)) return NaN;
  }
  return b;
}

/**
 * A root of an increasing function f, searched for outwards from x0 by
 * doubling steps until it is bracketed, within [lo, hi] (either infinite).
 */
export function rootIncreasing(f, x0, lo = -Infinity, hi = Infinity, scale = 1) {
  let a = x0;
  let fa = f(a);
  if (fa === 0) return a;
  let step = Math.max(Math.abs(scale), 1e-300);
  let b = a;
  let fb = fa;
  for (let i = 0; i < 2000; i++) {
    if (fa < 0) {
      b = a + step;
      if (b >= hi) b = Number.isFinite(hi) ? hi : b;
    } else {
      b = a - step;
      if (b <= lo) b = Number.isFinite(lo) ? lo : b;
    }
    fb = f(b);
    if (fb === 0 || (fa < 0) !== (fb < 0)) break;
    if (b === a) return a;
    a = b;
    fa = fb;
    step *= 2;
  }
  if (fb === 0) return b;
  return brentRoot(f, Math.min(a, b), Math.max(a, b),
    a < b ? { fa, fb } : { fa: fb, fb: fa });
}

/**
 * The minimum of f on [a, b] (Brent's parabolic interpolation with golden
 * sections). Returns { x, f }.
 */
export function brentMin(f, a, b, opts = {}) {
  const tol = opts.tol ?? 1e-10;
  const maxIter = opts.maxIter ?? 200;
  const cgold = 0.3819660112501051;
  let x = opts.x0 !== undefined ? opts.x0 : a + cgold * (b - a);
  let w = x;
  let v = x;
  let fx = f(x);
  let fw = fx;
  let fv = fx;
  let d = 0;
  let e = 0;
  for (let it = 0; it < maxIter; it++) {
    const xm = 0.5 * (a + b);
    const tol1 = tol * Math.abs(x) + 1e-300;
    const tol2 = 2 * tol1;
    if (Math.abs(x - xm) <= tol2 - 0.5 * (b - a)) break;
    let useGolden = true;
    if (Math.abs(e) > tol1) {
      let r = (x - w) * (fx - fv);
      let q = (x - v) * (fx - fw);
      let p = (x - v) * q - (x - w) * r;
      q = 2 * (q - r);
      if (q > 0) p = -p;
      q = Math.abs(q);
      const etemp = e;
      e = d;
      if (!(Math.abs(p) >= Math.abs(0.5 * q * etemp) || p <= q * (a - x) || p >= q * (b - x))) {
        d = p / q;
        const u = x + d;
        if (u - a < tol2 || b - u < tol2) d = xm - x >= 0 ? tol1 : -tol1;
        useGolden = false;
      }
    }
    if (useGolden) {
      e = x >= xm ? a - x : b - x;
      d = cgold * e;
    }
    const u = Math.abs(d) >= tol1 ? x + d : x + (d >= 0 ? tol1 : -tol1);
    const fu = f(u);
    if (fu <= fx) {
      if (u >= x) a = x; else b = x;
      v = w; fv = fw;
      w = x; fw = fx;
      x = u; fx = fu;
    } else {
      if (u < x) a = u; else b = u;
      if (fu <= fw || w === x) {
        v = w; fv = fw;
        w = u; fw = fu;
      } else if (fu <= fv || v === x || v === w) {
        v = u; fv = fu;
      }
    }
  }
  return { x, f: fx };
}

/* ---- several variables ------------------------------------------------------- */

/**
 * Nelder-Mead minimisation of f over R^n from x0. Values that are not
 * finite count as +Infinity, so a constraint can be written as "return
 * Infinity". The coefficients adapt to the dimension (Gao and Han 2012),
 * and the search restarts once from where it stopped, which catches a
 * simplex that collapsed early.
 *
 * @returns {{x: number[], f: number, iterations: number, converged: boolean}}
 */
export function nelderMead(f, x0, opts = {}) {
  const n = x0.length;
  const ftol = opts.ftol ?? 1e-12;
  const xtol = opts.xtol ?? 1e-10;
  const maxIter = opts.maxIter ?? 400 * n;
  const restarts = opts.restarts ?? 1;
  const fv = (x) => {
    const y = f(x);
    return Number.isFinite(y) ? y : Infinity;
  };
  const alpha = 1;
  const beta = n >= 3 ? 1 + 2 / n : 2;
  const gamma = n >= 3 ? 0.75 - 1 / (2 * n) : 0.5;
  const delta = n >= 3 ? 1 - 1 / n : 0.5;
  let best = { x: x0.slice(), f: fv(x0) };
  let total = 0;
  let converged = false;
  for (let round = 0; round <= restarts; round++) {
    const start = best.x;
    const steps = opts.steps || start.map((v) => (Math.abs(v) > 1e-8 ? 0.1 * Math.abs(v) : 0.1));
    const simplex = [{ x: start.slice(), f: best.f }];
    for (let i = 0; i < n; i++) {
      const x = start.slice();
      x[i] += steps[i] * (round ? 0.5 : 1);
      let fx = fv(x);
      if (fx === Infinity) {
        x[i] = start[i] - steps[i] * (round ? 0.5 : 1);
        fx = fv(x);
      }
      simplex.push({ x, f: fx });
    }
    converged = false;
    for (let it = 0; it < maxIter; it++, total++) {
      simplex.sort((p, q) => p.f - q.f);
      const fBest = simplex[0].f;
      const fWorst = simplex[n].f;
      let size = 0;
      for (let i = 1; i <= n; i++) {
        for (let j = 0; j < n; j++) {
          size = Math.max(size, Math.abs(simplex[i].x[j] - simplex[0].x[j]) / (Math.abs(simplex[0].x[j]) + 1e-8));
        }
      }
      if (Math.abs(fWorst - fBest) <= ftol * (Math.abs(fBest) + 1e-30) && size <= xtol) { converged = true; break; }
      if (fBest === Infinity) break;
      const centroid = new Array(n).fill(0);
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) centroid[j] += simplex[i].x[j] / n;
      const worst = simplex[n];
      const at = (t) => centroid.map((c, j) => c + t * (worst.x[j] - c));
      const xr = at(-alpha);
      const fr = fv(xr);
      if (fr < simplex[0].f) {
        const xe = at(-alpha * beta);
        const fe = fv(xe);
        simplex[n] = fe < fr ? { x: xe, f: fe } : { x: xr, f: fr };
      } else if (fr < simplex[n - 1].f) {
        simplex[n] = { x: xr, f: fr };
      } else {
        const outside = fr < worst.f;
        const xc = outside ? at(-alpha * gamma) : at(gamma);
        const fc = fv(xc);
        if (fc < (outside ? fr : worst.f)) {
          simplex[n] = { x: xc, f: fc };
        } else {
          for (let i = 1; i <= n; i++) {
            const x = simplex[i].x.map((v, j) => simplex[0].x[j] + delta * (v - simplex[0].x[j]));
            simplex[i] = { x, f: fv(x) };
          }
        }
      }
    }
    simplex.sort((p, q) => p.f - q.f);
    const improved = simplex[0].f < best.f;
    if (simplex[0].f <= best.f) best = { x: simplex[0].x.slice(), f: simplex[0].f };
    if (round > 0 && !improved) break;
  }
  return { x: best.x, f: best.f, iterations: total, converged };
}

/**
 * Newton's method with a finite-difference Jacobian for F(z) = 0, F from
 * R^n to R^n, with step halving while the residual grows.
 *
 * @returns {{x: number[], norm: number}}
 */
export function newtonSystem(F, z0, opts = {}) {
  const n = z0.length;
  const maxIter = opts.maxIter ?? 50;
  const tol = opts.tol ?? 1e-13;
  let z = z0.slice();
  let r = F(z);
  let norm = Math.hypot(...r);
  for (let it = 0; it < maxIter && Number.isFinite(norm) && norm > tol; it++) {
    const J = [];
    for (let j = 0; j < n; j++) {
      const h = 1e-7 * Math.max(Math.abs(z[j]), 1e-3);
      const zp = z.slice();
      zp[j] += h;
      const rp = F(zp);
      for (let i = 0; i < n; i++) {
        if (!J[i]) J[i] = new Array(n);
        J[i][j] = (rp[i] - r[i]) / h;
      }
    }
    const step = solveLinear(J, r.map((v) => -v));
    if (!step) break;
    let t = 1;
    let accepted = false;
    for (let k = 0; k < 30; k++) {
      const zn = z.map((v, j) => v + t * step[j]);
      const rn = F(zn);
      const nn = Math.hypot(...rn);
      if (Number.isFinite(nn) && nn < norm) {
        z = zn; r = rn; norm = nn;
        accepted = true;
        break;
      }
      t *= 0.5;
    }
    if (!accepted) break;
  }
  return { x: z, norm };
}

/** Gaussian elimination with partial pivoting; null if singular. */
export function solveLinear(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let piv = col;
    for (let i = col + 1; i < n; i++) if (Math.abs(M[i][col]) > Math.abs(M[piv][col])) piv = i;
    if (!(Math.abs(M[piv][col]) > 1e-300)) return null;
    [M[col], M[piv]] = [M[piv], M[col]];
    for (let i = col + 1; i < n; i++) {
      const fct = M[i][col] / M[col][col];
      for (let j = col; j <= n; j++) M[i][j] -= fct * M[col][j];
    }
  }
  const x = new Array(n);
  for (let i = n - 1; i >= 0; i--) {
    let s = M[i][n];
    for (let j = i + 1; j < n; j++) s -= M[i][j] * x[j];
    x[i] = s / M[i][i];
  }
  return x;
}

/** The inverse of a small symmetric matrix, or null. */
export function invertMatrix(A) {
  const n = A.length;
  const cols = [];
  for (let j = 0; j < n; j++) {
    const e = new Array(n).fill(0);
    e[j] = 1;
    const c = solveLinear(A, e);
    if (!c) return null;
    cols.push(c);
  }
  return A.map((_, i) => cols.map((c) => c[i]));
}

/**
 * The Hessian of f at x by central differences, with steps scaled to each
 * coordinate.
 */
export function hessian(f, x, rel = 1e-4) {
  const n = x.length;
  const h = Array.isArray(rel) ? rel.slice() : x.map((v) => rel * Math.max(Math.abs(v), 1e-2));
  const f0 = f(x);
  const H = Array.from({ length: n }, () => new Array(n).fill(0));
  const at = (di, si, dj, sj) => {
    const y = x.slice();
    y[di] += si * h[di];
    if (dj >= 0) y[dj] += sj * h[dj];
    return f(y);
  };
  for (let i = 0; i < n; i++) {
    H[i][i] = (at(i, 1, -1, 0) - 2 * f0 + at(i, -1, -1, 0)) / (h[i] * h[i]);
    for (let j = 0; j < i; j++) {
      const v = (at(i, 1, j, 1) - at(i, 1, j, -1) - at(i, -1, j, 1) + at(i, -1, j, -1)) / (4 * h[i] * h[j]);
      H[i][j] = v;
      H[j][i] = v;
    }
  }
  return H;
}

/* ---- integrals -------------------------------------------------------------------- */

const GK_X = [0.991455371120812639206854697526329, 0.949107912342758524526189684047851,
  0.864864423359769072789712788640926, 0.741531185599394439863864773280788,
  0.586087235467691130294144845693013, 0.405845151377397166906606412076961,
  0.207784955007898467600689403773245, 0];
const GK_WK = [0.022935322010529224963732008058970, 0.063092092629978553290700663189204,
  0.104790010322250183839876322541518, 0.140653259715525918745189590510238,
  0.169004726639267902826583426598550, 0.190350578064785409913256402421014,
  0.204432940075298892414161999234649, 0.209482141084727828012999174891714];
const GK_WG = [0, 0.129484966168869693270611432679082, 0, 0.279705391489276667901467771423780,
  0, 0.381830050505118944950369775488975, 0, 0.417959183673469387755102040816327];

function gk15(f, a, b) {
  const c = 0.5 * (a + b);
  const h = 0.5 * (b - a);
  const fc = f(c);
  let k = fc * GK_WK[7];
  let g = fc * GK_WG[7];
  for (let i = 0; i < 7; i++) {
    const dx = h * GK_X[i];
    const s = f(c - dx) + f(c + dx);
    k += GK_WK[i] * s;
    g += GK_WG[i] * s;
  }
  return { value: k * h, error: Math.abs((k - g) * h) };
}

/**
 * The integral of f over [a, b] by adaptive Gauss-Kronrod (7-15), always
 * splitting the interval with the largest error estimate.
 */
export function integrate(f, a, b, opts = {}) {
  if (a === b) return 0;
  if (a > b) return -integrate(f, b, a, opts);
  const atol = opts.atol ?? 1e-13;
  const rtol = opts.rtol ?? 1e-10;
  const maxIntervals = opts.maxIntervals ?? 400;
  const first = gk15(f, a, b);
  const pieces = [{ a, b, ...first }];
  let total = first.value;
  let error = first.error;
  while (error > Math.max(atol, rtol * Math.abs(total)) && pieces.length < maxIntervals) {
    let worst = 0;
    for (let i = 1; i < pieces.length; i++) if (pieces[i].error > pieces[worst].error) worst = i;
    const p = pieces[worst];
    const m = 0.5 * (p.a + p.b);
    if (m <= p.a || m >= p.b) break;
    const left = gk15(f, p.a, m);
    const right = gk15(f, m, p.b);
    pieces.splice(worst, 1, { a: p.a, b: m, ...left }, { a: m, b: p.b, ...right });
    total = 0;
    error = 0;
    for (const q of pieces) { total += q.value; error += q.error; }
  }
  return total;
}

/**
 * The integral over (0, 1) of f(u, 1 - u) by tanh-sinh quadrature. f gets
 * both u and its complement, computed separately, so that a quantile
 * function can use its upper-tail form near 1 where 1 - u is not
 * representable. Endpoint singularities that are integrable (a quantile
 * function at 0 or 1, a logarithm) are what the method is for.
 */
export function integrate01(f, opts = {}) {
  const rtol = opts.rtol ?? 1e-11;
  const maxLevel = opts.maxLevel ?? 9;
  /* At t = 6 the points are 1e-275 from the ends: far enough for a heavy
     tail's share of a moment, and still a double. */
  const tmax = opts.tmax ?? 6;
  let h = 0.5;
  let sum = (Math.PI / 4) * f(0.5, 0.5);
  const term = (t) => {
    const s = 0.5 * Math.PI * Math.sinh(t);
    const e = Math.exp(-2 * s);
    const small = e / (1 + e);   // the point near 0; its partner near 1 is 1 - small
    if (small === 0) return 0;
    const large = 1 / (1 + e);
    const w = Math.PI * Math.cosh(t) * e / ((1 + e) * (1 + e));
    const v = w * (f(small, large) + f(large, small));
    return Number.isFinite(v) ? v : 0;
  };
  for (let k = 1; k * h <= tmax; k++) sum += term(k * h);
  let estimate = sum * h;
  for (let level = 1; level <= maxLevel; level++) {
    h /= 2;
    let add = 0;
    for (let k = 1; k * h <= tmax; k += 2) add += term(k * h);
    sum += add;
    const next = sum * h;
    const done = Math.abs(next - estimate) <= rtol * Math.abs(next);
    estimate = next;
    if (done) break;
  }
  return estimate;
}

/**
 * integrate01 for a vector of integrands at once: f(u, 1 - u) returns an
 * array, every element of which is integrated over (0, 1). The levels are
 * refined until every element has settled (relative to the largest of its
 * own magnitude and `scale[i]`). `breaks` splits (0, 1) where the integrand
 * has a kink or a jump (a quantile function at a density's corner), so that
 * each piece is smooth inside, which is what the method needs.
 */
export function integrate01Vec(f, dims, opts = {}) {
  const rtol = opts.rtol ?? 1e-10;
  const maxLevel = opts.maxLevel ?? 8;
  const tmax = opts.tmax ?? 6;
  const scale = opts.scale || new Array(dims).fill(0);
  const cuts = [0, ...(opts.breaks || []).filter((b) => b > 1e-12 && b < 1 - 1e-12).sort((a, b) => a - b), 1];
  const pieces = [];
  for (let i = 0; i + 1 < cuts.length; i++) if (cuts[i + 1] > cuts[i]) pieces.push([cuts[i], cuts[i + 1]]);
  let h = 0.5;
  const sum = new Float64Array(dims);
  const add = (vals, w) => {
    for (let i = 0; i < dims; i++) {
      const v = w * vals[i];
      if (Number.isFinite(v)) sum[i] += v;
    }
  };
  /* a node t of (0, 1) and its complement, in each piece [a, b] */
  const at = (t, tc, w) => {
    for (const [a, b] of pieces) {
      const len = b - a;
      add(f(a + len * t, (1 - b) + len * tc), w * len);
    }
  };
  at(0.5, 0.5, Math.PI / 4);
  const term = (t) => {
    const s = 0.5 * Math.PI * Math.sinh(t);
    const e = Math.exp(-2 * s);
    const small = e / (1 + e);
    if (small === 0) return;
    const large = 1 / (1 + e);
    const w = Math.PI * Math.cosh(t) * e / ((1 + e) * (1 + e));
    at(small, large, w);
    at(large, small, w);
  };
  for (let k = 1; k * h <= tmax; k++) term(k * h);
  let estimate = Array.from(sum, (v) => v * h);
  for (let level = 1; level <= maxLevel; level++) {
    h /= 2;
    for (let k = 1; k * h <= tmax; k += 2) term(k * h);
    const next = Array.from(sum, (v) => v * h);
    let done = true;
    for (let i = 0; i < dims; i++) {
      if (Math.abs(next[i] - estimate[i]) > rtol * Math.max(Math.abs(next[i]), scale[i])) done = false;
    }
    estimate = next;
    if (done && level >= 2) break;
  }
  return estimate;
}
