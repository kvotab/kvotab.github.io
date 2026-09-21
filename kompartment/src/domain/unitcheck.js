/**
 * Unit checking: does an equation come out in the unit the block claims?
 *
 * Ecolego does this in `domain.validation.EquationValidator.validateUnit`,
 * against `javax.measure`. The rules here are that method's, read off the
 * source rather than guessed:
 *
 *   `*` and `/`      multiply and divide the units
 *   `+` and `-`      the two sides must agree -- **except** that a
 *                    dimensionless side is absorbed, so `1 + k*t` is fine
 *   `^`              the exponent must be a constant; the base is raised to it
 *   a comparison     is dimensionless, whatever it compares
 *   min, max, if     every argument must agree; the result is that unit
 *   sqrt             halves the exponents
 *   time             is the simulation's time unit
 *
 * and the two special targets: a compartment's *derivative* is checked against
 * `<compartment>/<time>` rather than against the compartment's own unit, and a
 * delay time against the time unit.
 *
 * Two things this deliberately does not do. It never converts -- `m` and `cm`
 * are different units here, because nothing in this tool multiplies by a
 * conversion factor and silently accepting `cm` where `m` was meant would be
 * worse than saying nothing. What it *does* know is that they are the same
 * kind of quantity a factor apart: an SI prefix on a base unit is read as that
 * unit with a scale (`kBq` is 1000 Bq, `cm^3` is 10^-6 m^3), so the message for
 * `kBq/m^3` against `Bq/m^3` can say "the same quantity, 1000 times larger"
 * rather than treat them as strangers -- and can still say it, since the two
 * never compare equal. GoldSim converts; this reports. And it never fails a
 * run: the engine treats units as labels, so a mismatch is a warning about the
 * model's bookkeeping, not an error in it.
 */

import { parse, ParseError } from '../parser/parser.js';
import { lookupFunction } from '../parser/functions.js';

/**
 * What a unit means once the spelling is taken off it: a power for each base
 * symbol, and a scale -- the factor an SI prefix put in front. `kBq/m^3` is
 * {Bq: 1, m: -3} at scale 1000. The scale is part of the unit, so `equals`
 * compares it: a kilobecquerel is not a becquerel. `sameKind` is the looser
 * question, "the same quantity, whatever the factor", and `factor` is the
 * factor, for the message that says so.
 */
export class Dim {
	constructor(powers = new Map(), scale = 1) {
		this.powers = powers;
		this.scale = scale;
	}

	static one() { return new Dim(); }

	/** Unitless: no dimension and no factor. A bare `1000` is not a unit. */
	get isOne() { return this.powers.size === 0 && this.scale === 1; }

	times(other, sign = 1) {
		const out = new Map(this.powers);
		for (const [sym, n] of other.powers) {
			const next = (out.get(sym) ?? 0) + n * sign;
			if (next === 0) out.delete(sym);
			else out.set(sym, next);
		}
		return new Dim(out, sign > 0 ? this.scale * other.scale : this.scale / other.scale);
	}

	over(other) { return this.times(other, -1); }

	pow(n) {
		if (n === 0) return Dim.one();
		const out = new Map();
		for (const [sym, e] of this.powers) {
			const next = e * n;
			// A root that does not come out whole is not a unit this can
			// name, so it is not a unit this will claim to have checked.
			if (!Number.isInteger(next)) return null;
			out.set(sym, next);
		}
		return new Dim(out, this.scale ** n);
	}

	/** The same base symbols to the same powers: the same kind of quantity. */
	sameKind(other) {
		if (!other || this.powers.size !== other.powers.size) return false;
		for (const [sym, n] of this.powers) if (other.powers.get(sym) !== n) return false;
		return true;
	}

	/** How many of `other` make one of this: 1000 for kBq against Bq. */
	factor(other) { return this.scale / other.scale; }

	equals(other) {
		if (!this.sameKind(other)) return false;
		// Scales are products of powers of ten and come out of floating-point
		// arithmetic, so 0.01^3 against 1e-6 is a relative comparison.
		return Math.abs(this.factor(other) - 1) < 1e-9;
	}

