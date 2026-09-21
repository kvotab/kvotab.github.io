/* ==========================================================================
   ode_julia / core / jacobian

   Getting df/du, and turning it into the matrix the solvers actually invert.

   Two things live here.

   1. JacobianCache -- produces J, either by calling a Jacobian the caller
      supplied or by differencing f. Differencing costs one evaluation of the
      whole right-hand side per *group* of structurally orthogonal columns, not
      per column, so a sparsity pattern is worth giving even when the matrix is
      then handled densely: a chemical Jacobian of 63 species needs about 45
      groups, and one of 200 species often still needs fewer than 50.

   2. WFactorization -- forms W = I − γh·J (or I/(γh) − J, which Radau and the
      Rosenbrock methods want) and factorises it, dense or sparse, and knows
      when it may skip doing so. That last part is where the time goes: a stiff
      solver that re-forms and re-factorises W on every step of a smooth
      stretch does several times the work of one that does not.
   ========================================================================== */

import {
  DenseMatrix, CSC, DenseLU, SparseLU, cscFromTriplets, reverseCuthillMcKee,
} from './linalg.js';

const SQRT_EPS = Math.sqrt(Number.EPSILON);   // ~1.49e-8

/**
 * Group the columns of a sparsity pattern so that no two columns in a group
 * share a row.
 *
 * Greedy distance-1 colouring of the column-intersection graph, largest degree
 * first. Perturbing every column of a group at once and differencing gives
 * each of their columns exactly, because no row receives a contribution from
 * more than one of them.
 *
 * @param {number} n
 * @param {Int32Array} colPtr
 * @param {Int32Array} rowIdx
 * @returns {{colour: Int32Array, groups: Int32Array[], count: number}}
 */
export function colourColumns(n, colPtr, rowIdx) {
  // rows -> the columns that touch them, so two columns can be seen to clash.
  const rowCount = new Int32Array(n + 1);
  for (let j = 0; j < n; j++) {
    for (let k = colPtr[j]; k < colPtr[j + 1]; k++) rowCount[rowIdx[k] + 1]++;
  }
  for (let i = 0; i < n; i++) rowCount[i + 1] += rowCount[i];
  const rowCols = new Int32Array(rowCount[n]);
  const at = Int32Array.from(rowCount);
  for (let j = 0; j < n; j++) {
    for (let k = colPtr[j]; k < colPtr[j + 1]; k++) rowCols[at[rowIdx[k]]++] = j;
  }

  const order = Array.from({ length: n }, (_, j) => j)
    .sort((a, b) => (colPtr[b + 1] - colPtr[b]) - (colPtr[a + 1] - colPtr[a]));

  const colour = new Int32Array(n).fill(-1);
  const taken = new Uint8Array(n + 1);
  let count = 0;
  const touched = [];
  for (const j of order) {
    touched.length = 0;
    for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
      const i = rowIdx[k];
      for (let p = rowCount[i]; p < rowCount[i + 1]; p++) {
        const other = rowCols[p];
        const c = colour[other];
        if (c >= 0 && !taken[c]) { taken[c] = 1; touched.push(c); }
      }
    }
    let c = 0;
    while (taken[c]) c++;
    colour[j] = c;
    if (c + 1 > count) count = c + 1;
    for (const t of touched) taken[t] = 0;
  }

  const sizes = new Int32Array(count);
  for (let j = 0; j < n; j++) sizes[colour[j]]++;
  const groups = Array.from({ length: count }, (_, c) => new Int32Array(sizes[c]));
  const fillAt = new Int32Array(count);
  for (let j = 0; j < n; j++) {
    const c = colour[j];
    groups[c][fillAt[c]++] = j;
  }
  return { colour, groups, count };
}

/** A dense n×n pattern, for when the caller gives none. */
export function densePattern(n) {
  const colPtr = new Int32Array(n + 1);
  const rowIdx = new Int32Array(n * n);
  for (let j = 0; j < n; j++) {
    colPtr[j + 1] = (j + 1) * n;
    for (let i = 0; i < n; i++) rowIdx[j * n + i] = i;
  }
  return { colPtr, rowIdx };
}

/**
 * Produces J = df/du at (t, u).
 *
 * Three ways in, in order of preference:
 *   jac(t, u, J)      the caller fills J themselves -- exact, and cheapest
 *   jacPattern + f    differenced, one f per colour group
 *   f alone           differenced, one f per column (n+1 evaluations a time)
 */
