/**
 * Which inputs the answer depends on.
 *
 * A probabilistic run gives a band; a sensitivity analysis says what made it
 * that wide. Ecolego's default method is the one built on the Monte Carlo
 * sample it has just drawn -- it calls it *Probabilistic*, and its own
 * description lists what it computes:
 *
 *     A Monte Carlo sample is generated using the linear congruent method.
 *     This common method is used to estimate a number of statistics:
 *     1. Pearson product moment correlation (Pearson)
 *     2. Spearman coefficient (Spearman)
 *     3. Standardized Regression Coefficient (SRC)
 *     4. Partial Correlation Coefficient (PCC)
 *     5. Standardized Rank Regression Coefficient (SRRC)
 *     6. Partial Rank Correlation Coefficient (PRCC)
 *     7. First Order Sensitivity Index (S1)
 *
 * The first two are here. They need no model runs beyond the ones already
 * done, they cost one pass over the sample per output time, and between them
 * they answer the question the others refine: **Pearson** finds a straight-line
 * relationship, **Spearman** finds any monotone one -- which is what a
 * log-triangular sorption coefficient driving a dose through four compartments
 * actually has. Where they disagree, the relationship is monotone and bent, and
 * that disagreement is itself worth seeing.
 *
 * The other five are here too, at one output time rather than at every one,
 * because of what they cost. SRC, PCC, SRRC and PRCC are all one multiple
 * regression of the output on *every* input: model B samples 617
 * values, so that is a 617-wide least squares -- where a correlation is a dot
 * product -- and it is done for the time the reader is looking at, on request,
 * rather than for all 356 output times with the run. See `regressionMeasures`.
 * The first-order index is estimated by binning the input, which a plain
 * sample allows and a second designed sample would only sharpen; see
 * `firstOrderIndex`.
 *
 * Every function here takes an optional `mask` -- 1 to use a realisation, 0 to
 * leave it out -- which is how a result *screened* to some categories of
 * realisation is analysed over just those. A masked realisation is treated
 * exactly as a failed one: as if it were not there.
 *
 * **Ranks are what make Spearman.** A rank correlation is Pearson's on the
 * ranks, so the whole of Spearman is `rank()` and then `pearson()`. Ties get
 * the average of the positions they span, which is the standard definition and
 * the one that keeps a constant input at a correlation of zero rather than an
 * arbitrary one.
 */

/**
 * Pearson's product-moment correlation of two samples.
 *
 * Non-finite pairs are left out rather than poisoning the sum: one realisation
 * of a thousand can fail, and a NaN in the output would otherwise take every
 * coefficient with it.
 *
 * @returns {number} in [-1, 1], or NaN when either sample never varies
 */
export function pearson(x, y, n = x.length) {
	let sx = 0;
	let sy = 0;
	let count = 0;
	for (let i = 0; i < n; i++) {
		if (!Number.isFinite(x[i]) || !Number.isFinite(y[i])) continue;
		sx += x[i];
		sy += y[i];
		count++;
	}
	if (count < 3) return NaN;
	const mx = sx / count;
	const my = sy / count;
	let sxy = 0;
	let sxx = 0;
	let syy = 0;
	for (let i = 0; i < n; i++) {
		if (!Number.isFinite(x[i]) || !Number.isFinite(y[i])) continue;
		const dx = x[i] - mx;
		const dy = y[i] - my;
		sxy += dx * dy;
		sxx += dx * dx;
		syy += dy * dy;
	}
	// A constant input -- a distribution whose whole range is one value, or a
	// parameter the model does not read -- has no correlation with anything,
	// and saying 0 would claim it was measured.
	if (!(sxx > 0) || !(syy > 0)) return NaN;
	return sxy / Math.sqrt(sxx * syy);
}

/**
 * Ranks, averaging ties.
 *
 * `into` is filled rather than allocated: a sensitivity analysis ranks the same
 * two vectors at every output time, and a fresh array per time is the largest
 * thing the pass would otherwise do.
 */
