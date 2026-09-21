/**
 * A number read off a finished time history.
 *
 * "The peak dose." "The year it peaked." "How much arrived altogether." These
 * are the three or four numbers an assessment actually quotes, and they are all
 * reductions of a curve the run already produced.
 *
 * **This is not what the recorders do, and the difference matters.** A min/max
 * block, a running mean, a snapshot -- those accumulate *during* the
 * integration, into a history the built system carries, because Ecolego's do
 * and because some of them have to: a delay feeds its own value back into the
 * derivative, so it cannot be worked out afterwards. The cost of that is real:
 * a model carrying one can never have its trajectory re-used, so every edit to
 * anything re-solves it (see ../domain/fingerprint.js).
 *
 * A derived parameter costs none of that. It is computed from `(t, y)` when
 * something asks, like every other non-state series in this tool, so it adds
 * nothing to the solve, nothing to the state vector, and nothing to what has to
 * be remembered. AMBER draws the same line and calls these Derived Parameters
 * (Reference Manual §9.1.9); the four kinds here are its four.
 *
 * Reach for a recorder when the model *reads* the number while it runs, and one
 * of these when a person reads it afterwards. Almost every peak dose in an
 * assessment is the second.
 */

/** What a derived parameter can be. */
export const DERIVED_KINDS = [
	'max', 'min', 'time_of_max', 'at_time', 'integral',
	'period_mean', 'period_sum', 'period_change', 'period_rate',
];

/** The four that read the series period by period. */
export const PERIOD_KINDS = ['period_mean', 'period_sum', 'period_change', 'period_rate'];

/** What each is called in the interface. */
export const DERIVED_LABEL = {
	max: 'Maximum',
	min: 'Minimum',
	time_of_max: 'Time of maximum',
	at_time: 'Value at a given time',
	integral: 'Integral over time',
	period_mean: 'Mean over each period',
	period_sum: 'Total over each period',
	period_change: 'Change over each period',
	period_rate: 'Rate of change over each period',
};

/** A line each, for the panel that offers them. */
export const DERIVED_BLURB = {
	max: 'The largest value the series reaches over the run.',
	min: 'The smallest value the series reaches over the run.',
	time_of_max: 'When it reached it — a time, not a quantity, so it carries the '
		+ 'run’s time unit rather than the series’ own.',
	at_time: 'What it was at one moment. The time may be a number or the name of '
		+ 'a parameter, so the moment can be a thing the model says.',
	integral: 'Accumulated from the start of the run — the area under the curve, '
		+ 'by the trapezium rule. This one is a curve itself, not a single '
		+ 'number: it is the total *so far* at every time.',
	period_mean: 'The series averaged over each period of the given length — the '
		+ 'annual mean dose, with a period of one year. A stair-step curve: every '
		+ 'time in a period carries that period’s mean.',
	period_sum: 'The series integrated over each period — the release in each '
		+ 'year. A stair-step curve, in the series’ unit times time.',
	period_change: 'The series at the end of each period less its value at the '
		+ 'end of the period before.',
	period_rate: 'That change divided by the period’s length: the average rate '
		+ 'over the period.',
};

/**
 * Whether a derived parameter is one number or a curve.
 *
 * Only the integral is a curve. The other three are a single number, which the
 * chart draws as a flat line -- deliberately, because a flat line at the peak
 * drawn across the series it came from is exactly how a peak is read.
 */
export function isSeries(kind) {
	return kind === 'integral' || PERIOD_KINDS.includes(kind);
}

/** The unit a derived value carries, given the unit of what it was taken from. */
export function derivedUnit(kind, sourceUnit, timeUnit) {
	const u = String(sourceUnit ?? '').trim();
	const tu = String(timeUnit ?? '').trim();
	if (kind === 'time_of_max') return tu;
	if (kind === 'integral' || kind === 'period_sum') return u ? `${u} ${tu}` : '';
	if (kind === 'period_rate') return u ? `${u}/${tu}` : '';
	return u;
}

