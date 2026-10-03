/* ==========================================================================
   ode_julia / core / krylov

   GMRES, and the matrix-free W that the Krylov FBDF solves its Newton
   iterations with -- what OrdinaryDiffEq does with
   FBDF(linsolve = KrylovJL_GMRES()), which is the stiff method its default
   algorithm takes for a system of more than 500 states.

   No matrix is formed at all. W·v needs J·v, and that is a directional
   difference of f at the current Newton iterate,

       J·v ≈ (f(z + ε·v) − f(z)) / ε,   ε = max(√eps·‖z‖, √eps) / ‖v‖

   (FiniteDiff.jl's jvp step, which DifferentiationInterface uses for
   AutoFiniteDiff), unless the problem supplies its own `jvp`. Each GMRES
   iteration costs one evaluation of f, and the linearisation point moves
   with every Newton iteration: it is a Newton method, not the simplified one
   the factorising methods use.

   How it is solved follows the pieces OrdinaryDiffEq stacks, each from its
   source:

     the system     Julia's W = J − I/(γh) against its residual, which is
                    this package's (I − γh·J) and residual divided through by
                    −γh (see `KrylovW.solve`); the scaling matters, because
                    GMRES's absolute tolerance is not scale-free
     weighting      a diagonal scaling on both sides by the error weights,
                    wᵢ = 1/(abstolᵢ + reltol·max(|uprevᵢ|, |uᵢ|)): OrdinaryDiffEq's
                    wrapprecs, M = InvPreconditioner(Diagonal(w)) on the left
                    and N = Diagonal(w) on the right, which Krylov.jl applies
                    with ldiv, so the residual is measured as w∘r
     tolerances     rtol = the integration's reltol (OrdinaryDiffEq's
                    dolinsolve), atol = √eps (LinearSolve's default), at most
                    n iterations (LinearSolve's maxiters), never restarted
                    (gmres_restart = 0)
     warm start     the previous solution, rescaled by Hegedüs's trick and
                    used only when it at least halves the residual
                    (LinearSolve's WarmStart.Hegedus, which OrdinaryDiffEq
                    selects on its Newton path), with the stopping threshold
                    kept at the cold start's
     the iteration  Krylov.jl's gmres!: modified Gram-Schmidt, Givens
                    rotations from sym_givens, a breakdown tolerance of
                    eps^(3/4)

   One deliberate difference: the basis is never let grow past 256 MB (the
   dense-matrix cap of ../../core), which on a system of 50 000 states is 670
   vectors where Julia would allow 50 000 and run out of memory first. A
   solve that reaches the cap fails as one that reaches its iteration limit
   does, and the Newton iteration treats it as divergence.

   Licence. GMRES and symGivens are a port of Krylov.jl's gmres! and
   sym_givens, https://github.com/JuliaSmoothOptimizers/Krylov.jl, Copyright
   (c) 2015-present: Alexis Montoison, Dominique Orban, and other
   contributors, which is licensed under the Mozilla Public License 2.0; so,
   unlike the rest of this package (../LICENSE), is this file:

   This Source Code Form is subject to the terms of the Mozilla Public
   License, v. 2.0. If a copy of the MPL was not distributed with this file,
   You can obtain one at https://mozilla.org/MPL/2.0/.
   ========================================================================== */

const JVP_SQRT_EPS = Math.sqrt(Number.EPSILON);
const BTOL = Number.EPSILON ** 0.75;
const BASIS_MAX_BYTES = 256 * 1024 * 1024;
// LinearSolve's Hegedüs acceptance: the guess must at least halve the residual.
const HEGEDUS_MIN_COSINE = Math.sqrt(1 - 0.5 ** 2);

/**
 * Krylov.jl's sym_givens for real a, b: (c, s, ρ) with [c s; s −c]·[a; b] = [ρ; 0].
 * Written into `out` to keep the inner loop free of allocation.
 */
export function symGivens(a, b, out) {
  let c; let s; let rho;
  if (b === 0) {
    c = a === 0 ? 1 : Math.sign(a);
    s = 0;
    rho = Math.abs(a);
  } else if (a === 0) {
    c = 0;
    s = Math.sign(b);
    rho = Math.abs(b);
  } else if (Math.abs(b) > Math.abs(a)) {
    const t = a / b;
    s = Math.sign(b) / Math.sqrt(1 + t * t);
    c = s * t;
    rho = b / s;
  } else {
    const t = b / a;
    c = Math.sign(a) / Math.sqrt(1 + t * t);
    s = c * t;
    rho = a / c;
  }
  out[0] = c; out[1] = s; out[2] = rho;
  return out;
}

