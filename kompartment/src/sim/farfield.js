/**
 * The runtime side of a FARFCOMP block: one `FarfPath` per block, holding the
 * transport matrix over its own cells and applying it to the state vector.
 *
 * WHY A RUNTIME OBJECT rather than generated code, which is how every other
 * block in this tool works. A path of 20 fracture cells by 20 matrix layers
 * has 420 cells per nuclide and about 1,250 non-zero rates; a model with ten
 * nuclides would emit 12,500 lines for one block, and the same again for the
 * Jacobian's pattern and its tangent. The structure is identical for every
 * nuclide and every index of the block, so it is built once as index arrays
 * and walked in a flat loop instead. See ../domain/farfield.js for the
 * arithmetic itself.
 *
 * The state is laid out nuclide-innermost --
 *
 *     base + other*(cells*nuclides) + cell*nuclides + m
 *
 * -- so the decay chain, which couples nuclides within one cell and nothing
 * else, is a stride-1 walk, and the transport, which couples cells within one
 * nuclide, strides by the nuclide count.
 */

import {
	cellStructure, cellValues, coefficients, coefficientsTangent,
	releaseCells, releaseWeights, FARF_EQUATION_KEYS,
	effectiveStructure, matchedGrid, wettedSurface,
} from '../domain/farfield.js';

export class FarfPath {
	/**
	 * @param {object} spec
	 * @param {{n_f:number,n_m:number,o_b:number,n_b:number}} spec.structure
	 *   the cells as the grid has them (see `effectiveStructure`)
	 * @param {number} spec.base first state index of the block
	 * @param {number} spec.nnuc how many nuclides the block is indexed over
	 * @param {number} spec.otherWidth combinations of its other dimensions
	 * @param {Int32Array} spec.dimOff for each (other, nuclide), the offset
	 *   within the block's own dimensions -- which is what every algebraic
	 *   slot of the block is addressed by
	 * @param {Int32Array} spec.singleOff for each combination of the other
	 *   dimensions, the offset among *those* -- where a setting that is one
	 *   value per path rather than one per nuclide is read
	 * @param {object} spec.settingBase algebraic base per setting key
	 * @param {string[]} [spec.keys] the settings the path is worked out from,
	 *   in slot order: every equation but the ways of giving the wetted
	 *   surface it does not use
	 * @param {string[]} spec.single which settings hold one value for the whole
	 *   path rather than one per nuclide -- read at their own slot, not at the
	 *   nuclide's
	 * @param {string} [spec.grid] 'matched' or 'reference': how the matrix
	 *   layers are laid out
	 * @param {string} [spec.surface] how the wetted surface is given
	 * @param {number} spec.releaseBase algebraic base of the block's own value
	 */
	constructor(spec) {
		Object.assign(this, spec);
		this.structure = effectiveStructure(spec.structure);
		this.isSingle = new Set(spec.single ?? []);
		const g = this.structure;
		this.ncells = (g.n_f + g.n_b) * (g.n_m + 1);
		const { rows, cols, nnz } = cellStructure(g);
		this.rows = rows;
		this.cols = cols;
		this.nnz = nnz;
		this.relCells = Int32Array.from(releaseCells(g));
		this.nrel = this.relCells.length;
		this.grid = spec.grid === 'matched' ? 'matched' : 'reference';
		this.surface = spec.surface ?? 'f';

		const slots = this.otherWidth * this.nnuc;
		this.slots = slots;
		this.vals = new Float64Array(slots * nnz);
		this.relW = new Float64Array(slots * this.nrel);
		// The settings as they were when the rates were last worked out. A
		// path whose parameters are constants -- which is the ordinary case --
		// then costs one root-find for the whole run rather than one per
		// derivative call.
		this.keys = spec.keys ?? FARF_EQUATION_KEYS;
		this.seen = new Float64Array(slots * this.keys.length).fill(NaN);
		// One slot's settings, read out before they are committed to `seen`.
		this.probe = new Float64Array(this.keys.length);
		this.dvals = null;
		this.drelW = null;
		this.setting = {};
		this.dsetting = {};
		// Each nuclide's decay constant, for the matched layers: a nuclide
		// that decays fast has a thin profile to resolve. Zero until the
		// builder hands the decay table over, and zero for a path that does
		// not decay.
		this.lam = new Float64Array(this.nnuc);
		// The matched layers of each combination of the other dimensions, and
		// whether they have been laid out for this run.
		this.layers = new Array(this.otherWidth).fill(null);
		this.laidOut = new Uint8Array(this.otherWidth);
	}

	/** The decay constants the path's nuclides decay with, or null for none. */
	setDecay(lam) {
		this.lam.fill(0);
		if (lam) for (let m = 0; m < this.nnuc; m++) this.lam[m] = lam[m] ?? 0;
		this.restart();
	}

