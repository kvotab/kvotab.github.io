/**
 * Tokenizer and parser for the model expression language.
 *
 * Precedence notes, measured against the files this reads rather than guessed.
 * An equation in one of those is rewritten so that `a^b` becomes `pow(a, b)`
 * and the rest is evaluated as an ordinary C-family expression, which fixes
 * three things that are easy to get wrong:
 *
 *   - precedence is the C family's for everything except `^`;
 *   - `^` binds tighter than unary minus and is LEFT-associative, because the
 *     rewrite takes one operand per side scanning left to right
 *     (so 2^3^2 === 64);
 *   - `2^-1` is legal: a leading sign in the exponent is allowed.
 *
 * On the surface the language keeps two array-language conveniences: `~=` is
 * not-equal, and `.*`, `./`, `.^` are accepted as aliases of `*`, `/`, `^`.
 */

import { lookupFunction } from './functions.js';

export class ParseError extends Error {
	constructor(message, position, source) {
		super(message);
		this.name = 'ParseError';
		this.position = position;
		this.source = source;
	}
}

// --- tokenizer -----------------------------------------------------------

const T = {
	NUMBER: 'number',
	IDENT: 'ident',
	OP: 'op',
	LPAREN: 'lparen',
	RPAREN: 'rparen',
	COMMA: 'comma',
	LBRACKET: 'lbracket',
	RBRACKET: 'rbracket',
	INDEX: 'index',
	EOF: 'eof',
};

/** Multi-character operators must be tried before single-character ones. */
const OPERATORS = [
	'<=', '>=', '==', '~=', '!=', '&&', '||', '.*', './', '.^',
	'+', '-', '*', '/', '^', '<', '>', '?', ':',
];

const OP_ALIAS = { '.*': '*', './': '/', '.^': '^', '!=': '~=' };

// Code points rather than a regex per character. `tokenize` asks these once
// for every character of every equation in the model, and the editor
// re-tokenises the whole model on every edit -- so `/[A-Za-z0-9_]/.test(c)`,
// which allocates nothing but walks the regex engine each time, was 274 ms of
// the 1.4-second scan on the largest assessment here. Same alphabet, same
// answers; `isDigit` on the line above has always done it this way.
const isDigit = (c) => c >= '0' && c <= '9';

const A = 65, Z = 90, a = 97, z = 122, ZERO = 48, NINE = 57, UNDERSCORE = 95;

const isIdentStart = (c) => {
	if (c === undefined) return false;
	const k = c.charCodeAt(0);
	return (k >= a && k <= z) || (k >= A && k <= Z) || k === UNDERSCORE;
};

const isIdentPart = (c) => {
	if (c === undefined) return false;
	const k = c.charCodeAt(0);
	return (k >= a && k <= z) || (k >= A && k <= Z)
		|| (k >= ZERO && k <= NINE) || k === UNDERSCORE;
};

