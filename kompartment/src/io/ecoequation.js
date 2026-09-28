/**
 * Equations in Ecolego's spelling, for the .eco export (./ecoexport.js).
 *
 * This tool's equation language is Ecolego's with more in it, and an equation
 * that uses the more is refused by Ecolego or, worse, read by it and then not
 * compiled: its validation passes and the Java it generates from the equation
 * does not. Each rule below was found by running equations through Ecolego
 * 6.5's own reader and simulator and comparing the numbers with this tool's:
 *
 * - **A unit written against a number**, `0.01[m]`, is this tool's own; Ecolego
 *   reads the equation as empty. The number goes without it -- the unit is
 *   bookkeeping for the checker, and the value is the same.
 * - **A comparison or a logical test is a condition, not a number**, in the
 *   Java Ecolego writes: `(a > b) * 3`, `x == 1 == 1`, `if(c, 1, 2) > 1`,
 *   `and(a > 0, b > 0)` and `3 && 2` all fail to compile or to build. So a test
 *   is only ever written as the condition of an `if()`, joined by `&&` and
 *   `||`, and a test that stands for a number is `if(test, 1, 0)`. A number
 *   inside a test is `x ~= 0`, which is what this tool means by true -- NaN
 *   included, as Ecolego has it.
 * - **`?:` and `!=`** do not parse there: `if()` and `~=`.
 * - **A sign after an operator** is bracketed: Ecolego wants `a^(-b)`, not
 *   `a^-b`, and writes `a - -b` into Java as `a--b`.
 * - **Five spellings** it does not know -- `ln`, `pow`, `sgn`, `fabs`,
 *   `product` -- are `log`, `power`, `sign`, `abs` and `prod`.
 * - **`min`, `max`, `sum`, `prod` and `mean` of one value** are that value;
 *   Ecolego wants two at least. `and` and `or` of more than two are one test.
 * - **Functions it has no counterpart for** are written out as the arithmetic
 *   they stand for, operation for operation, so the number is the same to the
 *   last bit: `mole2bq`, `bq2mole`, `ulp`, the ramps and smooth steps, `nand`,
 *   `nor` and `xor`.
 * - **`mod` and `rem`** Ecolego has, and works out as the exact remainder,
 *   Java's `%`; this tool works them out as `a - b * floor(a / b)` and
 *   `a - b * fix(a / b)`, which is not always the same number: half of all
 *   pairs differ in the last bit, and `mod(1, 0.1)` is 0 here and 0.0999…
 *   there, a whole period at the instant a saw-tooth jumps. So they go out as
 *   that arithmetic, which Java does to the bit -- and `mod(a, 0)`, which is
 *   `a` here, is guarded wherever the divisor is not a number other than zero.
 * - **`asinh`, `acosh` and `atanh`** Ecolego lists and cannot run: the Java it
 *   writes calls `Math.asinh`, which Java does not have. They are written as
 *   the logarithms they are, with a short series near zero and a logarithm of
 *   their size far out, where the plain formula would lose its digits or
 *   overflow -- which agrees with this tool's to about twelve figures, not to
 *   the bit, since the two libraries work them out differently.
 * - **`percentile` and the transport operations** have no counterpart at all,
 *   and a block that calls one is left out (see `unsupportedCalls`).
 * - **A table read at a value and repeated over its range** Ecolego repeats
 *   over the *time*: its code for a cyclic table reads the clock and never
 *   the argument. The caller says which tables those are (`options.call`),
 *   and each call wraps its value into the table's range the way
 *   ../domain/lookup.js does -- `rem` is Java's `%`, which is JavaScript's --
 *   so the table can go out unrepeated.
 *
 * An equation that needs none of this is written as it was typed. One that
 * does is written again from its parse, with the numbers spelled as they were
 * written and only the brackets the grammar needs -- and the sign rule's.
 *
 * The Python package's io/ecoequation.py is the same, and the export tests
 * compare the two byte for byte.
 */

