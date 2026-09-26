/**
 * The runtime side of a far-field path worked out semi-analytically: one
 * `LaplaceFarfPath` per block whose method is 'semi-analytical', beside
 * `FarfPath` in ./farfield.js for the paths on cells, and with its interface.
 *
 * WHAT IT HOLDS. No cells. One state per nuclide -- per combination of the
 * block's other dimensions -- for what the path holds, integrated from the
 * path's own balance
 *
 *     d(held)/dt = in - out - Lambda held,
 *
 * so that what went in, what came out and what decayed add up to what is held
 * to rounding, whatever the solver does. `in` is whatever the model's fluxes
 * deliver into the path: they land on that state exactly as they land on the
 * first fracture cell of a path on cells. `out`, the release, is the
 * convolution of the inflow's history with the path's unit responses:
 *
 *     out_i(t) = sum_j integral h_ij(t - tau) in_j(tau) dtau,
 *
 * the responses worked out once per run -- a realisation's included, since
 * the path's settings are constants within one -- by the Laplace-domain
 * solution in ../domain/farfield-laplace.js, which says what is solved and how.
 *
 * THE HISTORY. The inflow is recorded wherever the solver tells the model
 * about an instant: every accepted step, every requested output time, and the
 * start of every segment (after a switch time or a jump). Between records it
 * is the cubic through that record and the three before it in the same run of
 * records -- causal, so a piece never changes once written, and fourth order,
 * so it follows the inflow as closely as the solver followed the state. Two
 * records at one instant are a step in the inflow; a jump of the held state
 * between them is an amount delivered at once (a waste package failing, a
 * disruption), which releases as that amount times the unit response.
 *
 * THE CONVOLUTION, and why it costs no more as the run gets longer. Each
 * recorded piece is kept as its first six moments about its centre. While a
 * piece is narrow beside the response's own grid spacing at the lag it sits
 * at, its contribution is sum_m (-w)^m h^(m)(t - c)/m! mu_m -- exact over one
 * quintic piece of the tabulated response, and within the tabulation's own
 * tolerance across two. Adjacent pieces merge (their moments shift to the
 * merged centre exactly) as soon as the merged width is narrow beside every
 * spacing they will still meet: lags only grow, and past the front the
 * response's spacing grows with them. So the history holds about as many
 * blocks as the response has grid points, however many steps the solver
 * takes, and the history is summed once per instant the solver asks about --
 * Newton iterations and Jacobian colours at one instant share it.
 *
 * THE STEP BEING TAKEN. From the last record to the time asked about, the
 * inflow is the same cubic with the current inflow as its last node, and its
 * contribution is sum_k v_k W_k, the weights integrals of the response
 * against the cubic's basis over [0, dt] -- exact for that cubic. The weight of
 * the current inflow is also the release's derivative along it, which is what
 * `releaseTangent` hands the Jacobian. It is zero while the step is shorter
 * than the time the path takes to let anything through, which is the usual
 * case, and exactly zero under plug flow.
 *
 * AFTER THE RUN. The release at every recorded instant is kept, so the pass
 * that works the series out afterwards reads what the run used. At any other
 * earlier time -- or on a run read back from a file, whose records travel in
 * `memory` like a recorder's history -- the convolution is swept forward from
 * the records again.
 */

import { FarfError } from '../domain/farfield.js';
import {
	preparePath, transferAtZero, unitResponse, LaplacePathError,
} from '../domain/farfield-laplace.js';

/**
 * A merged block may be at most this fraction of the narrowest response
 * spacing it will still meet. Measured on an inflow the history holds
 * exactly, so that only this approximation is left: 0.3 is 1e-11, 0.6 is
 * 2e-10 and 1 is 8e-9 of the release under plug flow (the hardest case), and
 * the blocks go 3,000, 1,850, 1,270 on 20,000 records.
 */
const RHO = 0.5;

/** Pairs that pass less than this fraction of what their source lets through at most are left out. */
const NEGLIGIBLE = 1e-15;

/** Five-point Gauss-Legendre on [-1, 1]: exact for the quintic response times a cubic. */
const GL5_X = [-0.906179845938664, -0.5384693101056831, 0, 0.5384693101056831, 0.906179845938664];
const GL5_W = [0.23692688505618908, 0.47862867049936647, 0.5688888888888889, 0.47862867049936647, 0.23692688505618908];

/** Unit responses by settings, shared by every path and every run in this thread. */
const RESPONSES = new Map();
const RESPONSES_KEEP = 32;

/** What a set of responses is a function of, as one string: every number by `String`, so Infinity is kept. */
function responseKey(settings, D, span, nnuc) {
	const parts = [String(span), String(nnuc)];
	for (const key of Object.keys(settings).sort()) {
		const v = settings[key];
		parts.push(`${key}=${Array.isArray(v) ? v.map(String).join(',') : String(v)}`);
	}
	if (D) {
		for (const name of ['lam', 'ioff', 'icnt', 'ipar', 'icoef']) parts.push(`${name}=${Array.from(D[name]).map(String).join(',')}`);
	}
	return parts.join(';');
}

/**
 * One unit response, ready to convolve: the quintic Hermite pieces of
 * ../domain/farfield-laplace.js in the power basis of each piece, their running
 * moments for the step being taken, and the narrowest spacing ahead of every
 * lag, which is what a block of history may be merged against.
 */
