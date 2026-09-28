/**
 * The far-field path solved in the Laplace domain: the semi-analytical
 * alternative to the cells of ./farfield.js.
 *
 * WHAT IS SOLVED. The same path, from the same settings: advection and
 * dispersion along the fracture, written in water travel time (TW) and Peclet
 * number (Pe); equilibrium sorption on the fracture coating (Kd,f); diffusion
 * into the rock matrix beside it, which holds the nuclide in its pore water
 * and on its surfaces (eps_m, rho_m, Kd,m, De,m); decay and ingrowth
 * everywhere, along the model's own decay network. With constant settings the
 * path is linear and time-invariant, so everything it does is in its unit
 * responses: what comes out, and what it holds, after one unit of one nuclide
 * went in at time zero.
 *
 * THE EQUATIONS. With zeta the distance along the path measured in water
 * travel time (0 ... TW), c the concentration in the flowing water and cp the
 * one in the matrix pore water, 0 <= x <= x0 (x0 = PENDEP):
 *
 *   Rf_i dc_i/dt = -dc_i/dzeta + (TW/Pe) d2c_i/dzeta2 + aw De_i dcp_i/dx|x=0
 *                  - lambda_i Rf_i c_i + sum_j k_ij Rf_j c_j,
 *   Rm_i dcp_i/dt = De_i d2cp_i/dx2 - lambda_i Rm_i cp_i + sum_j k_ij Rm_j cp_j,
 *
 * with aw = F/TW, Rf = 1 + Kd,f aw (the fracture coating: f_df = 1/Rf is the
 * dissolved fraction of ./farfield.js), Rm = eps_m + rho_m Kd,m, and k_ij the
 * ingrowth coefficient from parent j to daughter i exactly as the cells use it
 * (the builder's decay table: branching times the parent's decay constant for
 * amounts, times the daughter's for activities). cp = c at x = 0, no flux at
 * x = x0 (x0 may be infinite), the inflow is a flux at zeta = 0, the water
 * beyond the path is semi-infinite, and the release is the same flux at
 * zeta = TW -- FARF31's model (Norman and Kjellbert 1990, SKB TR 90-01;
 * summarised in SKB R-04-51, section 3), with the fracture coating and a
 * general decay network added.
 *
 * THE SOLUTION. Transforming in t (variable s), with Lambda the decay matrix
 * (lambda_i on the diagonal, -k_ij below it: lower triangular once the
 * nuclides are ordered parents first), A = sI + Lambda and Rf, Rm, De
 * diagonal:
 *
 *   M = De^-1 A Rm,     tau(z) = sqrt(z) tanh(x0 sqrt(z))  (sqrt(z) for x0 = inf),
 *   G = A Rf + aw De tau(M),
 *   T(s) = H(G),        H(g) = exp((Pe/2) (1 - sqrt(1 + 4 TW g/Pe)))
 *                       (exp(-TW g) for plug flow, Pe = inf).
 *
 * T_ij is the transform of h_ij, the release of i after a unit pulse of j. The
 * path's inventory follows from the mass balance, d(Inv)/dt = in - out -
 * Lambda Inv, whose transform is
 *
 *   K(s) = A^-1 (I - T(s)),
 *
 * the transform of k_ij, what the path holds of i after a unit pulse of j.
 * K has no poles at s = -lambda: they cancel (I - T vanishes there with A),
 * so the contours are only kept off those points. Inverted whole, K is two
 * terms with different saddles, though, and while the path still holds most
 * of a pulse k is taken as e^(-Lambda t) -- the Bateman solution, a function
 * of the triangular Lambda like the others -- less the inverse of A^-1 T: see
 * `sampleInventory`.
 *
 * PROVENANCE. The page FARF31.html solves the same transform for unbranched
 * chains without the coating; its model (resources/js/farf31-model.js in this
 * repository) was written from the public reports alone, and everything
 * numerical here is adapted from it:
 *
 *   - tau(M) and H(G) as functions of triangular matrices: Parlett's
 *     recurrence when the diagonal is well separated, otherwise sums over the
 *     decay paths of products of off-diagonal entries and divided differences,
 *     those of close points from Taylor series about the cluster's centre --
 *     so two nuclides of one element with close or equal decay constants lose
 *     nothing. Here M and G are general lower-triangular matrices (branching,
 *     and several parents), restricted for each pair (i, j) to the nuclides on
 *     some decay path from j to i;
 *   - inversion along a parabola through the saddle point of e^(st) T(s) on
 *     the real axis, with Talbot's contour and de Hoog's method as checks.
 *     One change: the halvings of the trapezoidal step also stop only once
 *     the nearest singularity's own error bound is met (see
 *     `invertParabola`), which the page's rule -- that each halving squares
 *     the error -- missed next to a pole;
 *   - the shared contours: nearby times summed from the nodes of one
 *     parabola, the times of each axis divided into cells on a lattice in
 *     ln t taken from its real-axis table alone, and a time its cell cannot
 *     serve given a parabola of its own (see `makeCells`);
 *   - under plug flow the pair's delay taken out of each member's exponent as
 *     it is formed, not subtracted after (see `gFracture`), and the step
 *     following the members' own phase rates there as elsewhere; nodes
 *     spaced as c sinh(u) where a weak singularity next to the saddle makes
 *     the strip of analyticity far narrower than the integrand (see
 *     `nodeScale`); the real-axis table reaching to before a sharp front's
 *     rising edge (see `realAxis`);
 *   - each response sampled with its first two derivatives (the inversions of
 *     s T and s^2 T come free) on an adaptive grid, interpolated by quintic
 *     Hermite pieces;
 *   - the exact convolution of a piecewise-linear inflow with those pieces.
 *
 * WHAT IT DOES NOT DO. The discretisation's own settings (PENDEP0, NF, NM, NB,
 * the layer grid) mean nothing here: there are no cells. The outlet is
 * semi-infinite, as in FARF31 -- the rock goes on past the release point,
 * which the cells approach with extra cells beyond it -- and not one of the
 * reference implementation's four conditions, which close the path at the
 * release point (OB = 1, the closed Danckwerts outlet, releases 4a/(1+a)^2 of
 * this at a = sqrt(1 + 4 TW g/Pe)). Settings must be constants: a path whose
 * travel time follows the clock or a compartment is not time-invariant, and
 * has no transfer function.
 *
 * UNITS. The model's own time unit throughout, as in ./farfield.js: TW in
 * [time], F in [time] m2/m3, De in m2/[time], decay constants in 1/[time].
 *
 * The Python engine carries the same algorithms in
 * python/kompartment/engine/farfield_laplace.py; the two agree to rounding.
 */

/** A path this method cannot solve, and why. */
export class LaplacePathError extends Error {
	constructor(message) {
		super(message);
		this.name = 'LaplacePathError';
	}
}

/** The largest set of nuclides one pair's transform couples. */
export const MAX_BLOCK = 16;

/** Which transform: what leaves the path, or what it holds. */
export const KINDS = ['release', 'inventory'];

const RELEASE = 0;
// What the path holds: K = A^-1 (I - T), inverted whole where most of a
// pulse has left, and otherwise as e^(-Lambda t) minus the inverse of
// A^-1 T -- the decayed cumulative release, DECAYED -- which has a saddle of
// its own. See `sampleInventory`.
const INVENTORY = 1;
const DECAYED = 2;
const PI = Math.PI;

/* ==========================================================================
   Complex arithmetic on two registers, so the hot loops allocate nothing
   ========================================================================== */

let RE = 0;
let IM = 0;
// pathFrequency's fastest phase rate per unit u of sinh nodes (see nodeScale)
let RATE_U = 0;

function cdiv(ar, ai, br, bi) {
	if (Math.abs(br) >= Math.abs(bi)) {
		const r = bi / br;
		const d = br + bi * r;
		RE = (ar + ai * r) / d;
		IM = (ai - ar * r) / d;
	} else {
		const r = br / bi;
		const d = bi + br * r;
		RE = (ar * r + ai) / d;
		IM = (ai * r - ar) / d;
	}
}

/** The principal square root; the cut is the negative real axis. */
function csqrt(ar, ai) {
	if (ai === 0) {
		if (ar >= 0) { RE = Math.sqrt(ar); IM = 0; } else { RE = 0; IM = Math.sqrt(-ar); }
		return;
	}
	const m = Math.hypot(ar, ai);
	if (ar >= 0) {
		const t = Math.sqrt(0.5 * (m + ar));
		RE = t;
		IM = ai / (2 * t);
	} else {
		const t = Math.sqrt(0.5 * (m - ar));
		RE = Math.abs(ai) / (2 * t);
		IM = ai >= 0 ? t : -t;
	}
}

function cexp(ar, ai) {
	const e = Math.exp(ar);
	RE = e * Math.cos(ai);
	IM = e * Math.sin(ai);
}

/** tanh, accurate for small arguments and safe for large ones. */
function ctanh(ar, ai) {
	let sg = 1;
	if (ar < 0) { ar = -ar; ai = -ai; sg = -1; }
	if (ar > 18) {
		const e = 2 * Math.exp(-2 * ar);
		RE = sg * (1 - e * Math.cos(2 * ai));
		IM = sg * (e * Math.sin(2 * ai));
		return;
	}
	const d = Math.cosh(2 * ar) + Math.cos(2 * ai);
	RE = sg * Math.sinh(2 * ar) / d;
	IM = sg * Math.sin(2 * ai) / d;
}

/** sech^2 = 1 - tanh^2, without the cancellation near tanh = 1. */
function csech2(ar, ai) {
	if (ar < 0) { ar = -ar; ai = -ai; }
	const e1 = Math.exp(-ar);
	const e2 = e1 * e1;
	const wr = e2 * Math.cos(2 * ai);
	const wi = -e2 * Math.sin(2 * ai);
	const nr = 2 * e1 * Math.cos(ai);
	const ni = -2 * e1 * Math.sin(ai);
	cdiv(nr, ni, 1 + wr, wi);
	const sr = RE;
	const si = IM;
	RE = sr * sr - si * si;
	IM = 2 * sr * si;
}

/* ==========================================================================
   The settings, checked and turned into per-nuclide constants
   ========================================================================== */

/** The per-nuclide settings, in the order ./farfield.js lists them. */
const NUCLIDE_KEYS = ['kd_f', 'eps_m', 'kd_m', 'de_m'];

function isList(v) {
	return Array.isArray(v) || ArrayBuffer.isView(v);
}

/**
 * A decay table in the builder's layout -- `{lam, ioff, icnt, ipar, icoef}`,
 * what `decayTables` in ../sim/builder.js hands a path at run time -- from
 * decay constants and (parent, daughter, coefficient) triples. The
 * coefficient is the ingrowth coefficient itself: branching times the
 * parent's decay constant when the model holds amounts.
 *
 * @param {ArrayLike<number>} lambdas
 * @param {Array<[number, number, number]>} pairs
 */
export function decayTable(lambdas, pairs = []) {
	const n = lambdas.length;
	const byDaughter = Array.from({ length: n }, () => []);
	for (const [p, d, c] of pairs) byDaughter[d].push([p, c]);
	const ioff = new Int32Array(n);
	const icnt = new Int32Array(n);
	const ipar = [];
	const icoef = [];
	for (let k = 0; k < n; k++) {
		ioff[k] = ipar.length;
		for (const [p, c] of byDaughter[k]) { ipar.push(p); icoef.push(c); }
		icnt[k] = byDaughter[k].length;
	}
	return {
		lam: Float64Array.from(lambdas), ioff, icnt,
		ipar: Int32Array.from(ipar), icoef: Float64Array.from(icoef),
	};
}

/**
 * A path, ready to be solved.
 *
 * `settings` holds the block's settings as numbers: `tw`, `rho_m`, `pe` and
 * `pen_dep` once for the path, and `kd_f`, `eps_m`, `kd_m`, `de_m` either
 * once or one per nuclide. The wetted surface is given as the block gives it:
 * `surface` 'f' (the default) reads F and a_w = F/TW, 'aw' reads a_w, and
 * 'aperture' reads the aperture delta, a_w = 2/delta. `pe` and `pen_dep` may
 * be Infinity (plug flow, an unlimited matrix). The discretisation's settings
 * are ignored.
 *
 * `decay` is the builder's decay table for the path's nuclide list, or null
 * for species that neither decay nor grow in.
 *
 * @param {object} settings
 * @param {object|null} decay
 * @param {{n?: number, names?: string[]}} options
 */
export function preparePath(settings, decay = null, options = {}) {
	let n = options.n ?? null;
	if (n == null && decay) n = decay.lam.length;
	if (n == null) {
		for (const key of NUCLIDE_KEYS) if (isList(settings[key])) n = settings[key].length;
	}
	n ??= 1;
	if (!(n >= 1)) throw new LaplacePathError('A path needs at least one species to carry.');
	const names = options.names ?? Array.from({ length: n }, (_, k) => `#${k + 1}`);
	const one = (key) => {
		const v = Number(settings[key]);
		if (Number.isNaN(v)) throw new LaplacePathError(`${key} must be a number (got ${settings[key]})`);
		return v;
	};
	const each = (key) => {
		const v = settings[key];
		const out = new Float64Array(n);
		for (let k = 0; k < n; k++) {
			out[k] = Number(isList(v) ? v[k] : v);
			if (!Number.isFinite(out[k]) || out[k] < 0) {
				throw new LaplacePathError(
					`${key} of ${names[k]} must be zero or a positive number (got ${isList(v) ? v[k] : v})`,
				);
			}
		}
		return out;
	};
	const tw = one('tw');
	const rho = one('rho_m');
	const Pe = one('pe');
	const x0 = one('pen_dep');
	if (!(tw > 0) || !Number.isFinite(tw)) {
		throw new LaplacePathError(`The travel time TW must be a positive number (got ${tw})`);
	}
	const surface = settings.surface ?? 'f';
	let aw;
	if (surface === 'aw') {
		aw = one('aw');
		if (!(aw >= 0) || !Number.isFinite(aw)) {
			throw new LaplacePathError(`The flow-wetted surface a_w must be zero or positive (got ${aw})`);
		}
	} else if (surface === 'aperture') {
		const delta = one('aperture');
		if (!(delta > 0)) throw new LaplacePathError(`The fracture aperture must be a positive length (got ${delta})`);
		aw = 2 / delta;
	} else if (surface === 'f') {
		const f0 = one('f');
		if (!(f0 >= 0) || !Number.isFinite(f0)) {
			throw new LaplacePathError(`The flow-related transport resistance F must be zero or positive (got ${f0})`);
		}
		aw = f0 / tw;
	} else {
		throw new LaplacePathError(`Unknown way of giving the wetted surface '${surface}'`);
	}
	const f = aw * tw;
	if (!(Pe > 0)) {
		throw new LaplacePathError(`The Peclet number must be greater than zero (got ${Pe})`);
	}
	if (!(x0 > 0)) {
		throw new LaplacePathError(`The depth into the matrix must be a positive length, or Infinity (got ${x0})`);
	}
	if (!(rho >= 0) || !Number.isFinite(rho)) {
		throw new LaplacePathError(`The rock density must be zero or positive (got ${rho})`);
	}
	const kdF = each('kd_f');
	const eps = each('eps_m');
	const kdM = each('kd_m');
	const De = each('de_m');
	const Rf = new Float64Array(n);
	const Rm = new Float64Array(n);
	const matrix = new Uint8Array(n);
	for (let k = 0; k < n; k++) {
		Rf[k] = 1 + kdF[k] * aw;
		Rm[k] = eps[k] + rho * kdM[k];
		if (aw > 0 && De[k] > 0 && !(Rm[k] > 0)) {
			throw new LaplacePathError(
				`The matrix capacity eps + rho*Kd of ${names[k]} must be greater than zero: `
				+ 'a rock with no porosity and no sorption has nothing for it to diffuse into.',
			);
		}
		matrix[k] = aw > 0 && De[k] > 0 ? 1 : 0;
	}

	// The decay network, as the cells see it.
	const lam = new Float64Array(n);
	const parents = Array.from({ length: n }, () => []);
	if (decay) {
		if (decay.lam.length < n) throw new LaplacePathError('The decay table is shorter than the nuclide list.');
		for (let i = 0; i < n; i++) {
			lam[i] = decay.lam[i];
			if (!Number.isFinite(lam[i]) || lam[i] < 0) {
				throw new LaplacePathError(`The decay constant of ${names[i]} must be zero or positive (got ${lam[i]})`);
			}
			const o = decay.ioff[i];
			for (let q = 0; q < decay.icnt[i]; q++) {
				const p = decay.ipar[o + q];
				const c = decay.icoef[o + q];
				if (!Number.isFinite(c) || c < 0) {
					throw new LaplacePathError(`The ingrowth of ${names[i]} from ${names[p]} must be zero or positive (got ${c})`);
				}
				if (c === 0) continue;
				if (p === i) throw new LaplacePathError(`${names[i]} is its own parent.`);
				const had = parents[i].find((e) => e[0] === p);
				if (had) had[1] += c; else parents[i].push([p, c]);
			}
		}
	}
	// Parents first: Kahn's algorithm, lowest index first, so the order does
	// not depend on anything but the list.
	const indeg = new Int32Array(n);
	const children = Array.from({ length: n }, () => []);
	for (let i = 0; i < n; i++) {
		for (const [p] of parents[i]) { children[p].push(i); indeg[i]++; }
	}
	const order = [];
	const taken = new Uint8Array(n);
	for (let round = 0; round < n; round++) {
		let pick = -1;
		for (let k = 0; k < n; k++) if (!taken[k] && indeg[k] === 0) { pick = k; break; }
		if (pick < 0) break;
		taken[pick] = 1;
		order.push(pick);
		for (const c of children[pick]) indeg[c]--;
	}
	if (order.length < n) {
		throw new LaplacePathError('The decay network closes on itself, so it has no order to solve it in.');
	}
	const pos = new Int32Array(n);
	order.forEach((k, p) => { pos[k] = p; });
	// reach[j][k]: k is j or one of its descendants.
	const reach = Array.from({ length: n }, () => new Uint8Array(n));
	for (let p = n - 1; p >= 0; p--) {
		const k = order[p];
		reach[k][k] = 1;
		for (const c of children[k]) for (let l = 0; l < n; l++) if (reach[c][l]) reach[k][l] = 1;
	}
	// A nuclide that does not enter the matrix, linked to one that does,
	// would sit in the matrix where its parent put it, without a way out:
	// an algebraic member the matrix functions do not describe.
	for (let i = 0; i < n; i++) {
		for (const [p] of parents[i]) {
			if (matrix[p] !== matrix[i]) {
				const [inside, outside] = matrix[p] ? [names[p], names[i]] : [names[i], names[p]];
				throw new LaplacePathError(
					`${outside} does not diffuse into the matrix (De = 0) while ${inside}, which it `
					+ `decays ${matrix[p] ? 'from' : 'into'}, does: give it a small De, or use the `
					+ 'discretised path.',
				);
			}
		}
	}
	const infPe = !Number.isFinite(Pe);
	if (infPe) {
		for (let k = 0; k < n; k++) {
			if (!matrix[k]) {
				throw new LaplacePathError(
					`Plug flow (Pe = Infinity) needs matrix diffusion for every nuclide: without it ${names[k]} `
					+ 'leaves as a pulse with no width at all.',
				);
			}
		}
	}
	let maxBlock = 1;
	for (let j = 0; j < n; j++) {
		for (let i = 0; i < n; i++) {
			if (i === j || !reach[j][i]) continue;
			let m = 0;
			for (let k = 0; k < n; k++) if (reach[j][k] && reach[k][i]) m++;
			if (m > MAX_BLOCK) {
				throw new LaplacePathError(
					`${m} nuclides lie on the decay paths from ${names[j]} to ${names[i]}; at most `
					+ `${MAX_BLOCK} can be solved together.`,
				);
			}
			if (m > maxBlock) maxBlock = m;
		}
	}
	const path = {
		n, names, tw, f, Pe, infPe, aw, x0, infX0: !Number.isFinite(x0), rho,
		lam, Rf, Rm, De, matrix, parents, order, pos, reach, maxBlock,
		blocks: new Map(),
		ws: null,
	};
	path.ws = makeWorkspace(maxBlock);
	return path;
}

