/**
 * Compiles expression ASTs to JavaScript source.
 *
 * A model's equations are generated rather than interpreted: this emits a JS
 * expression string per equation, and the assembled derivative function goes
 * to `new Function`, which the engine then JITs. The desktop tools do the
 * same thing by writing and compiling a class per model. Either way the payoff
 * is the same -- no interpretive overhead in the inner ODE loop.
 */

import { FUNCTIONS, FUNCTION_ALIASES } from './functions.js';

/**
 * `^` becomes Math.pow, which is also how an equation in a model file is
 * rewritten before it is compiled. Comparisons yield 1/0 rather than booleans
 * so that they compose arithmetically, which is what `if` in this language
 * expects of them.
 */
const BINARY_TEMPLATES = {
	'+': (a, b) => `(${a} + ${b})`,
	'-': (a, b) => `(${a} - ${b})`,
	'*': (a, b) => `(${a} * ${b})`,
	'/': (a, b) => `(${a} / ${b})`,
	'^': (a, b) => `Math.pow(${a}, ${b})`,
	'<': (a, b) => `((${a} < ${b}) ? 1 : 0)`,
	'<=': (a, b) => `((${a} <= ${b}) ? 1 : 0)`,
	'>': (a, b) => `((${a} > ${b}) ? 1 : 0)`,
	'>=': (a, b) => `((${a} >= ${b}) ? 1 : 0)`,
	'==': (a, b) => `((${a} === ${b}) ? 1 : 0)`,
	'~=': (a, b) => `((${a} !== ${b}) ? 1 : 0)`,
	'&&': (a, b) => `((${a} !== 0 && ${b} !== 0) ? 1 : 0)`,
	'||': (a, b) => `((${a} !== 0 || ${b} !== 0) ? 1 : 0)`,
};

/**
 * Functions that inline to plain JS operators or Math calls, avoiding a
 * property lookup and call in the hot loop. Everything else goes through the
 * FUNCTIONS table via the `F` binding.
 */
const INLINE = {
	abs: (a) => `Math.abs(${a})`,
	sqrt: (a) => `Math.sqrt(${a})`,
	exp: (a) => `Math.exp(${a})`,
	log: (a) => `Math.log(${a})`,
	log10: (a) => `Math.log10(${a})`,
	log2: (a) => `Math.log2(${a})`,
	sin: (a) => `Math.sin(${a})`,
	cos: (a) => `Math.cos(${a})`,
	tan: (a) => `Math.tan(${a})`,
	sinh: (a) => `Math.sinh(${a})`,
	cosh: (a) => `Math.cosh(${a})`,
	tanh: (a) => `Math.tanh(${a})`,
	asin: (a) => `Math.asin(${a})`,
	acos: (a) => `Math.acos(${a})`,
	atan: (a) => `Math.atan(${a})`,
	ceil: (a) => `Math.ceil(${a})`,
	floor: (a) => `Math.floor(${a})`,
	round: (a) => `Math.round(${a})`,
	sign: (a) => `Math.sign(${a})`,
	power: (a, b) => `Math.pow(${a}, ${b})`,
	atan2: (a, b) => `Math.atan2(${a}, ${b})`,
	hypot: (a, b) => `Math.hypot(${a}, ${b})`,
	pi: () => `Math.PI`,
	not: (a) => `((${a} === 0) ? 1 : 0)`,
	if: (t, a, b) => `((${t} !== 0) ? (${a}) : (${b ?? '0'}))`,
};

/** Variadic functions that fold into a chain of binary Math calls. */
const FOLDABLE = {
	min: (args) => `Math.min(${args.join(', ')})`,
	max: (args) => `Math.max(${args.join(', ')})`,
	sum: (args) => `(${args.join(' + ')})`,
	prod: (args) => `(${args.join(' * ')})`,
	mean: (args) => `((${args.join(' + ')}) / ${args.length})`,
};

/**
 * Emits a JS expression for `ast`.
 *
 * @param {object} ast          node from parser.parse()
 * @param {(name: string, indices: Array<string|null>) => string} resolveRef
 *        maps a block reference to a JS expression, e.g. 'y[4]' or 'P[2]';
 *        `indices` is one entry per bracket the reference was written with
 * @param {(name: string, argCodes: string[]) => ({value: string, slope?: string}|null)}
 *        [resolveCall] maps a call the model itself defines -- a lookup table
 *        read at an argument, `Table(x)` -- to a JS expression, and optionally
 *        to the derivative of that expression with respect to the argument.
 *        Returning null leaves the name to the built-in function table.
 */
export function emit(ast, resolveRef, resolveCall) {
	try {
		return emitNode(ast, resolveRef, resolveCall);
	} catch (e) {
		throw tooBigToEmit(e);
	}
}

/**
 * A RangeError from the emitters, said in terms of the equation.
 *
 * Both emitters descend one frame per AST node, and `parseBinary` builds its
 * tree iteratively -- so `a+a+...` four thousand terms long parses happily and
 * then exhausts the stack here, arriving as a bare `RangeError: Maximum call
 * stack size exceeded` with no block named and nothing to act on. parser.js
 * does the same conversion for the nesting it can see; this is the other half,
 * for the width it cannot. Anything else is re-thrown untouched.
 */