function makeKernel(r) {
	const t = Float64Array.from(r.t);
	const n = t.length;
	const np = Math.max(0, n - 1);
	const a = new Float64Array(np * 6);
	for (let k = 0; k < np; k++) {
		const d = t[k + 1] - t[k];
		const ya = r.h[k];
		const da = d * r.dh[k];
		const ea = d * d * r.d2h[k];
		const yb = r.h[k + 1];
		const db = d * r.dh[k + 1];
		const eb = d * d * r.d2h[k + 1];
		const o = k * 6;
		a[o] = ya;
		a[o + 1] = da;
		a[o + 2] = 0.5 * ea;
		a[o + 3] = -10 * ya - 6 * da - 1.5 * ea + 10 * yb - 4 * db + 0.5 * eb;
		a[o + 4] = 15 * ya + 8 * da + 1.5 * ea - 15 * yb + 7 * db - eb;
		a[o + 5] = -6 * ya - 3 * da - 0.5 * ea + 6 * yb - 3 * db + 0.5 * eb;
	}
	// The narrowest piece from each one on: a lag that will only grow meets
	// nothing narrower than this. (Widening where the response is far below
	// its peak halves the blocks and costs relative accuracy exactly where a
	// release is made of the tail alone -- 1e-6 under plug flow -- so no.)
	const ahead = new Float64Array(np + 1).fill(Infinity);
	for (let k = np - 1; k >= 0; k--) ahead[k] = Math.min(ahead[k + 1], t[k + 1] - t[k]);
	// integral of h(u) u^q from the first point to each point, q = 0..3.
	const P = [new Float64Array(n), new Float64Array(n), new Float64Array(n), new Float64Array(n)];
	const kern = {
		t, n, np, a, ahead, P, t0: n ? t[0] : Infinity, tEnd: n ? t[n - 1] : -Infinity, T0: r.T0,
		// Under plug flow, what arrives within a hair of the delay, as a point
		// mass at the first time: m0 times the inflow at t - tm0.
		m0: r.m0 > 0 && n ? r.m0 : 0, tm0: n ? t[0] : Infinity,
	};
	for (let k = 0; k < np; k++) {
		const part = pieceMoments(kern, k, t[k], t[k + 1]);
		for (let q = 0; q < 4; q++) P[q][k + 1] = P[q][k] + part[q];
	}
	return kern;
}

/** The piece that holds lag u, clamped to the grid. */
function pieceAt(kern, u) {
	const { t, np } = kern;
	if (u <= t[0]) return 0;
	if (u >= t[np]) return np - 1;
	let lo = 0;
	let hi = np;
	while (hi - lo > 1) {
		const m = (lo + hi) >> 1;
		if (t[m] <= u) lo = m; else hi = m;
	}
	return lo;
}

/** h at lag u, zero outside the tabulated span. */
function kernelAt(kern, u) {
	if (!(u >= kern.t0) || !(u <= kern.tEnd) || kern.np < 1) return 0;
	const k = pieceAt(kern, u);
	const o = k * 6;
	const d = kern.t[k + 1] - kern.t[k];
	const x = (u - kern.t[k]) / d;
	const a = kern.a;
	return a[o] + x * (a[o + 1] + x * (a[o + 2] + x * (a[o + 3] + x * (a[o + 4] + x * a[o + 5]))));
}

/** integral of h(u) u^q over [ua, ub] inside piece k, q = 0..3, by Gauss-Legendre. */
function pieceMoments(kern, k, ua, ub) {
	const out = [0, 0, 0, 0];
	if (!(ub > ua)) return out;
	const t0 = kern.t[k];
	const d = kern.t[k + 1] - t0;
	const o = k * 6;
	const a = kern.a;
	const c = 0.5 * (ua + ub);
	const hw = 0.5 * (ub - ua);
	for (let g = 0; g < 5; g++) {
		const u = c + GL5_X[g] * hw;
		const x = (u - t0) / d;
		const h = a[o] + x * (a[o + 1] + x * (a[o + 2] + x * (a[o + 3] + x * (a[o + 4] + x * a[o + 5]))));
		const w = GL5_W[g] * hw * h;
		out[0] += w;
		out[1] += w * u;
		out[2] += w * u * u;
		out[3] += w * u * u * u;
	}
	return out;
}

/** integral of h(u) u^q over [0, D], q = 0..3, into `out`. */
function runningMoments(kern, D, out) {
	out[0] = 0; out[1] = 0; out[2] = 0; out[3] = 0;
	if (!(D > kern.t0) || kern.np < 1) return out;
	const top = Math.min(D, kern.tEnd);
	const k = pieceAt(kern, top);
	for (let q = 0; q < 4; q++) out[q] = kern.P[q][k];
	const rest = pieceMoments(kern, k, kern.t[k], top);
	for (let q = 0; q < 4; q++) out[q] += rest[q];
	return out;
}

/**
 * The Lagrange basis of the nodes `s` (lags, the last one zero) as
 * polynomials in x = u/D over the step: `coef[k][q]`.
 */
function lagBasis(s, count, D, coef) {
	for (let k = 0; k < count; k++) {
		const row = coef[k];
		row.fill(0);
		row[0] = 1;
		let deg = 0;
		let den = 1;
		const sk = s[k] / D;
		for (let m = 0; m < count; m++) {
			if (m === k) continue;
			const sm = s[m] / D;
			// row *= (x - sm)
			for (let q = deg + 1; q >= 1; q--) row[q] = row[q - 1] - sm * row[q];
			row[0] = -sm * row[0];
			deg++;
			den *= sk - sm;
		}
		for (let q = 0; q <= deg; q++) row[q] /= den;
	}
}

/** Binomial coefficients to 5, for shifting moments. */
const BINOM = [[1], [1, 1], [1, 2, 1], [1, 3, 3, 1], [1, 4, 6, 4, 1], [1, 5, 10, 10, 5, 1]];

/**
 * The inflow of one source, recorded, and what it has put into the path.
 *
 * Blocks are kept oldest first in flat arrays: centre, half-width, the six
 * moments scaled by the half-width, and -- for a block that is still one
 * recorded piece -- the piece's cubic in s = (tau - c)/w, so that a piece too
 * wide for its moments can be integrated against the response directly.
 */
