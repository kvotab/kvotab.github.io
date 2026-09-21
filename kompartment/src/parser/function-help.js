/**
 * What each function in the expression language is for.
 *
 * The table in ./functions.js says what a function *computes*; this says what
 * to tell someone who is about to type one. It exists because the equation
 * editor completes function names, and a list of seventy identifiers with no
 * signature and no description is a list you have to already know the answer
 * to read.
 *
 * The argument names are the ones the file format uses, so that a call written
 * in one of these files reads the same way here; the one-line summaries and
 * the categories are this tool's own. `percentile` has no entry in the
 * format's function list at all, and `start_time` and `end_time` are filed
 * under Time rather than under Constant, so the three clock functions sit
 * together in a list someone is scanning.
 *
 * Arity is not repeated here. It lives in ./functions.js, which is what the
 * parser checks against, and a second copy would be a second thing to get
 * wrong: `functionSignature` reads it from there.
 */

import { FUNCTIONS, FUNCTION_ALIASES, lookupFunction } from './functions.js';

/** @type {Record<string, {params: string[], category: string, summary: string}>} */
export const FUNCTION_HELP = {
	abs: { params: ['a'], category: 'General',
		summary: 'The size of a, with its sign dropped' },
	sqrt: { params: ['a'], category: 'Exponential',
		summary: 'The square root of a, for a ≥ 0' },
	exp: { params: ['a'], category: 'Exponential',
		summary: 'The exponential, e to the power a' },
	log: { params: ['a'], category: 'Exponential',
		summary: 'The natural logarithm of a' },
	log10: { params: ['a'], category: 'Exponential',
		summary: 'The logarithm of a to base 10' },
	log2: { params: ['x'], category: 'Exponential',
		summary: 'The logarithm of x to base 2' },
	power: { params: ['a', 'b'], category: 'Exponential',
		summary: 'a to the power b' },
	hypot: { params: ['a', 'b'], category: 'Exponential',
		summary: 'sqrt(a² + b²), worked out without overflowing on the way' },
	ceil: { params: ['a'], category: 'Rounding',
		summary: 'a rounded up to the nearest whole number' },
	floor: { params: ['a'], category: 'Rounding',
		summary: 'a rounded down to the nearest whole number' },
	round: { params: ['a'], category: 'Rounding',
		summary: 'a rounded to the nearest whole number, a half going up' },
	fix: { params: ['x'], category: 'Rounding',
		summary: 'x rounded towards zero, so −2.7 becomes −2' },
	sign: { params: ['d'], category: 'General',
		summary: '−1, 0 or 1, according to the sign of d' },
	eps: { params: [], category: 'Constant',
		summary: 'The gap between 1 and the next larger number, 2.2e−16' },
	ulp: { params: ['d'], category: 'General',
		summary: 'The gap between d and the next larger number' },
	pi: { params: [], category: 'Constant',
		summary: 'π, 3.14159…' },
	mod: { params: ['a', 'b'], category: 'Rounding',
		summary: 'The remainder of a divided by b, with the sign of b' },
	rem: { params: ['a', 'b'], category: 'Rounding',
		summary: 'The remainder of a divided by b, with the sign of a' },
	factorial: { params: ['n'], category: 'Arithmetic',
		summary: 'n! — the product 1 · 2 · … · n' },
	binomial: { params: ['n', 'k'], category: 'Arithmetic',
		summary: 'The number of ways to choose k things from n' },
	erf: { params: ['x'], category: 'General',
		summary: 'The Gaussian error function of x' },
	erfc: { params: ['x'], category: 'General',
		summary: '1 − erf(x), kept accurate where erf is close to 1' },
	sin: { params: ['a'], category: 'Trigonometry',
		summary: 'The sine of a, in radians' },
	cos: { params: ['a'], category: 'Trigonometry',
		summary: 'The cosine of a, in radians' },
	tan: { params: ['a'], category: 'Trigonometry',
		summary: 'The tangent of a, in radians' },
	asin: { params: ['a'], category: 'Trigonometry',
		summary: 'The angle in radians whose sine is a' },
	acos: { params: ['a'], category: 'Trigonometry',
		summary: 'The angle in radians whose cosine is a' },
	atan: { params: ['a'], category: 'Trigonometry',
		summary: 'The angle in radians whose tangent is a' },
	atan2: { params: ['x', 'y'], category: 'Trigonometry',
		summary: 'The angle in radians of the point (y, x), in whichever quadrant it lies' },
	sinh: { params: ['x'], category: 'Trigonometry',
		summary: 'The hyperbolic sine of x' },
	cosh: { params: ['x'], category: 'Trigonometry',
		summary: 'The hyperbolic cosine of x' },
	tanh: { params: ['x'], category: 'Trigonometry',
		summary: 'The hyperbolic tangent of x' },
	asinh: { params: ['x'], category: 'Trigonometry',
		summary: 'The inverse hyperbolic sine of x' },
	acosh: { params: ['x'], category: 'Trigonometry',
		summary: 'The inverse hyperbolic cosine of x' },
	atanh: { params: ['x'], category: 'Trigonometry',
		summary: 'The inverse hyperbolic tangent of x' },
	min: { params: ['a', 'b'], category: 'General',
		summary: 'The smallest of the arguments' },
	max: { params: ['a', 'b'], category: 'General',
		summary: 'The largest of the arguments' },
	sum: { params: ['a', 'b'], category: 'General',
		summary: 'The sum of the arguments' },
	prod: { params: ['a', 'b'], category: 'General',
		summary: 'The product of the arguments' },
	mean: { params: ['a', 'b'], category: 'General',
		summary: 'The arithmetic mean of the arguments' },
	if: { params: ['logical_test', 'value_if_true', 'value_if_false'], category: 'Logical',
		summary: 'One value when the test holds, another when it does not' },
	not: { params: ['x'], category: 'Logical',
		summary: '1 when x is zero, else 0' },
	and: { params: ['a', 'b'], category: 'Logical',
		summary: '1 when every argument is non-zero, else 0' },
	or: { params: ['a', 'b'], category: 'Logical',
		summary: '1 when any argument is non-zero, else 0' },
	nand: { params: ['a', 'b'], category: 'Logical',
		summary: '0 when every argument is non-zero, else 1' },
	nor: { params: ['a', 'b'], category: 'Logical',
		summary: '1 when every argument is zero, else 0' },
	xor: { params: ['a', 'b'], category: 'Logical',
		summary: '1 when exactly one argument is non-zero, else 0' },
	percentile: { params: ['phi', 'a'], category: 'General',
		summary: 'The phi-th percentile of the values that follow it' },
	interpolationUseEndValues: { params: ['xi', 'x', 'y'], category: 'Table lookup',
		summary: 'Reads a table written into the equation: the point, then x, y pairs' },
	interpolationExtrapolation: { params: ['xi', 'x', 'y'], category: 'Table lookup',
		summary: 'The same, extrapolating beyond the ends of the table rather than holding' },
	// Two conversions between an activity and an amount of substance, with the
	// half-life in years as the second argument.
	bq2mole: { params: ['bq', 'half_life_years'], category: 'General',
		summary: 'An activity as an amount of substance, in moles' },
	mole2bq: { params: ['mole', 'half_life_years'], category: 'General',
		summary: 'An amount of substance in moles as an activity, in Bq' },
	rampDown: { params: ['x', 'start', 'end'], category: 'Transitions',
		summary: '1 before start, 0 after end, a straight line between — a '
			+ 'switch with a width, which a stiff solver walks over where it '
			+ 'would have to bisect its way across a step' },
	rampUp: { params: ['x', 'start', 'end'], category: 'Transitions',
		summary: '0 before start, 1 after end; 1 − rampDown' },
	smoothDown: { params: ['x', 'X', 'sharpness'], category: 'Transitions',
		summary: '1 for small x, 0.5 at X, approaching 0 beyond — a smoothed '
			+ 'step. A larger sharpness makes the change quicker, not slower' },
	smoothUp: { params: ['x', 'X', 'sharpness'], category: 'Transitions',
		summary: '0 for small x, 0.5 at X, approaching 1 beyond; 1 − smoothDown' },
	time: { params: [], category: 'Time',
		summary: 'The current simulation time, in the simulation’s time unit' },
	start_time: { params: [], category: 'Time',
		summary: 'The first simulation time point' },
	end_time: { params: [], category: 'Time',
		summary: 'The last simulation time point' },
	// The three the run writes for a transport operation that takes an
	// argument -- `Op(x)` in a model becomes `transport_point(c1, …, cn, x)`.
	// Not Ecolego's: there the operation is a block, and the arithmetic is
	// generated straight into the model class. Named here so that the code
	// tab and the completer can say what they are.
	transport_point: { params: ['c1', 'cn', 'x'], category: 'Transport',
		summary: 'The compartment of a transport chain at position x (0 to 1) along it' },
	transport_sum: { params: ['c1', 'cn', 'from', 'to'], category: 'Transport',
		summary: 'The sum over a transport chain between two positions (0 to 1) along it' },
	transport_mean: { params: ['c1', 'cn', 'from', 'to'], category: 'Transport',
		summary: 'The mean over a transport chain between two positions (0 to 1) along it' },
};

