/**
 * Dense linear algebra: LU decomposition with partial pivoting.
 *
 * Dense factorisation, written here rather than pulled from a library. It is
 * O(n^3) per factorisation, so the stiff solvers stay comfortable to a few
 * hundred states and get slow beyond roughly a thousand; past that, ./sparse.js
 * takes over with a sparse CSC path.
 *
 * Matrices are stored row-major as an array of Float64Array rows.
 */

export function zeros(n, m = n) {
	const a = new Array(n);
	for (let i = 0; i < n; i++) a[i] = new Float64Array(m);
	return a;
}

export function identity(n) {
	const a = zeros(n);
	for (let i = 0; i < n; i++) a[i][i] = 1;
	return a;
}

export function norm(v) {
	// Two-norm, guarded against intermediate overflow the way BLAS does.
	let scale = 0, ssq = 1;
	for (let i = 0; i < v.length; i++) {
		const x = v[i];
		if (x === 0) continue;
		const ax = Math.abs(x);
		if (scale < ax) {
			const r = scale / ax;
			ssq = 1 + ssq * r * r;
			scale = ax;
		} else {
			const r = ax / scale;
			ssq += r * r;
		}
	}
	return scale * Math.sqrt(ssq);
}

/**
 * LU factorisation with partial pivoting, done in place on a copy.
 * Returns a reusable solver object, mirroring the factorize()/solve() split of
 * a sparse LU so the Rosenbrock solver can factor once and solve
 * three times per step.
 */
export class LU {
	constructor(n) {
		this.n = n;
		this.lu = zeros(n);
		this.piv = new Int32Array(n);
		this.singular = false;
	}

	/** Factors `A` (an n x n row-major matrix). Does not modify `A`. */
	factorize(A) {
		const n = this.n;
		const lu = this.lu;
		for (let i = 0; i < n; i++) lu[i].set(A[i]);
		const piv = this.piv;
		for (let i = 0; i < n; i++) piv[i] = i;
		this.singular = false;

		for (let k = 0; k < n; k++) {
			// Find pivot.
			let p = k;
			let maxAbs = Math.abs(lu[k][k]);
			for (let i = k + 1; i < n; i++) {
				const v = Math.abs(lu[i][k]);
				if (v > maxAbs) { maxAbs = v; p = i; }
			}
			if (maxAbs === 0) {
				this.singular = true;
				continue; // leave the zero column; solve() will produce Inf/NaN
			}
			if (p !== k) {
				const tmp = lu[p]; lu[p] = lu[k]; lu[k] = tmp;
				const t = piv[p]; piv[p] = piv[k]; piv[k] = t;
			}
			const pivotRow = lu[k];
			const pivot = pivotRow[k];
			for (let i = k + 1; i < n; i++) {
				const row = lu[i];
				const f = row[k] / pivot;
				if (f === 0) continue;
				row[k] = f;
				for (let j = k + 1; j < n; j++) {
					row[j] -= f * pivotRow[j];
				}
			}
		}
		return this;
	}

	/** Solves A x = b for the most recent factorisation. Returns a new array. */
	solve(b) {
		const n = this.n;
		const lu = this.lu;
		const piv = this.piv;
		const x = new Float64Array(n);

		// Apply the row permutation.
		for (let i = 0; i < n; i++) x[i] = b[piv[i]];

		// Forward substitution (unit lower triangle).
		for (let i = 1; i < n; i++) {
			const row = lu[i];
			let s = x[i];
			for (let j = 0; j < i; j++) s -= row[j] * x[j];
			x[i] = s;
		}

		// Back substitution.
		for (let i = n - 1; i >= 0; i--) {
			const row = lu[i];
			let s = x[i];
			for (let j = i + 1; j < n; j++) s -= row[j] * x[j];
			x[i] = s / row[i];
		}
		return x;
	}
}

/**
 * Builds the Rosenbrock iteration matrix Miter = I + c*J in place into `out`.
 * Forms I/(h*d) - J, the matrix a Rosenbrock step solves against.
 */
export function createMiter(c, J, out) {
	const n = J.length;
	const M = out ?? zeros(n);
	for (let i = 0; i < n; i++) {
		const Ji = J[i];
		const Mi = M[i];
		for (let j = 0; j < n; j++) Mi[j] = c * Ji[j];
		Mi[i] += 1;
	}
	return M;
}
