/**
 * Function library for the model expression language.
 *
 * Names and arities match what a model file may contain, so that equations
 * written for one of the desktop tools transfer verbatim.
 *
 * Each entry is { arity, fn, varargs?, needsContext? }. `arity` is the minimum
 * argument count; `maxArity` caps it where the language does.
 */

import { interpolateArgs, interpolateSlope } from '../domain/lookup.js';
import { percentile as percentileOf } from '../domain/reduce.js';
import { SECONDS_PER_YEAR } from '../domain/nuclides.js';

/** Avogadro's number (mol^-1), to the precision model files state it. */
const AVOGADRO = 6.02214179e23;

const EPS = Math.pow(2, -52);

/** Truncate towards zero. */
function fix(a) {
	return a < 0 ? Math.ceil(a) : Math.floor(a);
}

/**
 * Abramowitz & Stegun 7.1.26 is only good to ~1e-7; the desktop tools' erf comes
 * from a higher precision series, so we use the Numerical Recipes erfc rational
 * approximation (fractional error < 1.2e-7 everywhere) refined by one
 * Newton step against the defining integral's derivative.
 */
function erfc(x) {
	const z = Math.abs(x);
	const t = 2 / (2 + z);
	const ty = 4 * t - 2;
	const cof = [
		-1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2,
		-9.561514786808631e-3, -9.46595344482036e-4, 3.66839497852761e-4,
		4.2523324806907e-5, -2.0278578112534e-5, -1.624290004647e-6,
		1.303655835580e-6, 1.5626441722e-8, -8.5238095915e-8,
		6.529054439e-9, 5.059343495e-9, -9.91364156e-10,
		-2.27365122e-10, 9.6467911e-11, 2.394038e-12,
		-6.886027e-12, 8.94487e-13, 3.13092e-13,
		-1.12708e-13, 3.81e-16, 7.106e-15,
	];
	let d = 0, dd = 0;
	for (let j = cof.length - 1; j > 0; j--) {
		const tmp = d;
		d = ty * d - dd + cof[j];
		dd = tmp;
	}
	const ans = t * Math.exp(-z * z + 0.5 * (cof[0] + ty * d) - dd);
	return x >= 0 ? ans : 2 - ans;
}

function erf(x) {
	return 1 - erfc(x);
}

/**
 * n!, capped where the double runs out.
 *
 * The loop is only reachable for arguments the answer is actually finite for.
 * 171! overflows, so everything above 170 used to spend its multiplications
 * arriving at Infinity the slow way: `factorial(3e8)` took 450 ms and
 * `factorial(1e12)` never came back at all -- in the worker that is not a slow
 * equation, it is a simulation that hangs with nothing to cancel.
 *
 * 170 is not a round number chosen here; it is where the format's own table stops.
 * the factorial calls `Arithmetic.factorial((int) k)`, which is a table
 * lookup -- 21 long entries then 150 double ones, so 0..170 -- and returns
 * Double.POSITIVE_INFINITY past the end of it. Negative there throws; this
 * tool has always returned NaN, which is how a bad argument travels through
 * the rest of the expression rather than stopping the run.
 */
const FACTORIAL_MAX = 170;

function factorial(n) {
	const k = Math.round(n);
	// Not `k < 0`: that is false for NaN, and the loop below then returned 1
	// for it -- a number, out of nothing.
	if (!(k >= 0)) return NaN;
	if (k > FACTORIAL_MAX) return Infinity;
	let r = 1;
	for (let i = 2; i <= k; i++) r *= i;
	return r;
}

function binomial(n, k) {
	return factorial(n) / (factorial(k) * factorial(n - k));
}

/**
 * The compartment of a transport chain at a position along it.
 *
 * `states` are the chain's compartments in order and `x` is a fraction of its
 * length. the transport code generator, case POINT:
 *
 *     if( arg0 == 1.0 ) sum = getState(n-1);
 *     else { final int f = (int) (arg0*n); sum = getState(f); }
 *
 * so the chain is read as n equal cells and `x` falls in cell floor(x*n),
 * except that exactly 1 is the last cell rather than one past it.
 */
function transportPoint(args) {
	const x = args[args.length - 1];
	const n = args.length - 1;
	if (Number.isNaN(x)) return NaN;
	if (x < 0) throw new RangeError(`transport operation: the position ${x} is lower than zero`);
	if (x > 1) throw new RangeError(`transport operation: the position ${x} is higher than one`);
	return args[x === 1 ? n - 1 : Math.trunc(x * n)];
}

