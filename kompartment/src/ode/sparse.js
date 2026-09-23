/**
 * Sparse linear algebra for the iteration matrix I - h*J.
 *
 * The stiff solvers spend their time factorising that matrix, and in a
 * compartment model it is nearly all zeros: a compartment couples only to the
 * compartments it exchanges with and to its own decay chain, so a row holds a
 * handful of entries whatever the model's size. Factorising it densely costs
 * O(n^3) and, past a few hundred states, is the whole run. The usual answer is
 * to call a native sparse library; this is the part of one such library this
 * tool needs, in plain JavaScript.
 *
 * The factorisation is Gilbert-Peierls left-looking LU with partial pivoting --
 * the algorithm behind CSparse's cs_lu, which is what KLU itself builds on.
 * Its virtue is that the symbolic phase is per column and touches only the
 * entries it will use, so the total cost is proportional to the arithmetic
 * actually performed rather than to n^2 or n^3.
 *
 * Sparsity is not free: on a matrix whose factor fills in towards dense, this
 * is slower than the dense LU in ./linalg.js, and measurably so. The caller
 * decides, from the fill it measures rather than from the pattern it hopes for.
 *
 * Index conventions, used throughout:
 *
 *   m, n         rows, columns
 *   colptr[j]    start of column j in rowind/values;   colptr[n] === nnz
 *   rowind[p]    row index of the p-th stored entry
 *   values[p]    value of the p-th stored entry
 *   p, q         positions in rowind/values, never matrix indices
 *   i            a row index in the ORIGINAL numbering
 *   j            a column index in the ORIGINAL numbering
 *   k            a step of the factorisation, i.e. a column of L and of U
 *   pinv[i]      = k when original row i is the pivot row of step k, else -1
 *   perm[k]      = i, the inverse of pinv
 *   qcol[k]      = j, the original column factorised at step k
 */

import { RefactorLU, OPS_BUDGET } from './refactor.js';

// --- the container ----------------------------------------------------------

export class CSC {
	/**
	 * @param {number} m rows
	 * @param {number} n columns
	 * @param {Int32Array} colptr length n+1
	 * @param {Int32Array} rowind length >= colptr[n]
	 * @param {Float64Array} values length >= colptr[n]
	 */
	constructor(m, n, colptr, rowind, values) {
		this.m = m;
		this.n = n;
		this.colptr = colptr;
		this.rowind = rowind;
		this.values = values;
	}

	get nnz() { return this.colptr[this.n]; }

	copy() {
		return new CSC(
			this.m, this.n,
			Int32Array.from(this.colptr),
			Int32Array.from(this.rowind.subarray(0, this.nnz)),
			Float64Array.from(this.values.subarray(0, this.nnz)),
		);
	}

	/** Largest |entry|; 0 for an empty matrix. Used for growth factors. */
	maxAbs() {
		let a = 0;
		const nz = this.nnz, v = this.values;
		for (let p = 0; p < nz; p++) { const t = Math.abs(v[p]); if (t > a) a = t; }
		return a;
	}
}

/**
 * Transpose. Also the cheapest way to get a row-wise (CSR) view of A: the
 * result's colptr is indexed by A's ROW number and its rowind holds A's COLUMN
 * numbers. Counting sort, O(m + n + nnz), and it leaves each output column
 * sorted by index.
 */
export function cscTranspose(A) {
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
			Ti[q] = j;
			Tx[q] = values[p];
		}
	}
	return new CSC(n, m, Tp, Ti, Tx);
}

/**
 * Merges entries that repeat within a column. Assumes each column's row
 * indices are already sorted, which is what a double transpose guarantees.
 */
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
			Ci[nz] = i;
			Cx[nz] = s;
			nz++;
		}
	}
	Cp[n] = nz;
	return new CSC(m, n, Cp, Ci.slice(0, nz), Cx.slice(0, nz));
}