export function rank(v, n = v.length, into = new Float64Array(n), order = null) {
	const idx = order ?? new Int32Array(n);
	let m = 0;
	for (let i = 0; i < n; i++) if (Number.isFinite(v[i])) idx[m++] = i;
	const use = idx.subarray(0, m);
	// A plain sort of the indices: `m` is the realisation count, a thousand at
	// most in practice.
	Array.prototype.sort.call(use, (a, b) => v[a] - v[b]);
	into.fill(NaN);
	let i = 0;
	while (i < m) {
		let j = i;
		while (j + 1 < m && v[use[j + 1]] === v[use[i]]) j++;
		// The average of the positions this run of equal values spans, so that
		// a vector of one repeated number ranks flat rather than in the order
		// the sort happened to leave it.
		const r = (i + j) / 2 + 1;
		for (let k = i; k <= j; k++) into[use[k]] = r;
		i = j + 1;
	}
	return into;
}

/** Spearman's coefficient: Pearson's, on the ranks. */
export function spearman(x, y, n = x.length, scratch = null) {
	const rx = rank(x, n, scratch?.rx ?? new Float64Array(n), scratch?.ix);
	const ry = rank(y, n, scratch?.ry ?? new Float64Array(n), scratch?.iy);
	return pearson(rx, ry, n);
}

/** Room to rank two vectors of `n` without allocating per call. */
export function scratchFor(n) {
	return {
		rx: new Float64Array(n),
		ry: new Float64Array(n),
		ix: new Int32Array(n),
		iy: new Int32Array(n),
	};
}

/**
 * How each input correlates with one output, at one time.
 *
 * @param {Float64Array[]} samples  one per input, `iterations` long
 * @param {Float64Array} values     the output, realisation-major
 * @param {number} times
 * @param {number} iterations
 * @param {number} at               which output time
 * @returns {{pearson: Float64Array, spearman: Float64Array}}
 */
export function atTime(samples, values, times, iterations, at, scratch = null, mask = null) {
	const s = scratch ?? scratchFor(iterations);
	const y = s.y ?? new Float64Array(iterations);
	for (let i = 0; i < iterations; i++) {
		y[i] = mask && !mask[i] ? NaN : values[i * times + at];
	}
	const p = new Float64Array(samples.length);
	const r = new Float64Array(samples.length);
	// The output's ranks are the same for every input, so they are worked out
	// once rather than once per input -- which on 617 inputs is 616 sorts of a
	// thousand numbers saved at every time.
	const ry = rank(y, iterations, s.ry, s.iy);
	for (let k = 0; k < samples.length; k++) {
		p[k] = pearson(samples[k], y, iterations);
		r[k] = pearson(rank(samples[k], iterations, s.rx, s.ix), ry, iterations);
	}
	return { pearson: p, spearman: r };
}

/**
 * The inputs that matter, ranked, at one time.
 *
 * Ordered by |Spearman| rather than |Pearson|: a monotone relationship that is
 * not a straight line is the normal case here -- a log-triangular sorption
 * coefficient driving a dose is monotone and nothing like linear -- and
 * ordering by Pearson would put a genuinely important input below a
 * coincidentally straight one.
 *
 * @returns {Array<{k: number, pearson: number, spearman: number}>}
 */
export function ranked(samples, values, times, iterations, at, { most = 20, mask = null } = {}) {
	const { pearson: p, spearman: r } = atTime(samples, values, times, iterations, at, null, mask);
	const rows = [];
	for (let k = 0; k < samples.length; k++) {
		if (!Number.isFinite(r[k]) && !Number.isFinite(p[k])) continue;
		rows.push({ k, pearson: p[k], spearman: r[k] });
	}
	rows.sort((a, b) => Math.abs(b.spearman || 0) - Math.abs(a.spearman || 0));
	return rows.slice(0, most);
}

