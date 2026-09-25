/* ==========================================================================
   ode_julia / core / linalg

   The linear algebra the stiff solvers need, and nothing else.

   Every stiff method here spends almost all of its time in one place: solving
   (W)x = b where W = I/(γh) − J, or M − γhJ, or the complex pair Radau needs.
   So the shapes are chosen for that and not for generality.

     - Dense matrices are column-major in one Float64Array. LU walks columns.
     - Sparse matrices are compressed-column (CSC), which is what a Jacobian
       built column by column already is, and what the left-looking LU below
       wants.
     - Factorisations own their buffers and are reused. Forming W and
       factorising it is the expensive part of a stiff step, and the whole
       point of the caches above this file is to do it as rarely as possible;
       nothing here allocates once it has been constructed.

   Complex arithmetic is split into parallel re/im arrays rather than an array
   of objects: RadauIIA5 solves one complex n×n system per Newton iteration,
   and an array of {re, im} would allocate 2n objects per solve.
   ========================================================================== */

/**
 * A square matrix, column-major: A[i][j] is data[j * n + i].
 *
 * Column-major because both LU factorisations here are column algorithms --
 * the inner loops run down a column, which is then contiguous.
 */
export class DenseMatrix {
  constructor(n, data) {
    this.n = n;
    this.data = data || new Float64Array(n * n);
  }

  static zeros(n) { return new DenseMatrix(n); }

  /** A[i][j] = v */
  set(i, j, v) { this.data[j * this.n + i] = v; }

  /** A[i][j] */
  get(i, j) { return this.data[j * this.n + i]; }

  fill(v) { this.data.fill(v); }

  /** this <- 0, then the diagonal <- v. */
  setIdentity(v = 1) {
    this.data.fill(0);
    for (let i = 0; i < this.n; i++) this.data[i * this.n + i] = v;
  }

  /** y <- A x. y may not alias x. */
  apply(x, y) {
    const { n, data } = this;
    y.fill(0);
    for (let j = 0; j < n; j++) {
      const xj = x[j];
      if (xj === 0) continue;
      const base = j * n;
      for (let i = 0; i < n; i++) y[i] += data[base + i] * xj;
    }
    return y;
  }
}

/**
 * Compressed sparse column.
 *
 * colPtr has n+1 entries; the entries of column j are rowIdx/values over
 * [colPtr[j], colPtr[j+1]), with the row indices sorted ascending. Sorted
 * rows are not merely tidy: the triangular solves below rely on it.
 */
export class CSC {
  constructor(n, colPtr, rowIdx, values) {
    this.n = n;
    this.colPtr = colPtr;
    this.rowIdx = rowIdx;
    this.values = values || new Float64Array(rowIdx.length);
  }

  get nnz() { return this.colPtr[this.n]; }

  /** A copy of the sparsity with a fresh value array. */
  cloneStructure() {
    return new CSC(this.n, this.colPtr, this.rowIdx, new Float64Array(this.rowIdx.length));
  }

  /** y <- A x. y may not alias x. */
  apply(x, y) {
    const { n, colPtr, rowIdx, values } = this;
    y.fill(0);
    for (let j = 0; j < n; j++) {
      const xj = x[j];
      if (xj === 0) continue;
      for (let k = colPtr[j]; k < colPtr[j + 1]; k++) y[rowIdx[k]] += values[k] * xj;
    }
    return y;
  }

  /** Dense copy, for small problems and for checking. */
  toDense() {
    const A = DenseMatrix.zeros(this.n);
    for (let j = 0; j < this.n; j++) {
      for (let k = this.colPtr[j]; k < this.colPtr[j + 1]; k++) A.set(this.rowIdx[k], j, this.values[k]);
    }
    return A;
  }
}

/**
 * Build a CSC from triplets, summing duplicates and sorting rows.
 *
 * Used to turn a Jacobian pattern given as (i, j) pairs into something the
 * factorisations can take.
 */