export class JacobianCache {
  /**
   * @param {number} n
   * @param {object} opts
   * @param {(t:number,u:Float64Array,J:object)=>void} [opts.jac]  fills J in place
   * @param {{colPtr:Int32Array,rowIdx:Int32Array}} [opts.jacPattern]
   * @param {'auto'|'sparse'|'dense'} [opts.matrix]
   * @param {boolean} [opts.central]  central differences (2 f per group, one more digit)
   */
  constructor(n, opts = {}) {
    this.n = n;
    this.userJac = opts.jac || null;
    this.central = !!opts.central;
    this.pattern = opts.jacPattern || null;
    this.sparse = false;
    this.nf = 0;         // f evaluations spent on Jacobians
    this.njac = 0;

    // Which storage J lives in. Sparse only pays when the pattern is given and
    // genuinely sparse; the factorisation decides separately, since a sparse J
    // can still have a factor so full that a dense LU is faster.
    const want = opts.matrix || 'auto';
    const nnz = this.pattern ? this.pattern.colPtr[n] : n * n;
    this.sparse = want === 'sparse' || (want === 'auto' && !!this.pattern && nnz < 0.25 * n * n);

    if (!this.pattern && (this.sparse || !this.userJac)) this.pattern = densePattern(n);

    if (this.sparse) {
      this.J = new CSC(n, this.pattern.colPtr, this.pattern.rowIdx);
    } else {
      this.J = DenseMatrix.zeros(n);
    }

    // Differencing machinery. Built even when a `jac` was given, because that
    // callback may answer `false` for a point it will not vouch for -- see
    // `evaluate` -- and differencing that one call is the whole answer to it.
    // A colouring at construction and three vectors is what it costs.
    this.groups = colourColumns(n, this.pattern.colPtr, this.pattern.rowIdx).groups;
    this.upert = new Float64Array(n);
    this.fpert = new Float64Array(n);
    this.fpert2 = this.central ? new Float64Array(n) : null;
    this.delta = new Float64Array(n);
  }

  /** How many right-hand-side evaluations one differenced Jacobian costs. */
  get groupCount() { return this.groups ? this.groups.length : 0; }

  /**
   * Fill this.J with df/du at (t, u). `fu` is f(t, u), already computed by the
   * caller -- forward differencing needs it and recomputing it is a waste.
   *
   * @param {(t:number,u:Float64Array,out:Float64Array)=>void} f
   */
  evaluate(f, t, u, fu) {
    this.njac++;
    // A caller's `jac` may answer `false` to mean "not this time" -- the
    // Ecolego port's analytic matrix declines a point where an entry comes out
    // non-finite, and differences for that one call rather than handing over a
    // matrix with an infinity in it. Anything else, including undefined, is
    // the matrix having been filled.
    if (this.userJac && this.userJac(t, u, this.J) !== false) return this.J;
    const { n, groups, upert, fpert, delta } = this;
    const { colPtr, rowIdx } = this.pattern;
    const values = this.sparse ? this.J.values : this.J.data;
    if (this.sparse) values.fill(0); else this.J.data.fill(0);

    for (const group of groups) {
      // One perturbation vector for the whole group.
      upert.set(u);
      for (let g = 0; g < group.length; g++) {
        const j = group[g];
        // The step the reference implementations use: relative to the component, but
        // never smaller than the same fraction of 1, so a component sitting at
        // zero still gets differenced.
        const d = SQRT_EPS * Math.max(Math.abs(u[j]), 1e-5);
        delta[j] = d;
        upert[j] = u[j] + d;
      }
      this.nf++;
      f(t, upert, fpert);
      if (this.central) {
        for (let g = 0; g < group.length; g++) {
          const j = group[g];
          upert[j] = u[j] - delta[j];
        }
        this.nf++;
        f(t, upert, this.fpert2);
      }

      for (let g = 0; g < group.length; g++) {
        const j = group[g];
        const scale = this.central ? 1 / (2 * delta[j]) : 1 / delta[j];
        for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
          const i = rowIdx[k];
          const back = this.central ? this.fpert2[i] : fu[i];
          const v = (fpert[i] - back) * scale;
          if (this.sparse) values[k] = v;
          else this.J.data[j * n + i] = v;
        }
      }
    }
    return this.J;
  }
}

/**
 * W = I − γh·J, or W = I/(γh) − J, formed and factorised.
 *
 * `transform` picks between them. The first is what a Newton iteration on a
 * DIRK or BDF stage wants; the second is what the Rosenbrock methods and Radau
 * want, because their stage equations are already written with the increments
 * divided through by γh, and forming W that way keeps the linear system's
 * scaling independent of the step size.
 *
 * The factorisation is kept and reused. `needsUpdate` is the whole economy of
 * a stiff solver: J is re-differenced only when the Newton iteration says it
 * has gone stale, and W is re-factorised only when J changed or γh moved
 * enough to matter.
 */