class Convolver {
	constructor(targets) {
		// [{i, kern}] for every target this source reaches.
		this.targets = targets;
		this.reset();
	}

	reset() {
		this.bc = [];
		this.bw = [];
		this.bm = [];
		this.bp = [];
		// The records of the current run of them (after the last break), at
		// most the four the cubic needs.
		this.rt = [];
		this.rv = [];
		this.lastT = -Infinity;
		this.impT = [];
		this.impA = [];
		this.compactAt = 64;
		this.count = 0;
	}

	/** The narrowest response spacing any target will meet from lag u on. */
	ahead(u) {
		let m = Infinity;
		for (const { kern } of this.targets) {
			if (u >= kern.tEnd) continue;
			const d = u <= kern.t0 ? kern.ahead[0] : kern.ahead[pieceAt(kern, u)];
			if (d < m) m = d;
		}
		return m;
	}

	/** The latest lag any target still responds at. */
	reach() {
		let m = -Infinity;
		for (const { kern } of this.targets) if (kern.tEnd > m) m = kern.tEnd;
		return m;
	}

	/** An amount delivered at one instant. */
	impulse(t, amount) {
		if (amount === 0 || !Number.isFinite(amount)) return;
		this.impT.push(t);
		this.impA.push(amount);
	}

	/** One record. Equal to the last in time, it starts a new run of records. */
	push(t, v) {
		this.count++;
		if (t === this.lastT) {
			if (v === this.rv[this.rv.length - 1]) return;
			this.rt = [t];
			this.rv = [v];
			return;
		}
		if (t < this.lastT) throw new Error('a far-field path was told about an earlier instant after a later one');
		const nr = this.rt.length;
		if (nr) this._piece(t, v);
		this.rt.push(t);
		this.rv.push(v);
		if (this.rt.length > 4) { this.rt.shift(); this.rv.shift(); }
		this.lastT = t;
		if (this.bc.length > this.compactAt) this.compact(t);
	}

	/** The piece from the last record to (t, v), as a block. */
	_piece(t, v) {
		const nr = this.rt.length;
		const tb = t;
		const ta = this.rt[nr - 1];
		const c = 0.5 * (ta + tb);
		const w = 0.5 * (tb - ta);
		// The nodes, in s = (tau - c)/w: the new record at 1, the last at -1.
		const count = Math.min(nr + 1, 4);
		const ns = new Array(count);
		const nv = new Array(count);
		for (let k = 0; k < count - 1; k++) {
			ns[k] = (this.rt[nr - (count - 1) + k] - c) / w;
			nv[k] = this.rv[nr - (count - 1) + k];
		}
		ns[count - 1] = 1;
		nv[count - 1] = v;
		// The cubic through them, in the power basis of s.
		const e = [0, 0, 0, 0];
		const basis = [0, 0, 0, 0, 0];
		for (let k = 0; k < count; k++) {
			basis.fill(0);
			basis[0] = 1;
			let deg = 0;
			let den = 1;
			for (let m = 0; m < count; m++) {
				if (m === k) continue;
				for (let q = deg + 1; q >= 1; q--) basis[q] = basis[q - 1] - ns[m] * basis[q];
				basis[0] = -ns[m] * basis[0];
				deg++;
				den *= ns[k] - ns[m];
			}
			for (let q = 0; q <= deg; q++) e[q] += nv[k] * basis[q] / den;
		}
		// Its moments about c: w * integral_{-1}^{1} p(s) s^m ds.
		const mu = new Array(6);
		for (let m = 0; m < 6; m++) {
			let s = 0;
			for (let q = 0; q < 4; q++) if ((q + m) % 2 === 0) s += e[q] * 2 / (q + m + 1);
			mu[m] = w * s;
		}
		this.bc.push(c);
		this.bw.push(w);
		this.bm.push(mu);
		this.bp.push(e);
	}

	/**
	 * Merges neighbouring blocks that are narrow beside every response spacing
	 * they will still meet, and drops those older than any response reaches.
	 */
	compact(tNow) {
		const reach = this.reach();
		const bc = [];
		const bw = [];
		const bm = [];
		const bp = [];
		for (let k = 0; k < this.bc.length; k++) {
			let c = this.bc[k];
			let w = this.bw[k];
			if (tNow - (c + w) > reach) continue;
			let mu = this.bm[k];
			let p = this.bp[k];
			const last = bc.length - 1;
			if (last >= 0) {
				const lo = bc[last] - bw[last];
				const hi = c + w;
				const width = hi - lo;
				if (width <= RHO * this.ahead(tNow - hi)) {
					const nc = 0.5 * (lo + hi);
					const nw = 0.5 * width;
					const merged = shift(bm[last], bc[last], bw[last], nc, nw);
					const mine = shift(mu, c, w, nc, nw);
					for (let m = 0; m < 6; m++) merged[m] += mine[m];
					bc[last] = nc;
					bw[last] = nw;
					bm[last] = merged;
					bp[last] = null;
					continue;
				}
			}
			bc.push(c);
			bw.push(w);
			bm.push(mu);
			bp.push(p);
		}
		this.bc = bc;
		this.bw = bw;
		this.bm = bm;
		this.bp = bp;
		this.compactAt = 2 * bc.length + 64;
	}