/**
 * Builds a CSC from triplets (i, j, v), SUMMING duplicates -- the assembly
 * convention every finite-element and compartment assembler relies on, and the
 * one the derivative generator in src/sim/builder.js naturally produces (each
 * transfer contributes -flux to one row and +flux to another, and several
 * transfers can hit the same (i, j)).
 *
 * Row indices come out sorted within each column: build unsorted by counting
 * sort on the column, then transpose twice (each transpose is a counting sort
 * that leaves the result ordered), then merge equal neighbours.
 */
export function cscFromTriplets(m, n, I, J, V) {
	const nz = I.length;
	if (J.length !== nz || V.length !== nz) {
		throw new Error('cscFromTriplets: I, J and V must have the same length');
	}
	const colptr = new Int32Array(n + 1);
	for (let p = 0; p < nz; p++) {
		const j = J[p];
		if (j < 0 || j >= n) throw new Error(`cscFromTriplets: column ${j} out of range`);
		colptr[j + 1]++;
	}
	for (let j = 0; j < n; j++) colptr[j + 1] += colptr[j];
	const next = Int32Array.from(colptr.subarray(0, n));
	const rowind = new Int32Array(nz);
	const values = new Float64Array(nz);
	for (let p = 0; p < nz; p++) {
		const i = I[p];
		if (i < 0 || i >= m) throw new Error(`cscFromTriplets: row ${i} out of range`);
		const q = next[J[p]]++;
		rowind[q] = i;
		values[q] = V[p];
	}
	const unsorted = new CSC(m, n, colptr, rowind, values);
	return cscMergeSorted(cscTranspose(cscTranspose(unsorted)));
}

/** CSC -> row-major dense. */
export function cscToDense(A) {
	const { m, n, colptr, rowind, values } = A;
	const D = new Array(m);
	for (let i = 0; i < m; i++) D[i] = new Float64Array(n);
	for (let j = 0; j < n; j++) {
		for (let p = colptr[j]; p < colptr[j + 1]; p++) D[rowind[p]][j] += values[p];
	}
	return D;
}

/** out = A * x. Column-wise (axpy) form: the natural access order for CSC. */
export function cscMulVec(A, x, out) {
	const { m, n, colptr, rowind, values } = A;
	const y = out ?? new Float64Array(m);
	y.fill(0);
	for (let j = 0; j < n; j++) {
		const xj = x[j];
		if (xj === 0) continue;
		for (let p = colptr[j]; p < colptr[j + 1]; p++) y[rowind[p]] += values[p] * xj;
	}
	return y;
}

// --- the iteration matrix ---------------------------------------------------

/**
 * The hot path. J's pattern is fixed for the whole run and its values change
 * every step, so the pattern of Miter = I - h*J -- which is J's pattern with
 * the diagonal forced in -- is computed once and then only filled.
 *
 * Returns an object whose `update(h, Jvalues)` rewrites M.values in place in
 * O(nnz) with no allocation and no searching. `Jvalues` must be the values
 * array of a CSC with exactly the pattern this builder was made from.
 */
export function makeMiterBuilder(J) {
	const n = J.n;
	if (J.m !== n) throw new Error('makeMiterBuilder: J must be square');
	const nzJ = J.nnz;

	// Pattern = pattern(J) union diagonal. Built through the triplet path so
	// duplicates (a J entry that is already on the diagonal) merge.
	const I2 = new Int32Array(nzJ + n);
	const J2 = new Int32Array(nzJ + n);
	const V2 = new Float64Array(nzJ + n);
	let t = 0;
	for (let j = 0; j < n; j++) {
		for (let p = J.colptr[j]; p < J.colptr[j + 1]; p++) { I2[t] = J.rowind[p]; J2[t] = j; t++; }
	}
	for (let j = 0; j < n; j++) { I2[t] = j; J2[t] = j; t++; }
	const M = cscFromTriplets(n, n, I2, J2, V2);

	// jToM[p] = the slot in M.values holding J's p-th entry.
	// diagPos[i] = the slot in M.values holding M(i,i).
	const jToM = new Int32Array(nzJ);
	const diagPos = new Int32Array(n).fill(-1);
	const pos = new Int32Array(n).fill(-1);
	for (let j = 0; j < n; j++) {
		for (let p = M.colptr[j]; p < M.colptr[j + 1]; p++) pos[M.rowind[p]] = p;
		for (let p = J.colptr[j]; p < J.colptr[j + 1]; p++) {
			const s = pos[J.rowind[p]];
			if (s < 0) throw new Error('makeMiterBuilder: pattern mismatch');
			jToM[p] = s;
		}
		diagPos[j] = pos[j];
		for (let p = M.colptr[j]; p < M.colptr[j + 1]; p++) pos[M.rowind[p]] = -1;
	}

	const Mx = M.values;
	return {
		M,
		jToM,
		diagPos,
		/** M := I - h*J. Returns M. */
		update(h, Jvalues) {
			Mx.fill(0);
			for (let p = 0; p < nzJ; p++) Mx[jToM[p]] = -h * Jvalues[p];
			for (let i = 0; i < n; i++) Mx[diagPos[i]] += 1;
			return M;
		},
	};
}