function tooBigToEmit(e) {
	if (!(e instanceof RangeError)) return e;
	return new Error(
		'This equation is too long or too deeply nested to compile. Split it '
		+ 'into expression blocks.',
	);
}

function emitNode(ast, resolveRef, resolveCall) {
	switch (ast.type) {
		case 'num': {
			// Preserve full double precision and keep negatives parenthesised.
			const v = ast.value;
			if (!Number.isFinite(v)) {
				return v > 0 ? 'Infinity' : Number.isNaN(v) ? 'NaN' : '(-Infinity)';
			}
			const s = String(v);
			return v < 0 ? `(${s})` : s;
		}

		case 'ref':
			// The node goes with the name: a reference the inliner moved here
			// from somewhere else carries the scope it was written in, and
			// nothing but the node itself can say so. Every resolver that
			// does not care takes two arguments and ignores the third.
			return resolveRef(ast.name, ast.indices, ast);

		case 'unary':
			return `(-${emitNode(ast.operand, resolveRef, resolveCall)})`;

		case 'binary': {
			const a = emitNode(ast.left, resolveRef, resolveCall);
			const b = emitNode(ast.right, resolveRef, resolveCall);
			const tmpl = BINARY_TEMPLATES[ast.op];
			if (!tmpl) throw new Error(`Cannot emit operator '${ast.op}'`);
			return tmpl(a, b);
		}

		case 'cond':
			return `((${emitNode(ast.test, resolveRef, resolveCall)} !== 0) ? (${
				emitNode(ast.then, resolveRef, resolveCall)}) : (${
				emitNode(ast.otherwise, resolveRef, resolveCall)}))`;

		case 'call': {
			const name = FUNCTION_ALIASES[ast.name] ?? ast.name;
			const args = ast.args.map((a) => emitNode(a, resolveRef, resolveCall));

			// A call the model defines wins over the built-in table. Block names
			// may not collide with a function name (see project.js RESERVED), so
			// this can only ever match something the model actually declares.
			const own = resolveCall ? resolveCall(ast.name, args) : null;
			if (own) return own.value;

			if (INLINE[name] && args.length <= INLINE[name].length) {
				return INLINE[name](...args);
			}
			if (FOLDABLE[name]) {
				return FOLDABLE[name](args);
			}

			const spec = FUNCTIONS[name];
			if (!spec) throw new Error(`Unknown function '${name}'`);
			// Time functions read the clock, passed in as `ctx`.
			if (spec.needsContext) {
				return `F.${name}.fn(ctx${args.length ? ', ' + args.join(', ') : ''})`;
			}
			return `F.${name}.fn(${args.join(', ')})`;
		}

		default:
			throw new Error(`Cannot emit node type '${ast.type}'`);
	}
}

/**
 * Builds a callable from a body of JS statements.
 *
 * `F` (the function table) and `ctx` (the simulation clock) are always in
 * scope, plus whatever extra parameter names the caller declares.
 */
export function buildFunction(paramNames, body, name = 'compiled') {
	const src = `"use strict";\n${body}`;
	try {
		let parts = splitBody(body);
		let fn = null;
		if (parts) {
			// A part that does not compile is a body the scan misjudged, and
			// the whole of it is still good: it runs whole, as it always did.
			try { fn = linkParts(paramNames, parts); } catch { parts = null; }
		}
		// eslint-disable-next-line no-new-func
		fn ??= new Function('F', 'ctx', ...paramNames, src);
		Object.defineProperty(fn, 'name', { value: name });
		// The whole of it, as one piece: the parts are slices of it and
		// add nothing a reader needs.
		fn.source = src;
		fn.parts = parts ? parts.length : 1;
		return fn;
	} catch (e) {
		// The head of it, not all of it. A generated derivative function runs
		// to the 300,000-line ceiling ../sim/jacobian.js sets, and the whole
		// thing used to go into the message: tens of megabytes structured-
		// cloned out of the worker and then laid out in the error panel, to
		// say that line four is malformed. The first lines identify which
		// generator wrote it, which is what the reader needs; the count says
		// how much is not shown.
		const lines = src.split('\n');
		const head = lines.slice(0, ERROR_SOURCE_LINES).join('\n');
		const rest = lines.length > ERROR_SOURCE_LINES
			? `\n... ${lines.length - ERROR_SOURCE_LINES} more lines`
			: '';
		throw new Error(
			`Generated code failed to compile (${e.message}).\n`
			+ `--- source (${lines.length} lines) ---\n${head}${rest}`,
		);
	}
}

/** How much of a failed generated function goes into its error message. */
const ERROR_SOURCE_LINES = 40;