	/**
	 * What the recorded history releases at t, added into `out[i]` for each
	 * target: the blocks and the amounts delivered at once.
	 *
	 * Newest block first, so that both lags a block is read at -- its centre's
	 * and its youngest edge's -- only grow, and the response pieces holding
	 * them are found by walking forward rather than by searching.
	 */
	history(t, out) {
		const { bc, bw, bm, bp } = this;
		const nb = bc.length;
		for (let q = 0; q < this.targets.length; q++) {
			const { i, kern } = this.targets[q];
			const np = kern.np;
			if (np < 1) continue;
			const tk = kern.t;
			const ahead = kern.ahead;
			const t0 = kern.t0;
			const tEnd = kern.tEnd;
			let sum = 0;
			let k = 0;
			let ka = 0;
			for (let b = nb - 1; b >= 0; b--) {
				const c = bc[b];
				const w = bw[b];
				const uc = t - c;
				if (uc + w <= t0) continue;
				if (uc - w >= tEnd) break;
				const e = bp[b];
				if (e) {
					// One recorded piece: by its moments only while it is narrow
					// beside every spacing from its youngest lag on.
					const young = uc - w;
					while (ka < np - 1 && tk[ka + 1] <= young) ka++;
					if (2 * w > RHO * (young <= t0 ? ahead[0] : ahead[ka])) {
						sum += direct(kern, t, c, w, e);
						continue;
					}
				}
				while (k < np - 1 && tk[k + 1] <= uc) k++;
				sum += fromMoments(kern, k, uc, w, bm[b]);
			}
			for (let r = 0; r < this.impT.length; r++) sum += this.impA[r] * kernelAt(kern, t - this.impT[r]);
			out[i] += sum;
		}
	}

	/** The narrowest spacing of one response from lag u on. */
	aheadOf(kern, u) {
		if (u >= kern.tEnd) return Infinity;
		return u <= kern.t0 ? kern.ahead[0] : kern.ahead[pieceAt(kern, u)];
	}
}

/**
 * Moments about c, scaled by the half-width w -- mu_m = integral in(tau)
 * ((tau - c)/w)^m dtau -- as moments about nc scaled by nw. With s the old
 * scaled variable, the new one is alpha s + beta, alpha = w/nw <= 1 and
 * |beta| <= 1, so the binomial sum cannot grow.
 */
function shift(mu, c, w, nc, nw) {
	const alpha = w / nw;
	const beta = (c - nc) / nw;
	const out = [0, 0, 0, 0, 0, 0];
	for (let m = 0; m < 6; m++) {
		let s = 0;
		for (let k = 0; k <= m; k++) s += BINOM[m][k] * alpha ** k * beta ** (m - k) * mu[k];
		out[m] = s;
	}
	return out;
}

/** A block by its moments, against the piece k of the response around lag uc. */
function fromMoments(kern, k, uc, w, mu) {
	const t0 = kern.t[k];
	const d = kern.t[k + 1] - t0;
	const x = (uc - t0) / d;
	const a = kern.a;
	const o = k * 6;
	// The Taylor coefficients of the piece at x, by repeated synthetic division.
	const b0 = a[o]; const b1 = a[o + 1]; const b2 = a[o + 2];
	const b3 = a[o + 3]; const b4 = a[o + 4]; const b5 = a[o + 5];
	let c5 = b5;
	let c4 = b4 + x * c5;
	let c3 = b3 + x * c4;
	let c2 = b2 + x * c3;
	let c1 = b1 + x * c2;
	const t0c = b0 + x * c1;
	c4 += x * c5;
	c3 += x * c4;
	c2 += x * c3;
	const t1c = c1 + x * c2;
	c4 += x * c5;
	c3 += x * c4;
	const t2c = c2 + x * c3;
	c4 += x * c5;
	const t3c = c3 + x * c4;
	const t4c = c4 + x * c5;
	const t5c = c5;
	const r = -w / d;
	return t0c * mu[0] + r * (t1c * mu[1] + r * (t2c * mu[2] + r * (t3c * mu[3] + r * (t4c * mu[4] + r * t5c * mu[5]))));
}

/** A recorded piece integrated against the response directly, piece by piece. */
function direct(kern, t, c, w, e) {
	const uLo = Math.max(t - (c + w), kern.t0);
	const uHi = Math.min(t - (c - w), kern.tEnd);
	if (!(uHi > uLo)) return 0;
	let k = pieceAt(kern, uLo);
	let u = uLo;
	let sum = 0;
	const a = kern.a;
	while (u < uHi && k < kern.np) {
		const next = Math.min(uHi, kern.t[k + 1]);
		if (next > u) {
			const t0 = kern.t[k];
			const d = kern.t[k + 1] - t0;
			const o = k * 6;
			const mid = 0.5 * (u + next);
			const hw = 0.5 * (next - u);
			for (let g = 0; g < 5; g++) {
				const uu = mid + GL5_X[g] * hw;
				const x = (uu - t0) / d;
				const h = a[o] + x * (a[o + 1] + x * (a[o + 2] + x * (a[o + 3] + x * (a[o + 4] + x * a[o + 5]))));
				const s = (t - uu - c) / w;
				const v = e[0] + s * (e[1] + s * (e[2] + s * e[3]));
				sum += GL5_W[g] * hw * h * v;
			}
		}
		u = next;
		k++;
	}
	return sum;
}

/**
 * The step from a source's last record to t, for each of its targets: the
 * weights of the cubic's nodes -- the up to three records before t in the
 * same run, then the current inflow -- each the integral of the response
 * against that node's basis polynomial over the lags [0, t - last].
 *
 * @returns {Array<{i: number, w: number[], count: number, nr: number}>}
 */