// 3. Gilbert-Peierls left-looking LU with partial pivoting

// --- Gilbert-Peierls LU with partial pivoting -------------------------------

/**
 * Factorises P*A*Q = L*U, where
 *
 *	 Q is the (optional, fill-reducing) COLUMN ordering, fixed before the
 *	   numerics start:	step k factorises original column qcol[k];
 *	 P is the ROW permutation chosen by partial pivoting DURING the numerics,
 *	   recorded as pinv[i] = k;
 *	 L is unit lower triangular, stored by columns with the unit diagonal as
 *	   the FIRST entry of each column;
 *	 U is upper triangular, stored by columns with the diagonal as the LAST
 *	   entry of each column.
 *
 * Storage layout, after a successful factorise:
 *
 *	 Lp[k] .. Lp[k+1]-1	  column k of L; Li[Lp[k]] === k, Lx[Lp[k]] === 1
 *	 Up[k] .. Up[k+1]-1	  column k of U; Ui[Up[k+1]-1] === k
 *	 pinv[i]			  step at which original row i became a pivot
 *	 perm[k]			  original row of the pivot at step k (inverse of pinv)
 *
 * L's row indices are in the PERMUTED numbering after finalisation; they are in
 * the ORIGINAL numbering while the factorisation is running, because the
 * permutation of the rows still to be pivoted is not known yet.
 *
 * Cost: the symbolic depth-first search per column touches exactly the entries
 * of L it will use, so the total is O(flops(LU)) -- proportional to the number
 * of floating-point operations actually performed, never to n^2 or n^3. That is
 * the whole point of Gilbert-Peierls: no separate symbolic phase, no upper
 * bound on the pattern, and no work proportional to the zeros.
 */
export class SparseLU {
	constructor(n) {
		this.n = n;
		this.pinv = new Int32Array(n);
		this.perm = new Int32Array(n);
		this.qcol = null;

		// Workspace, allocated once and reused across factorisations.
		this.x = new Float64Array(n);		// dense accumulator, indexed by ORIGINAL row
		this.xi = new Int32Array(n);		// output stack of the DFS: xi[top..n-1]
		this.stack = new Int32Array(n);		// DFS node stack
		this.pstack = new Int32Array(n);	// DFS "resume here" pointer per stack frame
		this.mark = new Int32Array(n).fill(-1);
		this.stampCounter = 0;

		const cap = Math.max(4 * n, 64);
		this.Lp = new Int32Array(n + 1);
		this.Li = new Int32Array(cap);
		this.Lx = new Float64Array(cap);
		this.Up = new Int32Array(n + 1);
		this.Ui = new Int32Array(cap);
		this.Ux = new Float64Array(cap);

		this.lnz = 0;
		this.unz = 0;
		this.singular = false;
		this.failColumn = -1;		// step k at which no pivot was found
		this.failOriginalColumn = -1;
		this.pivotMin = 0;			// smallest |pivot| accepted
		this.growth = 0;			// max|U| / max|A|, the growth factor
		this.maxA = 0;
	}