/* ==========================================================================
   The two scalar functions, their Taylor series and length scales

   tau(z) = sqrt(z) tanh(x0 sqrt(z)) is the flux into the matrix per unit
   concentration, over De; H(g) = exp(phi(g)) with phi the fracture exponent.
   For divided differences each needs a scale: points closer than a fraction
   of it are a cluster (Taylor series about the centre), since their
   difference quotients would cancel.
   ========================================================================== */

/** tau at z, into RE/IM. */
function tauAt(path, zr, zi) {
	csqrt(zr, zi);
	if (path.infX0) return;
	const ur = RE;
	const ui = IM;
	ctanh(path.x0 * ur, path.x0 * ui);
	const tr = RE;
	const ti = IM;
	RE = ur * tr - ui * ti;
	IM = ur * ti + ui * tr;
}

/** tau's length scale at z: the distance to the branch point of sqrt and to
    the nearest pole of tanh(x0 sqrt z), z_n = -((n + 1/2) pi/x0)^2. */
function tauScale(path, zr, zi) {
	let sc = Math.hypot(zr, zi);
	if (!path.infX0) {
		const a = PI / path.x0;
		let n0 = 0;
		if (zr < 0) n0 = Math.max(0, Math.floor(Math.sqrt(-zr) / a - 0.5));
		for (let n = Math.max(0, n0 - 1); n <= n0 + 1; n++) {
			const zp = -((n + 0.5) * a) * ((n + 0.5) * a);
			const d = Math.hypot(zr - zp, zi);
			if (d < sc) sc = d;
		}
	}
	return sc;
}

/**
 * phi(g) into RE/IM: (Pe/2)(1 - sqrt(1 + 4 TW g/Pe)) written without the
 * cancellation. Under plug flow phi = -TW g, g then the shifted exponent g -
 * Rmin s wherever the transform has its delay e^(-TW Rmin s) taken out and
 * applied as a shift in time (see gFracture).
 */
function phiAt(path, gr, gi) {
	const tw = path.tw;
	if (path.infPe) { RE = -tw * gr; IM = -tw * gi; return; }
	const B = 4 * tw / path.Pe;
	csqrt(1 + B * gr, B * gi);
	cdiv(-2 * tw * gr, -2 * tw * gi, 1 + RE, IM);
}

/**
 * The fracture's part of member p's g at s into RE/IM: Rf_p (s + lambda_p),
 * less d s when the pair's transform has the delay e^(-TW d s) taken out (d =
 * Rmin, the block's smallest Rf, under plug flow; 0 otherwise). What is formed
 * then is the shifted exponent Rf_p lambda_p + (Rf_p - d) s, directly: forming
 * Rf_p (s + lambda_p) and subtracting d s would leave the small remainder with
 * the rounding of the large terms, and right after the delay, where the
 * saddles lie at s of order 1/(t - delay), the transform lost up to eight
 * digits so. Rf_p - d is zero, or the member's own delay beyond the pair's.
 */
function gFracture(blk, p, sr, si, d) {
	const rf = blk.Rf[p];
	if (d > 0) {
		const e = rf - d;
		RE = rf * blk.lam[p] + e * sr;
		IM = e * si;
	} else {
		RE = (sr + blk.lam[p]) * rf;
		IM = si * rf;
	}
}

/** H's length scale at g: 1/|phi'| and the distance to the branch point
    g* = -Pe/(4 TW), whichever is smaller. */
function hScale(path, gr, gi) {
	const tw = path.tw;
	if (path.infPe) return 1 / tw;
	const B = 4 * tw / path.Pe;
	const S = Math.sqrt(Math.hypot(1 + B * gr, B * gi));
	return Math.min(S / tw, S * S / B);
}

const SERIES_MAX = 262;

const BINOM_HALF = (() => {
	const b = new Float64Array(260);
	b[0] = 1;
	for (let n = 1; n < b.length; n++) b[n] = b[n - 1] * (0.5 - (n - 1)) / n;
	return b;
})();

/** Taylor coefficients of sqrt(A + B w) about w = 0, into cr/ci[0..K]. */
function sqrtSeries(Ar, Ai, Br, Bi, K, cr, ci) {
	csqrt(Ar, Ai);
	const s0r = RE;
	const s0i = IM;
	cdiv(Br, Bi, Ar, Ai);
	const qr = RE;
	const qi = IM;
	let pr = s0r;
	let pi = s0i;
	for (let n = 0; n <= K; n++) {
		cr[n] = BINOM_HALF[n] * pr;
		ci[n] = BINOM_HALF[n] * pi;
		const t = pr * qr - pi * qi;
		pi = pr * qi + pi * qr;
		pr = t;
	}
}

/** Taylor coefficients of tau(c + w). s1..s3 are scratch. */
function tauSeries(path, cr0, ci0, K, outR, outI, s1r, s1i, s2r, s2i, s3r, s3i) {
	sqrtSeries(cr0, ci0, 1, 0, K, s1r, s1i);
	if (path.infX0) {
		for (let n = 0; n <= K; n++) { outR[n] = s1r[n]; outI[n] = s1i[n]; }
		return;
	}
	const x0 = path.x0;
	// T = tanh(x0 u): T' = (1 - T^2) x0 u'. s2 = T, s3 = Q = 1 - T^2.
	ctanh(x0 * s1r[0], x0 * s1i[0]);
	s2r[0] = RE;
	s2i[0] = IM;
	csech2(x0 * s1r[0], x0 * s1i[0]);
	s3r[0] = RE;
	s3i[0] = IM;
	for (let n = 1; n <= K; n++) {
		let ar = 0;
		let ai = 0;
		for (let k = 1; k <= n; k++) {
			const vr = k * x0 * s1r[k];
			const vi = k * x0 * s1i[k];
			const qr = s3r[n - k];
			const qi = s3i[n - k];
			ar += vr * qr - vi * qi;
			ai += vr * qi + vi * qr;
		}
		s2r[n] = ar / n;
		s2i[n] = ai / n;
		let br = 0;
		let bi = 0;
		for (let k = 0; k <= n; k++) {
			br += s2r[k] * s2r[n - k] - s2i[k] * s2i[n - k];
			bi += s2r[k] * s2i[n - k] + s2i[k] * s2r[n - k];
		}
		s3r[n] = -br;
		s3i[n] = -bi;
	}
	for (let n = 0; n <= K; n++) {
		let ar = 0;
		let ai = 0;
		for (let k = 0; k <= n; k++) {
			ar += s1r[k] * s2r[n - k] - s1i[k] * s2i[n - k];
			ai += s1r[k] * s2i[n - k] + s1i[k] * s2r[n - k];
		}
		outR[n] = ar;
		outI[n] = ai;
	}
}

/** Taylor coefficients of exp(phi(c + w) + E) (under plug flow c is a
    shifted exponent, see phiAt). */
function hSeries(path, cr0, ci0, E, K, outR, outI, s1r, s1i) {
	const tw = path.tw;
	if (path.infPe) {
		for (let n = 0; n <= K; n++) { s1r[n] = 0; s1i[n] = 0; }
		s1r[0] = -tw * cr0;
		s1i[0] = -tw * ci0;
		if (K >= 1) s1r[1] = -tw;
	} else {
		const B = 4 * tw / path.Pe;
		const half = path.Pe / 2;
		sqrtSeries(1 + B * cr0, B * ci0, B, 0, K, s1r, s1i);
		for (let n = 1; n <= K; n++) { s1r[n] *= -half; s1i[n] *= -half; }
		phiAt(path, cr0, ci0);
		s1r[0] = RE;
		s1i[0] = IM;
	}
	cexp(s1r[0] + E, s1i[0]);
	outR[0] = RE;
	outI[0] = IM;
	for (let n = 1; n <= K; n++) {
		let ar = 0;
		let ai = 0;
		for (let k = 1; k <= n; k++) {
			const pr = k * s1r[k];
			const pi = k * s1i[k];
			const hr = outR[n - k];
			const hi = outI[n - k];
			ar += pr * hr - pi * hi;
			ai += pr * hi + pi * hr;
		}
		outR[n] = ar / n;
		outI[n] = ai / n;
	}
}

/* ==========================================================================
   Divided differences over subsets of points, robust for clusters

   f[z_S] for a set S (a bit mask over the points). A set whose points all lie
   in one cluster uses the Taylor series about the cluster's centre c:

      f[z_0..z_m] = sum_(n>=m) f_n h_(n-m)(z_0 - c, ..., z_m - c),

   h_k the complete homogeneous symmetric polynomial. Any other set is split
   at two separated points (a, b): f[S] = (f[S\a] - f[S\b]) / (z_b - z_a).
   ========================================================================== */

const LINK_FRAC = 0.3;
const TAYLOR_FRAC = 0.5;

function makeDD(nmax) {
	const size = 1 << nmax;
	const dd = {
		n: 0, kind: 0, E: 0, t: 0,
		zr: new Float64Array(nmax), zi: new Float64Array(nmax),
		fr: new Float64Array(nmax), fi: new Float64Array(nmax),
		sc: new Float64Array(nmax), cl: new Int32Array(nmax), seen: new Int32Array(nmax),
		dist: new Float64Array(nmax * nmax),
		memoR: new Float64Array(size), memoI: new Float64Array(size), memoG: new Uint32Array(size),
		gen: 1,
		ncl: 0, clMask: new Int32Array(nmax), clCr: new Float64Array(nmax), clCi: new Float64Array(nmax),
		clOk: new Uint8Array(nmax), clK: new Int32Array(nmax),
		clCoefR: [], clCoefI: [],
		s1r: new Float64Array(SERIES_MAX), s1i: new Float64Array(SERIES_MAX),
		s2r: new Float64Array(SERIES_MAX), s2i: new Float64Array(SERIES_MAX),
		s3r: new Float64Array(SERIES_MAX), s3i: new Float64Array(SERIES_MAX),
		hR: new Float64Array(SERIES_MAX), hI: new Float64Array(SERIES_MAX),
	};
	for (let k = 0; k < nmax; k++) {
		dd.clCoefR.push(new Float64Array(SERIES_MAX));
		dd.clCoefI.push(new Float64Array(SERIES_MAX));
	}
	return dd;
}

/* The functions divided differences are taken of: 0 is tau, 1 is H, 2 is
   exp(-t z), whose matrix function is the Bateman solution e^(-Lambda t). */

function ddScale(path, dd, zr, zi) {
	if (dd.kind === 0) return tauScale(path, zr, zi);
	if (dd.kind === 1) return hScale(path, zr, zi);
	return 1 / dd.t;
}

function ddSeries(path, dd, cr, ci, K, outR, outI) {
	if (dd.kind === 0) tauSeries(path, cr, ci, K, outR, outI, dd.s1r, dd.s1i, dd.s2r, dd.s2i, dd.s3r, dd.s3i);
	else if (dd.kind === 1) hSeries(path, cr, ci, dd.E, K, outR, outI, dd.s1r, dd.s1i);
	else expSeries(dd.t, cr, ci, K, outR, outI);
}

/** Taylor coefficients of exp(-t (c + w)): e^(-t c) (-t)^n/n!. */
function expSeries(t, cr, ci, K, outR, outI) {
	cexp(-t * cr, -t * ci);
	outR[0] = RE;
	outI[0] = IM;
	for (let n = 1; n <= K; n++) {
		outR[n] = outR[n - 1] * (-t / n);
		outI[n] = outI[n - 1] * (-t / n);
	}
}

/** Sets up n points (values already in fr/fi) and finds the clusters.
    False when there are none: a plain recurrence is then safe. */
function ddSetup(path, dd, n) {
	dd.n = n;
	dd.gen++;
	if (dd.gen > 4e9) { dd.memoG.fill(0); dd.gen = 1; }
	for (let k = 0; k < n; k++) { dd.sc[k] = ddScale(path, dd, dd.zr[k], dd.zi[k]); dd.cl[k] = k; }
	let any = false;
	for (let a = 0; a < n; a++) {
		for (let b = a + 1; b < n; b++) {
			const dx = dd.zr[a] - dd.zr[b];
			const dy = dd.zi[a] - dd.zi[b];
			const d = Math.sqrt(dx * dx + dy * dy);
			dd.dist[a * n + b] = d;
			dd.dist[b * n + a] = d;
			if (d <= LINK_FRAC * Math.min(dd.sc[a], dd.sc[b])) {
				any = true;
				const ca = dd.cl[a];
				const cb = dd.cl[b];
				if (ca !== cb) for (let k = 0; k < n; k++) if (dd.cl[k] === cb) dd.cl[k] = ca;
			}
		}
	}
	dd.ncl = 0;
	if (!any) return false;
	const seen = dd.seen;
	for (let k = 0; k < n; k++) seen[k] = -1;
	for (let k = 0; k < n; k++) {
		const root = dd.cl[k];
		if (seen[root] < 0) { seen[root] = dd.ncl; dd.clMask[dd.ncl] = 0; dd.ncl++; }
		const c = seen[root];
		dd.cl[k] = c;
		dd.clMask[c] |= 1 << k;
	}
	for (let c = 0; c < dd.ncl; c++) { dd.clOk[c] = 0; dd.clK[c] = -1; }
	return true;
}

/** f[z_mask] into RE/IM. */
function ddGet(path, dd, mask) {
	if (dd.memoG[mask] === dd.gen) { RE = dd.memoR[mask]; IM = dd.memoI[mask]; return; }
	const n = dd.n;
	const lo = 31 - Math.clz32(mask & -mask);
	const hi = 31 - Math.clz32(mask);
	let vr;
	let vi;
	if (lo === hi) {
		vr = dd.fr[lo];
		vi = dd.fi[lo];
	} else {
		let c0 = dd.ncl ? dd.cl[lo] : -1;
		let cnt = 0;
		for (let m = mask; m; m &= m - 1) {
			cnt++;
			if (c0 >= 0 && dd.cl[31 - Math.clz32(m & -m)] !== c0) c0 = -1;
		}
		if (c0 >= 0 && ddTaylor(path, dd, mask, cnt, c0)) {
			vr = RE;
			vi = IM;
		} else {
			// Split at two separated points: the ends of the set when they are
			// in different clusters, else the end and the point farthest from
			// it outside its cluster, else the farthest pair of a wide cluster.
			let a = lo;
			let b = hi;
			if (dd.ncl && dd.cl[a] === dd.cl[b]) {
				let bd = -1;
				let bb = -1;
				for (let m = mask; m; m &= m - 1) {
					const k = 31 - Math.clz32(m & -m);
					if (dd.cl[k] !== dd.cl[a] && dd.dist[a * n + k] > bd) { bd = dd.dist[a * n + k]; bb = k; }
				}
				if (bb < 0) {
					for (let m = mask; m; m &= m - 1) {
						const p = 31 - Math.clz32(m & -m);
						for (let m2 = m & (m - 1); m2; m2 &= m2 - 1) {
							const q = 31 - Math.clz32(m2 & -m2);
							if (dd.dist[p * n + q] > bd) { bd = dd.dist[p * n + q]; a = p; bb = q; }
						}
					}
				}
				b = bb;
			}
			ddGet(path, dd, mask & ~(1 << a));
			const xr = RE;
			const xi = IM;
			ddGet(path, dd, mask & ~(1 << b));
			cdiv(xr - RE, xi - IM, dd.zr[b] - dd.zr[a], dd.zi[b] - dd.zi[a]);
			vr = RE;
			vi = IM;
		}
	}
	dd.memoR[mask] = vr;
	dd.memoI[mask] = vi;
	dd.memoG[mask] = dd.gen;
	RE = vr;
	IM = vi;
}

/** The Taylor form for a set inside cluster c; false when the cluster is too
    wide for its series (the caller then splits). */
function ddTaylor(path, dd, mask, cnt, c) {
	const m = cnt - 1;
	if (dd.clK[c] < 0) {
		const cm = dd.clMask[c];
		let cr = 0;
		let ci = 0;
		let k0 = 0;
		for (let k = 0; k < dd.n; k++) if (cm & (1 << k)) { cr += dd.zr[k]; ci += dd.zi[k]; k0++; }
		cr /= k0;
		ci /= k0;
		let rad = 0;
		for (let k = 0; k < dd.n; k++) {
			if (cm & (1 << k)) rad = Math.max(rad, Math.hypot(dd.zr[k] - cr, dd.zi[k] - ci));
		}
		const sc = ddScale(path, dd, cr, ci);
		const q = rad / sc;
		dd.clCr[c] = cr;
		dd.clCi[c] = ci;
		if (!(q <= TAYLOR_FRAC)) { dd.clOk[c] = 0; dd.clK[c] = 0; return false; }
		dd.clOk[c] = 1;
		// Terms beyond the order: q^j C(j+m, m) < 1e-17 for the largest m.
		const mmax = k0 - 1;
		let extra = 2;
		if (q > 0) {
			let term = 1;
			for (extra = 1; extra < 240; extra++) {
				term *= q * (extra + mmax) / extra;
				if (term < 1e-17 && extra > 2) break;
			}
		}
		const K = Math.min(255, mmax + extra + 2);
		dd.clK[c] = K;
		ddSeries(path, dd, cr, ci, K, dd.clCoefR[c], dd.clCoefI[c]);
	}
	if (!dd.clOk[c]) return false;
	const K = dd.clK[c];
	const cr = dd.clCr[c];
	const ci = dd.clCi[c];
	const L = K - m;
	const hR = dd.hR;
	const hI = dd.hI;
	hR[0] = 1;
	hI[0] = 0;
	for (let j = 1; j <= L; j++) { hR[j] = 0; hI[j] = 0; }
	for (let mm = mask; mm; mm &= mm - 1) {
		const k = 31 - Math.clz32(mm & -mm);
		const wr = dd.zr[k] - cr;
		const wi = dd.zi[k] - ci;
		for (let j = 1; j <= L; j++) {
			const pr = hR[j - 1];
			const pi = hI[j - 1];
			hR[j] += wr * pr - wi * pi;
			hI[j] += wr * pi + wi * pr;
		}
	}
	const fr = dd.clCoefR[c];
	const fi = dd.clCoefI[c];
	let sr = 0;
	let si = 0;
	for (let j = L; j >= 0; j--) {
		const ar = fr[m + j];
		const ai = fi[m + j];
		sr += ar * hR[j] - ai * hI[j];
		si += ar * hI[j] + ai * hR[j];
	}
	RE = sr;
	IM = si;
	return true;
}

/* ==========================================================================
   Functions of lower-triangular matrices

   f(L) for L lower triangular with diagonal z (the points in dd, values
   f(z_p) in dd.fr/fi) and strictly lower part (Lr, Li). Parlett's recurrence
   when no two diagonal entries are close; otherwise, entry by entry, the sum
   over the paths q = k0 < k1 < ... < kr = p through L's non-zero entries of
   prod L_(k_(l+1) k_l) f[z_k0 .. z_kr].
   ========================================================================== */