/**
 * Reduces a series to what the derived parameter says.
 *
 * NaN is skipped throughout rather than propagated. A probabilistic
 * realisation that failed is NaN across its whole row, and a maximum that came
 * back NaN because one run in a thousand did not finish would be a worse answer
 * than the maximum over the ones that did. An empty or all-NaN series gives
 * NaN, which is the honest answer for "the largest of nothing".
 *
 * @param {string} kind
 * @param {ArrayLike<number>} t      the output times
 * @param {ArrayLike<number>} values the series
 * @param {object} [opts]
 * @param {number} [opts.at]  for `at_time`: the moment to read at
 * @returns {number|Float64Array} a number, or the running integral
 */
export function reduce(kind, t, values, opts = {}) {
	const n = Math.min(t?.length ?? 0, values?.length ?? 0);
	if (kind === 'integral') return integral(t, values, n);
	if (PERIOD_KINDS.includes(kind)) return byPeriod(kind, t, values, n, Number(opts.period));
	if (!n) return NaN;

	if (kind === 'at_time') return valueAt(t, values, n, Number(opts.at));

	let best = NaN;
	let bestAt = NaN;
	const better = kind === 'min' ? (a, b) => a < b : (a, b) => a > b;
	for (let i = 0; i < n; i++) {
		const v = values[i];
		if (!Number.isFinite(v)) continue;
		if (Number.isNaN(best) || better(v, best)) { best = v; bestAt = t[i]; }
	}
	if (kind === 'time_of_max') return bestAt;
	return best;
}

/**
 * What the series was at one time, interpolated between the output points.
 *
 * Linear, and held flat outside the run: the output times are a grid somebody
 * chose, and "the dose at 10,000 years" should not depend on whether 10,000
 * happens to be one of them.
 */
export function valueAt(t, values, n, at) {
	if (!n || !Number.isFinite(at)) return NaN;
	if (at <= t[0]) return values[0];
	if (at >= t[n - 1]) return values[n - 1];
	// The grid is ascending, so a binary search finds the segment.
	let lo = 0;
	let hi = n - 1;
	while (hi - lo > 1) {
		const mid = (lo + hi) >> 1;
		if (t[mid] <= at) lo = mid; else hi = mid;
	}
	const span = t[hi] - t[lo];
	if (!(span > 0)) return values[lo];
	const a = values[lo];
	const b = values[hi];
	if (!Number.isFinite(a)) return b;
	if (!Number.isFinite(b)) return a;
	return a + ((at - t[lo]) / span) * (b - a);
}

/**
 * The running integral, by the trapezium rule.
 *
 * The trapezium rather than anything cleverer because the output times are
 * whatever the model asked for -- often logarithmic, sometimes a handful -- and
 * a higher-order rule over an uneven grid of unknown provenance is a way of
 * being confidently wrong. A gap with a NaN at either end contributes nothing
 * rather than poisoning everything after it.
 */
export function integral(t, values, n = Math.min(t?.length ?? 0, values?.length ?? 0)) {
	const out = new Float64Array(n);
	let total = 0;
	for (let i = 1; i < n; i++) {
		const dt = t[i] - t[i - 1];
		const a = values[i - 1];
		const b = values[i];
		if (dt > 0 && Number.isFinite(a) && Number.isFinite(b)) total += 0.5 * (a + b) * dt;
		out[i] = total;
	}
	return out;
}

/**
 * The series read period by period: GoldSim's Reporting Periods.
 *
 * "The annual mean dose" is the quantity several regulators write their limit
 * against, and a series on a logarithmic output grid has no such number in it
 * anywhere: the grid is dense early and sparse late, and no point on it is a
 * year's average. So the period is walked as a set of boundaries laid over
 * the run -- `t0, t0+P, t0+2P, …` -- and each period's number is worked out
 * from the curve between its boundaries, interpolating the curve at the
 * boundaries themselves, whatever the grid happens to be. The mean is the
 * integral over the period divided by the period's length, so that a dose
 * that peaks between two output times still counts for as long as it lasted.
 *
 * The answer is a stair-step curve on the run's own grid: every output time in
 * a period carries that period's number. That makes `max` of it the peak
 * annual mean, which is the number that is actually wanted, and lets it be
 * drawn on the same axis as the series it came from. A last period the run
 * does not fill is worked out over the part it covers.
 *
 * @param {number} period  the period's length in the run's time unit
 * @returns {Float64Array}
 */