export function cscFromTriplets(n, rows, cols, vals) {
  const count = new Int32Array(n + 1);
  const m = rows.length;
  for (let k = 0; k < m; k++) count[cols[k] + 1]++;
  for (let j = 0; j < n; j++) count[j + 1] += count[j];
  const colPtr = Int32Array.from(count);
  const rowIdx = new Int32Array(m);
  const values = new Float64Array(m);
  const at = Int32Array.from(count);
  for (let k = 0; k < m; k++) {
    const p = at[cols[k]]++;
    rowIdx[p] = rows[k];
    values[p] = vals ? vals[k] : 0;
  }
  // Sort each column by row and fold duplicates together.
  const outPtr = new Int32Array(n + 1);
  const outRow = new Int32Array(m);
  const outVal = new Float64Array(m);
  let w = 0;
  const order = [];
  for (let j = 0; j < n; j++) {
    const lo = colPtr[j];
    const hi = colPtr[j + 1];
    order.length = 0;
    for (let k = lo; k < hi; k++) order.push(k);
    order.sort((a, b) => rowIdx[a] - rowIdx[b]);
    let last = -1;
    for (const k of order) {
      const r = rowIdx[k];
      if (r === last) { outVal[w - 1] += values[k]; continue; }
      outRow[w] = r;
      outVal[w] = values[k];
      w++;
      last = r;
    }
    outPtr[j + 1] = w;
  }
  return new CSC(n, outPtr, outRow.slice(0, w), outVal.slice(0, w));
}

/* ==========================================================================
   Dense LU with partial pivoting
   ========================================================================== */

/**
 * Right-looking LU with partial pivoting, in place, column-major.
 *
 * Reused across Newton iterations and across steps: `factor` overwrites the
 * internal buffer and nothing else allocates, so a solver that re-forms W
 * every step still allocates only once.
 */
export class DenseLU {
  constructor(n) {
    this.n = n;
    this.lu = new Float64Array(n * n);
    this.piv = new Int32Array(n);
    this.singular = false;
  }

  /**
   * Factorise a copy of A (column-major Float64Array or DenseMatrix).
   * @returns {boolean} false if a zero pivot was met, and the factor is unusable.
   */
  factor(A) {
    const n = this.n;
    const a = this.lu;
    a.set(A.data || A);
    const piv = this.piv;
    this.singular = false;
    for (let k = 0; k < n; k++) {
      // Pivot: the largest entry at or below the diagonal of column k.
      let p = k;
      let big = Math.abs(a[k * n + k]);
      for (let i = k + 1; i < n; i++) {
        const v = Math.abs(a[k * n + i]);
        if (v > big) { big = v; p = i; }
      }
      piv[k] = p;
      if (big === 0) { this.singular = true; return false; }
      if (p !== k) {
        for (let j = 0; j < n; j++) {
          const o1 = j * n + k;
          const o2 = j * n + p;
          const t = a[o1]; a[o1] = a[o2]; a[o2] = t;
        }
      }
      const dinv = 1 / a[k * n + k];
      const colK = k * n;
      for (let i = k + 1; i < n; i++) a[colK + i] *= dinv;
      // Rank-1 update of the trailing submatrix.
      for (let j = k + 1; j < n; j++) {
        const akj = a[j * n + k];
        if (akj === 0) continue;
        const colJ = j * n;
        for (let i = k + 1; i < n; i++) a[colJ + i] -= a[colK + i] * akj;
      }
    }
    return true;
  }

  /**
   * Solve LUx = Pb, overwriting b with x.
   *
   * Every interchange is applied to b first, before any substitution. That is
   * forced by the factorisation above, which swaps the whole row -- the
   * already-computed multipliers included -- so the stored L is the L of the
   * fully permuted matrix. Interleaving a swap with each elimination, as
   * LINPACK does, is correct only for a factorisation that leaves the earlier
   * columns alone, and pairing the two conventions gives a plausible wrong
   * answer on any matrix that actually needs pivoting.
   */
  solve(b) {
    const n = this.n;
    const a = this.lu;
    const piv = this.piv;
    for (let k = 0; k < n; k++) {
      const p = piv[k];
      if (p !== k) { const t = b[k]; b[k] = b[p]; b[p] = t; }
    }
    for (let k = 0; k < n; k++) {
      const bk = b[k];
      if (bk === 0) continue;
      const colK = k * n;
      for (let i = k + 1; i < n; i++) b[i] -= a[colK + i] * bk;
    }
    for (let k = n - 1; k >= 0; k--) {
      const colK = k * n;
      const bk = (b[k] /= a[colK + k]);
      if (bk === 0) continue;
      for (let i = 0; i < k; i++) b[i] -= a[colK + i] * bk;
    }
    return b;
  }
}