	/**
	 * Starts a run: the matched layers are laid out again, from the settings
	 * as they are at its first instant, and held for the whole of it.
	 *
	 * Held, because the layers are where the matrix's inventory is: a layout
	 * that moved with a travel time following a table would carry what one
	 * layer holds into another layer's geometry, which is no physics at all.
	 * Laid out again, because a realisation that draws another diffusivity is
	 * another path. The reference layers are not held -- they follow their
	 * settings, as they always did.
	 */
	restart() {
		this.laidOut.fill(0);
		this.seen.fill(NaN);
	}

	/**
	 * Where one setting of one slot lives among the algebraic values.
	 *
	 * A setting that is not per nuclide is still per everything else the
	 * block is indexed by: read at this combination among those, not at the
	 * first slot of the block. With no other dimensions the two are the same
	 * slot, which is why this read zero for as long as a path could only be
	 * the nuclides -- and why, once a path could be more, the five places
	 * that each worked the address out for themselves did not all agree:
	 * `refresh` kept reading a single-valued setting at offset 0, so a second
	 * path's own travel time changing was not a change it could see, and its
	 * rates stayed as they were. One computation now, so there is one thing
	 * to be right.
	 *
	 * @param {string} key the setting
	 * @param {number} o which combination of the other dimensions
	 * @param {number} off `dimOff` of the (combination, nuclide) slot
	 */
	_at(key, o, off) {
		const one = this.singleOff ? this.singleOff[o] : 0;
		return this.settingBase[key] + (this.isSingle.has(key) ? one : off);
	}

	/** The settings for one slot, read out of the algebraic values. */
	_read(X, o, m, into) {
		const off = this.dimOff[o * this.nnuc + m];
		for (const key of this.keys) into[key] = X[this._at(key, o, off)];
		into.nf = this.structure.n_f;
		into.nm = this.structure.n_m;
		into.surface = this.surface;
		into.grid = this.grid;
		into.lam = this.lam[m];
		// An empty first-layer thickness is written as a zero by the equation
		// machinery -- there is no way to write "nothing" in an equation -- and
		// zero is the same request: work it out.
		if (!(into.pen_dep_0 > 0)) into.pen_dep_0 = null;
		return into;
	}

	/**
	 * Lays out the matched layers of one combination, from every nuclide on
	 * it: they share the cells, since a daughter grows in cell by cell.
	 */
	_layOut(X, o) {
		const s = this._read(X, o, 0, {});
		const aw = wettedSurface(s);
		const nucs = new Array(this.nnuc);
		for (let m = 0; m < this.nnuc; m++) {
			const n = this._read(X, o, m, {});
			nucs[m] = {
				de: n.de_m, rm: n.eps_m + n.rho_m * n.kd_m, lam: this.lam[m], rf: 1 + n.kd_f * aw,
			};
		}
		return matchedGrid({
			penDep: s.pen_dep, nm: s.nm, first: s.pen_dep_0, aw, tw: s.tw, pe: s.pe, nucs,
		});
	}

	/** Recomputes the rates for every slot whose settings have moved. */
	refresh(X) {
		const { keys, nnuc, otherWidth } = this;
		const s = this.setting;
		const probe = this.probe;
		const matched = this.grid === 'matched';
		for (let o = 0; o < otherWidth; o++) {
			// A combination laid out afresh has every rate worked out again
			// over its new layers, whether or not a setting moved.
			const fresh = matched && !this.laidOut[o];
			if (fresh) this.layers[o] = this._layOut(X, o);
			try {
				for (let m = 0; m < nnuc; m++) {
					const slot = o * nnuc + m;
					const off = this.dimOff[slot];
					let changed = fresh;
					for (let k = 0; k < keys.length; k++) {
						probe[k] = X[this._at(keys[k], o, off)];
						if (this.seen[slot * keys.length + k] !== probe[k]) changed = true;
					}
					if (!changed) continue;
					this._read(X, o, m, s);
					const c = coefficients(s, matched ? this.layers[o] : null);
					cellValues(this.structure, c, this.vals.subarray(slot * this.nnz, (slot + 1) * this.nnz));
					releaseWeights(this.structure, c, this.relW.subarray(slot * this.nrel, (slot + 1) * this.nrel));
					// Marked seen only now. Recording the settings before working
					// them out meant that a slot whose settings cannot mean
					// anything -- F/TW zero, a Peclet number of zero -- raised its
					// refusal exactly once: whoever called first got the error,
					// and every call after it found the slot up to date and went
					// on using whatever was left in `vals`, which is zeros. A
					// caller that swallows the first failure would then get a
					// silent answer to a question the model cannot answer.
					for (let k = 0; k < keys.length; k++) {
						this.seen[slot * keys.length + k] = probe[k];
					}
				}
			} catch (e) {
				// Layers laid out from settings that cannot be used are not a
				// layout to hold for the run.
				if (fresh) this.laidOut[o] = 0;
				throw e;
			}
			if (fresh) this.laidOut[o] = 1;
		}
	}