function stepWeights(cv, t) {
	const out = [];
	const nr = cv.rt.length;
	const D = t - cv.lastT;
	if (!cv.targets.length || !nr || !(D > 0)) return out;
	const count = Math.min(nr + 1, 4);
	const s = new Array(count);
	for (let k = 0; k < count - 1; k++) s[k] = t - cv.rt[nr - (count - 1) + k];
	s[count - 1] = 0;
	let coef = null;
	const mom = [0, 0, 0, 0];
	for (const { i, kern } of cv.targets) {
		if (!(D > kern.t0)) continue;
		if (!coef) {
			coef = Array.from({ length: count }, () => [0, 0, 0, 0, 0]);
			lagBasis(s, count, D, coef);
		}
		runningMoments(kern, D, mom);
		// integral of h (u/D)^q
		let Dq = 1;
		for (let q = 1; q < 4; q++) { Dq *= D; mom[q] /= Dq; }
		const w = new Array(count);
		for (let k = 0; k < count; k++) {
			let v = 0;
			for (let q = 0; q < count; q++) v += coef[k][q] * mom[q];
			w[k] = v;
		}
		out.push({ i, w, count, nr });
	}
	return out;
}

/**
 * The point masses (see `makeKernel`) whose lag puts them inside the step
 * being taken, after the last record: the inflow there is the step's cubic,
 * so each is a set of node weights like the step's own.
 */
function pointParts(cv, t) {
	const out = [];
	const nr = cv.rt.length;
	if (!nr) return out;
	for (const { i, kern } of cv.targets) {
		if (!(kern.m0 > 0)) continue;
		const tau = t - kern.tm0;
		if (!(tau > cv.lastT)) continue;
		const count = Math.min(nr + 1, 4);
		const nodes = new Array(count);
		for (let k = 0; k < count - 1; k++) nodes[k] = cv.rt[nr - (count - 1) + k];
		nodes[count - 1] = t;
		const w = new Array(count);
		for (let k = 0; k < count; k++) {
			let l = 1;
			for (let m = 0; m < count; m++) if (m !== k) l *= (tau - nodes[m]) / (nodes[k] - nodes[m]);
			w[k] = kern.m0 * l;
		}
		out.push({ i, w, count, nr });
	}
	return out;
}

/** The step's contribution: its node weights against the records and the current inflow `v`. */
function stepSum(cv, part, v) {
	const { w, count, nr } = part;
	let r = w[count - 1] * v;
	for (let k = 0; k < count - 1; k++) r += w[k] * cv.rv[nr - (count - 1) + k];
	return r;
}

/**
 * A record-keeping stand-in for a recorder, so that the path's history
 * travels in `memory` with the recorders' when a run is saved to a file and
 * read back (see ../io/dataset.js).
 */
function holder(kind) {
	return {
		kind,
		history: { t: [], v: [] },
		recording: true,
		totalTime: 0,
		lastTime: 0,
		resetSum: 0,
		prime() {
			this.history.t = [];
			this.history.v = [];
		},
	};
}

export class LaplaceFarfPath {
	/**
	 * @param {object} spec  as `FarfPath` takes it, plus
	 * @param {number} spec.span  the length of the run, which is as far as a
	 *   response is ever read
	 * @param {string[]} [spec.names]  the nuclides, for messages
	 * @param {string} [spec.blockName]  the block, for messages
	 */
	constructor(spec) {
		Object.assign(this, spec);
		this.method = 'semi-analytical';
		this.isSingle = new Set(spec.single ?? []);
		this.ncells = 1;
		this.slots = this.otherWidth * this.nnuc;
		this.surface = spec.surface ?? 'f';
		this.D = null;
		this.inflowFn = null;
		this.inflowTangentFn = null;
		this.inflowColumnsFn = null;
		this.IN = new Float64Array(this.slots);
		this.DIN = new Float64Array(this.slots);
		this.held = new Float64Array(this.slots);
		this.lastHeld = new Float64Array(this.slots);
		// Per slot, what it has recorded and what it delivered at once: the
		// part of the run a file carries.
		this.records = Array.from({ length: this.slots }, () => holder('farfield_inflow'));
		this.impulses = Array.from({ length: this.slots }, () => holder('farfield_impulse'));
		this.memory = [...this.records, ...this.impulses];
		this.combos = new Array(this.otherWidth).fill(null);
		this.live = null;
		this.sweep = null;
		this.sweepAt = -Infinity;
		this.releases = new Map();
		this.lastT = -Infinity;
		this.histT = NaN;
		this.histVals = new Float64Array(this.slots);
		this.weightT = NaN;
		this.weights = null;
		this.ready = false;
		this.key = null;
		this.stats = { evaluations: 0, blocks: 0, pairs: 0, responseMs: 0 };
	}

	/** The decay constants and the decay table the path's nuclides decay with, or null for none. */
	setDecay(lam, table = null) {
		this.D = table ?? null;
		this.restart();
	}

	/** The generated functions that work out, for every slot, what the model's fluxes deliver into the path. */
	setInflow({ value, tangent, columns }) {
		this.inflowFn = value;
		this.inflowTangentFn = tangent;
		this.inflowColumnsFn = columns;
	}

	/** Starts a run: responses are worked out again from the settings at its first instant, and the history is empty. */
	restart() {
		this.ready = false;
		this.live = null;
		this.sweep = null;
		this.sweepAt = -Infinity;
		this.releases = new Map();
		this.lastT = -Infinity;
		this.histT = NaN;
		this.weightT = NaN;
		for (const h of this.memory) h.prime();
	}

	_at(key, o, off) {
		const one = this.singleOff ? this.singleOff[o] : 0;
		return this.settingBase[key] + (this.isSingle.has(key) ? one : off);
	}

	/** The settings of one combination, as ../domain/farfield-laplace.js takes them. */
	settingsOf(X, o) {
		const s = { surface: this.surface };
		for (const key of this.keys) {
			if (this.isSingle.has(key)) {
				s[key] = X[this._at(key, o, this.dimOff[o * this.nnuc])];
			} else {
				const v = new Array(this.nnuc);
				for (let m = 0; m < this.nnuc; m++) v[m] = X[this._at(key, o, this.dimOff[o * this.nnuc + m])];
				s[key] = v;
			}
		}
		return s;
	}