export function tokenize(src) {
	const tokens = [];
	let i = 0;

	while (i < src.length) {
		const c = src[i];

		if (c === ' ' || c === '\t' || c === '\n' || c === '\r') {
			i++;
			continue;
		}

		// Numbers, including 1e-5 / 1.0E10 exponent forms.
		if (isDigit(c) || (c === '.' && isDigit(src[i + 1]))) {
			const start = i;
			while (i < src.length && isDigit(src[i])) i++;
			if (src[i] === '.') {
				i++;
				while (i < src.length && isDigit(src[i])) i++;
			}
			if (src[i] === 'e' || src[i] === 'E') {
				const save = i;
				i++;
				if (src[i] === '+' || src[i] === '-') i++;
				if (isDigit(src[i])) {
					while (i < src.length && isDigit(src[i])) i++;
				} else {
					i = save; // not an exponent after all, e.g. "2e" in "2*ex"
				}
			}
			const text = src.slice(start, i);
			tokens.push({ type: T.NUMBER, value: Number(text), text, pos: start });
			continue;
		}

		if (isIdentStart(c)) {
			const start = i;
			while (i < src.length && isIdentPart(src[i])) i++;
			// A dotted path is one name, not a field access: Ecolego scopes
			// block names by sub-system, and `NearField.Water` is how an
			// equation reaches one. The dot is only swallowed when a letter
			// follows it, so `a .* b` is still three tokens and `x.5` is still
			// a name and a number.
			while (src[i] === '.' && isIdentStart(src[i + 1])) {
				i++;
				while (i < src.length && isIdentPart(src[i])) i++;
			}
			const text = src.slice(start, i);
			tokens.push({ type: T.IDENT, value: text, text, pos: start });
			continue;
		}

		if (c === '(') { tokens.push({ type: T.LPAREN, text: c, pos: i++ }); continue; }
		if (c === ')') { tokens.push({ type: T.RPAREN, text: c, pos: i++ }); continue; }
		if (c === ',') { tokens.push({ type: T.COMMA, text: c, pos: i++ }); continue; }
		// An index name is raw text up to the closing bracket, not something
		// to tokenize: an index is read exactly
		// that, and real models need it -- `F.18:00_51_FORSMARK`, `_Ra-226`,
		// `01`, `B.04:00_205_BARSEBÄCK`. Tokenizing it would reject the colon
		// and the Ä, and would leave `Cs` in `A[Cs-137]` looking like a block
		// reference to anything that walks the token stream.
		if (c === '[') {
			tokens.push({ type: T.LBRACKET, text: c, pos: i++ });
			const start = i;
			while (i < src.length && src[i] !== ']') i++;
			if (i > start) {
				const text = src.slice(start, i);
				tokens.push({ type: T.INDEX, value: text, text, pos: start });
			}
			continue;
		}
		if (c === ']') { tokens.push({ type: T.RBRACKET, text: c, pos: i++ }); continue; }

		const op = OPERATORS.find((o) => src.startsWith(o, i));
		if (op) {
			tokens.push({
				type: T.OP,
				value: OP_ALIAS[op] ?? op,
				text: op,
				pos: i,
			});
			i += op.length;
			continue;
		}

		throw new ParseError(`Unexpected character '${c}'`, i, src);
	}

	tokens.push({ type: T.EOF, text: '<end>', pos: src.length });
	return tokens;
}

// --- parser --------------------------------------------------------------

/**
 * Binary precedence, following the C family (see the note at the top of this file).
 * `^` is handled separately because it is left-associative but binds tighter
 * than unary minus.
 */
const BINARY_PRECEDENCE = {
	'||': 1,
	'&&': 2,
	'==': 3, '~=': 3,
	'<': 4, '<=': 4, '>': 4, '>=': 4,
	'+': 5, '-': 5,
	'*': 6, '/': 6,
};

const POWER_PRECEDENCE = 8;

/**
 * Parses an equation string into an AST.
 *
 * Node shapes:
 *   { type: 'num',  value, unit? }     -- `unit` only when written as `0.01[m]`
 *   { type: 'ref',  name, indices }   -- a reference to a block; `indices` is
 *                                      one entry per bracket, null for `[]`
 *   { type: 'call', name, args }
 *   { type: 'unary', op, operand }
 *   { type: 'binary', op, left, right }
 *   { type: 'cond', test, then, otherwise }
 *
 * `options.calls` names calls the *model* defines rather than the function
 * table: a lookup table with an argument is written `Table(x)`, and only the
 * caller knows which names those are. Without it an unknown call is an error
 * here, which is where the position information is, rather than three layers
 * down in the code generator.
 */
