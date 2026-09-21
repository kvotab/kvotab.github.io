/* ==========================================================================
   STIFF ODE/DAE SOLVER WITH A SPARSE ITERATION MATRIX

   One integrator for M·dy/dt = f(t, y), with M a diagonal of ones and zeros
   (an algebraic variable has a zero), fed an analytic Jacobian as the values
   of a fixed sparsity pattern (compressed sparse column):

     ndf   variable-order numerical differentiation formulas, orders 1-5,
           with the backward differentiation formulas as the case of every
           kappa set to zero

   and the linear algebra behind it: M - h*J is assembled in CSC and
   factorised by a Gilbert-Peierls left-looking LU with partial pivoting and a
   reverse Cuthill-McKee ordering, or densely when a trial factorisation shows
   the sparse factor filling in. The choice is measured, not assumed, and is
   reported in the run's statistics.

   THE METHOD is written from its published descriptions: L. F. Shampine and
   M. W. Reichelt, "The MATLAB ODE Suite", SIAM J. Sci. Comput. 18 (1997)
   1-22, section 2, for the kappa values and the error estimate, and E. Hairer
   and G. Wanner, Solving Ordinary Differential Equations II (2nd ed., 1996),
   chapter V, for the backward-difference formulation and the order and
   step-size strategy. The integrator is arranged as a difference table (the
   columns of backward differences, the predictor read off them, and one
   linear map that re-expresses them on another grid -- a change of step, an
   event inside the step, or, read at one point, the interpolant), a weighting
   (the norm every test is measured in), and a driver over them. The same
   design is used by kvot ab's compartment-modelling application.

   Conventions: f(t, y, out) fills and returns `out` (Float64Array); the
   Jacobian object is { pattern: {n, nnz, colPtr, rowIdx}, evaluate(t, y) ->
   Float64Array | null }; results are { t, y } at the end of the run, with the
   accepted steps handed to `onAccepted` as they happen and, when `saveAt` is
   given, the solution at those times read off the interpolant.

   One global: FacsimileODE. Runs in a page, a Worker, or Node.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  root.FacsimileODE = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const EPS = 2 ** -52;
  const SQRT_EPS = Math.sqrt(EPS);

  /**
   * The weighted norm of the error control: the componentwise maximum
   * (norm 'max'), or the root-mean-square over the weighted components
   * (norm 'rms') that SciPy's BDF/Radau and SUNDIALS CVODE use. Both measure
   * |v_i| * invwt_i with invwt_i = 1 / max(|y_i|, |ynew_i|, atol_i/rtol).
   */
  function makeNorm(kind, neq) {
    if (kind === 'rms') {
      return (v, invwt) => {
        let s = 0;
        for (let i = 0; i < neq; i++) { const e = v[i] * invwt[i]; s += e * e; }
        return Math.sqrt(s / neq);
      };
    }
    return (v, invwt) => {
      let m = 0;
      for (let i = 0; i < neq; i++) { const e = Math.abs(v[i] * invwt[i]); if (!(e >= 0)) return NaN; if (e > m) m = e; }
      return m;
    };
  }

  class SolverError extends Error {
    constructor(code, message, t) {
      super(message);
      this.name = 'SolverError';
      this.code = code;
      this.t = t;
    }
  }

  /* ======================================================================
     1. Compressed sparse column matrices
     ====================================================================== */
  class CSC {
    constructor(m, n, colptr, rowind, values) {
      this.m = m; this.n = n; this.colptr = colptr; this.rowind = rowind; this.values = values;
    }
    get nnz() { return this.colptr[this.n]; }
    maxAbs() {
      let a = 0;
      for (let p = 0, nz = this.nnz; p < nz; p++) { const t = Math.abs(this.values[p]); if (t > a) a = t; }
      return a;
    }
  }

  function cscTranspose(A) {
    const { m, n, colptr, rowind, values } = A;
    const nz = colptr[n];
    const Tp = new Int32Array(m + 1);
    for (let p = 0; p < nz; p++) Tp[rowind[p] + 1]++;
    for (let i = 0; i < m; i++) Tp[i + 1] += Tp[i];
    const next = Int32Array.from(Tp.subarray(0, m));
    const Ti = new Int32Array(nz);
    const Tx = new Float64Array(nz);
    for (let j = 0; j < n; j++) {
      for (let p = colptr[j]; p < colptr[j + 1]; p++) {
        const q = next[rowind[p]]++;
        Ti[q] = j; Tx[q] = values[p];
      }
    }
    return new CSC(n, m, Tp, Ti, Tx);
  }

  function cscMergeSorted(A) {
    const { m, n, colptr, rowind, values } = A;
    const Cp = new Int32Array(n + 1);
    const Ci = new Int32Array(colptr[n]);
    const Cx = new Float64Array(colptr[n]);
    let nz = 0;
    for (let j = 0; j < n; j++) {
      Cp[j] = nz;
      let p = colptr[j];
      const end = colptr[j + 1];
      while (p < end) {
        const i = rowind[p];
        let s = values[p];
        p++;
        while (p < end && rowind[p] === i) { s += values[p]; p++; }
        Ci[nz] = i; Cx[nz] = s; nz++;
      }
    }
    Cp[n] = nz;
    return new CSC(m, n, Cp, Ci.slice(0, nz), Cx.slice(0, nz));
  }

  /** Triplets -> CSC, summing duplicates; rows come out sorted within columns. */
  function cscFromTriplets(m, n, I, J, V) {
    const nz = I.length;
    const colptr = new Int32Array(n + 1);
    for (let p = 0; p < nz; p++) colptr[J[p] + 1]++;
    for (let j = 0; j < n; j++) colptr[j + 1] += colptr[j];
    const next = Int32Array.from(colptr.subarray(0, n));
    const rowind = new Int32Array(nz);
    const values = new Float64Array(nz);
    for (let p = 0; p < nz; p++) {
      const q = next[J[p]]++;
      rowind[q] = I[p]; values[q] = V[p];
    }
    return cscMergeSorted(cscTranspose(cscTranspose(new CSC(m, n, colptr, rowind, values))));
  }

  /** out = A*x for a pattern {n, colPtr, rowIdx} with separate values. */
  function patternMatVec(pattern, values, x, out) {
    out.fill(0);
    for (let j = 0; j < pattern.n; j++) {
      const v = x[j];
      if (v === 0) continue;
      for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) out[pattern.rowIdx[p]] += values[p] * v;
    }
    return out;
  }

  /**
   * The iteration matrix I - a*J in CSC, with J's pattern plus the diagonal.
   * update(a, Jvalues) rewrites the values in O(nnz) without allocation.
   */
  function makeMiterBuilder(pattern) {
    const n = pattern.n;
    const nzJ = pattern.nnz;
    const I2 = new Int32Array(nzJ + n), J2 = new Int32Array(nzJ + n), V2 = new Float64Array(nzJ + n);
    let t = 0;
    for (let j = 0; j < n; j++) {
      for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) { I2[t] = pattern.rowIdx[p]; J2[t] = j; t++; }
    }
    for (let j = 0; j < n; j++) { I2[t] = j; J2[t] = j; t++; }
    const M = cscFromTriplets(n, n, I2, J2, V2);
    const jToM = new Int32Array(nzJ);
    const diagPos = new Int32Array(n).fill(-1);
    const pos = new Int32Array(n).fill(-1);
    for (let j = 0; j < n; j++) {
      for (let p = M.colptr[j]; p < M.colptr[j + 1]; p++) pos[M.rowind[p]] = p;
      for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) jToM[p] = pos[pattern.rowIdx[p]];
      diagPos[j] = pos[j];
      for (let p = M.colptr[j]; p < M.colptr[j + 1]; p++) pos[M.rowind[p]] = -1;
    }
    const Mx = M.values;
    const rowOf = pattern.rowIdx;
    return {
      M,
      /**
       * M := Mass - a*J, optionally in the scaled variables y_i / w_i:
       * M_ij = mass_i delta_ij - a J_ij w_j / w_i. The species of this kind of
       * model span forty orders of magnitude, and without the scaling the
       * pivoting of either factorisation is decided by the largest
       * coefficients and the corrections for the trace species come out wrong.
       *
       * `mass` is the diagonal of the mass matrix in M y' = f: one for a
       * variable with a differential equation, zero for one with an algebraic
       * one. Absent, it is the identity and this is the ordinary ODE matrix.
       * The mass matrix is diagonal, so the scaling leaves it alone: w_i / w_i
       * is one.
       */
      update(a, Jvalues, w, mass) {
        Mx.fill(0);
        if (w) {
          for (let j = 0; j < n; j++) {
            const wj = w[j];
            for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) Mx[jToM[p]] = -a * Jvalues[p] * wj / w[rowOf[p]];
          }
        } else {
          for (let p = 0; p < nzJ; p++) Mx[jToM[p]] = -a * Jvalues[p];
        }
        if (mass) for (let i = 0; i < n; i++) Mx[diagPos[i]] += mass[i];
        else for (let i = 0; i < n; i++) Mx[diagPos[i]] += 1;
        return M;
      },
    };
  }

  /* ======================================================================
     2. Gilbert-Peierls sparse LU with partial pivoting
     ====================================================================== */
  class SparseLU {
    constructor(n) {
      this.n = n;
      this.pinv = new Int32Array(n);
      this.perm = new Int32Array(n);
      this.qcol = null;
      this.x = new Float64Array(n);
      this.xi = new Int32Array(n);
      this.stack = new Int32Array(n);
      this.pstack = new Int32Array(n);
      this.mark = new Int32Array(n).fill(-1);
      this.stampCounter = 0;
      const cap = Math.max(4 * n, 64);
      this.Lp = new Int32Array(n + 1); this.Li = new Int32Array(cap); this.Lx = new Float64Array(cap);
      this.Up = new Int32Array(n + 1); this.Ui = new Int32Array(cap); this.Ux = new Float64Array(cap);
      this.lnz = 0; this.unz = 0;
      this.singular = false;
      this.failColumn = -1;
      this._solveWork = new Float64Array(n);
    }
    _growL(need) {
      if (need <= this.Li.length) return;
      let cap = this.Li.length; while (cap < need) cap *= 2;
      const Li = new Int32Array(cap); Li.set(this.Li); this.Li = Li;
      const Lx = new Float64Array(cap); Lx.set(this.Lx); this.Lx = Lx;
    }
    _growU(need) {
      if (need <= this.Ui.length) return;
      let cap = this.Ui.length; while (cap < need) cap *= 2;
      const Ui = new Int32Array(cap); Ui.set(this.Ui); this.Ui = Ui;
      const Ux = new Float64Array(cap); Ux.set(this.Ux); this.Ux = Ux;
    }
    /** Reach of A(:,col) through L, in topological order in xi[top..n-1]. */
    _reach(Ap, Ai, col) {
      const n = this.n;
      const { xi, stack, pstack, mark, pinv, Lp, Li } = this;
      const stamp = ++this.stampCounter;
      let top = n;
      for (let sp = Ap[col]; sp < Ap[col + 1]; sp++) {
        const start = Ai[sp];
        if (mark[start] === stamp) continue;
        let head = 0;
        stack[0] = start;
        while (head >= 0) {
          const j = stack[head];
          const J = pinv[j];
          if (mark[j] !== stamp) {
            mark[j] = stamp;
            pstack[head] = J < 0 ? 0 : Lp[J] + 1;
          }
          const pend = J < 0 ? 0 : Lp[J + 1];
          let done = true;
          for (let p = pstack[head]; p < pend; p++) {
            const w = Li[p];
            if (mark[w] === stamp) continue;
            pstack[head] = p;
            stack[++head] = w;
            done = false;
            break;
          }
          if (done) { head--; xi[--top] = j; }
        }
      }
      return top;
    }
    _spsolve(Ap, Ai, Ax, col) {
      const n = this.n;
      const top = this._reach(Ap, Ai, col);
      const { xi, x, pinv, Lp, Li, Lx } = this;
      for (let p = top; p < n; p++) x[xi[p]] = 0;
      for (let p = Ap[col]; p < Ap[col + 1]; p++) x[Ai[p]] = Ax[p];
      for (let px = top; px < n; px++) {
        const j = xi[px];
        const J = pinv[j];
        if (J < 0) continue;
        const xj = x[j];
        if (xj === 0) continue;
        for (let p = Lp[J] + 1; p < Lp[J + 1]; p++) x[Li[p]] -= Lx[p] * xj;
      }
      return top;
    }
    /** @param {CSC} A  @param {{q?: Int32Array|null}} opts column ordering */
    factorize(A, opts = {}) {
      const n = this.n;
      const q = opts.q || null;
      const Ap = A.colptr, Ai = A.rowind, Ax = A.values;
      this.qcol = q;
      this.singular = false;
      this.failColumn = -1;
      this.pinv.fill(-1);
      this.mark.fill(-1);
      this.stampCounter = 0;
      this.x.fill(0);
      let lnz = 0, unz = 0;
      for (let k = 0; k < n; k++) {
        this.Lp[k] = lnz;
        this.Up[k] = unz;
        this._growL(lnz + n);
        this._growU(unz + n);
        const { Li, Lx, Ui, Ux, xi, x, pinv } = this;
        const col = q ? q[k] : k;
        const top = this._spsolve(Ap, Ai, Ax, col);
        let ipiv = -1, best = -1;
        for (let p = top; p < n; p++) {
          const i = xi[p];
          if (pinv[i] < 0) {
            const t = Math.abs(x[i]);
            if (t > best) { best = t; ipiv = i; }
          } else {
            Ui[unz] = pinv[i]; Ux[unz] = x[i]; unz++;
          }
        }
        if (ipiv === -1 || !(best > 0) || !Number.isFinite(best)) {
          this.singular = true;
          this.failColumn = col;
          this.lnz = lnz; this.unz = unz;
          for (let kk = k; kk <= n; kk++) { this.Lp[kk] = lnz; this.Up[kk] = unz; }
          return this;
        }
        const pivot = x[ipiv];
        Ui[unz] = k; Ux[unz] = pivot; unz++;
        pinv[ipiv] = k;
        Li[lnz] = ipiv; Lx[lnz] = 1; lnz++;
        for (let p = top; p < n; p++) {
          const i = xi[p];
          if (pinv[i] < 0) { Li[lnz] = i; Lx[lnz] = x[i] / pivot; lnz++; }
          x[i] = 0;
        }
      }
      this.Lp[n] = lnz; this.Up[n] = unz;
      this.lnz = lnz; this.unz = unz;
      const { Li, pinv, perm } = this;
      for (let p = 0; p < lnz; p++) Li[p] = pinv[Li[p]];
      for (let i = 0; i < n; i++) perm[pinv[i]] = i;
      return this;
    }
    solve(b, out) {
      const n = this.n;
      const { perm, qcol, Lp, Li, Lx, Up, Ui, Ux } = this;
      const t = this._solveWork;
      for (let k = 0; k < n; k++) t[k] = b[perm[k]];
      for (let j = 0; j < n; j++) {
        const xj = t[j];
        if (xj === 0) continue;
        for (let p = Lp[j] + 1; p < Lp[j + 1]; p++) t[Li[p]] -= Lx[p] * xj;
      }
      for (let j = n - 1; j >= 0; j--) {
        const d = Ux[Up[j + 1] - 1];
        const xj = t[j] / d;
        t[j] = xj;
        if (xj === 0) continue;
        for (let p = Up[j]; p < Up[j + 1] - 1; p++) t[Ui[p]] -= Ux[p] * xj;
      }
      const x = out || new Float64Array(n);
      if (qcol) for (let k = 0; k < n; k++) x[qcol[k]] = t[k];
      else x.set(t);
      return x;
    }
  }

  /** Reverse Cuthill-McKee ordering on the pattern of A + A'. */
  function reverseCuthillMcKee(A) {
    const n = A.n;
    const adj = Array.from({ length: n }, () => new Set());
    for (let j = 0; j < n; j++) {
      for (let p = A.colptr[j]; p < A.colptr[j + 1]; p++) {
        const i = A.rowind[p];
        if (i === j) continue;
        adj[i].add(j); adj[j].add(i);
      }
    }
    const degree = adj.map((s) => s.size);
    const visited = new Uint8Array(n);
    const order = new Int32Array(n);
    let filled = 0;
    const byDegree = Array.from({ length: n }, (_, i) => i).sort((a, b) => degree[a] - degree[b] || a - b);
    const queue = new Int32Array(n);
    for (const seed of byDegree) {
      if (visited[seed]) continue;
      let head = 0, tail = 0;
      queue[tail++] = seed; visited[seed] = 1;
      while (head < tail) {
        const v = queue[head++];
        order[filled++] = v;
        const nb = [...adj[v]].filter((u) => !visited[u]).sort((a, b) => degree[a] - degree[b] || a - b);
        for (const u of nb) { visited[u] = 1; queue[tail++] = u; }
      }
    }
    const rev = new Int32Array(n);
    for (let i = 0; i < n; i++) rev[i] = order[n - 1 - i];
    return rev;
  }

  /* ======================================================================
     3. Dense LU (fallback when the sparse factor fills in)
     ====================================================================== */
  class DenseLU {
    constructor(n) {
      this.n = n;
      this.lu = Array.from({ length: n }, () => new Float64Array(n));
      this.piv = new Int32Array(n);
      this.singular = false;
      this.failColumn = -1;
    }
    /** Factors Mass - a*J where J is given through a pattern and its values; w scales and `mass` is the mass diagonal, both as in makeMiterBuilder. */
    formAndFactor(a, pattern, values, w, mass) {
      const n = this.n, lu = this.lu;
      for (let i = 0; i < n; i++) lu[i].fill(0);
      for (let j = 0; j < n; j++) {
        const wj = w ? w[j] : 1;
        for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) {
          const i = pattern.rowIdx[p];
          lu[i][j] = -a * values[p] * (w ? wj / w[i] : 1);
        }
      }
      if (mass) for (let i = 0; i < n; i++) lu[i][i] += mass[i];
      else for (let i = 0; i < n; i++) lu[i][i] += 1;
      return this.factorizeInPlace();
    }
    factorizeInPlace() {
      const n = this.n, lu = this.lu, piv = this.piv;
      for (let i = 0; i < n; i++) piv[i] = i;
      this.singular = false;
      this.failColumn = -1;
      for (let k = 0; k < n; k++) {
        let p = k, maxAbs = Math.abs(lu[k][k]);
        for (let i = k + 1; i < n; i++) { const v = Math.abs(lu[i][k]); if (v > maxAbs) { maxAbs = v; p = i; } }
        if (!(maxAbs > 0) || !Number.isFinite(maxAbs)) { this.singular = true; this.failColumn = k; return this; }
        if (p !== k) {
          const tmp = lu[p]; lu[p] = lu[k]; lu[k] = tmp;
          const t = piv[p]; piv[p] = piv[k]; piv[k] = t;
        }
        const pivotRow = lu[k], pivot = pivotRow[k];
        for (let i = k + 1; i < n; i++) {
          const row = lu[i];
          const f = row[k] / pivot;
          if (f === 0) continue;
          row[k] = f;
          for (let j = k + 1; j < n; j++) row[j] -= f * pivotRow[j];
        }
      }
      return this;
    }
    solve(b, out) {
      const n = this.n, lu = this.lu, piv = this.piv;
      const x = out || new Float64Array(n);
      for (let i = 0; i < n; i++) x[i] = b[piv[i]];
      for (let i = 1; i < n; i++) {
        const row = lu[i];
        let s = x[i];
        for (let j = 0; j < i; j++) s -= row[j] * x[j];
        x[i] = s;
      }
      for (let i = n - 1; i >= 0; i--) {
        const row = lu[i];
        let s = x[i];
        for (let j = i + 1; j < n; j++) s -= row[j] * x[j];
        x[i] = s / row[i];
      }
      return x;
    }
  }

  /* ======================================================================
     4. The iteration matrix: sparse or dense, decided by measured fill
     ====================================================================== */
  /**
   * @param {object} pattern  {n, nnz, colPtr, rowIdx}
   * @param {Float64Array} values  Jacobian values for the trial factorisation
   * @param {'auto'|'sparse'|'dense'} mode
   */
  /**
   * Why the iteration matrix would not factor.
   *
   * For an ODE, Mass - h*J is the identity minus something small: it is
   * singular only if the Jacobian has blown up. With algebraic variables the
   * identity is gone from those rows, and the matrix is singular exactly when
   * the constraints do not determine them -- a constraint that does not
   * mention its own variable, two that say the same thing, or a system of
   * index above one. That is a different fault and gets a different message.
   */
  function singularMessage(mass, column) {
    const algebraic = mass && mass[column] === 0;
    return algebraic
      ? `The iteration matrix M - h*J is singular at the algebraic variable in column ${column}: `
        + 'its constraint does not determine it. Check that the constraint depends on its own '
        + 'variable, that no two constraints say the same thing, and that the system is index 1.'
      : `The iteration matrix M - h*J is singular at column ${column}`;
  }

  function makeIterationMatrix(pattern, values, mode = 'auto', mass = null) {
    const n = pattern.n;
    const dense = new DenseLU(n);
    const info = { sparse: false, fill: null, denseFill: n * n, ordering: 'natural', nnz: pattern.nnz };
    // The scaling in force for the current factorisation, and the scaled solve.
    let wScale = null;
    const scratch = new Float64Array(n);
    const scaledSolve = (lu, rhs, out) => {
      if (!wScale) return lu.solve(rhs, out);
      for (let i = 0; i < n; i++) scratch[i] = rhs[i] / wScale[i];
      const x = lu.solve(scratch, out);
      for (let i = 0; i < n; i++) x[i] *= wScale[i];
      return x;
    };
    const keepScale = (w) => { wScale = w ? Float64Array.from(w) : null; };
    if (mode === 'dense') {
      return {
        info,
        form(a, current, w) {
          keepScale(w);
          dense.formAndFactor(a, pattern, current, wScale, mass);
          if (dense.singular) throw new Error(singularMessage(mass, dense.failColumn));
        },
        solve(rhs, out) { return scaledSolve(dense, rhs, out); },
      };
    }
    const builder = makeMiterBuilder(pattern);
    const factors = new SparseLU(n);
    // One real factorisation of each ordering decides: the fill of the factor,
    // not the sparsity of the pattern, is what the solve costs.
    const M = builder.update(1e-3, values, null, mass);
    factors.factorize(M);
    let best = factors.singular ? Infinity : factors.lnz + factors.unz;
    let q = null;
    const rcm = reverseCuthillMcKee(M);
    factors.factorize(M, { q: rcm });
    if (!factors.singular && factors.lnz + factors.unz < best) { best = factors.lnz + factors.unz; q = rcm; }
    if (best === Infinity) { best = pattern.nnz + n; q = rcm; }
    info.fill = best;
    info.ordering = q ? 'reverse Cuthill-McKee' : 'natural';
    // Past a third of a dense factor the sparse factorisation is slower than
    // the dense one at this size, so it is used only when it pays.
    if (mode === 'auto' && best > 0.35 * n * n) {
      info.sparse = false;
      return {
        info,
        form(a, current, w) {
          keepScale(w);
          dense.formAndFactor(a, pattern, current, wScale, mass);
          if (dense.singular) throw new Error(singularMessage(mass, dense.failColumn));
        },
        solve(rhs, out) { return scaledSolve(dense, rhs, out); },
      };
    }
    info.sparse = true;
    return {
      info,
      form(a, current, w) {
        keepScale(w);
        factors.factorize(builder.update(a, current, wScale, mass), { q });
        if (factors.singular) throw new Error(singularMessage(mass, factors.failColumn));
      },
      solve(rhs, out) { return scaledSolve(factors, rhs, out); },
    };
  }

  /* ======================================================================
     5. Finite-difference Jacobian through the pattern (fallback and checks)
     ====================================================================== */
  /**
   * Groups columns that share no row (greedy, largest degree first), so a
   * finite-difference Jacobian costs one evaluation per group.
   */
  function colourColumns(pattern) {
    const { n, colPtr, rowIdx } = pattern;
    const rowCount = new Int32Array(n + 1);
    for (let k = 0; k < rowIdx.length; k++) rowCount[rowIdx[k] + 1]++;
    for (let i = 0; i < n; i++) rowCount[i + 1] += rowCount[i];
    const rowPtr = Int32Array.from(rowCount);
    const rowCols = new Int32Array(rowIdx.length);
    const fill = Int32Array.from(rowPtr);
    for (let j = 0; j < n; j++) for (let k = colPtr[j]; k < colPtr[j + 1]; k++) rowCols[fill[rowIdx[k]]++] = j;
    const order = Array.from({ length: n }, (_, j) => j).sort((a, c) => (colPtr[c + 1] - colPtr[c]) - (colPtr[a + 1] - colPtr[a]));
    const colour = new Int32Array(n).fill(-1);
    const used = new Int32Array(n + 1).fill(-1);
    let ncolours = 0;
    for (const j of order) {
      for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
        const row = rowIdx[k];
        for (let q = rowPtr[row]; q < rowPtr[row + 1]; q++) { const other = rowCols[q]; if (colour[other] >= 0) used[colour[other]] = j; }
      }
      let c = 0;
      while (used[c] === j) c++;
      colour[j] = c;
      if (c + 1 > ncolours) ncolours = c + 1;
    }
    const groups = Array.from({ length: ncolours }, () => []);
    for (let j = 0; j < n; j++) groups[colour[j]].push(j);
    return groups.map((g) => Int32Array.from(g));
  }
  /** One-sided differences of f through the pattern, one evaluation per colour. */
  function differenceJacobian(f, t, y, f0, pattern, groups, threshold, out) {
    const n = y.length;
    const { colPtr, rowIdx } = pattern;
    const ytry = new Float64Array(n);
    const fd = new Float64Array(n);
    const del = new Float64Array(n);
    for (let j = 0; j < n; j++) {
      // sqrt(eps) of the larger of the state and its error threshold, rounded
      // to what the addition actually changed, so the quotient divides by
      // the perturbation that was made.
      let dj = SQRT_EPS * Math.max(Math.abs(y[j]), threshold[j]);
      if (dj === 0) dj = SQRT_EPS;
      const moved = (y[j] + dj) - y[j];
      del[j] = moved === 0 ? dj : moved;
    }
    for (const group of groups) {
      ytry.set(y);
      for (const j of group) ytry[j] += del[j];
      f(t, ytry, fd);
      for (const j of group) {
        for (let k = colPtr[j]; k < colPtr[j + 1]; k++) { const i = rowIdx[k]; out[k] = (fd[i] - f0[i]) / del[j]; }
      }
    }
    return out;
  }

  /* ======================================================================
     6. Event location on an interpolant
     ====================================================================== */
  /**
   * `en`, when given, is a mask: a zero there is an event that has already
   * done its one job and is not to be looked at again. That is FACSIMILE's
   * WHEN against its WHENEVER, which is the only difference between the two.
   */
  function crosses(vL, vR, dir, i, en) {
    if (en && !en[i]) return false;
    if (Math.sign(vL[i]) === Math.sign(vR[i])) return false;
    return dir[i] * (vR[i] - vL[i]) >= 0;
  }
  function anyCrossing(vL, vR, dir, en) {
    for (let i = 0; i < vL.length; i++) if (crosses(vL, vR, dir, i, en)) return true;
    return false;
  }
  /**
   * How closely a crossing in [tL, tR] is pinned down: a few dozen units of
   * round-off in the times themselves, and never more than the step, so a
   * very short step is not bisected for ever. The floor of one keeps a run
   * that starts at zero from asking for a tolerance of zero.
   */
  function crossingTolerance(tL, tR) {
    return Math.min(Math.abs(tR - tL), 64 * EPS * Math.max(Math.abs(tL), Math.abs(tR), 1));
  }
  /** The earliest secant root any crossing component predicts, as a fraction of the bracket. */
  function earliestSecant(vlo, vhi, dir, en) {
    let frac = 1;
    for (let i = 0; i < vlo.length; i++) {
      if (!crosses(vlo, vhi, dir, i, en)) continue;
      const a = vlo[i], b = vhi[i];
      let f = a === b ? 0.5 : -a / (b - a);
      if (!(f > 0 && f < 1)) f = 0.5;
      if (f < frac) frac = f;
    }
    return frac;
  }
  /**
   * Earliest crossing in (tL, tR], or null. `valuesAt(t)` evaluates the event
   * functions on the solver's interpolant and hands back an array the search
   * may keep. `tStart` is where the segment began: a component exactly on zero
   * there is the event that stopped the previous segment, and is not a
   * crossing until it has left zero -- it is judged by where it is half a
   * tolerance later.
   *
   * The search is a safeguarded regula falsi: the secant root of whichever
   * crossing component predicts the earliest crossing, falling back to the
   * midpoint when that root lies outside the bracket or the same end has
   * been kept twice running, which is what stops a function that grazes zero
   * from pinning one end of the bracket in place.
   */
  function firstCrossing(valuesAt, tL, vL, tR, vR, dir, tStart, en) {
    const tol = crossingTolerance(tL, tR);
    const tdir = Math.sign(tR - tL);
    let lo = tL, vlo = vL;
    if (tStart !== undefined && tL === tStart) {
      let resting = false;
      for (let i = 0; i < vL.length; i++) if (vL[i] === 0 && vR[i] !== 0 && (!en || en[i])) { resting = true; break; }
      if (resting) {
        lo = tL + tdir * 0.5 * tol;
        if (tdir * (tR - lo) <= 0) return null;
        vlo = Float64Array.from(valuesAt(lo));
        // Still on zero half a tolerance in: it has not moved, and a
        // component that has not moved is left out of the search.
        for (let i = 0; i < vlo.length; i++) if (vlo[i] === 0 && vL[i] === 0) vlo[i] = vR[i];
      }
    }
    if (!anyCrossing(vlo, vR, dir, en)) return null;
    let hi = tR, vhi = vR;
    let kept = 0, sameEnd = 0;
    for (let iter = 0; iter < 80 && Math.abs(hi - lo) > tol; iter++) {
      let mid;
      if (sameEnd >= 2) mid = 0.5 * (lo + hi);
      else {
        mid = lo + earliestSecant(vlo, vhi, dir, en) * (hi - lo);
        const inner = 0.5 * tol;
        if (tdir * (mid - lo) < inner) mid = lo + tdir * inner;
        if (tdir * (hi - mid) < inner) mid = hi - tdir * inner;
        if (!(tdir * (mid - lo) > 0 && tdir * (hi - mid) > 0)) mid = 0.5 * (lo + hi);
      }
      const vmid = valuesAt(mid);
      if (anyCrossing(vlo, vmid, dir, en)) { hi = mid; vhi = vmid; sameEnd = kept === 1 ? sameEnd + 1 : 1; kept = 1; }
      else { lo = mid; vlo = vmid; sameEnd = kept === -1 ? sameEnd + 1 : 1; kept = -1; }
    }
    const which = [];
    for (let i = 0; i < vlo.length; i++) if (crosses(vlo, vhi, dir, i, en)) which.push(i);
    return { t: hi, values: vhi, which };
  }

  /* ======================================================================
     7. ndf: variable-order NDF/BDF, orders 1-5
     ====================================================================== */
  const MAX_ORDER = 5;
  /** kappa_k for k = 1..5, as published; every kappa zero is the BDF. */
  const KAPPA = [-0.185, -1 / 9, -0.0823, -0.0415, 0];
  /** gamma_k = sum_{j=1..k} 1/j, the coefficient the corrector puts on the (k+1)th difference. */
  const GAMMA = [1, 3 / 2, 11 / 6, 25 / 12, 137 / 60];
  const NEWTON_MAX = 4;         // iterations per attempt at a step
  const NEWTON_TOL = 0.3;       // Newton error allowed, as a fraction of rtol
  const RATE_LIMIT = 0.9;       // a contraction rate at or above this is not converging
  const RATE_FLOOR = 0.02;      // the smallest rate believed from one earlier step
  const CONVERGED_FLOOR = 1e-3; // a correction this far under rtol is converged whatever its rate says
  const SAFETY = 0.8, SAFETY_LOWER = 0.75, SAFETY_HIGHER = 0.7;
  const MAX_GROWTH = 10;
  const NEWTON_CUT = 0.25;
  const STALL_WINDOW = 4000, STALL_SPAN_FRACTION = 1e-10;

  function ulp(x) {
    const a = Math.abs(x);
    if (!(a > 0)) return Number.MIN_VALUE;
    return 2 ** Math.max(Math.floor(Math.log2(a)) - 52, -1074);
  }
  const stepFloor = (t) => 16 * ulp(t);

  /**
   * The Newton backward-difference basis at `s` steps past the table's end:
   * c_0 = 1 and c_j = c_{j-1}·(s + j - 1)/j, so a polynomial through equally
   * spaced points reads sum_j c_j(s)·∇^j y at s.
   */
  function basisAt(s, k, out) {
    out[0] = 1;
    for (let j = 1; j <= k; j++) out[j] = out[j - 1] * ((s + j - 1) / j);
    return out;
  }
  function choose(n, r) {
    let v = 1;
    for (let i = 1; i <= r; i++) v = (v * (n - r + i)) / i;
    return v;
  }
  /**
   * The linear map that re-expresses the backward differences of a degree-k
   * polynomial on another grid, ending `sEnd` old steps past the table's end
   * with a spacing of `ratio` old steps. The new m-th difference is the
   * alternating sum of the polynomial's values at the new points, each read
   * through the basis above; entries that are analytically zero (j < m) are
   * written as exactly zero rather than left to rounding.
   */
  function regridMatrix(k, sEnd, ratio) {
    const T = new Array(k + 1);
    const c = new Float64Array(k + 1);
    const values = new Array(k + 1);
    for (let i = 0; i <= k; i++) values[i] = Float64Array.from(basisAt(sEnd - i * ratio, k, c));
    for (let m = 0; m <= k; m++) {
      const row = new Float64Array(k + 1);
      for (let j = m; j <= k; j++) {
        let acc = 0;
        for (let i = 0; i <= m; i++) acc += (i % 2 ? -1 : 1) * choose(m, i) * values[i][j];
        row[j] = acc;
      }
      T[m] = row;
    }
    return T;
  }

  /**
   * The backward differences of the solution at the current point: cols[j]
   * is ∇^j y for every state, cols[0] the state itself. Columns run to
   * maxOrder + 2, since choosing an order needs the difference one above the
   * order in use, and forming that needs the one above again.
   */
  class DifferenceTable {
    constructor(neq, maxOrder) {
      this.cols = [];
      for (let j = 0; j < maxOrder + 3; j++) this.cols.push(new Float64Array(neq));
      this._scratch = new Float64Array(neq);
      this._basis = new Float64Array(maxOrder + 3);
    }
    get y() { return this.cols[0]; }
    start(y, hf) {
      this.cols[0].set(y);
      this.cols[1].set(hf);
      for (let j = 2; j < this.cols.length; j++) this.cols[j].fill(0);
    }
    /** The order-k predictor, sum_{j=0..k} ∇^j y. */
    predict(k, out) {
      const c = this.cols;
      out.set(c[0]);
      for (let j = 1; j <= k; j++) { const col = c[j]; for (let i = 0; i < out.length; i++) out[i] += col[i]; }
      return out;
    }
    /** The corrector's history term sum_{j=1..k} gamma_j ∇^j y. */
    history(k, out) {
      const c = this.cols;
      out.fill(0);
      for (let j = 1; j <= k; j++) { const col = c[j], g = GAMMA[j - 1]; for (let i = 0; i < out.length; i++) out[i] += g * col[i]; }
      return out;
    }
    /** Folds an accepted correction d = ∇^{k+1} y_{n+1} in; every lower difference follows. */
    advance(k, d) {
      const c = this.cols;
      const top = c[k + 1], above = c[k + 2];
      for (let i = 0; i < d.length; i++) { above[i] = d[i] - top[i]; top[i] = d[i]; }
      for (let j = k; j >= 0; j--) { const col = c[j], next = c[j + 1]; for (let i = 0; i < col.length; i++) col[i] += next[i]; }
    }
    rescale(k, ratio) { this.regrid(k, 0, ratio); }
    /** The same polynomial on a grid ending sEnd steps past the current end with `ratio` times the spacing. */
    regrid(k, sEnd, ratio) {
      const T = regridMatrix(k, sEnd, ratio);
      const c = this.cols, tmp = this._scratch;
      for (let m = 0; m <= k; m++) {
        const row = T[m];
        tmp.fill(0);
        for (let j = m; j <= k; j++) {
          const w = row[j];
          if (w === 0) continue;
          const col = c[j];
          for (let i = 0; i < tmp.length; i++) tmp[i] += w * col[i];
        }
        c[m].set(tmp);
      }
    }
    /** The interpolant: the degree-k polynomial through the last k+1 points, read s steps past the end. */
    valueAt(k, s, out, clampAtZero) {
      const c = this.cols, b = basisAt(s, k, this._basis);
      out.set(c[0]);
      for (let j = 1; j <= k; j++) { const w = b[j], col = c[j]; for (let i = 0; i < out.length; i++) out[i] += w * col[i]; }
      if (clampAtZero) for (const i of clampAtZero) if (out[i] < 0) out[i] = 0;
      return out;
    }
    /** A state just projected onto zero has no history worth keeping. */
    forget(i) { for (let j = 1; j < this.cols.length; j++) this.cols[j][i] = 0; }
  }

  /**
   * @param {(t:number, y:Float64Array, out:Float64Array)=>Float64Array} f
   * @param {number} t0 @param {number} tfinal @param {Float64Array} y0
   * @param {object} opts
   *   rtol, atol (number|array), maxOrder (1-5), bdf (bool), hmax, h0, maxSteps,
   *   nonNegative (bool[] or null), mass (diagonal: 1 differential, 0 algebraic),
   *   suppressAlgebraic, norm ('max'|'rms'), scaling, minNewton, stagnationTol,
   *   belowTolRun, autoAtol,
   *   jacobian: {pattern, evaluate(t,y), groups} -- `evaluate` optional (differenced through the pattern),
   *   matrix: 'auto'|'sparse'|'dense',
   *   events: {n, direction:Int8Array, enabled?:Uint8Array, fun(t,y,out)} or null (all terminal),
   *   tStart (segment start for events), saveAt (ascending times to read the solution at),
   *   onAccepted(t, y), onStep(t, nsteps) -> false to abort, debug(info)
   */
  function ndf(f, t0, tfinal, y0, opts = {}) {
    const neq = y0.length;
    const rtol = opts.rtol ?? 1e-3;
    // Copied, so that a caller's array is never written to -- except when the
    // caller has asked for the tolerance to follow the run and has handed
    // over an array to hold it, so the high-water mark survives a restart.
    const atol = (opts.autoAtol && opts.atol instanceof Float64Array)
      ? opts.atol
      : (typeof opts.atol === 'number' || opts.atol == null
        ? new Float64Array(neq).fill(opts.atol ?? 1e-6) : Float64Array.from(opts.atol));
    const maxk = Math.min(MAX_ORDER, Math.max(1, Math.round(opts.maxOrder ?? MAX_ORDER)));
    const bdf = !!opts.bdf;
    const maxSteps = opts.maxSteps ?? 2e6;
    const tdir = Math.sign(tfinal - t0);
    if (tdir === 0) throw new SolverError('span', 'The start and end times are equal', t0);
    const span = Math.abs(tfinal - t0);
    const hmax = opts.hmax != null && opts.hmax > 0 ? Math.min(opts.hmax, span) : 0.1 * span;

    /*
      M y' = f, with M the diagonal handed in as `mass`: one where the variable
      has a differential equation, zero where it has an algebraic one. On an
      algebraic row the corrector asks that the residual itself be zero, and
      the iteration matrix has no identity there -- the classical way of
      carrying an index-1 system through a BDF code, and what makes the matrix
      singular exactly when the constraints do not determine the algebraic
      variables.
    */
    const mass = opts.mass && opts.mass.length === neq ? opts.mass : null;
    const idxAlg = [];
    if (mass) for (let i = 0; i < neq; i++) if (!mass[i]) idxAlg.push(i);
    const hasAlg = idxAlg.length > 0;
    const suppressAlg = hasAlg && !!opts.suppressAlgebraic;
    // An algebraic variable is not projected onto zero: its value is whatever
    // satisfies its constraint, and moving it breaks that.
    const constrained = [];
    if (opts.nonNegative) for (let i = 0; i < neq; i++) if (opts.nonNegative[i] && !(mass && !mass[i])) constrained.push(i);
    const hasNN = constrained.length > 0;
    const clampList = hasNN ? constrained : null;
    const wnorm = makeNorm(opts.norm || 'max', neq);
    const minNewton = opts.minNewton ?? 2;
    const stagnationTol = opts.stagnationTol ?? 0;
    const BELOW_TOL_RUN = opts.belowTolRun == null ? 5 : Math.max(0, Math.round(opts.belowTolRun));
    const autoAtol = !!opts.autoAtol;

    // The corrector's leading coefficient (1 - kappa_k)·gamma_k and the error
    // constant kappa_k·gamma_k + 1/(k+1), both indexed by order.
    const leading = new Float64Array(MAX_ORDER + 2), errorConst = new Float64Array(MAX_ORDER + 2);
    for (let q = 1; q <= MAX_ORDER; q++) {
      const kappa = bdf ? 0 : KAPPA[q - 1];
      leading[q] = (1 - kappa) * GAMMA[q - 1];
      errorConst[q] = kappa * GAMMA[q - 1] + 1 / (q + 1);
    }

    // The error test's threshold may float upwards with the solution
    // (`autoAtol`); the Newton test's and the matrix scaling's do not, since
    // what a species once was is the wrong scale for how well this step's
    // equations have been solved.
    const threshold = new Float64Array(neq);
    for (let i = 0; i < neq; i++) threshold[i] = atol[i] / rtol;
    const newtonThreshold = autoAtol ? Float64Array.from(threshold) : threshold;

    // Statistics, and a short trace of the last accepted steps for a failure report.
    let nsteps = 0, nfailed = 0, nfevals = 0, npds = 0, ndecomps = 0, nsolves = 0, nbelowtol = 0, negative = 0;
    const trace = [];
    let t = t0;
    const table = new DifferenceTable(neq, maxk);
    const y = table.y;
    y.set(y0);
    const fail = (e) => { e.trace = trace.slice(); e.lastT = t; e.lastY = Float64Array.from(y); e.stats = { nsteps, nfailed, nfevals, npds, ndecomps, nsolves }; return e; };

    // --- the derivative: the model's own, and the projected system's --------
    const raw = (tt, yy, out) => { nfevals++; return f(tt, yy, out); };
    const heldRows = hasNN ? new Uint8Array(neq) : null;
    const push = hasNN ? new Float64Array(constrained.length) : null;
    const rhs = hasNN
      ? (tt, yy, out) => {
        raw(tt, yy, out);
        for (let m = 0; m < constrained.length; m++) {
          const i = constrained[m];
          if (yy[i] <= 0 && out[i] < 0) { if (-out[i] > push[m]) push[m] = -out[i]; out[i] = 0; heldRows[i] = 1; } else heldRows[i] = 0;
        }
        return out;
      }
      : raw;

    const f0 = new Float64Array(neq);
    rhs(t, y, f0);
    for (let i = 0; i < neq; i++) {
      if (!Number.isFinite(y[i]) || !Number.isFinite(f0[i])) {
        throw new SolverError('nonfinite', `The state or its derivative is not a number at t=${t0} (state ${i})`, t0);
      }
    }

    // --- the Jacobian, and the matrix built from it ------------------------
    const Jopt = opts.jacobian || null;
    if (!Jopt || !Jopt.pattern) throw new SolverError('jacobian', 'this solver needs a Jacobian pattern (analytic or to difference through)', t0);
    const pattern = Jopt.pattern;
    const groups = Jopt.groups || colourColumns(pattern);
    const dfdy = new Float64Array(pattern.nnz);
    const maskedValues = hasNN ? new Float64Array(pattern.nnz) : null;
    const analytic = typeof Jopt.evaluate === 'function';
    const fwork = new Float64Array(neq);
    let jacFresh = false;
    const formJacobian = (fty) => {
      npds++;
      const v = analytic ? Jopt.evaluate(t, y) : null;
      if (v) dfdy.set(v);
      else differenceJacobian(raw, t, y, fty || raw(t, y, fwork), pattern, groups, threshold, dfdy);
      jacFresh = true;
    };
    formJacobian(f0);
    const iter = makeIterationMatrix(pattern, dfdy, opts.matrix || 'auto', mass);

    // Which rows the constraint holds for the step being taken, and which the
    // matrix was formed with. Read once per step from the derivative at the
    // point the step starts from -- a matrix that followed every flicker of a
    // state hovering on zero was re-formed for ever -- and changed inside a
    // step only when a held state is found to have been released.
    const heldNow = hasNN ? new Uint8Array(neq) : null;
    const heldInW = hasNN ? new Uint8Array(neq) : null;
    const readHeld = () => { if (hasNN) heldNow.set(heldRows); };
    const heldMoved = () => {
      if (!hasNN) return false;
      for (let m = 0; m < constrained.length; m++) { const i = constrained[m]; if (heldNow[i] !== heldInW[i]) return true; }
      return false;
    };
    const releasedInW = () => {
      if (!hasNN) return false;
      let any = false;
      for (let m = 0; m < constrained.length; m++) { const i = constrained[m]; if (heldInW[i] && !heldRows[i]) { heldNow[i] = 0; any = true; } }
      return any;
    };
    // The scaled Newton system (see makeMiterBuilder): each variable in units
    // of its own weight, max(|y_i|, atol_i/rtol), as the error control sees it.
    const wscale = new Float64Array(neq);
    const scaling = opts.scaling !== false;
    let k = 1, h = 0, hTable = 0, hW = 0, kW = 0, rate = -1;
    const formW = () => {
      let current = dfdy;
      if (hasNN) {
        heldInW.set(heldNow);
        let any = false;
        for (let m = 0; m < constrained.length; m++) if (heldInW[constrained[m]]) { any = true; break; }
        if (any) {
          // A held state's derivative is identically zero: its row of the
          // Jacobian is zero, so its row of M - a·J is a row of the identity.
          maskedValues.set(dfdy);
          const { n, colPtr, rowIdx } = pattern;
          for (let j = 0; j < n; j++) for (let p = colPtr[j]; p < colPtr[j + 1]; p++) if (heldInW[rowIdx[p]]) maskedValues[p] = 0;
          current = maskedValues;
        }
      }
      if (scaling) for (let i = 0; i < neq; i++) wscale[i] = Math.max(Math.abs(y[i]), newtonThreshold[i]);
      try { iter.form(h / leading[k], current, scaling ? wscale : null); } catch (e) { throw fail(new SolverError('singular', `${e.message} (at t=${t})`, t)); }
      ndecomps++;
      hW = h; kW = k; rate = -1;
    };

    // --- the first step ---------------------------------------------------------
    // Sized from y' and an estimate of y'' out of one explicit Euler trial,
    // for the first-order start, over the differential rows only: on an
    // algebraic row f is a constraint residual, not a rate of change.
    const yp = Float64Array.from(f0);
    for (const i of idxAlg) yp[i] = 0;
    const invw = new Float64Array(neq), invwN = autoAtol ? new Float64Array(neq) : invw;
    const weigh = (ya, yb) => {
      for (let i = 0; i < neq; i++) {
        const s = Math.max(Math.abs(ya[i]), Math.abs(yb[i]));
        invw[i] = 1 / Math.max(s, threshold[i]);
        if (autoAtol) invwN[i] = 1 / Math.max(s, newtonThreshold[i]);
      }
    };
    let absh;
    if (opts.h0 != null && opts.h0 > 0) absh = opts.h0;
    else {
      weigh(y, y);
      const diffOnly = (v) => { if (!hasAlg) return v; const w = Float64Array.from(v); for (const i of idxAlg) w[i] = 0; return w; };
      const d0 = wnorm(diffOnly(y), invw) / rtol;
      const d1 = wnorm(yp, invw) / rtol;
      let guess = d0 < 1e-5 || d1 < 1e-5 ? 1e-6 : 0.01 * (d0 / d1);
      guess = Math.min(guess, hmax);
      const trial = new Float64Array(neq), ftry = new Float64Array(neq);
      for (let i = 0; i < neq; i++) trial[i] = y[i] + tdir * guess * yp[i];
      rhs(t0 + tdir * guess, trial, ftry);
      for (let i = 0; i < neq; i++) ftry[i] -= f0[i];
      let d2 = wnorm(diffOnly(ftry), invw) / rtol / guess;
      if (!Number.isFinite(d2)) d2 = 100 * d1;
      const m = Math.max(d1, d2);
      const h1 = m <= 1e-15 ? Math.max(1e-6, guess * 1e-3) : Math.sqrt(0.01 / m);
      absh = Math.min(100 * guess, h1);
    }
    absh = Math.min(hmax, Math.max(stepFloor(t0), absh));
    h = tdir * absh;
    {
      const hf = new Float64Array(neq);
      for (let i = 0; i < neq; i++) hf[i] = h * yp[i];
      table.start(y, hf);
    }
    hTable = h;
    readHeld();
    formW();

    // Events
    const events = opts.events || null;
    const nev = events ? events.n : 0;
    const vL = new Float64Array(nev), vR = new Float64Array(nev);
    if (events) events.fun(t, y, vL);
    const tStart = opts.tStart !== undefined ? opts.tStart : t0;
    let stopped = null;

    // The solution at asked-for times, off the interpolant.
    const saveAt = opts.saveAt && opts.saveAt.length ? opts.saveAt : null;
    const savedT = [], savedY = [];
    let nextSave = 0;
    if (saveAt) while (nextSave < saveAt.length && tdir * (saveAt[nextSave] - t0) <= 0) { savedT.push(saveAt[nextSave]); savedY.push(Float64Array.from(y)); nextSave++; }

    // Work arrays
    const pred = new Float64Array(neq), hist = new Float64Array(neq), d = new Float64Array(neq), ynew = new Float64Array(neq);
    const resid = new Float64Array(neq), delta = new Float64Array(neq), interp = new Float64Array(neq), errw = new Float64Array(neq);
    let tnew = t, err = 0, newtonIts = 0, stepFails = 0, belowTolRun = 0;
    let consecutive = 0, maskReforms = 0, last = false;
    let stallStep = 0, stallT = t0, stallH = 0;

    const denseAt = (tq) => table.valueAt(k, (tq - tnew) / h, interp, clampList);
    const changeStep = (factor) => {
      const hNew = tdir * Math.max(stepFloor(t), Math.abs(h) * factor);
      if (hNew !== hTable) { table.rescale(k, hNew / hTable); hTable = hNew; }
      h = hNew; consecutive = 0; maskReforms = 0;
    };
    /** Puts constrained states that `should` be onto the bound: within atol of zero and pushed past it. */
    const snapOntoBound = (should) => {
      let snapped = false;
      for (let m = 0; m < constrained.length; m++) {
        const i = constrained[m];
        if (y[i] > 0 && y[i] <= atol[i] && should(i)) { y[i] = 0; table.forget(i); negative++; snapped = true; }
      }
      if (snapped) { rhs(t, y, fwork); readHeld(); formW(); }
      return snapped;
    };
    const topOf = (v, w) => Array.from(v, (x, i) => [i, Math.abs(x * w[i])]).sort((a, b) => b[1] - a[1]).slice(0, 4);

    for (;;) {
      const hmin = stepFloor(t);
      absh = Math.min(hmax, Math.max(hmin, Math.abs(h)));
      last = false;
      let hTry = tdir * absh;
      if (1.1 * absh >= Math.abs(tfinal - t)) { hTry = tfinal - t; last = true; }
      if (hTry !== hTable) { table.rescale(k, hTry / hTable); hTable = hTry; consecutive = 0; }
      h = hTry;
      maskReforms = 0;
      if (hasNN) {
        let onBound = false;
        for (let m = 0; m < constrained.length; m++) if (y[constrained[m]] <= 0) { onBound = true; break; }
        if (onBound) rhs(t, y, fwork);
        readHeld();
      }
      if (h !== hW || k !== kW || heldMoved()) formW();

      let firstFailure = true;
      for (;;) {
        tnew = last ? tfinal : t + h;
        table.predict(k, pred);
        table.history(k, hist);
        ynew.set(pred);
        d.fill(0);
        if (hasNN) push.fill(0);
        weigh(y, ynew);
        const roundoff = 100 * EPS * wnorm(ynew, invwN);

        // The simplified Newton iteration on the correction d, against the
        // matrix M - (h/l_k)·J formed for this step and order:
        //     W·Δ = (h·f(t_{n+1}, y⁰ + d) - M·history)/l_k - M·d
        // The contraction rate measured between two corrections says how much
        // error the last one leaves; a rate remembered from an earlier step at
        // the same matrix lets a step be taken on one iteration when
        // `minNewton` allows it and that estimate is already inside the tolerance.
        let outcome = 'converged', prev = 0, rho = rate, nonfinite = false;
        const scale = 1 / leading[k];
        const newtonNorms = [];
        newtonIts = 0;
        for (let it = 1; it <= NEWTON_MAX; it++) {
          rhs(tnew, ynew, resid);
          if (mass) for (let i = 0; i < neq; i++) resid[i] = (h * resid[i] - mass[i] * hist[i]) * scale - mass[i] * d[i];
          else for (let i = 0; i < neq; i++) resid[i] = (h * resid[i] - hist[i]) * scale - d[i];
          iter.solve(resid, delta);
          nsolves++;
          newtonIts = it;
          const size = wnorm(delta, invwN);
          newtonNorms.push(size);
          if (!Number.isFinite(size)) { nonfinite = true; outcome = 'nonfinite'; break; }
          for (let i = 0; i < neq; i++) { d[i] += delta[i]; ynew[i] = pred[i] + d[i]; }
          if (size <= roundoff || size <= CONVERGED_FLOOR * rtol) break;
          if (it === 1) {
            if (minNewton <= 1 && rate >= 0 && (rate / (1 - rate)) * size <= NEWTON_TOL * rtol) break;
            prev = size;
            continue;
          }
          const ratio = size / prev;
          if (ratio >= RATE_LIMIT) {
            // A correction that has stopped shrinking. Ordinarily the step is
            // too long for the iteration. Where the right-hand side cancels so
            // heavily that its residual cannot be evaluated any finer, the
            // correction stalls at the arithmetic's floor instead, and no
            // shorter step mends that; `stagnationTol` lets such a correction
            // be taken on its size alone, at a Jacobian for this point.
            if (stagnationTol > 0 && jacFresh && size <= stagnationTol * rtol) break;
            outcome = 'slow';
            break;
          }
          rho = Math.max(ratio, RATE_FLOOR);
          const remaining = (rho / (1 - rho)) * size;
          if (remaining <= NEWTON_TOL * rtol && it >= minNewton) break;
          if (it === NEWTON_MAX || remaining * rho ** (NEWTON_MAX - it) > NEWTON_TOL * rtol) { outcome = 'slow'; break; }
          prev = size;
        }

        if (outcome !== 'converged') {
          nfailed++;
          if (opts.debug) opts.debug({ t, h, k, newtonIts, newtonNorms, nonfinite, jacobianFresh: jacFresh, top: topOf(delta, invwN), y: Float64Array.from(y), ynew: Float64Array.from(ynew), invwt: Float64Array.from(invw), del: Float64Array.from(delta) });
          // Cheapest remedy first: a state the iteration met the kink with,
          // put onto the bound; then a Jacobian from an earlier point; only
          // then a shorter step.
          if (hasNN && snapOntoBound((i) => heldRows[i])) continue;
          if (!jacFresh) { formJacobian(null); readHeld(); formW(); continue; }
          if (Math.abs(h) <= hmin) {
            // A step of the smallest size whose corrector still will not
            // converge, and no shorter step to try. Where the iterate is a
            // number this is the same escape as the error test's below: a
            // residual that cannot be evaluated any finer than the arithmetic
            // allows -- a species sitting at 1e-29 against an absolute
            // tolerance of 1e-30 after a restart -- is not mended by any step
            // size, and the implicit step itself is what puts it right. Up to
            // BELOW_TOL_RUN such steps in a row are taken and counted.
            if (nonfinite || belowTolRun >= BELOW_TOL_RUN) throw fail(atHmin(t, hmin, nonfinite));
            belowTolRun++; nbelowtol++;
            err = rtol;
            break;
          }
          changeStep(NEWTON_CUT);
          last = false;
          formW();
          continue;
        }
        // A state the matrix held whose equations, at the point the iteration
        // settled on, no longer push it below zero has been released inside
        // the step: taken again with the row restored, once.
        if (hasNN && maskReforms < 1 && releasedInW()) { maskReforms++; nfailed++; formW(); continue; }
        rate = rho;

        // --- the error test ------------------------------------------------
        // Algebraic components are included by default: the correction to the
        // predictor measures how well the polynomial tracks the constraint,
        // which for an index-1 problem is a legitimate if conservative thing
        // to control. `suppressAlgebraic` leaves them out instead, which is
        // what an index-2 system needs.
        if (suppressAlg) { errw.set(invw); for (const i of idxAlg) errw[i] = 0; err = errorConst[k] * wnorm(d, errw); }
        else err = errorConst[k] * wnorm(d, invw);
        if (!Number.isFinite(err)) throw fail(new SolverError('nonfinite', `The error estimate is not a number at t=${t}`, t));
        let forConstraint = false;
        if (hasNN) {
          let worst = 0;
          for (let m = 0; m < constrained.length; m++) { const i = constrained[m]; if (ynew[i] < 0) { const v = -ynew[i] / threshold[i]; if (v > worst) worst = v; } }
          if (worst > rtol && worst > err) { err = worst; forConstraint = true; }
        }
        if (err <= rtol) { belowTolRun = 0; break; }

        nfailed++;
        stepFails++;
        if (opts.debug) opts.debug({ t, h, k, errTest: err, top: topOf(d, invw).map(([i, v]) => [i, v * errorConst[k]]), y: Float64Array.from(y), ynew: Float64Array.from(ynew), invwt: Float64Array.from(invw) });
        // A state within its tolerance of the bound and pushed past it is put
        // onto the bound and the step tried again from there.
        if (forConstraint && snapOntoBound((i) => ynew[i] < 0)) continue;
        if (Math.abs(h) <= hmin) {
          // A step of the smallest size that still fails the error test. Up
          // to BELOW_TOL_RUN of them in a row are taken and counted, so a run
          // that leaned on it says so: after a restart from an interpolated
          // state a species with a lifetime of femtoseconds is off its steady
          // state by more than the tolerance, and no step size mends that --
          // the implicit step itself does.
          if (belowTolRun < BELOW_TOL_RUN) { belowTolRun++; nbelowtol++; break; }
          throw fail(atHmin(t, hmin, false));
        }
        let factor;
        if (firstFailure) {
          firstFailure = false;
          factor = Math.max(0.1, SAFETY * (rtol / err) ** (1 / (k + 1)));
          // Would the order below have allowed a longer step? Its error is
          // read off ∇^k y_{n+1}, the table's column k plus the correction;
          // a drop in order never buys a longer step than the one that failed.
          if (k > 1) {
            const colk = table.cols[k];
            for (let i = 0; i < neq; i++) errw[i] = colk[i] + d[i];
            const errLower = errorConst[k - 1] * wnorm(errw, invw);
            const lower = Math.max(0.1, SAFETY_LOWER * (rtol / errLower) ** (1 / k));
            if (lower > factor) { k--; factor = Math.min(1, lower); }
          }
        } else factor = 0.5;
        changeStep(factor);
        last = false;
        formW();
      }

      // --- accepted ----------------------------------------------------------
      nsteps++;
      if (autoAtol) {
        for (let i = 0; i < neq; i++) {
          const want = rtol * Math.abs(ynew[i]);
          if (want > atol[i]) { atol[i] = want; threshold[i] = want / rtol; }
        }
      }
      trace.push({ t, h, k, err, newton: newtonIts, failed: stepFails });
      if (trace.length > 12) trace.shift();
      stepFails = 0;
      if (nsteps > maxSteps) throw fail(new SolverError('steps', `More than ${maxSteps} steps at t=${t}`, t));
      if (nsteps - stallStep >= STALL_WINDOW) {
        if (Math.abs(tnew - stallT) < span * STALL_SPAN_FRACTION && Math.abs(h) <= stallH * 2) {
          throw fail(new SolverError('stalled', `The solver stopped making progress at t=${tnew}`, tnew));
        }
        stallStep = nsteps; stallT = tnew; stallH = Math.abs(h);
      }

      table.advance(k, d);
      if (hasNN) {
        for (let m = 0; m < constrained.length; m++) {
          const i = constrained[m];
          if (y[i] < 0) { y[i] = 0; negative++; table.forget(i); }
        }
      }

      if (events) {
        events.fun(tnew, y, vR);
        const at = (tq) => { const o = new Float64Array(nev); events.fun(tq, denseAt(tq), o); return o; };
        const hit = anyCrossing(vL, vR, events.direction, events.enabled)
          ? firstCrossing(at, t, vL, tnew, vR, events.direction, tStart, events.enabled) : null;
        if (hit) {
          // The table is re-expressed to end at the crossing, with the step
          // from the start of this one to it, so the state there is its first
          // column and the interpolant below covers [t, tE].
          const tE = hit.t;
          table.regrid(k, (tE - tnew) / h, (tE - t) / h);
          h = tE - t; hTable = h; tnew = tE; consecutive = 0;
          if (clampList) for (const i of clampList) if (y[i] < 0) y[i] = 0;
          vR.set(hit.values);
          stopped = { t: tE, y: Float64Array.from(y), which: hit.which };
          last = true;
        }
        vL.set(vR);
      }

      if (saveAt) {
        while (nextSave < saveAt.length && tdir * (tnew - saveAt[nextSave]) >= 0) {
          const tq = saveAt[nextSave];
          savedT.push(tq);
          savedY.push(Float64Array.from(tq === tnew ? y : denseAt(tq)));
          nextSave++;
        }
      }
      if (opts.onAccepted) opts.onAccepted(tnew, y);
      if (opts.onStep && (nsteps & 15) === 0 && opts.onStep(tnew, nsteps) === false) throw new SolverError('aborted', 'Aborted', tnew);

      t = tnew;
      if (last) break;

      // --- the next step's size and order -----------------------------------
      // Only after k+1 steps at constant step and order, when the whole table
      // is made of real steps at this spacing and the differences an order
      // change is judged by can be believed.
      consecutive++;
      if (consecutive >= k + 1) {
        const allowed = (e, q, safety) => (e > 0 ? Math.min(MAX_GROWTH, safety * (rtol / e) ** (1 / (q + 1))) : MAX_GROWTH);
        let bestK = k, best = allowed(err, k, SAFETY);
        if (k > 1) {
          const g = allowed(errorConst[k - 1] * wnorm(table.cols[k], invw), k - 1, SAFETY_LOWER);
          if (g > best) { best = g; bestK = k - 1; }
        }
        if (k < maxk) {
          const g = allowed(errorConst[k + 1] * wnorm(table.cols[k + 2], invw), k + 1, SAFETY_HIGHER);
          if (g > best) { best = g; bestK = k + 1; }
        }
        if (best > 1) { k = bestK; h *= best; consecutive = 0; }
      }
      jacFresh = false;
    }

    return {
      t, y: Float64Array.from(y), stopped,
      series: saveAt ? { t: Float64Array.from(savedT), y: savedY } : null,
      stats: { nsteps, nfailed, nfevals, npds, ndecomps, nsolves, nbelowtol, negative, sparse: iter.info.sparse, fill: iter.info.fill, ordering: iter.info.ordering, solver: bdf ? 'BDF' : 'NDF' },
    };
  }

  function atHmin(t, hmin, nonfinite) {
    if (nonfinite) return new SolverError('nonfinite', `The state or its derivative became non-finite at t=${t}, and no step size above the smallest allowed (${hmin}) gives a number.`, t);
    return new SolverError('tolerance', `Failure at t=${t}: unable to meet the integration tolerances without reducing the step size below the smallest value allowed (${hmin}).`, t);
  }

  /* ======================================================================
     8. Driver: a compiled model over [0, tend] with its events
     ====================================================================== */
  /**
   * Read per-species absolute tolerances out of a block of text.
   *
   * One `SPECIES VALUE` a line -- `=` and `:` do as separators, `#` and `!`
   * start a comment. The syntax is deliberately forgiving about spacing and
   * case and deliberately strict about everything else: a line it cannot read
   * is reported rather than skipped, because a silently ignored tolerance
   * looks exactly like one that did not help.
   *
   * Names are not checked here -- that needs a compiled model, and this is
   * called from the panel as the reader types, before there is one.
   *
   * @param {string} text
   * @returns {{values: Object<string, number>, errors: string[]}}
   */
  function parseSpeciesTolerances(text) {
    const values = Object.create(null);
    const errors = [];
    if (!text) return { values, errors };
    // Split on newlines alone, so a reported line number is the line the
    // reader is looking at; several entries may still share one line, comma-
    // or semicolon-separated.
    String(text).split(/\r?\n/).forEach((raw, i) => {
      const line = raw.replace(/[#!].*$/, '').trim();
      if (!line) return;
      line.split(/[,;]/).forEach((entry) => {
        const item = entry.trim();
        if (!item) return;
        const m = /^([A-Za-z][A-Za-z0-9_]*)\s*(?:[=:]|\s)\s*(\S+)$/.exec(item);
        if (!m) {
          errors.push(`line ${i + 1}: "${item}" is not a species name and a number`);
          return;
        }
        const v = Number(m[2]);
        if (!(v >= 0) || !Number.isFinite(v)) {
          errors.push(`line ${i + 1}: "${m[2]}" is not a tolerance (it must be a number, and not negative)`);
          return;
        }
        values[m[1].toUpperCase()] = v;
      });
    });
    return { values, errors };
  }

  /**
   * The absolute tolerance as one number per species.
   *
   * `atol` is the floor every species gets; `overrides` names the ones that
   * get something else. Returns null when there is nothing to override, so
   * that the common case still hands the solver the scalar it started with
   * and nothing downstream has to care.
   */
  function speciesAtol(species, atol, overrides) {
    const names = overrides ? Object.keys(overrides) : [];
    if (!names.length) return null;
    const n = species.length;
    const out = typeof atol === 'number' || atol == null
      ? new Float64Array(n).fill(atol ?? 1e-6)
      : Float64Array.from(atol);
    const index = new Map();
    for (let i = 0; i < n; i++) index.set(String(species[i]).toUpperCase(), i);
    const unknown = [];
    for (const name of names) {
      const i = index.get(name.toUpperCase());
      if (i === undefined) unknown.push(name);
      else out[i] = overrides[name];
    }
    if (unknown.length) {
      throw new SolverError('atol',
        `This model has no species called ${unknown.map((u) => `"${u}"`).join(', ')}. `
        + 'Per-species tolerances are matched by name against the compiled model.', 0);
    }
    return out;
  }

  /**
   * Moves the algebraic variables onto their constraints before the run.
   *
   * A differential-algebraic system has to start from a state that satisfies
   * its own constraints. FACSIMILE required the author to supply one ("close
   * enough to the exact solution for iterative refinement to work") and so,
   * at first, did this; what that produces when the guess is off is not a
   * warning but a stall. The circle problem of the FACSIMILE User Guide,
   * started at its documented y2 = -0.9 when the constraint wants -0.866,
   * takes a first step in which the algebraic variable jumps by 0.034. The
   * error test measures that jump, rejects the step, and halves h -- and the
   * jump does not shrink with h, because the constraint has to hold at the
   * new point whatever h is. The step size collapses to the denormal floor
   * and the run never leaves t = 0.
   *
   * So the constraints are solved here instead, by Newton on the algebraic
   * variables alone with the differential ones held where the author put
   * them. That is the index-1 initialisation: with y fixed, g(y, z) = 0
   * determines z. The differential variables are never touched, so what the
   * author wrote for them is what is integrated.
   *
   * @returns {{solved: boolean, iterations: number, residual: number, moved: number, why: string}}
   */
  function consistentInitial(model, t, y, opts = {}) {
    const mass = model.mass;
    const alg = [];
    if (mass) for (let i = 0; i < model.nspecies; i++) if (!mass[i]) alg.push(i);
    if (!alg.length) return { solved: true, iterations: 0, residual: 0, moved: 0, why: '' };

    const n = model.nspecies, na = alg.length;
    const maxit = opts.maxIterations || 30;
    const rtol = opts.rtol || 1e-10;
    // Where each (algebraic row, algebraic column) entry sits in the Jacobian
    // values, worked out once from the pattern.
    const at = new Int32Array(na * na).fill(-1);
    const col = new Int32Array(n).fill(-1);
    alg.forEach((j, c) => { col[j] = c; });
    const pat = model.pattern;
    const rowSlot = new Int32Array(n).fill(-1);
    alg.forEach((i, r) => { rowSlot[i] = r; });
    for (let j = 0; j < pat.n; j++) {
      const c = col[j];
      if (c < 0) continue;
      for (let k = pat.colPtr[j]; k < pat.colPtr[j + 1]; k++) {
        const r = rowSlot[pat.rowIdx[k]];
        if (r >= 0) at[r * na + c] = k;
      }
    }

    const lu = new DenseLU(na);
    const V = new Float64Array(model.nnz);
    const f = new Float64Array(n);
    const g = new Float64Array(na), rhs = new Float64Array(na), dz = new Float64Array(na);
    const before = Float64Array.from(y);
    const gnorm = () => { let m = 0; for (let i = 0; i < na; i++) m = Math.max(m, Math.abs(g[i])); return m; };
    const residual = () => { model.rhs(t, y, f); for (let i = 0; i < na; i++) g[i] = f[alg[i]]; return gnorm(); };

    let r0 = residual();
    let it = 0;
    let why = '';
    for (; it < maxit; it++) {
      // Converged when the correction is negligible against the variables
      // themselves, which is the only scale a constraint residual has.
      model.jac(t, y, V);
      for (let r = 0; r < na; r++) {
        const row = lu.lu[r];
        row.fill(0);
        for (let c = 0; c < na; c++) { const k = at[r * na + c]; if (k >= 0) row[c] = V[k]; }
      }
      lu.factorizeInPlace();
      if (lu.singular) {
        why = `the constraints do not determine ${model.species[alg[lu.failColumn]] || lu.failColumn} at the start`;
        break;
      }
      for (let i = 0; i < na; i++) rhs[i] = -g[i];
      lu.solve(rhs, dz);
      // A halving line search: Newton on a constraint can overshoot, and a
      // step that makes the residual worse is not an improvement.
      let lambda = 1, ok = false;
      const keep = alg.map((i) => y[i]);
      for (let trial = 0; trial < 12; trial++) {
        for (let i = 0; i < na; i++) y[alg[i]] = keep[i] + lambda * dz[i];
        const rn = residual();
        if (rn <= r0 || rn === 0) { r0 = rn; ok = true; break; }
        lambda *= 0.5;
      }
      if (!ok) {
        for (let i = 0; i < na; i++) y[alg[i]] = keep[i];
        residual();
        why = 'the Newton iteration on the constraints stopped improving';
        break;
      }
      let small = true;
      for (let i = 0; i < na; i++) {
        const scale = Math.max(Math.abs(y[alg[i]]), 1e-30);
        if (Math.abs(lambda * dz[i]) > rtol * scale) { small = false; break; }
      }
      if (small) { it++; why = ''; break; }
    }
    let moved = 0;
    for (let i = 0; i < na; i++) {
      const j = alg[i];
      moved = Math.max(moved, Math.abs(y[j] - before[j]) / Math.max(Math.abs(y[j]), 1e-30));
    }
    return { solved: !why, iterations: it, residual: r0, moved, why };
  }

  /**
   * Integrates a FacsimileModel-compiled model, restarting at each terminal
   * event after applying it.
   *
   * @param {object} model   from FacsimileModel.compile
   * @param {object} opts    solver ('ndf', 'bdf' or a function), tend (s), rtol, atol,
   *                         atolSpecies ({NAME: value} overriding atol for those species),
   *                         nonNegative (bool), matrix, jacobianMode ('analytic'|'numeric'),
   *                         maxOrder, bdf, onProgress(t, nsteps), maxPoints (how many
   *                         points to keep; the store is thinned to stay inside it),
   *                         outputTimes (seconds; defaults to the model's <TIMES> section)
   * @returns {{t: Float64Array, y: Float64Array[], grid: object|null, events: object[], stats: object}}
   */
  function runModel(model, opts = {}) {
    const n = model.nspecies;
    // A name, or a solver of the caller's own -- which is how the ode_julia
    // solvers are run: facsimile-ode-julia.js wraps each one in this same
    // signature, reporting its steps the same way, so everything below is
    // unchanged whichever is chosen.
    // A model with algebraic variables is a differential-algebraic system,
    // and only the solver in this file knows what to do with the mass matrix.
    // The ported ones would read a constraint residual as a rate of change
    // and integrate it, which is not a slower answer but a wrong one, so they
    // are refused rather than allowed to produce it.
    if (model.nalgebraic && typeof opts.solver === 'function') {
      throw new SolverError('solver',
        `This model has ${model.nalgebraic} algebraic variable${model.nalgebraic === 1 ? '' : 's'} `
        + `(${(model.algebraicNames || []).join(', ')}), which makes it a differential-algebraic `
        + 'system. The ported solvers do not take a mass matrix and would integrate the '
        + 'constraint residuals as if they were rates of change. Use NDF or BDF.', 0);
    }
    let solver;
    if (typeof opts.solver === 'function') solver = opts.solver;
    // 'ndf' and 'bdf' are the same integrator: the kappa terms that make an
    // NDF out of a BDF are switched off by `bdf`, which is the only difference.
    else if (opts.solver == null || opts.solver === 'ndf' || opts.solver === 'bdf') solver = ndf;
    else {
      // A name nothing here answers to -- a Julia port where the adapter did
      // not load, most likely. Refused rather than quietly served by the NDF,
      // which would report the wrong solver's answer as that one's.
      throw new SolverError('solver',
        `There is no solver called "${opts.solver}" here. The ported solvers are `
        + 'wired up in facsimile-ode-julia.js, which has to be loaded first.', 0);
    }
    const tend = opts.tend;
    if (!(tend > 0)) throw new SolverError('span', 'The simulated time must be positive', 0);
    const y0 = model.initialState(0);
    // The constraints, before anything is integrated. See consistentInitial.
    let startInfo = null;
    if (model.nalgebraic && opts.consistentStart !== false) {
      startInfo = consistentInitial(model, 0, y0, { rtol: opts.rtol });
      if (!startInfo.solved) {
        throw new SolverError('consistent',
          `The algebraic variables could not be put on their constraints at t = 0: ${startInfo.why}. `
          + `The largest residual left is ${startInfo.residual.toExponential(3)}. Give <INITIAL> a `
          + 'closer starting value, or check that each constraint determines its own variable.', 0);
      }
    }
    const f = (t, y, out) => model.rhs(t, y, out);
    const V = new Float64Array(model.nnz);
    const analytic = opts.jacobianMode !== 'numeric';
    const jacobian = {
      pattern: model.pattern,
      evaluate: analytic
        ? (t, y) => {
          model.jac(t, y, V);
          for (let k = 0; k < V.length; k++) if (!Number.isFinite(V[k])) return null;
          return V;
        }
        : undefined,
    };
    const nonNegative = opts.nonNegative ? new Uint8Array(n).fill(1) : null;
    const events = model.nevents
      ? {
        n: model.nevents,
        // An event says which way it is to be crossed: up (the default), down,
        // or either. 0 means either, which is what the crossing test reads a
        // zero direction as.
        direction: model.eventDirections && model.eventDirections.length === model.nevents
          ? Int8Array.from(model.eventDirections) : new Int8Array(model.nevents).fill(1),
        // An event marked `once` is switched off here after it has fired,
        // which is what makes it FACSIMILE's WHEN rather than its WHENEVER.
        // The mask lives for the whole run, not for one segment, so a
        // one-shot event stays shot across the restart at every later event.
        enabled: new Uint8Array(model.nevents).fill(1),
        fun: (t, y, out) => model.eventValues(t, y, out),
      }
      : null;
    const T = [0], Y = [Float64Array.from(y0)];
    // How many points come back, whatever the solver does to get there.
    //
    // Every accepted step used to be kept, which is fine at a few thousand of
    // them and fatal at a few hundred thousand: on this model that was 185 MB
    // of retained state after a minute and climbing at about 3 MB a second.
    // The tab does not so much freeze as run the machine out of memory, and by
    // then there is no clicking Stop. Bounded here instead, at a resolution
    // far past what a chart or a table can show.
    const maxPoints = Math.max(1000, opts.maxPoints || 20000);
    let stride = 1;   // one point kept per `stride` accepted steps
    let since = 0;
    const remember = (t, yy) => {
      if (++since < stride) return;
      since = 0;
      T.push(t);
      Y.push(Float64Array.from(yy));
      if (T.length < maxPoints) return;
      // Full: drop every other point and keep half as often from here on. The
      // sample stays uniform in step number, which is where the detail is --
      // dense through a transient the solver crept over, sparse where it flew.
      let w = 1;
      for (let r = 2; r < T.length; r += 2) { T[w] = T[r]; Y[w] = Y[r]; w++; }
      T.length = w;
      Y.length = w;
      stride *= 2;
    };
    /* ---- the output grid ---------------------------------------------------
       Values at times the model asked for rather than at the steps the solver
       chose, which is what FACSIMILE's WHEN/WHENEVER lists give and what a
       table meant for comparison needs. Between the two accepted steps that
       bracket a wanted time the solution is interpolated by the cubic through
       both ends and both derivatives; that costs two extra derivative
       evaluations per bracket that holds a wanted time, and nothing at all
       where none does. Every solver on the menu is served the same way, which
       reading each one's own interpolant would not be.                      */
    // An `outputTimes` that was given wins, even when it is empty: that is how
    // a caller says "no grid" for a model whose text asks for one. Only an
    // absent option falls back to the model's own <TIMES> section.
    const asked = opts.outputTimes !== undefined ? opts.outputTimes : model.outputTimes;
    const wanted = asked && asked.length ? asked : null;
    const gridT = [], gridY = [];
    // The mass diagonal, when there is anything algebraic to look after.
    const algMass = model.nalgebraic ? model.mass : null;
    const gridModel = model;
    let gi = 0;
    let prevT = 0;
    // One buffer for the previous step, refilled rather than replaced: this
    // runs on every accepted step, and a run that takes hundreds of thousands
    // of them is exactly the case the ceiling on the stored points exists for.
    const prevY = wanted ? Float64Array.from(y0) : null;
    const fa = wanted ? new Float64Array(n) : null;
    const fb = wanted ? new Float64Array(n) : null;
    if (wanted) {
      while (gi < wanted.length && wanted[gi] <= 0) {
        gridT.push(wanted[gi] < 0 ? 0 : wanted[gi]);
        gridY.push(Float64Array.from(y0));
        gi++;
      }
    }
    const fillGrid = (t1, y1) => {
      if (!wanted) return;
      if (!(t1 > prevT)) { prevT = t1; prevY.set(y1); return; }
      if (gi < wanted.length && wanted[gi] <= t1) {
        const h = t1 - prevT;
        model.rhs(prevT, prevY, fa);
        model.rhs(t1, y1, fb);
        while (gi < wanted.length && wanted[gi] <= t1) {
          const tq = wanted[gi];
          const u = Math.min(1, Math.max(0, (tq - prevT) / h));
          const u2 = u * u, u3 = u2 * u;
          const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u;
          const h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
          const yq = new Float64Array(n);
          for (let i = 0; i < n; i++) {
            // An algebraic variable has no derivative -- what f holds on its
            // row is a residual -- so the two Hermite slope terms are dropped
            // for it and the cubic runs through the two values alone.
            yq[i] = (algMass && !algMass[i])
              ? h00 * prevY[i] + h01 * y1[i]
              : h00 * prevY[i] + h10 * h * fa[i] + h01 * y1[i] + h11 * h * fb[i];
          }
          // And then put back on its constraint. Interpolating between two
          // points that each satisfy g = 0 does not give a point that does:
          // on Robertson's problem the reported sum of the three species was
          // out by 3e-4 where the solver's own steps hold it to rounding.
          if (algMass) consistentInitial(gridModel, tq, yq, { rtol: 1e-12 });
          gridT.push(tq);
          gridY.push(yq);
          gi++;
        }
      }
      prevT = t1;
      prevY.set(y1);
    };

    const eventLog = [];
    const total = { nsteps: 0, nfailed: 0, nfevals: 0, npds: 0, ndecomps: 0, nsolves: 0, nbelowtol: 0, negative: 0, segments: 0 };
    // One array for the whole run when the tolerance is allowed to follow the
    // solution, so that what a species has already reached is remembered
    // across the restart at each event.
    // Per-species tolerances, if any: resolved once against the compiled
    // species list, so an unknown name is refused before the run rather than
    // ignored during it.
    const baseAtol = speciesAtol(model.species, opts.atol, opts.atolSpecies) ?? opts.atol;
    const runAtol = opts.autoAtol
      ? (typeof baseAtol === 'number' || baseAtol == null
        ? new Float64Array(n).fill(baseAtol ?? 1e-6) : Float64Array.from(baseAtol))
      : baseAtol;
    let t0 = 0, y = y0, info = null, stoppedBy = null;
    const started = Date.now();
    for (let seg = 0; seg < 50; seg++) {
      total.segments++;
      let res;
      try {
        res = solver(f, t0, tend, y, {
        rtol: opts.rtol, atol: runAtol, maxOrder: opts.maxOrder, bdf: opts.solver === 'bdf' || !!opts.bdf, hmax: opts.hmax, norm: opts.norm, debug: opts.debug, scaling: opts.scaling, minNewton: opts.minNewton, stagnationTol: opts.stagnationTol,
        nonNegative, jacobian, matrix: opts.matrix || 'auto', events, tStart: seg === 0 ? undefined : t0,
        mass: model.mass, suppressAlgebraic: opts.suppressAlgebraic,
        maxSteps: opts.maxSteps,
        // Named one by one rather than spread, so that a solver can only be
        // handed what this driver knows it means. The cost of that is that a
        // new option has to be added here as well as at both ends, and
        // forgetting to is silent -- the knob simply does nothing.
        minOrder: opts.minOrder, kappa: opts.kappa, maxJacAge: opts.maxJacAge,
        smoothEst: opts.smoothEst, belowTolRun: opts.belowTolRun,
        autoAtol: opts.autoAtol,
        onAccepted: (t, yy) => { fillGrid(t, yy); remember(t, yy); },
        onStep: opts.onProgress ? (t, ns) => opts.onProgress(t, ns + total.nsteps, T.length) : null,
        });
      } catch (e) {
        // Hand back what was integrated, so a failed run can still be looked at.
        e.partial = {
          t: Float64Array.from(T), y: Y, events: eventLog,
          grid: wanted ? { t: Float64Array.from(gridT), y: gridY } : null,
        };
        throw e;
      }
      for (const key of ['nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'nbelowtol', 'negative']) total[key] += res.stats[key] || 0;
      info = res.stats;
      // Where a segment ends is worth keeping whatever the thinning says: it
      // is the answer at the end of the run, or the state an event fired at.
      fillGrid(res.t, res.y);
      if (T[T.length - 1] !== res.t) { T.push(res.t); Y.push(Float64Array.from(res.y)); }
      if (!res.stopped) break;
      // Apply the event and continue from there.
      const which = res.stopped.which[0];
      if (!(res.stopped.t > t0)) {
        // The event has fired at the instant it was applied. The solvers here
        // step past a crossing that is still resting on zero at the start of a
        // segment; one that cannot would restart for ever, so it says so.
        throw new SolverError('events',
          `The event "${(model.events[which] || {}).shown || (model.events[which] || {}).expr || which}" fires again at the `
          + `instant it was applied (t = ${res.stopped.t}). This solver cannot step past a `
          + 'crossing that stays on zero; the NDF can.', res.stopped.t);
      }
      const ev = model.events[which] || {};
      // A pure stop event changes nothing: applying it would still recompute
      // the run constants at the event time, which is a side effect it never
      // asked for.
      const changed = ev.assigns && ev.assigns.length ? model.applyEvent(which, res.stopped.t, y0) : [];
      // An event changes the constants, so it can move the constraints; the
      // state has to be put back on them before the next segment starts.
      if (model.nalgebraic && changed.length && opts.consistentStart !== false) {
        const again = consistentInitial(model, res.stopped.t, res.stopped.y, { rtol: opts.rtol });
        if (!again.solved) {
          throw new SolverError('consistent',
            `After the event "${ev.expr}" the algebraic variables could not be put back on their `
            + `constraints: ${again.why}.`, res.stopped.t);
        }
      }
      if (ev.once) events.enabled[which] = 0;
      eventLog.push({
        t: res.stopped.t, event: which, expr: ev.shown || ev.expr, changed,
        stop: !!ev.stop, once: !!ev.once,
      });
      if (ev.stop) { stoppedBy = { event: which, expr: ev.expr, t: res.stopped.t }; break; }
      t0 = res.stopped.t;
      y = res.stopped.y;
      if (t0 >= tend) break;
    }
    return {
      t: Float64Array.from(T), y: Y, events: eventLog,
      grid: wanted ? { t: Float64Array.from(gridT), y: gridY, wanted: wanted.length } : null,
      stats: {
        ...total, sparse: info.sparse, fill: info.fill, ordering: info.ordering, solver: info.solver,
        nnz: model.nnz, n, points: T.length, stride, stoppedBy, consistentStart: startInfo,
        nalgebraic: model.nalgebraic || 0,
        seconds: (Date.now() - started) / 1000,
      },
    };
  }

  return { ndf, runModel, consistentInitial, parseSpeciesTolerances, speciesAtol, SolverError, CSC, cscFromTriplets, SparseLU, DenseLU, makeIterationMatrix, colourColumns, differenceJacobian, reverseCuthillMcKee, firstCrossing, crossingTolerance };
});
