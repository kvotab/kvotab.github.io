/**
 * Probability distributions on a parameter.
 *
 * A parameter in a real assessment is rarely a number. It is a number *and*
 * the distribution it was drawn from, per index: model B carries
 * 1,288 of them, `model G` 4,978, and of the 302 model files here 112 have at
 * least one. Ecolego keeps both on the entry, and so does this:
 *
 *     <entry type="parameter" index="Construction&#95;concrete">
 *       <value><![CDATA[1.0E-11]]></value>
 *       <pdf function="logt">
 *         <pdf-value><![CDATA[logt(min=7.0E-12,max=5.0E-11,mode=1.0E-11)]]></pdf-value>
 *       </pdf>
 *     </entry>
 *
 * The `value` is what a deterministic run uses and what this tool has always
 * read. The `pdf` is what a probabilistic one would sample. Nothing here
 * samples anything yet -- this file is the distribution itself: read it, write
 * it back as Ecolego spells it, say what it is, and work out its density so it
 * can be drawn.
 *
 * ---
 *
 * **Two names, and the attribute is the one that means something.** The
 * expression always spells the family -- `logn(...)` -- while the attribute
 * names the class, and three different parameterisations share that one
 * spelling:
 *
 * | `function=` | expression | what the numbers are |
 * |---|---|---|
 * | `Logn4` | `logn(gm=, gsd=)` | geometric mean and geometric sd |
 * | `logn` | `logn(mean=, sd=)` | arithmetic mean and sd |
 * | `logn5` | `logn(p1=, x1=, p2=, x2=)` | two quantiles to fit through |
 *
 * Read off the expression alone, a `Logn4` would be taken for a `logn` and
 * drawn with the wrong shape. So the attribute is the kind, and the argument
 * names are the fallback when a file has no attribute. Counted over the
 * corpus, the attribute and the argument names agree in every one of the
 * 18,000-odd distributions there -- but they agree because the attribute is
 * right, not because the expression is enough.
 *
 * **Every density here is the file format's, not a textbook's.** They mostly agree,
 * and where the format is particular this follows it. `Logt` is the one worth
 * quoting, since "log-triangular" could reasonably mean two things and this
 * is which:
 *
 *     if (x[i] > a && x[i] <= c && a != c) {
 *         y[i] = 1.0 / x[i] * (2.0 * (Math.log(x[i]) - loga) / (logc - loga) / (logb - loga));
 *     } else if (x[i] > a && x[i] > c && x[i] <= b && b != c) {
 *         y[i] = 1.0 / x[i] * (2.0 * (logb - Math.log(x[i])) / (logb - logc) / (logb - loga));
 *     }
 *
 * -- a triangle in `ln x`, carried back to `x` by the `1/x`. `Logn4` is
 * `exp(-0.5*((ln x - ln gm)/ln gsd)^2) / (x*sqrt(2*pi)*ln gsd)`, which is the
 * geometric parameterisation written out; `Logu` is `1/(x*(ln b - ln a))`.
 *
 * **A distribution may be declared and not filled in.** `logn(gm,gsd)` -- the
 * argument names with no values -- appears 11 times in the corpus, and 943
 * more carry a truncation and no shape at all. Ecolego writes those when the
 * kind has been chosen and the numbers have not. They are not errors and they
 * are not thrown away: `complete()` is false for them, the editor shows the
 * fields empty, and they are written back as they came.
 */

import { erfc } from '../parser/functions.js';