	/** The release out of the path, into the block's own algebraic slot. */
	release(y, X) {
		this.refresh(X);
		const { nnuc, otherWidth, ncells, nrel, relCells, relW, base } = this;
		for (let o = 0; o < otherWidth; o++) {
			const obase = base + o * ncells * nnuc;
			for (let m = 0; m < nnuc; m++) {
				const slot = o * nnuc + m;
				let q = 0;
				for (let r = 0; r < nrel; r++) {
					q += relW[slot * nrel + r] * y[obase + relCells[r] * nnuc + m];
				}
				X[this.releaseBase + this.dimOff[slot]] = q;
			}
		}
	}

	/** Transport and decay, added into the derivative. */
	apply(y, out, X, D) {
		this.refresh(X);
		const {
			nnuc, otherWidth, ncells, nnz, rows, cols, vals, base,
		} = this;
		for (let o = 0; o < otherWidth; o++) {
			const obase = base + o * ncells * nnuc;
			// Transport: one nuclide's cells at a time, since that is what the
			// matrix couples.
			for (let m = 0; m < nnuc; m++) {
				const v = (o * nnuc + m) * nnz;
				for (let e = 0; e < nnz; e++) {
					out[obase + rows[e] * nnuc + m] += vals[v + e] * y[obase + cols[e] * nnuc + m];
				}
			}
			// Decay and ingrowth: within one cell, over the nuclides, exactly
			// as a compartment does it. Every cell of the path holds an
			// inventory and every one of them decays -- unless the block says
			// not to, which is the same switch a compartment has and is there
			// for the same reason: to compare against something that does not.
			// A cell's inventory is what is dissolved in its water and what is
			// sorbed on its surfaces together, so the sorbed part decays too,
			// and a daughter born of it takes up its own equilibrium in the
			// same cell -- which is what the analytical models assume as well.
			if (!D) continue;
			for (let cell = 0; cell < ncells; cell++) {
				const si = obase + cell * nnuc;
				for (let m = 0; m < nnuc; m++) {
					out[si + m] -= D.lam[m] * y[si + m];
					const o0 = D.ioff[m];
					const cnt = D.icnt[m];
					for (let q = 0; q < cnt; q++) out[si + m] += D.icoef[o0 + q] * y[si + D.ipar[o0 + q]];
				}
			}
		}
	}

	/**
	 * The rates' own tangents, for the Jacobian.
	 *
	 * Only reached when a setting depends on the state -- a travel time that
	 * follows a compartment, say. When they are constants or functions of the
	 * clock alone, `dX` is zero at every setting slot and this does nothing.
	 * The matched layers are held for the run, so only the rates over them
	 * move; see `coefficientsTangent`.
	 *
	 * @returns {boolean} whether any rate moves with the state at all
	 */
	refreshTangent(X, dX) {
		const { keys, nnuc, otherWidth, nnz, nrel } = this;
		let any = false;
		const dOf = (key, slot, off) => dX[this._at(key, Math.floor(slot / nnuc), off)];
		for (let slot = 0; slot < this.slots; slot++) {
			const off = this.dimOff[slot];
			for (const key of keys) {
				if (dOf(key, slot, off) !== 0) { any = true; break; }
			}
			if (any) break;
		}
		if (!any) {
			if (this.dvals) { this.dvals.fill(0); this.drelW.fill(0); }
			return false;
		}
		if (!this.dvals) {
			this.dvals = new Float64Array(this.slots * nnz);
			this.drelW = new Float64Array(this.slots * nrel);
		}
		const s = this.setting;
		const ds = this.dsetting;
		const matched = this.grid === 'matched';
		for (let o = 0; o < otherWidth; o++) {
			for (let m = 0; m < nnuc; m++) {
				const slot = o * nnuc + m;
				const off = this.dimOff[slot];
				this._read(X, o, m, s);
				for (const key of keys) ds[key] = dOf(key, slot, off);
				ds.nf = 0;
				ds.nm = 0;
				const c = coefficients(s, matched ? this.layers[o] : null);
				const dc = coefficientsTangent(s, ds, c);
				cellValues(
					this.structure, dcAsRates(dc),
					this.dvals.subarray(slot * nnz, (slot + 1) * nnz),
				);
				releaseWeights(
					this.structure, dcAsRates(dc),
					this.drelW.subarray(slot * nrel, (slot + 1) * nrel),
				);
			}
		}
		return true;
	}