const NEED_ALL = 0;
const NEED_COLUMN = 1;
const NEED_CORNER = 2;

function triFun(path, ws, m, Lr, Li, Fr, Fi, need) {
	const dd = ws.dd;
	for (let p = 0; p < m; p++) { Fr[p * m + p] = dd.fr[p]; Fi[p * m + p] = dd.fi[p]; }
	if (m === 1) return;
	if (!ddSetup(path, dd, m)) {
		// F_pq (z_p - z_q) = L_pq (F_pp - F_qq) + sum_k (F_pk L_kq - L_pk F_kq)
		for (let d = 1; d < m; d++) {
			for (let q = 0; q + d < m; q++) {
				const p = q + d;
				const lr = Lr[p * m + q];
				const li = Li[p * m + q];
				const er = Fr[p * m + p] - Fr[q * m + q];
				const ei = Fi[p * m + p] - Fi[q * m + q];
				let ar = lr * er - li * ei;
				let ai = lr * ei + li * er;
				for (let k = q + 1; k < p; k++) {
					const g1r = Lr[p * m + k];
					const g1i = Li[p * m + k];
					const f1r = Fr[k * m + q];
					const f1i = Fi[k * m + q];
					const f2r = Fr[p * m + k];
					const f2i = Fi[p * m + k];
					const g2r = Lr[k * m + q];
					const g2i = Li[k * m + q];
					ar += f2r * g2r - f2i * g2i - (g1r * f1r - g1i * f1i);
					ai += f2r * g2i + f2i * g2r - (g1r * f1i + g1i * f1r);
				}
				cdiv(ar, ai, dd.zr[p] - dd.zr[q], dd.zi[p] - dd.zi[q]);
				Fr[p * m + q] = RE;
				Fi[p * m + q] = IM;
			}
		}
		return;
	}
	ws.clustered++;
	if (need === NEED_ALL) {
		for (let p = 1; p < m; p++) for (let q = 0; q < p; q++) { Fr[p * m + q] = 0; Fi[p * m + q] = 0; }
		for (let q = 0; q < m - 1; q++) pathVisit(path, ws, m, Lr, Li, Fr, Fi, q, q, 1 << q, 1, 0, false);
	} else {
		for (let p = 1; p < m; p++) { Fr[p * m] = 0; Fi[p * m] = 0; }
		pathVisit(path, ws, m, Lr, Li, Fr, Fi, 0, 0, 1, 1, 0, need === NEED_CORNER);
	}
}

function pathVisit(path, ws, m, Lr, Li, Fr, Fi, q, k, mask, pr, pi, cornerOnly) {
	if (k !== q && (!cornerOnly || k === m - 1)) {
		ddGet(path, ws.dd, mask);
		Fr[k * m + q] += pr * RE - pi * IM;
		Fi[k * m + q] += pr * IM + pi * RE;
	}
	for (let l = k + 1; l < m; l++) {
		const er = Lr[l * m + k];
		const ei = Li[l * m + k];
		if (er === 0 && ei === 0) continue;
		pathVisit(path, ws, m, Lr, Li, Fr, Fi, q, l, mask | (1 << l), pr * er - pi * ei, pr * ei + pi * er, cornerOnly);
	}
}

/* ==========================================================================
   One pair's transform

   The block of a pair (i, j) is the set of nuclides on some decay path from j
   to i, parents first: T_ij and K_ij involve no others. Its local index 0 is
   j and its last is i.
   ========================================================================== */

function makeWorkspace(nmax) {
	const nn = nmax * nmax;
	return {
		ar: new Float64Array(nmax), ai: new Float64Array(nmax),
		mr: new Float64Array(nmax), mi: new Float64Array(nmax),
		tr: new Float64Array(nmax), ti: new Float64Array(nmax),
		gr: new Float64Array(nmax), gi: new Float64Array(nmax),
		vr: new Float64Array(nmax), vi: new Float64Array(nmax),
		Lr: new Float64Array(nn), Li: new Float64Array(nn),
		Tr: new Float64Array(nn), Ti: new Float64Array(nn),
		Fr: new Float64Array(nn), Fi: new Float64Array(nn),
		E: 0,
		dd: makeDD(nmax),
		clustered: 0, evaluations: 0,
	};
}

/** The block of the pair (i, j), or null when j never becomes i. */
function blockOf(path, i, j) {
	const key = i * path.n + j;
	if (path.blocks.has(key)) return path.blocks.get(key);
	let blk = null;
	if (path.reach[j][i]) {
		const S = path.order.filter((k) => path.reach[j][k] && path.reach[k][i]);
		const m = S.length;
		const local = new Map(S.map((k, p) => [k, p]));
		const A = new Float64Array(m * m);
		for (let p = 0; p < m; p++) {
			for (const [par, c] of path.parents[S[p]]) {
				const q = local.get(par);
				if (q !== undefined) A[p * m + q] -= c;
			}
		}
		const pick = (arr) => Float64Array.from(S, (k) => arr[k]);
		const Rf = pick(path.Rf);
		let Rmin = Infinity;
		for (const r of Rf) if (r < Rmin) Rmin = r;
		blk = {
			i, j, S: Int32Array.from(S), m, A,
			lam: pick(path.lam), Rf, Rm: pick(path.Rm), De: pick(path.De),
			Rmin, matrix: path.matrix[S[0]] === 1, s0: NaN,
		};
	}
	path.blocks.set(key, blk);
	return blk;
}

/**
 * The pair's transform at s, scaled: the value is (RE + i IM) e^(-ws.E).
 * RELEASE gives T_ij and DECAYED (A^-1 T)_ij, under plug flow both without
 * their delay e^(-TW Rmin s); INVENTORY gives K_ij, which has none.
 */
function evalBlock(path, ws, blk, sr, si, kind) {
	const m = blk.m;
	const aw = path.aw;
	ws.evaluations++;
	// Under plug flow T and A^-1 T have their delay e^(-TW Rmin s) taken out:
	// G's diagonal then holds g_p - Rmin s, formed directly (see gFracture).
	// Divided differences of H are the same for points shifted alike, and
	// the shift Rmin s is one for the whole block, whatever each member's Rf,
	// so exp(-TW G) with the shifted diagonal is H(G) without the delay.
	const delay = kind !== INVENTORY && path.infPe ? blk.Rmin : 0;
	let phiMax = -Infinity;
	for (let p = 0; p < m; p++) {
		const ar = sr + blk.lam[p];
		const ai = si;
		ws.ar[p] = ar;
		ws.ai[p] = ai;
		gFracture(blk, p, sr, si, delay);
		let gr = RE;
		let gi = IM;
		if (blk.matrix) {
			const f = blk.Rm[p] / blk.De[p];
			const mr = f * ar;
			const mi = f * ai;
			ws.mr[p] = mr;
			ws.mi[p] = mi;
			tauAt(path, mr, mi);
			ws.tr[p] = RE;
			ws.ti[p] = IM;
			gr += aw * blk.De[p] * RE;
			gi += aw * blk.De[p] * IM;
		}
		ws.gr[p] = gr;
		ws.gi[p] = gi;
		phiAt(path, gr, gi);
		if (RE > phiMax) phiMax = RE;
	}
	const E = Number.isFinite(phiMax) ? -phiMax : 0;
	const Lr = ws.Lr;
	const Li = ws.Li;
	const dd = ws.dd;
	if (m > 1) {
		if (blk.matrix) {
			// tau(M), M = De^-1 A Rm: its strictly lower part is real.
			dd.kind = 0;
			for (let p = 0; p < m; p++) {
				dd.zr[p] = ws.mr[p]; dd.zi[p] = ws.mi[p]; dd.fr[p] = ws.tr[p]; dd.fi[p] = ws.ti[p];
				for (let q = 0; q < p; q++) {
					Lr[p * m + q] = blk.A[p * m + q] * blk.Rm[q] / blk.De[p];
					Li[p * m + q] = 0;
				}
			}
			triFun(path, ws, m, Lr, Li, ws.Tr, ws.Ti, NEED_ALL);
			for (let p = 1; p < m; p++) {
				const c = aw * blk.De[p];
				for (let q = 0; q < p; q++) {
					Lr[p * m + q] = blk.A[p * m + q] * blk.Rf[q] + c * ws.Tr[p * m + q];
					Li[p * m + q] = c * ws.Ti[p * m + q];
				}
			}
		} else {
			for (let p = 1; p < m; p++) {
				for (let q = 0; q < p; q++) {
					Lr[p * m + q] = blk.A[p * m + q] * blk.Rf[q];
					Li[p * m + q] = 0;
				}
			}
		}
	}
	// H(G), scaled by e^E.
	dd.kind = 1;
	dd.E = E;
	for (let p = 0; p < m; p++) {
		dd.zr[p] = ws.gr[p];
		dd.zi[p] = ws.gi[p];
		phiAt(path, ws.gr[p], ws.gi[p]);
		cexp(RE + E, IM);
		dd.fr[p] = RE;
		dd.fi[p] = IM;
	}
	triFun(path, ws, m, Lr, Li, ws.Fr, ws.Fi, kind === RELEASE ? NEED_CORNER : NEED_COLUMN);
	if (kind === RELEASE) {
		ws.E = E;
		RE = ws.Fr[(m - 1) * m];
		IM = ws.Fi[(m - 1) * m];
		return;
	}
	// K = A^-1 (I - T), column 0, by forward substitution; scaled by e^EK so
	// that a T far above one does not overflow. A^-1 T the same way, without
	// the identity.
	const EK = kind === DECAYED ? E : (E < 0 ? E : 0);
	const c0 = kind === DECAYED ? 0 : Math.exp(EK);
	const c1 = kind === DECAYED ? -1 : Math.exp(EK - E);
	for (let p = 0; p < m; p++) {
		let wr = (p === 0 ? c0 : 0) - c1 * ws.Fr[p * m];
		let wi = -c1 * ws.Fi[p * m];
		for (let q = 0; q < p; q++) {
			const a = blk.A[p * m + q];
			if (a !== 0) { wr -= a * ws.vr[q]; wi -= a * ws.vi[q]; }
		}
		cdiv(wr, wi, ws.ar[p], ws.ai[p]);
		ws.vr[p] = RE;
		ws.vi[p] = IM;
	}
	ws.E = EK;
	RE = ws.vr[m - 1];
	IM = ws.vi[m - 1];
}

function kindOf(kind) {
	const k = typeof kind === 'number' ? kind : KINDS.indexOf(kind ?? 'release');
	if (k !== RELEASE && k !== INVENTORY && k !== DECAYED) {
		throw new LaplacePathError(`Unknown response kind '${kind}'`);
	}
	return k;
}

/** T_ij(s) as [re, im]; [0, 0] when j never becomes i. */
export function transfer(path, sr, si, i, j) {
	const blk = blockOf(path, i, j);
	if (!blk) return [0, 0];
	evalBlock(path, path.ws, blk, sr, si, RELEASE);
	const re = RE;
	const im = IM;
	// the delay e^(-TW Rmin s) of plug flow, put back
	const lr = -path.ws.E - (path.infPe ? path.tw * blk.Rmin * sr : 0);
	const li = path.infPe ? -path.tw * blk.Rmin * si : 0;
	cexp(lr, li);
	return [re * RE - im * IM, re * IM + im * RE];
}

/** K_ij(s) as [re, im], the transform of what the path holds. */
export function inventoryTransfer(path, sr, si, i, j) {
	const blk = blockOf(path, i, j);
	if (!blk) return [0, 0];
	evalBlock(path, path.ws, blk, sr, si, INVENTORY);
	const f = Math.exp(-path.ws.E);
	return [RE * f, IM * f];
}

/**
 * T(0) for every pair, row-major n x n: the fraction of a unit of j that
 * leaves as i, decay allowed for. With a stable end to every chain and the
 * model holding amounts, each column sums to one.
 */
export function transferAtZero(path) {
	const n = path.n;
	const out = new Float64Array(n * n);
	for (let i = 0; i < n; i++) {
		for (let j = 0; j < n; j++) {
			if (!blockOf(path, i, j)) continue;
			let v = transfer(path, 0, 0, i, j)[0];
			if (!Number.isFinite(v)) v = transfer(path, 1e-300, 0, i, j)[0];
			out[i * n + j] = v;
		}
	}
	return out;
}

/** Which pairs (i, j) have a response: j is i, or decays into it. */
export function pairs(path) {
	const out = [];
	for (let j = 0; j < path.n; j++) {
		for (let i = 0; i < path.n; i++) if (path.reach[j][i]) out.push([i, j]);
	}
	return out;
}

/* ==========================================================================
   Numerical inversion
   ========================================================================== */

const M_DEFAULT = 28;
const TALBOT_M_MAX = 96;

/** tau on the real axis (negative z: -|u| tan(x0 |u|)). */
function tauReal(path, z) {
	if (z >= 0) {
		const u = Math.sqrt(z);
		return path.infX0 ? u : u * Math.tanh(path.x0 * u);
	}
	const u = Math.sqrt(-z);
	return path.infX0 ? NaN : -u * Math.tan(path.x0 * u);
}

/**
 * The rightmost singularity of the block's transforms; all lie on the real
 * axis at or left of it. Per member: the branch point s = -lambda of an
 * unlimited matrix, the first pole of tanh(x0 sqrt(m)) of a finite one, and
 * the branch point of sqrt(1 + 4 TW g/Pe), g(s) = -Pe/(4 TW), whichever comes
 * first. K's points s = -lambda are not among them: they cancel. A^-1 T's
 * are: they are the poles of A^-1.
 */
function singularity(path, blk, kind = RELEASE) {
	if (kind === DECAYED) {
		let s0 = singularity(path, blk);
		for (let p = 0; p < blk.m; p++) if (-blk.lam[p] > s0) s0 = -blk.lam[p];
		return s0;
	}
	if (!Number.isNaN(blk.s0)) return blk.s0;
	let s0 = -Infinity;
	for (let p = 0; p < blk.m; p++) {
		const lam = blk.lam[p];
		const Rf = blk.Rf[p];
		let sk;
		if (!blk.matrix) {
			sk = path.infPe ? -Infinity : -lam - path.Pe / (4 * path.tw * Rf);
		} else if (path.infX0) {
			sk = -lam;
		} else {
			const f = blk.Rm[p] / blk.De[p];
			const pole = -lam - (PI / (2 * path.x0)) * (PI / (2 * path.x0)) / f;
			if (path.infPe) {
				sk = pole;
			} else {
				// g(s) = (s + lam) Rf + aw De tau(f (s + lam)) rises from -inf at
				// the pole to 0 at -lam
				const gs = -path.Pe / (4 * path.tw);
				let a = pole;
				let b = -lam;
				for (let it = 0; it < 200 && b - a > 1e-15 * Math.max(Math.abs(a), Math.abs(b)); it++) {
					const c = 0.5 * (a + b);
					const g = (c + lam) * Rf + path.aw * blk.De[p] * tauReal(path, f * (c + lam));
					if (g > gs) b = c; else a = c;
				}
				sk = b;
			}
		}
		if (sk > s0) s0 = sk;
	}
	blk.s0 = s0;
	return s0;
}

/** A point of K's real axis moved off the removable points s = -lambda. */
function offLambda(blk, s, gap) {
	for (let pass = 0; pass <= blk.m; pass++) {
		let moved = false;
		for (let p = 0; p < blk.m; p++) {
			if (Math.abs(s + blk.lam[p]) < gap) { s = -blk.lam[p] + gap; moved = true; }
		}
		if (!moved) break;
	}
	return s;
}

/**
 * ln of the transform on the real axis right of the rightmost singularity
 * s0, on a grid geometric in x = s - s0: from where the tilted mean -dpsi/ds
 * exceeds 10 tHi out to where the transform underflows. D (at the midpoints)
 * is that tilted mean, the mean arrival time of e^(-st) h(t); it falls with
 * s, and the saddle for time t is where D = t.
 */