	_growL(need) {
		if (need <= this.Li.length) return;
		let cap = this.Li.length;
		while (cap < need) cap *= 2;
		const Li = new Int32Array(cap); Li.set(this.Li); this.Li = Li;
		const Lx = new Float64Array(cap); Lx.set(this.Lx); this.Lx = Lx;
	}

	_growU(need) {
		if (need <= this.Ui.length) return;
		let cap = this.Ui.length;
		while (cap < need) cap *= 2;
		const Ui = new Int32Array(cap); Ui.set(this.Ui); this.Ui = Ui;
		const Ux = new Float64Array(cap); Ux.set(this.Ux); this.Ux = Ux;
	}

	/**
	 * SYMBOLIC PHASE for one column.
	 *
	 * Finds Reach(L, pattern of A(:,col)): the set of rows i for which the
	 * solution x of L*x = A(:,col) can be nonzero. In graph terms L is the
	 * adjacency of a directed graph whose edge j -> i exists when L(i,j) != 0;
	 * the nonzero pattern of x is exactly the set of nodes reachable from the
	 * nonzero rows of A(:,col). Gilbert and Peierls' theorem.
	 *
	 * Writes that set into xi[top..n-1] in TOPOLOGICAL order (a node appears
	 * before every node it can reach), which is exactly the order in which the
	 * numeric solve must process it, and returns `top`.
	 *
	 * The DFS is iterative -- a recursive one blows the JS stack on a long
	 * decay chain, which is precisely the structure a radionuclide model has.
	 * `mark` is stamped rather than cleared, so the whole routine is O(size of
	 * the reach), never O(n).
	 */
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
				const J = pinv[j];				// column of L holding row j, or -1
				if (mark[j] !== stamp) {
					mark[j] = stamp;
					// Skip Li[Lp[J]], which is the unit diagonal, i.e. j itself:
					// it is already marked, so visiting it would be a no-op.
					pstack[head] = J < 0 ? 0 : Lp[J] + 1;
				}
				const pend = J < 0 ? 0 : Lp[J + 1];
				let done = true;
				for (let p = pstack[head]; p < pend; p++) {
					const w = Li[p];
					if (mark[w] === stamp) continue;
					pstack[head] = p;			// resume here when the child returns
					stack[++head] = w;
					done = false;
					break;
				}
				if (done) {
					head--;
					xi[--top] = j;				// post-order == reverse topological
				}
			}
		}
		return top;
	}

	/**
	 * NUMERIC PHASE for one column: solve L*x = A(:,col) for the sparse x,
	 * touching only the reach found above. x is left in the dense accumulator,
	 * its pattern in xi[top..n-1].
	 */
	_spsolve(Ap, Ai, Ax, col) {
		const n = this.n;
		const top = this._reach(Ap, Ai, col);
		const { xi, x, pinv, Lp, Li, Lx } = this;

		for (let p = top; p < n; p++) x[xi[p]] = 0;				 // clear the reach
		for (let p = Ap[col]; p < Ap[col + 1]; p++) x[Ai[p]] = Ax[p];  // scatter A(:,col)

		for (let px = top; px < n; px++) {
			const j = xi[px];
			const J = pinv[j];
			if (J < 0) continue;				// row j has no pivot yet: nothing to do
			// Counted whatever the value, for comparing with ./refactor.js,
			// whose count is structural too: a zero at the trial is rarely a
			// zero at every step.
			this.flops += Lp[J + 1] - Lp[J] - 1;
			const xj = x[j];					// L(j,j) === 1, so no division
			if (xj === 0) continue;
			for (let p = Lp[J] + 1; p < Lp[J + 1]; p++) x[Li[p]] -= Lx[p] * xj;
		}
		return top;
	}

	/**
	 * @param {CSC} A square, in CSC
	 * @param {{q?: Int32Array|null, tol?: number}} opts
	 *		  q	  column ordering; step k factorises column q[k]. null = natural.
	 *		  tol 1 = strict partial pivoting (default). 0 < tol < 1 prefers the
	 *			  diagonal entry whenever |a_dd| >= tol * max|a_ik|, which is
	 *			  what KLU and UMFPACK call a threshold pivot: it keeps the
	 *			  fill-reducing ordering intact at the price of a bounded loss of
	 *			  stability. tol = 0 is diagonal pivoting, which is unsafe.
	 */
	factorize(A, opts = {}) {
		const n = this.n;
		if (A.n !== n || A.m !== n) throw new Error(`SparseLU: expected ${n}x${n}`);
		const q = opts.q ?? null;
		const tol = opts.tol ?? 1;

		const Ap = A.colptr, Ai = A.rowind, Ax = A.values;
		this.qcol = q;
		this.singular = false;
		this.failColumn = -1;
		this.failOriginalColumn = -1;
		this.pinv.fill(-1);
		this.mark.fill(-1);
		this.stampCounter = 0;
		this.x.fill(0);
		this.flops = 0;

		this.maxA = A.maxAbs();
		let maxU = 0;
		let pivotMin = Infinity;
		let lnz = 0, unz = 0;

		for (let k = 0; k < n; k++) {
			this.Lp[k] = lnz;
			this.Up[k] = unz;
			// A column can hold at most n entries, so reserving n up front
			// means the inner loops can never overflow.
			this._growL(lnz + n);
			this._growU(unz + n);
			const { Li, Lx, Ui, Ux, xi, x, pinv } = this;

			const col = q ? q[k] : k;
			const top = this._spsolve(Ap, Ai, Ax, col);

			// --- pivot choice, and the split of x into U(:,k) and L(:,k) -----
			// Rows already pivotal belong to U; rows not yet pivotal are the
			// candidates for this step's pivot and, once scaled, become L(:,k).
			let ipiv = -1;
			let best = -1;
			for (let p = top; p < n; p++) {
				const i = xi[p];
				if (pinv[i] < 0) {
					const t = Math.abs(x[i]);
					if (t > best) { best = t; ipiv = i; }
				} else {
					Ui[unz] = pinv[i];
					Ux[unz] = x[i];
					unz++;
					const t = Math.abs(x[i]);
					if (t > maxU) maxU = t;
				}
			}
			if (ipiv === -1 || !(best > 0)) {
				// ipiv === -1: every row this column can reach is already a
				// pivot -- the matrix is STRUCTURALLY singular.
				// best === 0: the column is numerically zero below the already
				// eliminated rows -- numerically singular.
				this.singular = true;
				this.failColumn = k;
				this.failOriginalColumn = col;
				this.lnz = lnz; this.unz = unz;
				for (let kk = k; kk <= n; kk++) { this.Lp[kk] = lnz; this.Up[kk] = unz; }
				return this;
			}
			// Threshold pivoting: keep the diagonal if it is within tol of the
			// best candidate. With tol === 1 this only fires when the diagonal
			// IS the best candidate, i.e. it is plain partial pivoting.
			if (tol < 1 && pinv[col] < 0 && Math.abs(x[col]) >= best * tol) ipiv = col;

			const pivot = x[ipiv];
			if (Math.abs(pivot) < pivotMin) pivotMin = Math.abs(pivot);
			if (Math.abs(pivot) > maxU) maxU = Math.abs(pivot);

			Ui[unz] = k;				 // U(k,k) is stored LAST in column k
			Ux[unz] = pivot;
			unz++;
			pinv[ipiv] = k;
			Li[lnz] = ipiv;				 // L(k,k) is stored FIRST in column k
			Lx[lnz] = 1;
			lnz++;

			for (let p = top; p < n; p++) {
				const i = xi[p];
				if (pinv[i] < 0) {		 // still not pivotal: an entry of L(:,k)
					Li[lnz] = i;
					Lx[lnz] = x[i] / pivot;
					lnz++;
				}
				x[i] = 0;				 // leave the accumulator clean
			}
		}

		this.Lp[n] = lnz;
		this.Up[n] = unz;
		this.lnz = lnz;
		this.unz = unz;
		this.pivotMin = pivotMin === Infinity ? 0 : pivotMin;
		this.growth = this.maxA > 0 ? maxU / this.maxA : 0;

		// Rewrite L's row indices into the permuted numbering, so that L is
		// genuinely lower triangular and the forward solve can run in order.
		const { Li, pinv, perm } = this;
		for (let p = 0; p < lnz; p++) Li[p] = pinv[Li[p]];
		for (let i = 0; i < n; i++) perm[pinv[i]] = i;
		return this;
	}


	/** x := L \ x, in place, x in the PERMUTED numbering. */
	lsolve(x) {
		const n = this.n;
		const { Lp, Li, Lx } = this;
		for (let j = 0; j < n; j++) {
			const xj = x[j];					// L(j,j) === 1
			if (xj === 0) continue;
			for (let p = Lp[j] + 1; p < Lp[j + 1]; p++) x[Li[p]] -= Lx[p] * xj;
		}
		return x;
	}

	/** x := U \ x, in place, x in the PERMUTED numbering. */
	usolve(x) {
		const n = this.n;
		const { Up, Ui, Ux } = this;
		for (let j = n - 1; j >= 0; j--) {
			const d = Ux[Up[j + 1] - 1];		// U(j,j) is the last entry
			const xj = x[j] / d;
			x[j] = xj;
			if (xj === 0) continue;
			for (let p = Up[j]; p < Up[j + 1] - 1; p++) x[Ui[p]] -= Ux[p] * xj;
		}
		return x;
	}

	/**
	 * Solves A*x = b. Returns a new Float64Array unless `out` is given.
	 *
	 *	 P b  ->  L \ .	 ->	 U \ .	->	scatter through Q
	 */
	solve(b, out) {
		const n = this.n;
		if (this.singular) {
			throw new Error(
				`SparseLU.solve: the factorisation failed at column `
				+ `${this.failOriginalColumn} (step ${this.failColumn}); the matrix is singular`,
			);
		}
		const { perm, qcol } = this;
		const t = this._solveWork ?? (this._solveWork = new Float64Array(n));
		for (let k = 0; k < n; k++) t[k] = b[perm[k]];	 // t = P*b
		this.lsolve(t);
		this.usolve(t);
		const x = out ?? new Float64Array(n);
		if (qcol) for (let k = 0; k < n; k++) x[qcol[k]] = t[k];
		else x.set(t);
		return x;
	}

	/** L and U as CSC matrices, for inspection and testing. */
	factors() {
		const n = this.n;
		const L = new CSC(n, n, Int32Array.from(this.Lp),
			Int32Array.from(this.Li.subarray(0, this.lnz)),
			Float64Array.from(this.Lx.subarray(0, this.lnz)));
		const U = new CSC(n, n, Int32Array.from(this.Up),
			Int32Array.from(this.Ui.subarray(0, this.unz)),
			Float64Array.from(this.Ux.subarray(0, this.unz)));
		return { L, U };
	}
}