/** What each kind is called where a person reads it, and what it takes. */
export const PDF_KINDS = {
	unif: {
		label: 'Uniform',
		expr: 'unif',
		blurb: 'Every value between the two ends is as likely as any other.',
		params: [
			{ key: 'min', label: 'Minimum' },
			{ key: 'max', label: 'Maximum' },
		],
	},
	triang: {
		label: 'Triangular',
		expr: 'triang',
		blurb: 'A straight rise to the most likely value and a straight fall away '
			+ 'from it — the shape for "about this, no less than that, no more than '
			+ 'the other".',
		params: [
			{ key: 'min', label: 'Minimum' },
			{ key: 'max', label: 'Maximum' },
			{ key: 'mode', label: 'Most likely' },
		],
	},
	// skbrnt's `dtriang` (samp_util.Dtriang). Ecolego has no such shape, so the
	// spelling is skbrnt's and the numbers are its `a`, `b` and `m`.
	dtriang: {
		label: 'Double-triangular',
		expr: 'dtriang',
		blurb: 'Two triangles that meet at the most likely value, with half the '
			+ 'probability on each side — so that value is the median as well as '
			+ 'the peak, wherever it sits between the ends.',
		params: [
			{ key: 'min', label: 'Minimum' },
			{ key: 'max', label: 'Maximum' },
			{ key: 'mode', label: 'Most likely (the median)' },
		],
	},
	norm: {
		label: 'Normal',
		expr: 'norm',
		blurb: 'The bell curve, symmetric about its mean.',
		params: [
			{ key: 'mean', label: 'Mean' },
			{ key: 'sd', label: 'Std. deviation', positive: true },
		],
	},
	logu: {
		label: 'Log-uniform',
		expr: 'logu',
		positive: true,
		log: true,
		blurb: 'Uniform in the logarithm: every decade between the ends carries the '
			+ 'same probability. The shape for a quantity known only to within '
			+ 'orders of magnitude.',
		params: [
			{ key: 'min', label: 'Minimum', positive: true },
			{ key: 'max', label: 'Maximum', positive: true },
		],
	},
	logt: {
		label: 'Log-triangular',
		expr: 'logt',
		positive: true,
		log: true,
		blurb: 'A triangle in the logarithm — the commonest shape in these '
			+ 'assessments, and what a sorption coefficient known to a factor of '
			+ 'ten usually gets.',
		params: [
			{ key: 'min', label: 'Minimum', positive: true },
			{ key: 'max', label: 'Maximum', positive: true },
			{ key: 'mode', label: 'Most likely', positive: true },
		],
	},
	// skbrnt's `logdt` (samp_util.Logdt): the double triangular in `ln x`.
	logdt: {
		label: 'Log-double-triangular',
		expr: 'logdt',
		positive: true,
		log: true,
		blurb: 'Two triangles in the logarithm that meet at the most likely value, '
			+ 'with half the probability on each side — so that value is the median '
			+ 'as well as the peak, wherever it sits between the ends.',
		params: [
			{ key: 'min', label: 'Minimum', positive: true },
			{ key: 'max', label: 'Maximum', positive: true },
			{ key: 'mode', label: 'Most likely (the median)', positive: true },
		],
	},
	Logn4: {
		label: 'Log-normal (geometric)',
		expr: 'logn',
		positive: true,
		log: true,
		blurb: 'A normal curve in the logarithm, given as a geometric mean and a '
			+ 'geometric standard deviation — a GSD of 3 means "a factor of three '
			+ 'either way".',
		params: [
			{ key: 'gm', label: 'Geometric mean', positive: true },
			{ key: 'gsd', label: 'Geometric SD', positive: true },
		],
	},
	logn: {
		label: 'Log-normal (mean, SD)',
		expr: 'logn',
		positive: true,
		log: true,
		blurb: 'The same curve, given as the ordinary mean and standard deviation '
			+ 'of the quantity itself rather than of its logarithm.',
		params: [
			{ key: 'mean', label: 'Mean', positive: true },
			{ key: 'sd', label: 'Std. deviation', positive: true },
		],
	},
	logn5: {
		label: 'Log-normal (two quantiles)',
		expr: 'logn',
		positive: true,
		log: true,
		blurb: 'A log-normal fitted through two points you know: "5% below x1, 95% '
			+ 'below x2".',
		params: [
			{ key: 'p1', label: 'First quantile' },
			{ key: 'x1', label: 'is at', positive: true },
			{ key: 'p2', label: 'Second quantile' },
			{ key: 'x2', label: 'is at', positive: true },
		],
	},
	pg: {
		label: 'List of values',
		expr: 'pg',
		list: true,
		blurb: 'Not a curve but a list — values sampled somewhere else and written '
			+ 'into the model, taken one per realisation. The commonest kind here '
			+ 'by far, and the reason a run can reproduce somebody else’s.',
		params: [],
	},
};

/** The order the editor offers them in: the shapes first, the list last. */
export const PDF_KIND_IDS = [
	'unif', 'triang', 'dtriang', 'norm', 'logu', 'logt', 'logdt', 'Logn4', 'logn', 'logn5', 'pg',
];

/**
 * Truncation, which any of them may carry, in either of the two ways it can
 * be written.
 *
 * `trmin`/`trmax` are **values**: cut the curve at 0.005 and at 0.03.
 * `pmin`/`pmax` are **probabilities**: cut it at its own 5th and 95th
 * percentiles, wherever those fall. The second is how a data set that fixes
 * the same tail fraction for a thousand element-specific distributions writes
 * it -- the numbers differ in every one of them and the rule does not -- and
 * it is the form a log-normal concentration ratio is usually quoted in.
 *
 * Both may be given, and then both apply: what is left is the part of the
 * curve inside all four. Truncating twice is not an error, and neither is
 * saying the same cut in both forms.
 */
export const TRUNCATION = [
	{ key: 'trmin', label: 'Truncate below' },
	{ key: 'trmax', label: 'Truncate above' },
];

/** The same two as percentiles of the distribution's own curve. */
export const PERCENTILE_TRUNCATION = [
	{ key: 'pmin', label: 'Truncate below percentile' },
	{ key: 'pmax', label: 'Truncate above percentile' },
];

const num = (v) => {
	if (v == null || v === '') return null;
	const n = Number(v);
	return Number.isFinite(n) ? n : null;
};

/**
 * A name rather than a number: a correlation group's, which may be either.
 *
 * Not called `name` -- `parsePDF` has a local of that name for the function it
 * is reading, and a module-level one would be shadowed exactly where it is
 * wanted.
 */
const token = (v) => {
	const t = String(v ?? '').trim();
	return t === '' ? null : t;
};