/**
 * One input's correlation with one output at every time.
 *
 * The shape behind Ecolego's *correlation rank coefficients over time* chart:
 * an input that matters early and not late is a thing a single number cannot
 * say, and it is common -- a release rate governs the first century and a
 * sorption coefficient the next ten thousand years.
 */
export function overTime(sample, values, times, iterations, { rankBased = true, mask = null } = {}) {
	const out = new Float64Array(times);
	const y = new Float64Array(iterations);
	const s = scratchFor(iterations);
	const rx = rankBased ? rank(sample, iterations, s.rx, s.ix) : sample;
	for (let j = 0; j < times; j++) {
		for (let i = 0; i < iterations; i++) {
			y[i] = mask && !mask[i] ? NaN : values[i * times + j];
		}
		out[j] = rankBased
			? pearson(rx, rank(y, iterations, s.ry, s.iy), iterations)
			: pearson(sample, y, iterations);
	}
	return out;
}

/**
 * The regression family, at one time: R², SRC and PCC for every input.
 *
 * One multiple regression of the output on all the inputs at once, which is
 * what separates these from a correlation. A correlation asks "does the
 * output move with this input"; the standardized regression coefficient asks
 * "how much of the output's movement is *this* input's, given the others",
 * and the partial correlation asks the same with the others' linear effects
 * taken out of both. Where the inputs are independent -- a Latin hypercube
 * with no correlations -- SRC and correlation nearly agree and PCC is the one
 * that separates two inputs the output happens to track together. Where they
 * are correlated, SRC and PCC are the ones that mean anything.
 *
 * Computed from the inputs' correlation matrix `R_xx` and their correlations
 * with the output `r_xy`, which is all a standardized regression needs:
 *
 *     SRC    = R_xx⁻¹ · r_xy
 *     R²     = r_xyᵀ · SRC
 *     PCC_k² = SRC_k² / (SRC_k² + (1 − R²) · (R_xx⁻¹)[k, k]),  with SRC_k's sign
 *
 * so the whole family is one K-wide inverse rather than K regressions of K−1
 * variables. The last line is the partial correlation written as the
 * t-statistic of the coefficient; the textbook route through the inverse of
 * the augmented `[inputs, output]` matrix gives the same numbers and is
 * singular exactly when the fit is perfect, which on ranks is the ordinary
 * case of an output that follows one input.
 *
 * **`translate` is what the fit is fitted to.** A linear regression answers a
 * linear question, and the relationships here are usually neither linear nor
 * expressible as one without help:
 *
 *   `none`  the values as they are. The coefficients are in the model's own
 *           units and mean what they say.
 *   `rank`  each column replaced by its ranks, which gives SRRC and PRCC --
 *           the standard reading for a relationship that is monotone and bent,
 *           which a log-triangular sorption coefficient driving a dose is.
 *   `log`   the logarithm of every column and of the output. A power law
 *           `y = a·x^b` is a straight line in logs, and the coefficient is then
 *           the elasticity: the percentage in `y` per percentage in `x`.
 *
 * `log` needs positive numbers. A realisation where any column or the output is
 * zero or negative has no logarithm and is dropped -- counted in `dropped`, so
 * the caller can say how many rather than quietly fitting to a subset.
 *
 * **`b` is the unstandardized coefficient** and `src` the standardized one.
 * They answer different questions: `src` is comparable *between inputs* --
 * which is why it is the one to rank by -- and `b` is in units, so it says how
 * much the output moves per unit of this input and can be read against what
 * the input actually is. `b_k = SRC_k · sd(y) / sd(x_k)`, on whatever the
 * translation left behind.
 *
 * An input that never varied has no column: it is reported as NaN and left out
 * of the regression rather than making the matrix singular. When the inverse
 * fails anyway -- more inputs than realisations, or two inputs that are the
 * same numbers -- everything is NaN and `ok` says so.
 *
 * @param {Float64Array[]} samples  one per input, `iterations` long
 * @param {Float64Array} y          the output at one time, `iterations` long
 * @param {{translate?: 'none'|'rank'|'log', mask?: Uint8Array|null}} [opts]
 * @returns {{r2: number, src: Float64Array, b: Float64Array, pcc: Float64Array,
 *            used: number, dropped: number, ok: boolean}}
 */
