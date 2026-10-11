/**
 * The iteration matrix in block upper triangular form, and an LU that keeps
 * its pivots block by block.
 *
 * Many models are groups of states that feed one another one way only: a
 * nuclide's compartments feed its daughter's, and nothing flows back up the
 * chain. Numbered group by group, in the right order, Mass - a*J is then block
 * upper triangular -- square blocks on the diagonal, nothing below them. An LU
 * of the whole matrix does not know that. Eliminating one group's columns
 * writes into every row that reads them, the coupling to the groups it feeds
 * fills in, and the record of a kept-pivot LU holds all of it. Factorised a
 * block at a time, as KLU does (Davis and Palamadai Natarajan, 2010), nothing
 * outside the diagonal blocks is ever touched: each block is factorised on its
 * own, and the solve takes the blocks from the last to the first, reading the
 * entries between them as they are. On made-up decay chains through sixty
 * cells with a back flow between neighbours (11,520 states, a block of sixty
 * per nuclide), a refactorisation's multiply-adds fell sixteen-fold and the
 * factor's entries to a quarter.
 *
 * The blocks are the strongly connected components of the matrix's graph, an
 * edge from column j to row i for every entry (i, j). Their order is the order
 * Tarjan's algorithm closes them in, which is the reverse of a topological
 * order and puts every entry in a block at or above the diagonal. The diagonal
 * is always in the pattern of Mass - a*J, so no matching is needed first: for a
 * pattern with a zero-free diagonal, these components are its finest block
 * triangular form.
 *
 * Each block of more than one state is a RefactorLU of its own (./refactor.js),
 * threshold Markowitz within the block. A block of one state is its own pivot.
 * What a block declines -- nothing left to pivot on, or a value that is not a
 * number -- the whole matrix declines, and the caller hands it to the
 * Gilbert-Peierls LU as it does a declined RefactorLU.
 *
 * Shared by facsimile.html, rtm.html and Kompartment. The source is
 * resources/js/ode/ in the site; scripts/build-solvers.mjs copies it into
 * kompartment/src/ode/ and builds resources/js/ode-core.js from it. See
 * resources/js/ode/README.md.
 */

import { RefactorLU } from './refactor.js';

/**
 * The strongly connected components of a square pattern's graph, an edge from
 * column j to row i for every entry (i, j) off the diagonal: Tarjan's
 * algorithm, without recursion, since a decay chain is a path as long as the
 * model. Returns `{nblocks, block}`, `block[i]` the component of state i,
 * numbered in the order the components close, in which every entry's row lies
 * in a block at or before its column's: block upper triangular.
 *
 * @param {{n: number, colPtr: Int32Array, rowIdx: Int32Array}} pattern
 */
export function blockTriangular(pattern) {
	const n = pattern.n;
	const colPtr = pattern.colPtr ?? pattern.colptr;
	const rowIdx = pattern.rowIdx ?? pattern.rowind;
	const index = new Int32Array(n).fill(-1);
	const low = new Int32Array(n);
	const onStack = new Uint8Array(n);
	const stack = new Int32Array(n);
	const path = new Int32Array(n);
	const next = new Int32Array(n);
	const block = new Int32Array(n);
	let counter = 0, top = 0, nblocks = 0;
	for (let s = 0; s < n; s++) {
		if (index[s] >= 0) continue;
		let depth = 0;
		path[0] = s;
		index[s] = low[s] = counter++;
		next[s] = colPtr[s];
		stack[top++] = s;
		onStack[s] = 1;
		while (depth >= 0) {
			const v = path[depth];
			if (next[v] < colPtr[v + 1]) {
				const w = rowIdx[next[v]++];
				if (w === v) continue;
				if (index[w] < 0) {
					index[w] = low[w] = counter++;
					next[w] = colPtr[w];
					stack[top++] = w;
					onStack[w] = 1;
					path[++depth] = w;
				} else if (onStack[w] && index[w] < low[v]) low[v] = index[w];
				continue;
			}
			if (low[v] === index[v]) {
				let w;
				do {
					w = stack[--top];
					onStack[w] = 0;
					block[w] = nblocks;
				} while (w !== v);
				nblocks++;
			}
			depth--;
			if (depth >= 0) {
				const u = path[depth];
				if (low[v] < low[u]) low[u] = low[v];
			}
		}
	}
	return { nblocks, block };
}