	/**
	 * The unit responses of every combination, from the settings in X.
	 * Refuses, with the reason, what the method cannot solve.
	 */
	prepare(X) {
		const started = typeof performance !== 'undefined' ? performance.now() : Date.now();
		this.combos = new Array(this.otherWidth);
		let pairs = 0;
		for (let o = 0; o < this.otherWidth; o++) {
			const settings = this.settingsOf(X, o);
			const D = this.D;
			const key = responseKey(settings, D, this.span, this.nnuc);
			let combo = RESPONSES.get(key);
			if (combo) {
				RESPONSES.delete(key);
				RESPONSES.set(key, combo);
			} else {
				combo = this._responses(settings);
				RESPONSES.set(key, combo);
				while (RESPONSES.size > RESPONSES_KEEP) RESPONSES.delete(RESPONSES.keys().next().value);
			}
			this.combos[o] = combo;
			pairs += combo.pairs;
		}
		const ended = typeof performance !== 'undefined' ? performance.now() : Date.now();
		this.stats.responseMs += ended - started;
		this.stats.pairs = pairs;
		this.ready = true;
		this.live = this._convolvers();
	}

	_responses(settings) {
		let path;
		try {
			path = preparePath(settings, this.D, { n: this.nnuc, names: this.names });
		} catch (e) {
			if (e instanceof LaplacePathError) throw new FarfError(e.message);
			throw e;
		}
		const n = this.nnuc;
		const T0 = transferAtZero(path);
		const kernels = new Array(n * n).fill(null);
		// Responses that miss their mass balance even when worked out again
		// (see `unitResponse`): the run goes on, and says so.
		const misses = [];
		let pairs = 0;
		for (let j = 0; j < n; j++) {
			let most = 0;
			for (let i = 0; i < n; i++) if (T0[i * n + j] > most) most = T0[i * n + j];
			for (let i = 0; i < n; i++) {
				if (!path.reach[j][i]) continue;
				const T = T0[i * n + j];
				if (!(T > NEGLIGIBLE * most) || !(T > 1e-300)) continue;
				const r = unitResponse(path, i, j, { kind: 'release', tMax: this.span });
				if (r.balanced === false) {
					misses.push({
						i, j, integral: r.integral, expected: r.expected, T0: r.T0, rel: r.rel,
						until: r.t.length ? r.t[r.t.length - 1] : NaN,
					});
				}
				if (r.t.length < 2) continue;
				kernels[i * n + j] = makeKernel(r);
				pairs++;
			}
		}
		return { kernels, pairs, misses };
	}

	/**
	 * What the run has to say about this path: every unit response that
	 * missed its mass balance, `{block, message}` -- never a quiet shortfall.
	 */
	balanceWarnings() {
		const out = [];
		const p4 = (x) => Number(x).toPrecision(4);
		const name = (k) => (this.names ? this.names[k] : `#${k + 1}`);
		(this.combos ?? []).forEach((combo, o) => {
			for (const m of combo?.misses ?? []) {
				const where = this.otherWidth > 1 ? ` (index combination ${o + 1} of ${this.otherWidth})` : '';
				out.push({
					block: this.blockName,
					message: `the unit response of ${name(m.i)} to ${name(m.j)}${where} integrates to `
						+ `${p4(m.integral)}, but ${p4(m.expected)} of a pulse leaves the path by `
						+ `${p4(m.until)} (T(0) = ${p4(m.T0)}): the inversion failed there, and the release `
						+ 'worked out from it is not reliable',
				});
			}
		});
		return out;
	}

	/** One convolver per slot, over the targets its source reaches. */
	_convolvers() {
		const out = new Array(this.slots);
		for (let o = 0; o < this.otherWidth; o++) {
			const { kernels } = this.combos[o];
			for (let j = 0; j < this.nnuc; j++) {
				const targets = [];
				for (let i = 0; i < this.nnuc; i++) {
					const kern = kernels[i * this.nnuc + j];
					if (kern) targets.push({ i: o * this.nnuc + i, kern });
				}
				out[o * this.nnuc + j] = new Convolver(targets);
			}
		}
		return out;
	}

	/** What the model's fluxes deliver into every slot at (y, X), into `this.IN`. */
	inflow(y, X) {
		this.IN.fill(0);
		this.inflowFn?.(y, X, this.IN);
		return this.IN;
	}

	/**
	 * The step from the last record to t: for each source and target, the
	 * weights of the cubic's nodes -- the records before it and the current
	 * inflow -- and in `cur` the current inflow's alone, which is the
	 * release's derivative along it.
	 */
	_weights(t) {
		if (t === this.weightT) return this.weights;
		const n = this.nnuc;
		const W = { cur: new Float64Array(this.slots * n), parts: [] };
		if (this.live && t > this.lastT) {
			for (let slot = 0; slot < this.slots; slot++) {
				for (const part of [...stepWeights(this.live[slot], t), ...pointParts(this.live[slot], t)]) {
					part.slot = slot;
					W.parts.push(part);
					W.cur[part.i * n + (slot % n)] += part.w[part.count - 1];
				}
			}
		}
		this.weights = W;
		this.weightT = t;
		return W;
	}