/* ==========================================================================
   Complex dense LU
   ========================================================================== */

/**
 * The same algorithm over the complex numbers, with re and im held apart.
 *
 * RadauIIA5 needs exactly one of these: its 3×3 stage system decouples, over
 * the eigenbasis of the inverse Butcher matrix, into one real n×n solve and
 * one complex n×n solve. Doing it that way rather than as a real 3n×3n system
 * is the difference between 3n³/3 and 27n³/3 of work per factorisation.
 */
export class ComplexDenseLU {
  constructor(n) {
    this.n = n;
    this.re = new Float64Array(n * n);
    this.im = new Float64Array(n * n);
    this.piv = new Int32Array(n);
    this.singular = false;
  }

  /** Factorise the matrix given as separate real and imaginary parts. */
  factor(Are, Aim) {
    const n = this.n;
    const re = this.re;
    const im = this.im;
    re.set(Are);
    im.set(Aim);
    const piv = this.piv;
    this.singular = false;
    for (let k = 0; k < n; k++) {
      let p = k;
      let big = Math.abs(re[k * n + k]) + Math.abs(im[k * n + k]);
      for (let i = k + 1; i < n; i++) {
        const v = Math.abs(re[k * n + i]) + Math.abs(im[k * n + i]);
        if (v > big) { big = v; p = i; }
      }
      piv[k] = p;
      if (big === 0) { this.singular = true; return false; }
      if (p !== k) {
        for (let j = 0; j < n; j++) {
          const o1 = j * n + k;
          const o2 = j * n + p;
          let t = re[o1]; re[o1] = re[o2]; re[o2] = t;
          t = im[o1]; im[o1] = im[o2]; im[o2] = t;
        }
      }
      // 1 / (dr + i di), by the scaled form that avoids overflow in dr² + di².
      const dr = re[k * n + k];
      const di = im[k * n + k];
      let invR;
      let invI;
      if (Math.abs(dr) >= Math.abs(di)) {
        const r = di / dr;
        const den = dr + di * r;
        invR = 1 / den;
        invI = -r / den;
      } else {
        const r = dr / di;
        const den = dr * r + di;
        invR = r / den;
        invI = -1 / den;
      }
      const colK = k * n;
      for (let i = k + 1; i < n; i++) {
        const ar = re[colK + i];
        const ai = im[colK + i];
        re[colK + i] = ar * invR - ai * invI;
        im[colK + i] = ar * invI + ai * invR;
      }
      for (let j = k + 1; j < n; j++) {
        const colJ = j * n;
        const br = re[colJ + k];
        const bi = im[colJ + k];
        if (br === 0 && bi === 0) continue;
        for (let i = k + 1; i < n; i++) {
          const ar = re[colK + i];
          const ai = im[colK + i];
          re[colJ + i] -= ar * br - ai * bi;
          im[colJ + i] -= ar * bi + ai * br;
        }
      }
    }
    return true;
  }

  /**
   * Solve in place; br/bi are overwritten with the real and imaginary parts.
   * The interchanges come first, for the reason given in DenseLU.solve.
   */
  solve(br, bi) {
    const n = this.n;
    const re = this.re;
    const im = this.im;
    const piv = this.piv;
    for (let k = 0; k < n; k++) {
      const p = piv[k];
      if (p !== k) {
        let t = br[k]; br[k] = br[p]; br[p] = t;
        t = bi[k]; bi[k] = bi[p]; bi[p] = t;
      }
    }
    for (let k = 0; k < n; k++) {
      const xr = br[k];
      const xi = bi[k];
      if (xr === 0 && xi === 0) continue;
      const colK = k * n;
      for (let i = k + 1; i < n; i++) {
        const ar = re[colK + i];
        const ai = im[colK + i];
        br[i] -= ar * xr - ai * xi;
        bi[i] -= ar * xi + ai * xr;
      }
    }
    for (let k = n - 1; k >= 0; k--) {
      const colK = k * n;
      const dr = re[colK + k];
      const di = im[colK + k];
      const xr = br[k];
      const xi = bi[k];
      let qr;
      let qi;
      if (Math.abs(dr) >= Math.abs(di)) {
        const r = di / dr;
        const den = dr + di * r;
        qr = (xr + xi * r) / den;
        qi = (xi - xr * r) / den;
      } else {
        const r = dr / di;
        const den = dr * r + di;
        qr = (xr * r + xi) / den;
        qi = (xi * r - xr) / den;
      }
      br[k] = qr;
      bi[k] = qi;
      if (qr === 0 && qi === 0) continue;
      for (let i = 0; i < k; i++) {
        const ar = re[colK + i];
        const ai = im[colK + i];
        br[i] -= ar * qr - ai * qi;
        bi[i] -= ar * qi + ai * qr;
      }
    }
  }
}

