/**
 * Dense linear algebra: LU decomposition with partial pivoting.
 *
 * Dense factorisation, written here rather than pulled from a library. It is
 * O(n^3) per factorisation, so the stiff solvers stay comfortable to a few
 * hundred states and get slow beyond roughly a thousand; past that, ./sparse.js
 * takes over with a sparse CSC path.
 *
 * Matrices are stored row-major as an array of Float64Array rows.
 *
 * One of the modules of resources/js/ode_core/, the solver core shared by
 * facsimile.html, rtm.html and Kompartment: see its README.md.
 */

/** The machine epsilon, 2^-52, which every tolerance and increment here is scaled by. */
export const EPS = 2 ** -52;

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
 * LU factorisation with partial pivoting, reusable across factorisations of
 * the same size: `factorize` copies a matrix in, `formAndFactor` assembles
 * Mass - a*J into it from a sparse Jacobian, and `solve` answers for the most
 * recent one, as often as asked -- the Rosenbrock solver factors once and
 * solves three times per step.
 *
 * A column with no usable pivot -- nothing nonzero below the diagonal, or a
 * value that is not finite -- ends the factorisation there, with `singular`
 * set, `failColumn` the step it happened at, and `nonFinite` telling the two
 * apart (`failValue` is the value that was not a number). Every caller stops
 * there and says why; nothing solves with a factor that failed.
 */
export class LU {
	constructor(n) {
		this.n = n;
		this.lu = zeros(n);
		this.piv = new Int32Array(n);
		this.singular = false;
		this.nonFinite = false;
		this.failColumn = -1;
		this.failValue = 0;
	}

	/** Factors `A` (an n x n row-major matrix). Does not modify `A`. */
	factorize(A) {
		const n = this.n;
		const lu = this.lu;
		for (let i = 0; i < n; i++) lu[i].set(A[i]);
		return this.factorizeInPlace();
	}

	/**
	 * Factors Mass - a*J, with J given as the values of a CSC pattern
	 * {n, colPtr, rowIdx}: optionally in the scaled variables y_i / w_i, and
	 * with `mass` the diagonal of the mass matrix (one for a variable with a
	 * differential equation, zero for one with an algebraic one; absent, the
	 * identity). See makeMiterBuilder in ./sparse.js, which does the same in CSC.
	 */
	formAndFactor(a, pattern, values, w, mass) {
		const n = this.n, lu = this.lu;
		for (let i = 0; i < n; i++) lu[i].fill(0);
		// An entry that is not a number would solve to finite nonsense -- x/Inf
		// is 0 -- so it is not factorised at all, and its column is named.
		let bad = -1, badValue = 0;
		for (let j = 0; j < n; j++) {
			const wj = w ? w[j] : 1;
			for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) {
				const i = pattern.rowIdx[p];
				const v = -a * values[p] * (w ? wj / w[i] : 1);
				if (bad < 0 && !Number.isFinite(v)) { bad = j; badValue = v; }
				lu[i][j] = v;
			}
		}
		if (bad >= 0) {
			this.singular = true;
			this.nonFinite = true;
			this.failColumn = bad;
			this.failValue = badValue;
			return this;
		}
		if (mass) for (let i = 0; i < n; i++) lu[i][i] += mass[i];
		else for (let i = 0; i < n; i++) lu[i][i] += 1;
		return this.factorizeInPlace();
	}

	/** Factors what `this.lu` holds, in place. */
	factorizeInPlace() {
		const n = this.n, lu = this.lu, piv = this.piv;
		for (let i = 0; i < n; i++) piv[i] = i;
		this.singular = false;
		this.nonFinite = false;
		this.failColumn = -1;
		for (let k = 0; k < n; k++) {
			let p = k, maxAbs = Math.abs(lu[k][k]);
			for (let i = k + 1; i < n; i++) {
				const v = Math.abs(lu[i][k]);
				if (v > maxAbs) { maxAbs = v; p = i; }
			}
			if (!(maxAbs > 0) || !Number.isFinite(maxAbs)) {
				this.singular = true;
				this.nonFinite = maxAbs !== 0;
				this.failColumn = k;
				this.failValue = maxAbs;
				return this;
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
				for (let j = k + 1; j < n; j++) row[j] -= f * pivotRow[j];
			}
		}
		return this;
	}

	/** Solves A x = b for the most recent factorisation, into `out` or a new array. */
	solve(b, out) {
		const n = this.n;
		const lu = this.lu;
		const piv = this.piv;
		const x = out ?? new Float64Array(n);
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

/** facsimile.html's name for the same class. */
export const DenseLU = LU;

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