/** Categories in the order a list of every function should walk them. */
export const FUNCTION_CATEGORIES = [
	'General', 'Arithmetic', 'Exponential', 'Trigonometry', 'Rounding',
	'Logical', 'Table lookup', 'Time', 'Transitions', 'Constant', 'Transport',
];

/**
 * How a call is written: `min(a, …)`, `if(logical_test, value_if_true[,
 * value_if_false])`, `pi`.
 *
 * Read off the arity in ./functions.js rather than written out, so a function
 * whose arity changes cannot end up with a signature that lies about it. The
 * argument names are the file format's; where there are fewer names than required
 * arguments the rest are numbered from the last one, which is what the
 * variadic table-lookup functions need (`xi, x1, y1, …`).
 */
export function functionSignature(name) {
	const fn = lookupFunction(name);
	if (!fn) return null;
	const help = FUNCTION_HELP[fn.key];
	const names = [...(help?.params ?? [])];
	const max = fn.maxArity ?? (fn.varargs ? Infinity : fn.arity);
	const nameAt = (i) => names[i] ?? `${names[names.length - 1] ?? 'a'}${i + 1}`;

	// A function that takes nothing may be written bare -- `time`, not
	// `time()` -- and the parser accepts both, so the bare form is what is
	// shown and what is inserted.
	if (max === 0) return fn.key;

	const parts = [];
	for (let i = 0; i < fn.arity; i++) parts.push(nameAt(i));
	if (fn.varargs) parts.push('…');
	let sig = `${fn.key}(${parts.join(', ')}`;
	if (!fn.varargs && max > fn.arity) {
		const rest = [];
		for (let i = fn.arity; i < max; i++) rest.push(nameAt(i));
		sig += `[, ${rest.join(', ')}]`;
	}
	return `${sig})`;
}