export class BlockLU {
	/**
	 * @param {{n: number, nnz: number, colPtr: Int32Array, rowIdx: Int32Array}} pattern J's pattern
	 * @param {{nblocks: number, block: Int32Array}} [blocks] `blockTriangular(pattern)`, when the caller has it
	 */
	constructor(pattern, blocks = blockTriangular(pattern)) {
		const n = pattern.n;
		const colPtr = pattern.colPtr ?? pattern.colptr;
		const rowIdx = pattern.rowIdx ?? pattern.rowind;
		const { nblocks, block } = blocks;
		this.n = n;
		this.nblocks = nblocks;
		this.columns = null;
		this.ordering = 'block triangular, threshold Markowitz';
		// The states of block b are member[start[b]] .. member[start[b + 1] - 1],
		// in their own order; local[i] is state i's place in its block.
		const start = new Int32Array(nblocks + 1);
		for (let i = 0; i < n; i++) start[block[i] + 1]++;
		for (let b = 0; b < nblocks; b++) start[b + 1] += start[b];
		const member = new Int32Array(n);
		const local = new Int32Array(n);
		const filled = Int32Array.from(start.subarray(0, nblocks));
		for (let i = 0; i < n; i++) {
			const b = block[i];
			local[i] = filled[b] - start[b];
			member[filled[b]++] = i;
		}
		this.start = start;
		this.member = member;
		// The entries between blocks, by column: their rows, and where J holds them.
		const offPtr = new Int32Array(n + 1);
		for (let j = 0; j < n; j++) {
			let c = 0;
			for (let p = colPtr[j]; p < colPtr[j + 1]; p++) if (block[rowIdx[p]] !== block[j]) c++;
			offPtr[j + 1] = offPtr[j] + c;
		}
		const noff = offPtr[n];
		const offRow = new Int32Array(noff);
		const offPos = new Int32Array(noff);
		for (let j = 0, e = 0; j < n; j++) {
			for (let p = colPtr[j]; p < colPtr[j + 1]; p++) {
				if (block[rowIdx[p]] === block[j]) continue;
				offRow[e] = rowIdx[p];
				offPos[e] = p;
				e++;
			}
		}
		this.offPtr = offPtr;
		this.offRow = offRow;
		this.offPos = offPos;
		// A block of one state: where J holds its diagonal (-1 where it has none).
		// A larger one: its pattern in its own numbering, where J holds each of
		// its entries, and its LU.
		this.diagPos = new Int32Array(nblocks).fill(-1);
		this.lus = new Array(nblocks).fill(null);
		this.pos = new Array(nblocks).fill(null);
		let most = 0, mostEntries = 0;
		for (let b = 0; b < nblocks; b++) {
			const s0 = start[b], size = start[b + 1] - s0;
			if (size === 1) {
				const i = member[s0];
				for (let p = colPtr[i]; p < colPtr[i + 1]; p++) if (rowIdx[p] === i) this.diagPos[b] = p;
				continue;
			}
			const cp = new Int32Array(size + 1);
			let count = 0;
			for (let l = 0; l < size; l++) {
				const j = member[s0 + l];
				for (let p = colPtr[j]; p < colPtr[j + 1]; p++) if (block[rowIdx[p]] === b) count++;
				cp[l + 1] = count;
			}
			const ri = new Int32Array(count);
			const pos = new Int32Array(count);
			for (let l = 0, k = 0; l < size; l++) {
				const j = member[s0 + l];
				for (let p = colPtr[j]; p < colPtr[j + 1]; p++) {
					if (block[rowIdx[p]] !== b) continue;
					ri[k] = local[rowIdx[p]];
					pos[k] = p;
					k++;
				}
			}
			this.lus[b] = new RefactorLU({ n: size, nnz: count, colPtr: cp, rowIdx: ri });
			this.pos[b] = pos;
			if (size > most) most = size;
			if (count > mostEntries) mostEntries = count;
		}
		// Scratch a block is loaded through: its values, weights and mass.
		this.bValues = new Float64Array(mostEntries);
		this.bW = new Float64Array(most);
		this.bMass = new Float64Array(most);
		// The factor as the solve walks it. Every block's steps are numbered in
		// the order the solve takes them, the last block first (`base[b]`, its
		// first step), and the steps fall into segments: one block of more than
		// one state, or a run of blocks of one state each. By step: the state it
		// pivots on, by row and by column; L, U and the pivot; and the entries
		// between blocks by the step of their column, each naming the step that
		// pivots on its row. A block of one state has its step for good; a larger
		// block's steps are laid out again when its pivots are chosen again
		// (`_layout`), and every value is written after every factorisation
		// (`_values`).
		this.base = new Int32Array(nblocks);
		this.rowOfStep = new Int32Array(n);
		this.colOfStep = new Int32Array(n);
		this.stepOfRow = new Int32Array(n);
		const segStart = [0], segBlock = [];
		for (let b = nblocks - 1, g = 0; b >= 0; b--) {
			const size = start[b + 1] - start[b];
			this.base[b] = g;
			if (size === 1) {
				const i = member[start[b]];
				this.rowOfStep[g] = this.colOfStep[g] = i;
				this.stepOfRow[i] = g;
				if (segBlock.length && segBlock[segBlock.length - 1] < 0) segStart[segStart.length - 1] = g + 1;
				else { segBlock.push(-1); segStart.push(g + 1); }
			} else {
				segBlock.push(b);
				segStart.push(g + size);
			}
			g += size;
		}
		this.segStart = Int32Array.from(segStart);
		this.segBlock = Int32Array.from(segBlock);
		this.Lp = new Int32Array(n + 1);
		this.Up = new Int32Array(n + 1);
		this.Li = new Int32Array(0);
		this.Lx = new Float64Array(0);
		this.Ui = new Int32Array(0);
		this.Ux = new Float64Array(0);
		this.D = new Float64Array(n);
		this.offP = new Int32Array(n + 1);
		this.offStep = new Int32Array(noff);
		this.offAt = new Int32Array(noff);		// where J holds it
		this.offRowOf = new Int32Array(noff);	// its row and column, for the weights
		this.offColOf = new Int32Array(noff);
		this.offX = new Float64Array(noff);
		this.zs = new Float64Array(n);
		this.laidOut = -1;		// the blocks' choices the layout was made for (`repivots`)
		this.valid = false;
		this.ops = 0;			// multiply-adds per factorisation, over the blocks
		this.limit = Infinity;	// a trial stops once its work passes this
		this.nnz = 0;
	}