/**
 * Reads Ecolego's expression into a spec.
 *
 * @param {string} expr  the `<pdf-value>` text, `logt(min=1,max=9,mode=3)`
 * @param {string} [functionName]  the `function=` attribute, which is the kind
 * @returns {{kind: string, params: object, values: number[]|null,
 *   trmin: number|null, trmax: number|null, pmin: number|null,
 *   pmax: number|null, group: string|null, inorder: boolean, pos: number}|null}
 */
export function parsePDF(expr, functionName = '') {
	const text = String(expr ?? '').trim();
	if (!text) return null;
	const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*\(([\s\S]*)\)\s*$/.exec(text);
	if (!m) return null;
	const [, name, body] = m;

	// Commas separate arguments; a list's own values are separated by `;`, so
	// nothing inside one is mistaken for the next argument.
	const args = new Map();
	const bare = [];
	for (const piece of body.split(',')) {
		const at = piece.indexOf('=');
		if (at < 0) {
			const word = piece.trim();
			if (word) bare.push(word);
			continue;
		}
		args.set(piece.slice(0, at).trim(), piece.slice(at + 1).trim());
	}

	// The attribute is the kind. Without one -- a file written by something
	// else, or a spec typed by hand -- the argument names say which
	// parameterisation of `logn` this is, and the expression name does for the
	// rest.
	let kind = PDF_KINDS[functionName] ? functionName : null;
	if (!kind) {
		const has = (k) => args.has(k) || bare.includes(k);
		if (name === 'logn') {
			if (has('gm') || has('gsd')) kind = 'Logn4';
			else if (has('p1') || has('x1')) kind = 'logn5';
			else kind = 'logn';
		} else {
			kind = Object.keys(PDF_KINDS).find((k) => PDF_KINDS[k].expr === name) ?? null;
		}
	}
	if (!kind) return null;

	const spec = {
		kind,
		params: {},
		values: null,
		trmin: num(args.get('trmin')),
		trmax: num(args.get('trmax')),
		pmin: num(args.get('pmin')),
		pmax: num(args.get('pmax')),
		group: token(args.get('group')),
		inorder: args.get('inorder') !== 'false',
		pos: num(args.get('pos')) ?? 0,
	};
	for (const p of PDF_KINDS[kind].params) spec.params[p.key] = num(args.get(p.key));
	if (kind === 'pg') {
		const raw = args.get('values');
		spec.values = raw
			? raw.split(';').map((v) => Number(v.trim())).filter((v) => Number.isFinite(v))
			: [];
	}
	return spec;
}

/** Whether every number this kind needs has been filled in. */
export function complete(spec) {
	if (!spec || !PDF_KINDS[spec.kind]) return false;
	if (spec.kind === 'pg') return !!spec.values?.length;
	return PDF_KINDS[spec.kind].params.every((p) => spec.params?.[p.key] != null);
}

/**
 * Back to Ecolego's spelling, so a model that came from a file goes back as
 * the file had it -- including the ones that were only ever half filled in,
 * which is how Ecolego writes a kind that has been chosen and not given
 * numbers.
 */
export function formatPDF(spec) {
	if (!spec || !PDF_KINDS[spec.kind]) return '';
	const meta = PDF_KINDS[spec.kind];
	const bits = [];
	if (spec.kind === 'pg') {
		bits.push(`values=${(spec.values ?? []).join(';')}`);
	} else {
		for (const p of meta.params) {
			const v = spec.params?.[p.key];
			// The name alone where there is no number: `logn(gm,gsd)`, which is
			// what the corpus holds eleven times over.
			bits.push(v == null ? p.key : `${p.key}=${v}`);
		}
	}
	if (spec.trmin != null) bits.push(`trmin=${spec.trmin}`);
	if (spec.trmax != null) bits.push(`trmax=${spec.trmax}`);
	if (spec.pmin != null) bits.push(`pmin=${spec.pmin}`);
	if (spec.pmax != null) bits.push(`pmax=${spec.pmax}`);
	if (spec.group) bits.push(`group=${spec.group}`);
	if (spec.kind === 'pg') {
		bits.push(`inorder=${spec.inorder === false ? 'false' : 'true'}`);
		bits.push(`pos=${spec.pos ?? 0}`);
	}
	return `${meta.expr}(${bits.join(',')})`;
}

/**
 * The standard normal's CDF, to double precision.
 *
 * It was Abramowitz & Stegun 7.1.26, which is good to 7e-8 absolutely and
 * nothing like that relatively in a tail: 0.16% of the probability below
 * z = -5, 2% below -8. That is where a truncation reads it -- `trmin` and
 * `trmax` become the probabilities a draw is taken between -- so a curve cut
 * in its own tail was cut in the wrong place, and every draw from a truncated
 * normal sat up to 1e-7 in probability away from where SciPy (skbrnt) puts it.
 * `erfc` rather than `1 + erf`, because the lower tail is a small number in
 * its own right and a sum with 1 rounds it away.
 */
export function phi(z) {
	return 0.5 * erfc(-z / Math.SQRT2);
}