function dot(n, x, y) {
  let s = 0;
  for (let i = 0; i < n; i++) s += x[i] * y[i];
  return s;
}

function norm2(n, x) {
  return Math.sqrt(dot(n, x, x));
}

/**
 * GMRES without restarts, as Krylov.jl's gmres! with restart = false.
 *
 * The basis grows as it is needed, from `memory` vectors up to `maxBasis`.
 */
export class GMRES {
  constructor(n, opts = {}) {
    this.n = n;
    this.memory = Math.min(opts.memory ?? 20, n);
    this.maxBasis = Math.max(this.memory,
      Math.floor((opts.maxBytes ?? BASIS_MAX_BYTES) / (8 * Math.max(1, n))));
    this.V = [];
    this.R = [];
    this.c = [];
    this.s = [];
    this.z = [];
    this.w = new Float64Array(n);
    this.q = new Float64Array(n);
    this.p = new Float64Array(n);
    this.dx = new Float64Array(n);
    this.g = new Float64Array(3);
    this.stats = { niter: 0, solved: false, status: '', rNorm: 0 };
  }

  basis(k) {
    while (this.V.length <= k) this.V.push(new Float64Array(this.n));
    return this.V[k];
  }

  /**
   * Solve A·x = b.
   *
   * @param {(v:Float64Array, out:Float64Array)=>void} A
   * @param {Float64Array} b
   * @param {Float64Array} x       the answer, written in place
   * @param {object} o
   * @param {Float64Array} [o.left]   a diagonal left preconditioner, applied as
   *        M⁻¹·v = left∘v (OrdinaryDiffEq's InvPreconditioner(Diagonal(w)), ldiv'd)
   * @param {Float64Array} [o.right]  a diagonal right one, applied as
   *        N⁻¹·v = v/right (Diagonal(w), ldiv'd)
   * @param {Float64Array|null} [o.x0]  a warm start, already chosen
   * @param {number} o.atol
   * @param {number} o.rtol
   * @param {number} [o.itmax]  0 means 2n, as Krylov.jl
   * @returns {{niter:number, solved:boolean, status:string, rNorm:number}}
   */
  solve(A, b, x, o) {
    const n = this.n;
    const { w, q, dx, g } = this;
    const { V, R, c, s, z } = this;
    const left = o.left || null;     // r ↦ left∘r   (M⁻¹)
    const right = o.right || null;   // v ↦ v/right  (N⁻¹)
    const warm = !!o.x0;
    const stats = this.stats;

    x.fill(0);
    if (warm) {
      dx.set(o.x0);
      A(dx, w);
      for (let i = 0; i < n; i++) w[i] = b[i] - w[i];
    } else {
      w.set(b);
    }
    const r0 = q;
    if (left) for (let i = 0; i < n; i++) r0[i] = left[i] * w[i];
    else r0.set(w);
    const beta = norm2(n, r0);
    let rNorm = beta;
    const eps = o.atol + o.rtol * rNorm;

    if (beta === 0) {
      if (warm) for (let i = 0; i < n; i++) x[i] += dx[i];
      stats.niter = 0; stats.solved = true; stats.status = 'x is a zero-residual solution'; stats.rNorm = 0;
      return stats;
    }

    let itmax = o.itmax > 0 ? o.itmax : 2 * n;
    itmax = Math.min(itmax, this.maxBasis);
    const capped = itmax === this.maxBasis && (o.itmax > 0 ? o.itmax : 2 * n) > this.maxBasis;

    let solved = rNorm <= eps;
    let breakdown = false;
    let inconsistent = false;
    let k = 0;               // inner iterations
    let nr = 0;              // coefficients stored in R
    R.length = 0; c.length = 0; s.length = 0; z.length = 0;

    if (!solved) {
      z.push(beta);
      const v0 = this.basis(0);
      for (let i = 0; i < n; i++) v0[i] = r0[i] / rNorm;
      const p = this.p;
      for (;;) {
        k++;
        const vk = V[k - 1];
        let pv = vk;
        if (right) { for (let i = 0; i < n; i++) p[i] = vk[i] / right[i]; pv = p; }
        A(pv, w);
        if (left) for (let i = 0; i < n; i++) q[i] = left[i] * w[i];
        else q.set(w);
        for (let i = 0; i < k; i++) {
          const h = dot(n, V[i], q);
          R.push(h);
          const vi = V[i];
          for (let m = 0; m < n; m++) q[m] -= h * vi[m];
        }
        const hbis = norm2(n, q);
        // The previous rotations, then this column's own.
        for (let i = 0; i < k - 1; i++) {
          const a1 = R[nr + i];
          const a2 = R[nr + i + 1];
          R[nr + i] = c[i] * a1 + s[i] * a2;
          R[nr + i + 1] = s[i] * a1 - c[i] * a2;
        }
        symGivens(R[nr + k - 1], hbis, g);
        c.push(g[0]); s.push(g[1]); R[nr + k - 1] = g[2];
        const zeta = s[k - 1] * z[k - 1];
        z[k - 1] = c[k - 1] * z[k - 1];
        rNorm = Math.abs(zeta);
        nr += k;

        solved = rNorm <= eps;
        breakdown = hbis <= BTOL;
        const tired = k >= itmax;
        if (solved || tired || breakdown || !Number.isFinite(rNorm)) break;
        const next = this.basis(k);
        for (let i = 0; i < n; i++) next[i] = q[i] / hbis;
        z.push(zeta);
      }

      // y from R·y = z by back substitution, in Krylov.jl's packed indexing
      // (1-based positions, column after column).
      const y = z;
      for (let i = k; i >= 1; i--) {
        let pos = nr + i - k;
        for (let j = k; j >= i + 1; j--) {
          y[i - 1] -= R[pos - 1] * y[j - 1];
          pos = pos - j + 1;
        }
        if (Math.abs(R[pos - 1]) <= BTOL) {
          y[i - 1] = 0;
          inconsistent = true;
        } else {
          y[i - 1] /= R[pos - 1];
        }
      }
      for (let i = 0; i < k; i++) {
        const yi = y[i];
        const vi = V[i];
        for (let m = 0; m < n; m++) x[m] += yi * vi[m];
      }
      if (right) for (let i = 0; i < n; i++) x[i] /= right[i];
    }
    if (warm) for (let i = 0; i < n; i++) x[i] += dx[i];

    stats.niter = k;
    stats.solved = solved;
    stats.rNorm = rNorm;
    stats.status = solved
      ? (inconsistent ? 'found approximate least-squares solution' : 'solution good enough given atol and rtol')
      : capped && k >= itmax ? 'the basis reached its memory cap'
        : k >= itmax ? 'maximum number of iterations exceeded'
          : breakdown ? 'breakdown' : 'not a number';
    return stats;
  }
}