	/** Times a block's pivots were chosen again, over every block. */
	get repivots() {
		let r = 0;
		for (const lu of this.lus) if (lu) r += lu.repivots;
		return r;
	}

	/**
	 * Factorises Mass - a*J -- I - a*J without a mass, and in the variables
	 * y_i / w_i where `w` is given, as RefactorLU's `factor` does; false when a
	 * block cannot be done with pivots that pass the test, or a value is not a
	 * number.
	 */
	factor(a, values, w = null, mass = null) {
		const { nblocks, start, member, base, D, bValues, bW, bMass } = this;
		this.valid = false;
		let ops = 0, nnz = this.offX.length;
		for (let b = 0; b < nblocks; b++) {
			const s0 = start[b];
			const lu = this.lus[b];
			if (!lu) {
				const i = member[s0];
				const p = this.diagPos[b];
				const d = (p >= 0 ? -a * values[p] : 0) + (mass ? mass[i] : 1);
				if (!(Math.abs(d) > 0) || !Number.isFinite(d)) return false;
				D[base[b]] = d;
				nnz++;
				continue;
			}
			const size = start[b + 1] - s0;
			const pos = this.pos[b];
			for (let k = 0; k < pos.length; k++) bValues[k] = values[pos[k]];
			if (w) for (let l = 0; l < size; l++) bW[l] = w[member[s0 + l]];
			if (mass) for (let l = 0; l < size; l++) bMass[l] = mass[member[s0 + l]];
			lu.limit = this.limit === Infinity ? Infinity : this.limit - ops;
			const ok = lu.factor(a, bValues, w ? bW : null, mass ? bMass : null);
			lu.limit = Infinity;
			if (!ok) return false;
			ops += lu.ops;
			nnz += lu.nnz;
			if (ops > this.limit) return false;
		}
		this.ops = ops;
		this.nnz = nnz;
		const chosen = this.repivots;
		if (chosen !== this.laidOut) {
			this._layout();
			this.laidOut = chosen;
		}
		if (!this._values(a, values, w)) return false;
		this.valid = true;
		return true;
	}

	/**
	 * The larger blocks' steps, L's and U's entries by step, and the entries
	 * between blocks by the steps of their column and their row. Made again
	 * whenever a block's pivots have been chosen again.
	 */
	_layout() {
		const { n, nblocks, start, member, base, rowOfStep, colOfStep, stepOfRow, Lp, Up } = this;
		let nl = 0, nu = 0;
		for (const lu of this.lus) {
			if (!lu) continue;
			nl += lu.Lstart[lu.n];
			nu += lu.Ustart[lu.n];
		}
		if (this.Li.length < nl) {
			this.Li = new Int32Array(nl);
			this.Lx = new Float64Array(nl);
		}
		if (this.Ui.length < nu) {
			this.Ui = new Int32Array(nu);
			this.Ux = new Float64Array(nu);
		}
		const { Li, Ui } = this;
		let lq = 0, uq = 0;
		for (let k = nblocks - 1; k >= 0; k--) {
			const s0 = start[k], m = start[k + 1] - s0, g0 = base[k];
			const lu = this.lus[k];
			if (!lu) {
				Lp[g0] = lq;
				Up[g0] = uq;
				continue;
			}
			const { pr, pc, Lstart, Lstep, Ustart, Ustep } = lu;
			for (let s = 0; s < m; s++) {
				const i = member[s0 + pr[s]];
				rowOfStep[g0 + s] = i;
				colOfStep[g0 + s] = member[s0 + pc[s]];
				stepOfRow[i] = g0 + s;
				Lp[g0 + s] = lq;
				for (let q = Lstart[s]; q < Lstart[s + 1]; q++) Li[lq++] = g0 + Lstep[q];
				Up[g0 + s] = uq;
				for (let u = Ustart[s]; u < Ustart[s + 1]; u++) Ui[uq++] = g0 + Ustep[u];
			}
		}
		Lp[n] = lq;
		Up[n] = uq;
		const { offPtr, offRow, offPos, offP, offStep, offAt, offRowOf, offColOf } = this;
		let e = 0;
		for (let g = 0; g < n; g++) {
			offP[g] = e;
			const j = colOfStep[g];
			for (let f = offPtr[j]; f < offPtr[j + 1]; f++) {
				offStep[e] = stepOfRow[offRow[f]];
				offAt[e] = offPos[f];
				offRowOf[e] = offRow[f];
				offColOf[e] = j;
				e++;
			}
		}
		offP[n] = e;
	}