	/** The release of every slot at t, into its algebraic slots. */
	release(y, X, t = NaN) {
		if (!this.ready) this.prepare(X);
		this.stats.evaluations++;
		const kept = this.releases.get(t);
		if (kept) {
			for (let slot = 0; slot < this.slots; slot++) X[this.releaseBase + this.dimOff[slot]] = kept[slot];
			return;
		}
		const recorded = this.records[0]?.history.t;
		const lastRecorded = recorded?.length ? recorded[recorded.length - 1] : -Infinity;
		if (t < lastRecorded || (recorded?.length && this.lastT === -Infinity)) {
			this._behind(y, X, t);
			return;
		}
		const hist = this.histVals;
		if (t !== this.histT) {
			hist.fill(0);
			if (this.live) {
				for (let slot = 0; slot < this.slots; slot++) {
					this.live[slot].history(t, hist);
					this._pointsBehind(this.live[slot], slot, t, hist);
				}
			}
			this.histT = t;
		}
		const IN = this.inflow(y, X);
		const W = this._weights(t);
		const res = this.scratch ?? (this.scratch = new Float64Array(this.slots));
		res.set(hist);
		for (const part of W.parts) res[part.i] += stepSum(this.live[part.slot], part, IN[part.slot]);
		for (let slot = 0; slot < this.slots; slot++) X[this.releaseBase + this.dimOff[slot]] = res[slot];
	}

	/**
	 * The release at an earlier instant than the last record, or on a run read
	 * back from a file: swept forward from the records again.
	 */
	_behind(y, X, t) {
		if (!this.sweep || t < this.sweepAt) {
			this.sweep = this._convolvers();
			this.sweepAt = -Infinity;
			this.sweepNext = 0;
			this.sweepImp = new Int32Array(this.slots);
		}
		const times = this.records[0].history.t;
		while (this.sweepNext < times.length && times[this.sweepNext] <= t) {
			const q = this.sweepNext++;
			for (let slot = 0; slot < this.slots; slot++) {
				const rec = this.records[slot].history;
				this.sweep[slot].push(rec.t[q], rec.v[q]);
			}
		}
		for (let slot = 0; slot < this.slots; slot++) {
			const imp = this.impulses[slot].history;
			const cv = this.sweep[slot];
			while (this.sweepImp[slot] < imp.t.length && imp.t[this.sweepImp[slot]] <= t) {
				const q = this.sweepImp[slot]++;
				cv.impulse(imp.t[q], imp.v[q]);
			}
		}
		this.sweepAt = t;
		const out = new Float64Array(this.slots);
		for (let slot = 0; slot < this.slots; slot++) {
			this.sweep[slot].history(t, out);
			this._pointsBehind(this.sweep[slot], slot, t, out);
		}
		// The step from the last record to t, with the inflow at (t, y).
		const IN = this.inflow(y, X);
		for (let slot = 0; slot < this.slots; slot++) {
			const cv = this.sweep[slot];
			for (const part of [...stepWeights(cv, t), ...pointParts(cv, t)]) out[part.i] += stepSum(cv, part, IN[slot]);
		}
		for (let slot = 0; slot < this.slots; slot++) X[this.releaseBase + this.dimOff[slot]] = out[slot];
	}

	/**
	 * The point masses whose lag reaches back into the recorded history: m0
	 * times what flowed in at t - tm0, from the records.
	 */
	_pointsBehind(cv, slot, t, out) {
		for (const { i, kern } of cv.targets) {
			if (!(kern.m0 > 0)) continue;
			const tau = t - kern.tm0;
			if (tau > cv.lastT) continue;
			out[i] += kern.m0 * this._recordedInflow(slot, tau);
		}
	}

	/**
	 * What flowed into `slot` at the earlier instant tau: the cubic the history
	 * holds there, through the record after tau and up to three before it in
	 * the same run of records. Nothing before the first record.
	 */
	_recordedInflow(slot, tau) {
		const T = this.records[0].history.t;
		const V = this.records[slot].history.v;
		const n = T.length;
		if (!n || !(tau >= T[0])) return 0;
		if (tau >= T[n - 1]) return V[n - 1];
		let lo = 0;
		let hi = n - 1;
		while (hi - lo > 1) { const c = (lo + hi) >> 1; if (T[c] <= tau) lo = c; else hi = c; }
		const b = lo + 1;
		let first = b;
		while (first > 0 && b - first < 3 && T[first - 1] < T[first]) first--;
		let v = 0;
		for (let k = first; k <= b; k++) {
			let l = 1;
			for (let m = first; m <= b; m++) if (m !== k) l *= (tau - T[m]) / (T[k] - T[m]);
			v += l * V[k];
		}
		return v;
	}

	/**
	 * Puts the history back to the start of a run and records its first
	 * instant. `X` is the algebra at (t0, y0).
	 */
	prime(t0, y0, X) {
		if (!this.ready) this.prepare(X);
		for (const h of this.memory) h.prime();
		this.live = this._convolvers();
		this.sweep = null;
		this.releases = new Map();
		this.lastT = -Infinity;
		this.histT = NaN;
		this.weightT = NaN;
		this.store(t0, y0, X);
	}

	/**
	 * Records an instant the solver has told the model about: an accepted step,
	 * a requested output time, or the start of a segment. `X` is the algebra at
	 * (t, y), the release among it.
	 */
	store(t, y, X) {
		if (!this.ready) this.prepare(X);
		if (!this.live) this.live = this._convolvers();
		// A restart from an earlier instant: nothing recorded after it happened.
		if (t < this.lastT) this._truncate(t);
		const IN = this.inflow(y, X);
		const held = this.held;
		for (let slot = 0; slot < this.slots; slot++) held[slot] = y[this.base + slot];
		const same = t === this.lastT;
		let record = !same;
		if (same) {
			for (let slot = 0; slot < this.slots; slot++) {
				// The same instant again: a jump of what is held is an amount
				// delivered at once, and a different inflow a step in it.
				const amount = held[slot] - this.lastHeld[slot];
				if (amount !== 0) {
					this.live[slot].impulse(t, amount);
					this.impulses[slot].history.t.push(t);
					this.impulses[slot].history.v.push(amount);
				}
				const rec = this.records[slot].history;
				if (IN[slot] !== rec.v[rec.v.length - 1]) record = true;
			}
		}
		// Every slot records every instant it records at all, so that the
		// records line up; an unchanged one at the same instant is no step.
		if (record) {
			for (let slot = 0; slot < this.slots; slot++) {
				const rec = this.records[slot].history;
				rec.t.push(t);
				rec.v.push(IN[slot]);
				this.live[slot].push(t, IN[slot]);
			}
		}
		if (!this.releases.has(t)) {
			const keep = new Float64Array(this.slots);
			for (let slot = 0; slot < this.slots; slot++) keep[slot] = X[this.releaseBase + this.dimOff[slot]];
			this.releases.set(t, keep);
		}
		this.lastHeld.set(held);
		this.lastT = t;
		this.histT = NaN;
		this.weightT = NaN;
		let blocks = 0;
		for (const cv of this.live) blocks += cv.bc.length;
		this.stats.blocks = blocks;
	}