	/**
	 * Canonical, so two spellings of one unit read the same in a message. The
	 * scale is written as a number in front -- `1000 Bq/m^3` -- rather than
	 * folded back into a prefix, because there is not always one to fold it
	 * into (`cm^3` is 10^-6 m^3, and no prefix on a cubic metre says that).
	 */
	toString() {
		if (this.isOne) return 'unitless';
		const up = [...this.powers].filter(([, n]) => n > 0).sort();
		const down = [...this.powers].filter(([, n]) => n < 0).sort();
		const part = ([sym, n]) => (Math.abs(n) === 1 ? sym : `${sym}^${Math.abs(n)}`);
		// `kBq/Bq`: no dimension left, only the factor.
		if (!up.length && !down.length) return `×${scaleText(this.scale)}`;
		const top = up.length ? up.map(part).join('*') : '1';
		const lead = this.scale === 1 ? '' : `${scaleText(this.scale)} `;
		if (!down.length) return `${lead}${top}`;
		const bottom = down.map(part).join('*');
		return `${lead}${top}/${down.length > 1 ? `(${bottom})` : bottom}`;
	}
}

/** A scale as a reader would write it: 1000, 0.01, 1e-6, 1e+12. */
export function scaleText(scale) {
	if (scale >= 1e-3 && scale < 1e6) {
		// Trim the float noise off 0.001 * 0.001 and the like.
		return String(Number(scale.toPrecision(12)));
	}
	return Number(scale.toPrecision(12)).toExponential().replace(/\.?0+e/, 'e');
}

/**
 * Spellings that mean the same thing.
 *
 * Only what the real files actually use: `Sv/y` appears 41 times beside
 * `Sv/year`, and treating them as different units would report a mismatch
 * where the modeller wrote the same thing twice. Anything not listed is left
 * exactly as written -- inventing equivalences is how a checker starts lying.
 */
const ALIAS = new Map(Object.entries({
	y: 'year', yr: 'year', years: 'year', a: 'year',
	sec: 's', second: 's', seconds: 's',
	hour: 'h', hours: 'h',
	day: 'd', days: 'd',
	litre: 'L', liter: 'L', l: 'L',
	Bequerel: 'Bq', becquerel: 'Bq',
	// UnitFactory's own aliases for the other unit an inventory can be in.
	// Not the same dimension as Bq, and deliberately: a model that adds an
	// amount to an activity has made a mistake worth reporting.
	Mole: 'mol', mole: 'mol', moles: 'mol',
	Sievert: 'Sv', sievert: 'Sv',
	kilogram: 'kg', kilograms: 'kg',
	metre: 'm', meter: 'm', metres: 'm', meters: 'm',
}));

/**
 * The SI prefixes, and the base units they may stand in front of.
 *
 * The list of bases is short on purpose. A prefix is only read off a symbol
 * whose remainder is one of these, so `mol` is a mole and not a milli-`ol`,
 * `min` a minute, `Gy` a gray, `Pa` a pascal, `ha` a hectare -- and a symbol
 * this tool has never seen stays exactly as written, which is the rule for
 * everything else here. Hecto, deca, peta and exa are left out: `h` is an
 * hour, `da` and `Pa` are other units, and none of the four appears in a
 * model on this machine.
 */
export const PREFIX = new Map(Object.entries({
	T: 1e12, G: 1e9, M: 1e6, k: 1e3,
	d: 1e-1, c: 1e-2, m: 1e-3, u: 1e-6, 'µ': 1e-6, 'μ': 1e-6, n: 1e-9, p: 1e-12,
}));

const PREFIXABLE = new Set(['Bq', 'Sv', 'Gy', 'g', 'kg', 'm', 'mol', 'L', 's', 'J', 'W', 'Pa', 'Ci']);