export function regressionMeasures(samples, y, { translate = 'none', mask = null } = {}) {
	const K = samples.length;
	const n = y.length;
	const logs = translate === 'log';
	const src = new Float64Array(K).fill(NaN);
	const b = new Float64Array(K).fill(NaN);
	const pcc = new Float64Array(K).fill(NaN);
	// The realisations every column agrees on: finite everywhere, not masked.
	const keep = new Uint8Array(n);
	let m = 0;
	let offered = 0;
	// On logs a row also needs every value to *have* one. Dropped rather than
	// nudged: a zero moved to 1e-300 is a row that then dominates the fit.
	const usable = (v) => Number.isFinite(v) && (!logs || v > 0);
	for (let i = 0; i < n; i++) {
		if (mask && !mask[i]) continue;
		offered++;
		if (!usable(y[i])) continue;
		let good = true;
		for (let k = 0; k < K && good; k++) if (!usable(samples[k][i])) good = false;
		if (good) { keep[i] = 1; m++; }
	}
	const dropped = offered - m;
	if (m < 4) return { r2: NaN, src, b, pcc, used: m, dropped, ok: false };

	// The columns that vary, as standardized vectors over the kept rows.
	const take = (v) => {
		const out = new Float64Array(m);
		let j = 0;
		for (let i = 0; i < n; i++) if (keep[i]) out[j++] = logs ? Math.log(v[i]) : v[i];
		return out;
	};
	const s = scratchFor(m);
	// The standardized column *and* its spread, because the unstandardized
	// coefficient is the standardized one carried back into units.
	const standardize = (col) => {
		const x = translate === 'rank' ? rank(col, m, new Float64Array(m), s.ix) : col;
		let sum = 0;
		for (let i = 0; i < m; i++) sum += x[i];
		const mean = sum / m;
		let ss = 0;
		for (let i = 0; i < m; i++) ss += (x[i] - mean) ** 2;
		if (!(ss > 0)) return null;
		const sd = Math.sqrt(ss / (m - 1));
		const out = new Float64Array(m);
		for (let i = 0; i < m; i++) out[i] = (x[i] - mean) / sd;
		return { z: out, sd };
	};
	const cols = [];
	const sds = [];
	const which = [];
	for (let k = 0; k < K; k++) {
		const z = standardize(take(samples[k]));
		if (z) { cols.push(z.z); sds.push(z.sd); which.push(k); }
	}
	const ystd = standardize(take(y));
	if (!ystd || !cols.length) return { r2: NaN, src, b, pcc, used: m, dropped, ok: false };
	const zy = ystd.z;
	const P = cols.length;
	if (P >= m - 1) return { r2: NaN, src, b, pcc, used: m, dropped, ok: false };

	// R_xx, the inputs' correlation matrix, and r_xy: the standardized
	// columns make each entry a dot product over m−1.
	const Rxx = new Float64Array(P * P);
	const rxy = new Float64Array(P);
	for (let a = 0; a < P; a++) {
		for (let b = a; b < P; b++) {
			let dot = 0;
			const u = cols[a];
			const v = cols[b];
			for (let i = 0; i < m; i++) dot += u[i] * v[i];
			Rxx[a * P + b] = dot / (m - 1);
			Rxx[b * P + a] = Rxx[a * P + b];
		}
		let dot = 0;
		for (let i = 0; i < m; i++) dot += cols[a][i] * zy[i];
		rxy[a] = dot / (m - 1);
	}
	// Only the inputs' matrix is inverted. The augmented `[inputs, output]`
	// matrix is the textbook route to the partial correlations, and it is
	// singular exactly when the fit is perfect -- an output that is a monotone
	// function of one input has a rank correlation of ±1 with it, and on ranks
	// that is R² = 1 and a zero determinant. Which is the case the rank form
	// exists for. The identity below reaches the same numbers from R_xx⁻¹.
	const Rxxinv = invertSymmetric(Rxx, P);
	if (!Rxxinv) return { r2: NaN, src, b, pcc, used: m, dropped, ok: false };
	let r2 = 0;
	const beta = new Float64Array(P);
	for (let a = 0; a < P; a++) {
		let b = 0;
		for (let c = 0; c < P; c++) b += Rxxinv[a * P + c] * rxy[c];
		beta[a] = b;
		r2 += rxy[a] * b;
	}
	// Rounding can carry a perfect fit a hair past one.
	const left = Math.max(0, 1 - r2);
	for (let a = 0; a < P; a++) {
		src[which[a]] = beta[a];
		// The same coefficient in units: how much the output moves per unit of
		// this input, with the others held. On logs that is an elasticity.
		b[which[a]] = beta[a] * (ystd.sd / sds[a]);
		// PCC_k² = β_k² / (β_k² + (1 − R²)·(R_xx⁻¹)_kk), with β_k's sign: the
		// partial correlation as the t-statistic of the coefficient, which
		// is what it is. At R² = 1 an input with a coefficient explains the
		// whole of what is left, and one without explains none of it.
		const denom = beta[a] * beta[a] + left * Rxxinv[a * P + a];
		pcc[which[a]] = denom > 0 ? Math.sign(beta[a]) * Math.sqrt((beta[a] * beta[a]) / denom) : 0;
	}
	return { r2, src, b, pcc, used: m, dropped, ok: true };
}