	/** Forgets everything recorded after t. */
	_truncate(t) {
		for (const h of this.memory) {
			const { t: ts, v } = h.history;
			let k = ts.length;
			while (k > 0 && ts[k - 1] > t) k--;
			ts.length = k;
			v.length = k;
		}
		for (const key of [...this.releases.keys()]) if (key > t) this.releases.delete(key);
		this.live = this._convolvers();
		const times = this.records[0].history.t;
		for (let q = 0; q < times.length; q++) {
			for (let slot = 0; slot < this.slots; slot++) {
				const rec = this.records[slot].history;
				this.live[slot].push(rec.t[q], rec.v[q]);
			}
		}
		for (let slot = 0; slot < this.slots; slot++) {
			const imp = this.impulses[slot].history;
			for (let q = 0; q < imp.t.length; q++) this.live[slot].impulse(imp.t[q], imp.v[q]);
		}
		this.lastT = times.length ? times[times.length - 1] : -Infinity;
	}

	/** Release and decay out of what the path holds, added into the derivative. */
	apply(y, out, X, D) {
		const { nnuc, otherWidth, base } = this;
		for (let o = 0; o < otherWidth; o++) {
			const si = base + o * nnuc;
			for (let m = 0; m < nnuc; m++) {
				out[si + m] -= X[this.releaseBase + this.dimOff[o * nnuc + m]];
				if (!D) continue;
				out[si + m] -= D.lam[m] * y[si + m];
				const o0 = D.ioff[m];
				for (let q = 0; q < D.icnt[m]; q++) out[si + m] += D.icoef[o0 + q] * y[si + D.ipar[o0 + q]];
			}
		}
	}

	/** J*v for this block: the release's tangent out, and decay. */
	jvp(y, v, dout, X, dX, D) {
		const { nnuc, otherWidth, base } = this;
		for (let o = 0; o < otherWidth; o++) {
			const si = base + o * nnuc;
			for (let m = 0; m < nnuc; m++) {
				dout[si + m] -= dX[this.releaseBase + this.dimOff[o * nnuc + m]];
				if (!D) continue;
				dout[si + m] -= D.lam[m] * v[si + m];
				const o0 = D.ioff[m];
				for (let q = 0; q < D.icnt[m]; q++) dout[si + m] += D.icoef[o0 + q] * v[si + D.ipar[o0 + q]];
			}
		}
	}

	/**
	 * The tangent of the release: the weight of each source's current inflow,
	 * times that inflow's own tangent. Zero while the step is shorter than
	 * the time anything takes to come through.
	 */
	releaseTangent(y, v, X, dX, t = NaN) {
		const n = this.nnuc;
		const W = this._weights(t);
		this.DIN.fill(0);
		const any = W.cur.some((w) => w !== 0);
		if (any) this.inflowTangentFn?.(y, v, X, dX, this.DIN);
		for (let slot = 0; slot < this.slots; slot++) {
			const o = Math.floor(slot / n);
			let d = 0;
			if (any) {
				for (let j = 0; j < n; j++) d += W.cur[slot * n + j] * this.DIN[o * n + j];
			}
			dX[this.releaseBase + this.dimOff[slot]] = d;
		}
	}

	/**
	 * The (row, column) pairs this block can fill: decay within what is held,
	 * and everything the release reads -- the inflow's own columns.
	 */
	pattern(PAT, SX, D) {
		const { nnuc, otherWidth, base } = this;
		for (let o = 0; o < otherWidth; o++) {
			const si = base + o * nnuc;
			for (let m = 0; m < nnuc; m++) {
				PAT(si + m, si + m);
				if (D) {
					const o0 = D.ioff[m];
					for (let q = 0; q < D.icnt[m]; q++) PAT(si + m, si + D.ipar[o0 + q]);
				}
				for (const c of SX[this.releaseBase + this.dimOff[o * nnuc + m]]) PAT(si + m, c);
			}
		}
	}

	/**
	 * The columns the release depends on: what the inflow into the same
	 * combination reads, since the step being taken carries it with a weight.
	 */
	releasePattern(SX) {
		const COLS = Array.from({ length: this.slots }, () => new Set());
		this.inflowColumnsFn?.(SX, COLS);
		const { nnuc, otherWidth } = this;
		for (let o = 0; o < otherWidth; o++) {
			const cols = new Set();
			for (let j = 0; j < nnuc; j++) for (const c of COLS[o * nnuc + j]) cols.add(c);
			for (let m = 0; m < nnuc; m++) {
				const s = SX[this.releaseBase + this.dimOff[o * nnuc + m]];
				for (const c of cols) s.add(c);
			}
		}
	}
}

/** Forgets every response kept, for a test that wants to measure the first. */
export function clearResponses() {
	RESPONSES.clear();
}

/** For the tests: the pieces the release is made of. */
export const _internal = { makeKernel, Convolver, stepWeights, stepSum, kernelAt, runningMoments };