/*
 * A generated function is run in parts when it is long.
 *
 * V8 will not hand a function of more than 60 KB of bytecode to its optimising
 * compiler. A longer one stays in the baseline tier for the whole run, however
 * hot it is, and raising the limit is no way out: at these sizes the optimising
 * compiler crashes. The functions here get long. The landscape model in the
 * SR-PSU biosphere folder (LandscapeAllChain, 9,462 states) has a derivative
 * of 3 MB of source and a Jacobian tangent of 7 MB, fifty to a hundred times
 * the limit.
 *
 * So the body is cut into parts of about PART_CHARS characters, each compiled
 * as a function of its own with the same arguments, and called in order by a
 * function that returns what the last one returns. A part is a slice of the
 * body and nothing else. Everything the generated code carries from one
 * statement to a later one is in the arrays it was handed (X, T, out, dX...),
 * which every part sees. A cut is only made where that is the whole story:
 *
 *   - between top-level statements, never inside a loop, a block or a bracket;
 *   - where no local declared at the top level is read again later. A
 *     transfer's `const f12` and a conditional's `let v3` live for a few lines,
 *     and the cut waits for them;
 *   - the tape line (tapePrelude) is the exception: it is idempotent and read
 *     throughout, so every part begins with it.
 *
 * A body this scan does not fully understand (a string, a template, a block
 * comment, a nested function, a `return` anywhere but at the end, or a
 * declaration it cannot parse) is compiled whole, as it always was, and so is
 * one whose parts do not compile. That is safe: the parts only exist to make
 * it faster. `fn.parts` says how many there are.
 */
const PART_CHARS = 24000;

const TOP_DECL = /^\s*(const|let|var)\s+(.*)$/;
const IDENT = /[A-Za-z_$][\w$]*/g;

/**
 * The parts of a body, or null to compile it whole.
 * @param {string} body
 * @returns {string[] | null}
 */