/**
 * The sum, or the mean, over a stretch of a transport chain.
 *
 * `states` are the chain's compartments in order; the last two arguments are
 * the two ends of the stretch as fractions of its length, in either order.
 * The stretch is n equal cells: the cells wholly inside count once, and the
 * two cells the ends fall in count by the fraction of each that is inside.
 * A mean divides by that many cells. the transport code generator, case
 * RANGE, line for line -- including `(int)`, which truncates, so a stretch
 * that ends exactly on a cell boundary takes nothing from the cell beyond it.
 */
function transportRange(args, mean) {
	const n = args.length - 2;
	let from = args[n];
	let to = args[n + 1];
	if (Number.isNaN(from) || Number.isNaN(to)) return NaN;
	if (from > to) [from, to] = [to, from];
	if (from < 0) {
		throw new RangeError(`transport operation: the range starts at ${from}, which is lower than zero`);
	}
	if (to > 1) {
		throw new RangeError(`transport operation: the range ends at ${to}, which is higher than one`);
	}
	let sum = 0;
	if (from === 0 && to === 1) {
		for (let e = 0; e < n; e++) sum += args[e];
		return mean ? sum / n : sum;
	}
	const f = Math.trunc(from * n) + 1;
	const t = Math.trunc(to * n);
	let cells = 0;
	if (t > f) {
		for (let e = f; e < t; e++) sum += args[e];
		cells += t - f;
	}
	const dx = f - from * n;
	cells += dx;
	sum += args[f - 1] * dx;
	if (to < 1) {
		const dy = to * n - t;
		cells += dy;
		sum += args[t] * dy;
	}
	return mean ? sum / cells : sum;
}

/**
 * Ecolego treats non-zero as true, and returns 1/0 from logical functions.
 *
 * NaN is therefore true, which is worth saying out loud because it is not the
 * obvious choice. The rule is `a != 0.0` and nothing else: the `and` function is
 * `a != 0.0 && b != 0.0`, the `if` function is `bool != 0 ? istrue :
 * isfalse`, and where an equation writes a bare value as a condition
 * the conditional rewrite rewrites it to `0.0 != a`. All
 * three say true for NaN.
 *
 * This used to read `v !== 0 && !Number.isNaN(v)`, so the same expression
 * answered two ways depending on which path compiled it: `(0/0) && 1` went
 * through the inline template in ../parser/compile.js and was 1, while
 * `and(0/0, 1)` came here and was 0.
 */
const truthy = (v) => v !== 0;
const bool = (b) => (b ? 1 : 0);

/**
 * 1 before `start`, 0 after `end`, a straight line between.
 *
 * Degenerate widths are the interesting case and are answered rather than
 * divided by: `start === end` is a hard step at that point, and a range given
 * backwards is read the way it was written -- 1 up to the smaller of the two
 * and 0 past the larger -- rather than producing a ramp that runs the wrong
 * way.
 */
function rampDown(x, start, end) {
	const a = Math.min(start, end);
	const b = Math.max(start, end);
	if (!(x > a)) return 1;
	if (x >= b) return 0;
	return (b - x) / (b - a);
}

/**
 * A step of controllable sharpness: 1 for small `x`, 0.5 at `X`, 0 beyond.
 *
 * AMBER Reference Manual §9.3.7, equation 9.1. `s` larger makes the transition
 * *sharper*; at very large `s` it is a step in all but name, and at `s` near
 * zero it is barely a transition at all.
 */
function smoothDown(x, X, s) {
	if (!(x > 0)) return 1;
	if (!(X > 0)) return 0;
	const r = Math.pow(x / X, 2 * s);
	return Number.isFinite(r) ? 1 / (1 + r) : 0;
}