/* -------------------------------------------------------------------------
 * The forward and inverse CDF.
 *
 * Here rather than beside the sampler, because they are facts about the
 * *shape* -- `unif` is a straight line whoever asks -- and because the rest of
 * this module needs them: a truncation written as a pair of percentiles is a
 * probability, and turning it into the value it cuts at is `quantile`.
 * ---------------------------------------------------------------------- */

/** A log-normal's log-space mean and sd, whichever way it was written. */
function logSpace(spec) {
	const p = spec.params ?? {};
	if (spec.kind === 'Logn4') {
		return { mu: Math.log(p.gm), sigma: Math.log(p.gsd) };
	}
	if (spec.kind === 'logn') {
		// Logn.muprim / sigmaprim: an arithmetic mean and sd carried into log
		// space, which is where the curve is a normal one.
		return {
			mu: Math.log((p.mean * p.mean) / Math.sqrt(p.sd * p.sd + p.mean * p.mean)),
			sigma: Math.sqrt(Math.log(1 + (p.sd * p.sd) / (p.mean * p.mean))),
		};
	}
	if (spec.kind === 'logn5') {
		const z1 = probit(p.p1);
		const z2 = probit(p.p2);
		if (z1 == null || z2 == null || z1 === z2) return null;
		const sigma = (Math.log(p.x2) - Math.log(p.x1)) / (z2 - z1);
		if (!(sigma > 0)) return null;
		return { mu: Math.log(p.x1) - sigma * z1, sigma };
	}
	return null;
}

/**
 * The probability of being at or below `x`.
 *
 * Only needed to turn a truncation into a range of uniforms, so it is exact
 * where the shape is elementary and goes through the normal CDF where it is
 * not -- which is every log-normal, since all three parameterisations are one
 * normal curve in `ln x`.
 */
export function cdfAt(spec, x) {
	const p = spec.params ?? {};
	switch (spec.kind) {
		case 'unif': {
			if (x <= p.min) return 0;
			if (x >= p.max) return 1;
			return (x - p.min) / (p.max - p.min);
		}
		case 'triang': {
			const { min: a, max: b, mode: c } = p;
			if (x <= a) return 0;
			if (x >= b) return 1;
			return x <= c
				? ((x - a) ** 2) / ((b - a) * (c - a))
				: 1 - ((b - x) ** 2) / ((b - a) * (b - c));
		}
		case 'dtriang': {
			// skbrnt's Dtriang.cdf: each side is a right triangle holding half
			// the probability, so the mode is at exactly 1/2. A mode at an end
			// never divides by zero here -- the side it would divide on is the
			// one outside the range.
			const { min: a, max: b, mode: c } = p;
			if (x <= a) return 0;
			if (x >= b) return 1;
			return x <= c
				? ((x - a) ** 2) / (2 * (c - a) ** 2)
				: 1 - ((b - x) ** 2) / (2 * (b - c) ** 2);
		}
		case 'logu': {
			if (x <= p.min) return 0;
			if (x >= p.max) return 1;
			return (Math.log(x) - Math.log(p.min)) / (Math.log(p.max) - Math.log(p.min));
		}
		case 'logt': {
			// The triangular CDF, in `ln x`.
			const la = Math.log(p.min);
			const lb = Math.log(p.max);
			const lc = Math.log(p.mode);
			if (x <= p.min) return 0;
			if (x >= p.max) return 1;
			const lx = Math.log(x);
			return lx <= lc
				? ((lx - la) ** 2) / ((lc - la) * (lb - la))
				: 1 - ((lb - lx) ** 2) / ((lb - la) * (lb - lc));
		}
		case 'logdt': {
			// The double triangular's CDF, in `ln x`.
			if (x <= p.min) return 0;
			if (x >= p.max) return 1;
			const la = Math.log(p.min);
			const lb = Math.log(p.max);
			const lc = Math.log(p.mode);
			const lx = Math.log(x);
			return lx <= lc
				? ((lx - la) ** 2) / (2 * (lc - la) ** 2)
				: 1 - ((lb - lx) ** 2) / (2 * (lb - lc) ** 2);
		}
		case 'norm':
			return phi((x - p.mean) / p.sd);
		case 'Logn4': case 'logn': case 'logn5': {
			if (x <= 0) return 0;
			const ls = logSpace(spec);
			return ls ? phi((Math.log(x) - ls.mu) / ls.sigma) : 0;
		}
		default:
			return 0;
	}
}