function splitBody(body) {
	if (body.length <= PART_CHARS * 1.25) return null;
	const prelude = tapePrelude('').trim();
	const lines = body.split('\n');
	const n = lines.length;
	const depthAfter = new Int32Array(n);
	const declared = new Map();         // top-level local -> line it is declared on
	const lastUse = new Map();          // top-level local -> last line that names it
	const replicated = new Uint8Array(n);
	let depth = 0;
	let returnLine = -1;
	for (let i = 0; i < n; i++) {
		const line = lines[i];
		// A comment is whatever follows `//`. That holds only while the code
		// before it has no string in it, which the next test makes sure of.
		const cut = line.indexOf('//');
		const code = cut < 0 ? line : line.slice(0, cut);
		if (/[`'"]|\/\*|=>|\bfunction\b/.test(code)) return null;
		if (code.trim() === prelude) {
			if (depth !== 0) return null;
			replicated[i] = 1;
			depthAfter[i] = 0;
			continue;
		}
		const atTop = depth === 0;
		if (atTop) {
			const m = TOP_DECL.exec(code);
			if (m) {
				// `let v3;`, `let v3, v4;` or `const f12 = ...;`: nothing else.
				let names;
				if (m[1] === 'let' && /^[\w$\s,]+;\s*$/.test(m[2])) names = m[2].replace(/;\s*$/, '').split(',').map((s) => s.trim());
				else if (/^[A-Za-z_$][\w$]*\s*=/.test(m[2])) names = [m[2].match(/^[A-Za-z_$][\w$]*/)[0]];
				else return null;
				for (const nm of names) declared.set(nm, i);
			}
		}
		if (/\breturn\b/.test(code)) {
			if (!atTop || returnLine >= 0) return null;
			returnLine = i;
		}
		for (let k = 0; k < code.length; k++) {
			const c = code.charCodeAt(k);
			if (c === 40 || c === 91 || c === 123) depth++;          // ( [ {
			else if (c === 41 || c === 93 || c === 125) depth--;     // ) ] }
		}
		if (depth < 0) return null;
		depthAfter[i] = depth;
		if (declared.size) {
			IDENT.lastIndex = 0;
			let t;
			while ((t = IDENT.exec(code)) !== null) {
				if (declared.has(t[0])) lastUse.set(t[0], i);
			}
		}
	}
	if (depth !== 0) return null;
	// The return must close the body: nothing but blank lines and comments after it.
	if (returnLine >= 0) {
		for (let i = returnLine + 1; i < n; i++) if (lines[i].replace(/\/\/.*$/, '').trim()) return null;
	}

	// Where a cut may follow a line: at the top level, and past the last use
	// of every top-level local declared so far.
	const head = lines.filter((_, i) => replicated[i]);
	const parts = [];
	let chunk = [];
	let size = 0;
	let liveTo = -1;
	const openers = new Map();
	for (const [nm, at] of declared) {
		if (!openers.has(at)) openers.set(at, []);
		openers.get(at).push(nm);
	}
	for (let i = 0; i < n; i++) {
		if (replicated[i]) continue;
		chunk.push(lines[i]);
		size += lines[i].length + 1;
		for (const nm of openers.get(i) ?? []) liveTo = Math.max(liveTo, lastUse.get(nm) ?? i);
		if (size > PART_CHARS && depthAfter[i] === 0 && liveTo <= i && (returnLine < 0 || i < returnLine)) {
			parts.push(chunk);
			chunk = [];
			size = 0;
		}
	}
	if (chunk.length) parts.push(chunk);
	if (parts.length < 2) return null;
	return parts.map((p) => `"use strict";\n${[...head, ...p].join('\n')}`);
}

/** One function of F, ctx and the parameters that calls the parts in order. */
function linkParts(paramNames, parts) {
	const params = ['F', 'ctx', ...paramNames];
	// eslint-disable-next-line no-new-func
	const fns = parts.map((src) => new Function(...params, src));
	const args = params.join(', ');
	const calls = fns.map((_, k) => (k === fns.length - 1
		? `\treturn parts[${k}](${args});`
		: `\tparts[${k}](${args});`));
	// eslint-disable-next-line no-new-func
	return new Function('parts', `"use strict";\nreturn function (${args}) {\n${calls.join('\n')}\n};`)(fns);
}

// --- forward-mode derivatives -----------------------------------------------

/**
 * Raised when an expression has no derivative this generator is willing to
 * invent. The caller falls back to a finite-difference Jacobian rather than
 * shipping a wrong one.
 */
export class NoDerivative extends Error {
	constructor(what) {
		super(`No derivative rule for ${what}`);
		this.name = 'NoDerivative';
		this.what = what;
	}
}

/**
 * A statement list with single-assignment temporaries.
 *
 * The tangent rules need a sub-expression's *value* as well as its derivative
 * -- d(a/b) uses a/b itself, d(sqrt(a)) uses sqrt(a) -- and several of them use
 * it twice. Emitting those inline duplicates the sub-expression at every level,
 * which for nested division or powers grows exponentially with depth. Naming
 * each node instead keeps the generated code linear in the number of AST nodes,
 * and lets the value be reused rather than recomputed.
 */
export function makeTape(indent = '\t') {
	return { lines: [], indent, n: 0, cse: new Map(), count: 0 };
}

/**
 * The line a tape's owner must put at the top of the function it builds.
 *
 * Hoisted temporaries used to be `const` locals, and V8 gives every local in a
 * function a register in the interpreter frame -- so a large enough generated
 * function could not be *called*: it compiled, and the RangeError arrived on
 * the first call. Where "large enough" is depends on how much stack there is,
 * and a **worker has far less than the page**: measured in this browser, a
 * function of 60,000 locals is callable in a worker and one of 62,000 is not,
 * while the page manages 100,000 and Node a little more. Runs happen in the
 * worker, so the worker's number was the ceiling, and it was low enough to
 * deny a real 8,427-state model its analytic Jacobian.
 *
 * Slots in an array instead. The frame then holds a handful of locals whatever
 * the model's size, and the limit becomes compile time and the cost of a call
 * -- both of which are mild: 300,000 slots compile in 176 ms inside a worker
 * and run in 10 ms, where 68,000 locals could not be called at all.
 *
 * The array lives on the runtime context because every generated function
 * already takes one, so nothing else in the pipeline has to learn a new
 * argument. It is allocated once and reused; the slots are written before they
 * are read within a single call, and no two generated functions are ever on
 * the stack together.
 */
export const tapePrelude = (indent = '\t') => `${indent}const T = ctx.__tape || (ctx.__tape = []);`;

// Something already atomic -- a literal, `y[3]`, `X[b + n0 * 4]` -- costs
// nothing to repeat, so it is never hoisted.
const ATOMIC = /^-?(?:\d+(?:\.\d*)?(?:e[+-]?\d+)?|[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\[[^[\]]*\])?)$/i;

function hoist(tape, code) {
	if (code == null) return null;
	if (ATOMIC.test(code)) return code;
	const seen = tape.cse.get(code);
	if (seen) return seen;
	// A slot, not a local: see `tapePrelude`. `T[12]` is atomic by the test
	// above, so a value already in a slot is never hoisted into another.
	const name = `T[${tape.n++}]`;
	tape.lines.push(`${tape.indent}${name} = ${code};`);
	tape.count++;
	tape.cse.set(code, name);
	return name;
}

/** A tape for a nested block: its temporaries do not escape the block. */
function branchTape(tape) {
	const sub = makeTape(tape.indent + '\t');
	sub.n = tape.n;
	sub.cse = new Map(tape.cse);
	return sub;
}

function closeBranch(tape, sub) {
	tape.n = sub.n;
	tape.count += sub.count;
}

/**
 * Tangent rules, one per function, applied only when at least one argument has
 * a live derivative. `A` are the argument values, `dA` their tangents (null
 * where structurally zero) and `V` the call's own value.
 *
 * Everything here is the derivative of what `emit` actually generates, which is
 * not always the derivative of the mathematical function: `ulp` is implemented
 * as |a|*eps, and the staircases (floor, round, sign, ...) are piecewise
 * constant, so zero is their exact derivative away from the jumps. A finite
 * difference across such a jump reports a slope of 1/delta -- an entry of order
 * 1e8 that is pure artefact -- so the analytic rule is not merely cheaper here,
 * it is better behaved.
 */
/**
 * A rule's tangent, but zero when none of the arguments carry one.
 *
 * Most of these rules divide by something the argument can make zero --
 * `sqrt(0)`, `log(0)`, `asin(1)`, `hypot(0, 0)`. When the seed vector does not
 * reach that argument at all its tangent is the literal 0, and the rule then
 * computes `0 / 0`: NaN written into a column whose true entry is zero, and
 * from there into every row that reads it. The chain rule's answer for a
 * column the expression does not depend on is 0 whatever the function is
 * doing at that point, so it is said directly rather than computed.
 *
 * Cheap at runtime -- a comparison against zero on a temporary -- and free
 * when every tangent is the constant 0, which the generator can see.
 */
function guardZeroSeed(dA, tangent) {
	if (tangent == null) return tangent;
	const live = dA.filter((d) => d != null && String(d) !== '0');
	if (!live.length) return '0';
	return `(${live.map((d) => `${d} === 0`).join(' && ')} ? 0 : ${tangent})`;
}

const TANGENT_RULES = {
	abs: ({ A, dA }) => `(Math.sign(${A[0]}) * ${dA[0]})`,
	sqrt: ({ V, dA }) => `(${dA[0]} / (2 * ${V}))`,
	exp: ({ V, dA }) => `(${V} * ${dA[0]})`,
	log: ({ A, dA }) => `(${dA[0]} / ${A[0]})`,
	log10: ({ A, dA }) => `(${dA[0]} / (${A[0]} * Math.LN10))`,
	log2: ({ A, dA }) => `(${dA[0]} / (${A[0]} * Math.LN2))`,
	hypot: ({ A, dA, V }) => `((${term(A[0], dA[0])}${plus(term(A[1], dA[1]))}) / ${V})`,
	sin: ({ A, dA }) => `(Math.cos(${A[0]}) * ${dA[0]})`,
	cos: ({ A, dA }) => `((-Math.sin(${A[0]})) * ${dA[0]})`,
	tan: ({ V, dA }) => `((1 + ${V} * ${V}) * ${dA[0]})`,
	asin: ({ A, dA }) => `(${dA[0]} / Math.sqrt(1 - ${A[0]} * ${A[0]}))`,
	acos: ({ A, dA }) => `((-${dA[0]}) / Math.sqrt(1 - ${A[0]} * ${A[0]}))`,
	atan: ({ A, dA }) => `(${dA[0]} / (1 + ${A[0]} * ${A[0]}))`,
	sinh: ({ A, dA }) => `(Math.cosh(${A[0]}) * ${dA[0]})`,
	cosh: ({ A, dA }) => `(Math.sinh(${A[0]}) * ${dA[0]})`,
	tanh: ({ V, dA }) => `((1 - ${V} * ${V}) * ${dA[0]})`,
	asinh: ({ A, dA }) => `(${dA[0]} / Math.sqrt(${A[0]} * ${A[0]} + 1))`,
	acosh: ({ A, dA }) => `(${dA[0]} / Math.sqrt(${A[0]} * ${A[0]} - 1))`,
	atanh: ({ A, dA }) => `(${dA[0]} / (1 - ${A[0]} * ${A[0]}))`,
	// 2/sqrt(pi), folded so the inner loop does no work.
	erf: ({ A, dA }) => `(1.1283791670955126 * Math.exp(-${A[0]} * ${A[0]}) * ${dA[0]})`,
	erfc: ({ A, dA }) => `(-1.1283791670955126 * Math.exp(-${A[0]} * ${A[0]}) * ${dA[0]})`,
	atan2: ({ A, dA }) => `((${term(A[1], dA[0])}${minus(term(A[0], dA[1]))}) `
		+ `/ (${A[0]} * ${A[0]} + ${A[1]} * ${A[1]}))`,
	// mod(a,b) = a - b*floor(a/b); floor is locally constant, so d/da = 1 and
	// d/db = -floor(a/b). b === 0 mirrors the primal, which returns a.
	mod: ({ A, dA }) => (dA[1] == null
		? dA[0]
		: `((${A[1]} === 0) ? ${dA[0] ?? 0} : (${dA[0] ?? 0} - Math.floor(${A[0]} / ${A[1]}) * ${dA[1]}))`),
	rem: ({ A, dA }) => (dA[1] == null
		? dA[0]
		: `((${A[1]} === 0) ? NaN : (${dA[0] ?? 0} - F.fix.fn(${A[0]} / ${A[1]}) * ${dA[1]}))`),
	ulp: ({ A, dA }) => `(Math.sign(${A[0]}) * 2.220446049250313e-16 * ${dA[0]})`,
	// A ramp: zero outside, the constant slope of the line inside, and the two
	// corners are a measure-zero set the solver steps over -- which is exactly
	// why the switch times matter (see ../domain/switchtimes.js). Written as a
	// comparison rather than through `rampDown` again so the inner loop does
	// one subtraction and no call.
	rampDown: ({ A, dA }) => (dA[0] == null || dA[1] != null || dA[2] != null
		? null
		: `((${A[0]} > Math.min(${A[1]}, ${A[2]}) && ${A[0]} < Math.max(${A[1]}, ${A[2]})) `
			+ `? ((-${dA[0]}) / (Math.max(${A[1]}, ${A[2]}) - Math.min(${A[1]}, ${A[2]}))) : 0)`),
	rampUp: ({ A, dA }) => (dA[0] == null || dA[1] != null || dA[2] != null
		? null
		: `((${A[0]} > Math.min(${A[1]}, ${A[2]}) && ${A[0]} < Math.max(${A[1]}, ${A[2]})) `
			+ `? (${dA[0]} / (Math.max(${A[1]}, ${A[2]}) - Math.min(${A[1]}, ${A[2]}))) : 0)`),
	// d/dx of 1/(1 + (x/X)^(2s)) is -(2s/x) · r/(1+r)^2 with r = (x/X)^(2s),
	// which is -(2s/x) · V · (1 - V) once V is in hand. Zero for x <= 0, where
	// the primal is flat at 1. `s` and `X` are constants here for the same
	// reason a ramp's ends are: a transition whose *shape* depends on the state
	// is not something to guess at.
	smoothDown: ({ A, dA, V }) => (dA[0] == null || dA[1] != null || dA[2] != null
		? null
		: `((${A[0]} > 0) ? ((-2 * ${A[2]} / ${A[0]}) * ${V} * (1 - ${V}) * ${dA[0]}) : 0)`),
	smoothUp: ({ A, dA, V }) => (dA[0] == null || dA[1] != null || dA[2] != null
		? null
		: `((${A[0]} > 0) ? ((2 * ${A[2]} / ${A[0]}) * (1 - ${V}) * ${V} * ${dA[0]}) : 0)`),
	// Piecewise constant: exactly zero away from the jumps.
	ceil: () => null,
	floor: () => null,
	round: () => null,
	fix: () => null,
	sign: () => null,
	not: () => null,
	and: () => null,
	or: () => null,
	nand: () => null,
	nor: () => null,
	xor: () => null,
	eps: () => null,
	pi: () => null,
	// A table's derivative is the slope of the segment the lookup point falls
	// in -- zero outside it, unless the rule extrapolates. The table itself is
	// assumed constant; a live tangent among its points is refused below.
	interpolationUseEndValues: ({ A, dA }) => (dA.slice(1).some((d) => d != null)
		? null
		: `(F.interpolationUseEndValues.slope(${A.join(', ')}) * ${dA[0]})`),
	interpolationExtrapolation: ({ A, dA }) => (dA.slice(1).some((d) => d != null)
		? null
		: `(F.interpolationExtrapolation.slope(${A.join(', ')}) * ${dA[0]})`),
	// The unit conversions. bq2mole(a, T) is c·a·T, so its tangent is the
	// same conversion applied to each argument's tangent in turn; mole2bq(n, T)
	// is c·n/T, linear in the amount and falling as 1/T in the half-life.
	// Through the library's own functions rather than a constant written out
	// here, so the tangent can never use a different Avogadro's number or a
	// different year from the value it is the tangent of.
	bq2mole: ({ A, dA }) => added([
		dA[0] == null ? null : `F.bq2mole.fn(${dA[0]}, ${A[1]})`,
		dA[1] == null ? null : `F.bq2mole.fn(${A[0]}, ${dA[1]})`,
	]),
	mole2bq: ({ A, dA, V }) => added([
		dA[0] == null ? null : `F.mole2bq.fn(${dA[0]}, ${A[1]})`,
		dA[1] == null ? null : `(-${V} * ${dA[1]} / ${A[1]})`,
	]),
};

/**
 * Functions whose rule returns null only because it will not guess -- as
 * opposed to the staircases, whose derivative really is zero.
 */
const LIVE_OR_REFUSE = new Set(['interpolationUseEndValues', 'interpolationExtrapolation']);

/** `d` scaled by `a`, dropping a structurally zero factor. */
function term(a, d) {
	return d == null ? '' : `${a} * ${d}`;
}

/** The terms that are there, added up; null when none of them is. */
function added(parts) {
	const live = parts.filter((p) => p != null);
	if (!live.length) return null;
	return live.length === 1 ? live[0] : `(${live.join(' + ')})`;
}
const plus = (s) => (s ? ` + ${s}` : '');
const minus = (s) => (s ? ` - ${s}` : '');

/**
 * How many arguments a nested selection may have before it is flattened.
 *
 * The chain below nests one level per argument, and a nested expression is a
 * nested parse: V8 overflows its own parser stack at about a thousand, so a
 * `min` over an index list of a thousand indices produced a tangent function
 * that could not be compiled at all -- and took the whole analytic Jacobian
 * with it. Measured at 500 deep ok, 1000 deep RangeError; this is well below.
 */
const MAX_SELECT_NEST = 64;

/**
 * The derivative of `min`/`max`: the tangent of whichever argument was chosen.
 * Ties pick the first, which is the usual compromise at a kink. The trailing
 * NaN matters: with a NaN argument Math.min returns NaN, no comparison matches,
 * and without it the chain would quietly return the last tangent.
 *
 * Past `MAX_SELECT_NEST` arguments the same chain is written as statements on
 * the tape instead of as one nested expression -- identical arithmetic, one
 * level deep. It costs every comparison rather than stopping at the match,
 * which is the price of being compilable at all.
 */
function selectRule(A, dA, V, tape = null) {
	if (A.length > MAX_SELECT_NEST && tape) {
		let out = 'NaN';
		for (let i = A.length - 1; i >= 0; i--) {
			out = hoist(tape, `((${A[i]} === ${V}) ? ${dA[i] ?? 0} : ${out})`);
		}
		return out;
	}
	let out = 'NaN';
	for (let i = A.length - 1; i >= 0; i--) {
		out = `((${A[i]} === ${V}) ? ${dA[i] ?? 0} : ${out})`;
	}
	return out;
}

/**
 * d(a^b). The exponent is nearly always a constant or a parameter, so those
 * cases are folded rather than paying for the general formula -- which needs
 * log(a) and is undefined for a <= 0.
 */
function powerRule(A, dA, V, exponent) {
	const [a, b] = A;
	const [da, db] = dA;
	if (db == null && exponent != null) {
		if (exponent === 0) return null;
		if (exponent === 1) return da;
		if (exponent === 2) return `(2 * ${a} * ${da})`;
		if (exponent === 0.5) return `(${da} / (2 * ${V}))`;
		return `(${exponent} * Math.pow(${a}, ${exponent - 1}) * ${da})`;
	}
	if (db == null) return `(${b} * Math.pow(${a}, ${b} - 1) * ${da})`;
	// A varying exponent needs log(a), which only exists for a > 0. Below that
	// the base term is still right, so it is kept rather than poisoning the
	// whole column with NaN.
	if (da == null) return `((${a} > 0) ? (${V} * Math.log(${a}) * ${db}) : 0)`;
	return `((${a} > 0) ? (${V} * ((${b} / ${a}) * ${da} + Math.log(${a}) * ${db}))`
		+ ` : (${b} * Math.pow(${a}, ${b} - 1) * ${da}))`;
}

/** A literal exponent, seeing through the unary minus of `2^-1`. */
function constantExponent(node) {
	if (node.type === 'num') return node.value;
	if (node.type === 'unary' && node.operand.type === 'num') return -node.operand.value;
	return null;
}

/**
 * Emits `ast` together with its derivative along a seed direction.
 *
 * Statements are appended to `tape`; the return value names the expressions
 * holding the value and the tangent. A null tangent means *structurally* zero
 * -- not "happens to be zero here" -- which is what lets the caller drop terms
 * and, in the end, read the sparsity pattern off the model rather than off a
 * numerical probe. It also keeps 0 * Infinity from appearing: a zero folded
 * away can never meet an infinity.
 *
 * @param {object} ast
 * @param {(name: string, indices?: Array) => {value: string, tangent: string|null}} resolve
 * @param {object} tape  from makeTape()
 * @param {(name: string, argCodes: string[]) => ({value: string, slope?: string}|null)}
 *        [resolveCall] as in emit(), plus the `slope` a live argument needs
 * @returns {{value: string, tangent: string|null}}
 */
export function emitWithTangent(ast, resolve, tape, resolveCall) {
	try {
		return tangentNode(ast, resolve, tape, resolveCall);
	} catch (e) {
		throw tooBigToEmit(e);
	}
}

function tangentNode(ast, resolve, tape, resolveCall) {
	switch (ast.type) {
		case 'num':
			return { value: emit(ast, null), tangent: null };

		case 'ref': {
			const r = resolve(ast.name, ast.indices, ast);
			return { value: r.value, tangent: r.tangent ?? null };
		}

		case 'unary': {
			const a = tangentNode(ast.operand, resolve, tape, resolveCall);
			return {
				value: hoist(tape, `(-${a.value})`),
				tangent: a.tangent == null ? null : hoist(tape, `(-${a.tangent})`),
			};
		}

		case 'binary': {
			const l = tangentNode(ast.left, resolve, tape, resolveCall);
			const r = tangentNode(ast.right, resolve, tape, resolveCall);
			const tmpl = BINARY_TEMPLATES[ast.op];
			if (!tmpl) throw new Error(`Cannot emit operator '${ast.op}'`);
			const value = hoist(tape, tmpl(l.value, r.value));
			return { value, tangent: hoist(tape, binaryTangent(ast, l, r, value)) };
		}

		case 'cond':
			return condWithTangent(ast.test, ast.then, ast.otherwise, resolve, tape, resolveCall);

		case 'call': {
			const name = FUNCTION_ALIASES[ast.name] ?? ast.name;
			if (name === 'if') {
				return condWithTangent(
					ast.args[0], ast.args[1], ast.args[2] ?? { type: 'num', value: 0 },
					resolve, tape, resolveCall,
				);
			}
			const parts = ast.args.map((a) => tangentNode(a, resolve, tape, resolveCall));
			const A = parts.map((p) => p.value);
			const dA = parts.map((p) => p.tangent);

			// A call the model defines -- a lookup table read at an argument.
			// Its derivative is the slope of the segment the argument lands in,
			// times the argument's own tangent; the table's points are data, so
			// they contribute nothing.
			const own = resolveCall ? resolveCall(ast.name, A) : null;
			if (own) {
				const v = hoist(tape, own.value);
				if (dA.every((d) => d == null)) return { value: v, tangent: null };
				if (!own.slope || dA.slice(1).some((d) => d != null)) {
					throw new NoDerivative(`${ast.name}()`);
				}
				return { value: v, tangent: hoist(tape, `(${own.slope} * ${dA[0]})`) };
			}

			const value = hoist(tape, emitCall(name, A));

			// No live argument derivative means the call is constant along the
			// seed, whatever the function is -- which is how factorial() of a
			// parameter stays usable while factorial() of a state is refused.
			if (dA.every((d) => d == null)) return { value, tangent: null };

			if (name === 'power') {
				// Guarded like the rules below it: a zero seed contributes
				// zero whatever the exponent does. `power(a, 0.5)` at a = 0
				// otherwise divides by sqrt(0) and writes NaN into a column
				// the expression does not even depend on.
				return {
					value,
					tangent: hoist(tape, guardZeroSeed(
						dA, powerRule(A, dA, value, constantExponent(ast.args[1])),
					)),
				};
			}
			if (name === 'min' || name === 'max') {
				return { value, tangent: hoist(tape, selectRule(A, dA, value, tape)) };
			}
			if (name === 'sum' || name === 'mean') {
				const live = dA.filter((d) => d != null);
				const total = `(${live.join(' + ')})`;
				return {
					value,
					tangent: hoist(tape, name === 'sum' ? total : `(${total} / ${A.length})`),
				};
			}
			if (name === 'prod') {
				// Left fold, matching the association FOLDABLE emits, and safe
				// when a factor is zero -- which the tidier V * sum(dA_i/A_i)
				// form is not, and an empty compartment is exactly that case.
				let p = A[0];
				let dp = dA[0];
				for (let i = 1; i < A.length; i++) {
					const next = hoist(tape, `(${p} * ${A[i]})`);
					const parts2 = [];
					if (dp != null) parts2.push(`${dp} * ${A[i]}`);
					if (dA[i] != null) parts2.push(`${p} * ${dA[i]}`);
					dp = parts2.length ? hoist(tape, `(${parts2.join(' + ')})`) : null;
					p = next;
				}
				return { value, tangent: dp };
			}

			const rule = TANGENT_RULES[name];
			if (!rule) throw new NoDerivative(`${name}()`);
			const tangent = guardZeroSeed(dA, rule({ A, dA, V: value }));
			// A rule that cannot differentiate what it was given says so by
			// returning null while an argument still has a live tangent: a
			// table whose own points move with the state is not something to
			// guess at.
			if (tangent == null && dA.some((d) => d != null) && LIVE_OR_REFUSE.has(name)) {
				throw new NoDerivative(`${name}() with a table that depends on the state`);
			}
			return { value, tangent: hoist(tape, tangent) };
		}

		default:
			throw new Error(`Cannot emit node type '${ast.type}'`);
	}
}

function binaryTangent(ast, l, r, value) {
	const da = l.tangent;
	const db = r.tangent;
	switch (ast.op) {
		case '+':
			if (da == null) return db;
			return db == null ? da : `(${da} + ${db})`;
		case '-':
			if (db == null) return da;
			return da == null ? `(-${db})` : `(${da} - ${db})`;
		case '*':
			if (da == null && db == null) return null;
			if (db == null) return `(${da} * ${r.value})`;
			if (da == null) return `(${l.value} * ${db})`;
			return `(${da} * ${r.value} + ${l.value} * ${db})`;
		case '/':
			if (da == null && db == null) return null;
			if (db == null) return `(${da} / ${r.value})`;
			// Reusing the quotient costs one multiply and duplicates nothing.
			if (da == null) return `((-(${value} * ${db})) / ${r.value})`;
			return `((${da} - ${value} * ${db}) / ${r.value})`;
		case '^':
			if (da == null && db == null) return null;
			// `a^0.5` must answer what `sqrt(a)` answers: the same guard, for
			// the same reason -- at a = 0 the rule divides by sqrt(0), and a
			// seed that never reaches `a` was owed a plain 0 rather than the
			// 0/0 it got.
			return guardZeroSeed(
				[da, db],
				powerRule([l.value, r.value], [da, db], value, constantExponent(ast.right)),
			);
		default:
			// Comparisons and the logical operators return 1 or 0 and are
			// locally constant; on the switching surface itself the derivative
			// is a delta, which no number represents. Zero is exact everywhere
			// else, and a solver only needs a good local model.
			return null;
	}
}

/**
 * A conditional, as a block rather than a ternary: the branch not taken is not
 * evaluated, so `if(t > t0, <expensive>, 0)` still costs what it costs, and a
 * branch that would divide by zero is never entered.
 */
function condWithTangent(testAst, thenAst, elseAst, resolve, tape, resolveCall) {
	const test = tangentNode(testAst, resolve, tape, resolveCall);
	const name = `v${tape.n++}`;
	const dname = `v${tape.n++}`;

	const build = (ast) => {
		const sub = branchTape(tape);
		const r = tangentNode(ast, resolve, sub, resolveCall);
		closeBranch(tape, sub);
		return { sub, r };
	};
	const a = build(thenAst);
	const b = build(elseAst);
	const live = a.r.tangent != null || b.r.tangent != null;

	tape.lines.push(`${tape.indent}let ${name}${live ? `, ${dname}` : ''};`);
	tape.lines.push(`${tape.indent}if (${test.value} !== 0) {`);
	tape.lines.push(...a.sub.lines);
	tape.lines.push(`${tape.indent}\t${name} = ${a.r.value};`
		+ (live ? ` ${dname} = ${a.r.tangent ?? 0};` : ''));
	tape.lines.push(`${tape.indent}} else {`);
	tape.lines.push(...b.sub.lines);
	tape.lines.push(`${tape.indent}\t${name} = ${b.r.value};`
		+ (live ? ` ${dname} = ${b.r.tangent ?? 0};` : ''));
	tape.lines.push(`${tape.indent}}`);
	tape.count += 2;
	return { value: name, tangent: live ? dname : null };
}

/** The value code for a call, byte-identical to what `emit` produces. */
function emitCall(name, args) {
	if (INLINE[name] && args.length <= INLINE[name].length) return INLINE[name](...args);
	if (FOLDABLE[name]) return FOLDABLE[name](args);
	const spec = FUNCTIONS[name];
	if (!spec) throw new Error(`Unknown function '${name}'`);
	if (spec.needsContext) {
		return `F.${name}.fn(ctx${args.length ? ', ' + args.join(', ') : ''})`;
	}
	return `F.${name}.fn(${args.join(', ')})`;
}

export { FUNCTIONS as FUNCTION_TABLE };