// 4. Triangular solves against a right-hand side that is itself sparse

// --- fill-reducing ordering -------------------------------------------------

/** Pattern of A + A', diagonal removed, as adjacency lists. */
function symmetricAdjacency(A) {
	const n = A.n;
	const { colptr, rowind } = A;
	const deg = new Int32Array(n);
	// Count, allowing duplicates; they are removed after the fact.
	for (let j = 0; j < n; j++) {
		for (let p = colptr[j]; p < colptr[j + 1]; p++) {
			const i = rowind[p];
			if (i === j) continue;
			deg[i]++;
			deg[j]++;
		}
	}
	const ptr = new Int32Array(n + 1);
	for (let i = 0; i < n; i++) ptr[i + 1] = ptr[i] + deg[i];
	const next = Int32Array.from(ptr.subarray(0, n));
	const adj = new Int32Array(ptr[n]);
	for (let j = 0; j < n; j++) {
		for (let p = colptr[j]; p < colptr[j + 1]; p++) {
			const i = rowind[p];
			if (i === j) continue;
			adj[next[i]++] = j;
			adj[next[j]++] = i;
		}
	}
	// De-duplicate each list.
	const out = new Array(n);
	const seen = new Int32Array(n).fill(-1);
	for (let i = 0; i < n; i++) {
		const list = [];
		for (let p = ptr[i]; p < ptr[i + 1]; p++) {
			const w = adj[p];
			if (seen[w] === i) continue;
			seen[w] = i;
			list.push(w);
		}
		out[i] = list;
	}
	return out;
}