import { tokenize, parse } from '../parser/parser.js';
import { FUNCTION_ALIASES, lookupFunction } from '../parser/functions.js';

/** Calls with no Ecolego counterpart and no written-out form: a block that makes one is left out. */
export const NO_ECOLEGO_FUNCTION = new Set(['percentile', 'transport_point', 'transport_sum', 'transport_mean']);

/**
 * The constants the written-out functions need, as Java writes them
 * (`javaDouble` in ./ecoexport.js; a test holds the two together): ln 2, this
 * tool's Avogadro number and year in seconds (../parser/functions.js), and the
 * largest double, which is how "finite" is asked of a number that cannot be
 * negative.
 */
export const LN2_TEXT = '0.6931471805599453';
export const AVOGADRO_TEXT = '6.02214179E23';
export const SECONDS_PER_YEAR_TEXT = '3.15576E7';
export const MAX_DOUBLE_TEXT = '1.7976931348623157E308';

/** The written-out functions Ecolego has too, working them out another way. */
export const WORKED_OTHERWISE = new Set(['mod', 'rem']);

const WRITTEN_OUT = new Set([
	'mole2bq', 'bq2mole', 'ulp', 'rampDown', 'rampUp', 'smoothDown', 'smoothUp', 'nand', 'nor', 'xor',
	'asinh', 'acosh', 'atanh', ...WORKED_OTHERWISE,
]);

/** The written-out functions that agree to rounding rather than to the bit. */
export const TO_ROUNDING = new Set(['asinh', 'acosh', 'atanh']);
const LOGICAL_CALLS = new Set(['and', 'or', 'not', 'nand', 'nor', 'xor']);
const AGGREGATES = new Set(['min', 'max', 'sum', 'prod', 'mean']);
const COMPARISONS = new Set(['<', '<=', '>', '>=', '==', '~=']);
const TEST_OPERATORS = new Set([...COMPARISONS, '&&', '||', '!=', '?']);

/** The calls that make an equation worth writing again, by the name it is written with. */
const CALLS_TO_WRITE = new Set([
	...Object.keys(FUNCTION_ALIASES), ...WRITTEN_OUT, ...LOGICAL_CALLS, ...AGGREGATES, ...NO_ECOLEGO_FUNCTION,
	'if',
]);

/** How tightly a printed expression holds together: an operator's own precedence, or these. */
const PRIMARY = 10;
const POWER = 8;
const UNARY = 7;
const PRECEDENCE = { '+': 5, '-': 5, '*': 6, '/': 6 };

const num = (text) => ({ type: 'num', value: Number(text), text });
const call = (name, args) => ({ type: 'call', name, args });
const binary = (op, left, right) => ({ type: 'binary', op, left, right });

/** Whether a node is a test rather than a number. */
function isTest(node) {
	return (node.type === 'binary' && (COMPARISONS.has(node.op) || node.op === '&&' || node.op === '||'))
		|| (node.type === 'call' && LOGICAL_CALLS.has(node.name));
}

/** The operators after which Ecolego wants a sign bracketed. */
const ARITHMETIC = new Set(['+', '-', '*', '/', '^', '.*', './', '.^']);

/**
 * What the tokens say: whether the equation may have to be written again
 * (`look`), and whether it certainly does (`must`) -- a spelling Ecolego does
 * not have, `!=`, or a sign straight after an arithmetic operator. Whether a
 * test or a call has to change is for the tree to say.
 */
function scan(toks, wraps) {
	let look = false;
	let must = false;
	for (let i = 0; i < toks.length; i++) {
		const t = toks[i];
		const next = toks[i + 1];
		if (t.type === 'number' && next?.type === 'lbracket') look = must = true;
		if (t.type === 'op') {
			if (TEST_OPERATORS.has(t.text)) look = true;
			if (t.text === '!=') must = true;
			if (ARITHMETIC.has(t.text) && next?.type === 'op' && (next.text === '-' || next.text === '+')) look = must = true;
		}
		if (t.type === 'ident' && next?.type === 'lparen' && CALLS_TO_WRITE.has(t.value)) {
			look = true;
			if (Object.prototype.hasOwnProperty.call(FUNCTION_ALIASES, t.value)) must = true;
		}
		if (t.type === 'ident' && next?.type === 'lparen' && wraps?.(t.value)) look = must = true;
	}
	return { look, must };
}

