/**
 * User-defined functions: a body written once, called from any equation.
 *
 * In the desktop tools these are compiled code. What comes across is metadata -- a name,
 * a source type and a file name -- pointing at a class in the project archive:
 *
 *     public class function1 extends AbstractUserDefinedFunction {
 *         public double function(double ... params) { ... }
 *     }
 *
 * which the code generator instantiates once per run and every call site
 * compiles to `Model._function1.function(a, b)`. None of that can come across:
 * the browser cannot run compiled code from the file, and a tool that did would be running
 * arbitrary code out of a file somebody sent you.
 *
 * What comes across is the *capability*: a modeller who needs the same
 * arithmetic in fifteen equations writes it once and calls it. So a function
 * here is a body in this tool's own equation language, with named parameters:
 *
 *     { "name": "TR_adv", "parameters": ["LAI", "width", "wind"],
 *       "equation": "0.5 * LAI * sqrt(wind / width)" }
 *
 * and `TR_adv(LAI_ter, 0.02, u)` anywhere in the model means that body with
 * those three expressions substituted in.
 *
 * **The body may read the model, and does.** Ecolego has two flavours of this
 * and the one real models use is the second: an `Expression` that implements
 * `IArgumentable`, whose `<argument>` elements name values the equation may
 * use *beside* everything it can already see. one small test model has
 *
 *     ADV(position, kd) = interpolationUseEndValues(
 *         DegradedFcn, position, Q1, position + z_barrier/N, Q2) * kd
 *
 * called as `ADV(index[_source_]/N, Kd)` from four transfer rates --
 * `DegradedFcn`, `Q1`, `Q2`, `z_barrier` and `N` are blocks, and a version
 * that could not read them would make the caller pass five more arguments.
 *
 * A name in the body means what it meant *there*: a function sits in a
 * sub-system like any other block, and its body reads that sub-system's names
 * however deep the call site is. The inliner stamps each reference with that
 * scope and the builder's locator reads the stamp, which is what keeps
 * `Water` in a body written at the top level from becoming `NF.Water` when it
 * is called from inside `NF`.
 *
 * A parameter may shadow a block -- Ecolego's `ADV(position, kd)` has a `kd`
 * of its own -- so the stamp goes on everything that is *not* a parameter,
 * and the parameters are substituted before anything looks a name up.
 *
 * A body is evaluated at the index of whatever calls it. Nothing else is
 * possible with inlining, and nothing else is meaningful: the body is written
 * once and the caller is the one standing at an index.
 *
 * Inlining rather than emitting a JS function is what makes everything else
 * work unchanged: the dependency order, the index machinery, the unit check
 * and -- the one that would be real work otherwise -- the analytic Jacobian
 * all see an ordinary expression, because by the time they look, that is what
 * it is.
 */

import { parse, ParseError } from '../parser/parser.js';
import { qualifiedName, resolveReference } from '../domain/systems.js';

/** A function that cannot be built. The builder reports it as a BuildError. */
export class FunctionError extends Error {
	constructor(message, blockName = null) {
		super(message);
		this.name = 'FunctionError';
		this.blockName = blockName;
	}
}

/** How deep one call may nest before we call it a runaway. */
const MAX_DEPTH = 32;

/**
 * The functions a project declares, parsed and ready to inline.
 *
 * @param {object} project a `Project` or a raw model
 * @returns {{
 *   size: number,
 *   has: (name: string) => boolean,
 *   get: (name: string) => object|null,
 *   inline: (ast: object, owner?: string) => object,
 * }}
 */
export function userFunctions(project, { callable = null } = {}) {
	const defs = new Map();
	const declared = new Set(
		(project?.functions ?? []).filter((f) => f?.name).map((f) => qualifiedName(f)),
	);
	/** The function a call names, seen from `system`: the ordinary rule. */
	const resolve = (written, system) => {
		const q = resolveReference(written, system ?? '', (n) => declared.has(n));
		return q && declared.has(q) ? q : null;
	};

	for (const f of project?.functions ?? []) {
		if (!f?.name) continue;
		const name = qualifiedName(f);
		const parameters = (f.parameters ?? []).map((p) => String(p));
		const text = String(f.equation ?? '').trim();
		if (!text) {
			// A function with no body is a real state to be in -- it is what
			// an import makes of a call to a function whose body did not come
			// across -- so it loads, appears in the panels and is reported.
			// It is only *running* that is impossible.
			throw new FunctionError(
				`'${name}' has no body yet. Write what it works out to in terms of `
				+ `${parameters.length
					? `its parameters (${parameters.join(', ')})`
					: 'numbers and the built-in functions'}, `
				+ 'or delete it and the equations that call it.', name,
			);
		}
		let ast;
		try {
			// A body may call another function, a lookup table read at an
			// argument, or a transport operation -- whatever the caller
			// supplies as callable, plus the functions themselves.
			ast = parse(text, {
				calls: (n) => !!resolve(n, f.system ?? '') || !!callable?.(n, f.system ?? ''),
			});
		} catch (e) {
			if (e instanceof ParseError) {
				throw new FunctionError(
					`${e.message} in the body of '${name}' (at character ${e.position + 1})`, name,
				);
			}
			throw e;
		}
		// Every name in the body that is not a parameter is a block, read in
		// the function's own sub-system. `scope` is what says so once the body
		// has been moved into somebody else's equation: see `makeLocator` in
		// ./builder.js.
		defs.set(name, {
			name, parameters, block: f,
			ast: scoped(ast, new Set(parameters), f.system ?? ''),
		});
	}

	/**
	 * `ast` with every call of a user-defined function replaced by its body.
	 *
	 * @param ast     the expression, straight from the parser
	 * @param owner   whose equation it is, for the message
	 * @param system  the sub-system it was written in, which is how a bare
	 *                name in it finds the function it means
	 */
	const inline = (ast, owner = null, system = '') => expand(
		ast, { defs, resolve }, owner, system, [], 0,
	);

	return {
		size: defs.size,
		has: (qname) => defs.has(qname),
		get: (qname) => defs.get(qname) ?? null,
		resolve,
		names: () => [...defs.keys()],
		inline,
	};
}