/**
 * The matrix-free W of the Krylov FBDF, with the `solve(b)` the Newton
 * iteration calls.
 *
 * The Newton iteration (../core/newton.js) tells it where it is before every
 * solve -- `setPoint(t, z, f(z), γh)` -- and hands it this package's
 * right-hand side, `(I − γh·J)·dz = b`. OrdinaryDiffEq solves
 * `(J − I/(γh))·x = b/(γh)` instead and steps by −x; that is the same
 * equation, and solving it in that form keeps GMRES's absolute tolerance
 * meaning what it means there.
 */
export class KrylovW {
  constructor(n, integ, opts = {}) {
    this.n = n;
    this.integ = integ;
    this.gmres = new GMRES(n, { memory: opts.krylovMemory, maxBytes: opts.krylovMaxBytes });
    this.weight = new Float64Array(n);
    this.bj = new Float64Array(n);
    this.x = new Float64Array(n);
    this.xPrev = new Float64Array(n);
    this.havePrev = false;
    this.Au = new Float64Array(n);
    this.zpert = new Float64Array(n);
    this.fpert = new Float64Array(n);
    this.t = 0;
    this.z = null;
    this.fz = null;
    this.gammaDt = 1;
    this.zNorm = 0;
    // Counted work: solves, GMRES iterations, products J·v, failed solves.
    this.nsolve = 0;
    this.niter = 0;
    this.njvp = 0;
    this.nfail = 0;
    this.warmStarts = 0;
    this.apply = (v, out) => this.applyW(v, out);
  }

  /** The error weights for this step, as OrdinaryDiffEq's Newton initialize! sets them. */
  prepare(integ) {
    const n = this.n;
    const { uprev, u } = integ;
    const at = integ.abstolFixed;
    const scalar = typeof at === 'number';
    const rtol = integ.reltol;
    for (let i = 0; i < n; i++) {
      const w = (scalar ? at : at[i]) + rtol * Math.max(Math.abs(uprev[i]), Math.abs(u[i]));
      // A weight that is no number to scale by -- zero, or infinite where a
      // rejected non-finite step left a state -- is left unscaled: 1/∞ would
      // be a zero the right scaling then divides by.
      this.weight[i] = w > 0 && Number.isFinite(w) ? 1 / w : 1;
    }
  }