/**
 * The names of the calls in an equation that Ecolego has no counterpart for,
 * or an empty list. An equation that does not parse has none: it is written as
 * it is, and Ecolego says what it thinks of it.
 */
export function unsupportedCalls(text) {
	const src = String(text ?? '');
	let toks;
	try { toks = tokenize(src); } catch { return []; }
	const out = [];
	for (let i = 0; i < toks.length; i++) {
		const t = toks[i];
		if (t.type === 'ident' && toks[i + 1]?.type === 'lparen' && NO_ECOLEGO_FUNCTION.has(t.value) && !out.includes(t.value)) {
			out.push(t.value);
		}
	}
	return out;
}

/**
 * An equation in Ecolego's spelling.
 *
 * @param {*} text  the equation as the model holds it
 * @param {{call?: (name: string) => ({first: string, span: string}|null)}} [options]
 *   `call` says of a call the model defines whether it reads a table that
 *   repeats over its range, and that range, as Java writes the two numbers
 * @returns {{text: string, units: boolean, writtenOut: string[], respelled: boolean}}
 *   `units` when numbers lost the units written against them, `writtenOut`
 *   the functions written out as arithmetic, and `respelled` when the text
 *   changed at all
 */
export function ecolegoEquation(text, options = {}) {
	const src = String(text ?? '');
	const same = { text: src, units: false, writtenOut: [], respelled: false };
	if (src.trim() === '') return same;
	let toks;
	let ast;
	let seen;
	try {
		toks = tokenize(src);
		seen = scan(toks, options.call);
		if (!seen.look) return same;
		// Every call parses: one the function table does not know is the
		// model's own -- a function block, or a lookup table read at a value.
		ast = parse(src, { calls: () => true });
	} catch {
		return same;
	}
	// The numbers as they were written, in the order the tree holds them.
	const spelled = toks.filter((t) => t.type === 'number').map((t) => t.text);
	let k = 0;
	const stack = [ast];
	const order = [];
	while (stack.length) {
		const node = stack.pop();
		order.push(node);
		const kids = node.type === 'binary' ? [node.left, node.right]
			: node.type === 'unary' ? [node.operand]
				: node.type === 'call' ? node.args
					: node.type === 'cond' ? [node.test, node.then, node.otherwise] : [];
		for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
	}
	for (const node of order) if (node.type === 'num') node.text = spelled[k++] ?? String(node.value);

	// `needed` is set wherever the printer has to change what the equation
	// says in Ecolego's terms; an equation it only reprints goes as it was typed.
	const notes = { units: false, writtenOut: [], needed: seen.must, wraps: options.call ?? null };
	const out = value(ast, notes).text;
	if (!notes.needed) return same;
	return { text: out, units: notes.units, writtenOut: notes.writtenOut, respelled: out !== src };
}

// --- the printer -------------------------------------------------------------------

/** A number's worth of equation: `{ text, prec }`. */
function value(node, notes) {
	switch (node.type) {
		case 'num':
			if (node.unit != null) notes.units = notes.needed = true;
			return { text: node.text, prec: PRIMARY };
		case 'ref':
			return { text: node.name + (node.indices ?? []).map((i) => `[${i ?? ''}]`).join(''), prec: PRIMARY };
		case 'unary': {
			const inner = value(node.operand, notes);
			return { text: `-${inner.prec >= POWER ? inner.text : `(${inner.text})`}`, prec: UNARY };
		}
		case 'cond':
			notes.needed = true;
			return { text: `if(${test(node.test, notes, true)}, ${value(node.then, notes).text}, ${value(node.otherwise, notes).text})`, prec: PRIMARY };
		case 'binary':
			if (isTest(node)) {
				notes.needed = true;
				return { text: `if(${test(node, notes, true)}, 1, 0)`, prec: PRIMARY };
			}
			if (node.op === '^') {
				const base = value(node.left, notes);
				const power = value(node.right, notes);
				const b = base.prec === PRIMARY || base.prec === POWER ? base.text : `(${base.text})`;
				const p = power.prec === PRIMARY ? power.text : `(${power.text})`;
				return { text: `${b}^${p}`, prec: POWER };
			}
			return arithmetic(node, notes);
		case 'call':
			return callValue(node, notes);
		default:
			return { text: '0', prec: PRIMARY };
	}
}