export const FUNCTIONS = {
	// --- general ---------------------------------------------------------
	abs: { arity: 1, fn: Math.abs },
	sqrt: { arity: 1, fn: Math.sqrt },
	exp: { arity: 1, fn: Math.exp },
	log: { arity: 1, fn: Math.log }, // natural log, per LogMetadata
	log10: { arity: 1, fn: Math.log10 },
	log2: { arity: 1, fn: Math.log2 },
	power: { arity: 2, fn: Math.pow },
	hypot: { arity: 2, fn: Math.hypot },
	ceil: { arity: 1, fn: Math.ceil },
	floor: { arity: 1, fn: Math.floor },
	round: { arity: 1, fn: Math.round },
	fix: { arity: 1, fn: fix },
	sign: { arity: 1, fn: Math.sign },
	eps: { arity: 0, maxArity: 0, fn: () => EPS },
	ulp: { arity: 1, fn: (a) => Math.abs(a) * EPS },
	pi: { arity: 0, maxArity: 0, fn: () => Math.PI },

	// The two are distinguished by the rounding used on the quotient.
	mod: { arity: 2, fn: (a, b) => (b === 0 ? a : a - b * Math.floor(a / b)) },
	rem: { arity: 2, fn: (a, b) => (b === 0 ? NaN : a - b * fix(a / b)) },

	factorial: { arity: 1, fn: factorial },
	binomial: { arity: 2, fn: binomial },
	erf: { arity: 1, fn: erf },
	erfc: { arity: 1, fn: erfc },

	// --- trigonometry ----------------------------------------------------
	sin: { arity: 1, fn: Math.sin },
	cos: { arity: 1, fn: Math.cos },
	tan: { arity: 1, fn: Math.tan },
	asin: { arity: 1, fn: Math.asin },
	acos: { arity: 1, fn: Math.acos },
	atan: { arity: 1, fn: Math.atan },
	atan2: { arity: 2, fn: Math.atan2 },
	sinh: { arity: 1, fn: Math.sinh },
	cosh: { arity: 1, fn: Math.cosh },
	tanh: { arity: 1, fn: Math.tanh },
	asinh: { arity: 1, fn: Math.asinh },
	acosh: { arity: 1, fn: Math.acosh },
	atanh: { arity: 1, fn: Math.atanh },

	// --- aggregates (variadic) -------------------------------------------
	min: { arity: 1, varargs: true, fn: (...a) => Math.min(...a) },
	max: { arity: 1, varargs: true, fn: (...a) => Math.max(...a) },
	sum: { arity: 1, varargs: true, fn: (...a) => a.reduce((s, v) => s + v, 0) },
	prod: { arity: 1, varargs: true, fn: (...a) => a.reduce((s, v) => s * v, 1) },
	mean: {
		arity: 1,
		varargs: true,
		fn: (...a) => a.reduce((s, v) => s + v, 0) / a.length,
	},

	// --- logical ---------------------------------------------------------
	if: {
		arity: 2,
		maxArity: 3,
		fn: (t, a, b = 0) => (truthy(t) ? a : b),
	},
	not: { arity: 1, fn: (a) => bool(!truthy(a)) },
	and: { arity: 2, varargs: true, fn: (...a) => bool(a.every(truthy)) },
	or: { arity: 2, varargs: true, fn: (...a) => bool(a.some(truthy)) },
	nand: { arity: 2, varargs: true, fn: (...a) => bool(!a.every(truthy)) },
	nor: { arity: 2, varargs: true, fn: (...a) => bool(!a.some(truthy)) },
	xor: {
		arity: 2,
		varargs: true,
		fn: (...a) => bool(a.filter(truthy).length % 2 === 1),
	},

	// --- lookup ----------------------------------------------------------
	// A table written into the equation itself, for one too small to be worth
	// a block: the lookup point, then the table interleaved as x, y pairs.
	// the interpolation modes the format defines.
	// `slope` is not callable from an equation -- the parser only ever looks at
	// `fn`. It is there for the generated Jacobian, which needs d/dXI.
	// The percentile of the values that follow it, as
	// the standard percentile definition. An `index-operation` block set
	// to PERCENTILE compiles to this.
	percentile: {
		arity: 2, varargs: true,
		fn: (phi, ...a) => percentileOf(phi, a),
	},

	interpolationUseEndValues: {
		arity: 3, varargs: true,
		fn: (...a) => interpolateArgs(a, 'linear'),
		slope: (...a) => interpolateSlope(a, 'linear'),
	},
	interpolationExtrapolation: {
		arity: 3, varargs: true,
		fn: (...a) => interpolateArgs(a, 'extrapolate'),
		slope: (...a) => interpolateSlope(a, 'extrapolate'),
	},

	// --- radionuclide units ----------------------------------------------
	// `bq2mole` and `mole2bq` are the two names the built-in function library exposes to equations
	// for moving between an activity and an amount of substance. The
	// conversion needs the half-life, which is why it is an argument and not
	// something the model's decay unit could do for you: an activity is a rate
	// of decays and an amount is a count, and only lambda relates them.
	//
	//   A = ln2 * n * N_A / T        n = A * T / (ln2 * N_A)
	//
	// The half-life is in years, as the built-in expects. Two deliberate
	// divergences from it:
	//
	// the mole-to-becquerel conversion computes `halflife_seconds = halflife_years /
	// YEAR_IN_SECONDS`, dividing where it must multiply, so it is not the
	// inverse of its own `bq2Mole` -- the two are out by YEAR_IN_SECONDS
	// squared, about 1e15. Reproducing an arithmetic slip is not fidelity.
	// (Neither is reachable from an Ecolego equation as it stands: the name
	// map sends them to the becquerel-to-mole conversion and the mole-to-becquerel conversion, which are not
	// the methods' names, so the generated code would not compile.)
	//
	// And the year here is this tool's own, 365.25 days, rather than the built-in library’s
	// 31556952 s. They differ by 2e-5, and agreeing with the lambda this
	// engine actually integrates with matters more: it makes `mole2bq(n, T)`
	// exactly `lambda_per_second * n * N_A`.
	bq2mole: {
		arity: 2,
		fn: (bq, halfLifeYears) => (bq * halfLifeYears * SECONDS_PER_YEAR) / (Math.LN2 * AVOGADRO),
	},
	mole2bq: {
		arity: 2,
		fn: (mole, halfLifeYears) => (Math.LN2 * mole * AVOGADRO) / (halfLifeYears * SECONDS_PER_YEAR),
	},

	// --- transport operations --------------------------------------------
	// What a transport operation with an argument comes to, written out by
	// the run for every `Op(x)` in the model: the chain's compartments first
	// and the caller's own argument(s) last. the transport code generator
	// generates exactly this arithmetic, so the rounding is the format's --
	// `(int)` truncates -- and so is the refusal of a position outside 0..1,
	// which there is a SolverException. See ../sim/transport.js.
	transport_point: { arity: 2, varargs: true, fn: (...a) => transportPoint(a) },
	transport_sum: { arity: 3, varargs: true, fn: (...a) => transportRange(a, false) },
	transport_mean: { arity: 3, varargs: true, fn: (...a) => transportRange(a, true) },

	// --- transitions ------------------------------------------------------
	//
	// A model that switches something on -- a cap failing, a well being drilled,
	// a glaciation arriving -- has to say *how* it switches. A hard step is the
	// honest shape for an event and the worst possible input to a stiff solver:
	// it has no derivative, and an adaptive stepper meets it by rejecting steps
	// until it has bisected its way across. These are the two answers AMBER
	// offers (Reference Manual §9.3.7), and both are worth having for the same
	// reason -- they are differentiable, so the solver walks over them.
	//
	// A ramp is linear between two times and flat outside them. `rampDown` is 1
	// before `start` and 0 after `end`; `rampUp` is its complement. Where `x`
	// is the clock, `start` and `end` are the times to declare as switch times
	// (see `switchTimes` in ../domain/switchtimes.js), because the corners are
	// still corners even if the middle is smooth.
	rampDown: { arity: 3, fn: rampDown },
	rampUp: { arity: 3, fn: (x, a, b) => 1 - rampDown(x, a, b) },
	// A smooth step, with the width of the transition as an argument rather
	// than as a second time:
	//
	//     smoothDown(x, X, s) = 1 / (1 + (x/X)^(2s))   for x > 0, else 1
	//
	// so it is 1 for small x, 0.5 at x = X, and approaches 0 beyond -- and a
	// larger `s` makes the change sharper, not smoother, which is the one thing
	// about it worth reading twice. `s` is dimensionless; `x` and `X` share a
	// unit.
	smoothDown: { arity: 3, fn: smoothDown },
	smoothUp: { arity: 3, fn: (x, X, s) => 1 - smoothDown(x, X, s) },

	// --- time ------------------------------------------------------------
	// These read the simulation clock rather than their arguments, so they are
	// flagged and receive the evaluation context as a hidden first parameter.
	time: { arity: 0, maxArity: 0, needsContext: true, fn: (ctx) => ctx.t },
	start_time: {
		arity: 0, maxArity: 0, needsContext: true, fn: (ctx) => ctx.startTime,
	},
	end_time: {
		arity: 0, maxArity: 0, needsContext: true, fn: (ctx) => ctx.endTime,
	},
};

/** Aliases accepted by the Ecolego parser (see resources/functions/functions.txt). */
export const FUNCTION_ALIASES = {
	fabs: 'abs',
	ln: 'log',
	pow: 'power',
	sgn: 'sign',
	product: 'prod',
};

export function lookupFunction(name) {
	const key = FUNCTION_ALIASES[name] ?? name;
	return FUNCTIONS[key] ? { key, ...FUNCTIONS[key] } : null;
}

export { erf, erfc, fix, EPS };