/* ==========================================================================
   Sparse LU: Gilbert-Peierls, left-looking, partial pivoting
   ========================================================================== */

/**
 * Reverse Cuthill-McKee on the symmetrised pattern.
 *
 * A fill-reducing permutation. For a chemical Jacobian -- banded-ish once the
 * species are ordered by how they react -- it is usually worth several times
 * its cost, and where it is not, the caller compares the measured fill against
 * dense and picks the cheaper. Returns the new-to-old ordering.
 */
export function reverseCuthillMcKee(n, colPtr, rowIdx) {
  // Symmetrise: adjacency of A + Aᵀ.
  const deg = new Int32Array(n);
  for (let j = 0; j < n; j++) {
    for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
      const i = rowIdx[k];
      if (i === j) continue;
      deg[i]++;
      deg[j]++;
    }
  }
  const start = new Int32Array(n + 1);
  for (let j = 0; j < n; j++) start[j + 1] = start[j] + deg[j];
  const adj = new Int32Array(start[n]);
  const at = Int32Array.from(start);
  for (let j = 0; j < n; j++) {
    for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
      const i = rowIdx[k];
      if (i === j) continue;
      adj[at[i]++] = j;
      adj[at[j]++] = i;
    }
  }

  const order = new Int32Array(n);
  const seen = new Uint8Array(n);
  let w = 0;
  const nbrs = [];
  // One component, breadth first from the vertex of least degree at or after
  // `from`, each vertex's neighbours taken in increasing degree.
  const component = (from) => {
    let root = from;
    let best = Infinity;
    for (let v = from; v < n; v++) {
      if (seen[v]) continue;
      const d = start[v + 1] - start[v];
      if (d < best) { best = d; root = v; }
    }
    seen[root] = 1;
    order[w++] = root;
    let head = w - 1;
    while (head < w) {
      const v = order[head++];
      nbrs.length = 0;
      for (let k = start[v]; k < start[v + 1]; k++) {
        const u = adj[k];
        if (!seen[u]) { seen[u] = 1; nbrs.push(u); }
      }
      nbrs.sort((a, b) => (start[a + 1] - start[a]) - (start[b + 1] - start[b]));
      for (const u of nbrs) order[w++] = u;
    }
  };
  for (let s = 0; s < n; s++) {
    if (seen[s]) continue;
    component(s);
  }
  // That loop moves past s whether or not the component it started reached s
  // -- the root is the least degree from s on, which need not be s -- so it
  // can pass vertices that no later component contains. The order then came
  // back short and padded with zeros: not a permutation, and a factorisation
  // through it reported the matrix singular or pivoted on garbage. Two
  // isolated vertices after a connected block were enough, and a Kompartment
  // model with its mass-balance audit on has dozens. Whatever it left is
  // ordered here; from s on nothing is unseen, so nothing is passed again.
  // Where it left nothing -- every case it got right -- the order is the one
  // it always gave.
  for (let s = 0; s < n && w < n; s++) {
    while (!seen[s]) component(s);
  }
  // Reversed: Cuthill-McKee reversed has strictly no more fill, usually less.
  const rcm = new Int32Array(n);
  for (let i = 0; i < n; i++) rcm[i] = order[n - 1 - i];
  return rcm;
}

/**
 * Left-looking sparse LU with partial pivoting (Gilbert and Peierls, 1988).
 *
 * Column j of L and U is found by solving a sparse triangular system against
 * the columns already computed. The cost is proportional to the number of
 * non-zeros in the factor rather than to n³, which is the whole reason to
 * bother; the depth-first search below is what finds, in time proportional to
 * the answer, which rows of the column can be non-zero.
 *
 * The pattern is fixed at construction (the Jacobian's), but the pivoting is
 * numeric, so the factor's pattern is discovered at each factorisation. That
 * is Gilbert-Peierls as written; a symbolic-once variant would need threshold
 * pivoting and is a different trade.
 */