/** The value at probability `u`, before truncation. */
export function quantile(spec, u) {
	const p = spec.params ?? {};
	switch (spec.kind) {
		case 'unif':
			return p.min + u * (p.max - p.min);
		case 'triang': {
			const { min: a, max: b, mode: c } = p;
			const split = (c - a) / (b - a);
			return u <= split
				? a + Math.sqrt(u * (b - a) * (c - a))
				: b - Math.sqrt((1 - u) * (b - a) * (b - c));
		}
		case 'dtriang': {
			// Dtriang.inv: the split is always the median, wherever the mode
			// sits between the ends.
			const { min: a, max: b, mode: c } = p;
			return u <= 0.5 ? a + Math.sqrt(2 * u) * (c - a) : b - (b - c) * Math.sqrt(2 * (1 - u));
		}
		case 'logu':
			return Math.exp(Math.log(p.min) + u * (Math.log(p.max) - Math.log(p.min)));
		case 'logt': {
			// The triangular quantile in `ln x`, carried back by `exp`.
			const la = Math.log(p.min);
			const lb = Math.log(p.max);
			const lc = Math.log(p.mode);
			const split = (lc - la) / (lb - la);
			const lx = u <= split
				? la + Math.sqrt(u * (lb - la) * (lc - la))
				: lb - Math.sqrt((1 - u) * (lb - la) * (lb - lc));
			return Math.exp(lx);
		}
		case 'logdt': {
			// The double triangular's quantile in `ln x`, carried back by `exp`.
			const la = Math.log(p.min);
			const lb = Math.log(p.max);
			const lc = Math.log(p.mode);
			const lx = u <= 0.5
				? la + Math.sqrt(2 * u) * (lc - la)
				: lb - (lb - lc) * Math.sqrt(2 * (1 - u));
			return Math.exp(lx);
		}
		case 'norm':
			return p.mean + p.sd * probit(u);
		case 'Logn4': case 'logn': case 'logn5': {
			const ls = logSpace(spec);
			return ls ? Math.exp(ls.mu + ls.sigma * probit(u)) : NaN;
		}
		default:
			return NaN;
	}
}

/** The density at one point, before truncation. */
function bareDensity(spec, x) {
	const p = spec.params ?? {};
	switch (spec.kind) {
		case 'unif': {
			const { min: a, max: b } = p;
			return x >= a && x <= b && b > a ? 1 / (b - a) : 0;
		}
		case 'triang': {
			// Triang.pdf, which guards the degenerate ends rather than dividing
			// by zero at them.
			const a = p.min; const b = p.max; const c = p.mode;
			if (x > a && x <= c && a !== c && b !== a) return (2 * (x - a)) / (b - a) / (c - a);
			if (x > a && x > c && x <= b && b !== a && b !== c) return (2 * (b - x)) / (b - a) / (b - c);
			return 0;
		}
		case 'dtriang': {
			// Dtriang.pdf. The two sides meet at the mode at different heights
			// unless it is the middle of the range: each holds half the
			// probability however wide it is.
			const a = p.min; const b = p.max; const c = p.mode;
			if (x > a && x <= c && a !== c) return (x - a) / (c - a) ** 2;
			if (x > a && x > c && x <= b && b !== c) return (b - x) / (b - c) ** 2;
			return 0;
		}
		case 'norm': {
			const { mean: mu, sd } = p;
			if (!(sd > 0)) return 0;
			return Math.exp(-0.5 * ((x - mu) / sd) ** 2) / (Math.sqrt(2 * Math.PI) * sd);
		}
		case 'logu': {
			const a = p.min; const b = p.max;
			if (!(a > 0 && b > a) || x < a || x > b) return 0;
			return 1 / (x * (Math.log(b) - Math.log(a)));
		}
		case 'logt': {
			const a = p.min; const b = p.max; const c = p.mode;
			if (!(a > 0 && b > 0 && c > 0) || x <= 0) return 0;
			const la = Math.log(a); const lb = Math.log(b); const lc = Math.log(c);
			const lx = Math.log(x);
			if (x > a && x <= c && a !== c) return (1 / x) * ((2 * (lx - la)) / (lc - la) / (lb - la));
			if (x > a && x > c && x <= b && b !== c) return (1 / x) * ((2 * (lb - lx)) / (lb - lc) / (lb - la));
			return 0;
		}
		case 'logdt': {
			// The double triangular's density in `ln x`, over x: a step at the
			// mode unless it is the geometric middle of the range.
			const a = p.min; const b = p.max; const c = p.mode;
			if (!(a > 0 && b > 0 && c > 0) || x <= 0) return 0;
			const la = Math.log(a); const lb = Math.log(b); const lc = Math.log(c);
			const lx = Math.log(x);
			if (x > a && x <= c && a !== c) return (lx - la) / (lc - la) ** 2 / x;
			if (x > a && x > c && x <= b && b !== c) return (lb - lx) / (lb - lc) ** 2 / x;
			return 0;
		}
		case 'Logn4': {
			const { gm, gsd } = p;
			if (!(gm > 0 && gsd > 1) || x <= 0) return 0;
			const s = Math.log(gsd);
			return Math.exp(-0.5 * ((Math.log(x) - Math.log(gm)) / s) ** 2)
				/ (x * Math.sqrt(2 * Math.PI) * s);
		}
		case 'logn': {
			// Logn.muprim / sigmaprim: an arithmetic mean and sd carried into
			// log space, which is where the curve is a normal one.
			const { mean, sd } = p;
			if (!(mean > 0 && sd > 0) || x <= 0) return 0;
			const mu = Math.log((mean * mean) / Math.sqrt(sd * sd + mean * mean));
			const sigma = Math.sqrt(Math.log(1 + (sd * sd) / (mean * mean)));
			return Math.exp(-0.5 * ((Math.log(x) - mu) / sigma) ** 2)
				/ (x * Math.sqrt(2 * Math.PI) * sigma);
		}
		case 'logn5': {
			const fit = quantileFit(p);
			if (!fit) return 0;
			if (x <= 0) return 0;
			return Math.exp(-0.5 * ((Math.log(x) - fit.mu) / fit.sigma) ** 2)
				/ (x * Math.sqrt(2 * Math.PI) * fit.sigma);
		}
		default:
			return 0;
	}
}