export class WFactorization {
  /**
   * @param {number} n
   * @param {JacobianCache} jacCache
   * @param {object} [opts]
   * @param {'auto'|'sparse'|'dense'} [opts.matrix]
   * @param {boolean} [opts.reorder]  apply a fill-reducing ordering (sparse only)
   */
  constructor(n, jacCache, opts = {}) {
    this.n = n;
    this.jacCache = jacCache;
    this.sparse = jacCache.sparse;
    this.nfactor = 0;
    this.nsolve = 0;
    this.fill = null;
    this.ordering = 'none';

    if (this.sparse) {
      // W has the pattern of J plus a full diagonal, which J may not carry.
      const J = jacCache.J;
      const rows = []; const cols = [];
      for (let j = 0; j < n; j++) {
        for (let k = J.colPtr[j]; k < J.colPtr[j + 1]; k++) { rows.push(J.rowIdx[k]); cols.push(j); }
        rows.push(j); cols.push(j);
      }
      this.W = cscFromTriplets(n, rows, cols);
      // Where each entry of J lands in W, worked out once.
      this.jToW = new Int32Array(J.colPtr[n]);
      for (let j = 0; j < n; j++) {
        for (let k = J.colPtr[j]; k < J.colPtr[j + 1]; k++) {
          const i = J.rowIdx[k];
          let p = this.W.colPtr[j];
          while (this.W.rowIdx[p] !== i) p++;
          this.jToW[k] = p;
        }
      }
      this.diagW = new Int32Array(n);
      for (let j = 0; j < n; j++) {
        let p = this.W.colPtr[j];
        while (this.W.rowIdx[p] !== j) p++;
        this.diagW[j] = p;
      }
      const perm = opts.reorder === false
        ? null
        : reverseCuthillMcKee(n, this.W.colPtr, this.W.rowIdx);
      this.ordering = perm ? 'reverse Cuthill-McKee' : 'natural';
      this.lu = new SparseLU(n, this.W.colPtr, this.W.rowIdx, perm);
    } else {
      this.W = DenseMatrix.zeros(n);
      this.lu = new DenseLU(n);
    }

    // What the stored factorisation was built from.
    this.gammaDt = NaN;
    this.transform = false;
    this.jacT = NaN;
    this.jacStale = true;
    this.haveFactor = false;

    // How many steps the stored Jacobian has been used for, and the most it
    // may be. A stiff solver saves most of its work by reusing J, and the
    // usual rule -- reuse while the Newton iteration keeps converging quickly
    // -- has a hole in it: a Newton seeded close enough to converge on its
    // first iteration always reports fast convergence, so J is never
    // questioned. TRBDF2 on the pollution problem walked off with a Jacobian
    // hundreds of steps old, converged happily at every step to the wrong
    // root, and reached 1e9 in components that belong between 0 and 1. By then
    // the relative error test scales with the blown-up state and notices
    // nothing. So there is also a plain age limit, as CVODE has (MSBP = 20).
    this.age = 0;
    this.maxAge = opts.maxJacAge ?? 20;
  }

  /** Say that J is out of date, so the next form() re-evaluates it. */
  markStale() { this.jacStale = true; }

  /** One accepted step has passed. */
  agePlus() { this.age++; }

  /** Has the stored Jacobian been used for as long as it may be? */
  get tooOld() { return this.age >= this.maxAge; }

  /** Is the stored J the one for this (t, u)? */
  isCurrent(t) { return !this.jacStale && this.jacT === t; }

  /**
   * Ensure J is current, then build and factorise W for this γh.
   *
   * @returns {boolean} false if W is singular, which the caller answers by
   *                    cutting the step rather than by giving up.
   */
  form(f, t, u, fu, gammaDt, transform, forceJac = false) {
    const n = this.n;
    // Only the caller decides. An earlier version also re-evaluated whenever t
    // had moved, which is every step, so the Jacobian reuse that the whole
    // design is built around never happened once: FBDF reported exactly as
    // many Jacobians as accepted steps.
    if (forceJac || this.jacStale || this.tooOld) {
      this.jacCache.evaluate(f, t, u, fu);
      this.jacT = t;
      this.jacStale = false;
      this.age = 0;
      this.haveFactor = false;
    } else if (this.haveFactor && this.gammaDt === gammaDt && this.transform === transform) {
      return true;             // nothing has changed: reuse the factor
    }

    const J = this.jacCache.J;
    if (this.sparse) {
      const w = this.W.values;
      w.fill(0);
      const jv = J.values;
      if (transform) {
        const d = 1 / gammaDt;
        for (let k = 0; k < jv.length; k++) w[this.jToW[k]] = -jv[k];
        for (let j = 0; j < n; j++) w[this.diagW[j]] += d;
      } else {
        for (let k = 0; k < jv.length; k++) w[this.jToW[k]] = -gammaDt * jv[k];
        for (let j = 0; j < n; j++) w[this.diagW[j]] += 1;
      }
      this.nfactor++;
      const ok = this.lu.factor(this.W.colPtr, this.W.rowIdx, w);
      this.fill = this.lu.fill;
      this.haveFactor = ok;
      this.gammaDt = gammaDt;
      this.transform = transform;
      return ok;
    }

    const w = this.W.data;
    const jd = J.data;
    if (transform) {
      const d = 1 / gammaDt;
      for (let k = 0; k < w.length; k++) w[k] = -jd[k];
      for (let j = 0; j < n; j++) w[j * n + j] += d;
    } else {
      for (let k = 0; k < w.length; k++) w[k] = -gammaDt * jd[k];
      for (let j = 0; j < n; j++) w[j * n + j] += 1;
    }
    this.nfactor++;
    const ok = this.lu.factor(this.W);
    this.haveFactor = ok;
    this.gammaDt = gammaDt;
    this.transform = transform;
    return ok;
  }

  /** Solve Wx = b in place. */
  solve(b) {
    this.nsolve++;
    this.lu.solve(b);
    return b;
  }
}
