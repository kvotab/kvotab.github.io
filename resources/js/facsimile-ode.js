/* ==========================================================================
   STIFF ODE SOLVERS WITH A SPARSE ITERATION MATRIX

   One integrator for dy/dt = f(t, y), fed an analytic Jacobian as the values
   of a fixed sparsity pattern (compressed sparse column):

     ndf   variable-order NDF/BDF, orders 1-5

   and the linear algebra behind it: I - h*J is assembled in CSC and
   factorised by a Gilbert-Peierls left-looking LU with partial pivoting and a
   reverse Cuthill-McKee ordering, or densely when a trial factorisation shows
   the sparse factor filling in. The choice is measured, not assumed, and is
   reported in the run's statistics.

   The method is the numerical differentiation formulas of Shampine and
   Reichelt (SIAM J. Sci. Comput. 18 (1997) 1-22): backward differentiation
   with an extra term in the highest difference, weighted by kappa, which buys
   a longer step at the same accuracy for orders 1-5. Setting every kappa to
   zero -- the `bdf` option -- leaves the plain variable-step BDF. The numerics
   follow the ecolego-js port of the same formulas (src/ode/ndf.js, sparse.js).

   Conventions: f(t, y, out) fills and returns `out` (Float64Array); the
   Jacobian object is { pattern: {n, nnz, colPtr, rowIdx}, evaluate(t, y) ->
   Float64Array | null }; results are { t: Float64Array, y: Float64Array[] }.

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
       * M := I - a*J, optionally in the scaled variables y_i / w_i:
       * M_ij = delta_ij - a J_ij w_j / w_i. The species of this kind of model
       * span forty orders of magnitude, and without the scaling the pivoting
       * of either factorisation is decided by the largest coefficients and the
       * corrections for the trace species come out wrong.
       */
      update(a, Jvalues, w) {
        Mx.fill(0);
        if (w) {
          for (let j = 0; j < n; j++) {
            const wj = w[j];
            for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) Mx[jToM[p]] = -a * Jvalues[p] * wj / w[rowOf[p]];
          }
        } else {
          for (let p = 0; p < nzJ; p++) Mx[jToM[p]] = -a * Jvalues[p];
        }
        for (let i = 0; i < n; i++) Mx[diagPos[i]] += 1;
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
    /** Factors I - a*J where J is given through a pattern and its values; w scales as in makeMiterBuilder. */
    formAndFactor(a, pattern, values, w) {
      const n = this.n, lu = this.lu;
      for (let i = 0; i < n; i++) lu[i].fill(0);
      for (let j = 0; j < n; j++) {
        const wj = w ? w[j] : 1;
        for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) {
          const i = pattern.rowIdx[p];
          lu[i][j] = -a * values[p] * (w ? wj / w[i] : 1);
        }
      }
      for (let i = 0; i < n; i++) lu[i][i] += 1;
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
  function makeIterationMatrix(pattern, values, mode = 'auto') {
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
          dense.formAndFactor(a, pattern, current, wScale);
          if (dense.singular) throw new Error(`The iteration matrix I - h*J is singular at column ${dense.failColumn}`);
        },
        solve(rhs, out) { return scaledSolve(dense, rhs, out); },
      };
    }
    const builder = makeMiterBuilder(pattern);
    const factors = new SparseLU(n);
    // One real factorisation of each ordering decides: the fill of the factor,
    // not the sparsity of the pattern, is what the solve costs.
    const M = builder.update(1e-3, values);
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
          dense.formAndFactor(a, pattern, current, wScale);
          if (dense.singular) throw new Error(`The iteration matrix I - h*J is singular at column ${dense.failColumn}`);
        },
        solve(rhs, out) { return scaledSolve(dense, rhs, out); },
      };
    }
    info.sparse = true;
    return {
      info,
      form(a, current, w) {
        keepScale(w);
        factors.factorize(builder.update(a, current, wScale), { q });
        if (factors.singular) throw new Error(`The iteration matrix I - h*J is singular at column ${factors.failColumn}`);
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
  function numjacPattern(f, t, y, f0, pattern, groups, threshold, out) {
    const n = y.length;
    const { colPtr, rowIdx } = pattern;
    const ydel = new Float64Array(n);
    const fd = new Float64Array(n);
    const del = new Float64Array(n);
    for (let j = 0; j < n; j++) {
      let d = SQRT_EPS * Math.max(Math.abs(y[j]), threshold[j]);
      if (d === 0) d = SQRT_EPS;
      d = (y[j] + d) - y[j];
      del[j] = f0[j] >= 0 ? d : -d;
    }
    for (const group of groups) {
      ydel.set(y);
      for (const j of group) ydel[j] += del[j];
      f(t, ydel, fd);
      for (const j of group) {
        for (let k = colPtr[j]; k < colPtr[j + 1]; k++) { const i = rowIdx[k]; out[k] = (fd[i] - f0[i]) / del[j]; }
      }
    }
    return out;
  }

  /* ======================================================================
     6. Event location on an interpolant
     ====================================================================== */
  function crosses(vL, vR, dir, i) {
    if (Math.sign(vL[i]) === Math.sign(vR[i])) return false;
    return dir[i] * (vR[i] - vL[i]) >= 0;
  }
  function anyCrossing(vL, vR, dir) {
    for (let i = 0; i < vL.length; i++) if (crosses(vL, vR, dir, i)) return true;
    return false;
  }
  /**
   * Earliest crossing in (tL, tR], or null. `valuesAt(t)` evaluates the event
   * functions on the solver's interpolant. `tStart` is where the segment
   * began: a crossing whose bracket never leaves it is the event that stopped
   * the previous segment, still on zero, and is stepped past.
   */
  function firstCrossing(valuesAt, tL, vL, tR, vR, dir, tStart) {
    if (!anyCrossing(vL, vR, dir)) return null;
    const n = vL.length;
    const tdir = Math.sign(tR - tL);
    const tol = Math.min(Math.abs(tR - tL), 128 * Math.max(Math.abs(tL), Math.abs(tR), 1) * EPS);
    let lo = tL, hi = tR, vlo = vL, vhi = vR;
    for (;;) {
      for (let iter = 0; iter < 80 && Math.abs(hi - lo) > tol; iter++) {
        let mid;
        let resting = false;
        if (lo === tL) for (let i = 0; i < n; i++) if (vlo[i] === 0 && vhi[i] !== 0 && crosses(vlo, vhi, dir, i)) resting = true;
        if (resting) mid = lo + tdir * 0.5 * tol;
        else {
          let frac = 1;
          for (let i = 0; i < n; i++) {
            if (!crosses(vlo, vhi, dir, i)) continue;
            const a = vlo[i], b = vhi[i];
            let f = a === b ? 0.5 : -a / (b - a);
            if (!(f > 0 && f < 1)) f = 0.5;
            if (f < frac) frac = f;
          }
          mid = lo + frac * (hi - lo);
          if (!(mid > Math.min(lo, hi) && mid < Math.max(lo, hi))) mid = 0.5 * (lo + hi);
        }
        const vmid = valuesAt(mid);
        if (anyCrossing(vlo, vmid, dir)) { hi = mid; vhi = vmid; } else { lo = mid; vlo = vmid; }
      }
      if (tStart !== undefined && lo === tStart) {
        if (Math.abs(tR - hi) <= tol) return null;
        lo = hi + tdir * 0.5 * tol;
        vlo = valuesAt(lo);
        hi = tR; vhi = vR;
        if (!anyCrossing(vlo, vhi, dir)) return null;
        continue;
      }
      const which = [];
      for (let i = 0; i < n; i++) if (crosses(vlo, vhi, dir, i)) which.push(i);
      return { t: hi, values: vhi, which };
    }
  }

  /* ======================================================================
     7. ndf: variable-order NDF/BDF, orders 1-5
     ====================================================================== */
  const G = [1, 1.5, 11 / 6, 25 / 12, 137 / 60];
  const DIFUFULL = [
    [-1, -2, -3, -4, -5],
    [0, 1, 3, 6, 10],
    [0, 0, -1, -4, -10],
    [0, 0, 0, 1, 5],
    [0, 0, 0, 0, -1],
  ];

  function ulp(x) {
    const a = Math.abs(x);
    if (a === 0) return 2 ** -1074;
    const e = Math.floor(Math.log2(a));
    return 2 ** (e - 52);
  }

  /** dif(:,K) = dif(:,K) * difRU(K,K), the rescale after a change of h or k. */
  function updateDif(ratio, difU, neq, k, maxk, dif) {
    if (k === 1) {
      let difRU11 = 0;
      for (let j = 0; j < k; j++) for (let m = 0; m < maxk; m++) difRU11 += -(m + 1) * ratio * difU[m][j];
      for (let i = 0; i < neq; i++) dif[0][i] *= difRU11;
      return;
    }
    const cp = [];
    for (let i = 0; i < k; i++) cp.push(new Array(maxk));
    for (let j = 0; j < maxk; j++) cp[0][j] = -(j + 1) * ratio;
    for (let i = 1; i < k; i++) for (let j = 0; j < maxk; j++) cp[i][j] = (cp[i - 1][j] * (i - (j + 1) * ratio)) / (i + 1);
    const difRU = [];
    for (let i = 0; i < k; i++) difRU.push(new Array(k));
    for (let j = 0; j < k; j++) {
      for (let i = 0; i < k; i++) {
        let s = 0;
        for (let m = 0; m < maxk; m++) s += cp[i][m] * difU[m][j];
        difRU[i][j] = s;
      }
    }
    const old = [];
    for (let i = 0; i < k; i++) old.push(Float64Array.from(dif[i]));
    for (let j = 0; j < k; j++) {
      dif[j].fill(0);
      for (let i = 0; i < k; i++) {
        const c = difRU[i][j];
        if (c === 0) continue;
        const row = old[i], dst = dif[j];
        for (let m = 0; m < neq; m++) dst[m] += row[m] * c;
      }
    }
  }

  /** The NDF interpolant (ntrp15s). */
  function ntrpndf(tinterp, tnew, ynew, h, dif, k, out) {
    const neq = ynew.length;
    const s = (tinterp - tnew) / h;
    const y = out || new Float64Array(neq);
    y.set(ynew);
    if (k === 1) { for (let i = 0; i < neq; i++) y[i] += dif[0][i] * s; return y; }
    let cp = 1;
    for (let j = 0; j < k; j++) {
      cp *= (s + j) / (j + 1);
      const row = dif[j];
      for (let i = 0; i < neq; i++) y[i] += row[i] * cp;
    }
    return y;
  }

  /**
   * @param {(t:number, y:Float64Array, out:Float64Array)=>Float64Array} f
   * @param {number} t0 @param {number} tfinal @param {Float64Array} y0
   * @param {object} opts
   *   rtol, atol (number|array), maxOrder (1-5), bdf (bool), hmax, h0,
   *   maxSteps, nonNegative (bool[] or null),
   *   jacobian: {pattern, evaluate(t,y)} or {pattern} (differenced through it) or null,
   *   matrix: 'auto'|'sparse'|'dense',
   *   events: {n, direction:Int8Array, fun(t,y,out)} or null (all terminal),
   *   onAccepted(t, y), onStep(t, nsteps) -> false to abort, tStart (segment start for events)
   */
  function ndf(f, t0, tfinal, y0, opts = {}) {
    const neq = y0.length;
    const rtol = opts.rtol ?? 1e-3;
    // Copied, so that a caller's array is never written to -- except when the
    // caller has asked for the tolerance to be updated as the run goes and has
    // handed over an array to hold it. runModel does exactly that, so that the
    // high-water mark survives the restart at each event instead of being
    // forgotten every time the solver is called again.
    const atol = (opts.autoAtol && opts.atol instanceof Float64Array)
      ? opts.atol
      : (typeof opts.atol === 'number' || opts.atol == null
        ? new Float64Array(neq).fill(opts.atol ?? 1e-6) : Float64Array.from(opts.atol));
    const maxk = Math.min(5, Math.max(1, opts.maxOrder ?? 5));
    const bdf = !!opts.bdf;
    const maxSteps = opts.maxSteps ?? 2e6;
    const tdir = Math.sign(tfinal - t0);
    if (tdir === 0) throw new SolverError('span', 'The start and end times are equal', t0);
    const idxNN = [];
    if (opts.nonNegative) for (let i = 0; i < neq; i++) if (opts.nonNegative[i]) idxNN.push(i);
    const hasNN = idxNN.length > 0;
    const wnorm = makeNorm(opts.norm || 'max', neq);
    const minNewton = opts.minNewton ?? 2;

    // Statistics, and a short trace of the last accepted steps for a failure report
    let nsteps = 0, nfailed = 0, nfevals = 0, npds = 0, ndecomps = 0, nsolves = 0, nbelowtol = 0, negative = 0;
    // How many consecutive steps at the smallest allowed size may be accepted
    // after failing the error test. See the two sites that use it below. Zero
    // is the conventional rule: stop and hand back the partial solution.
    const BELOW_TOL_RUN = opts.belowTolRun == null ? 5 : Math.max(0, Math.round(opts.belowTolRun));
    const trace = [];
    const fail = (e) => { e.trace = trace.slice(); e.lastT = t; e.lastY = Float64Array.from(y); e.stats = { nsteps, nfailed, nfevals, npds, ndecomps, nsolves }; return e; };

    // --- the derivative, wrapped for non-negativity ----------------------
    const raw = (t, y, out) => { nfevals++; return f(t, y, out); };
    let clampedThisStep = false;
    const ode = hasNN
      ? (t, y, out) => {
        raw(t, y, out);
        for (let m = 0; m < idxNN.length; m++) {
          const i = idxNN[m];
          if (y[i] <= 0 && out[i] < 0) { out[i] = 0; clampedThisStep = true; }
        }
        return out;
      }
      : raw;

    const alpha = bdf ? [0, 0, 0, 0, 0] : [-0.185, -1 / 9, -0.0823, -0.0415, 0];
    const invGa = new Array(5), erconst = new Array(5);
    for (let i = 0; i < 5; i++) { invGa[i] = 1 / (G[i] * (1 - alpha[i])); erconst[i] = alpha[i] * G[i] + 1 / (i + 2); }
    const difU = [];
    for (let i = 0; i < maxk; i++) difU.push(DIFUFULL[i].slice(0, maxk));

    const span = Math.abs(tfinal - t0);
    const hmax = opts.hmax != null && opts.hmax > 0 ? Math.min(opts.hmax, span) : 0.1 * span;
    const threshold = new Float64Array(neq);
    for (let i = 0; i < neq; i++) threshold[i] = atol[i] / rtol;

    /*
      Let the absolute tolerance follow the solution upwards.

      The error test weighs each component against max(|y|, atol/rtol), so a
      component is held to `atol` in absolute terms whenever it is small. On a
      chemical system that is often the wrong question to ask. A radical that
      rose to 1e-5 and has since decayed to 1e-40 is still being held to an
      absolute tolerance of 1e-30, which is thirty-five orders below anything
      it ever was, and the step size pays for it.

      With this on, after every accepted step

          atol[i]      <- max(atol[i], rtol*|y[i]|)
          threshold[i] <- atol[i] / rtol

      so the threshold becomes a running high-water mark of |y| and each
      component is judged against the largest it has ever been rather than
      against a floor chosen before the run.

      It only ever loosens, never tightens, which is the whole point and also
      the whole risk: a component that genuinely needs absolute accuracy after
      having once been large will not get it. Off unless asked for.
    */
    const autoAtol = !!opts.autoAtol;
    /*
      The Newton system keeps the threshold it started with, even when the
      error test's is allowed to grow.

      Those two uses of the same number want opposite things. The error test
      asks "is this component accurate enough", and a species that has decayed
      to nothing should be judged against what it once was. The Newton scaling
      asks "what size is this component now", so that the LU pivoting is not
      decided by the largest coefficients and the trace-species corrections
      come out right -- and for that, what a species once was is exactly the
      wrong answer.

      Measured on the canister model, sharing one ratcheting threshold between
      them turns a 5888-step run into a 72303-step one. Kept apart, the same
      run takes 6451 steps.
    */
    const scaleThreshold = autoAtol ? Float64Array.from(threshold) : threshold;

    let t = t0;
    let y = Float64Array.from(y0);
    const f0 = new Float64Array(neq);
    ode(t, y, f0);
    for (let i = 0; i < neq; i++) {
      if (!Number.isFinite(y[i]) || !Number.isFinite(f0[i])) {
        throw new SolverError('nonfinite', `The state or its derivative is not a number at t=${t0} (state ${i})`, t0);
      }
    }

    // --- Jacobian -----------------------------------------------------------
    const Jopt = opts.jacobian || null;
    if (!Jopt || !Jopt.pattern) throw new SolverError('jacobian', 'this solver needs a Jacobian pattern (analytic or to difference through)', t0);
    const pattern = Jopt.pattern;
    const groups = Jopt.groups || colourColumns(pattern);
    const dfdy = new Float64Array(pattern.nnz);
    const analytic = typeof Jopt.evaluate === 'function';
    const fwork = new Float64Array(neq);
    /** Whether a non-negativity constraint binds at (t, y): a held state pushed below zero. */
    const constraintBinds = (tt, yy) => {
      if (!hasNN) return false;
      raw(tt, yy, fwork);
      for (let m = 0; m < idxNN.length; m++) { const i = idxNN[m]; if (yy[i] <= 0 && fwork[i] < 0) return true; }
      return false;
    };
    let kinkJacobian = false;
    const formJacobian = (tt, yy, fty) => {
      npds++;
      kinkJacobian = constraintBinds(tt, yy);
      // While a constraint binds, the derivative integrated is the wrapped one,
      // whose Jacobian the analytic matrix knows nothing about; difference it
      // as the reference implementation does, so the held state is pinned.
      if (analytic && !kinkJacobian) {
        const v = Jopt.evaluate(tt, yy);
        if (v) { dfdy.set(v); return; }
      }
      numjacPattern(ode, tt, yy, fty, pattern, groups, threshold, dfdy);
    };
    formJacobian(t, y, f0);
    const iter = makeIterationMatrix(pattern, dfdy, opts.matrix || 'auto');
    // The scaled Newton system (see makeMiterBuilder): each variable in units
    // of its own weight, max(|y_i|, atol_i/rtol), as the error control sees it.
    const wscale = new Float64Array(neq);
    const scaling = opts.scaling !== false;
    const formIteration = (a) => {
      if (scaling) for (let i = 0; i < neq; i++) wscale[i] = Math.max(Math.abs(y[i]), scaleThreshold[i]);
      try { iter.form(a, dfdy, scaling ? wscale : null); } catch (e) { throw new SolverError('singular', `${e.message} (at t=${t})`, t); }
      ndecomps++;
    };

    // --- initial step ---------------------------------------------------
    let hmin = 16 * ulp(t);
    let absh;
    const yp = Float64Array.from(f0);
    if (opts.h0 != null && opts.h0 > 0) {
      absh = Math.min(hmax, Math.max(hmin, opts.h0));
    } else {
      let rh = 0;
      for (let i = 0; i < neq; i++) rh = Math.max(rh, Math.abs(yp[i] / Math.max(Math.abs(y[i]), threshold[i])));
      rh /= 0.8 * Math.sqrt(rtol);
      absh = Math.min(hmax, span);
      if (absh * rh > 1) absh = 1 / rh;
      absh = Math.max(absh, hmin);
      let h = tdir * absh;
      const tdel = (t + tdir * Math.min(Math.sqrt(EPS) * Math.max(Math.abs(t), Math.abs(t + h)), absh)) - t;
      const f1 = new Float64Array(neq);
      ode(t + tdel, y, f1);
      const DfDt = new Float64Array(neq);
      patternMatVec(pattern, dfdy, yp, DfDt);
      for (let i = 0; i < neq; i++) DfDt[i] += (f1[i] - f0[i]) / tdel;
      rh = 0;
      for (let i = 0; i < neq; i++) rh = Math.max(rh, Math.abs(DfDt[i] / Math.max(Math.abs(y[i]), threshold[i])));
      rh = 1.25 * Math.sqrt((0.5 * rh) / rtol);
      absh = Math.min(hmax, span);
      if (absh * rh > 1) absh = 1 / rh;
      absh = Math.max(absh, hmin);
    }
    let h = tdir * absh;

    let k = 1, klast = k, abshlast = absh;
    const dif = [];
    for (let i = 0; i < maxk + 2; i++) dif.push(new Float64Array(neq));
    for (let i = 0; i < neq; i++) dif[0][i] = h * yp[i];
    let hinvGak = h * invGa[k - 1];
    let nconhk = 0;
    formIteration(hinvGak);
    let havrate = false, rate = 0, done = false, at_hmin = false;
    let Jcurrent = true;
    let kinkWas = kinkJacobian;

    // Events
    const events = opts.events || null;
    const nev = events ? events.n : 0;
    const vL = new Float64Array(nev), vR = new Float64Array(nev);
    if (events) events.fun(t, y, vL);
    const tStart = opts.tStart !== undefined ? opts.tStart : t0;
    let stopped = null;

    // Work arrays
    const psi = new Float64Array(neq), pred = new Float64Array(neq), ynew = new Float64Array(neq);
    const difkp1 = new Float64Array(neq), invwt = new Float64Array(neq), rhs = new Float64Array(neq), del = new Float64Array(neq);
    const yinterp = new Float64Array(neq);
    let tnew = t, err = 0, newtonIts = 0, stepFails = 0, belowTolRun = 0;

    // Stall guard: no ground covered and a step size that has stopped growing.
    const stallWindow = 4000, stallSpan = span * 1e-10;
    let stallCheckStep = 0, stallCheckT = t0, stallCheckAbsh = 0;

    while (!done) {
      hmin = 16 * ulp(t);
      absh = Math.min(hmax, Math.max(hmin, absh));
      if (absh === hmin) { if (at_hmin) absh = abshlast; at_hmin = true; } else at_hmin = false;
      h = tdir * absh;
      if (1.1 * absh >= Math.abs(tfinal - t)) { h = tfinal - t; absh = Math.abs(h); done = true; }

      if (!(absh === abshlast && k === klast) || (Jcurrent && kinkJacobian !== kinkWas)) {
        if (!(absh === abshlast && k === klast)) {
          updateDif(absh / abshlast, difU, neq, k, maxk, dif);
          hinvGak = h * invGa[k - 1];
        }
        nconhk = 0;
        formIteration(hinvGak);
        havrate = false;
      }
      kinkWas = kinkJacobian;

      let nofailed = true;
      for (;;) {
        let gotynew = false;
        while (!gotynew) {
          // psi = dif(:,K) * (G(K) .* invGa(k))
          psi.fill(0);
          for (let m = 0; m < k; m++) {
            const row = dif[m], c = G[m] * invGa[k - 1];
            for (let i = 0; i < neq; i++) psi[i] += row[i] * c;
          }
          tnew = t + h;
          if (done) tnew = tfinal;
          h = tnew - t;
          pred.set(y);
          for (let m = 0; m < k; m++) { const row = dif[m]; for (let i = 0; i < neq; i++) pred[i] += row[i]; }
          ynew.set(pred);
          difkp1.fill(0);
          clampedThisStep = false;
          for (let i = 0; i < neq; i++) invwt[i] = 1 / Math.max(Math.max(Math.abs(y[i]), Math.abs(ynew[i])), threshold[i]);
          const minnrm = 100 * EPS * wnorm(ynew, invwt);

          // Simplified Newton iteration
          const maxit = 4;
          let tooslow = false, oldnrm = 0, nonfinite = false;
          newtonIts = 0;
          const newtonNorms = [];
          for (let it = 1; it <= maxit; it++) {
            ode(tnew, ynew, rhs);
            for (let i = 0; i < neq; i++) rhs[i] = rhs[i] * hinvGak - (psi[i] + difkp1[i]);
            iter.solve(rhs, del);
            nsolves++;
            const newnrm = wnorm(del, invwt);
            newtonIts = it;
            if (opts.debug) (newtonNorms.length < it ? newtonNorms.push(newnrm) : newtonNorms[it - 1] = newnrm);
            if (!Number.isFinite(newnrm)) { nonfinite = true; tooslow = true; break; }
            for (let i = 0; i < neq; i++) { difkp1[i] += del[i]; ynew[i] = pred[i] + difkp1[i]; }
            if (newnrm <= minnrm) { gotynew = true; break; }
            if (it === 1) {
              // The reference implementation accepts here on the strength of the rate seen
              // in earlier steps. On a very steep switch (a corrosion rate that
              // turns on over 1e-7 in relative humidity) a Jacobian formed a
              // step ago can carry a diagonal that damps the correction by
              // 1e6 while the residual is far from zero, and the tiny first
              // correction then passes as converged. Two iterations are
              // demanded unless minNewton says otherwise: a stale
              // linearisation shows as a rate near one and is refreshed.
              if (havrate && minNewton <= 1) {
                const errit = (newnrm * rate) / (1 - rate);
                if (errit <= 0.05 * rtol) { gotynew = true; break; }
              } else if (!havrate) rate = 0;
            } else {
              if (newnrm > 0.9 * oldnrm) { tooslow = true; break; }
              rate = Math.max(0.9 * rate, newnrm / oldnrm);
              havrate = true;
              const errit = (newnrm * rate) / (1 - rate);
              if (errit <= 0.5 * rtol) { gotynew = true; break; }
              if (it === maxit) { tooslow = true; break; }
              if (0.5 * rtol < errit * rate ** (maxit - it)) { tooslow = true; break; }
            }
            oldnrm = newnrm;
          }

          // A corrector that converged against the pinning (kink) matrix while
          // nothing was actually held took the one small correction that matrix
          // allows: retake the step with the model's own matrix.
          if (gotynew && kinkJacobian && analytic && !clampedThisStep) {
            gotynew = false;
            nfailed++;
            const v = Jopt.evaluate(t, y);
            if (v) dfdy.set(v); else numjacPattern(ode, t, y, ode(t, y, fwork), pattern, groups, threshold, dfdy);
            kinkJacobian = false;
            npds++;
            Jcurrent = true;
            formIteration(hinvGak);
            havrate = false;
            continue;
          }

          if (tooslow) {
            nfailed++;
            if (opts.debug) {
              const top = Array.from(del, (v, i) => [i, Math.abs(v * invwt[i])]).sort((a, b) => b[1] - a[1]).slice(0, 4);
              opts.debug({ t, h, k, newtonIts, newtonNorms, nonfinite, Jcurrent, top, y: Float64Array.from(y), ynew: Float64Array.from(ynew), invwt: Float64Array.from(invwt), del: Float64Array.from(del) });
            }
            if (Jcurrent) {
              if (absh <= hmin) throw fail(atHmin(t, hmin, nonfinite));
              abshlast = absh;
              absh = Math.max(hmin, 0.3 * absh);
              h = tdir * absh;
              done = false;
              updateDif(absh / abshlast, difU, neq, k, maxk, dif);
              hinvGak = h * invGa[k - 1];
              nconhk = 0;
            } else {
              formJacobian(t, y, ode(t, y, fwork));
              Jcurrent = true;
            }
            formIteration(hinvGak);
            havrate = false;
          }
        }

        // Error estimate
        err = wnorm(difkp1, invwt) * erconst[k - 1];
        if (!Number.isFinite(err)) throw fail(new SolverError('nonfinite', `The error estimate is not a number at t=${t}`, t));
        if (hasNN && err <= rtol) {
          let errNN = 0;
          for (let m = 0; m < idxNN.length; m++) {
            const i = idxNN[m];
            if (ynew[i] < 0) errNN = Math.max(errNN, Math.abs(-ynew[i] / threshold[i]));
          }
          if (errNN > rtol) err = errNN;
        }
        if (!(err > rtol)) { belowTolRun = 0; break; }         // successful step

        nfailed++;
        stepFails++;
        if (opts.debug) {
          const top = Array.from(difkp1, (v, i) => [i, Math.abs(v * invwt[i]) * erconst[k - 1]]).sort((a, b) => b[1] - a[1]).slice(0, 4);
          opts.debug({ t, h, k, errTest: err, top, y: Float64Array.from(y), ynew: Float64Array.from(ynew), invwt: Float64Array.from(invwt) });
        }
        if (absh <= hmin) {
          // A step of the smallest size that still fails the error test.
          //
          // THIS IS A DELIBERATE DEPARTURE FROM THE PUBLISHED METHOD, which
          // raises a tolerance-not-met error here and returns the partial
          // solution -- it never accepts a step that failed. This accepts up to
          // BELOW_TOL_RUN of them in a row instead, counts them in nbelowtol,
          // and reports the count in bold in the footer, so a run that leaned
          // on it says so.
          //
          // The reason is this model. After a restart from an interpolated
          // state a species with a lifetime of femtoseconds is off its steady
          // state by more than the tolerance, and no step size mends that: the
          // implicit step itself does. Measured across the 39 presets, the
          // escape is used three times in total, and without it three of them
          // stop early.
          if (belowTolRun < BELOW_TOL_RUN) { belowTolRun++; nbelowtol++; break; }
          throw fail(atHmin(t, hmin, false));
        }
        abshlast = absh;
        let hopt;
        if (nofailed) {
          nofailed = false;
          hopt = absh * Math.max(0.1, 0.833 * Math.pow(rtol / err, 1 / (k + 1)));
          if (k > 1) {
            let errkm1 = 0;
            for (let i = 0; i < neq; i++) errkm1 = Math.max(errkm1, Math.abs((dif[k - 1][i] + difkp1[i]) * invwt[i]));
            errkm1 *= erconst[k - 2];
            const hkm1 = absh * Math.max(0.1, 0.769 * Math.pow(rtol / errkm1, 1 / k));
            if (hkm1 > hopt) { hopt = Math.min(absh, hkm1); k--; }
          }
          absh = Math.max(hmin, hopt);
        } else {
          absh = Math.max(hmin, 0.5 * absh);
        }
        // The reduced step has landed at the floor. Same escape as above, and
        // bounded by the same counter: it was unbounded here at first, which
        // meant a run could accept any number of failing steps and still call
        // itself a success. It has never once fired on these presets, which is
        // exactly why it needed the bound rather than the benefit of the doubt.
        if (absh <= hmin) {
          if (belowTolRun < BELOW_TOL_RUN) { belowTolRun++; nbelowtol++; absh = abshlast; break; }
          throw fail(atHmin(t, hmin, false));
        }
        h = tdir * absh;
        if (absh < abshlast) done = false;
        updateDif(absh / abshlast, difU, neq, k, maxk, dif);
        hinvGak = h * invGa[k - 1];
        nconhk = 0;
        formIteration(hinvGak);
        havrate = false;
      }

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
      if (nsteps - stallCheckStep >= stallWindow) {
        if (Math.abs(tnew - stallCheckT) < stallSpan && absh <= stallCheckAbsh * 2) {
          throw fail(new SolverError('stalled', `The solver stopped making progress at t=${tnew}`, tnew));
        }
        stallCheckStep = nsteps; stallCheckT = tnew; stallCheckAbsh = absh;
      }

      // Fold difkp1 into the difference table
      for (let i = 0; i < neq; i++) { dif[k + 1][i] = difkp1[i] - dif[k][i]; dif[k][i] = difkp1[i]; }
      for (let m = k - 1; m >= 0; m--) { const a = dif[m], b = dif[m + 1]; for (let i = 0; i < neq; i++) a[i] += b[i]; }

      // Non-negativity: project and remember which
      let NNreset = null;
      if (hasNN) {
        for (let m = 0; m < idxNN.length; m++) {
          const i = idxNN[m];
          if (ynew[i] < 0) { ynew[i] = 0; negative++; (NNreset = NNreset || []).push(i); }
        }
      }

      // Events: locate on the interpolant and cut the step
      if (events) {
        events.fun(tnew, ynew, vR);
        const at = (tq) => { ntrpndf(tq, tnew, ynew, h, dif, k, yinterp); const o = new Float64Array(nev); events.fun(tq, yinterp, o); return o; };
        const hit = firstCrossing(at, t, vL, tnew, vR, events.direction, tStart);
        if (hit) {
          // Rebuild the difference table for the shortened step
          const te = hit.t;
          const yaux = [];
          for (let m = 0; m < k + 1; m++) yaux.push(ntrpndf(te - m * (te - t), tnew, ynew, h, dif, k));
          for (let m = 1; m < k + 1; m++) {
            for (let j = k; j >= m; j--) for (let i = 0; i < neq; i++) yaux[j][i] = yaux[j - 1][i] - yaux[j][i];
          }
          for (let m = 0; m < k; m++) dif[m].set(yaux[m + 1]);
          tnew = te;
          ynew.set(yaux[0]);
          h = tnew - t;
          done = true;
          stopped = { t: te, y: Float64Array.from(ynew), which: hit.which };
        }
        vL.set(vR);
      }

      if (opts.onAccepted) opts.onAccepted(tnew, ynew);
      if (opts.onStep && (nsteps & 15) === 0 && opts.onStep(tnew, nsteps) === false) throw new SolverError('aborted', 'Aborted', tnew);

      if (done) { t = tnew; y.set(ynew); break; }

      klast = k; abshlast = absh;
      nconhk = Math.min(nconhk + 1, maxk + 2);
      if (nconhk >= k + 2) {
        let temp = 1.2 * Math.pow(err / rtol, 1 / (k + 1));
        let hopt = temp > 0.1 ? absh / temp : 10 * absh;
        let kopt = k;
        if (k > 1) {
          let errkm1 = 0;
          for (let i = 0; i < neq; i++) errkm1 = Math.max(errkm1, Math.abs(dif[k - 1][i] * invwt[i]));
          errkm1 *= erconst[k - 2];
          temp = 1.3 * Math.pow(errkm1 / rtol, 1 / k);
          const hkm1 = temp > 0.1 ? absh / temp : 10 * absh;
          if (hkm1 > hopt) { hopt = hkm1; kopt = k - 1; }
        }
        if (k < maxk) {
          let errkp1 = 0;
          for (let i = 0; i < neq; i++) errkp1 = Math.max(errkp1, Math.abs(dif[k + 1][i] * invwt[i]));
          errkp1 *= erconst[k];
          temp = 1.4 * Math.pow(errkp1 / rtol, 1 / (k + 2));
          const hkp1 = temp > 0.1 ? absh / temp : 10 * absh;
          if (hkp1 > hopt) { hopt = hkp1; kopt = k + 1; }
        }
        if (hopt > absh) { absh = hopt; if (k !== kopt) k = kopt; }
      }

      t = tnew;
      y.set(ynew);
      if (NNreset) for (const i of NNreset) for (let j = 0; j < maxk + 2; j++) dif[j][i] = 0;
      Jcurrent = false;
      if (hasNN && (clampedThisStep || kinkJacobian)) {
        // The matrix in hand was formed at a kink that has let go, or a
        // constraint has taken hold since: it is about a state the integration
        // has left, so it is re-formed before the next step.
        if (constraintBinds(t, y) !== kinkJacobian) {
          formJacobian(t, y, ode(t, y, fwork));
          Jcurrent = true;
        }
      }
    }

    return {
      t, y, stopped,
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
   * Integrates a FacsimileModel-compiled model, restarting at each terminal
   * event after applying it.
   *
   * @param {object} model   from FacsimileModel.compile
   * @param {object} opts    solver ('ndf', 'bdf' or a function), tend (s), rtol, atol,
   *                         atolSpecies ({NAME: value} overriding atol for those species),
   *                         nonNegative (bool), matrix, jacobianMode ('analytic'|'numeric'),
   *                         maxOrder, bdf, onProgress(t, nsteps), maxPoints (how many
   *                         points to keep; the store is thinned to stay inside it)
   * @returns {{t: Float64Array, y: Float64Array[], events: object[], stats: object}}
   */
  function runModel(model, opts = {}) {
    const n = model.nspecies;
    // A name, or a solver of the caller's own -- which is how the ode_julia
    // solvers are run: facsimile-ode-julia.js wraps each one in this same
    // signature, reporting its steps the same way, so everything below is
    // unchanged whichever is chosen.
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
        direction: new Int8Array(model.nevents).fill(1),
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
    let t0 = 0, y = y0, info = null;
    const started = Date.now();
    for (let seg = 0; seg < 50; seg++) {
      total.segments++;
      let res;
      try {
        res = solver(f, t0, tend, y, {
        rtol: opts.rtol, atol: runAtol, maxOrder: opts.maxOrder, bdf: opts.solver === 'bdf' || !!opts.bdf, hmax: opts.hmax, norm: opts.norm, debug: opts.debug, scaling: opts.scaling, minNewton: opts.minNewton,
        nonNegative, jacobian, matrix: opts.matrix || 'auto', events, tStart: seg === 0 ? undefined : t0,
        maxSteps: opts.maxSteps,
        // Named one by one rather than spread, so that a solver can only be
        // handed what this driver knows it means. The cost of that is that a
        // new option has to be added here as well as at both ends, and
        // forgetting to is silent -- the knob simply does nothing.
        minOrder: opts.minOrder, kappa: opts.kappa, maxJacAge: opts.maxJacAge,
        smoothEst: opts.smoothEst, belowTolRun: opts.belowTolRun,
        autoAtol: opts.autoAtol,
        onAccepted: remember,
        onStep: opts.onProgress ? (t, ns) => opts.onProgress(t, ns + total.nsteps, T.length) : null,
        });
      } catch (e) {
        // Hand back what was integrated, so a failed run can still be looked at.
        e.partial = { t: Float64Array.from(T), y: Y, events: eventLog };
        throw e;
      }
      for (const key of ['nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'nbelowtol', 'negative']) total[key] += res.stats[key] || 0;
      info = res.stats;
      // Where a segment ends is worth keeping whatever the thinning says: it
      // is the answer at the end of the run, or the state an event fired at.
      if (T[T.length - 1] !== res.t) { T.push(res.t); Y.push(Float64Array.from(res.y)); }
      if (!res.stopped) break;
      // Apply the event and continue from there.
      const which = res.stopped.which[0];
      if (!(res.stopped.t > t0)) {
        // The event has fired at the instant it was applied. The solvers here
        // step past a crossing that is still resting on zero at the start of a
        // segment; one that cannot would restart for ever, so it says so.
        throw new SolverError('events',
          `The event "${(model.events[which] || {}).expr || which}" fires again at the `
          + `instant it was applied (t = ${res.stopped.t}). This solver cannot step past a `
          + 'crossing that stays on zero; the NDF can.', res.stopped.t);
      }
      const changed = model.applyEvent(which, res.stopped.t, y0);
      eventLog.push({ t: res.stopped.t, event: which, expr: model.events[which].expr, changed });
      t0 = res.stopped.t;
      y = res.stopped.y;
      if (t0 >= tend) break;
    }
    return {
      t: Float64Array.from(T), y: Y, events: eventLog,
      stats: {
        ...total, sparse: info.sparse, fill: info.fill, ordering: info.ordering, solver: info.solver,
        nnz: model.nnz, n, points: T.length, stride, seconds: (Date.now() - started) / 1000,
      },
    };
  }

  return { ndf, runModel, parseSpeciesTolerances, speciesAtol, SolverError, CSC, cscFromTriplets, SparseLU, DenseLU, makeIterationMatrix, colourColumns, numjacPattern, reverseCuthillMcKee, firstCrossing, ntrpndf };
});