function realAxis(path, ws, pr, tLo, tHi) {
	const { blk, kind } = pr;
	const s0 = singularity(path, blk, kind);
	const fac = 10 ** (1 / 8);
	const psiAt = (s) => {
		const at = kind === INVENTORY ? offLambda(blk, s, 1e-7 * (s - s0)) : s;
		evalBlock(path, ws, blk, at, 0, kind);
		const F = RE;
		return F > 0 && Number.isFinite(F) ? Math.log(F) - ws.E : -Infinity;
	};
	const x0 = Math.max(Math.abs(s0), 0) + 1 / tHi;
	const up = [];
	const dn = [];
	// w = s D + psi(s), D the tilted mean between two points, is the
	// saddle-point exponent of the response at the time D (its log there, but
	// for half the log of 2 pi psi''). It is largest, ln T(0), at s = 0 and
	// falls as s grows (dw/ds = s dD/ds < 0): away from s0 the scan goes on
	// until w is e^-120 below its top, and so to before the response's rising
	// edge. psi itself may be far below what exp can hold (at a sharp front
	// e^(st) makes up for a transform of e^-1000 and less; evalBlock holds it
	// scaled, and psi is its log). A psi that is not finite, x past 1e12/tLo
	// and 800 points end the scan too.
	const Dof = (a, b) => -(b[1] - a[1]) / (b[0] - a[0]);
	let wmax = -Infinity;
	for (let x = x0, k = 0; k < 800; x *= fac, k++) {
		const p = psiAt(s0 + x);
		up.push([s0 + x, p]);
		if (!Number.isFinite(p) || x > 1e12 / tLo) break;
		const m = up.length;
		if (m >= 2) {
			const a = up[m - 2];
			const b = up[m - 1];
			const w = 0.5 * (a[0] + b[0]) * Dof(a, b) + 0.5 * (a[1] + b[1]);
			if (w > wmax) wmax = w;
			if (w < wmax - 120) break;
		}
	}
	// Toward s0 the tilted mean D grows without bound. w there is the
	// Chernoff bound: the part of the response after the time D is at most e^w
	// (s < 0). The scan stops where that part is negligible, where D passes 10
	// tHi, and where D no longer grows: psi is convex (the response is not
	// negative), so a D that does not grow is rounding -- s0 + x keeping few
	// digits of x, and the transform cancelling next to its singularity. Such
	// a D once stopped every saddle search of a path with little matrix and a
	// long tail.
	let prev = up[0];
	let Dprev = up.length > 1 ? Dof(up[0], up[1]) : 0;
	for (let x = x0 / fac, k = 0; k < 800; x /= fac, k++) {
		const s = s0 + x;
		if (!(s > s0)) break;
		const p = psiAt(s);
		if (!Number.isFinite(p)) break;
		const D = Dof([s, p], prev);
		if (!(D > Dprev)) break;
		dn.push([s, p]);
		const w = 0.5 * (s + prev[0]) * D + 0.5 * (p + prev[1]);
		if (w > wmax) wmax = w;
		prev = [s, p];
		Dprev = D;
		if (D > 10 * tHi || x < 1e-13 * Math.max(Math.abs(s0), 1 / tHi) || w < wmax - 120) break;
	}
	let pts = dn.reverse().concat(up);
	// A grid geometric in s - s0 steps by about |s0|/3 near s = 0: when the
	// singularity lies far out (under plug flow, the first pole of tanh at
	// -1e5 and more) the saddles of every time the response lives at fall
	// between two of its points. Add s = +-e, e geometric from 1/tHi, on
	// either side of 0 (on the left no nearer s0 than half way).
	{
		const extra = [];
		const eHi = Math.max(pts[pts.length - 1][0], 0);
		const eLeft = 0.5 * Math.abs(s0);
		for (let e = 1 / tHi; e < Math.max(eHi, eLeft); e *= fac) {
			if (e < eHi) extra.push(e);
			if (e < eLeft) extra.push(-e);
		}
		if (extra.length) {
			const have = pts.map((q) => q[0]);
			const lo0 = have[0];
			const near = (a, b) => Math.abs(a - b) < 1e-6 * Math.max(Math.abs(a), Math.abs(b), 1 / tHi);
			for (const e of extra) {
				if (!(e > lo0) || have.some((h) => near(h, e))) continue;
				const pv = psiAt(e);
				if (Number.isFinite(pv)) pts.push([e, pv]);
			}
			pts.sort((a, b) => a[0] - b[0]);
			// keep the tilted mean positive and falling (rounding next to s0,
			// or a point too close to its neighbour, would stop every saddle
			// search)
			const kept = [pts[0]];
			for (let k = 1; k < pts.length; k++) {
				const Dn = Dof(kept[kept.length - 1], pts[k]);
				if (!(Dn > 0) || (kept.length >= 2 && !(Dn < Dof(kept[kept.length - 2], kept[kept.length - 1])))) continue;
				kept.push(pts[k]);
			}
			pts = kept;
		}
	}
	// Resolve the saddles: where D falls from one interval to the next by
	// more than the tilted spread allows (psi'' span^2 > 1, the span wider
	// than the Gaussian's width in s), put a node between, as far as the
	// response matters (w within 80 of its top). A narrow pulse would
	// otherwise have its saddles placed far off, with terms e^10 and more
	// larger than the answer.
	for (let pass = 0; pass < 14 && pts.length < 4000; pass++) {
		const out = [pts[0]];
		let added = false;
		for (let k = 0; k + 1 < pts.length; k++) {
			const a = pts[k];
			const b = pts[k + 1];
			const Dk = Dof(a, b);
			const Dl = k > 0 ? Dof(pts[k - 1], a) : NaN;
			const Dr = k + 2 < pts.length ? Dof(b, pts[k + 2]) : NaN;
			const drop = Math.max(Number.isFinite(Dl) ? Dl - Dk : 0, Number.isFinite(Dr) ? Dk - Dr : 0);
			const w = 0.5 * (a[0] + b[0]) * Dk + 0.5 * (a[1] + b[1]);
			if (drop * (b[0] - a[0]) > 1 && w > wmax - 80) {
				const sMid = s0 + Math.sqrt((a[0] - s0) * (b[0] - s0));
				if (sMid > a[0] && sMid < b[0]) {
					const p = psiAt(sMid);
					if (Number.isFinite(p)) { out.push([sMid, p]); added = true; }
				}
			}
			out.push(b);
		}
		pts = out;
		if (!added) break;
	}
	const K = pts.length;
	const s = new Float64Array(K);
	const psi = new Float64Array(K);
	for (let k = 0; k < K; k++) { s[k] = pts[k][0]; psi[k] = pts[k][1]; }
	const sm = new Float64Array(Math.max(0, K - 1));
	const D = new Float64Array(Math.max(0, K - 1));
	for (let k = 0; k + 1 < K; k++) {
		sm[k] = s0 + Math.sqrt((s[k] - s0) * (s[k + 1] - s0));
		D[k] = Number.isFinite(psi[k + 1]) && Number.isFinite(psi[k])
			? -(psi[k + 1] - psi[k]) / (s[k + 1] - s[k]) : NaN;
	}
	return { pr, s0, s, psi, sm, D };
}

/** The saddle of e^(st) times the transform for time t: s with D(s) = t,
    psi'' there, and w = s t + psi(s), the estimate of the response's log. */
function saddleAt(ax, t) {
	const D = ax.D;
	const sm = ax.sm;
	const K = D.length;
	const s0 = ax.s0;
	if (K < 2) return null;
	let k = 0;
	while (k < K && !(D[k] <= t)) {
		if (!Number.isFinite(D[k]) && k > 0) break;
		k++;
	}
	if (k === 0) {
		const psi2 = (D[0] - D[1]) / (sm[1] - sm[0]);
		return { s: sm[0], psi2, w: sm[0] * t + ax.psi[0], edge: true, beyond: false };
	}
	if (k >= K || !Number.isFinite(D[k])) {
		return { s: sm[Math.min(k, K) - 1], psi2: NaN, w: -Infinity, edge: false, beyond: true };
	}
	const a = k - 1;
	const b = k;
	const la = Math.log(D[a]);
	const lb = Math.log(D[b]);
	const f = (la - Math.log(t)) / (la - lb);
	const xa = sm[a] - s0;
	const xb = sm[b] - s0;
	const ss = s0 + xa * (xb / xa) ** f;
	const psi2 = (D[a] - D[b]) / (sm[b] - sm[a]);
	const psi = ax.psi[b] + (ax.s[b] - ss) * 0.5 * (t + D[b]);
	return { s: ss, psi2, w: ss * t + psi, edge: false, beyond: false };
}

/** One term of the parabola sum at Y, jac = dY/du the node map's Jacobian
    (1 for uniform nodes) and wgt the trapezoidal weight (1/2 at the vertex):
    adds wgt jac z to acc and returns jac |z|. */
function parabolaTerm(path, ws, pr, t, ss, kappa, Y, jac, wgt, acc) {
	const sr = ss - kappa * Y * Y;
	const si = Y;
	evalBlock(path, ws, pr.blk, sr, si, pr.kind);
	const Fr = RE;
	const Fi = IM;
	const ex = t * sr - ws.E;
	if (ex > 700) { acc.bad = true; return Infinity; }
	if (ex < -740 || (Fr === 0 && Fi === 0)) return 0;
	cexp(ex, t * si);
	const er = RE;
	const ei = IM;
	const ar = er * Fr - ei * Fi;
	const ai = er * Fi + ei * Fr;
	const q = 2 * kappa * Y;
	const zr = ar - ai * q;
	const zi = ai + ar * q;
	const w = wgt * jac;
	acc.h += w * zr;
	const yr = sr * zr - si * zi;
	const yi = sr * zi + si * zr;
	acc.dh += w * yr;
	acc.d2 += w * (sr * yr - si * yi);
	const mod = Math.hypot(zr, zi);
	acc.abs += w * mod;
	return jac * mod;
}

/** Trapezoidal sum over u = off, off + 2 step, ... (off = 0 or step) until
    the terms die out; the nodes are Y = u, or Y = c sinh(u) when c > 0 (see
    nodeScale). Terms that grow back, after they have fallen away, to within
    1e-3 of the largest, or past it, mean the path runs into a region where
    the transform is large: `regrow`. The terms' envelope is the largest of
    the last seven, so that a dip (the transform passing near a zero) is not
    taken for a fall. Out of nodes or budget before the terms died out, the
    sum is `cut` short. */
function parabolaSweep(path, ws, pr, t, ss, kappa, step, off, acc, c) {
	let maxMod = 0;
	let minEnv = Infinity;
	let small = 0;
	const last = [0, 0, 0, 0, 0, 0, 0];
	for (let k = 0; k < 20000; k++) {
		const u = off + k * (off ? 2 * step : step);
		const Y = c > 0 ? c * Math.sinh(u) : u;
		const jac = c > 0 ? c * Math.cosh(u) : 1;
		if (u === 0) {
			const m0 = parabolaTerm(path, ws, pr, t, ss, kappa, 0, jac, 0.5, acc);
			maxMod = Math.max(maxMod, m0);
			continue;
		}
		const m = parabolaTerm(path, ws, pr, t, ss, kappa, Y, jac, 1, acc);
		if (k > 3 && (m > 100 * maxMod || (minEnv < 1e-6 * maxMod && m > 1e-3 * maxMod))) { acc.regrow = true; break; }
		if (m > maxMod) maxMod = m;
		last[k % 7] = m;
		if (k >= 7) minEnv = Math.min(minEnv, Math.max(...last));
		if (m <= 1e-18 * maxMod) { if (++small >= 3 && k > 3) return; } else small = 0;
		if (acc.bad) return;
		if (ws.evaluations > acc.stop) break;
	}
	acc.cut = true;
}

/** psi = ln of the pair's transform at a real s, NaN where it is not positive. */
function psiReal(path, ws, pr, s) {
	evalBlock(path, ws, pr.blk, s, 0, pr.kind);
	const F = RE;
	return F > 0 && Number.isFinite(F) ? Math.log(F) - ws.E : NaN;
}

/** psi, the tilted mean D = -psi' and psi'' at s, by central differences
    a thousandth of s - s0 apart, or a tenth of `scale` (the saddle's own
    width) when that is less. */
function localAxis(path, ws, ax, s, scale) {
	const dl = Math.min(1e-3 * (s - ax.s0), scale > 0 ? 0.1 * scale : Infinity);
	const pm = psiReal(path, ws, ax.pr, s - dl);
	const p0 = psiReal(path, ws, ax.pr, s);
	const pp = psiReal(path, ws, ax.pr, s + dl);
	return { psi: p0, D: (pm - pp) / (2 * dl), psi2: (pp - 2 * p0 + pm) / (dl * dl) };
}

/** ln |H(g_p(s))|, the size of member p's own transform at s, with the
    delay e^(-TW rfc s) taken out as the pair's transform has it. */
function lnHk(path, blk, p, sr, si, rfc) {
	const lam = blk.lam[p];
	gFracture(blk, p, sr, si, rfc);
	let gr = RE;
	let gi = IM;
	if (blk.matrix) {
		const f = blk.Rm[p] / blk.De[p];
		tauAt(path, f * (sr + lam), f * si);
		gr += path.aw * blk.De[p] * RE;
		gi += path.aw * blk.De[p] * IM;
	}
	phiAt(path, gr, gi);
	return RE;
}

/**
 * Whether, along s = v + iY - kappa Y^2, no member's own transform times
 * e^(st) grows above lev[p]. The fracture's transform reaches e^(Pe/2) at its
 * branch point, g = -Pe/(4 TW), and is large near the real axis on the far
 * side of it; a parabola that bends too fast passes there low, and its terms,
 * far larger than the answer, cancel to rounding.
 */
function clearsRidge(path, blk, v, t, kappa, lev, levMin, rfc) {
	let ymax;
	if (path.infPe) {
		// plug flow: the transform exp(-TW aw De tau) has essential
		// singularities at the poles of tanh, large just right of each; look
		// as far as e^(st) takes 80 off the vertex
		ymax = Math.sqrt(80 / (t * kappa));
	} else {
		// |H| <= e^(Pe/2): where t Re s + Pe/2 stays below the levels nothing
		// can grow, and beyond ymax t Re s + Pe/2 < levMin - 40
		if (t * v + path.Pe / 2 <= levMin) return true;
		ymax = Math.sqrt((t * v + path.Pe / 2 - levMin + 40) / (t * kappa));
	}
	for (let q = 1; q <= 96; q++) {
		const Y = ymax * q / 96;
		const sr = v - kappa * Y * Y;
		for (let p = 0; p < blk.m; p++) if (t * sr + lnHk(path, blk, p, sr, Y, rfc) > lev[p]) return false;
	}
	return true;
}

/**
 * How fast, at most, the phase of any member's own transform times e^(st)
 * turns along s = v + iY - kappa Y^2 (per unit Y), over the stretch where its
 * size is above e^floor. Next to the fracture's branch point the transform
 * turns at (Pe/2) |d sqrt(1 + 4 TW g/Pe)/ds|, fast when Pe is large, and a
 * member that the saddle of a daughter's response does not hold still turns
 * at |t - D_k|: the trapezoidal step must follow both, or its sums alias
 * them, two halvings agreeing on the wrong value. The rate is linear in t:
 * with t2 given, the larger of its values at t and t2 (the floor and the
 * stretch are then those of t, the earlier). With c > 0 it also leaves in
 * RATE_U the fastest rate per unit u of sinh nodes Y = c sinh(u) (see
 * nodeScale): the rate per unit Y times dY/du = sqrt(c^2 + Y^2). rfc is the
 * delay the pair's transform has taken out (see gFracture).
 */
function pathFrequency(path, blk, v, t, kappa, floor, rfc, t2, c) {
	const ymax = Math.sqrt(Math.max(0, (t * v - floor + (path.infPe ? 40 : path.Pe / 2 + 40)) / (t * kappa)));
	let wmax = 0;
	let wmaxU = 0;
	for (let q = 0; q <= 96; q++) {
		const Y = ymax * q / 96;
		const sr = v - kappa * Y * Y;
		const si = Y;
		for (let p = 0; p < blk.m; p++) {
			const zr0 = sr + blk.lam[p];
			// g (under plug flow g - rfc s, see gFracture) and dg/ds
			gFracture(blk, p, sr, si, rfc);
			let gr = RE;
			let gi = IM;
			let dgr = path.infPe ? blk.Rf[p] - rfc : blk.Rf[p];
			let dgi = 0;
			if (blk.matrix) {
				const f = blk.Rm[p] / blk.De[p];
				const awDe = path.aw * blk.De[p];
				csqrt(f * zr0, f * si);
				const ur = RE;
				const ui = IM;
				// tau and tau'
				let tr = ur;
				let ti = ui;
				let dr;
				let di;
				cdiv(0.5, 0, ur, ui);
				const hr = RE;
				const hi = IM;
				if (path.infX0) {
					dr = hr;
					di = hi;
				} else {
					ctanh(path.x0 * ur, path.x0 * ui);
					const thr = RE;
					const thi = IM;
					tr = ur * thr - ui * thi;
					ti = ur * thi + ui * thr;
					csech2(path.x0 * ur, path.x0 * ui);
					dr = thr * hr - thi * hi + 0.5 * path.x0 * RE;
					di = thr * hi + thi * hr + 0.5 * path.x0 * IM;
				}
				gr += awDe * tr;
				gi += awDe * ti;
				dgr += awDe * f * dr;
				dgi += awDe * f * di;
			}
			phiAt(path, gr, gi);
			if (t * sr + RE < floor) continue;
			// phi'(s) = dphi/dg g'(s): -TW/sqrt(1 + 4 TW g/Pe) g'(s), or -TW g'(s)
			// under plug flow (g' then the derivative of g - rfc s)
			let pr;
			let pi;
			if (path.infPe) {
				pr = -path.tw * dgr;
				pi = -path.tw * dgi;
			} else {
				const B = 4 * path.tw / path.Pe;
				csqrt(1 + B * gr, B * gi);
				cdiv(-path.tw, 0, RE, IM);
				pr = RE * dgr - IM * dgi;
				pi = RE * dgi + IM * dgr;
			}
			// d(phase)/dY = Im[(t + phi'(s)) (i - 2 kappa Y)]
			let w = Math.abs((t + pr) - 2 * kappa * Y * pi);
			if (t2 !== undefined) w = Math.max(w, Math.abs((t2 + pr) - 2 * kappa * Y * pi));
			if (w > wmax) wmax = w;
			if (c > 0) {
				const wu = w * Math.sqrt(c * c + Y * Y);
				if (wu > wmaxU) wmaxU = wu;
			}
		}
	}
	RATE_U = wmaxU;
	return wmax;
}

const ZERO = { h: 0, dh: 0, d2: 0, err: 0, cond: 1, nodes: 0 };

const VERTEX_BETA = 1.5;

/**
 * The vertex of the parabola for time tt: the saddle `sad` from the table, at
 * least 1.5/tt right of s0, polished by Newton's method on D(v) = tt -- except
 * K's, whose removable points s = -lambda would spoil the differences: it
 * stays where the scan put it. Returns `{v, loc, psi2}`, `loc` the local axis
 * at v (null for K).
 */
function parabolaVertex(path, ws, ax, tt, sad) {
	const vMin = ax.s0 + VERTEX_BETA / tt;
	let v = Math.max(sad.s, vMin);
	let loc = null;
	let psi2 = NaN;
	if (ax.pr.kind !== INVENTORY) {
		// the differences on the scale of the saddle's own width (the distance
		// to s0 can be 1e5 times larger, under plug flow with a finite matrix)
		const scale = Math.min(1 / tt, Number.isFinite(sad.psi2) && sad.psi2 > 0 ? 1 / Math.sqrt(sad.psi2) : Infinity);
		loc = localAxis(path, ws, ax, v, scale);
		for (let it = 0; it < 3 && v > vMin && loc.psi2 > 0 && Math.abs(loc.D - tt) > 0.5 * Math.sqrt(loc.psi2); it++) {
			const vn = Math.max(v + (loc.D - tt) / loc.psi2, vMin);
			const ln = localAxis(path, ws, ax, vn, scale);
			if (!(Math.abs(ln.D - tt) < Math.abs(loc.D - tt)) || !(ln.psi2 > 0)) break;
			v = vn;
			loc = ln;
		}
		psi2 = loc.psi2;
	}
	if (!(psi2 > 0) || !Number.isFinite(psi2)) psi2 = Number.isFinite(sad.psi2) && sad.psi2 > 0 ? sad.psi2 : tt * tt;
	return { v, loc, psi2 };
}

/**
 * kappa, divided by 4 until no member's own transform times e^(st) grows along
 * the parabola at time t (see clearsRidge); wv = t v + psi(v) is the size of
 * the answer's integrand at the vertex, rfc the delay the pair's transform has
 * taken out.
 */
function flattenForRidge(path, blk, v, t, wv, kappa, rfc) {
	// each member may grow along the path to its own size at the vertex or to
	// the answer's, whichever is larger (under plug flow with an unlimited
	// matrix nothing grows: exp(-TW aw sqrt(De R s)))
	const m = blk.m;
	const lev = new Float64Array(m);
	let levMin = Infinity;
	for (let p = 0; p < m; p++) {
		lev[p] = Math.max(t * v + lnHk(path, blk, p, v, 0, rfc), wv) + 2;
		levMin = Math.min(levMin, lev[p]);
	}
	for (let k = 0; k < 16 && !clearsRidge(path, blk, v, t, kappa, lev, levMin, rfc); k++) kappa /= 4;
	return kappa;
}

/**
 * The response and its first two derivatives at t, on a parabola
 * s(Y) = v + iY - kappa Y^2.
 *
 * The vertex v is the saddle s* of e^(st) times the transform on the real
 * axis (polished by Newton's method on D(s) = t), or 1.5/t right of the
 * rightmost singularity s0 when the saddle lies closer to it: next to a
 * branch point the integrand is then at most e^1.5 larger, and the step can
 * be of the order of 1/t rather than the saddle's distance to s0.
 *
 * kappa = psi''(v)/(2t) makes the path the steepest descent to second order
 * (exact for advection and dispersion alone, whose integrand it turns into a
 * Gaussian in Y). It is at least 1/(4(v - s0)), which puts the parabola's
 * focus at s0 so that the path wraps a branch point there as Hankel's
 * contour does. It is reduced until no member's transform grows along the
 * path (see clearsRidge), and again should the terms, once fallen away, grow
 * on. Trapezoidal in Y, the step halved until two sums agree, following the
 * fastest phase along the path of the answer and of every member's own
 * transform (see pathFrequency), under plug flow as elsewhere; next to a weak
 * singularity trapezoidal in u, Y = c sinh(u) (see nodeScale).
 */