/** Two quantiles to a log-normal: solve for mu and sigma through both points. */
function quantileFit({ p1, x1, p2, x2 }) {
	if (!(x1 > 0 && x2 > 0)) return null;
	const z1 = probit(p1); const z2 = probit(p2);
	if (z1 == null || z2 == null || z1 === z2) return null;
	const sigma = (Math.log(x2) - Math.log(x1)) / (z2 - z1);
	if (!(sigma > 0)) return null;
	return { mu: Math.log(x1) - sigma * z1, sigma };
}

/**
 * The standard normal's inverse CDF, Acklam's rational approximation.
 *
 * Accurate to about 1.15e-9 over the whole range, which is far more than a
 * curve on screen needs and enough that the two points a `logn5` is fitted
 * through land where they were asked to. A draw from a truncated curve can
 * come back that far outside its cut; `valueAtProbability` clamps it.
 */
export function probit(p) {
	const q = Number(p);
	if (!(q > 0 && q < 1)) return null;
	const a = [-3.969683028665376e+1, 2.209460984245205e+2, -2.759285104469687e+2,
		1.383577518672690e+2, -3.066479806614716e+1, 2.506628277459239];
	const b = [-5.447609879822406e+1, 1.615858368580409e+2, -1.556989798598866e+2,
		6.680131188771972e+1, -1.328068155288572e+1];
	const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
		-2.549732539343734, 4.374664141464968, 2.938163982698783];
	const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
		3.754408661907416];
	const lo = 0.02425;
	let x;
	if (q < lo) {
		const t = Math.sqrt(-2 * Math.log(q));
		x = (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5])
			/ ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1);
	} else if (q <= 1 - lo) {
		const t = q - 0.5;
		const r = t * t;
		x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * t
			/ (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
	} else {
		const t = Math.sqrt(-2 * Math.log(1 - q));
		x = -(((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5])
			/ ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1);
	}
	return x;
}

/** Where the curve is worth drawing between. */
/**
 * Both truncations as the values they cut at, for a kind that can say.
 *
 * `trmin`/`trmax` are already values. A percentile is turned into one by the
 * quantile function, which is why that lives in this module -- and it is only
 * askable of a distribution that is filled in, so an incomplete one reports no
 * cut rather than NaN.
 *
 * `lo`/`hi` are the untruncated support, used to keep a percentile of 0 or 1
 * from reaching for the infinite tail of a curve that has one.
 */
export function valueCuts(spec, lo = -Infinity, hi = Infinity) {
	const out = { lo: spec?.trmin ?? null, hi: spec?.trmax ?? null };
	const can = spec && PDF_KINDS[spec.kind] && spec.kind !== 'pg' && complete(spec);
	const at = (p, fallback) => {
		if (!can || !(p > 0) || !(p < 1)) return p === 0 ? fallback : (p === 1 ? fallback : null);
		const v = quantile(spec, p);
		return Number.isFinite(v) ? v : null;
	};
	const pl = at(spec?.pmin, lo);
	const ph = at(spec?.pmax, hi);
	if (pl != null && Number.isFinite(pl)) out.lo = out.lo == null ? pl : Math.max(out.lo, pl);
	if (ph != null && Number.isFinite(ph)) out.hi = out.hi == null ? ph : Math.min(out.hi, ph);
	return out;
}

export function supportOf(spec) {
	if (!complete(spec)) return null;
	const p = spec.params ?? {};
	let lo; let hi;
	switch (spec.kind) {
		case 'unif': case 'triang': case 'dtriang': lo = p.min; hi = p.max; break;
		case 'logu': case 'logt': case 'logdt': lo = p.min; hi = p.max; break;
		case 'norm': lo = p.mean - 4 * p.sd; hi = p.mean + 4 * p.sd; break;
		case 'Logn4': {
			const s = Math.log(p.gsd);
			lo = p.gm * Math.exp(-4 * s); hi = p.gm * Math.exp(4 * s);
			break;
		}
		case 'logn': {
			const mu = Math.log((p.mean * p.mean) / Math.sqrt(p.sd * p.sd + p.mean * p.mean));
			const sigma = Math.sqrt(Math.log(1 + (p.sd * p.sd) / (p.mean * p.mean)));
			lo = Math.exp(mu - 4 * sigma); hi = Math.exp(mu + 4 * sigma);
			break;
		}
		case 'logn5': {
			const fit = quantileFit(p);
			if (!fit) return null;
			lo = Math.exp(fit.mu - 4 * fit.sigma); hi = Math.exp(fit.mu + 4 * fit.sigma);
			break;
		}
		case 'pg': {
			const v = spec.values ?? [];
			if (!v.length) return null;
			lo = Math.min(...v); hi = Math.max(...v);
			if (lo === hi) { lo -= Math.abs(lo) * 0.1 + 1; hi += Math.abs(hi) * 0.1 + 1; }
			break;
		}
		default: return null;
	}
	// Truncation cuts the drawing as well as the density: a curve drawn over
	// ground it has been truncated off is a curve of a different distribution.
	// A percentile cut is the same cut said the other way round, so it is
	// resolved to the value it falls at and applied beside the other.
	const cut = valueCuts(spec, lo, hi);
	if (cut.lo != null && cut.lo > lo) lo = cut.lo;
	if (cut.hi != null && cut.hi < hi) hi = cut.hi;
	if (!(Number.isFinite(lo) && Number.isFinite(hi) && hi > lo)) return null;
	return [lo, hi];
}