export function parse(src, options = {}) {
	if (src == null || String(src).trim() === '') {
		return { type: 'num', value: 0 };
	}
	const tokens = tokenize(String(src));
	let pos = 0;

	const peek = () => tokens[pos];
	const next = () => tokens[pos++];

	function expect(type, what) {
		const tok = peek();
		if (tok.type !== type) {
			throw new ParseError(
				`Expected ${what} but found '${tok.text}'`, tok.pos, src,
			);
		}
		return next();
	}

	function parsePrimary() {
		const tok = peek();

		if (tok.type === T.NUMBER) {
			next();
			// `0.01[m]`: a number with its unit written against it. The unit
			// is bookkeeping for the checker -- the compiler reads the value
			// and nothing else, exactly as it did before the bracket -- so a
			// literal can say what it is in without a parameter being made of
			// it. GoldSim writes constants this way; the syntax is borrowed
			// from there and from the index brackets that already exist.
			if (peek().type === T.LBRACKET) {
				next();
				const text = peek().type === T.INDEX ? next().value.trim() : '';
				expect(T.RBRACKET, "']'");
				return { type: 'num', value: tok.value, unit: text };
			}
			return { type: 'num', value: tok.value };
		}

		if (tok.type === T.LPAREN) {
			next();
			const inner = parseTernary();
			expect(T.RPAREN, "')'");
			return inner;
		}

		if (tok.type === T.OP && (tok.value === '-' || tok.value === '+')) {
			next();
			// Unary binds looser than `^`, so -a^2 is -(a^2).
			const operand = parseBinary(POWER_PRECEDENCE - 1);
			return tok.value === '-'
				? { type: 'unary', op: '-', operand }
				: operand;
		}

		if (tok.type === T.IDENT) {
			next();
			const name = tok.value;

			// Function call?
			if (peek().type === T.LPAREN) {
				const fn = lookupFunction(name);
				if (!fn) {
					if (!options.calls?.(name)) {
						throw new ParseError(`Unknown function '${name}'`, tok.pos, src);
					}
					next(); // consume '('
					const own = [];
					if (peek().type !== T.RPAREN) {
						for (;;) {
							own.push(parseTernary());
							if (peek().type === T.COMMA) { next(); continue; }
							break;
						}
					}
					expect(T.RPAREN, "')'");
					// How many arguments it takes is the caller's business.
					return { type: 'call', name, args: own };
				}
				next(); // consume '('
				const args = [];
				if (peek().type !== T.RPAREN) {
					for (;;) {
						args.push(parseTernary());
						if (peek().type === T.COMMA) { next(); continue; }
						break;
					}
				}
				expect(T.RPAREN, "')'");

				const max = fn.maxArity ?? (fn.varargs ? Infinity : fn.arity);
				if (args.length < fn.arity || args.length > max) {
					const wanted = max === Infinity
						? `at least ${fn.arity}`
						: fn.arity === max ? `${fn.arity}` : `${fn.arity}-${max}`;
					throw new ParseError(
						`Function '${name}' takes ${wanted} argument(s), got ${args.length}`,
						tok.pos, src,
					);
				}
				return { type: 'call', name: fn.key, args };
			}

			// Zero-argument functions may be written without parentheses
			// (`time`, `pi`, `eps`), as the function library has them.
			const fn = lookupFunction(name);
			if (fn && fn.arity === 0) {
				return { type: 'call', name: fn.key, args: [] };
			}

			// Otherwise it is a reference to another block, with one bracket
			// per pinned dimension: `C1[Cs-137]`, or `M[_Ra-226][Pb-210]` for a
			// two-dimensional one. Ecolego writes exactly one bracket per
			// dimension of the target and an empty
			// `[]` for a dimension it does not pin.
			//
			// The contents come from the tokenizer as one raw string, because
			// an index name is not an identifier: real models use
			// `F.18:00_51_FORSMARK`, `_Ra-226`, `11` and `BARSEBÄCK`.
			const indices = [];
			while (peek().type === T.LBRACKET) {
				next();
				const text = peek().type === T.INDEX ? next().value.trim() : '';
				expect(T.RBRACKET, "']'");
				indices.push(text === '' ? null : text);
			}
			return { type: 'ref', name, indices };
		}

		throw new ParseError(`Unexpected '${tok.text}'`, tok.pos, src);
	}

	/**
	 * The exponent of `^`: one operand, with a sign allowed in front of it.
	 *
	 * `parsePrimary` cannot be used for this directly, because its own sign
	 * branch descends into `parseBinary` and so swallows the whole `^` chain:
	 * `2^-3^2` parsed as `2^-(3^2)`. The rewrite takes exactly one token
	 * on each side -- `closes = i + 3` when the token after `^` is a sign,
	 * `i + 2` otherwise -- so the exponent stops at the operand and the next
	 * `^` applies to the power already built. `2^-3^2` is `(2^-3)^2`.
	 */
	function parseExponent() {
		const tok = peek();
		if (tok.type === T.OP && (tok.value === '-' || tok.value === '+')) {
			next();
			const operand = parseExponent();
			return tok.value === '-'
				? { type: 'unary', op: '-', operand }
				: operand;
		}
		return parsePrimary();
	}

	/** `^`, left-associative, tighter than unary minus. */
	function parsePower() {
		let left = parsePrimary();
		while (peek().type === T.OP && peek().value === '^') {
			next();
			// The exponent takes a single operand, optionally signed.
			const right = parseExponent();
			left = { type: 'binary', op: '^', left, right };
		}
		return left;
	}

	function parseBinary(minPrec) {
		let left = parsePower();
		for (;;) {
			const tok = peek();
			if (tok.type !== T.OP) break;
			const prec = BINARY_PRECEDENCE[tok.value];
			if (prec === undefined || prec < minPrec) break;
			next();
			const right = parseBinary(prec + 1); // all binaries are left-assoc
			left = { type: 'binary', op: tok.value, left, right };
		}
		return left;
	}

	function parseTernary() {
		const test = parseBinary(1);
		if (peek().type === T.OP && peek().value === '?') {
			next();
			const then = parseTernary();
			const colon = peek();
			if (colon.type !== T.OP || colon.value !== ':') {
				throw new ParseError(
					`Expected ':' in conditional but found '${colon.text}'`,
					colon.pos, src,
				);
			}
			next();
			const otherwise = parseTernary();
			return { type: 'cond', test, then, otherwise };
		}
		return test;
	}

	let ast;
	try {
		ast = parseTernary();
	} catch (e) {
		// The parser descends one frame per level of nesting, so an equation
		// nested a couple of thousand deep exhausts the stack. That arrived as
		// a bare `RangeError: Maximum call stack size exceeded` from somewhere
		// inside this file, with no equation named and nothing to act on --
		// and it is not a bug in the model, it is a limit, so it says so.
		if (e instanceof RangeError) {
			throw new ParseError(
				'This equation is nested too deeply to read. Split it into '
				+ 'expression blocks, which is also how anyone else will be '
				+ 'able to follow it.',
				0, src,
			);
		}
		throw e;
	}
	const trailing = peek();
	if (trailing.type !== T.EOF) {
		throw new ParseError(`Unexpected '${trailing.text}'`, trailing.pos, src);
	}
	return ast;
}

/** Collects the names of every block referenced by an AST. */
export function collectReferences(ast, out = new Set()) {
	switch (ast.type) {
		case 'ref':
			out.add(ast.name);
			break;
		case 'call':
			ast.args.forEach((a) => collectReferences(a, out));
			break;
		case 'unary':
			collectReferences(ast.operand, out);
			break;
		case 'binary':
			collectReferences(ast.left, out);
			collectReferences(ast.right, out);
			break;
		case 'cond':
			collectReferences(ast.test, out);
			collectReferences(ast.then, out);
			collectReferences(ast.otherwise, out);
			break;
	}
	return out;
}

export { T as TokenType };