/**
 * The body, with every reference that is not a parameter stamped with the
 * scope it was written in.
 *
 * Stamped rather than rewritten to a qualified name, because a root block's
 * qualified name is its bare name and a bare name is exactly what a
 * sub-system can shadow.
 */
function scoped(ast, params, system) {
	if (!ast || typeof ast !== 'object') return ast;
	switch (ast.type) {
		case 'ref':
			return params.has(ast.name) ? ast : { ...ast, scope: system };
		case 'unary':
			return { ...ast, operand: scoped(ast.operand, params, system) };
		case 'binary':
			return {
				...ast,
				left: scoped(ast.left, params, system),
				right: scoped(ast.right, params, system),
			};
		case 'cond':
			return {
				...ast,
				test: scoped(ast.test, params, system),
				then: scoped(ast.then, params, system),
				otherwise: scoped(ast.otherwise, params, system),
			};
		case 'call':
			return { ...ast, args: (ast.args ?? []).map((a) => scoped(a, params, system)) };
		default:
			return ast;
	}
}

/** One pass of substitution, deepest call first. */
function expand(ast, table, owner, system, stack, depth) {
	if (!ast || typeof ast !== 'object') return ast;
	if (depth > MAX_DEPTH) {
		throw new FunctionError(
			`'${stack[stack.length - 1] ?? owner}' nests function calls more than `
			+ `${MAX_DEPTH} deep.`, owner,
		);
	}
	const go = (node) => expand(node, table, owner, system, stack, depth);
	switch (ast.type) {
		case 'ref':
		case 'num':
			return ast;
		case 'unary':
			return { ...ast, operand: go(ast.operand) };
		case 'binary':
			return { ...ast, left: go(ast.left), right: go(ast.right) };
		case 'cond':
			return {
				...ast, test: go(ast.test), then: go(ast.then), otherwise: go(ast.otherwise),
			};
		case 'call': {
			const args = (ast.args ?? []).map(go);
			// Which function a call names is the ordinary resolution rule --
			// a bare name in a sub-system means that sub-system's, then the
			// top level's -- and a reference the inliner has already moved
			// carries the scope it came from.
			const q = table.resolve(ast.name, ast.scope ?? system);
			const fn = q ? table.defs.get(q) : null;
			// A built-in, a lookup table read at an argument, a transport
			// operation: not ours, and already checked by whoever owns it.
			if (!fn) return { ...ast, args };
			if (stack.includes(fn.name)) {
				throw new FunctionError(
					`'${fn.name}' calls itself (${[...stack, fn.name].join(' \u2192 ')}). `
					+ 'A function is worked out where it is called, so there would be '
					+ 'nothing to stop at.', stack[0] ?? owner,
				);
			}
			if (args.length !== fn.parameters.length) {
				throw new FunctionError(
					`'${fn.name}' takes ${fn.parameters.length} argument`
					+ `${fn.parameters.length === 1 ? '' : 's'}`
					+ `${fn.parameters.length ? ` (${fn.parameters.join(', ')})` : ''}, `
					+ `but is called with ${args.length}.`, owner,
				);
			}
			const bound = new Map(fn.parameters.map((p, i) => [p, args[i]]));
			const body = substitute(fn.ast, bound, fn.name);
			// The body may call another function, from its own sub-system;
			// those are expanded with this one on the stack, which is what
			// catches a cycle.
			return expand(
				body, table, owner, fn.block?.system ?? '', [...stack, fn.name], depth + 1,
			);
		}
		default:
			return ast;
	}
}

/** The body, with each parameter replaced by the expression passed for it. */
function substitute(ast, bound, fnName) {
	if (!ast || typeof ast !== 'object') return ast;
	switch (ast.type) {
		case 'ref': {
			const arg = bound.get(ast.name);
			if (arg === undefined) return ast;
			if ((ast.indices ?? []).length) {
				// `x[Cs-137]` where x is a parameter: an argument is one value
				// worked out at the call site, not a block with indices to
				// pick from. The caller writes the index instead.
				throw new FunctionError(
					`'${ast.name}[…]' asks for an index of a parameter of '${fnName}'. `
					+ 'An argument is a single value, already worked out where the '
					+ 'function is called: put the index there instead.', fnName,
				);
			}
			return arg;
		}
		case 'unary':
			return { ...ast, operand: substitute(ast.operand, bound, fnName) };
		case 'binary':
			return {
				...ast,
				left: substitute(ast.left, bound, fnName),
				right: substitute(ast.right, bound, fnName),
			};
		case 'cond':
			return {
				...ast,
				test: substitute(ast.test, bound, fnName),
				then: substitute(ast.then, bound, fnName),
				otherwise: substitute(ast.otherwise, bound, fnName),
			};
		case 'call':
			return { ...ast, args: (ast.args ?? []).map((a) => substitute(a, bound, fnName)) };
		default:
			return ast;
	}
}