function invertParabola(path, ws, ax, t, opt) {
	const pr = ax.pr;
	const tt = t - pr.shift;
	if (!(tt > 0)) return ZERO;
	const rtol = (opt && opt.rtol) || 1e-11;
	const atol = (opt && opt.atol) || 0;
	const maxEval = (opt && opt.maxEval) || 6000;
	const sad = saddleAt(ax, tt);
	if (!sad || sad.beyond || sad.w < -720) return { ...ZERO, negligible: true };
	const n0 = ws.evaluations;
	const { v, loc, psi2 } = parabolaVertex(path, ws, ax, tt, sad);
	const wv = loc && Number.isFinite(loc.psi) ? tt * v + loc.psi : sad.w;
	const omega = loc && Number.isFinite(loc.D) ? Math.abs(tt - loc.D) : 0;
	let kappa = Math.max(psi2 / (2 * tt), 0.25 / (v - ax.s0));
	// the delay the pair's transform has taken out (under plug flow)
	const rfc = pr.shift > 0 ? pr.blk.Rmin : 0;
	if (!path.infPe || !path.infX0) kappa = flattenForRidge(path, pr.blk, v, tt, wv, kappa, rfc);
	let res = null;
	for (let attempt = 0; attempt < 4; attempt++) {
		const strip = parabolaStrip(ax, v, kappa);
		const psi2e = pathCurvature(psi2, tt, loc ? loc.D : NaN, kappa);
		// The phase rates, per unit Y and per unit u of sinh nodes: |t - D(v)|
		// over the stretch where the answer's terms are above e^-25 of the
		// vertex's, and the members' own (pathFrequency), under plug flow as
		// well: the members of a chain can each exceed the answer, with tilted
		// means far from t, and turn thousands of times faster than it along
		// the path; two sums at a step too coarse for them agreed on a value
		// 1e-4 off.
		const wY = Math.max(omega, pathFrequency(path, pr.blk, v, tt, kappa, wv - 25, rfc, undefined, strip));
		const wU = Math.max(omega * Math.sqrt(strip * strip + 50 / psi2e), RATE_U);
		const c = nodeScale(strip, psi2e, 1.5 * PI / Math.sqrt(18.5 * psi2), wY, wU);
		res = parabolaSums(path, ws, ax, tt, v, kappa, psi2, c > 0 ? wU : wY, rtol, atol, n0 + maxEval, strip, c);
		if (!res.regrow) break;
		kappa /= 8;
	}
	if (res.regrow || res.bad) {
		return { h: NaN, dh: NaN, d2: NaN, err: Infinity, cond: Infinity, nodes: ws.evaluations - n0 };
	}
	res.nodes = ws.evaluations - n0;
	return res;
}

/** The half-width of the strip of analyticity about the real Y axis of the
    integrand along s = v + iY - kappa Y^2: the rightmost singularity s0 maps
    to Y = (i +- sqrt(4 kappa d - 1))/(2 kappa), d = v - s0. */
function parabolaStrip(ax, v, kappa) {
	const dist = v - ax.s0;
	let strip = Infinity;
	if (dist > 0 && Number.isFinite(dist)) {
		strip = kappa * dist < 1e-12 ? dist
			: 4 * kappa * dist >= 1 ? 1 / (2 * kappa) : (1 - Math.sqrt(1 - 4 * kappa * dist)) / (2 * kappa);
	}
	if (!(strip > 0)) strip = dist > 0 ? dist : Infinity;
	return strip;
}

/** The curvature of the integrand's Gaussian in Y along the parabola at time
    t: ln |e^(st) T(s)| = t v + psi(v) - (t - D(v)) kappa Y^2 - psi'' Y^2/2 +
    ..., D(v) the tilted mean at the vertex. At the saddle it is psi''; a
    vertex held right of the saddle (D(v) < t) adds the rest. */
function pathCurvature(psi2, t, Dv, kappa) {
	return psi2 + 2 * Math.max(0, Number.isFinite(Dv) ? t - Dv : 0) * kappa;
}

const SINH_RATIO = 0.1; // sinh nodes only where the strip is below this times the Gaussian's width
const SINH_STEP = 0.3; // the first step in u of sinh nodes (about 1e-7; halved, rounding)

/**
 * The node map of the trapezoidal sums along a parabola: Y = u (returns 0) or
 * Y = c sinh(u), c = strip (returns c).
 *
 * Next to a weak singularity the strip of analyticity, half-width `strip` in
 * Y, can be far narrower than the integrand's Gaussian: a first pole of tanh
 * just left of the saddle, whose residue (a_w D_e small) hardly shows in the
 * response, bounds a uniform step all the same, and the terms die out only
 * after tens of thousands of steps. With Y = c sinh(u), trapezoidal in u, the
 * nodes lie c h apart next to the vertex and about |Y| h beyond, so that a few
 * dozen cover the Gaussian. The singularity at Y = i c maps to u = i pi/2,
 * but the Gaussian grows off the real u axis past |Im u| = pi/4 (Re Y^2 < 0
 * there for large |u|): the strip in u is pi/4, the error goes as
 * exp(-pi^2/(2 h)) in the step h in u, and halving h still squares it. The
 * spacing grows with |Y|, so a phase that turns over the whole Gaussian costs
 * sinh nodes more than uniform ones; and in the first halvings the sums can
 * converge more slowly than the strip of pi/4 promises, so their sums are
 * never taken after one halving on the strip's bound.
 *
 * So sinh nodes where the strip is narrower than a tenth of the Gaussian's
 * width 1/sqrt(psi2e) (a uniform step then needs ten times the nodes and
 * more), sets the uniform step, and sinh nodes reach the end of the Gaussian
 * (e^-41.5, where the sweeps stop) in fewer nodes at the first steps:
 * gaussStep the uniform step for the Gaussian, wY and wU the fastest phase
 * per unit Y and per unit u (four nodes to a turn in either).
 */
function nodeScale(strip, psi2e, gaussStep, wY, wU) {
	if (!(strip * Math.sqrt(psi2e) < SINH_RATIO)) return 0;
	const stepY = Math.min(gaussStep, wY > 0 ? 0.5 * PI / wY : Infinity);
	if (!(0.5 * strip < stepY)) return 0;
	const reach = Math.sqrt(83 / psi2e);
	const nY = reach / (0.5 * strip);
	const nU = Math.asinh(reach / strip) / sinhStep(strip, gaussStep, wU);
	return nU < nY ? strip : 0;
}

/** The first step in u of sinh nodes Y = c sinh(u): SINH_STEP, four nodes to
    a turn of the phase (wU per unit u), and no coarser than the uniform step
    for the Gaussian next to the vertex, where dY/du = c. */
function sinhStep(c, gaussStep, wU) {
	return Math.min(SINH_STEP, wU > 0 ? 0.5 * PI / wU : Infinity, gaussStep / c);
}

/** The trapezoidal sums of invertParabola on one parabola: strip from
    parabolaStrip, c from nodeScale, omega the fastest phase rate per unit of
    the node variable. */
function parabolaSums(path, ws, ax, tt, v, kappa, psi2, omega, rtol, atol, stop, strip, c) {
	const pr = ax.pr;
	let step;
	let stripU;
	if (c > 0) {
		// sinh nodes: the strip in u is pi/4 (see nodeScale)
		stripU = PI / 4;
		step = sinhStep(c, 1.5 * PI / Math.sqrt(18.5 * psi2), omega);
	} else {
		// A Gaussian e^(-psi'' Y^2/2) is integrated to about 1e-7 at this step
		// and to rounding at half of it; four nodes to a turn of the fastest
		// phase along the path (a vertex off the saddle turns at |t - D|; see
		// pathFrequency).
		step = 1.5 * PI / Math.sqrt(18.5 * psi2);
		if (omega > 0) step = Math.min(step, 0.5 * PI / omega);
		// The integrand is analytic in the strip |Im Y| < strip, and the
		// trapezoidal rule converges like exp(-2 pi strip/step). Start inside
		// that, or two coarse sums can agree while both miss the feature.
		stripU = strip;
		step = Math.min(step, 0.5 * strip);
	}
	// K is finite at s = -lambda, but I - T cancels there: keep the node on
	// the real axis a quarter step clear of those points, on the right,
	// where there is nothing singular to meet (dY/du = c at the vertex).
	const ss = pr.kind === INVENTORY ? offLambda(pr.blk, v, 0.25 * (c > 0 ? c * step : step)) : v;
	const acc = { h: 0, dh: 0, d2: 0, abs: 0, bad: false, regrow: false, cut: false, stop };
	parabolaSweep(path, ws, pr, tt, ss, kappa, step, 0, acc, c);
	if (acc.regrow) return { regrow: true };
	let h = acc.h * step / PI;
	let dh = acc.dh * step / PI;
	let d2 = acc.d2 * step / PI;
	let err = Infinity;
	let agreed = 0;
	for (let level = 0; level < 12 && !acc.bad; level++) {
		if (ws.evaluations > stop) break;
		const half = step / 2;
		const a2 = { h: 0, dh: 0, d2: 0, abs: 0, bad: false, regrow: false, cut: false, stop };
		parabolaSweep(path, ws, pr, tt, ss, kappa, half, half, a2, c);
		if (a2.regrow) return { regrow: true };
		if (a2.bad) { acc.bad = true; break; }
		if (a2.cut) acc.cut = true;
		acc.h += a2.h;
		acc.dh += a2.dh;
		acc.d2 += a2.d2;
		acc.abs += a2.abs;
		step = half;
		const h2 = acc.h * step / PI;
		// The trapezoidal error squares with each halving: the difference of
		// the last two sums bounds the error of the one before, and its square
		// (relative) that of the new one.
		err = Math.abs(h2 - h);
		h = h2;
		dh = acc.dh * step / PI;
		d2 = acc.d2 * step / PI;
		const floor = 1e-15 * acc.abs * step / PI + atol;
		const rel = err / Math.max(Math.abs(h), 1e-300);
		// What the nearest singularity leaves at this step: the trapezoidal
		// error of a pole at the strip's edge whose residue is the size of the
		// answer. Squaring alone is not enough: A^-1 T has a pole and a branch
		// point together at s = -lambda, and there a sum that squared its
		// error by the difference was still 2e-11 out, at an estimate of 2e-15.
		const next = Math.max(rel * rel, 2 * Math.exp(-2 * PI * stripU / step));
		// Under plug flow a finite matrix puts an essential singularity at
		// every pole of tanh, with a ridge beside it, and an oscillation a
		// whole number of steps long gives two sums that agree and are both
		// wrong: there, two agreements in a row.
		const ok = err <= floor || (level >= 1 && err <= rtol * Math.abs(h) && next <= rtol)
			|| (!(c > 0) && step <= 0.3 * stripU && next <= rtol * 1e-2);
		agreed = ok ? agreed + 1 : 0;
		if (ok && (agreed >= 2 || !path.infPe)) {
			err = Math.min(err, next * Math.abs(h) + floor);
			break;
		}
	}
	if (acc.bad) return { bad: true };
	const cond = acc.abs * step / PI / Math.max(Math.abs(h), 1e-300);
	// a sum cut short can agree with the next one and still be wrong
	if (acc.cut) err = Infinity;
	return { h, dh, d2, err, cond, s: ss, kappa, c };
}

/* ==========================================================================
   Shared contours: one parabola for the times of a cell

   The nodes of one parabola give the response at any time t' near its own
   time t_a from the same values of the transform: only e^(s t') changes, and
   that costs a small fraction of an evaluation of the transform, let alone of
   the search for the path. Along the parabola built for t_a the terms for t'
   exceed the answer by about exp((t' - t_a)^2/(2 psi'')) near the saddle (in
   general by f(v) - min f, f(s) = s t' + psi(s)), so one parabola serves the
   times within a few tilted standard deviations sigma = sqrt(psi'') of t_a;
   and within a factor of about 2, since the Gaussian's width in Y goes as
   sqrt(t_a/t').

   The cells: a lattice in ln t per axis, from its real-axis table alone, t
   the time less the plug-flow delay. u(ln t) = integral of max(t/(2 C
   sigma(t)), 1/(2 ln F)) d ln t, C = 2, F = 2, sigma from psi'' on the table
   as saddleAt takes it, continued beyond the table's ends with the slope
   1/(2 ln F); cell k covers u in [k - 1/2, k + 1/2], so it spans at most 2
   sigma and a factor 2 on either side of its middle time t(u = k). A cell
   depends on the table and k only, never on which times were asked for: a
   time's result does not depend on the order in which times are requested.

   The parabola of cell k is built from its middle time's saddle and vertex
   rule, as for a single time -- K's vertex stays where the scan put it, the
   tilted mean there taken as the middle time, and its node on the real axis
   a quarter step clear of s = -lambda -- and made valid for all its times:
   the ridge is checked at the earliest time (where e^(st) damps least), the
   phase rate is the larger of its values at the two ends (it is linear in t),
   the first step follows the narrowest Gaussian (psi'' t_hi/t_a, the latest
   time), the nodes are uniform or sinh-spaced as for a single time (see
   nodeScale, the widest Gaussian deciding), and the sweeps run until the
   terms are negligible at five probe times across the cell (at k - 1/2,
   k - 1/4, k, k + 1/4, k + 1/2 on the lattice), so as far as the widest
   Gaussian needs. The halvings stop only when every probe
   meets the tests of parabolaSums. The nodes are kept, and any time of the
   cell is summed from them, with its own error estimate from the last two
   levels of halving (under plug flow, three) and the tests of parabolaSums
   at its own time. A cell whose sums still grow back when flattened as for a
   single time, are cut short, run out of budget or do not converge serves no
   time, and a time whose own estimate does not pass is inverted on its own
   parabola as before. Each axis has cells of its own: an inventory is
   sampled on two (see `sampleInventory`).
   ========================================================================== */

const CELL_C = 2; // a cell spans at most 2 tilted standard deviations either side
const CELL_F = 2; // and at most a factor 2 either side
const CELL_PROBES = [-0.5, -0.25, 0, 0.25, 0.5]; // the probe times, in u about the cell's middle
const CELL_COND = 1e6; // the largest sum of moduli over the answer a shared time may have
const CELL_PRUNE = 1e-20; // nodes below this times the vertex's term at both ends are dropped
const CELL_NEGLIGIBLE = 1e-20; // terms below this times the response's peak need no condition
const CELL_MAX_EVAL = 24000; // the evaluations a cell may take: four times a single time's budget, for all its times
const CELL_SLOPE = 1 / (2 * Math.log(CELL_F)); // du/d ln t where the factor rules
const LN_PRUNE = Math.log(CELL_PRUNE);

/** The part of u over [t1, t2] within one interval of the table (sigma
    constant there). */
function cellSpan(t1, t2, sig) {
	if (!(sig > 0) || !Number.isFinite(sig)) return CELL_SLOPE * Math.log(t2 / t1);
	const tk = CELL_C * sig / Math.log(CELL_F); // t/(2 C sigma) = 1/(2 ln F) here
	if (t2 <= tk) return CELL_SLOPE * Math.log(t2 / t1);
	if (t1 >= tk) return (t2 - t1) / (2 * CELL_C * sig);
	return CELL_SLOPE * Math.log(tk / t1) + (t2 - tk) / (2 * CELL_C * sig);
}

/** u at time tt (the time less the plug-flow delay). */
function cellU(C, tt) {
	const tb = C.tb;
	const nb = tb.length;
	if (!nb) return CELL_SLOPE * Math.log(tt);
	if (tt <= tb[0]) return CELL_SLOPE * Math.log(tt / tb[0]);
	if (tt >= tb[nb - 1]) return C.U[nb - 1] + CELL_SLOPE * Math.log(tt / tb[nb - 1]);
	let lo = 0;
	let hi = nb - 1;
	while (hi - lo > 1) { const c = (lo + hi) >> 1; if (tb[c] <= tt) lo = c; else hi = c; }
	return C.U[lo] + cellSpan(tb[lo], tt, C.sig[lo]);
}

/** The time tt at u, the inverse of cellU. */
function cellT(C, u) {
	const tb = C.tb;
	const nb = tb.length;
	const U = C.U;
	if (!nb) return Math.exp(u / CELL_SLOPE);
	if (u <= 0) return tb[0] * Math.exp(u / CELL_SLOPE);
	if (u >= U[nb - 1]) return tb[nb - 1] * Math.exp((u - U[nb - 1]) / CELL_SLOPE);
	let lo = 0;
	let hi = nb - 1;
	while (hi - lo > 1) { const c = (lo + hi) >> 1; if (U[c] <= u) lo = c; else hi = c; }
	const t1 = tb[lo];
	const sig = C.sig[lo];
	const du = u - U[lo];
	if (!(sig > 0) || !Number.isFinite(sig)) return t1 * Math.exp(du / CELL_SLOPE);
	const tk = CELL_C * sig / Math.log(CELL_F);
	if (t1 >= tk) return t1 + du * 2 * CELL_C * sig;
	const uk = CELL_SLOPE * Math.log(tk / t1);
	return du <= uk ? t1 * Math.exp(du / CELL_SLOPE) : tk + (du - uk) * 2 * CELL_C * sig;
}

/**
 * The cells of one axis, built as times ask for them. `opt`: `{rtol}` (1e-11,
 * as invertParabola), `atol` (0), `peak` (the response's peak; from the table
 * when left out), `maxEval` (CELL_MAX_EVAL). The counts in `.stats`: times
 * served by their cell, times that fell back to their own parabola, times
 * negligible by the saddle rule, cells built, cells that failed, and times
 * whose own parabola failed too and that went on to de Hoog's method.
 */
function makeCells(path, ax, opt) {
	// the tilted means of the table, falling, as saddleAt reads them; the
	// lattice's anchor u = 0 is the earliest of them
	const D = ax.D;
	const sm = ax.sm;
	const K = D.length;
	const tb = [];
	const sb = [];
	let last = Infinity;
	for (let k = 0; k < K; k++) {
		const d = D[k];
		if (!Number.isFinite(d)) { if (tb.length) break; continue; }
		if (!(d > 0) || !(d < last)) continue;
		tb.push(d);
		sb.push(sm[k]);
		last = d;
	}
	tb.reverse();
	sb.reverse();
	const nb = tb.length;
	const U = new Float64Array(nb);
	const sig = new Float64Array(Math.max(0, nb - 1));
	for (let m = 0; m + 1 < nb; m++) {
		const psi2 = (tb[m + 1] - tb[m]) / (sb[m] - sb[m + 1]);
		sig[m] = psi2 > 0 && Number.isFinite(psi2) ? Math.sqrt(psi2) : NaN;
		U[m + 1] = U[m] + cellSpan(tb[m], tb[m + 1], sig[m]);
	}
	let peak = opt && opt.peak > 0 ? opt.peak : 0;
	if (!peak) {
		let lp = -Infinity;
		for (const t of tb) lp = Math.max(lp, logEstimate(ax, t + ax.pr.shift));
		peak = Number.isFinite(lp) ? Math.exp(lp) : 0;
	}
	const np = CELL_PROBES.length;
	return {
		ax, tb, U, sig, map: new Map(), peak, infPe: path.infPe,
		rtol: (opt && opt.rtol) || 1e-11, atol: (opt && opt.atol) || 0, maxEval: (opt && opt.maxEval) || CELL_MAX_EVAL,
		stats: { shared: 0, fallback: 0, negligible: 0, cells: 0, failed: 0, dehoog: 0 },
		// scratch for the sweeps
		pt: new Float64Array(np), ph: new Float64Array(np), pa: new Float64Array(np), mods: new Float64Array(np),
		maxMod: new Float64Array(np), minEnv: new Float64Array(np), small: new Int32Array(np), last: new Float64Array(7 * np),
	};
}