	/**
	 * The factor's values in that layout, after every factorisation: the larger
	 * blocks' L, U and pivots, and the entries between blocks worked out from J
	 * where they are laid out; false where one is not a number.
	 */
	_values(a, values, w) {
		const { nblocks, start, base, Lx, Ux, D, offX, offAt, offRowOf, offColOf } = this;
		let lq = 0, uq = 0;
		for (let k = nblocks - 1; k >= 0; k--) {
			const lu = this.lus[k];
			if (!lu) continue;
			const m = start[k + 1] - start[k], g0 = base[k];
			const { Lval, Uval, Dval } = lu;
			const nl = lu.Lstart[m], nu = lu.Ustart[m];
			for (let q = 0; q < nl; q++) Lx[lq++] = Lval[q];
			for (let u = 0; u < nu; u++) Ux[uq++] = Uval[u];
			for (let s = 0; s < m; s++) D[g0 + s] = Dval[s];
		}
		for (let e = 0; e < offX.length; e++) {
			const v = -a * values[offAt[e]] * (w ? w[offColOf[e]] / w[offRowOf[e]] : 1);
			if (!Number.isFinite(v)) return false;
			offX[e] = v;
		}
		return true;
	}

	/**
	 * Solves against the latest factorisation, the blocks from the last to the
	 * first: each block's unknowns from its own factor, as RefactorLU's `solve`
	 * works them out, each one's column of entries between blocks taken off
	 * the right-hand side of the steps that pivot on their rows as soon as it
	 * is known. One pass over the factor in the order it is laid out, a run of
	 * blocks of one state each in one loop. Returns a new Float64Array unless
	 * `out` is given.
	 *
	 * A block's backward pass is a chain, each unknown waiting on the one
	 * before; its entries between blocks reach only blocks still to come, and
	 * taken in that pass they are worked off while the chain waits. In passes
	 * of their own, they and the copy into the answer took a fifth of a solve's
	 * time on the far-field example.
	 */
	solve(b, out) {
		const { n, rowOfStep, colOfStep, Lp, Li, Lx, Up, Ui, Ux, D, offP, offStep, offX, zs, segStart, segBlock } = this;
		for (let g = 0; g < n; g++) zs[g] = b[rowOfStep[g]];
		const x = out ?? new Float64Array(n);
		for (let r = 0; r < segBlock.length; r++) {
			const g0 = segStart[r], g1 = segStart[r + 1];
			if (segBlock[r] < 0) {
				for (let g = g0; g < g1; g++) {
					const xg = zs[g] / D[g];
					zs[g] = xg;
					x[colOfStep[g]] = xg;
					if (xg === 0) continue;
					for (let e = offP[g], end = offP[g + 1]; e < end; e++) zs[offStep[e]] -= offX[e] * xg;
				}
				continue;
			}
			for (let g = g0; g < g1; g++) {
				const zg = zs[g];
				if (zg === 0) continue;
				for (let q = Lp[g], end = Lp[g + 1]; q < end; q++) zs[Li[q]] -= Lx[q] * zg;
			}
			for (let g = g1 - 1; g >= g0; g--) {
				let t = zs[g];
				for (let u = Up[g], end = Up[g + 1]; u < end; u++) t -= Ux[u] * zs[Ui[u]];
				const xg = t / D[g];
				zs[g] = xg;
				x[colOfStep[g]] = xg;
				if (xg === 0) continue;
				for (let e = offP[g], end = offP[g + 1]; e < end; e++) zs[offStep[e]] -= offX[e] * xg;
			}
		}
		return x;
	}
}
