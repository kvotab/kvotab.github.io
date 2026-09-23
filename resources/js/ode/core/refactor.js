/**
 * A sparse LU of Mass - a*J that keeps its pivots from one factorisation to
 * the next -- I - h*J for an ordinary system without scaling.
 *
 * A stiff run factorises the iteration matrix hundreds or thousands of times.
 * Its pattern never changes and its values change slowly, yet the
 * Gilbert-Peierls LU in ./sparse.js redoes everything each time: the depth-
 * first reach of every column, and the search for every pivot. On a
 * 16,244-state assessment model that was a third of the run.
 *
 * So the pivots are chosen once from the values, and every elimination is
 * recorded. Each later matrix is factorised by replaying the record over the
 * same structure, with nothing searched and nothing reached.
 *
 * CHOOSING. By threshold Markowitz: at each step, the entry with the least
 * (row count - 1) x (column count - 1), among those at least PIVOT_THRESHOLD
 * times the largest in their column. The search looks at the SEARCH_COLUMNS
 * sparsest columns that have a candidate, which is Zlatev's restricted
 * search. Alternatively the column order is fixed and only each pivot's row is
 * chosen, by the same test, preferring short rows. The caller tries both and
 * keeps the cheaper: Markowitz wins where a bandwidth order fills in, and a
 * fixed order wins where the matrix is banded blocks that order keeps
 * together.
 *
 * CHECKING. Every step of a replay is checked. The pivot must be nonzero and
 * finite, and no entry below it may exceed it by more than 1/KEEP_THRESHOLD,
 * which bounds how much any entry can grow in that step. The choice is made at
 * 0.1 (UMFPACK's and MA48's default) and the pivots are kept while 0.01 holds
 * (MA57's default). A pivot chosen at the stricter test can drift a long way
 * before it fails the looser one. A step that fails is chosen again from the
 * matrix as it stands, and so is every step after it; the steps before passed
 * and are kept. Choosing from the middle keeps pivots chosen for an earlier
 * matrix, and the order can drift, so past REORDER_GROWTH times the work of
 * the last choice made from the start, it is made from the start again.
 *
 * DECLINING. What cannot be factored this way, because nothing is left to
 * pivot on or a value is not finite, is declined. The caller hands it to the
 * Gilbert-Peierls LU, which either factors it or reports it singular exactly
 * as before. Nothing is ever solved with a pivot that failed the test.
 *
 * STORAGE is by slot. Every entry of the matrix and of its fill has a place in
 * one array V, and the slots are numbered in the order they are made: the
 * pattern first, then each step's fill. A step chosen again therefore discards
 * exactly the slots made after it, and memory is the size of the factor, not
 * n x n. The record holds one index per multiply-add, which is why the caller
 * keeps it under OPS_BUDGET.
 *
 * One class for the three pages that use it: the canister and
 * reactive-transport pages load and scale it with a mass diagonal and the
 * Newton weights, Kompartment as the plain I - h*J. The measurements behind
 * the constants are recorded in Kompartment's INTERNALS.md.
 *
 * Shared by facsimile.html, rtm.html and Kompartment. The source is
 * resources/js/ode/ in the site; scripts/build-solvers.mjs copies it into
 * kompartment/src/ode/ and builds resources/js/ode-core.js from it. See
 * resources/js/ode/README.md.
 */

export const PIVOT_THRESHOLD = 0.1;
export const KEEP_THRESHOLD = 0.01;
const SEARCH_COLUMNS = 16;
const REORDER_GROWTH = 1.2;

/**
 * The record holds one index per multiply-add. Past this many it is 16 MB,
 * and the Gilbert-Peierls LU, which stores only the factor, is left the job.
 */
export const OPS_BUDGET = 4e6;

/** A growable typed array: `a`, or a copy of it with room for `need`. */
function room(a, need) {
	if (need <= a.length) return a;
	let cap = Math.max(a.length, 64);
	while (cap < need) cap *= 2;
	const b = new a.constructor(cap);
	b.set(a);
	return b;
}