/** One trapezoidal sweep of a cell's parabola, as parabolaSweep but with the
    terms of every probe time: it stops when they have died out at all of
    them, and a regrowth at any one is a regrowth. The nodes are appended to
    `nodes` with their level, each as s and the weighted factor
    T(s) (1 + 2 i kappa Y) dY/du of its term, scaled by e^E; the nodes are
    Y = u, or Y = c sinh(u) when c > 0. */
function cellSweep(path, ws, C, ss, kappa, step, off, level, acc, nodes, c) {
	const pr = C.ax.pr;
	const P = C.pt;
	const np = P.length;
	const mods = C.mods;
	const maxMod = C.maxMod;
	const minEnv = C.minEnv;
	const small = C.small;
	const last = C.last;
	maxMod.fill(0);
	minEnv.fill(Infinity);
	small.fill(0);
	last.fill(0);
	for (let k = 0; k < 20000; k++) {
		const u = off + k * (off ? 2 * step : step);
		const Y = c > 0 ? c * Math.sinh(u) : u;
		const jac = c > 0 ? c * Math.cosh(u) : 1;
		const wgt = u === 0 ? 0.5 : 1;
		const w = wgt * jac;
		const sr = ss - kappa * Y * Y;
		const si = Y;
		evalBlock(path, ws, pr.blk, sr, si, pr.kind);
		const Fr = RE;
		const Fi = IM;
		const E = ws.E;
		const q = 2 * kappa * Y;
		const gr = w * (Fr - Fi * q);
		const gi = w * (Fi + Fr * q);
		nodes.sr.push(sr);
		nodes.si.push(si);
		nodes.gr.push(gr);
		nodes.gi.push(gi);
		nodes.E.push(E);
		nodes.lev.push(level);
		for (let p = 0; p < np; p++) {
			const t = P[p];
			const ex = t * sr - E;
			let m = 0;
			if (ex > 700) {
				acc.bad = true;
				m = Infinity;
			} else if (!(ex < -740 || (Fr === 0 && Fi === 0))) {
				cexp(ex, t * si);
				const zr = RE * gr - IM * gi;
				const zi = RE * gi + IM * gr;
				acc.h[p] += zr;
				m = Math.hypot(zr, zi);
				acc.abs[p] += m;
				m /= wgt;
			}
			mods[p] = m;
		}
		if (Y === 0) {
			for (let p = 0; p < np; p++) maxMod[p] = Math.max(maxMod[p], mods[p]);
			continue;
		}
		let dead = k > 3;
		for (let p = 0; p < np; p++) {
			const m = mods[p];
			if (k > 3 && (m > 100 * maxMod[p] || (minEnv[p] < 1e-6 * maxMod[p] && m > 1e-3 * maxMod[p]))) {
				acc.regrow = true;
				return;
			}
			if (m > maxMod[p]) maxMod[p] = m;
			last[7 * p + k % 7] = m;
			if (k >= 7) {
				let env = 0;
				for (let r = 7 * p; r < 7 * p + 7; r++) if (last[r] > env) env = last[r];
				if (env < minEnv[p]) minEnv[p] = env;
			}
			if (m <= 1e-18 * maxMod[p]) small[p]++; else small[p] = 0;
			if (small[p] < 3) dead = false;
		}
		if (dead) return;
		if (acc.bad) return;
		if (ws.evaluations > acc.stop) break;
	}
	// out of nodes or budget before the terms died out: the sum is cut short
	acc.cut = true;
}

/** The sums of a cell's parabola: those of parabolaSums, at every probe time.
    Returns `{regrow}`, `{ok: false, why}` or `{ok: true, step, levels, strip,
    c, ss, nodes}`, step and strip in the node variable u, ss the vertex's
    node. */
function cellSums(path, ws, C, v, kappa, psi2, omega, stop, strip, c) {
	const pr = C.ax.pr;
	const P = C.pt;
	const np = P.length;
	const rtol = C.rtol;
	// the step as in parabolaSums, for the narrowest Gaussian and the fastest
	// phase of the cell
	let step;
	let stripU;
	if (c > 0) {
		stripU = PI / 4;
		step = sinhStep(c, 1.5 * PI / Math.sqrt(18.5 * psi2), omega);
	} else {
		step = 1.5 * PI / Math.sqrt(18.5 * psi2);
		if (omega > 0) step = Math.min(step, 0.5 * PI / omega);
		stripU = strip;
		step = Math.min(step, 0.5 * strip);
	}
	// K's node on the real axis a quarter step clear of s = -lambda, as in
	// parabolaSums
	const ss = pr.kind === INVENTORY ? offLambda(pr.blk, v, 0.25 * (c > 0 ? c * step : step)) : v;
	const acc = { h: C.ph, abs: C.pa, bad: false, regrow: false, cut: false, stop };
	acc.h.fill(0);
	acc.abs.fill(0);
	const nodes = { sr: [], si: [], gr: [], gi: [], E: [], lev: [] };
	cellSweep(path, ws, C, ss, kappa, step, 0, 0, acc, nodes, c);
	if (acc.regrow) return { regrow: true };
	if (acc.bad || acc.cut) return { ok: false, why: acc.bad ? 'overflow' : 'cut short' };
	const h = new Float64Array(np);
	for (let p = 0; p < np; p++) h[p] = acc.h[p] * step / PI;
	let agreed = 0;
	for (let level = 0; level < 12; level++) {
		if (ws.evaluations > stop) break;
		const half = step / 2;
		cellSweep(path, ws, C, ss, kappa, half, half, level + 1, acc, nodes, c);
		if (acc.regrow) return { regrow: true };
		if (acc.bad || acc.cut) return { ok: false, why: acc.bad ? 'overflow' : 'cut short' };
		step = half;
		const edge = 2 * Math.exp(-2 * PI * stripU / step);
		let all = true;
		for (let p = 0; p < np; p++) {
			const h2 = acc.h[p] * step / PI;
			const err = Math.abs(h2 - h[p]);
			h[p] = h2;
			const floor = 1e-15 * acc.abs[p] * step / PI + C.atol;
			const rel = err / Math.max(Math.abs(h2), 1e-300);
			const next = Math.max(rel * rel, edge);
			if (!(err <= floor || (level >= 1 && err <= rtol * Math.abs(h2) && next <= rtol)
				|| (!(c > 0) && step <= 0.3 * stripU && next <= rtol * 1e-2))) all = false;
		}
		agreed = all ? agreed + 1 : 0;
		if (all && (agreed >= 2 || !path.infPe)) return { ok: true, step, levels: level + 1, strip: stripU, c, ss, nodes };
	}
	return { ok: false, why: ws.evaluations > stop ? 'budget' : 'no agreement' };
}

/** Cell k of C: its parabola, built and summed at its probe times, and its
    nodes, the negligible ones dropped. `{ok: false}` when it cannot serve. */
function buildCell(path, ws, C, k) {
	const ax = C.ax;
	const pr = ax.pr;
	const tA = cellT(C, k);
	const tLo = cellT(C, k - 0.5);
	const tHi = cellT(C, k + 0.5);
	const fail = (why) => ({ ok: false, k, tLo, tA, tHi, why });
	if (!(tLo > 0) || !(tA > tLo) || !(tHi > tA) || !Number.isFinite(tHi)) return fail('lattice');
	const sad = saddleAt(ax, tA);
	if (!sad || sad.beyond || sad.w < -720) return fail('negligible');
	const n0 = ws.evaluations;
	const { v, loc, psi2 } = parabolaVertex(path, ws, ax, tA, sad);
	// psi(v) and the tilted mean D(v); K's vertex is the scan's saddle for the
	// middle time, as invertParabola takes it
	let psiV = sad.w - tA * v;
	let Dv = tA;
	if (loc) {
		if (!Number.isFinite(loc.psi) || !Number.isFinite(loc.D)) return fail('axis');
		psiV = loc.psi;
		Dv = loc.D;
	}
	// the phase turns at |t - D(v)| at the vertex: the larger of the two ends
	const omega = Math.max(Math.abs(tLo - Dv), Math.abs(tHi - Dv));
	let kappa = Math.max(psi2 / (2 * tA), 0.25 / (v - ax.s0));
	const rfc = pr.shift > 0 ? pr.blk.Rmin : 0;
	// the ridge at the earliest time: t (Re s - v) is largest there
	if (!path.infPe || !path.infX0) kappa = flattenForRidge(path, pr.blk, v, tLo, tLo * v + psiV, kappa, rfc);
	for (let p = 0; p < CELL_PROBES.length; p++) C.pt[p] = cellT(C, k + CELL_PROBES[p]);
	let res = null;
	for (let attempt = 0; attempt < 4; attempt++) {
		// the phase rates and the node map as for a single time, the Gaussian
		// the widest (earliest time) for the stretch and the narrowest (latest)
		// for the step; the members' own rates under plug flow as well (see
		// invertParabola)
		const strip = parabolaStrip(ax, v, kappa);
		const psi2lo = Math.max(psi2 * tLo / tA, psi2 + 2 * (tLo - Dv) * kappa);
		const psi2hi = psi2 * tHi / tA;
		const wY = Math.max(omega, pathFrequency(path, pr.blk, v, tLo, kappa, tLo * v + psiV - 25, rfc, tHi, strip));
		const wU = Math.max(omega * Math.sqrt(strip * strip + 50 / psi2lo), RATE_U);
		const c = nodeScale(strip, psi2lo, 1.5 * PI / Math.sqrt(18.5 * psi2hi), wY, wU);
		res = cellSums(path, ws, C, v, kappa, psi2hi, c > 0 ? wU : wY, n0 + C.maxEval, strip, c);
		if (!res.regrow) break;
		kappa /= 8;
	}
	if (!res.ok) return fail(res.regrow ? 'regrowth' : res.why);
	// drop the nodes whose terms stay below CELL_PRUNE times the vertex's (the
	// first node) at both ends: ln |term| is linear in t
	const nd = res.nodes;
	const nn = nd.sr.length;
	const lg = (q) => Math.log(Math.hypot(nd.gr[q], nd.gi[q])) - nd.E[q];
	const lg0 = lg(0) + Math.LN2; // the vertex's weight 1/2 undone
	const keep = [];
	for (let q = 0; q < nn; q++) {
		const l = lg(q);
		const d = nd.sr[q] - res.ss;
		if (q === 0 || !(tLo * d + l < lg0 + LN_PRUNE && tHi * d + l < lg0 + LN_PRUNE)) keep.push(q);
	}
	const n = keep.length;
	const cell = {
		ok: true, k, tLo, tHi, tA, v, step: res.step, levels: res.levels, strip: res.strip, c: res.c, n,
		sr: new Float64Array(n), si: new Float64Array(n), gr: new Float64Array(n), gi: new Float64Array(n),
		ag: new Float64Array(n), la: new Float64Array(n), mE: new Float64Array(n), lev: new Uint8Array(n),
	};
	for (let r = 0; r < n; r++) {
		const q = keep[r];
		cell.sr[r] = nd.sr[q];
		cell.si[r] = nd.si[q];
		cell.gr[r] = nd.gr[q];
		cell.gi[r] = nd.gi[q];
		cell.ag[r] = Math.hypot(nd.gr[q], nd.gi[q]);
		cell.la[r] = Math.log(cell.ag[r]);
		cell.mE[r] = -nd.E[q];
		cell.lev[r] = nd.lev[q];
	}
	return cell;
}

/** h, h' and h'' at time tt from a cell's nodes, or null when the result does
    not pass: the error estimate is that of parabolaSums from the last two
    levels (under plug flow also the two before), and the sum of the moduli
    must stay within CELL_COND of the answer unless the terms are negligible
    against the response's peak. */
function cellSample(C, cell, tt) {
	const n = cell.n;
	const sr = cell.sr;
	const si = cell.si;
	const gr = cell.gr;
	const gi = cell.gi;
	const ag = cell.ag;
	const la = cell.la;
	const mE = cell.mE;
	const lev = cell.lev;
	const L = cell.levels;
	// a term below CELL_PRUNE times the vertex's (the first node) at tt is
	// left out, as the pruning leaves out those below it at both ends
	const low = tt * sr[0] + mE[0] + la[0] + LN_PRUNE;
	let h = 0;
	let d1 = 0;
	let d2 = 0;
	let a = 0;
	let h1 = 0;
	let a1 = 0;
	let h2 = 0;
	for (let q = 0; q < n; q++) {
		const ex = tt * sr[q] + mE[q];
		if (ex > 700) return null;
		if (ex < -740 || ex + la[q] < low) continue;
		const e = Math.exp(ex);
		const ph = tt * si[q];
		const er = e * Math.cos(ph);
		const ei = e * Math.sin(ph);
		const zr = er * gr[q] - ei * gi[q];
		const zi = er * gi[q] + ei * gr[q];
		const yr = sr[q] * zr - si[q] * zi;
		const yi = sr[q] * zi + si[q] * zr;
		const m = e * ag[q];
		h += zr;
		d1 += yr;
		d2 += sr[q] * yr - si[q] * yi;
		a += m;
		if (lev[q] < L) {
			h1 += zr;
			a1 += m;
			if (lev[q] < L - 1) h2 += zr;
		}
	}
	const rtol = C.rtol;
	const strip = cell.strip;
	// the test of parabolaSums on level l (step st) against l - 1
	const passes = (hn, hp, an, st, level) => {
		const err = Math.abs(hn - hp);
		const floor = 1e-15 * an + C.atol;
		const rel = err / Math.max(Math.abs(hn), 1e-300);
		const next = Math.max(rel * rel, 2 * Math.exp(-2 * PI * strip / st));
		const ok = err <= floor || (level >= 1 && err <= rtol * Math.abs(hn) && next <= rtol)
			|| (!(cell.c > 0) && st <= 0.3 * strip && next <= rtol * 1e-2);
		return ok ? Math.min(err, next * Math.abs(hn) + floor) : -1;
	};
	const st = cell.step;
	const c = st / PI;
	const H = h * c;
	const H1 = h1 * 2 * c;
	const A = a * c;
	const err = passes(H, H1, A, st, L - 1);
	if (!(err >= 0)) return null;
	if (C.infPe && !(passes(H1, h2 * 4 * c, a1 * 2 * c, 2 * st, L - 2) >= 0)) return null;
	const cond = A / Math.max(Math.abs(H), 1e-300);
	if (!Number.isFinite(H) || !(cond <= CELL_COND || A <= CELL_NEGLIGIBLE * C.peak)) return null;
	if (err > 1e-6 * Math.abs(H) + C.atol) return null;
	return { h: H, dh: d1 * c, d2: d2 * c, err, cond };
}

/**
 * The response and its first two derivatives at t from the shared parabola of
 * t's cell (C from makeCells), building the cell when it is first asked for:
 * `{h, dh, d2, err, cond, cell}`, the zeros of invertParabola where the
 * saddle rule makes the response negligible, or null when the cell cannot
 * serve t (then t needs its own parabola).
 */
function invertShared(path, ws, C, t) {
	const ax = C.ax;
	const tt = t - ax.pr.shift;
	if (!(tt > 0)) { C.stats.negligible++; return ZERO; }
	const sad = saddleAt(ax, tt);
	if (!sad || sad.beyond || sad.w < -720) { C.stats.negligible++; return { ...ZERO, negligible: true }; }
	const k = Math.floor(cellU(C, tt) + 0.5);
	let cell = C.map.get(k);
	if (!cell) {
		cell = buildCell(path, ws, C, k);
		C.map.set(k, cell);
		C.stats.cells++;
		if (!cell.ok) C.stats.failed++;
	}
	const r = cell.ok && Number.isFinite(k) ? cellSample(C, cell, tt) : null;
	if (r) { C.stats.shared++; r.cell = k; } else C.stats.fallback++;
	return r;
}

/** The fixed Talbot sum for h, h' and h'' with scale r and M nodes. */
function talbotSum(path, ws, pr, t, r, M) {
	let sh = 0;
	let sd = 0;
	let s2 = 0;
	let bad = false;
	for (let k = 0; k < M; k++) {
		let sr;
		let si;
		let sig;
		if (k === 0) {
			sr = r; si = 0; sig = 0;
		} else {
			const th = k * PI / M;
			const cot = Math.cos(th) / Math.sin(th);
			sr = r * th * cot; si = r * th; sig = th + (th * cot - 1) * cot;
		}
		evalBlock(path, ws, pr.blk, sr, si, pr.kind);
		const Fr = RE;
		const Fi = IM;
		if (Fr === 0 && Fi === 0) continue;
		const ex = t * sr - ws.E;
		if (ex < -740) continue;
		if (ex > 700) { bad = true; continue; }
		cexp(ex, t * si);
		const er = RE;
		const ei = IM;
		const ar = er * Fr - ei * Fi;
		const ai = er * Fi + ei * Fr;
		const tr = ar - ai * sig;
		const ti = ai + ar * sig;
		const w = k === 0 ? 0.5 : 1;
		const yr = sr * tr - si * ti;
		const yi = sr * ti + si * tr;
		sh += w * tr;
		sd += w * yr;
		s2 += w * (sr * yr - si * yi);
	}
	const c = r / M;
	return bad ? [NaN, NaN, NaN] : [c * sh, c * sd, c * s2];
}

/** The fixed Talbot contour (Abate and Valko), scaled out to the saddle when
    that lies right of 2M/(5t). */
function invertTalbot(path, ws, ax, t, opt) {
	const pr = ax.pr;
	const M0 = (opt && opt.M) || M_DEFAULT;
	const tt = t - pr.shift;
	if (!(tt > 0)) return { h: 0, dh: 0, d2: 0, r: 0, M: 0, saddle: false };
	const rdef = 2 * M0 / (5 * tt);
	const sad = saddleAt(ax, tt);
	let r = rdef;
	let M = M0;
	let useSad = false;
	if (sad && sad.s > rdef) {
		if (sad.beyond || sad.w < -720) return { h: 0, dh: 0, d2: 0, r: sad.s, M: 0, saddle: true };
		useSad = true;
		r = sad.s;
		const need = Number.isFinite(sad.psi2) && sad.psi2 > 0 ? 2.2 * r * Math.sqrt(sad.psi2) : 0;
		M = Math.min(TALBOT_M_MAX, Math.max(M0, Math.ceil(need + 0.6 * M0)));
	}
	const [h, dh, d2] = talbotSum(path, ws, pr, tt, r, M);
	return { h, dh, d2, r, M, saddle: useSad };
}

/**
 * De Hoog's M for this path: a front as sharp as dispersion makes it (width
 * about TW sqrt(2/Pe)) needs about 1.2 sqrt(Pe) terms, 24 to 160; with the
 * axis and a time, also 1.7 t/sigma, sigma = sqrt(psi'') the spread of the
 * response tilted to its saddle there (under plug flow, a matrix that fills at
 * once makes a spike that Pe says nothing of).
 */
function deHoogTerms(path, ax, t) {
	let m = path.infPe ? 24 : Math.max(24, Math.ceil(1.2 * Math.sqrt(path.Pe)));
	if (ax) {
		const tt = t - ax.pr.shift;
		const sad = tt > 0 ? saddleAt(ax, tt) : null;
		if (sad && !sad.beyond && sad.psi2 > 0) m = Math.max(m, Math.ceil(1.7 * tt / Math.sqrt(sad.psi2)));
	}
	return Math.min(160, m);
}