/**
 * A straight line through one input and one output, and how much of the
 * spread it accounts for.
 *
 * `regressionMeasures` above answers the question an assessment asks -- every
 * input at once, so an input that merely moves with another is told from the
 * one that drives -- and is the wrong shape for a scatter plot, which is two
 * columns and a line drawn on them. This is that: the least-squares fit
 * `y = a + b·x`, and R², which for one input is the square of the correlation.
 *
 * `translate` is the same idea as there and matters more here, because the line
 * is *drawn*: on logarithms a power law is straight and its slope is the
 * exponent, where on the values it is a curve with a straight line through it
 * saying nothing. Pairs that cannot be translated -- a zero under a logarithm --
 * are left out and counted.
 *
 * @returns {{a: number, b: number, r2: number, n: number, dropped: number,
 *            log: boolean, ok: boolean}}
 */
export function lineFit(x, y, { translate = 'none', mask = null } = {}) {
	const n = Math.min(x.length, y.length);
	const logs = translate === 'log';
	const usable = (v) => Number.isFinite(v) && (!logs || v > 0);
	const xs = [];
	const ys = [];
	let offered = 0;
	for (let i = 0; i < n; i++) {
		if (mask && !mask[i]) continue;
		offered++;
		if (!usable(x[i]) || !usable(y[i])) continue;
		xs.push(logs ? Math.log(x[i]) : x[i]);
		ys.push(logs ? Math.log(y[i]) : y[i]);
	}
	const m = xs.length;
	const dropped = offered - m;
	const none = { a: NaN, b: NaN, r2: NaN, n: m, dropped, log: logs, ok: false };
	if (m < 3) return none;
	let sx = 0;
	let sy = 0;
	for (let i = 0; i < m; i++) { sx += xs[i]; sy += ys[i]; }
	const mx = sx / m;
	const my = sy / m;
	let sxx = 0;
	let syy = 0;
	let sxy = 0;
	for (let i = 0; i < m; i++) {
		const dx = xs[i] - mx;
		const dy = ys[i] - my;
		sxx += dx * dx;
		syy += dy * dy;
		sxy += dx * dy;
	}
	// A column of one value has no line through it, and neither has an output
	// that never moved.
	if (!(sxx > 0) || !(syy > 0)) return none;
	const b = sxy / sxx;
	return {
		a: my - b * mx,
		b,
		r2: (sxy * sxy) / (sxx * syy),
		n: m,
		dropped,
		log: logs,
		ok: true,
	};
}