/**
 * Reverse Cuthill-McKee on the pattern of A + A'. A bandwidth reducer rather
 * than a fill reducer, but for the layered, chain-like graphs a compartment
 * model produces the two coincide closely, and it is O(nnz log) with no risk of
 * the quadratic blow-up minimum degree can hit.
 */
export function reverseCuthillMcKeeOrder(A) {
	const n = A.n;
	const adj = symmetricAdjacency(A);
	const degree = adj.map((l) => l.length);
	const visited = new Uint8Array(n);
	const order = new Int32Array(n);
	let filled = 0;

	// Start each component at its lowest-degree node -- the cheap stand-in for
	// a pseudo-peripheral vertex.
	const byDegree = Array.from({ length: n }, (_, i) => i)
		.sort((a, b) => degree[a] - degree[b] || a - b);

	const queue = new Int32Array(n);
	for (const seed of byDegree) {
		if (visited[seed]) continue;
		let head = 0, tail = 0;
		queue[tail++] = seed;
		visited[seed] = 1;
		while (head < tail) {
			const v = queue[head++];
			order[filled++] = v;
			const nb = adj[v].filter((u) => !visited[u]).sort((a, b) => degree[a] - degree[b] || a - b);
			for (const u of nb) { visited[u] = 1; queue[tail++] = u; }
		}
	}
	const rev = new Int32Array(n);
	for (let i = 0; i < n; i++) rev[i] = order[n - 1 - i];
	return rev;
}