/**
 * De Hoog, Knight and Stokes (1982): the trapezoidal rule on the Bromwich
 * line Re s = gamma with period 2T, accelerated by the quotient-difference
 * continued fraction. The independent check on the parabola, and where it
 * finds no clear way. `opt.deriv` inverts s^deriv times the transform: 1 and
 * 2 the derivatives, -1 the integral from 0 to t.
 */
function invertDeHoog(path, ws, pr, t, opt) {
	const tt = t - pr.shift;
	if (!(tt > 0)) return 0;
	const M = (opt && opt.M) || 24;
	const tol = (opt && opt.tol) || 1e-12;
	const deriv = (opt && opt.deriv) ? (opt.deriv === true ? 1 : opt.deriv) : 0;
	const T = ((opt && opt.Tfac) || 2) * tt;
	const gamma = -Math.log(tol) / (2 * T);
	const K = 2 * M;
	const ar = new Float64Array(K + 1);
	const ai = new Float64Array(K + 1);
	let E0 = 0;
	let Kuse = K;
	for (let k = 0; k <= K; k++) {
		evalBlock(path, ws, pr.blk, gamma, k * PI / T, pr.kind);
		const Fr = RE;
		const Fi = IM;
		if (k === 0) E0 = ws.E;
		const sc = Math.exp(E0 - ws.E);
		ar[k] = Fr * sc;
		ai[k] = Fi * sc;
		for (let q = 0; q < deriv; q++) {
			const sr = gamma;
			const si = k * PI / T;
			const xr = ar[k];
			const xi = ai[k];
			ar[k] = sr * xr - si * xi;
			ai[k] = sr * xi + si * xr;
		}
		for (let q = 0; q > deriv; q--) {
			cdiv(ar[k], ai[k], gamma, k * PI / T);
			ar[k] = RE;
			ai[k] = IM;
		}
		if (!(ar[k] !== 0 || ai[k] !== 0) || !Number.isFinite(ar[k]) || !Number.isFinite(ai[k])) { Kuse = k - 1; break; }
	}
	if (Kuse % 2 === 1) Kuse--;
	if (Kuse < 2) return NaN;
	const Mu = Kuse / 2;
	ar[0] *= 0.5;
	ai[0] *= 0.5;
	const qr = new Float64Array(Kuse);
	const qi = new Float64Array(Kuse);
	const er = new Float64Array(Kuse + 1);
	const ei = new Float64Array(Kuse + 1);
	const dr = new Float64Array(Kuse + 1);
	const di = new Float64Array(Kuse + 1);
	for (let k = 0; k < Kuse; k++) { cdiv(ar[k + 1], ai[k + 1], ar[k], ai[k]); qr[k] = RE; qi[k] = IM; }
	dr[0] = ar[0];
	di[0] = ai[0];
	for (let r = 1; r <= Mu; r++) {
		for (let k = 0; k <= Kuse - 2 * r; k++) {
			er[k] = qr[k + 1] - qr[k] + er[k + 1];
			ei[k] = qi[k + 1] - qi[k] + ei[k + 1];
		}
		dr[2 * r - 1] = -qr[0];
		di[2 * r - 1] = -qi[0];
		dr[2 * r] = -er[0];
		di[2 * r] = -ei[0];
		if (r < Mu) {
			for (let k = 0; k < Kuse - 2 * r; k++) {
				const xr = qr[k + 1] * er[k + 1] - qi[k + 1] * ei[k + 1];
				const xi = qr[k + 1] * ei[k + 1] + qi[k + 1] * er[k + 1];
				cdiv(xr, xi, er[k], ei[k]);
				qr[k] = RE;
				qi[k] = IM;
			}
		}
	}
	// the continued fraction at z = exp(i pi t/T)
	const zr = Math.cos(PI * tt / T);
	const zi = Math.sin(PI * tt / T);
	let A2r = 0;
	let A2i = 0;
	let A1r = dr[0];
	let A1i = di[0];
	let B2r = 1;
	let B2i = 0;
	let B1r = 1;
	let B1i = 0;
	for (let k = 1; k <= Kuse; k++) {
		const cr = dr[k] * zr - di[k] * zi;
		const ci = dr[k] * zi + di[k] * zr;
		let Ar;
		let Ai;
		let Br;
		let Bi;
		if (k < Kuse) {
			Ar = A1r + cr * A2r - ci * A2i;
			Ai = A1i + cr * A2i + ci * A2r;
			Br = B1r + cr * B2r - ci * B2i;
			Bi = B1i + cr * B2i + ci * B2r;
		} else {
			// the remainder estimate of de Hoog et al.
			const d1r = dr[Kuse - 1] - dr[Kuse];
			const d1i = di[Kuse - 1] - di[Kuse];
			const hr = 0.5 * (1 + d1r * zr - d1i * zi);
			const hi = 0.5 * (d1r * zi + d1i * zr);
			const h2r = hr * hr - hi * hi;
			const h2i = 2 * hr * hi;
			cdiv(cr, ci, h2r, h2i);
			csqrt(1 + RE, IM);
			const Rr = -(hr * (1 - RE) - hi * (-IM));
			const Ri = -(hr * (-IM) + hi * (1 - RE));
			Ar = A1r + Rr * A2r - Ri * A2i;
			Ai = A1i + Rr * A2i + Ri * A2r;
			Br = B1r + Rr * B2r - Ri * B2i;
			Bi = B1i + Rr * B2i + Ri * B2r;
		}
		A2r = A1r; A2i = A1i; A1r = Ar; A1i = Ai;
		B2r = B1r; B2i = B1i; B1r = Br; B1i = Bi;
	}
	cdiv(A1r, A1i, B1r, B1i);
	return Math.exp(gamma * tt - E0) / T * RE;
}

/* ==========================================================================
   Unit responses on adaptive grids

   Each response is sampled with its first two derivatives, so a quintic
   Hermite piece represents it between samples. The grid starts from the
   saddle-point estimate of where the response matters and is refined until
   the interpolant predicts every new midpoint. An inventory response starts
   at t = 0 with its exact values there: one unit of j held, nothing yet
   released, k' = -Lambda k and k'' = Lambda^2 k.
   ========================================================================== */

const RESP_PER_DECADE = 10;
const RESP_RTOL = 2e-8;
const RESP_ATOL = 1e-13;
const RESP_MAXPTS = 6000;
const T_CAP = 1e12;
const EPS = 2.220446049250313e-16;

/** The saddle-point estimate of the response's log at t. */
function logEstimate(ax, t) {
	const tt = t - ax.pr.shift;
	if (!(tt > 0)) return -Infinity;
	const sad = saddleAt(ax, tt);
	if (!sad || sad.beyond || !Number.isFinite(sad.w)) return -Infinity;
	const c = Number.isFinite(sad.psi2) && sad.psi2 > 0 ? -0.5 * Math.log(2 * PI * sad.psi2) : 0;
	return sad.w + c;
}

/** Where a response is worth computing, from the estimate on a log grid:
    tLo (e^-62 below the peak), tHi (e^-72 below, or tMax), and tTail (the
    last time above 1e-9 of the peak). */
function responseSupport(ax, tMin, tMax) {
	// Under plug flow nothing arrives before the delay d: the grid is
	// logarithmic in t - d, or a response far narrower than d (a matrix that
	// fills at once) falls between its points.
	const d = ax.pr.shift;
	const uMin = tMin - d;
	const uMax = tMax - d;
	const per = 16;
	const n = Math.max(2, Math.ceil(Math.log10(uMax / uMin) * per) + 1);
	const ts = new Float64Array(n);
	const est = new Float64Array(n);
	let wmax = -Infinity;
	let kmax = -1;
	for (let k = 0; k < n; k++) {
		ts[k] = d + uMin * (uMax / uMin) ** (k / (n - 1));
		est[k] = logEstimate(ax, ts[k]);
		if (est[k] > wmax) { wmax = est[k]; kmax = k; }
	}
	if (!Number.isFinite(wmax)) return null;
	let kLo = 0;
	while (kLo < n && !(est[kLo] > wmax - 62)) kLo++;
	let kHi = n - 1;
	while (kHi > kmax && !(est[kHi] > wmax - 72)) kHi--;
	let kTail = n - 1;
	while (kTail > kmax && !(est[kTail] > wmax - 20.7)) kTail--;
	return {
		tLo: ts[Math.max(0, kLo - 1)], tHi: kHi >= n - 1 ? tMax : ts[Math.min(n - 1, kHi + 1)],
		tPeak: ts[kmax], logPeak: wmax,
		tTail: kTail >= n - 1 ? tMax : ts[Math.min(n - 1, kTail + 1)],
	};
}

/** One sample [h, h', h'', cond, err] of a pair's inverse, by the chosen
    method; the parabola where the other two break down. `cells` (from
    makeCells) are the axis's shared parabolas, for the default method. */
function sample(path, ws, ax, t, method, atol, hint, cells) {
	if (method === 'talbot') {
		const r = invertTalbot(path, ws, ax, t);
		if (Number.isFinite(r.h) && Number.isFinite(r.dh) && Number.isFinite(r.d2)) return [r.h, r.dh, r.d2, 1, 0];
	} else if (method === 'dehoog') {
		const mH = deHoogTerms(path, ax, t);
		const v = [
			invertDeHoog(path, ws, ax.pr, t, { M: mH }), invertDeHoog(path, ws, ax.pr, t, { M: mH, deriv: 1 }),
			invertDeHoog(path, ws, ax.pr, t, { M: mH, deriv: 2 }), 1, 0,
		];
		if (Number.isFinite(v[0]) && Number.isFinite(v[1]) && Number.isFinite(v[2])) return v;
	}
	// The default, and where the other two break down. A response whose
	// samples mostly fell back to de Hoog (below) goes there first.
	if (hint) hint.tries++;
	// the shared parabola of t's cell, and t's own where that cannot serve
	if (cells) {
		const s = invertShared(path, ws, cells, t);
		if (s) return [s.h, s.dh, s.d2, s.cond || 1, s.err];
	}
	const direct = hint && hint.tries > 16 && hint.fails > 0.75 * hint.tries;
	const r = direct ? { h: NaN, err: Infinity } : invertParabola(path, ws, ax, t, { atol });
	if (Number.isFinite(r.h) && !(r.err > 1e-6 * Math.abs(r.h) + atol)) return [r.h, r.dh, r.d2, r.cond || 1, r.err];
	if (hint) hint.fails++;
	if (cells) cells.stats.dehoog++;
	// A path that found no clear way, or did not converge within its budget:
	// de Hoog's Bromwich line (where |T| stays below T(Re s), so no sum of
	// huge terms), with twice the terms the spread asks for; the parabola
	// only when it has an error estimate below de Hoog's.
	const m1 = deHoogTerms(path, ax, t);
	const m2 = Math.min(2 * m1, 320);
	const a = invertDeHoog(path, ws, ax.pr, t, { M: m1 });
	const b = invertDeHoog(path, ws, ax.pr, t, { M: m2 });
	const eH = Math.abs(a - b);
	if (Number.isFinite(b) && (!Number.isFinite(r.h) || !Number.isFinite(r.err) || eH < r.err)) {
		const d1 = invertDeHoog(path, ws, ax.pr, t, { M: m2, deriv: 1 });
		const d2 = invertDeHoog(path, ws, ax.pr, t, { M: m2, deriv: 2 });
		if (Number.isFinite(d1) && Number.isFinite(d2)) return [b, d1, d2, 1, eH + atol];
	}
	if (Number.isFinite(r.h)) return [r.h, r.dh, r.d2, r.cond || 1, r.err];
	if (direct) {
		const s2 = invertParabola(path, ws, ax, t, { atol });
		if (Number.isFinite(s2.h)) return [s2.h, s2.dh, s2.d2, s2.cond || 1, s2.err];
	}
	return [0, 0, 0, Infinity, Infinity];
}

/**
 * The block's e^(-Lambda t), entry (i, j), and its first two derivatives:
 * the Bateman solution, what the path would hold of i if nothing left it.
 * A function of the triangular matrix Lambda like the others, so equal and
 * close decay constants cost nothing.
 */
function bateman(path, ws, blk, t) {
	const m = blk.m;
	const last = m - 1;
	const L = (p, q) => (p === q ? blk.lam[p] : blk.A[p * m + q]);
	const col = ws.vr;
	if (!(t > 0)) {
		for (let p = 0; p < m; p++) col[p] = p === 0 ? 1 : 0;
	} else {
		const dd = ws.dd;
		dd.kind = 2;
		dd.t = t;
		for (let p = 0; p < m; p++) {
			dd.zr[p] = blk.lam[p];
			dd.zi[p] = 0;
			dd.fr[p] = Math.exp(-t * blk.lam[p]);
			dd.fi[p] = 0;
			for (let q = 0; q < p; q++) { ws.Lr[p * m + q] = blk.A[p * m + q]; ws.Li[p * m + q] = 0; }
		}
		triFun(path, ws, m, ws.Lr, ws.Li, ws.Tr, ws.Ti, NEED_COLUMN);
		for (let p = 0; p < m; p++) col[p] = ws.Tr[p * m];
	}
	let b1 = 0;
	let b2 = 0;
	for (let k = 0; k < m; k++) {
		b1 += L(last, k) * col[k];
		let u = 0;
		for (let l = 0; l <= k; l++) u += L(k, l) * col[l];
		b2 += L(last, k) * u;
	}
	return [col[last], -b1, b2];
}

/**
 * One sample of an inventory response, k = L^-1[A^-1 (I - T)].
 *
 * Inverted whole, K is two terms with different saddles: A^-1, whose inverse
 * is the Bateman solution, and A^-1 T, which carries the path's delay. A
 * contour through K's saddle while the path still holds most of the pulse is
 * right for the first and wrong for the second, whose terms then grow like
 * e^(Pe/2) along it -- Pe = 300 loses every digit. So, while k is at least
 * half of e^(-Lambda t), k = e^(-Lambda t) - c, c the inverse of A^-1 T
 * through its own saddle, and the subtraction costs at most a bit. Later
 * that difference cancels more and more, while K inverted whole gets better
 * as the delay falls behind its saddle: both are worked out, and the one
 * with the smaller error estimate kept. `cells` are the shared parabolas of
 * the two axes, [axC's, axK's], or null.
 */
function sampleInventory(path, ws, axC, axK, t, method, atol, hint, cells) {
	const [b0, b1, b2] = bateman(path, ws, axC.pr.blk, t);
	const [c0, c1, c2, cc, ce] = sample(path, ws, axC, t, method, atol, hint, cells && cells[0]);
	const k0 = b0 - c0;
	const errSplit = ce + EPS * (cc * Math.abs(c0) + 2 * Math.abs(b0));
	const split = [k0, b1 - c1, b2 - c2, cc, errSplit];
	if (Math.abs(k0) >= 0.5 * Math.abs(b0)) return split;
	const r = sample(path, ws, axK, t, method, atol, null, cells && cells[1]);
	const errWhole = r[4] + EPS * r[3] * Math.abs(r[0]);
	return errWhole < errSplit ? r : split;
}

/** Quintic Hermite from values, first and second derivatives at the ends. */
function hermite5(ta, ya, da, ea, tb, yb, db, eb, t) {
	const d = tb - ta;
	const x = (t - ta) / d;
	const x2 = x * x;
	const x3 = x2 * x;
	const x4 = x3 * x;
	const x5 = x4 * x;
	const h0 = 1 - 10 * x3 + 15 * x4 - 6 * x5;
	const h1 = x - 6 * x3 + 8 * x4 - 3 * x5;
	const h2 = 0.5 * (x2 - 3 * x3 + 3 * x4 - x5);
	const h4 = -4 * x3 + 7 * x4 - 3 * x5;
	const h5 = 0.5 * (x3 - 2 * x4 + x5);
	return h0 * ya + d * h1 * da + d * d * h2 * ea + (1 - h0) * yb + d * h4 * db + d * d * h5 * eb;
}

/**
 * A response on [tA, tB] from `sampler(t, atol, hint) -> [h, h', h'', cond,
 * err]`, led by `start` = [h, h', h''] at t = 0 when the response has a value
 * there. `hint` counts the samples tried and those that fell back to de Hoog.
 */
function computeResponse(sampler, start, tA, tB, opt) {
	const method = (opt && opt.method) || 'parabola';
	const rtol = (opt && opt.rtol) || RESP_RTOL;
	// the absolute floor, relative to the peak, each method can hold in the tails
	const atolRel = method === 'parabola' ? RESP_ATOL : method === 'talbot' ? 1e-9 : 1e-8;
	const maxPts = (opt && opt.maxPts) || RESP_MAXPTS;
	const per = (opt && opt.perDecade) || RESP_PER_DECADE;
	// logarithmic in t - d, d the plug-flow delay (see responseSupport)
	const d = (opt && opt.delay) || 0;
	const n0 = Math.max(16, Math.ceil(Math.log10((tB - d) / (tA - d)) * per) + 1);
	let T = [];
	let H = [];
	let D = [];
	let D2 = [];
	let peak = 0;
	let maxCond = 1;
	let maxErr = 0;
	const atol = opt && opt.peakEstimate > 0 ? 1e-3 * RESP_ATOL * opt.peakEstimate : 0;
	const hint = { tries: 0, fails: 0 };
	if (start) {
		T.push(0); H.push(start[0]); D.push(start[1]); D2.push(start[2]);
		peak = Math.abs(start[0]);
	}
	for (let k = 0; k < n0; k++) {
		const t = d + (tA - d) * ((tB - d) / (tA - d)) ** (k / (n0 - 1));
		const [h, dh, d2, c, e] = sampler(t, atol, hint);
		if (e > maxErr) maxErr = e;
		T.push(t); H.push(h); D.push(dh); D2.push(d2);
		if (Math.abs(h) > peak) peak = Math.abs(h);
		if (c > maxCond) maxCond = c;
	}
	let flag = new Array(T.length - 1).fill(true);
	for (let pass = 0; pass < 30; pass++) {
		const nT = [T[0]];
		const nH = [H[0]];
		const nD = [D[0]];
		const nD2 = [D2[0]];
		const nF = [];
		let inserted = false;
		for (let k = 0; k + 1 < T.length; k++) {
			if (flag[k] && T.length + nT.length < 2 * maxPts && (T[k] === d || (T[k + 1] - d) / (T[k] - d) > 1 + 1e-9)) {
				const tm = T[k] === d ? d + 0.5 * (T[k + 1] - d) : d + Math.sqrt((T[k] - d) * (T[k + 1] - d));
				const [h, dh, d2, c, e] = sampler(tm, Math.max(atol, 1e-3 * RESP_ATOL * peak), hint);
				if (e > maxErr) maxErr = e;
				if (Math.abs(h) > peak) peak = Math.abs(h);
				if (c > maxCond) maxCond = c;
				const p = hermite5(T[k], H[k], D[k], D2[k], T[k + 1], H[k + 1], D[k + 1], D2[k + 1], tm);
				// where de Hoog made most samples, to what de Hoog can deliver
				const dh0 = hint.fails > 0.5 * hint.tries;
				const ok = Math.abs(h - p) <= (dh0 ? Math.max(rtol, 1e-7) : rtol) * Math.abs(h)
					+ (dh0 ? Math.max(atolRel, 1e-10) : atolRel) * peak;
				nT.push(tm); nH.push(h); nD.push(dh); nD2.push(d2);
				nF.push(!ok, !ok);
				if (!ok) inserted = true;
			} else {
				nF.push(false);
			}
			nT.push(T[k + 1]); nH.push(H[k + 1]); nD.push(D[k + 1]); nD2.push(D2[k + 1]);
		}
		T = nT; H = nH; D = nD; D2 = nD2; flag = nF;
		if (!inserted || T.length >= maxPts) break;
	}
	const n = T.length;
	const t = Float64Array.from(T);
	const h = Float64Array.from(H);
	const dh = Float64Array.from(D);
	const d2h = Float64Array.from(D2);
	let integral = 0;
	let tPeak = t[0];
	let pk = -Infinity;
	for (let k = 0; k < n; k++) if (h[k] > pk) { pk = h[k]; tPeak = t[k]; }
	for (let k = 0; k + 1 < n; k++) {
		const d = t[k + 1] - t[k];
		integral += d * (0.5 * (h[k] + h[k + 1]) + d * (dh[k] - dh[k + 1]) / 10 + d * d * (d2h[k] + d2h[k + 1]) / 120);
	}
	return {
		t, h, dh, d2h, peak: Math.max(pk, 0), tPeak, integral, maxCond, maxErr: maxErr / Math.max(pk, 1e-300),
	};
}