/**
 * The kilogram is the base unit of mass, in SI and in every model here: `kg`
 * appears in the files and `g` does not. So a gram is a thousandth of a
 * kilogram rather than the kilogram a thousand grams, and a message about
 * `kg/(m^2*year)` says `kg`, not `1000 g`.
 */
function massDim(base, scale) {
	if (base === 'g') return new Dim(new Map([['kg', 1]]), scale * 1e-3);
	return new Dim(new Map([[base, 1]]), scale);
}

/** Spellings of "no unit at all". */
const NONE = new Set(['', '-', '[-]', '1', 'unitless', 'dimensionless', 'none', 'n/a', '[]']);

/** `kBq` as {Bq: 1} at 1000; null when the symbol is not prefix + base. */
function prefixed(name) {
	for (const [pre, scale] of PREFIX) {
		if (!name.startsWith(pre) || name.length === pre.length) continue;
		const rest = name.slice(pre.length);
		const base = ALIAS.get(rest) ?? rest;
		if (base === 'kg') continue; // `mkg` is nothing; it is not milli-kilo-gram
		if (PREFIXABLE.has(base)) return massDim(base, scale);
	}
	return null;
}

function symbolDim(raw) {
	const sym = raw.trim();
	if (!sym) return Dim.one();
	if (NONE.has(sym.toLowerCase())) return Dim.one();
	// `m3`, `m2`, `cm3`: a length with its power written against it. Only a
	// length -- `Bq3` is not a thing anybody writes, and reading it as one
	// would be inventing.
	const packed = /^([A-Za-zµμ]+)(\d)$/.exec(sym);
	if (packed) {
		const base = symbolDim(packed[1]);
		if (base.powers.size === 1 && base.powers.has('m')) return base.pow(Number(packed[2]));
	}
	const name = ALIAS.get(sym) ?? sym;
	if (PREFIXABLE.has(name)) return massDim(name, 1);
	return prefixed(name) ?? new Dim(new Map([[name, 1]]));
}

/**
 * Reads a unit as it is written in a model: `Bq/m^3`, `kg/(m^2*year)`,
 * `year^-1`, `m year^-1`, `Sv/year/(Bq/m3)`.
 *
 * A space multiplies, which is what `m year^-1` means in these files. The one
 * casualty is a compound symbol written with a space -- `kg DW` becomes
 * kg·DW -- which costs nothing, since every use of it parses the same way and
 * so still compares equal to itself.
 *
 * @returns {Dim|null} null when it cannot be read at all
 */