/**
 * Everything worth showing about one function, by any name it answers to.
 *
 * `alias` is set when the name asked for is one of the spellings Ecolego
 * accepts for another function -- `ln` for `log`, `pow` for `power` -- because
 * an equation that says `ln` should say so in the list rather than silently
 * offering something else.
 */
export function functionHelp(name) {
	const fn = lookupFunction(name);
	if (!fn) return null;
	const help = FUNCTION_HELP[fn.key] ?? { category: 'General', summary: '' };
	const alias = FUNCTION_ALIASES[name] ? fn.key : null;
	return {
		name,
		key: fn.key,
		alias,
		arity: fn.arity,
		maxArity: fn.maxArity ?? (fn.varargs ? Infinity : fn.arity),
		varargs: !!fn.varargs,
		category: help.category,
		summary: help.summary,
		signature: alias
			? functionSignature(fn.key).replace(new RegExp(`^${fn.key}`), name)
			: functionSignature(fn.key),
	};
}

/**
 * Every name an equation may call, canonical spellings first and then the
 * aliases, each one sorted. Aliases are included because real .eco files use
 * them: `ln`, `pow`, `fabs`, `sgn` and `product` all appear in Ecolego's own
 * resources/functions/functions.txt.
 */
export function functionNames() {
	return [
		...Object.keys(FUNCTIONS).sort(),
		...Object.keys(FUNCTION_ALIASES).sort(),
	];
}