function pairOf(path, i, j, kind) {
	const blk = blockOf(path, i, j);
	if (!blk) return null;
	const k = kindOf(kind);
	return { blk, kind: k, shift: k !== INVENTORY && path.infPe ? path.tw * blk.Rmin : 0 };
}

/** The real axis of a pair, scanned once for everything asked of it. */
function axisOf(path, pr) {
	const key = `${pr.blk.i},${pr.blk.j},${pr.kind}`;
	path.axes ??= new Map();
	let ax = path.axes.get(key);
	if (!ax) {
		const tLo = pr.shift > 0 ? pr.shift * (1 + 1e-9) : path.tw * 1e-6;
		ax = realAxis(path, path.ws, pr, tLo, T_CAP);
		ax.tLo = tLo;
		path.axes.set(key, ax);
	}
	return ax;
}

/** The two axes an inventory response is sampled on. */
function inventoryAxes(path, i, j) {
	return [axisOf(path, pairOf(path, i, j, DECAYED)), axisOf(path, pairOf(path, i, j, INVENTORY))];
}

/**
 * The response of i to a unit pulse of j at t = 0 -- the release rate, or,
 * with `kind: 'inventory'`, what the path holds -- and its first two
 * derivatives, inverted at t directly: on a parabola of its own, and where
 * that one's error estimate does not pass, by de Hoog's method at twice its
 * terms (as a tabulated response's samples are, without the shared
 * parabolas), with `cond` and `err`.
 *
 * @param {object} opt `{kind, method, atol}`
 * @returns {{h: number, dh: number, d2: number}}
 */
export function responseAt(path, i, j, t, opt = {}) {
	const pr = pairOf(path, i, j, opt.kind);
	if (!pr) return { h: 0, dh: 0, d2: 0 };
	const ws = path.ws;
	if (pr.kind === INVENTORY) {
		if (!(t > 0)) {
			const [h, dh, d2] = bateman(path, ws, pr.blk, 0);
			return { h, dh, d2 };
		}
		const [axC, axK] = inventoryAxes(path, i, j);
		const [h, dh, d2, cond, err] = sampleInventory(path, ws, axC, axK, t, opt.method, 0);
		return { h, dh, d2, cond, err };
	}
	if (opt.method === 'dehoog') {
		return {
			h: invertDeHoog(path, ws, pr, t, opt), dh: invertDeHoog(path, ws, pr, t, { ...opt, deriv: 1 }),
			d2: invertDeHoog(path, ws, pr, t, { ...opt, deriv: 2 }),
		};
	}
	const ax = axisOf(path, pr);
	if (opt.method === 'talbot') return invertTalbot(path, ws, ax, t, opt);
	const [h, dh, d2, cond, err] = sample(path, ws, ax, t, 'parabola', opt.atol || 0);
	return { h, dh, d2, cond, err };
}

/**
 * Under plug flow a response starts at its delay, and a daughter born near the
 * outlet, or a nuclide the matrix barely holds, arrives within a hair of it:
 * what arrives before the response's first time (de Hoog's inversion of T/s
 * there) is kept as `m0`, added to the integral and released as a point mass
 * at that first time (see `convolve`, and the path's runtime).
 */
function addEarlyMass(path, pr, resp) {
	resp.m0 = 0;
	if (!path.infPe || pr.kind === INVENTORY || resp.t.length < 2) return;
	const S = invertDeHoog(path, path.ws, pr, resp.t[0], { M: deHoogTerms(path), deriv: -1 });
	if (S > 0 && Number.isFinite(S)) {
		resp.m0 = S;
		resp.integral += S;
	}
}

/**
 * A release response's mass balance: its integral against what leaves the path
 * by its last time -- T(0) when the rest is negligible, and otherwise the
 * integral of the response from 0 to that time (de Hoog's inversion of T/s).
 * The rest after time t is at most e^w, w = s t + psi(s) with the saddle s < 0
 * for t (the Chernoff bound). Nothing is checked when T(0) is below 1e-30, and
 * the difference is taken relative to T(0) or 1e-10, whichever is larger: a
 * daughter's T(0) of 1e-13 comes out of a sum of terms of order one, good to
 * about 1e-16. Returns `{ok, checked, expected, rel}`.
 */
function massBalance(path, ax, resp, tol) {
	const T0 = resp.T0;
	if (!(Math.abs(T0) > 1e-30)) return { ok: true, checked: false, expected: T0, rel: 0 };
	let expected = T0;
	const n = resp.t.length;
	if (n) {
		const tl = resp.t[n - 1];
		const tt = tl - ax.pr.shift;
		const sad = tt > 0 ? saddleAt(ax, tt) : null;
		const rest = sad && !sad.beyond && sad.s <= 0 ? Math.exp(sad.w) : Infinity;
		if (!(rest <= 1e-10 * Math.abs(T0))) {
			const S = invertDeHoog(path, path.ws, ax.pr, tl, { M: deHoogTerms(path), deriv: -1 });
			if (Number.isFinite(S)) expected = S;
		}
	}
	const rel = Math.abs(resp.integral - expected) / Math.max(Math.abs(T0), 1e-10);
	return { ok: rel <= tol, checked: true, expected, rel };
}

/**
 * One unit response, tabulated on an adaptive grid over [0, tMax]:
 * `{i, j, kind, t, h, dh, d2h, peak, tPeak, integral, T0}`, and for a release
 * `m0`, `expected`, `balanced` and `rel`.
 *
 * `integral` is the Hermite pieces' exact integral (and, under plug flow, what
 * arrives before the first time, `m0`): for a release it is held to what
 * leaves the path by its last time (`expected`, T(0) when the rest is
 * negligible), and one that misses is worked out again from far earlier on a
 * grid twice as fine; `balanced` false is a response that missed even so,
 * `rel` by how much, which the caller has to say. For an inventory `integral`
 * is the time the pulse spends in the path, when that is finite.
 *
 * The default inversion samples nearby times on shared parabolas (see
 * `makeCells`), and `shared` counts how the samples were taken, over the
 * response's axes and both passes when a first missed its balance.
 * `shared: false` gives every sample a parabola of its own (for comparisons);
 * `shared` is then null, as it is for the other methods.
 *
 * @param {object} opt `{kind, tMax, method, rtol, perDecade, maxPts, shared}`
 */
export function unitResponse(path, i, j, opt = {}) {
	const pr = pairOf(path, i, j, opt.kind);
	const kind = KINDS[kindOf(opt.kind)];
	const empty = () => ({
		t: new Float64Array(0), h: new Float64Array(0), dh: new Float64Array(0),
		d2h: new Float64Array(0), peak: 0, tPeak: NaN, integral: 0, maxCond: 1, maxErr: 0,
	});
	if (!pr) return { i, j, kind, ...empty(), T0: 0 };
	const ws = path.ws;
	const tMax = Math.min(opt.tMax ?? T_CAP, T_CAP);
	const o = { method: opt.method, perDecade: opt.perDecade, rtol: opt.rtol, maxPts: opt.maxPts };
	const T0raw = transfer(path, 0, 0, i, j)[0];
	const T0 = Number.isFinite(T0raw) ? T0raw : transfer(path, 1e-300, 0, i, j)[0];
	// The shared parabolas, a set per axis, held to the absolute floor of the
	// response's peak estimate (a floor that grew with the peak found so far
	// would make a cell depend on the times asked for before it).
	const share = (opt.method || 'parabola') === 'parabola' && opt.shared !== false;
	const cellsOf = (ax, peak) => makeCells(path, ax, { atol: peak > 0 ? 1e-3 * RESP_ATOL * peak : 0, peak });
	if (pr.kind === INVENTORY) {
		const [axC, axK] = inventoryAxes(path, i, j);
		const cells = share ? [cellsOf(axC, 1), cellsOf(axK, 1)] : null;
		const sampler = (t, atol, hint) => sampleInventory(path, ws, axC, axK, t, opt.method, atol, hint, cells);
		const start = bateman(path, ws, pr.blk, 0);
		const sup = responseSupport(axK, axK.tLo, T_CAP);
		const tA = Math.min(sup ? sup.tLo : axK.tLo, axK.tLo, tMax / 2);
		const tB = sup ? Math.min(Math.max(sup.tHi, 2 * tA), tMax) : tMax;
		const resp = computeResponse(sampler, start, tA, tB, { ...o, peakEstimate: 1 });
		return { i, j, kind, ...resp, T0, shared: cellCounts(cells) };
	}
	const ax = axisOf(path, pr);
	const sup = responseSupport(ax, ax.tLo, T_CAP);
	const tA = sup ? sup.tLo : NaN;
	const tB = sup ? Math.min(sup.tHi, tMax) : NaN;
	const peakEstimate = sup ? Math.exp(sup.logPeak) : 0;
	const cells = share ? cellsOf(ax, peakEstimate) : null;
	const sampler = (t, atol, hint) => sample(path, ws, ax, t, opt.method, atol, hint, cells);
	const ropt = { ...o, peakEstimate, delay: pr.shift };
	let resp = sup && tB > tA * (1 + 1e-9) ? computeResponse(sampler, null, tA, tB, ropt) : empty();
	addEarlyMass(path, pr, resp);
	resp.T0 = T0;
	// a check for failures, not for the last digits
	const tol = Math.max(1e-5, 50 * (opt.rtol || RESP_RTOL));
	let bal = massBalance(path, ax, resp, tol);
	if (!bal.ok) {
		// once more, from far earlier and on a finer grid (an estimate of
		// where the response lies that missed part of it)
		const tA2 = Math.max(ax.tLo, (sup ? sup.tLo : ax.tLo) / 1e3);
		const tB2 = sup ? tB : Math.min(T_CAP, tMax);
		if (tB2 > tA2 * (1 + 1e-9)) {
			const r2 = computeResponse(sampler, null, tA2, tB2, {
				...ropt,
				perDecade: 2 * (opt.perDecade || RESP_PER_DECADE),
				maxPts: 2 * (opt.maxPts || RESP_MAXPTS),
			});
			addEarlyMass(path, pr, r2);
			r2.T0 = T0;
			const b2 = massBalance(path, ax, r2, tol);
			if (b2.rel < bal.rel) {
				resp = r2;
				bal = b2;
			}
		}
	}
	return {
		i, j, kind, ...resp, T0, expected: bal.expected, balanced: bal.ok, rel: bal.rel, checked: bal.checked,
		shared: cellCounts(cells && [cells]),
	};
}

/** How the samples of a response's axes were taken (see makeCells), summed;
    null without shared parabolas. */
function cellCounts(sets) {
	if (!sets) return null;
	const out = { shared: 0, fallback: 0, negligible: 0, cells: 0, failed: 0, dehoog: 0 };
	for (const C of sets) for (const key of Object.keys(out)) out[key] += C.stats[key];
	return out;
}

/**
 * Every unit response of the path: `{release, inventory}`, each an array
 * indexed i*n + j (null where j never becomes i, or for a kind not asked for).
 *
 * @param {object} opt `{kinds, sources, tMax, method, rtol, perDecade, shared}`;
 *   `sources` limits the columns j to the nuclides that receive an inflow
 */
export function unitResponses(path, opt = {}) {
	const n = path.n;
	const kinds = opt.kinds ?? KINDS;
	const out = { release: new Array(n * n).fill(null), inventory: new Array(n * n).fill(null) };
	const sources = opt.sources ?? Array.from({ length: n }, (_, k) => k);
	for (const kind of kinds) {
		for (const j of sources) {
			for (let i = 0; i < n; i++) {
				if (!path.reach[j][i]) continue;
				out[kind][i * n + j] = unitResponse(path, i, j, { ...opt, kind });
			}
		}
	}
	return out;
}

/* ==========================================================================
   Inflow series and the convolution

   An inflow is piecewise linear between its points and zero before the first
   and after the last; a repeated time is a step. Its convolution with a
   Hermite-interpolated response is exact: on every piece between the merged
   breakpoints the integrand is a polynomial of degree six, integrated by
   four-point Gauss-Legendre.
   ========================================================================== */

/**
 * An inflow history from [t, rate] points, checked.
 *
 * @returns {{t: Float64Array, v: Float64Array, tFirst: number, tLast: number,
 *   mass: number, empty: boolean}}
 */
export function inflowSeries(points, name = 'Inflow') {
	const t = [];
	const v = [];
	for (const p of points ?? []) {
		const a = Number(p[0]);
		const b = Number(p[1]);
		if (!Number.isFinite(a) || !Number.isFinite(b)) {
			throw new LaplacePathError(`${name}: every point needs a finite time and rate.`);
		}
		if (t.length && a < t[t.length - 1]) {
			throw new LaplacePathError(`${name}: the times must not decrease (${a} after ${t[t.length - 1]}).`);
		}
		if (t.length && a === t[t.length - 1] && b === v[v.length - 1]) continue;
		t.push(a);
		v.push(b);
	}
	if (t.length < 2) throw new LaplacePathError(`${name}: at least two points are needed.`);
	let first = -1;
	let last = -1;
	for (let k = 0; k < t.length; k++) {
		const nz = v[k] !== 0 || (k + 1 < t.length && v[k + 1] !== 0 && t[k + 1] > t[k])
			|| (k > 0 && v[k - 1] !== 0 && t[k] > t[k - 1]);
		if (nz) { if (first < 0) first = k; last = k; }
	}
	let mass = 0;
	for (let k = 0; k + 1 < t.length; k++) mass += 0.5 * (t[k + 1] - t[k]) * (v[k] + v[k + 1]);
	return {
		t: Float64Array.from(t), v: Float64Array.from(v),
		tFirst: first < 0 ? NaN : t[first], tLast: last < 0 ? NaN : t[last], mass, empty: first < 0,
	};
}

const GL_X1 = 0.3399810435848563;
const GL_X2 = 0.8611363115940526;
const GL_W1 = 0.6521451548625461;
const GL_W2 = 0.3478548451374538;

function hAt(resp, k, u) {
	return hermite5(resp.t[k], resp.h[k], resp.dh[k], resp.d2h[k], resp.t[k + 1], resp.h[k + 1], resp.dh[k + 1], resp.d2h[k + 1], u);
}

/** The inflow at time x: linear between its points, zero outside them. */
function seriesAt(ser, x) {
	const st = ser.t;
	const n = st.length;
	if (!n || x < st[0] || x > st[n - 1]) return 0;
	let lo = 0;
	let hi = n - 1;
	while (hi - lo > 1) { const c = (lo + hi) >> 1; if (st[c] <= x) lo = c; else hi = c; }
	const d = st[hi] - st[lo];
	return d > 0 ? ser.v[lo] + (ser.v[hi] - ser.v[lo]) * (x - st[lo]) / d : ser.v[hi];
}

/** (h * in)(t): the integral over u of h(u) in(t - u), exactly. */
export function convolve(resp, ser, t) {
	const rt = resp.t;
	const nr = rt.length;
	const st = ser.t;
	const sv = ser.v;
	const ns = st.length;
	if (nr < 2 || ser.empty) return 0;
	// the part of the response before its first time (under plug flow, what
	// arrives within a hair of the delay), as a point mass there
	const lump = resp.m0 > 0 ? resp.m0 * seriesAt(ser, t - rt[0]) : 0;
	const uLo = Math.max(rt[0], t - st[ns - 1]);
	const uHi = Math.min(rt[nr - 1], t - st[0], t);
	if (!(uHi > uLo)) return lump;
	let a = 0;
	let b = nr - 1;
	while (b - a > 1) { const c = (a + b) >> 1; if (rt[c] <= uLo) a = c; else b = c; }
	let k = a;
	let m;
	{
		const x0 = t - uLo;
		let lo = 0;
		let hi = ns - 1;
		while (hi - lo > 1) { const c = (lo + hi) >> 1; if (st[c] < x0) lo = c; else hi = c; }
		m = lo;
	}
	let sum = 0;
	let u = uLo;
	while (u < uHi) {
		while (k + 1 < nr - 1 && rt[k + 1] <= u) k++;
		while (m > 0 && t - st[m] <= u) m--;
		let next = uHi;
		if (rt[k + 1] < next && rt[k + 1] > u) next = rt[k + 1];
		const um = t - st[m];
		if (um < next && um > u) next = um;
		if (next <= u) break;
		const tm0 = st[m];
		const tm1 = st[m + 1];
		const dseg = tm1 - tm0;
		if (dseg > 0) {
			const vm0 = sv[m];
			const slope = (sv[m + 1] - vm0) / dseg;
			const c = 0.5 * (u + next);
			const hw = 0.5 * (next - u);
			let q = 0;
			for (let g = 0; g < 4; g++) {
				const uu = c + (g < 2 ? (g ? GL_X1 : -GL_X1) : (g === 2 ? -GL_X2 : GL_X2)) * hw;
				q += (g < 2 ? GL_W1 : GL_W2) * hAt(resp, k, uu) * (vm0 + slope * (t - uu - tm0));
			}
			sum += hw * q;
		}
		u = next;
	}
	return sum + lump;
}

function sumOver(path, table, inflows, t) {
	const n = path.n;
	const out = new Float64Array(n);
	for (let i = 0; i < n; i++) {
		let s = 0;
		for (let j = 0; j < n; j++) {
			const r = table[i * n + j];
			if (r && inflows[j]) s += convolve(r, inflows[j], t);
		}
		out[i] = s;
	}
	return out;
}

/**
 * The release of every nuclide at t, from the release responses and one
 * inflow series per nuclide (null for none).
 */
export function releaseAt(path, responses, inflows, t) {
	return sumOver(path, responses.release, inflows, t);
}

/** What the path holds of every nuclide at t. */
export function inventoryAt(path, responses, inflows, t) {
	return sumOver(path, responses.inventory, inflows, t);
}

/** For the tests: the inversions themselves, on a pair. */
export const _internal = {
	blockOf, evalBlock, pairOf, axisOf, realAxis, saddleAt, invertParabola, invertTalbot, invertDeHoog,
	singularity, computeResponse, responseSupport, hermite5, bateman, sampleInventory, inventoryAxes,
	deHoogTerms, massBalance, sample, pathFrequency, makeCells, invertShared, cellU, cellT, RESP_ATOL,
	logEstimate, nodeScale, gFracture,
	RELEASE, INVENTORY, DECAYED,
	get RE() { return RE; }, get IM() { return IM; },
};