  /** Where the Newton iteration is: the linearisation point of J. */
  setPoint(t, z, fz, gammaDt) {
    this.t = t;
    this.z = z;
    this.fz = fz;
    this.gammaDt = gammaDt;
    this.zNorm = norm2(this.n, z);
  }

  /** J·v at the current point: the problem's own, or a forward difference. */
  jvp(v, out) {
    this.njvp++;
    const n = this.n;
    const integ = this.integ;
    if (integ.prob.jvp) {
      integ.prob.jvp(this.t, this.z, v, out, this.fz);
      return out;
    }
    const nx = Number.isFinite(this.zNorm) ? this.zNorm : 0;
    const nv = norm2(n, v);
    let eps = Math.max(JVP_SQRT_EPS * nx, JVP_SQRT_EPS);
    if (nv !== 0 && Number.isFinite(nv)) eps /= nv;
    const { zpert, fpert } = this;
    const z = this.z;
    for (let i = 0; i < n; i++) zpert[i] = z[i] + eps * v[i];
    integ.f(this.t, zpert, fpert);
    const fz = this.fz;
    for (let i = 0; i < n; i++) out[i] = (fpert[i] - fz[i]) / eps;
    return out;
  }

  /** Julia's W·v = J·v − v/(γh). */
  applyW(v, out) {
    this.jvp(v, out);
    const inv = 1 / this.gammaDt;
    const n = this.n;
    for (let i = 0; i < n; i++) out[i] -= v[i] * inv;
    return out;
  }

  /**
   * LinearSolve's Hegedüs warm start: the previous solution scaled to
   * minimise the residual along it, kept only if that at least halves it.
   * @returns {Float64Array|null} the starting guess, or null for a cold start
   */
  hegedus(b) {
    if (!this.havePrev) return null;
    const n = this.n;
    const u = this.xPrev;
    const unorm = norm2(n, u);
    if (unorm === 0 || !Number.isFinite(unorm)) return null;
    const Au = this.applyW(u, this.Au);
    const d = dot(n, Au, Au);
    if (d === 0 || !Number.isFinite(d)) return null;
    const Aub = dot(n, Au, b);
    if (!Number.isFinite(Aub)) return null;
    const bnorm = norm2(n, b);
    if (bnorm === 0 || !Number.isFinite(bnorm)) return null;
    if (Math.abs(Aub) < HEGEDUS_MIN_COSINE * Math.sqrt(d) * bnorm) return null;
    const xi = Aub / d;
    const x0 = this.zpert;     // free between products
    for (let i = 0; i < n; i++) x0[i] = xi * u[i];
    return x0;
  }

  /** Solve (I − γh·J)·dz = b in place, as the Newton iteration expects. */
  solve(b) {
    const n = this.n;
    const { bj, x, weight } = this;
    const g = this.gammaDt;
    for (let i = 0; i < n; i++) bj[i] = b[i] / g;
    const atol = JVP_SQRT_EPS;
    const rtol = this.integ.reltol;
    let x0 = this.hegedus(bj);
    let a = atol;
    let r = rtol;
    if (x0) {
      // Copied out of the scratch the products reuse, and the threshold kept
      // at the cold start's: atol + rtol·‖M⁻¹b‖, with rtol then zero.
      const start = this.xStart || (this.xStart = new Float64Array(n));
      start.set(x0);
      x0 = start;
      let s = 0;
      for (let i = 0; i < n; i++) { const v = weight[i] * bj[i]; s += v * v; }
      a = atol + rtol * Math.sqrt(s);
      r = 0;
      this.warmStarts++;
    }
    const st = this.gmres.solve(this.apply, bj, x, {
      left: weight, right: weight, x0, atol: a, rtol: r, itmax: n,
    });
    this.nsolve++;
    this.niter += st.niter;
    if (!st.solved) {
      this.nfail++;
      this.havePrev = false;
      b.fill(Infinity);
      return b;
    }
    this.xPrev.set(x);
    this.havePrev = true;
    for (let i = 0; i < n; i++) b[i] = -x[i];
    return b;
  }

  report() {
    return {
      krylovSolves: this.nsolve, krylovIters: this.niter, krylovJvps: this.njvp,
      krylovFailures: this.nfail, krylovWarmStarts: this.warmStarts,
    };
  }
}