export function byPeriod(kind, t, values, n, period) {
	const out = new Float64Array(n).fill(NaN);
	if (!n || !(period > 0)) return out;
	const t0 = t[0];
	const tEnd = t[n - 1];
	// The integral of the curve from t0 to `x`, by the trapezium rule with the
	// curve interpolated at `x`. Walked once, in order, so the whole run costs
	// one pass however many periods there are.
	const running = integral(t, values, n);
	const integralTo = (x) => {
		if (x <= t0) return 0;
		if (x >= tEnd) return running[n - 1];
		let lo = 0;
		let hi = n - 1;
		while (hi - lo > 1) {
			const mid = (lo + hi) >> 1;
			if (t[mid] <= x) lo = mid; else hi = mid;
		}
		const a = values[lo];
		const b = valueAt(t, values, n, x);
		if (!Number.isFinite(a) || !Number.isFinite(b)) return running[lo];
		return running[lo] + 0.5 * (a + b) * (x - t[lo]);
	};
	let j = 0;
	for (let k = 0; ; k++) {
		const from = t0 + k * period;
		if (from > tEnd) break;
		const to = Math.min(tEnd, from + period);
		const span = to - from;
		let v;
		if (kind === 'period_mean') {
			v = span > 0 ? (integralTo(to) - integralTo(from)) / span : valueAt(t, values, n, from);
		} else if (kind === 'period_sum') {
			v = integralTo(to) - integralTo(from);
		} else {
			// Change over the period: at its end less at the end of the one
			// before, which for the first period is the run's start.
			const change = valueAt(t, values, n, to) - valueAt(t, values, n, from);
			v = kind === 'period_change' ? change : (span > 0 ? change / span : NaN);
		}
		// Every output time in [from, to) -- and the last time of the run,
		// which the half-open interval would otherwise leave out.
		while (j < n && (t[j] < to || (to === tEnd && t[j] <= tEnd))) {
			out[j] = v;
			j++;
		}
		if (to === tEnd) break;
	}
	return out;
}

/**
 * The derived parameters a project declares, normalised.
 *
 * `of` names the series it reduces -- a block's label, as the chart spells it.
 * Anything malformed is left out here and reported by `derivedProblems`, for
 * the same reason the switch times are: a mis-typed name should cost one
 * output, not the run.
 */
export function derivedBlocks(project) {
	return (project?.derived ?? []).filter((b) => b && typeof b === 'object'
		&& String(b.name ?? '').trim() && DERIVED_KINDS.includes(b.kind)
		&& String(b.of ?? '').trim());
}

/** What is wrong with them, for the problem strip. */
export function derivedProblems(project, knownLabels = null) {
	const out = [];
	for (const b of project?.derived ?? []) {
		if (!b || typeof b !== 'object') continue;
		const name = String(b.name ?? '').trim() || '(unnamed)';
		if (!DERIVED_KINDS.includes(b.kind)) {
			out.push({
				name, field: 'kind',
				message: `'${b.kind}' is not one of ${DERIVED_KINDS.join(', ')}.`,
			});
			continue;
		}
		const of = String(b.of ?? '').trim();
		if (!of) {
			out.push({ name, field: 'of', message: 'It does not say which series it is of.' });
			continue;
		}
		if (knownLabels && !knownLabels.has(of)) {
			out.push({
				name, field: 'of',
				message: `'${of}' is not a series this run produces. Use the name as the `
					+ 'chart spells it.',
			});
		}
		if (b.kind === 'at_time' && !Number.isFinite(Number(b.at))) {
			out.push({
				name, field: 'at',
				message: `'${b.at}' is not a time. It has to be a number of ${''
				}${'the run’s time unit'}.`,
			});
		}
		if (PERIOD_KINDS.includes(b.kind) && !(Number(b.period) > 0)) {
			out.push({
				name, field: 'period',
				message: `'${b.period}' is not a period. It has to be a length of time `
					+ 'greater than zero, in the run’s time unit — 1 for an annual mean.',
			});
		}
	}
	return out;
}