/**
 * The curve to draw: `points` samples of the density across its support.
 *
 * Truncation is applied by cutting and rescaling so the area is one again.
 * The scale factor is the trapezoid sum over these very points rather than an
 * analytic CDF -- it is a picture, the grid is fine, and an area that comes
 * out at 0.999 would not be visible. What it must not do is *look* like the
 * untruncated curve, and cutting alone would.
 *
 * A list (`pg`) has no density: it comes back as bars, one per bin.
 *
 * @returns {{xs: number[], ys: number[], log: boolean, bars: boolean,
 *   area: number}|null}
 */
export function curveOf(spec, { points = 240, bins = 32 } = {}) {
	const span = supportOf(spec);
	if (!span) return null;
	const [lo, hi] = span;
	const meta = PDF_KINDS[spec.kind];

	if (spec.kind === 'pg') {
		const v = spec.values ?? [];
		const width = (hi - lo) / bins;
		const xs = []; const ys = new Array(bins).fill(0);
		for (let i = 0; i < bins; i++) xs.push(lo + width * (i + 0.5));
		for (const x of v) {
			let k = Math.floor((x - lo) / width);
			if (k < 0) k = 0;
			if (k >= bins) k = bins - 1;
			ys[k] += 1;
		}
		// As a density, so the y axis means the same thing as the curves'.
		const scale = v.length * width;
		return { xs, ys: ys.map((n) => (scale > 0 ? n / scale : 0)), log: false, bars: true, area: 1 };
	}

	// Log-scaled kinds are sampled geometrically: a log-triangular over five
	// decades has all its shape in the first, and an arithmetic grid draws a
	// spike and a flat line.
	const useLog = !!meta.log && lo > 0 && hi > 0;
	const xs = [];
	for (let i = 0; i < points; i++) {
		const f = i / (points - 1);
		xs.push(useLog ? Math.exp(Math.log(lo) + f * (Math.log(hi) - Math.log(lo)))
			: lo + f * (hi - lo));
	}
	const ys = xs.map((x) => bareDensity(spec, x));

	// Trapezoid over the drawn points, which is the area the picture shows.
	let area = 0;
	for (let i = 1; i < xs.length; i++) area += ((ys[i] + ys[i - 1]) / 2) * (xs[i] - xs[i - 1]);
	const truncated = spec.trmin != null || spec.trmax != null
		|| spec.pmin != null || spec.pmax != null;
	if (truncated && area > 0) for (let i = 0; i < ys.length; i++) ys[i] /= area;
	return { xs, ys, log: useLog, bars: false, area: truncated ? 1 : area };
}

/** One line saying what this is, for a row that has no room for a chart. */
export function describePDF(spec) {
	if (!spec || !PDF_KINDS[spec.kind]) return '';
	const meta = PDF_KINDS[spec.kind];
	if (!complete(spec)) return `${meta.label} — not filled in`;
	const fmt = (v) => (Math.abs(v) >= 1e4 || (v !== 0 && Math.abs(v) < 1e-3)
		? v.toExponential(2) : String(v));
	let body;
	if (spec.kind === 'pg') {
		const v = spec.values ?? [];
		body = `${v.length} value${v.length === 1 ? '' : 's'}`;
	} else {
		body = meta.params.map((p) => `${p.key} ${fmt(spec.params[p.key])}`).join(', ');
	}
	const tail = spec.group ? `, group ${spec.group}` : '';
	const cut = [];
	if (spec.trmin != null) cut.push(`≥ ${fmt(spec.trmin)}`);
	if (spec.trmax != null) cut.push(`≤ ${fmt(spec.trmax)}`);
	// A percentile cut is written as the percentile, not as the value it lands
	// on: the value is a consequence of the numbers above it and moves when
	// they do, and `p5` is what the data set this came from actually says.
	const pc = (v) => `p${String(Number((v * 100).toPrecision(4)))}`;
	if (spec.pmin != null) cut.push(`≥ ${pc(spec.pmin)}`);
	if (spec.pmax != null) cut.push(`≤ ${pc(spec.pmax)}`);
	return `${meta.label}: ${body}${cut.length ? `, truncated ${cut.join(' and ')}` : ''}${tail}`;
}