function arithmetic(node, notes) {
	const p = PRECEDENCE[node.op] ?? 5;
	const left = value(node.left, notes);
	const right = value(node.right, notes);
	const l = left.prec === UNARY || left.prec < p ? `(${left.text})` : left.text;
	const r = right.prec === UNARY || right.prec <= p ? `(${right.text})` : right.text;
	return { text: `${l} ${node.op} ${r}`, prec: p };
}

function callValue(node, notes) {
	const { name, args } = node;
	const said = (fn) => {
		notes.needed = true;
		if (!notes.writtenOut.includes(fn)) notes.writtenOut.push(fn);
	};
	// A logical function is always written as the test it is: Ecolego's own
	// fail to build with a test for an argument, and take exactly two.
	if (LOGICAL_CALLS.has(name)) notes.needed = true;
	switch (name) {
		case 'if': {
			const condition = test(args[0], notes, true);
			const rest = args.slice(1).map((a) => value(a, notes).text);
			return { text: `if(${[condition, ...rest].join(', ')})`, prec: PRIMARY };
		}
		case 'and':
		case 'or':
			return { text: `if(${test(node, notes, true)}, 1, 0)`, prec: PRIMARY };
		case 'not':
			return { text: `if(${test(args[0], notes, true)}, 0, 1)`, prec: PRIMARY };
		case 'nand':
		case 'nor':
			said(name);
			return { text: `if(${joined(args, name === 'nand' ? '&&' : '||', notes)}, 0, 1)`, prec: PRIMARY };
		case 'xor':
			said(name);
			// Ecolego's own mod: of a count, the exact remainder is the only one.
			return { text: `mod(${args.map((a) => `if(${test(a, notes, true)}, 1, 0)`).join(' + ')}, 2)`, prec: PRIMARY };
		case 'mod':
		case 'rem': {
			// The table wrap's `rem` is Ecolego's own: there Java's `%` is
			// what ../domain/lookup.js does, JavaScript's being the same.
			if (node.native) break;
			said(name);
			const [a, b] = args;
			const body = binary('-', a, binary('*', b, call(name === 'mod' ? 'floor' : 'fix', [binary('/', a, b)])));
			// rem(a, 0) is NaN here and so is the arithmetic; mod(a, 0) is a.
			const nonZero = b.type === 'num' ? b.value !== 0
				: b.type === 'unary' && b.operand.type === 'num' && b.operand.value !== 0;
			return value(name === 'rem' || nonZero ? body : call('if', [binary('==', b, num('0')), a, body]), notes);
		}
		case 'mole2bq':
			said(name);
			// (ln 2 * n * N_A) / (T * year), in the order ../parser/functions.js multiplies.
			return value(binary('/', binary('*', binary('*', num(LN2_TEXT), args[0]), num(AVOGADRO_TEXT)),
				binary('*', args[1], num(SECONDS_PER_YEAR_TEXT))), notes);
		case 'bq2mole':
			said(name);
			return value(binary('/', binary('*', binary('*', args[0], args[1]), num(SECONDS_PER_YEAR_TEXT)),
				binary('*', num(LN2_TEXT), num(AVOGADRO_TEXT))), notes);
		case 'ulp':
			said(name);
			return value(binary('*', call('abs', [args[0]]), call('eps', [])), notes);
		case 'rampDown':
			said(name);
			return value(rampDown(args), notes);
		case 'rampUp':
			said(name);
			return value(binary('-', num('1'), rampDown(args)), notes);
		case 'smoothDown':
			said(name);
			return value(smoothDown(args), notes);
		case 'smoothUp':
			said(name);
			return value(binary('-', num('1'), smoothDown(args)), notes);
		case 'asinh':
		case 'acosh':
		case 'atanh':
			said(name);
			return value(HYPERBOLIC[name](args[0]), notes);
		default:
			if (AGGREGATES.has(name) && args.length === 1) {
				notes.needed = true;
				return value(args[0], notes);
			}
			if (args.length === 1 && !node.wrapped) {
				const range = notes.wraps?.(name);
				if (range) {
					notes.needed = true;
					return value({ ...call(name, [wrapped(args[0], range)]), wrapped: true }, notes);
				}
			}
	}
	return { text: `${name}(${args.map((a) => value(a, notes).text).join(', ')})`, prec: PRIMARY };
}