// 6. Greedy distance-1 column colouring

// --- the iteration matrix, when it pays to keep it sparse -------------------

/**
 * Below this many equations a dense factorisation is not the bottleneck and
 * the indirection here is all cost. Measured on a chain model: the two are
 * level at about twenty states and sparse is ahead by half again at twenty-four.
 */
const SPARSE_MIN_EQUATIONS = 24;

/**
 * ... and above this share of a dense factor, the sparse one has filled in far
 * enough to lose anyway. Judged on the factor itself rather than on the
 * pattern: a matrix can be one per cent populated and still fill in to fifty,
 * at which point sparse is about twice as slow as dense.
 */
const SPARSE_MAX_FILL = 0.15;

/**
 * @param {object} [opts]
 * @param {boolean} [opts.mustBeSparse] there is no dense alternative to fall
 *   back to, so answer whatever the trial says about the fill
 */
export function sparseIterationMatrix(neq, pattern, values, { mustBeSparse = false } = {}) {
	if (neq < SPARSE_MIN_EQUATIONS) return null;
	const J = new CSC(
		neq, neq, pattern.colPtr, pattern.rowIdx, new Float64Array(pattern.nnz),
	);
	const builder = makeMiterBuilder(J);
	const factors = new SparseLU(neq);

	// Which column ordering, and indeed whether to be sparse at all, is decided
	// here -- on one real factorisation of each candidate rather than on the
	// pattern's promise. A model whose compartments happen to be declared in a
	// scattered order fills in badly in the natural ordering and hardly at all
	// after renumbering, and the only way to know is to try.
	const M = builder.update(1e-3, values);
	factors.factorize(M);
	let best = factors.singular ? Infinity : factors.lnz + factors.unz;
	let q = null;
	const rcm = reverseCuthillMcKeeOrder(J);
	factors.factorize(M, { q: rcm });
	if (!factors.singular && factors.lnz + factors.unz < best) {
		best = factors.lnz + factors.unz;
		q = rcm;
	}
	// Both trials singular tells us nothing about the fill, and it used to be
	// read as infinite fill -- "sparse is hopeless, go dense". It is not a
	// statement about the pattern at all: the trial is `I - 1e-3*J` at one
	// instant, and a matrix that is singular there may factorise perfectly
	// well at every step the solver actually takes. A 16,244-state
	// assessment model ran for nine thousand years on the sparse path, met an
	// event, found this trial singular at the restart, and was handed a dense
	// iteration matrix of 2.1 GB, which took the process with it.
	//
	// So: keep the sparse path, on the ordering that suits these graphs, and
	// let `form` below report a matrix that is genuinely singular -- which it
	// does, by name, with the reason.
	if (best === Infinity) {
		best = pattern.nnz;
		q = rcm;
	}
	const fillsIn = !mustBeSparse && !(best < SPARSE_MAX_FILL * neq * neq);
	const searching = (a, current) => {
		factors.factorize(builder.update(a, current), { q });
		if (factors.singular) {
			throw new Error(
				`The iteration matrix I - h*J is singular at column `
					+ `${factors.failOriginalColumn}. A compartment with no way in `
					+ `and no way out will do this.`,
			);
		}
		return factors;
	};

	// The LU that keeps its pivots (./refactor.js), if it costs no more than
	// what would otherwise be used: the dense LU's n^3/3 (a quarter of it, for
	// margin) where this factor fills in, and this LU's own count where it does
	// not, both structural. Two trials: pivots by threshold Markowitz, and rows
	// chosen in the column order found above. Each stops as soon as it has
	// spent that much, or OPS_BUDGET.
	factors.factorize(M, { q });
	const alternative = fillsIn ? 0.25 * neq * neq * neq / 3 : factors.flops;
	const limit = Math.min(OPS_BUDGET, alternative);
	const trial = (columns, most) => {
		const lu = new RefactorLU(pattern, columns);
		lu.limit = most;
		const ok = lu.factor(1e-3, values);
		lu.limit = Infinity;
		return ok ? lu : null;
	};
	const byMarkowitz = trial(null, limit);
	const byColumns = trial(q ?? Int32Array.from({ length: neq }, (_, i) => i),
		byMarkowitz ? Math.min(limit, byMarkowitz.ops) : limit);
	const kept = byColumns && (!byMarkowitz || byColumns.ops < byMarkowitz.ops) ? byColumns : byMarkowitz;
	if (kept) {
		// A matrix it declines goes to the searching LU, whose answer, or
		// singular message, is final.
		let current = kept;
		const matrix = {
			sparse: true,
			lu: 'refactor',
			fill: kept.nnz,
			repivots: 0,
			fallbacks: 0,
			form(a, J) {
				const before = kept.repivots;
				if (kept.factor(a, J)) {
					current = kept;
					matrix.fill = kept.nnz;
				} else {
					matrix.fallbacks++;
					current = searching(a, J);
				}
				matrix.repivots += kept.repivots - before;
			},
			solve(rhs) {
				return current.solve(rhs);
			},
			rowsDotY(J, yp, out) {
				return sparseMatVec(pattern, J, yp, out);
			},
		};
		return matrix;
	}
	if (fillsIn) return null;

	return {
		sparse: true,
		lu: 'sparse',
		fill: best,
		form(a, current) {
			searching(a, current);
		},
		solve(rhs) {
			return factors.solve(rhs);
		},
		rowsDotY(current, yp, out) {
			return sparseMatVec(pattern, current, yp, out);
		},
	};
}


/**
 * A CSC matrix times a vector, every row at once.
 *
 * The caller wants all `n` rows, and asking for them one at a time meant
 * walking the whole matrix `n` times over -- once per row, throwing away every
 * entry not in that row -- which is n*nnz where the product itself is nnz. On
 * a thousand-state model with five thousand stored entries that is five
 * million multiply-adds for five thousand useful ones, and it grows as the
 * square. One pass down the columns instead, accumulating into the rows.
 */
export function sparseMatVec(pattern, values, yp, out) {
	out.fill(0);
	for (let j = 0; j < pattern.n; j++) {
		const v = yp[j];
		for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) {
			out[pattern.rowIdx[p]] += values[p] * v;
		}
	}
	return out;
}