/**
 * What is wrong with it, said the way the rest of the model says things.
 *
 * Never throws and never refuses: a distribution being edited passes through
 * every half-finished state on the way to a finished one, and a field that
 * clears itself because `max` is briefly below `min` cannot be typed into.
 *
 * @returns {string[]}
 */
export function pdfProblems(spec) {
	const out = [];
	if (!spec || !PDF_KINDS[spec.kind]) return out;
	const meta = PDF_KINDS[spec.kind];
	const p = spec.params ?? {};
	for (const d of meta.params) {
		const v = p[d.key];
		if (v == null) continue;
		if (d.positive && !(v > 0)) out.push(`${d.label} has to be more than zero.`);
	}
	// A percentile is a probability, and one at either end asks for the tail
	// itself: the quantile of 0 or 1 is infinite for a curve with unbounded
	// tails, and one infinite parameter ruins a whole run.
	for (const key of ['pmin', 'pmax']) {
		const v = spec[key];
		if (v == null) continue;
		if (!(v >= 0 && v <= 1)) {
			out.push('A percentile truncation is a probability, so it has to be between '
				+ '0 and 1 — 0.05 for the 5th percentile, not 5.');
			break;
		}
	}
	if (spec.pmin != null && spec.pmax != null && !(spec.pmax > spec.pmin)) {
		out.push('The percentile truncation is inside out — nothing is left between them.');
	}
	// Both forms at once is allowed and means the intersection, but a pair that
	// leaves nothing is worth saying out loud rather than silently drawing from
	// the whole curve.
	{
		const cut = valueCuts(spec);
		if (cut.lo != null && cut.hi != null && !(cut.hi > cut.lo)) {
			const both = (spec.trmin != null || spec.trmax != null)
				&& (spec.pmin != null || spec.pmax != null);
			if (both) {
				out.push('The value truncation and the percentile truncation do not overlap — '
					+ 'between them nothing is left to draw from.');
			}
		}
	}
	if (meta.positive) {
		for (const key of ['trmin', 'trmax']) {
			if (spec[key] != null && spec[key] < 0) {
				out.push('This distribution is only defined above zero, so it cannot be '
					+ 'truncated below it.');
				break;
			}
		}
	}
	const pair = (a, b, what) => {
		if (p[a] != null && p[b] != null && !(p[b] > p[a])) {
			out.push(`${what} — the maximum has to be above the minimum.`);
		}
	};
	const ranged = ['unif', 'triang', 'dtriang', 'logu', 'logt', 'logdt'];
	if (ranged.includes(spec.kind)) pair('min', 'max', 'The range is empty');
	const moded = ['triang', 'dtriang', 'logt', 'logdt'];
	if (moded.includes(spec.kind) && p.mode != null) {
		if (p.min != null && p.mode < p.min) out.push('The most likely value is below the minimum.');
		if (p.max != null && p.mode > p.max) out.push('The most likely value is above the maximum.');
	}
	// Each side of a double triangular holds half the probability however
	// narrow it is, so a side of no width is half of every sample at one number.
	// skbrnt allows it; it is still rarely what was meant.
	if ((spec.kind === 'dtriang' || spec.kind === 'logdt') && p.mode != null && p.min != null
		&& p.max != null && p.max > p.min
		&& (p.mode === p.min || p.mode === p.max)) {
		out.push(`With the most likely value at the ${p.mode === p.min ? 'minimum' : 'maximum'}, `
			+ 'half of every sample is that one number: each side of this shape holds half '
			+ 'the probability, however narrow it is.');
	}
	if (spec.kind === 'Logn4' && p.gsd != null && p.gsd !== null && p.gsd <= 1 && p.gsd > 0) {
		out.push('A geometric standard deviation of 1 or less is a single value, not a '
			+ 'spread — it has to be more than 1.');
	}
	if (spec.kind === 'logn5') {
		for (const key of ['p1', 'p2']) {
			const v = p[key];
			if (v != null && !(v > 0 && v < 1)) {
				out.push('A quantile is a probability, so it has to be between 0 and 1.');
				break;
			}
		}
		if (p.p1 != null && p.p2 != null && p.p1 === p.p2) {
			out.push('The two quantiles have to be different.');
		}
	}
	if (spec.trmin != null && spec.trmax != null && !(spec.trmax > spec.trmin)) {
		// Ecolego writes `unif(min=0.0,max=6.5,trmin=6.5,trmax=0.0)` -- the two
		// the wrong way round, which is how it spells "no truncation". Said
		// rather than treated as an error, because the file really does contain
		// it and the model really does run.
		out.push('The truncation is inside out — nothing is left. Ecolego writes this '
			+ 'when a truncation has been cleared; clear both fields to say the same '
			+ 'thing.');
	}
	const span = supportOf(spec);
	if (complete(spec) && !span) {
		out.push('These numbers do not describe a distribution that can be drawn.');
	}
	return out;
}