/**
 * A value put on a table's own range: a remainder that keeps its sign, moved
 * back onto the interval -- `wrap` in ../domain/lookup.js, to the operation.
 */
function wrapped(x, { first, span }) {
	// A number written with its sign is a sign and a number, so the printer
	// brackets it where it follows an operator.
	const at = first.startsWith('-') ? { type: 'unary', op: '-', operand: num(first.slice(1)) } : num(first);
	const a = { ...call('rem', [binary('-', x, at), num(span)]), native: true };
	return call('if', [binary('>=', a, num('0')), binary('+', a, at), binary('+', binary('+', a, num(span)), at)]);
}

/** 1 up to the smaller end, 0 from the larger, a straight line between (`rampDown`). */
function rampDown([x, start, end]) {
	const lo = call('min', [start, end]);
	const hi = call('max', [start, end]);
	return call('if', [binary('>', x, lo),
		call('if', [binary('>=', x, hi), num('0'), binary('/', binary('-', hi, x), binary('-', hi, lo))]),
		num('1')]);
}

/** 1 / (1 + (x/X)^(2s)) for x > 0 and X > 0, and 0 where that power is not finite (`smoothDown`). */
function smoothDown([x, X, s]) {
	const r = call('power', [binary('/', x, X), binary('*', num('2'), s)]);
	return call('if', [binary('>', x, num('0')),
		call('if', [binary('>', X, num('0')),
			call('if', [binary('<=', r, num(MAX_DOUBLE_TEXT)), binary('/', num('1'), binary('+', num('1'), r)), num('0')]),
			num('0')]),
		num('1')]);
}

/**
 * The inverse hyperbolic functions as logarithms. Near where each is zero the
 * logarithm is of something close to 1 and loses digits, so a short series
 * stands in -- four terms, to 1e-2 from zero or 1e-5 above 1, after which the
 * next term is past the last digit -- and past 1e150 it is `ln 2 + ln |x|`,
 * where the square would overflow. `acosh` squares nothing: `(x - 1)(x + 1)`
 * has an exact `x - 1`, and a root of a negative number is its NaN below 1.
 */
const pow = (x, n) => (n === '1' ? x : binary('^', x, num(n)));
const series = (x, terms) => terms.reduce((sum, [op, k, n, d]) => binary(op, sum,
	k === '1' ? binary('/', pow(x, n), num(d)) : binary('/', binary('*', num(k), pow(x, n)), num(d))), num('1'));