export class SparseLU {
  /**
   * @param {number} n
   * @param {Int32Array} colPtr  pattern of the matrix to be factorised
   * @param {Int32Array} rowIdx
   * @param {Int32Array} [perm]  column ordering (new -> old), e.g. from RCM
   */
  constructor(n, colPtr, rowIdx, perm) {
    this.n = n;
    this.perm = perm || null;
    this.iperm = null;
    if (perm) {
      this.iperm = new Int32Array(n);
      for (let i = 0; i < n; i++) this.iperm[perm[i]] = i;
    }
    // Work space, all of it reused across factorisations.
    this.x = new Float64Array(n);          // the dense accumulator for one column
    this.mark = new Int32Array(n).fill(-1); // which column last touched a row
    this.stack = new Int32Array(n);
    this.pstack = new Int32Array(n);
    this.pattern = new Int32Array(n);      // the non-zero rows of the column
    this.piv = new Int32Array(n);          // row pivot chosen at each step
    this.pinv = new Int32Array(n).fill(-1); // old row -> position in the factor
    // The factor grows; start at a few times the matrix and double as needed.
    const guess = Math.max(4 * colPtr[n] + n, 16);
    this.Lp = new Int32Array(n + 1);
    this.Li = new Int32Array(guess);
    this.Lx = new Float64Array(guess);
    this.Up = new Int32Array(n + 1);
    this.Ui = new Int32Array(guess);
    this.Ux = new Float64Array(guess);
    this.singular = false;
    this.fill = 0;
  }

  _growL(need) {
    if (need <= this.Li.length) return;
    const cap = Math.max(need, this.Li.length * 2);
    const Li = new Int32Array(cap); Li.set(this.Li); this.Li = Li;
    const Lx = new Float64Array(cap); Lx.set(this.Lx); this.Lx = Lx;
  }

  _growU(need) {
    if (need <= this.Ui.length) return;
    const cap = Math.max(need, this.Ui.length * 2);
    const Ui = new Int32Array(cap); Ui.set(this.Ui); this.Ui = Ui;
    const Ux = new Float64Array(cap); Ux.set(this.Ux); this.Ux = Ux;
  }

  /**
   * Depth-first search from the non-zeros of column j of A, over the graph of
   * L, to find every row that can become non-zero. Returns the count, with the
   * rows written into this.pattern in topological order (last first).
   */
  _reach(colPtr, rowIdx, j, mark, top0) {
    const { stack, pstack, pattern, Lp, Li, pinv } = this;
    let top = top0;
    for (let p = colPtr[j]; p < colPtr[j + 1]; p++) {
      let i = rowIdx[p];
      if (mark[i] === j) continue;
      // Iterative DFS: the recursion would be n deep on a triangular matrix.
      let head = 0;
      stack[0] = i;
      while (head >= 0) {
        i = stack[head];
        const pi = pinv[i];
        let start;
        if (mark[i] !== j) {
          mark[i] = j;
          pstack[head] = pi < 0 ? 0 : Lp[pi];
        }
        start = pstack[head];
        let done = true;
        const end = pi < 0 ? 0 : Lp[pi + 1];
        for (let k = start; k < end; k++) {
          const child = Li[k];
          if (mark[child] === j) continue;
          pstack[head] = k + 1;
          stack[++head] = child;
          done = false;
          break;
        }
        if (done) {
          head--;
          pattern[--top] = i;
        }
      }
    }
    return top;
  }