export class RefactorLU {
	/**
	 * @param {{n: number, nnz: number, colPtr: Int32Array, rowIdx: Int32Array}} pattern J's pattern
	 * @param {Int32Array|null} [columns] a fixed column order, or null to choose
	 *   columns by threshold Markowitz as well
	 */
	constructor(pattern, columns = null) {
		const n = pattern.n;
		this.n = n;
		this.columns = columns;
		// The pattern's slots, and the diagonal's where the pattern has none.
		this.slotRow = new Int32Array(pattern.nnz + n);
		this.slotCol = new Int32Array(pattern.nnz + n);
		this.jSlot = new Int32Array(pattern.nnz);
		this.dSlot = new Int32Array(n);
		const mark = new Int32Array(n).fill(-1);
		let ns = 0;
		for (let j = 0; j < n; j++) {
			for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) {
				const i = pattern.rowIdx[p];
				this.slotRow[ns] = i;
				this.slotCol[ns] = j;
				this.jSlot[p] = ns;
				mark[i] = ns;
				ns++;
			}
			if (mark[j] >= 0) this.dSlot[j] = mark[j];
			else {
				this.slotRow[ns] = j;
				this.slotCol[ns] = j;
				this.dSlot[j] = ns;
				ns++;
			}
			for (let p = pattern.colPtr[j]; p < pattern.colPtr[j + 1]; p++) mark[pattern.rowIdx[p]] = -1;
		}
		this.nbase = ns;
		this.nslots = ns;
		this.V = new Float64Array(ns);
		// The record: step s pivots on slot pslot[s] at (pr[s], pc[s]); its
		// column below is the L entries Lstart[s].., its row to the right the
		// U entries Ustart[s].., and its |L| x |U| updates write the slots
		// T[Tstart[s]..]. fillStart[s] is the slot count before step s made fill.
		this.pr = new Int32Array(n);
		this.pc = new Int32Array(n);
		this.pslot = new Int32Array(n);
		this.Lstart = new Int32Array(n + 1);
		this.Ustart = new Int32Array(n + 1);
		this.Tstart = new Int32Array(n + 1);
		this.fillStart = new Int32Array(n + 1);
		this.Lslot = new Int32Array(64);
		this.Lrow = new Int32Array(64);
		this.Uslot = new Int32Array(64);
		this.Ucol = new Int32Array(64);
		this.T = new Int32Array(64);
		this.valid = false;
		this.ops = 0;			// multiply-adds per factorisation
		this.nnz = 0;			// entries of L + U
		this.repivots = 0;		// times the pivots were chosen again
		this.fullOps = 0;		// ops of the last choice made from the start
		this.limit = Infinity;	// a trial stops once its work passes this
		// Scratch for choosing.
		this.rowSlots = Array.from({ length: n }, () => []);
		this.colSlots = Array.from({ length: n }, () => []);
		this.rowActive = new Uint8Array(n);
		this.colActive = new Uint8Array(n);
		this.rc = new Int32Array(n);
		this.cc = new Int32Array(n);
		this.head = new Int32Array(n + 2);
		this.next = new Int32Array(n);
		this.prev = new Int32Array(n);
		this.at = new Int32Array(n);
		this.atStamp = new Int32Array(n);
		this.stamp = 0;
	}

	/** Mass - a*J into V, in the variables y_i / w_i where `w` is given; false if a value is not finite. */
	load(a, values, w, mass) {
		const { n, V, jSlot, dSlot, slotRow, slotCol } = this;
		V.fill(0, 0, this.nslots);
		let finite = true;
		for (let p = 0; p < jSlot.length; p++) {
			const s = jSlot[p];
			// Mass - a*J, in the scaled variables y_i / w_i where `w` is given
			// (facsimile.html's and rtm.html's Newton scaling): a*J_ij*w_j/w_i.
			// Without it the factor is 1, which multiplies exactly.
			const v = -a * values[p] * (w ? w[slotCol[s]] / w[slotRow[s]] : 1);
			if (!Number.isFinite(v)) finite = false;
			V[s] = v;
		}
		for (let i = 0; i < n; i++) V[dSlot[i]] += mass ? mass[i] : 1;
		return finite;
	}

	/**
	 * Factorises Mass - a*J -- I - a*J without a mass, and in the variables
	 * y_i / w_i where `w` is given; false when it cannot be done with pivots
	 * that pass the test.
	 */
	factor(a, values, w = null, mass = null) {
		if (!this.valid) this.nslots = this.nbase;
		if (!this.load(a, values, w, mass)) {
			this.valid = false;
			return false;
		}
		let from = 0;
		if (this.valid) {
			from = this.refactor();
			if (from < 0) return true;
		}
		this.repivots++;
		if (!this.choose(from)) {
			this.valid = false;
			return false;
		}
		if (from === 0) this.fullOps = this.ops;
		else if (this.ops > REORDER_GROWTH * this.fullOps) {
			this.load(a, values, w, mass);
			if (!this.choose(0)) {
				this.valid = false;
				return false;
			}
			this.fullOps = this.ops;
		}
		this.valid = true;
		return true;
	}

	/** Replays the record on V; -1, or the first step whose pivot fails. */
	refactor() {
		const { n, V, pslot, Lstart, Ustart, Tstart, Lslot, Uslot, T } = this;
		const bound = 1 / KEEP_THRESHOLD;
		for (let s = 0; s < n; s++) {
			const piv = V[pslot[s]];
			const ap = Math.abs(piv);
			if (!(ap > 0) || ap === Infinity) return s;
			const lim = bound * ap;
			const l0 = Lstart[s], l1 = Lstart[s + 1];
			for (let k = l0; k < l1; k++) if (!(Math.abs(V[Lslot[k]]) <= lim)) return s;
			const u0 = Ustart[s], u1 = Ustart[s + 1];
			let t = Tstart[s];
			for (let k = l0; k < l1; k++) {
				const ls = Lslot[k];
				const f = V[ls] / piv;
				V[ls] = f;
				if (f === 0) {
					t += u1 - u0;
					continue;
				}
				for (let u = u0; u < u1; u++) V[T[t++]] -= f * V[Uslot[u]];
			}
		}
		return -1;
	}

	_bucketOut(j) {
		const { head, next, prev, cc } = this;
		if (prev[j] >= 0) next[prev[j]] = next[j];
		else head[cc[j]] = next[j];
		if (next[j] >= 0) prev[next[j]] = prev[j];
	}

	_bucketIn(j) {
		const { head, next, prev, cc } = this;
		const c = cc[j];
		prev[j] = -1;
		next[j] = head[c];
		if (head[c] >= 0) prev[head[c]] = j;
		head[c] = j;
	}

	/** A fill slot at (i, j). The caller has made room, and has column j out of its bucket. */
	_newSlot(i, j) {
		const s = this.nslots++;
		this.V[s] = 0;
		this.slotRow[s] = i;
		this.slotCol[s] = j;
		this.rowSlots[i].push(s);
		this.colSlots[j].push(s);
		this.rc[i]++;
		this.cc[j]++;
		return s;
	}

	/**
	 * Chooses the pivots of steps s0.. from V as the kept steps before s0 left
	 * it, and eliminates as it goes. False when no acceptable pivot remains, a
	 * value is not finite, or the work passes `limit`.
	 */
	choose(s0) {
		const { n, pr, pc, pslot, Lstart, Ustart, Tstart, fillStart } = this;
		const { rowSlots, colSlots, rowActive, colActive, rc, cc, head, at, atStamp } = this;
		// Keep the pattern and the fill of the kept steps; the rest goes.
		this.nslots = s0 > 0 ? fillStart[s0] : this.nbase;
		rowActive.fill(1);
		colActive.fill(1);
		for (let s = 0; s < s0; s++) {
			rowActive[pr[s]] = 0;
			colActive[pc[s]] = 0;
		}
		for (let i = 0; i < n; i++) {
			rowSlots[i].length = 0;
			colSlots[i].length = 0;
		}
		rc.fill(0);
		cc.fill(0);
		for (let s = 0; s < this.nslots; s++) {
			const i = this.slotRow[s], j = this.slotCol[s];
			if (!rowActive[i] || !colActive[j]) continue;
			rowSlots[i].push(s);
			colSlots[j].push(s);
			rc[i]++;
			cc[j]++;
		}
		head.fill(-1);
		for (let j = 0; j < n; j++) if (colActive[j]) this._bucketIn(j);
		atStamp.fill(0);
		this.stamp = 0;
		let lp = Lstart[s0], up = Ustart[s0], tp = Tstart[s0];
		for (let s = s0; s < n; s++) {
			if (head[0] >= 0) return false;		// a column with nothing left in it
			const V = this.V, slotRow = this.slotRow;
			// The search: the SEARCH_COLUMNS sparsest columns with a candidate,
			// or the one column the fixed order names.
			let best = Infinity, bestRatio = 0, bslot = -1, examined = 0;
			const fixed = this.columns ? this.columns[s] : -1;
			for (let c = 1, cmax = fixed >= 0 ? 1 : n - s; c <= cmax && examined < SEARCH_COLUMNS && best > 0; c++) {
				for (let j = fixed >= 0 ? fixed : head[c]; j >= 0 && examined < SEARCH_COLUMNS && best > 0; j = fixed >= 0 ? -1 : this.next[j]) {
					// Scanned once for the largest, dropping the rows eliminated
					// since, so that no list is walked past what is left in it.
					const list = colSlots[j];
					let m = 0, keep = 0;
					for (let k = 0; k < list.length; k++) {
						const sl = list[k];
						if (!rowActive[slotRow[sl]]) continue;
						list[keep++] = sl;
						const v = Math.abs(V[sl]);
						if (!(v < Infinity)) return false;		// NaN or infinite
						if (v > m) m = v;
					}
					list.length = keep;
					if (!(m > 0)) continue;
					examined++;
					const thr = PIVOT_THRESHOLD * m, cj = fixed >= 0 ? 1 : c - 1;
					for (let k = 0; k < list.length; k++) {
						const sl = list[k];
						const v = Math.abs(V[sl]);
						if (v < thr) continue;
						const cost = (rc[slotRow[sl]] - 1) * cj, ratio = v / m;
						if (cost < best || (cost === best && ratio > bestRatio)) {
							best = cost;
							bestRatio = ratio;
							bslot = sl;
						}
					}
				}
			}
			if (bslot < 0) return false;
			const p = slotRow[bslot], q = this.slotCol[bslot];
			pr[s] = p;
			pc[s] = q;
			pslot[s] = bslot;
			fillStart[s] = this.nslots;
			rowActive[p] = 0;
			colActive[q] = 0;
			this._bucketOut(q);
			// Its column below and its row to the right, among what is active.
			const Lcol = colSlots[q], Urow = rowSlots[p];
			this.Lslot = room(this.Lslot, lp + Lcol.length);
			this.Lrow = room(this.Lrow, lp + Lcol.length);
			this.Uslot = room(this.Uslot, up + Urow.length);
			this.Ucol = room(this.Ucol, up + Urow.length);
			const { Lslot, Lrow, Uslot, Ucol } = this;
			Lstart[s] = lp;
			Ustart[s] = up;
			Tstart[s] = tp;
			for (let k = 0; k < Lcol.length; k++) {
				const sl = Lcol[k], i = slotRow[sl];
				if (rowActive[i]) { Lslot[lp] = sl; Lrow[lp] = i; lp++; }
			}
			for (let k = 0; k < Urow.length; k++) {
				const sl = Urow[k], j = this.slotCol[sl];
				if (colActive[j]) { Uslot[up] = sl; Ucol[up] = j; up++; }
			}
			const l0 = Lstart[s], u0 = Ustart[s];
			const most = (lp - l0) * (up - u0);
			this.T = room(this.T, tp + most);
			this.V = room(this.V, this.nslots + most);
			this.slotRow = room(this.slotRow, this.nslots + most);
			this.slotCol = room(this.slotCol, this.nslots + most);
			for (let u = u0; u < up; u++) this._bucketOut(Ucol[u]);
			const piv = this.V[bslot];
			for (let k = l0; k < lp; k++) {
				const i = Lrow[k];
				const f = this.V[Lslot[k]] / piv;
				this.V[Lslot[k]] = f;
				// Where row i already has an entry, by column.
				const stamp = ++this.stamp;
				const row = rowSlots[i];
				let keep = 0;
				for (let r = 0; r < row.length; r++) {
					const sl = row[r], j = this.slotCol[sl];
					if (!colActive[j]) continue;
					row[keep++] = sl;
					at[j] = sl;
					atStamp[j] = stamp;
				}
				row.length = keep;
				for (let u = u0; u < up; u++) {
					const j = Ucol[u];
					// Fill is structure whatever its value now: a later matrix
					// may put a number there.
					const t = atStamp[j] === stamp ? at[j] : this._newSlot(i, j);
					this.T[tp++] = t;
					if (f !== 0) this.V[t] -= f * this.V[Uslot[u]];
				}
			}
			for (let k = l0; k < lp; k++) rc[Lrow[k]]--;
			for (let u = u0; u < up; u++) {
				const j = Ucol[u];
				cc[j]--;
				this._bucketIn(j);
			}
			if (tp > this.limit) return false;
		}
		Lstart[n] = lp;
		Ustart[n] = up;
		Tstart[n] = tp;
		fillStart[n] = this.nslots;
		this.ops = tp;
		this.nnz = this.nslots;
		return true;
	}

	/** Solves against the latest factorisation. Returns a new Float64Array unless `out` is given. */
	solve(b, out) {
		const { n, V, pr, pc, pslot, Lstart, Ustart, Lslot, Lrow, Uslot, Ucol } = this;
		const y = this._y ?? (this._y = new Float64Array(n));
		y.set(b);						// indexed by row
		for (let s = 0; s < n; s++) {
			const yr = y[pr[s]];
			if (yr === 0) continue;
			for (let k = Lstart[s]; k < Lstart[s + 1]; k++) y[Lrow[k]] -= V[Lslot[k]] * yr;
		}
		const x = out ?? new Float64Array(n);	// indexed by column
		for (let s = n - 1; s >= 0; s--) {
			let t = y[pr[s]];
			for (let u = Ustart[s]; u < Ustart[s + 1]; u++) t -= V[Uslot[u]] * x[Ucol[u]];
			x[pc[s]] = t / V[pslot[s]];
		}
		return x;
	}
}