/**
 * The inverse of a symmetric positive-definite matrix, or null.
 *
 * Cholesky and two triangular solves per column. A pivot that is not
 * comfortably positive is a matrix that is singular for the purpose -- two
 * inputs that are the same numbers, or more inputs than realisations -- and
 * null is the honest answer rather than a large wrong one.
 */
function invertSymmetric(A, D) {
	const L = new Float64Array(D * D);
	for (let i = 0; i < D; i++) {
		for (let j = 0; j <= i; j++) {
			let s = A[i * D + j];
			for (let l = 0; l < j; l++) s -= L[i * D + l] * L[j * D + l];
			if (i === j) {
				if (!(s > 1e-10)) return null;
				L[i * D + i] = Math.sqrt(s);
			} else {
				L[i * D + j] = s / L[j * D + j];
			}
		}
	}
	const out = new Float64Array(D * D);
	const col = new Float64Array(D);
	for (let c = 0; c < D; c++) {
		// L z = e_c, then Lᵀ x = z.
		for (let i = 0; i < D; i++) {
			let s = i === c ? 1 : 0;
			for (let l = 0; l < i; l++) s -= L[i * D + l] * col[l];
			col[i] = s / L[i * D + i];
		}
		for (let i = D - 1; i >= 0; i--) {
			let s = col[i];
			for (let l = i + 1; l < D; l++) s -= L[l * D + i] * out[l * D + c];
			out[i * D + c] = s / L[i * D + i];
		}
	}
	return out;
}

/**
 * A first-order sensitivity index, estimated by binning.
 *
 * S₁ = Var(E[y | x]) / Var(y): the share of the output's variance that knowing
 * this one input would remove. Unlike a correlation it finds a relationship
 * of *any* shape -- an output that peaks in the middle of an input's range has
 * a correlation of nothing and an S₁ of a lot. Estimated the way a plain
 * sample allows: the input is cut into bins of equal count, the output is
 * averaged in each, and the variance of those averages is the numerator.
 * `√n` bins, so each holds `√n` realisations -- the usual balance between
 * resolving the shape and resolving each mean.
 *
 * Biased upwards by sampling noise in the bin means, by about `bins / n`, and
 * that much is subtracted; what is left is clamped at zero. So an input that
 * does nothing reads near zero rather than as a small positive number that
 * looks like something.
 *
 * @returns {number} in [0, 1], or NaN when there is nothing to measure
 */
export function firstOrderIndex(x, y, { mask = null, bins = null } = {}) {
	const n = x.length;
	const idx = [];
	for (let i = 0; i < n; i++) {
		if (mask && !mask[i]) continue;
		if (Number.isFinite(x[i]) && Number.isFinite(y[i])) idx.push(i);
	}
	const m = idx.length;
	if (m < 10) return NaN;
	idx.sort((a, b) => x[a] - x[b]);
	// A constant input has no bins to speak of.
	if (x[idx[0]] === x[idx[m - 1]]) return NaN;
	let sum = 0;
	for (const i of idx) sum += y[i];
	const mean = sum / m;
	let total = 0;
	for (const i of idx) total += (y[i] - mean) ** 2;
	total /= m;
	if (!(total > 0)) return NaN;
	const B = bins ?? Math.max(4, Math.min(50, Math.round(Math.sqrt(m))));
	let between = 0;
	for (let b = 0; b < B; b++) {
		const from = Math.floor((b * m) / B);
		const to = Math.floor(((b + 1) * m) / B);
		if (to <= from) continue;
		let s = 0;
		for (let i = from; i < to; i++) s += y[idx[i]];
		const mb = s / (to - from);
		between += (to - from) * (mb - mean) ** 2;
	}
	between /= m;
	// The bin means carry noise of about total/(m/B) each, which adds B/m of
	// the total variance to `between` on average.
	const raw = between / total - B / m;
	return Math.max(0, Math.min(1, raw));
}