  /**
   * Numeric factorisation of the matrix whose values are `values` over the
   * pattern this was built with.
   * @returns {boolean} false if a column was structurally or numerically empty.
   */
  factor(colPtr, rowIdx, values) {
    const n = this.n;
    const { x, mark, pattern, piv, pinv, perm } = this;
    mark.fill(-1);
    pinv.fill(-1);
    let lnz = 0;
    let unz = 0;
    this.singular = false;
    for (let k = 0; k < n; k++) {
      this.Lp[k] = lnz;
      this.Up[k] = unz;
      this._growL(lnz + n);
      this._growU(unz + n);
      const j = perm ? perm[k] : k;
      const top = this._reach(colPtr, rowIdx, j, mark, n);
      // Scatter column j of A into the dense accumulator.
      for (let t = top; t < n; t++) x[pattern[t]] = 0;
      for (let p = colPtr[j]; p < colPtr[j + 1]; p++) x[rowIdx[p]] = values[p];
      // Sparse triangular solve against the columns already done.
      for (let t = top; t < n; t++) {
        const i = pattern[t];
        const pi = pinv[i];
        if (pi < 0) continue;
        const xi = x[i];
        if (xi === 0) continue;
        for (let p = this.Lp[pi]; p < this.Lp[pi + 1]; p++) x[this.Li[p]] -= this.Lx[p] * xi;
      }
      // Pivot on the largest remaining entry that is not yet in U.
      let ipiv = -1;
      let big = 0;
      for (let t = top; t < n; t++) {
        const i = pattern[t];
        if (pinv[i] >= 0) continue;
        const v = Math.abs(x[i]);
        if (v > big) { big = v; ipiv = i; }
      }
      if (ipiv < 0 || big === 0) { this.singular = true; return false; }
      const pivot = x[ipiv];
      pinv[ipiv] = k;
      piv[k] = ipiv;
      // U gets the rows already pivoted, plus the pivot on the diagonal.
      for (let t = top; t < n; t++) {
        const i = pattern[t];
        const pi = pinv[i];
        if (pi < 0 || pi === k) continue;
        if (x[i] !== 0) { this.Ui[unz] = pi; this.Ux[unz] = x[i]; unz++; }
      }
      this.Ui[unz] = k; this.Ux[unz] = pivot; unz++;
      // L gets the rest, divided by the pivot.
      for (let t = top; t < n; t++) {
        const i = pattern[t];
        if (pinv[i] >= 0) continue;
        if (x[i] !== 0) { this.Li[lnz] = i; this.Lx[lnz] = x[i] / pivot; lnz++; }
      }
    }
    this.Lp[n] = lnz;
    this.Up[n] = unz;
    this.fill = lnz + unz;
    return true;
  }

  /** Solve LUx = Pb in place. */
  solve(b) {
    const n = this.n;
    const { piv, pinv, perm, x } = this;
    // Forward substitution in the factor's own order.
    x.set(b);
    for (let k = 0; k < n; k++) {
      const i = piv[k];
      const xk = x[i];
      if (xk === 0) continue;
      for (let p = this.Lp[k]; p < this.Lp[k + 1]; p++) x[this.Li[p]] -= this.Lx[p] * xk;
    }
    // Gather the pivoted entries into a compact vector, back-substitute in U.
    const y = b;
    for (let k = 0; k < n; k++) y[k] = x[piv[k]];
    for (let k = n - 1; k >= 0; k--) {
      const end = this.Up[k + 1] - 1;   // the diagonal, written last
      const yk = (y[k] /= this.Ux[end]);
      if (yk === 0) continue;
      for (let p = this.Up[k]; p < end; p++) y[this.Ui[p]] -= this.Ux[p] * yk;
    }
    // Undo the column permutation.
    if (perm) {
      x.set(y);
      for (let k = 0; k < n; k++) b[perm[k]] = x[k];
    }
    return b;
  }
}

/** Euclidean-ish helpers the controllers and error tests share. */
export function fillWeights(w, u, uprev, reltol, abstol) {
  const n = w.length;
  const scalarAtol = typeof abstol === 'number';
  for (let i = 0; i < n; i++) {
    const a = scalarAtol ? abstol : abstol[i];
    w[i] = a + reltol * Math.max(Math.abs(u[i]), Math.abs(uprev[i]));
  }
  return w;
}

/** The internal norm SciML uses by default: root-mean-square, not maximum. */
export function wrmsNorm(e, w) {
  const n = e.length;
  let s = 0;
  for (let i = 0; i < n; i++) {
    const r = e[i] / w[i];
    s += r * r;
  }
  return Math.sqrt(s / n);
}

/** The maximum-norm alternative: the worst-scaled component decides. */
export function wmaxNorm(e, w) {
  const n = e.length;
  let m = 0;
  for (let i = 0; i < n; i++) {
    const r = Math.abs(e[i] / w[i]);
    if (r > m) m = r;
  }
  return m;
}