export function parseUnit(text) {
	let src = String(text ?? '').trim();
	if (NONE.has(src.toLowerCase())) return Dim.one();
	// `[m3/m3]` -- brackets around the whole thing are decoration.
	if (/^\[.*\]$/.test(src)) src = src.slice(1, -1).trim();
	if (NONE.has(src.toLowerCase())) return Dim.one();

	// A unit is a handful of symbols, so a bracket nesting deeper than this is
	// not a unit anybody wrote. Bounded because `factor` recurses per bracket
	// and a long enough string of them overflowed the stack -- and a unit is
	// parsed while the panel is being drawn, so what the reader saw was the
	// whole settings dialog failing to appear. An unparseable unit is already
	// an ordinary outcome here: it means "no dimension", and the check that
	// uses it simply says nothing.
	const MAX_DEPTH = 32;
	let depth = 0;

	let at = 0;
	const skip = () => { while (at < src.length && src[at] === ' ') at++; };

	const number = () => {
		const m = /^[+-]?\d+(\.\d+)?/.exec(src.slice(at));
		if (!m) return null;
		at += m[0].length;
		return Number(m[0]);
	};

	const factor = () => {
		skip();
		if (src[at] === '(') {
			if (depth >= MAX_DEPTH) return null;
			at++;
			depth++;
			const inner = expr();
			depth--;
			skip();
			if (src[at] !== ')') return null;
			at++;
			return inner;
		}
		const m = /^[A-Za-z_µμ%][A-Za-z0-9_µμ%.]*/.exec(src.slice(at));
		if (m) {
			at += m[0].length;
			// `Sv/year per Bq/m3` -- the word, which is how a unit gets
			// written when it is read aloud.
			if (m[0] === 'per') return null;
			let dim = symbolDim(m[0]);
			// `year-1` is `year^-1` with the caret left out, which is how a
			// few of the real files write it.
			const bare = /^-\d+/.exec(src.slice(at));
			if (bare) { at += bare[0].length; dim = dim.pow(Number(bare[0])); }
			return dim;
		}
		// A bare number is dimensionless: `1/year` starts with one.
		const n = number();
		return n === null ? null : Dim.one();
	};

	const term = () => {
		let base = factor();
		if (!base) return null;
		// The space before a `^` is skipped, but only then: `m year^-1`
		// multiplies, and eating that space would hide the multiplication.
		const before = at;
		skip();
		if (src[at] !== '^') at = before;
		if (src[at] === '^') {
			at++;
			skip();
			let n;
			if (src[at] === '(') {
				at++;
				n = number();
				skip();
				// `m^(1/3)`: a rational exponent, which the files do use.
				if (n !== null && src[at] === '/') {
					at++;
					skip();
					const d = number();
					if (d === null || d === 0) return null;
					n /= d;
					skip();
				}
				if (n === null || src[at] !== ')') return null;
				at++;
			} else {
				n = number();
			}
			if (n === null) return null;
			base = base.pow(n);
			if (!base) return null;
		}
		return base;
	};

	const expr = () => {
		let out = term();
		if (!out) return null;
		for (;;) {
			// A space between two symbols multiplies them, so it only ends the
			// expression when what follows cannot start one.
			const save = at;
			skip();
			const ch = src[at];
			if (ch === '*' || ch === '·') {
				at++;
				const next = term();
				if (!next) return null;
				out = out.times(next);
			} else if (ch === '/') {
				at++;
				const next = term();
				if (!next) return null;
				out = out.over(next);
			} else if (/^per\b/.test(src.slice(at))) {
				// `Sv/year per Bq/m3` divides by the whole of what follows,
				// which is what reading it aloud means -- unlike a second
				// slash, which divides by one term at a time.
				at += 3;
				const rest = expr();
				if (!rest) return null;
				return out.over(rest);
			} else if (ch && /[A-Za-z_(µμ%]/.test(ch) && save !== at) {
				const next = term();
				if (!next) return null;
				out = out.times(next);
			} else {
				at = save;
				break;
			}
		}
		return out;
	};

	const value = expr();
	skip();
	return value && at >= src.length ? value : null;
}

/** True when two units mean the same thing, however each is written. */
export function sameUnit(a, b) {
	const x = parseUnit(a);
	const y = parseUnit(b);
	return !!x && !!y && x.equals(y);
}

/**
 * A mismatch found inside an equation, thrown so the walk can stop at the
 * first one -- as a parser does.
 */
class UnitClash extends Error {
	constructor(message) {
		super(message);
		this.name = 'UnitClash';
	}
}

/**
 * " — the same quantity, a factor of 1000 apart".
 *
 * Two sides of one operator that are the same kind a scale apart are the
 * commonest clash there is, and the reader should be handed the factor rather
 * than left to work out that `m` and `0.001 m` are related at all.
 *
 * A *literal* written directly against the other side never reaches this: it
 * was converted before anything was judged (see `scaleLiterals`). What reaches
 * this is the pair nothing can convert -- two blocks whose units differ, or a
 * literal buried in a product, where there is no one unit to scale it to. So
 * the note says the factor and leaves it there.
 */
function clashNote(l, r) {
	if (!l?.sameKind?.(r)) return '';
	// A factor without a direction: which of two operands is the larger is not
	// a thing a sentence can say without naming them again.
	const f = l.factor(r);
	return ` — the same quantity, a factor of ${scaleText(f >= 1 ? f : 1 / f)} apart; only a `
		+ 'literal written directly against the other side is converted, so the factor is '
		+ 'yours to write in here';
}

/** Every argument of min/max/if has to agree; a dimensionless one is absorbed. */
function agree(dims, what) {
	let out = null;
	for (const d of dims) {
		if (!d) return null;
		if (!out || out.isOne) { out = d; continue; }
		if (d.isOne || out.equals(d)) continue;
		throw new UnitClash(`${what} do not agree: ${out} and ${d}`);
	}
	return out;
}

/**
 * Functions whose result is dimensionless *and* whose argument must be.
 *
 * Nothing sensible comes of `exp(3 m)`: the series that defines it adds a
 * length to an area.
 */
const PURE = new Set([
	'exp', 'log', 'log10', 'log2', 'ln', 'sin', 'cos', 'tan', 'asin', 'acos',
	'atan', 'sinh', 'cosh', 'tanh', 'asinh', 'acosh', 'atanh', 'erf', 'erfc',
	'factorial', 'binomial',
]);

/** Functions that pass their argument's unit straight through. */
const SAME = new Set(['abs', 'fabs', 'ceil', 'floor', 'round', 'fix', 'min', 'max',
	'mean', 'percentile']);

/** Functions with no argument whose unit is known. */
const CLOCK = new Set(['time', 'start_time', 'end_time']);

/**
 * The unit an equation comes out in.
 *
 * `unitOf(name)` gives a referenced block's unit, or null when it has none --
 * and null spreads: an equation with one unknown in it has an unknown unit,
 * and this says so rather than guessing. That silence is what keeps the
 * checker quiet on the half of a real model that carries no units.
 *
 * @returns {{dim: Dim|null, clash: string|null}}
 */
export function equationUnit(ast, unitOf, timeDim) {
	const walk = (node) => {
		if (!node) return null;
		switch (node.type) {
			case 'num':
				// `0.01[m]` is a length; a bare number is nothing in
				// particular. A unit that cannot be read is an unknown, and
				// an unknown is silence, as it is for a block with none.
				// `dim` is what `scaleLiterals` left behind when it converted
				// the number: the unit it is in now, rather than the one it
				// was written in.
				if (node.dim) return node.dim;
				if (node.unit == null) return Dim.one();
				return parseUnit(node.unit);
			case 'ref':
				return unitOf(node.name);
			case 'unary':
				return node.op === '!' ? Dim.one() : walk(node.operand);
			case 'binary': {
				const op = node.op;
				if (['==', '!=', '<', '>', '<=', '>=', '~=', '&&', '||'].includes(op)) {
					// A comparison is a truth value. Its sides still have to
					// be comparable, which is worth saying when they are not.
					const l = walk(node.left);
					const r = walk(node.right);
					if (l && r && !l.isOne && !r.isOne && !l.equals(r)) {
						throw new UnitClash(`${l} and ${r} cannot be compared${clashNote(l, r)}`);
					}
					return Dim.one();
				}
				const l = walk(node.left);
				const r = walk(node.right);
				if (op === '*' || op === '.*') return l && r ? l.times(r) : null;
				if (op === '/' || op === './') return l && r ? l.over(r) : null;
				if (op === '^' || op === '.^') {
					if (!l) return null;
					if (l.isOne) return Dim.one();
					// An exponent that is not a constant, or one that leaves a
					// fractional power, is a unit this cannot name -- so it
					// says it does not know, rather than calling the model
					// wrong for something it cannot follow.
					if (node.right.type !== 'num') return null;
					return l.pow(node.right.value);
				}
				// + and -, where a dimensionless side is absorbed.
				if (!l || !r) return null;
				if (l.isOne) return r;
				if (r.isOne) return l;
				if (!l.equals(r)) {
					throw new UnitClash(`${l} and ${r} cannot be `
						+ `${op === '-' ? 'subtracted' : 'added'}${clashNote(l, r)}`);
				}
				return l;
			}
			case 'cond': {
				walk(node.test);
				return agree([walk(node.then), walk(node.otherwise)], 'the two results');
			}
			case 'call': {
				const name = node.name;
				const args = node.args.map(walk);
				if (CLOCK.has(name)) return timeDim;
				if (PURE.has(name)) {
					const a = args[0];
					if (a && !a.isOne) {
						throw new UnitClash(`${name} needs a plain number, not ${a}`);
					}
					return Dim.one();
				}
				if (name === 'sqrt') {
					return args[0] ? args[0].pow(0.5) : null;
				}
				if (name === 'power' || name === 'pow') {
					if (!args[0]) return null;
					if (args[0].isOne) return Dim.one();
					if (node.args[1]?.type !== 'num') return null;
					return args[0].pow(node.args[1].value);
				}
				if (name === 'if') {
					return agree(args.slice(1), 'the two results of if');
				}
				// A transition is a fraction between 0 and 1, so it is
				// dimensionless whatever it switches -- but the thing it
				// switches *on* and the times it switches at have to be the
				// same quantity, which is the mistake worth catching: a ramp
				// from year 100 to 0.5 m is not a ramp.
				if (name === 'rampUp' || name === 'rampDown') {
					agree(args, `the argument and the two ends of ${name}`);
					return Dim.one();
				}
				if (name === 'smoothUp' || name === 'smoothDown') {
					agree(args.slice(0, 2), `the argument and the half-way point of ${name}`);
					if (args[2] && !args[2].isOne) {
						throw new UnitClash(`the sharpness of ${name} is a plain number, `
							+ `not ${args[2]}`);
					}
					return Dim.one();
				}
				if (name === 'mod' || name === 'rem') return args[0] ?? null;
				if (name === 'atan2' || name === 'sign' || name === 'sgn') return Dim.one();
				if (name === 'hypot') return agree(args, 'the arguments of hypot');
				if (name === 'sum' || name === 'prod' || name === 'product') {
					return name === 'sum' ? agree(args, 'the arguments of sum') : null;
				}
				if (SAME.has(name)) return agree(args, `the arguments of ${name}`);
				// Something this does not know: an unknown unit, not a guess.
				return null;
			}
			default:
				return null;
		}
	};

	try {
		return { dim: walk(ast), clash: null };
	} catch (e) {
		if (e instanceof UnitClash) return { dim: null, clash: e.message };
		throw e;
	}
}

/**
 * Whether an equation names any block at all.
 *
 * Ecolego checks the unit only when it does,
 * and the reason is sound: `0.02` is written without a unit because a number
 * has none, and complaining that it is not `1/year` would be complaining
 * about every constant in the model.
 */
export function namesSomething(ast) {
	let found = false;
	const walk = (n) => {
		if (!n || found) return;
		if (n.type === 'ref') { found = true; return; }
		if (n.type === 'unary') walk(n.operand);
		else if (n.type === 'binary') { walk(n.left); walk(n.right); }
		else if (n.type === 'cond') { walk(n.test); walk(n.then); walk(n.otherwise); }
		else if (n.type === 'call') n.args.forEach(walk);
	};
	walk(ast);
	return found;
}

export { ParseError, parse, lookupFunction };

/** The operators whose two sides have to agree, and so can convert one. */
const AGREE_OPS = new Set(['+', '-', '==', '!=', '<', '>', '<=', '>=', '~=']);

/** The functions whose arguments have to agree. */
const AGREE_CALLS = new Set(['min', 'max', 'if', 'ifelse']);

/** Whether an equation carries a literal with a unit on it at all. */
function hasUnitLiteral(node) {
	if (!node || typeof node !== 'object') return false;
	if (node.type === 'num') return node.unit != null;
	return ['left', 'right', 'operand', 'test', 'then', 'otherwise']
		.some((k) => hasUnitLiteral(node[k]))
		|| (node.args ?? []).some(hasUnitLiteral);
}

/**
 * Converts a unit literal to the unit of what it is written against.
 *
 * `p1 + 1000[mm]` with `p1` in metres is 1 + 1, not 1 + 1000: the literal is
 * scaled by the factor between the two units and means a metre from then on.
 * The rewrite happens wherever the checker demands that two units *agree* --
 * `+` and `-`, a comparison, and the arguments of `min`, `max` and `if` --
 * because that is exactly where there is a unit to convert to. A product has
 * no such target (`Depth * 5[cm]` could be metres or centimetres depending on
 * nothing in the expression), so a literal there goes on meaning what it says.
 *
 * **The target is the sibling, never a canonical unit**, and that is what
 * makes this sound. Scaling `5[cm]` to metres because centimetres are not SI
 * would break every model whose lengths are in centimetres -- and break it
 * silently, since both sides would still agree on the dimension and the
 * checker would have nothing to report. Scaling it to whatever it is being
 * added to is right whatever the model's units are.
 *
 * Bottom-up, so an inner sum is converted before an outer one reads its unit.
 * The AST is rewritten in place: every caller parses its own.
 *
 * @param {object} ast  from `parse`
 * @param {(name: string) => Dim|null} unitOf  a referenced block's unit
 * @param {Dim|null} timeDim  the simulation's time unit
 * @returns {{converted: Array<{value: number, from: string, to: string, now: number}>,
 *   unconverted: Array<{value: number, unit: string}>}} what was scaled, and
 *   the literals that had nothing to be scaled against
 */
export function scaleLiterals(ast, unitOf, timeDim) {
	const converted = [];
	const unconverted = [];
	if (!hasUnitLiteral(ast)) return { converted, unconverted };

	// The same rule the checker applies, asked of a sub-expression rather than
	// written out a second time: a clash deeper down means the unit of this
	// piece is not known, which is the same answer as not knowing it.
	const dimOf = (node) => {
		try {
			return equationUnit(node, unitOf, timeDim).dim;
		} catch {
			return null;
		}
	};
	const literal = (n) => n?.type === 'num' && n.unit != null && !n.dim;

	/** One literal against one sibling, where the sibling settles the unit. */
	const against = (lit, other) => {
		const want = dimOf(other);
		const here = dimOf(lit);
		if (!here || here.isOne) return;
		if (!want) {
			// Nothing to convert to. Worth saying: the same equation would
			// convert the moment somebody typed a unit on the other side, and
			// a number that quietly means one thing now and another then is
			// the one trap this feature can lay.
			unconverted.push({ value: lit.value, unit: lit.unit });
			return;
		}
		if (!want.sameKind(here) || want.equals(here)) return;
		const factor = here.factor(want);
		converted.push({ value: lit.value, from: String(here), to: String(want), now: lit.value * factor });
		lit.value *= factor;
		lit.dim = want;
	};

	/** Every literal among these siblings, against the first settled unit. */
	const reconcile = (nodes) => {
		const lits = nodes.filter(literal);
		if (!lits.length) return;
		const anchor = nodes.find((n) => !literal(n) && dimOf(n)) ?? nodes.find((n) => n !== lits[0]);
		for (const lit of lits) {
			if (lit === anchor) continue;
			against(lit, anchor);
		}
	};

	const walk = (node) => {
		if (!node || typeof node !== 'object') return;
		for (const key of ['left', 'right', 'operand', 'test', 'then', 'otherwise']) {
			if (node[key]) walk(node[key]);
		}
		for (const arg of node.args ?? []) walk(arg);
		// ...and only then this node, so an inner sum has settled its unit
		// before an outer one is asked what that unit is.
		if (node.type === 'binary' && AGREE_OPS.has(node.op)) reconcile([node.left, node.right]);
		else if (node.type === 'cond') reconcile([node.then, node.otherwise]);
		else if (node.type === 'call' && AGREE_CALLS.has(node.name)) {
			// `if(test, a, b)` agrees on its two results, not on its test.
			reconcile(node.name === 'if' || node.name === 'ifelse' ? (node.args ?? []).slice(1) : (node.args ?? []));
		}
	};
	walk(ast);
	return { converted, unconverted };
}