const HYPERBOLIC = {
	asinh: (x) => call('if', [binary('<', call('abs', [x]), num('0.01')),
		binary('*', x, series(x, [['-', '1', '2', '6'], ['+', '3', '4', '40'], ['-', '15', '6', '336']])),
		call('if', [binary('>', call('abs', [x]), num('1e150')),
			binary('*', call('sign', [x]), binary('+', call('log', [call('abs', [x])]), num(LN2_TEXT))),
			binary('*', call('sign', [x]), call('log', [binary('+', call('abs', [x]), call('sqrt', [binary('+', pow(x, '2'), num('1'))]))]))])]),
	acosh: (x) => {
		const e = binary('-', x, num('1'));
		return call('if', [binary('<', e, num('1e-5')),
			binary('*', call('sqrt', [binary('*', num('2'), e)]), series(e, [['-', '1', '1', '12'], ['+', '3', '2', '160'], ['-', '5', '3', '896']])),
			call('if', [binary('>', x, num('1e150')),
				binary('+', call('log', [x]), num(LN2_TEXT)),
				call('log', [binary('+', x, binary('*', call('sqrt', [e]), call('sqrt', [binary('+', x, num('1'))])))])])]);
	},
	atanh: (x) => call('if', [binary('<', call('abs', [x]), num('0.01')),
		binary('*', x, series(x, [['+', '1', '2', '3'], ['+', '1', '4', '5'], ['+', '1', '6', '7']])),
		binary('*', num('0.5'), call('log', [binary('/', binary('+', num('1'), x), binary('-', num('1'), x))]))]),
};

/**
 * A test, as the condition of an `if()`: comparisons of numbers, joined by
 * `&&` and `||`. `direct` is the condition itself, where a plain name or
 * number may stand as it is; anywhere else a number is `x ~= 0`.
 */
function test(node, notes, direct) {
	if (node.type === 'binary' && COMPARISONS.has(node.op)) {
		return `${operand(value(node.left, notes))} ${node.op} ${operand(value(node.right, notes))}`;
	}
	if (node.type === 'binary' && (node.op === '&&' || node.op === '||')) {
		return joined([node.left, node.right], node.op, notes);
	}
	if (node.type === 'call' && (node.name === 'and' || node.name === 'or')) {
		return joined(node.args, node.name === 'and' ? '&&' : '||', notes);
	}
	// A number standing alone as the condition is Ecolego's own `0.0 != x`,
	// and needs nothing -- unless it is itself a conditional, whose Java
	// Ecolego writes without the brackets the comparison would need.
	// `not` and the written-out tests are conditionals too, once written.
	const conditional = node.type === 'cond' || (node.type === 'call' && (node.name === 'if' || LOGICAL_CALLS.has(node.name)));
	if (direct && !conditional) return value(node, notes).text;
	notes.needed = true;
	return `${operand(value(node, notes))} ~= 0`;
}

/** Tests joined by one operator, a test joined by the other bracketed. */
function joined(parts, op, notes) {
	return parts.map((p) => {
		const text = test(p, notes, false);
		const other = (p.type === 'binary' && (p.op === '&&' || p.op === '||') && p.op !== op)
			|| (p.type === 'call' && (p.name === 'and' || p.name === 'or') && (p.name === 'and' ? '&&' : '||') !== op);
		return other ? `(${text})` : text;
	}).join(` ${op} `);
}

/** A number in a comparison, bracketed where it is a sign. */
function operand(v) {
	return v.prec === UNARY ? `(${v.text})` : v.text;
}

// --- what an equation reads ------------------------------------------------------

/**
 * The names an equation reads -- its references, and the calls that are the
 * model's own rather than functions -- and whether it reads the time. Nothing
 * for an equation that does not parse.
 */
export function readsOf(text) {
	const out = { names: [], time: false };
	let ast;
	try { ast = parse(String(text ?? ''), { calls: () => true }); } catch { return out; }
	const stack = [ast];
	while (stack.length) {
		const node = stack.pop();
		if (node.type === 'ref') out.names.push(node.name);
		else if (node.type === 'call') {
			if (node.name === 'time') out.time = true;
			else if (!lookupFunction(node.name)) out.names.push(node.name);
			stack.push(...node.args);
		} else if (node.type === 'unary') stack.push(node.operand);
		else if (node.type === 'binary') stack.push(node.left, node.right);
		else if (node.type === 'cond') stack.push(node.test, node.then, node.otherwise);
	}
	return out;
}