	/**
	 * J*v for this block: the matrix applied to the seed, plus -- when a rate
	 * depends on the state -- the rate's own tangent applied to the state.
	 */
	jvp(y, v, dout, X, dX, D) {
		this.refresh(X);
		const moving = this.refreshTangent(X, dX);
		const {
			nnuc, otherWidth, ncells, nnz, rows, cols, vals, dvals, base,
		} = this;
		for (let o = 0; o < otherWidth; o++) {
			const obase = base + o * ncells * nnuc;
			for (let m = 0; m < nnuc; m++) {
				const vb = (o * nnuc + m) * nnz;
				for (let e = 0; e < nnz; e++) {
					const r = obase + rows[e] * nnuc + m;
					const c = obase + cols[e] * nnuc + m;
					dout[r] += vals[vb + e] * v[c];
					if (moving) dout[r] += dvals[vb + e] * y[c];
				}
			}
			// Decay is exactly linear in y, so its tangent is the same
			// expression with the seed in place of the state.
			if (!D) continue;
			for (let cell = 0; cell < ncells; cell++) {
				const si = obase + cell * nnuc;
				for (let m = 0; m < nnuc; m++) {
					dout[si + m] -= D.lam[m] * v[si + m];
					const o0 = D.ioff[m];
					const cnt = D.icnt[m];
					for (let q = 0; q < cnt; q++) dout[si + m] += D.icoef[o0 + q] * v[si + D.ipar[o0 + q]];
				}
			}
		}
	}

	/** The tangent of the release, into the block's own algebraic tangent. */
	releaseTangent(y, v, X, dX) {
		this.refresh(X);
		const moving = this.refreshTangent(X, dX);
		const {
			nnuc, otherWidth, ncells, nrel, relCells, relW, drelW, base,
		} = this;
		for (let o = 0; o < otherWidth; o++) {
			const obase = base + o * ncells * nnuc;
			for (let m = 0; m < nnuc; m++) {
				const slot = o * nnuc + m;
				let dq = 0;
				for (let r = 0; r < nrel; r++) {
					const si = obase + relCells[r] * nnuc + m;
					dq += relW[slot * nrel + r] * v[si];
					if (moving) dq += drelW[slot * nrel + r] * y[si];
				}
				dX[this.releaseBase + this.dimOff[slot]] = dq;
			}
		}
	}

	/**
	 * The (row, column) pairs this block can fill.
	 *
	 * Three inflows: the transport structure, which is fixed; the decay chain,
	 * which reaches the same cell's other nuclides; and, when a setting
	 * depends on the state, every column that setting depends on -- because a
	 * rate that moves with a compartment makes every rate in the path depend
	 * on it.
	 */
	pattern(PAT, SX, D) {
		const {
			nnuc, otherWidth, ncells, nnz, rows, cols, base,
		} = this;
		// Which columns the rates themselves depend on.
		const rateCols = new Set();
		for (let slot = 0; slot < this.slots; slot++) {
			const off = this.dimOff[slot];
			for (const key of this.keys) {
				for (const c of SX[this._at(key, Math.floor(slot / nnuc), off)]) rateCols.add(c);
			}
		}
		for (let o = 0; o < otherWidth; o++) {
			const obase = base + o * ncells * nnuc;
			for (let m = 0; m < nnuc; m++) {
				for (let e = 0; e < nnz; e++) {
					PAT(obase + rows[e] * nnuc + m, obase + cols[e] * nnuc + m);
				}
			}
			for (let cell = 0; cell < ncells; cell++) {
				const si = obase + cell * nnuc;
				for (let m = 0; m < nnuc; m++) {
					if (D) {
						const o0 = D.ioff[m];
						for (let q = 0; q < D.icnt[m]; q++) PAT(si + m, si + D.ipar[o0 + q]);
					}
					for (const c of rateCols) PAT(si + m, c);
				}
			}
		}
	}

	/** The columns the block's release depends on: its cells, and its rates. */
	releasePattern(SX) {
		const {
			nnuc, otherWidth, ncells, nrel, relCells, base,
		} = this;
		for (let o = 0; o < otherWidth; o++) {
			const obase = base + o * ncells * nnuc;
			for (let m = 0; m < nnuc; m++) {
				const slot = o * nnuc + m;
				const s = SX[this.releaseBase + this.dimOff[slot]];
				for (let r = 0; r < nrel; r++) s.add(obase + relCells[r] * nnuc + m);
				for (const key of this.keys) {
					for (const c of SX[this._at(key, o, this.dimOff[slot])]) s.add(c);
				}
			}
		}
	}
}

/**
 * A tangent set of coefficients, shaped like the coefficients themselves so
 * that `cellValues` and `releaseWeights` -- which are linear in the rates --
 * can assemble the tangent matrix with the same code that assembles the
 * matrix.
 */
function dcAsRates(dc) {
	return {
		advF: dc.advF, dF: dc.dF, diffFM1: dc.diffFM1, diffM1F: dc.diffM1F,
		diffMMF: dc.diffMMF, diffMMB: dc.diffMMB,
	};
}
