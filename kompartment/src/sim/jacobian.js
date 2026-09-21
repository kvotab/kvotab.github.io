/**
 * The Jacobian df/dy, generated from the model rather than probed with finite
 * differences.
 *
 * A compartment model's Jacobian is almost all zeros -- a compartment couples
 * only to the compartments it exchanges with, plus its own decay chain -- and
 * both stiff solvers want it. The pattern is worth stating rather than
 * rediscovering: without it, ros23 spends n extra evaluations of f per step
 * and ndf the same per refresh, all to work out a structure the model
 * already knows.
 *
 * Three things are generated here, from the same offsets the derivative
 * function itself uses (`makeLocator` in builder.js, passed in):
 *
 *   pattern   which (row, column) pairs can be non-zero. Structural, read off
 *             the equations -- never off a numerical probe, which would call a
 *             coefficient that happens to be zero at t0 a structural zero and
 *             then quietly drop it for the rest of the run.
 *   jvp       J*v for a seed vector v, by forward-mode differentiation of the
 *             generated code. Exact: no perturbation size to choose, no
 *             cancellation, and a staircase function contributes 0 rather than
 *             the 1e8 artefact a difference across its jump reports.
 *   colouring columns that share no row can be seeded together, so the whole
 *             matrix costs one jvp per colour -- typically five or ten, against
 *             one f per column.
 *
 * The pay-off is the sparsity, not the exactness: an exact dense Jacobian costs
 * about what the finite-difference one costs. What the pattern buys is the
 * colouring here and the sparse factorisation in ../ode/sparse.js.
 */

import {
	emitWithTangent, makeTape, tapePrelude, buildFunction, NoDerivative,
} from '../parser/compile.js';
import { schemeOf } from '../domain/availability.js';
import { FUNCTIONS, FUNCTION_ALIASES } from '../parser/functions.js';
import { resolveReference } from '../domain/systems.js';
import { FARF_EQUATION_KEYS } from '../domain/farfield.js';
import { hazardCode } from '../domain/wastepackage.js';

/**
 * How many temporaries the tangent function may hoist.
 *
 * Generated tangent statements are linear in the number of AST nodes, but a
 * model that unrolls per index tuple multiplies that by the tuple count. Past
 * some size the browser spends longer compiling the function than the finite
 * differences would have cost, so the analytic path declines rather than
 * hanging the tab.
 *
 * It used to be the stack that decided, and this number chased it. A hoisted
 * temporary was a `const` in one function body, V8 gives every local a
 * register in the interpreter frame, and a large enough function could not be
 * *called*: it compiled, and the RangeError arrived on the first call, from
 * inside the solver. Worse, how large "large enough" is depends on where the
 * code runs -- measured in this browser, a **worker**, which is where runs
 * actually happen, cannot call a function of 62,000 locals, while the page
 * manages 100,000 and Node a little more. So the real ceiling was a worker's
 * stack, and it was low enough to deny model C (8,427 states,
 * 67,578 statements) its analytic Jacobian and leave it differencing a dense
 * 8,427-square matrix -- about a day's arithmetic, against two minutes.
 *
 * The temporaries are slots in an array now rather than locals -- see
 * `tapePrelude` in ../parser/compile.js -- so the frame holds a handful of
 * registers whatever the model's size, and the stack has stopped being the
 * question. What is left is compile time and the cost of a call, both mild:
 * measured in a worker, 300,000 slots compile in 176 ms and run in 10 ms,
 * where 68,000 locals could not be called at all.
 *
 * So the limit is about work now rather than about frames, and sits where a
 * Jacobian of fifteen colours still costs about a tenth of a second to form.
 * `smokeTest` below remains the real guard: a number measures one shape of
 * bigness, and another engine is not this one.
 */
const MAX_STATEMENTS = 250000;

/**
 * And how many lines it may emit at all.
 *
 * `MAX_STATEMENTS` counts hoisted temporaries, and an equation simple enough
 * to need none -- `y[3]`, a bare reference, a literal -- hoists nothing. A
 * model of a million such slots emits two million lines with a count of zero,
 * so the limit above never fires: forty megabytes of source, four seconds to
 * compile, and no analytic Jacobian worth the wait. This is the other half of
 * the same guard, in lines rather than locals.
 */
const MAX_LINES = 300000;

/**
 * How deep the smoke test calls from.
 *
 * Comfortably past the couple of dozen frames the solver adds. It matters less
 * now that the temporaries are not on the stack, and it costs nothing to keep:
 * the engine this runs in is whichever one the page was opened in, and a guard
 * that proves the function can be entered from depth proves it for all of
 * them.
 */
const SMOKE_DEPTH = 200;

/** How many passes the dependency sets get to settle before we give up. */
const MAX_PATTERN_PASSES = 12;

/**
 * A name, safe to put inside a `//` comment.
 *
 * A line break in a block name would end the comment and leave the rest of the
 * name to be compiled as source. Nothing in the corpus can do it -- project.js
 * gates names through NAME_RE -- but the generated text is a program, and a
 * program that interpolates an outside string wants two locks rather than one.
 * builder.js has the twin of this; it is not exported, so this is a copy
 * rather than an import.
 */
const inComment = (text) => String(text).replace(/[\r\n\u2028\u2029]+/g, ' ');

class Refused extends Error {
	constructor(message) {
		super(message);
		this.name = 'JacobianRefused';
	}
}

/**
 * Proves the tangent function can be called at all.
 *
 * A generated function large enough that V8 cannot fit its frame on the stack
 * still *compiles*: `new Function` returns it, and the RangeError arrives on
 * the first call -- which would be from inside the solver, mid-run, as a
 * failure with nothing to do with the model. One call with a zero seed here
 * turns that into what it should be: the analytic path declining, and finite
 * differences instead.
 *
 * Only a RangeError counts. The equations are being evaluated at y = 0, which
 * a model is entitled to dislike -- a division, a log, a lookup outside its
 * range -- and none of that says anything about whether the function can run.
 */
function smokeTest(rawJvp, b) {
	const { nstate, nalg, runtime } = b;
	const { P, DEC, MAPS, TAB, MEM, FARF, ctx } = runtime;
	const wasT = ctx.t;
	const call = () => rawJvp(
		FUNCTIONS, ctx,
		new Float64Array(nstate), new Float64Array(nstate), new Float64Array(nstate),
		P, new Float64Array(Math.max(1, nalg)), new Float64Array(Math.max(1, nalg)),
		DEC, MAPS, TAB, MEM, FARF,
	);
	// From depth, not from here. Whether a function of this size can be
	// entered depends on how much stack is left when it is: the same function
	// that runs at the top level can fail two hundred frames down, and the
	// solver calls this one from inside its own Newton iteration. Testing it
	// at the top level answers an easier question than the one being asked.
	const deep = (d) => (d > 0 ? deep(d - 1) : call());
	try {
		deep(SMOKE_DEPTH);
	} catch (e) {
		if (e instanceof RangeError) {
			throw new Refused(
				'the generated tangent function is too large for this engine to call '
				+ `(${e.message})`,
			);
		}
		// Anything else is the model's own arithmetic at y = 0, which is not a
		// reason to decline: the real call is at a real state.
	} finally {
		ctx.t = wasT;
	}
}

/**
 * Proves the matrix it produces is made of numbers.
 *
 * An exact derivative is allowed to be infinite. `d/dA sqrt(A)` at A = 0 is
 * infinite and the rule that says so is right: a transfer of `k * sqrt(A)` out
 * of an empty compartment really does have an unbounded slope there. But a
 * column of Infinity is not a matrix anything can factorise. ros23 formed
 * I - h*d*J, got NaN out of it, and reported "the state or its derivative
 * became non-finite at t=0"; ndf reduced its step to 8e-323 and gave up on
 * the tolerances. Both messages blame the model, and the model is fine --
 * dp45, which differences nothing and forms no iteration matrix, integrates
 * it without complaint.
 *
 * So the analytic path declines here, exactly as it declines a function with
 * no derivative rule, and the solvers difference instead: a difference quotient
 * across a square root is large and finite, which is a bad approximation of an
 * infinite slope but a usable one.
 *
 * The probe is at the run's own initial state and start time -- the builder
 * hands `initialState` over for exactly this -- since that is where the
 * singularities live: sqrt(0), log(0), a compartment that has not been filled
 * yet, and an empty compartment is the commonest initial value in the corpus.
 * Probed at y = 0 instead, as a first version did, a model that starts with a
 * hundred becquerels in every compartment and takes a square root of one of
 * them lost its analytic Jacobian to a state it is never in.
 *
 * Once, at build time, so the status line can say why the run is
 * differencing. The step loop has its own, quieter guard: `evaluate` answers
 * null when a matrix it has just formed has a non-finite entry -- a
 * compartment drained to exactly zero mid-run does that to a square root --
 * and the solvers difference for that one call. See `evaluate`.
 */
function refuseNonFinite(evaluate, b) {
	const { nstate, runtime, initialState } = b;
	const { ctx } = runtime;
	const wasT = ctx.t;
	let values;
	try {
		const y0 = initialState ? initialState() : new Float64Array(nstate);
		values = evaluate(ctx.startTime, y0);
	} catch {
		// As in smokeTest: the model's own arithmetic at the start says
		// nothing about whether the matrix is usable at a real state.
		return;
	} finally {
		ctx.t = wasT;
	}
	if (values === null) {
		throw new Refused(
			'the generated Jacobian has a non-finite entry at the starting state '
			+ '(an exact derivative may be infinite where sqrt or log meets an '
			+ 'empty compartment), and an infinite entry is not a matrix a solver '
			+ 'can factorise',
		);
	}
}

/**
 * @returns {object} either { available: true, ... } or { available: false, reason }
 */
export function buildJacobian(b) {
	// A transfer whose flux is scaled by an availability is not `donor * rate`
	// any more -- it is `g(donor) * rate` with `g` the scheme's own function of
	// the inventory, and for a *shared* scheme `g` reads the inventories of
	// every other member of the group, which puts entries in this matrix that
	// the sparsity pattern below does not know about.
	//
	// Emitting the wrong matrix is far worse than emitting none. It was tried:
	// the flux was right and the matrix was the linear one, so above a
	// solubility limit Newton was told the flux still moved with the inventory
	// when it no longer did, and `examples/biosphere.json` ran to a million
	// steps and stopped -- at the moment the inventory crossed the limit,
	// whatever the limit was. The solvers difference what they are not given,
	// which is slower and right.
	//
	// The way to lift this is to give each scheme a `g` and a `g'` and to widen
	// the pattern for the shared ones; the shape of that is in
	// ../domain/availability.js, and it is a piece of work rather than a line.
	// The mass-balance audit appends budget states that accumulate every
	// flux, and those rows are not in the pattern below. Differencing is the
	// honest answer for an audit run, which is a run made to check the model,
	// not to be fast.
	if (b.project?.simulation?.mass_balance) {
		return {
			available: false,
			reason: 'The mass-balance audit is on, which adds budget states the generator '
				+ 'does not differentiate. The solver works out df/dy by differencing instead.',
		};
	}
	const limited = (b.project?.transfers ?? []).find((t) => schemeOf(t));
	if (limited) {
		return {
			available: false,
			reason: `'${limited.name}' scales its flux by an availability, which makes it `
				+ 'non-linear in the inventory. The solver works out df/dy by differencing '
				+ 'instead, which is slower and gives the same answer.',
		};
	}
	try {
		return generate(b);
	} catch (e) {
		if (e instanceof NoDerivative || e instanceof Refused) {
			return { available: false, reason: e.message };
		}
		throw e;
	}
}

function generate(b) {
	const { nstate, nalg, runtime } = b;

	// --- the sparsity pattern -------------------------------------------------
	const { algSource, rowSource } = patternSource(b);
	const rawAlgPattern = buildFunction(
		['SX', 'ADD', 'MAPS', 'FARF'], algSource, 'patternAlg',
	);
	const rawRowPattern = buildFunction(
		['SX', 'PAT', 'MAPS', 'DEC', 'FARF'], rowSource, 'patternRows',
	);

	const SX = Array.from({ length: Math.max(1, nalg) }, () => new Set());
	const ADD = (dst, src) => { for (const c of src) dst.add(c); };
	// A block may reference itself at another index -- `E[Cs-137]` inside E --
	// which the topological order does not resolve, so the sets are iterated
	// until they stop growing rather than filled in one pass.
	let previous = -1;
	for (let pass = 0; pass < MAX_PATTERN_PASSES; pass++) {
		rawAlgPattern(FUNCTIONS, runtime.ctx, SX, ADD, runtime.MAPS, runtime.FARF);
		let total = 0;
		for (const s of SX) total += s.size;
		if (total === previous) break;
		previous = total;
		if (pass === MAX_PATTERN_PASSES - 1) {
			throw new Refused('the algebraic dependencies did not settle');
		}
	}

	const cols = Array.from({ length: nstate }, () => new Set());
	const PAT = (row, col) => { cols[col].add(row); };
	// Every diagonal entry is present whether or not the model puts one there:
	// the solvers factorise I - h*J, so the identity contributes it anyway, and
	// a pattern that omits it would make the iteration matrix's structure
	// differ from the Jacobian's.
	for (let i = 0; i < nstate; i++) cols[i].add(i);
	rawRowPattern(
		FUNCTIONS, runtime.ctx, SX, PAT, runtime.MAPS,
		runtime.DEC, runtime.FARF,
	);

	const pattern = toCSC(cols, nstate);

	// --- one seed per colour --------------------------------------------------
	const groups = colourColumns(pattern);

	// --- the tangent function -------------------------------------------------
	// The column sets go with it: a couple of the rules below have to know
	// whether a quantity depends on the state at all, and that is what `SX`
	// says.
	b.SX = SX;
	const { source: jvpSource, slots } = jvpSourceFor(b);
	const rawJvp = buildFunction(
		['y', 'v', 'dout', 'P', 'X', 'dX', 'DEC', 'MAPS', 'TAB', 'MEM', 'FARF'],
		jvpSource, 'jvp',
	);
	// The scratch the tangent function hoists into, allocated once for the
	// life of the system rather than grown a slot at a time on the first call.
	runtime.ctx.__tape = new Array(slots);
	smokeTest(rawJvp, b);

	// --- is it the same matrix at every point? --------------------------------
	const constant = isConstant(b, SX);

	// --- evaluation -----------------------------------------------------------
	const {
		P, X, DEC, MAPS, TAB, MEM, FARF, ctx,
	} = runtime;
	const dX = new Float64Array(Math.max(1, nalg));
	const seed = new Float64Array(nstate);
	const dout = new Float64Array(nstate);
	const values = new Float64Array(pattern.nnz);
	const { colPtr, rowIdx } = pattern;

	/**
	 * The Jacobian at (t, y), as the values of the pattern -- or null when
	 * the matrix it just formed has an entry that is not a number.
	 *
	 * An exact derivative is allowed to be infinite: `d/dA sqrt(A)` at A = 0
	 * is, and the rule that says so is right. But Infinity in one entry makes
	 * I - h*J unfactorisable, and a compartment can reach exactly zero in the
	 * middle of a run -- the non-negative constraint pins it there -- long
	 * after the build-time probe (`refuseNonFinite`) approved the start. So
	 * the caller is told there is no matrix this time and differences instead,
	 * which is what it would have done had there been no analytic Jacobian at
	 * all; a difference quotient across the singularity is large and finite,
	 * a poor approximation of an infinite slope but a usable one. The scan is
	 * one pass over the non-zeros, a few per cent of forming them.
	 */
	const evaluate = (t, y) => {
		ctx.t = t;
		for (const group of groups) {
			for (const j of group) seed[j] = 1;
			rawJvp(FUNCTIONS, ctx, y, seed, dout, P, X, dX, DEC, MAPS, TAB, MEM, FARF);
			for (const j of group) {
				seed[j] = 0;
				for (let k = colPtr[j]; k < colPtr[j + 1]; k++) values[k] = dout[rowIdx[k]];
			}
		}
		for (let k = 0; k < values.length; k++) {
			if (!Number.isFinite(values[k])) return null;
		}
		return values;
	};

	const evaluateDense = (t, y, J) => {
		if (evaluate(t, y) === null) return null;
		// Cleared first: only the pattern's entries are written, and a caller
		// reusing a matrix would otherwise keep whatever was outside it.
		for (let i = 0; i < nstate; i++) J[i].fill(0);
		for (let j = 0; j < nstate; j++) {
			for (let k = colPtr[j]; k < colPtr[j + 1]; k++) J[rowIdx[k]][j] = values[k];
		}
		return J;
	};

	// Two things have to be true of this function, and neither is visible in
	// the source: that it can be entered at all (smokeTest, above) and that
	// what it returns is finite.
	refuseNonFinite(evaluate, b);

	/**
	 * `J * v` in one pass, for any direction `v`.
	 *
	 * This is what the tangent function *is* -- `evaluate` above only calls it
	 * once per colour group with a seed of ones and reads the columns out. A
	 * caller that wants the product rather than the matrix can have it for the
	 * cost of one call instead of one per colour, which for forward sensitivity
	 * analysis is the difference between a tangent per parameter and a whole
	 * Jacobian per step: 158 ms against 3 on model A.
	 *
	 * `out` is filled and returned; it may be the caller's own array.
	 */
	const jvp = (t, y, v, out = new Float64Array(nstate)) => {
		ctx.t = t;
		out.fill(0);
		rawJvp(FUNCTIONS, ctx, y, v, out, P, X, dX, DEC, MAPS, TAB, MEM, FARF);
		return out;
	};

	return {
		available: true,
		pattern,
		groups,
		constant,
		evaluate,
		jvp,
		evaluateDense,
		values,
		nnz: pattern.nnz,
		colours: groups.length,
		density: pattern.nnz / (nstate * nstate),
		source: jvpSource,
	};
}

/**
 * `df/dp * w` in one pass: the driving term of the forward sensitivity
 * equations, differentiated rather than differenced.
 *
 * `S = dy/dp` satisfies `S' = J*S + df/dp`. `J*S` has always been one `jvp`
 * call; `df/dp` was a one-sided difference -- one extra evaluation of the whole
 * derivative per parameter per step, plus the invariant pass to carry the
 * perturbed parameter into the algebra that was worked out from the old one.
 * That was the single approximation left in ../sim/localsens.js and it is gone:
 * this is the same generator, seeded on the parameters instead of on the state.
 *
 * **Why it is a separate call rather than a flag on `jvp`.** The two are asked
 * for at different rates -- `J*S` once per sensitivity block per step, `df/dp`
 * once per *parameter* per step -- and the solvers only ever want the first.
 * A model that cannot produce this one still gets its Jacobian.
 *
 * **What it refuses, and why.** Three blocks carry their own runtime pieces
 * that know how to differentiate along the state and not along a parameter --
 * a far-field path's transport matrix, a waste package's hazard, a disruptive
 * event's rate. Writing the parameter half of each is a piece of work rather
 * than a line, and a wrong matrix is far worse than none, so a model with any
 * of them is refused here and differenced by the caller exactly as before.
 *
 * @returns {{available: true, pvp: Function, nparam: number}
 *   | {available: false, reason: string}}
 */
export function buildParamTangent(b) {
	const { nstate, nalg, nparam, runtime } = b;
	if (!(nparam > 0)) {
		return { available: false, reason: 'the model holds no parameters' };
	}
	const has = (what, list) => ((list ?? []).length
		? `a ${what}, whose derivative along a parameter is not generated`
		: null);
	const refusal = has('far-field path', b.farfLayout)
		?? has('waste package', b.wasteLayout)
		?? has('disruptive event', b.disruptionLayout);
	if (refusal) {
		return { available: false, reason: `the model has ${refusal}` };
	}

	try {
		// The parameter columns of every algebraic slot, by the same walk that
		// fills the state columns. It is what says a quantity is structurally
		// still along a parameter -- and what the delay refusal below reads.
		const { algSource } = patternSource(b, { collect: 'param' });
		const rawAlgPattern = buildFunction(
			['SX', 'ADD', 'MAPS', 'FARF'], algSource, 'patternAlgParam',
		);
		const SP = Array.from({ length: Math.max(1, nalg) }, () => new Set());
		const ADD = (dst, src) => { for (const c of src) dst.add(c); };
		let previous = -1;
		for (let pass = 0; pass < MAX_PATTERN_PASSES; pass++) {
			rawAlgPattern(FUNCTIONS, runtime.ctx, SP, ADD, runtime.MAPS, runtime.FARF);
			let total = 0;
			for (const s of SP) total += s.size;
			if (total === previous) break;
			previous = total;
			if (pass === MAX_PATTERN_PASSES - 1) {
				throw new Refused('the algebraic dependencies did not settle');
			}
		}

		// `SX` is the name the generator reads the column sets under, and for
		// this pass the parameter sets are what "does this move?" means. The
		// state sets are put back before returning, since the caller holds the
		// same object and the Jacobian's own rules read them.
		const keep = b.SX;
		let source;
		try {
			b.SX = SP;
			source = jvpSourceFor(b, { seed: 'param' });
		} finally {
			b.SX = keep;
		}
		const raw = buildFunction(
			['y', 'v', 'dout', 'P', 'X', 'dX', 'DEC', 'MAPS', 'TAB', 'MEM', 'FARF'],
			source.source, 'pvp',
		);
		// The hoisted temporaries share one array with the Jacobian's tangent:
		// the two never run inside one another, and the prelude grows it if it
		// is short. Sized here so the first call does not.
		if ((runtime.ctx.__tape?.length ?? 0) < source.slots) {
			runtime.ctx.__tape = new Array(source.slots);
		}

		const { P, X, DEC, MAPS, TAB, MEM, FARF, ctx } = runtime;
		const dX = new Float64Array(Math.max(1, nalg));

		/**
		 * `(df/dp) * w` at (t, y), with the state held fixed.
		 *
		 * `out` is filled and returned; it may be the caller's own array.
		 */
		const pvp = (t, y, w, out = new Float64Array(nstate)) => {
			ctx.t = t;
			out.fill(0);
			raw(FUNCTIONS, ctx, y, w, out, P, X, dX, DEC, MAPS, TAB, MEM, FARF);
			return out;
		};

		// The same two questions the Jacobian's own tangent has to answer:
		// that the function can be entered at all, and that what it returns is
		// a number. A seed of ones exercises every parameter at once, at the
		// state the run starts from.
		const seed = new Float64Array(nparam).fill(1);
		const wasT = runtime.ctx.t;
		let probe;
		try {
			const y0 = b.initialState ? b.initialState() : new Float64Array(nstate);
			probe = pvp(runtime.ctx.startTime, y0, seed);
		} catch (e) {
			// The model's own arithmetic at the starting point, which says
			// nothing about whether the function is usable at a real state --
			// exactly as `smokeTest` reads it for the Jacobian.
			probe = null;
		} finally {
			runtime.ctx.t = wasT;
		}
		if (probe) {
			for (let i = 0; i < probe.length; i++) {
				if (!Number.isFinite(probe[i])) {
					return {
						available: false,
						reason: 'df/dp has a non-finite entry at the starting state, and a '
							+ 'driving term that is not a number is not one to integrate',
					};
				}
			}
		}
		return { available: true, pvp, nparam };
	} catch (e) {
		if (e instanceof NoDerivative || e instanceof Refused) {
			return { available: false, reason: e.message };
		}
		throw e;
	}
}

// --- the sparsity pattern ---------------------------------------------------

/**
 * Two generated functions: one filling each algebraic slot's set of state
 * columns, one turning those into (row, column) pairs. They are separate
 * because the first is run repeatedly to a fixed point and the second must run
 * exactly once.
 */
function patternSource(b, opts = {}) {
	const {
		project, space, algebraic, stateByName, algByName,
		makeLocator, mapIndex, emitLoop, emitByEquation, stateOffsetExpr, tupleByList, decaying,
		farfLayout, pathByName, farfInletExpr, dydtSlots = [], wasteLayout = [], disruptionLayout = [],
	} = b;

	// Which columns are being collected. `state` fills each algebraic slot's
	// set of *state* columns, which is what df/dy is read from; `param` fills
	// its set of *parameter* columns, which is what df/dp is read from. The
	// walk is the same one either way -- the only difference is which kind of
	// reference counts as a column and which is passed over -- so it is one
	// function rather than two that would drift.
	const wantParams = opts.collect === 'param';

	const { recorders } = b;
	const algLines = [];
	for (const a of algebraic) {
		// A path's release is read off its own cells with rates that may
		// themselves depend on the state, so both go into its column set --
		// the runtime object knows where its cells are and this does not.
		if (a.kind === 'farfield') {
			algLines.push(`\tFARF[${a.farfIndex}].releasePattern(SX);`);
			continue;
		}
		// Waste packages. The hazard reads the clock and the failure settings,
		// so it follows the state only through them; the release reads the
		// two inventories, the hazard, the instant-release fraction and the
		// degradation rate. See ../domain/wastepackage.js and the builder.
		if (a.kind === 'event:lambda') {
			// The expected-value rate follows its rate and window slots.
			const D = a.event;
			const from = Object.values(D.setting);
			if (from.length) {
				algLines.push('\t{');
				algLines.push(`\t\tconst s = SX[${a.base}];`);
				for (const f of from) algLines.push(`\t\tADD(s, SX[${f.base}]);`);
				algLines.push('\t}');
			}
			continue;
		}
		if (a.kind === 'waste_package:hazard') {
			const W = a.waste;
			const from = Object.entries(W.setting).filter(([k]) => k.startsWith('fail_')).map(([, slot]) => slot);
			// ...and the disruptive events that fail a share of these packages.
			for (const { D, share } of W.disrupted ?? []) from.push(D.lambdaSlot, share);
			if (from.length) {
				algLines.push('\t{');
				algLines.push(`\t\tconst s = SX[${a.base}];`);
				for (const f of from) algLines.push(`\t\tADD(s, SX[${f.base}]);`);
				algLines.push('\t}');
			}
			continue;
		}
		if (a.kind === 'waste_package') {
			const W = a.waste;
			for (let off = 0; off < a.width; off++) {
				algLines.push('\t{');
				algLines.push(`\t\tconst s = SX[${a.base + off}];`);
				algLines.push(`\t\ts.add(${W.intact.base + off});`);
				algLines.push(`\t\ts.add(${W.exposed.base + off});`);
				algLines.push(`\t\tADD(s, SX[${W.hazardSlot.base}]);`);
				algLines.push(`\t\tADD(s, SX[${W.setting.irf.base + off}]);`);
				algLines.push(`\t\tADD(s, SX[${W.setting.degradation_rate.base}]);`);
				algLines.push('\t}');
			}
			continue;
		}
		// A table read at the clock depends on no state at all, so its column
		// set stays empty and nothing that reads it gains an entry from it.
		if (a.kind === 'lookup') continue;

		// A block that remembers depends on whatever its parts do, plus -- for
		// a running mean -- the state carrying its integral. A snapshot and a
		// delay report the past, which no present state can move, so neither
		// gains a column.
		if (a.recorder) {
			const rec = a.recorder;
			const from = [];
			if (rec.kind === 'min_max' || rec.kind === 'running_mean') from.push(rec.aux.target);
			if (rec.kind === 'trigger') from.push(rec.aux.first, rec.aux.second);
			if (!from.length && !rec.state) continue;
			for (let off = 0; off < a.width; off++) {
				algLines.push('\t{');
				algLines.push(`\t\tconst s = SX[${a.base + off}];`);
				// A running mean's own integral is a state, so it is a column
				// of df/dy and never one of df/dp.
				if (rec.state && !wantParams) algLines.push(`\t\ts.add(${rec.state.base + off});`);
				for (const f of from) algLines.push(`\t\tADD(s, SX[${f.base + off}]);`);
				algLines.push('\t}');
			}
			continue;
		}
		const record = (ast, locate, slotExpr, indent) => {
			const refs = refNodes(ast);
			if (!refs.length) return;
			const body = [];
			for (const r of refs) {
				const loc = locate(r.name, r.indices, r);
				const own = wantParams ? 'param' : 'state';
				if (loc.kind === own) body.push(`${indent}\ts.add(${loc.offset});`);
				else if (loc.kind === 'alg') body.push(`${indent}\tADD(s, SX[${loc.offset}]);`);
			}
			if (!body.length) return;
			algLines.push(`${indent}{`);
			algLines.push(`${indent}\tconst s = SX[${slotExpr}];`);
			algLines.push(...body);
			algLines.push(`${indent}}`);
		};

		if (a.width === 1 && a.dims.length === 0) {
			record(a.asts[0], makeLocator(a, [], null, {}), String(a.base), '\t');
		} else if (a.uniform) {
			emitLoop(algLines, space, a.dims, '\t', (vars, offExpr, indent) => {
				record(a.asts[0], makeLocator(a, a.dims, vars, null),
					`${a.base} + ${offExpr}`, indent);
			});
		} else {
			emitByEquation(algLines, space, a, '\t', ({ ast, vars, tuple, slot, indent }) => {
				record(ast, makeLocator(a, a.dims, vars, tuple), slot, indent);
			});
		}
	}

	const rowLines = [];
	for (const t of project.transfers) {
		const alg = algByName.get(t.qname ?? t.name);
		const src = t.from ? stateByName.get(t.from) : null;
		const tgt = t.to ? stateByName.get(t.to) : null;
		const path = t.to && !tgt ? pathByName.get(t.to) : null;
		rowLines.push(`\t// transfer ${inComment(t.name)}`);
		emitLoop(rowLines, space, alg.dims, '\t', (vars, offExpr, indent) => {
			const resolveState = (entry) => stateOffsetExpr(
				space, alg.dims, vars, entry, t.name, mapIndex,
			);
			rowLines.push(`${indent}{`);
			rowLines.push(`${indent}\tconst cols = SX[${alg.base} + ${offExpr}];`);
			const rows = [];
			if (src) rows.push(`const rs = ${resolveState(src)};`);
			if (tgt) rows.push(`const rt = ${resolveState(tgt)};`);
			if (path) {
				rows.push(`const rt = ${
					farfInletExpr(space, alg.dims, vars, path, t.name, mapIndex)};`);
			}
			for (const line of rows) rowLines.push(`${indent}\t${line}`);
			// The flux is donor * rate, so it depends on the donor itself as
			// well as on everything the rate depends on.
			if (t.multiply_by_donor) {
				if (src) rowLines.push(`${indent}\tPAT(rs, rs);`);
				if (tgt || path) rowLines.push(`${indent}\tPAT(rt, rs);`);
			}
			rowLines.push(`${indent}\tfor (const c of cols) {`);
			if (src) rowLines.push(`${indent}\t\tPAT(rs, c);`);
			if (tgt || path) rowLines.push(`${indent}\t\tPAT(rt, c);`);
			rowLines.push(`${indent}\t}`);
			rowLines.push(`${indent}}`);
		});
	}

	for (const s of project.inflows) {
		const alg = algByName.get(s.qname ?? s.name);
		const tgt = stateByName.get(s.to);
		const path = tgt ? null : pathByName.get(s.to);
		rowLines.push(`\t// source ${inComment(s.name)}`);
		emitLoop(rowLines, space, alg.dims, '\t', (vars, offExpr, indent) => {
			const row = tgt
				? stateOffsetExpr(space, alg.dims, vars, tgt, s.name, mapIndex)
				: farfInletExpr(space, alg.dims, vars, path, s.name, mapIndex);
			rowLines.push(`${indent}{`);
			rowLines.push(`${indent}\tconst r = ${row};`);
			rowLines.push(`${indent}\tfor (const c of SX[${alg.base} + ${offExpr}]) PAT(r, c);`);
			rowLines.push(`${indent}}`);
		});
	}

	// A compartment's explicit dy/dt term: a rate into its own row, so the
	// row depends on whatever the term reads -- the compartment itself, very
	// often, which is what makes `-k*C` a diagonal entry.
	for (const slot of dydtSlots) {
		const st = stateByName.get(slot.stateName);
		rowLines.push(`\t// dy/dt term of ${inComment(st.name)}`);
		emitLoop(rowLines, space, slot.dims, '\t', (vars, offExpr, indent) => {
			rowLines.push(`${indent}for (const c of SX[${slot.base} + ${offExpr}]) `
				+ `PAT(${st.base} + ${offExpr}, c);`);
		});
	}

	// Waste packages: the intact row is -h P, so it depends on P and on what
	// the hazard does; the exposed row is h P - release, so on P, on the
	// hazard's columns and on the release's, which include itself. Where the
	// release goes is an ordinary transfer, above with the rest of them.
	for (const W of wasteLayout) {
		rowLines.push(`\t// waste packages ${inComment(W.q)}`);
		for (let off = 0; off < W.width; off++) {
			const P = W.intact.base + off;
			const M = W.exposed.base + off;
			rowLines.push('\t{');
			rowLines.push(`\t\tPAT(${P}, ${P});`);
			rowLines.push(`\t\tPAT(${M}, ${P});`);
			rowLines.push(`\t\tfor (const c of SX[${W.hazardSlot.base}]) { PAT(${P}, c); PAT(${M}, c); }`);
			rowLines.push(`\t\tfor (const c of SX[${W.releaseSlot.base + off}]) PAT(${M}, c);`);
			rowLines.push('\t}');
		}
	}

	// Disruptive events: the count's row takes the rate's columns; a move is a
	// first-order transfer of the share, so its two rows depend on the donor
	// and on whatever the rate and the share do.
	for (const D of disruptionLayout) {
		rowLines.push(`\t// disruptive event ${inComment(D.q)}`);
		rowLines.push(`\tfor (const c of SX[${D.lambdaSlot.base}]) PAT(${D.entry.base}, c);`);
		D.actions.forEach((a, k) => {
			if (a.kind !== 'move') return;
			const A = stateByName.get(a.from);
			const B = a.to ? stateByName.get(a.to) : null;
			for (let off = 0; off < A.width; off++) {
				const rows = [A.base + off, ...(B ? [B.base + off] : [])];
				for (const r of rows) {
					rowLines.push(`\tPAT(${r}, ${A.base + off});`);
					rowLines.push(`\tfor (const c of SX[${D.lambdaSlot.base}]) PAT(${r}, c);`);
					rowLines.push(`\tfor (const c of SX[${D.shares[k].base}]) PAT(${r}, c);`);
				}
			}
		});
	}

	// A path's own rows: transport between its cells, decay within them, and
	// whatever its rates depend on. Where its release goes is an ordinary
	// transfer, and is above with the rest of them.
	for (const p of farfLayout ?? []) {
		rowLines.push(`\t// far-field path ${inComment(p.name)}`);
		rowLines.push(`\tFARF[${p.farfIndex}].pattern(PAT, SX, ${
			p.decaySlot == null ? 'null' : `DEC[${p.decaySlot}]`});`);
	}

	// A running mean's own row: `dS/dt = target`, so it takes the target's
	// columns.
	for (const rec of recorders ?? []) {
		if (rec.kind !== 'running_mean') continue;
		rowLines.push(`\t// running mean ${inComment(rec.name)}`);
		for (let off = 0; off < rec.width; off++) {
			rowLines.push(`\tfor (const c of SX[${rec.aux.target.base + off}]) `
				+ `PAT(${rec.state.base + off}, c);`);
		}
	}

	for (const s of decaying ?? []) {
		const strideM = space.strides(s.dims)[s.m];
		rowLines.push(`\t// decay and ingrowth in ${inComment(s.name)}`);
		emitLoop(rowLines, space, s.dims, '\t', (vars, offExpr, indent) => {
			const nm = vars[s.m];
			rowLines.push(`${indent}{`);
			rowLines.push(`${indent}\tconst si = ${s.base} + ${offExpr};`);
			rowLines.push(`${indent}\tconst D = DEC[${s.slot}];`);
			rowLines.push(`${indent}\tPAT(si, si);`);
			rowLines.push(`${indent}\tconst o = D.ioff[${nm}], c = D.icnt[${nm}];`);
			rowLines.push(`${indent}\tfor (let q = 0; q < c; q++) {`);
			rowLines.push(`${indent}\t\tPAT(si, si + (D.ipar[o + q] - ${nm}) * ${strideM});`);
			rowLines.push(`${indent}\t}`);
			rowLines.push(`${indent}}`);
		});
	}

	return {
		algSource: algLines.join('\n') || '\t// nothing algebraic',
		rowSource: rowLines.join('\n') || '\t// no connections',
	};
}

// --- the tangent function ---------------------------------------------------

function jvpSourceFor(b, opts = {}) {
	const {
		project, space, algebraic, stateByName, algByName,
		makeLocator, makeCall, mapIndex, emitLoop, emitByEquation, stateOffsetExpr, tupleByList,
		decaying, recorders, farfLayout, pathByName, farfInletExpr, dydtSlots = [], wasteLayout = [],
		disruptionLayout = [],
	} = b;

	/**
	 * Which direction the tangent is taken along.
	 *
	 *   state   `v` seeds the state vector, the derivative is J*v, and a
	 *           parameter is a constant. This is df/dy, and is what the
	 *           solvers want.
	 *   param   `v` seeds the *parameters*, the derivative is (df/dp)*v, and
	 *           the state is held fixed. This is the driving term of the
	 *           forward sensitivity equations, `S' = J*S + df/dp`.
	 *
	 * One generator rather than two, because the two differ in exactly three
	 * places -- which reference carries the seed, which column set says a
	 * quantity is structurally still, and which terms of the assembly survive
	 * -- and a second copy of nine hundred lines of code generation would
	 * disagree with this one about a rule within a month.
	 */
	const alongState = (opts.seed ?? 'state') === 'state';

	const lines = [];
	// One counter for the whole function: a temporary emitted at top level
	// would otherwise be redeclared by the next block.
	const tape = makeTape('\t');
	const fresh = (indent) => {
		tape.lines = [];
		tape.cse = new Map();
		tape.indent = indent;
		return tape;
	};

	// Whether a block's value can move with the state at all.
	//
	// `SX` is the column set of every algebraic slot, filled by the pattern
	// pass before this runs. Empty means nothing in that slot follows a
	// compartment -- so its tangent is not merely zero at runtime, it is
	// structurally zero, and `dX` is written 0 for it either way.
	//
	// Saying so here matters for more than the size of the generated code. A
	// rule that will not differentiate a *live* argument -- a lookup table
	// whose own points move with the state -- decides that by asking whether
	// the argument has a tangent at all, and a symbolic `dX[i]` answered yes
	// for a table read at the clock. One landscape model's flow of water out
	// of an object is `interpolationUseEndValues(time, ..., WF_out_marine,
	// ...)` with `WF_out_marine` a time series: nothing in it follows the
	// state, and the whole 2,757-state model was declining an analytic
	// Jacobian over it -- falling back to a dense finite-difference matrix
	// that costs 2,757 evaluations of f to form and a dense factorisation to
	// use.
	//
	// The pattern is already the authority on which entries the matrix has,
	// so trusting it here adds no risk that was not already taken.
	const SX = b.SX ?? [];
	const still = new Map();
	const doesNotMove = (target) => {
		if (!target || target.base == null) return false;
		if (still.has(target)) return still.get(target);
		let answer = true;
		for (let i = 0; i < target.width; i++) {
			if (SX[target.base + i]?.size) { answer = false; break; }
		}
		still.set(target, answer);
		return answer;
	};

	const tangentResolver = (locate) => (name, index, node) => {
		const loc = locate(name, index, node);
		// Whichever of the two the seed is on carries it; the other is a
		// constant along this direction and its tangent is structurally zero,
		// which is what lets whole sub-expressions fold away.
		if (loc.kind === 'state') {
			return { value: `y[${loc.offset}]`, tangent: alongState ? `v[${loc.offset}]` : null };
		}
		if (loc.kind === 'param') {
			return { value: `P[${loc.offset}]`, tangent: alongState ? null : `v[${loc.offset}]` };
		}
		return {
			value: `X[${loc.offset}]`,
			tangent: doesNotMove(loc.target) ? null : `dX[${loc.offset}]`,
		};
	};

	// The temporaries live in an array on the context rather than in locals:
	// see `tapePrelude` in ../parser/compile.js. Declared once, at the top.
	lines.push(tapePrelude('\t'));
	lines.push('// --- algebraic blocks and their tangents ---');
	for (const a of algebraic) {
		// Sanitised for the same reason builder.js does it: a name with a line
		// break in it would end this comment and compile as source.
		lines.push(`\t// ${a.kind} ${inComment(a.name)}`);
		if (a.kind === 'lookup') {
			// The value still has to be computed -- whatever reads it reads X --
			// but its tangent along any state direction is exactly zero.
			if (a.width === 1 && a.dims.length === 0) {
				lines.push(`\tX[${a.base}] = TAB[${a.tab}].at(ctx.t);`);
				lines.push(`\tdX[${a.base}] = 0;`);
			} else {
				emitLoop(lines, space, a.dims, '\t', (vars, offExpr, indent) => {
					lines.push(
						`${indent}X[${a.base} + ${offExpr}] = TAB[${a.tab} + ${offExpr}].at(ctx.t);`,
					);
					lines.push(`${indent}dX[${a.base} + ${offExpr}] = 0;`);
				});
			}
			continue;
		}
		// A path's release: `sum(w(X)*y)` over a couple of its own cells, so
		// the tangent carries both the seed and, when a rate follows the
		// state, the rate's own tangent. It writes X as well as dX, since the
		// value has to be there for whatever reads it.
		if (a.kind === 'farfield') {
			lines.push(`\tFARF[${a.farfIndex}].release(y, X);`);
			lines.push(`\tFARF[${a.farfIndex}].releaseTangent(y, v, X, dX);`);
			continue;
		}
		// Waste packages. The hazard is a function of the clock and of settings
		// that are, in any model so far, constants: its tangent is then zero
		// exactly. A failure setting that follows the state would need the
		// hazard differentiated in each of its closed forms, and that is
		// refused rather than approximated -- the solvers difference instead.
		if (a.kind === 'waste_package:hazard') {
			const W = a.waste;
			const moving = Object.entries(W.setting)
				.filter(([k, slot]) => k.startsWith('fail_') && b.SX?.[slot.base]?.size);
			for (const { D, share } of W.disrupted ?? []) {
				if (b.SX?.[D.lambdaSlot.base]?.size) moving.push([`${D.q}'s rate`]);
				if (b.SX?.[share.base]?.size) moving.push([`${D.q}'s share`]);
			}
			if (moving.length) {
				throw new Refused(
					`'${inComment(W.q)}' fails by a setting that follows the state `
					+ `(${moving.map(([k]) => k).join(', ')}), and the hazard's derivative `
					+ 'along it is not one to guess at',
				);
			}
			const at = (key) => (W.setting[key] ? `X[${W.setting[key].base}]` : '0');
			const extra = (W.disrupted ?? [])
				.map(({ D, share }) => ` + X[${D.lambdaSlot.base}] * X[${share.base}]`).join('');
			lines.push(`\tX[${a.base}] = ${hazardCode(W.failure, {
				t: 'ctx.t', from: at('fail_from'), to: at('fail_to'), start: at('fail_start'),
				rate: at('fail_rate'), scale: at('fail_scale'), shape: at('fail_shape'),
			})}${extra};`);
			lines.push(`\tdX[${a.base}] = 0;`);
			continue;
		}
		// An event's expected-value rate: the rate gated by its window, with
		// no tangent unless a rate or a window follows the state, which is
		// refused for the same reason a moving failure setting is.
		if (a.kind === 'event:lambda') {
			const D = a.event;
			if (Object.values(D.setting).some((slot) => b.SX?.[slot.base]?.size)) {
				throw new Refused(
					`'${inComment(D.q)}' happens at a rate or in a window that follows the state, `
					+ 'and the derivative of that is not one to guess at',
				);
			}
			if (D.timing !== 'poisson') {
				lines.push(`\tX[${a.base}] = 0;`);
			} else {
				const from = D.setting.from ? `X[${D.setting.from.base}]` : 'ctx.startTime';
				const until = D.setting.until ? `X[${D.setting.until.base}]` : 'ctx.endTime';
				lines.push(`\tX[${a.base}] = ctx.dis[${D.index}] * `
					+ `(ctx.t >= ${from} && ctx.t < ${until} ? X[${D.setting.rate.base}] : 0);`);
			}
			lines.push(`\tdX[${a.base}] = 0;`);
			continue;
		}
		// The release, h P irf + d M, differentiated: through the two
		// inventories always, and through the fraction and the rate when
		// either follows the state.
		if (a.kind === 'waste_package') {
			const W = a.waste;
			const haz = `X[${W.hazardSlot.base}]`;
			const deg = `X[${W.setting.degradation_rate.base}]`;
			const dDeg = b.SX?.[W.setting.degradation_rate.base]?.size ? `dX[${W.setting.degradation_rate.base}]` : null;
			for (let off = 0; off < a.width; off++) {
				const P = W.intact.base + off;
				const M = W.exposed.base + off;
				const irf = `X[${W.setting.irf.base + off}]`;
				const dIrf = b.SX?.[W.setting.irf.base + off]?.size ? `dX[${W.setting.irf.base + off}]` : null;
				lines.push(`\tX[${a.base + off}] = ${haz} * y[${P}] * ${irf} + ${deg} * y[${M}];`);
				lines.push(`\tdX[${a.base + off}] = ${haz} * (v[${P}] * ${irf}`
					+ `${dIrf ? ` + y[${P}] * ${dIrf}` : ''}) + ${deg} * v[${M}]`
					+ `${dDeg ? ` + ${dDeg} * y[${M}]` : ''};`);
			}
			continue;
		}
		// A block that remembers. Each is differentiable exactly, and each in
		// its own way:
		//
		//   min/max        max(so far, target), whose derivative is the
		//                  target's when the target is the extreme and zero
		//                  when it is not -- which is the derivative of `max`
		//                  wherever one exists
		//   running mean   the integral divided by the time it covers, so the
		//                  tangent is the integral's over the same time
		//   snapshot,      the past, which no present state can move
		//   delay
		//   discrete event an ordinary difference of two expressions
		if (a.recorder) {
			const rec = a.recorder;
			for (let off = 0; off < a.width; off++) {
				const i = a.base + off;
				const at = (slot) => `X[${slot.base + off}]`;
				const dat = (slot) => `dX[${slot.base + off}]`;
				const mem = `MEM[${rec.mem + off}]`;
				switch (rec.kind) {
					case 'min_max':
						lines.push(`\tX[${i}] = ${mem}.extreme(ctx.t, ${at(rec.aux.target)});`);
						lines.push(`\tdX[${i}] = X[${i}] === ${at(rec.aux.target)} `
							+ `? ${dat(rec.aux.target)} : 0;`);
						break;
					case 'running_mean': {
						const st = rec.state.base + off;
						lines.push(`\tX[${i}] = ${mem}.mean(ctx.t, y[${st}], ${at(rec.aux.target)});`);
						lines.push(`\t{`);
						lines.push(`\t\tconst el = ${mem}.elapsedAt(ctx.t);`);
						lines.push(`\t\tdX[${i}] = el > 0 ? ${alongState ? `v[${st}] / el` : '0'} `
							+ `: ${dat(rec.aux.target)};`);
						lines.push(`\t}`);
						break;
					}
					case 'snapshot':
						lines.push(`\tX[${i}] = ${mem}.held(ctx.t);`);
						lines.push(`\tdX[${i}] = 0;`);
						break;
					case 'delay':
						// A delay reports the past, which no present state can
						// move -- *unless the lag itself does*. Then the value
						// slides along the recorded history as the state
						// changes, and `dX = 0` is a Jacobian entry that is
						// simply missing. Refused rather than guessed: the
						// derivative of a lerp over a history is not something
						// to invent, and the solvers fall back to differencing,
						// which gets it right.
						if (b.SX?.[rec.aux.delay.base + off]?.size) {
							throw new Refused(
								'a delay whose lag depends on the state: its value slides '
								+ 'along the recorded history as the state changes, and '
								+ 'that derivative is not one to guess at',
							);
						}
						lines.push(`\tX[${i}] = ${mem}.delayed(ctx.t, ${at(rec.aux.delay)});`);
						lines.push(`\tdX[${i}] = 0;`);
						break;
					default:
						lines.push(`\tX[${i}] = ${at(rec.aux.first)} - ${at(rec.aux.second)};`);
						lines.push(`\tdX[${i}] = ${dat(rec.aux.first)} - ${dat(rec.aux.second)};`);
						break;
				}
			}
			continue;
		}

		const emitOne = (ast, locate, call, slotExpr, indent) => {
			const t = fresh(indent);
			let r;
			try {
				r = emitWithTangent(ast, tangentResolver(locate), t, call);
			} catch (e) {
				// Which block it was. Without this the whole model declines an
				// analytic Jacobian over one equation and the panel says only
				// what the function was -- leaving no way to find the block and
				// no way to know that rewriting it would make the model fast.
				if (e instanceof NoDerivative) {
					throw new NoDerivative(`${e.what} in '${inComment(a.name)}'`);
				}
				throw e;
			}
			lines.push(...t.lines);
			lines.push(`${indent}X[${slotExpr}] = ${r.value};`);
			lines.push(`${indent}dX[${slotExpr}] = ${r.tangent ?? 0};`);
			if (tape.count > MAX_STATEMENTS) {
				throw new Refused(
					`the model generates more than ${MAX_STATEMENTS} tangent statements`,
				);
			}
			if (lines.length > MAX_LINES) {
				throw new Refused(
					`the model generates more than ${MAX_LINES} lines of tangent code`,
				);
			}
		};

		if (a.width === 1 && a.dims.length === 0) {
			emitOne(a.asts[0], makeLocator(a, [], null, {}), makeCall(a, [], null, {}),
				String(a.base), '\t');
		} else if (a.uniform) {
			emitLoop(lines, space, a.dims, '\t', (vars, offExpr, indent) => {
				emitOne(a.asts[0], makeLocator(a, a.dims, vars, null),
					makeCall(a, a.dims, vars, null), `${a.base} + ${offExpr}`, indent);
			});
		} else {
			emitByEquation(lines, space, a, '\t', ({ ast, vars, tuple, slot, indent }) => {
				emitOne(ast, makeLocator(a, a.dims, vars, tuple),
					makeCall(a, a.dims, vars, tuple), slot, indent);
			});
		}
	}

	lines.push('// --- derivative assembly, differentiated ---');
	lines.push('\tdout.fill(0);');

	let fluxSeq = 0;
	for (const t of project.transfers) {
		const alg = algByName.get(t.qname ?? t.name);
		const src = t.from ? stateByName.get(t.from) : null;
		const tgt = t.to ? stateByName.get(t.to) : null;
		const path = t.to && !tgt ? pathByName.get(t.to) : null;
		lines.push(`\t// transfer ${inComment(t.name)}`);
		emitLoop(lines, space, alg.dims, '\t', (vars, offExpr, indent) => {
			const f = `df${fluxSeq++}`;
			const rate = `${alg.base} + ${offExpr}`;
			const resolveState = (entry) => stateOffsetExpr(
				space, alg.dims, vars, entry, t.name, mapIndex,
			);
			if (t.multiply_by_donor) {
				const s = resolveState(src);
				// d(donor * rate) = d(donor) * rate + donor * d(rate). Along a
				// parameter the donor is held fixed, so only the second term
				// survives -- which is the whole of df/dp for a linear model.
				lines.push(alongState
					? `${indent}const ${f} = v[${s}] * X[${rate}] + y[${s}] * dX[${rate}];`
					: `${indent}const ${f} = y[${s}] * dX[${rate}];`);
			} else {
				lines.push(`${indent}const ${f} = dX[${rate}];`);
			}
			if (src) lines.push(`${indent}dout[${resolveState(src)}] -= ${f};`);
			if (tgt) lines.push(`${indent}dout[${resolveState(tgt)}] += ${f};`);
			if (path) {
				const inlet = farfInletExpr(space, alg.dims, vars, path, t.name, mapIndex);
				lines.push(`${indent}dout[${inlet}] += ${f};`);
			}
		});
	}

	for (const s of project.inflows) {
		const alg = algByName.get(s.qname ?? s.name);
		const tgt = stateByName.get(s.to);
		const path = tgt ? null : pathByName.get(s.to);
		lines.push(`\t// source ${inComment(s.name)}`);
		emitLoop(lines, space, alg.dims, '\t', (vars, offExpr, indent) => {
			const target = tgt
				? stateOffsetExpr(space, alg.dims, vars, tgt, s.name, mapIndex)
				: farfInletExpr(space, alg.dims, vars, path, s.name, mapIndex);
			lines.push(`${indent}dout[${target}] += dX[${alg.base} + ${offExpr}];`);
		});
	}

	// A compartment's explicit dy/dt term, differentiated: its slot's tangent
	// lands in the compartment's own row.
	for (const slot of dydtSlots) {
		const st = stateByName.get(slot.stateName);
		lines.push(`\t// dy/dt term of ${inComment(st.name)}`);
		emitLoop(lines, space, slot.dims, '\t', (vars, offExpr, indent) => {
			lines.push(`${indent}dout[${st.base} + ${offExpr}] += dX[${slot.base} + ${offExpr}];`);
		});
	}

	// Waste packages: `fail = h P` with the hazard's tangent zero (see above),
	// so d(fail) = h v[P]; the exposed row is fail - release, and the
	// release's tangent is in dX already.
	for (const W of wasteLayout) {
		lines.push(`\t// waste packages ${inComment(W.q)}`);
		for (let off = 0; off < W.width; off++) {
			const P = W.intact.base + off;
			const M = W.exposed.base + off;
			lines.push('\t{');
			lines.push(`\t\tconst dfail = X[${W.hazardSlot.base}] * v[${P}];`);
			lines.push(`\t\tdout[${P}] -= dfail;`);
			lines.push(`\t\tdout[${M}] += dfail - dX[${W.releaseSlot.base + off}];`);
			lines.push('\t}');
		}
	}

	// Disruptive events: the count's rate has no tangent (see above); a move
	// is `lambda * share * y[A]`, differentiated through the donor and, when
	// the share follows the state, through the share.
	for (const D of disruptionLayout) {
		lines.push(`\t// disruptive event ${inComment(D.q)}`);
		D.actions.forEach((a, k) => {
			if (a.kind !== 'move') return;
			const A = stateByName.get(a.from);
			const B = a.to ? stateByName.get(a.to) : null;
			const share = D.shares[k];
			const dShare = b.SX?.[share.base]?.size ? `dX[${share.base}]` : null;
			for (let off = 0; off < A.width; off++) {
				lines.push('\t{');
				lines.push(`\t\tconst dm = X[${D.lambdaSlot.base}] * (X[${share.base}] * v[${A.base + off}]`
					+ `${dShare ? ` + ${dShare} * y[${A.base + off}]` : ''});`);
				lines.push(`\t\tdout[${A.base + off}] -= dm;`);
				if (B) lines.push(`\t\tdout[${B.base + off}] += dm;`);
				lines.push('\t}');
			}
		});
	}

	// A path: the matrix applied to the seed, plus the rates' own tangents
	// applied to the state when a rate follows a compartment. Where its
	// release goes is an ordinary transfer, differentiated above with the
	// rest of them.
	for (const p of farfLayout ?? []) {
		lines.push(`\t// far-field path ${inComment(p.name)}`);
		lines.push(`\tFARF[${p.farfIndex}].jvp(y, v, dout, X, dX, ${
			p.decaySlot == null ? 'null' : `DEC[${p.decaySlot}]`});`);
	}

	for (const rec of recorders ?? []) {
		if (rec.kind !== 'running_mean') continue;
		lines.push(`\t// running mean ${inComment(rec.name)}`);
		for (let off = 0; off < rec.width; off++) {
			lines.push(`\tdout[${rec.state.base + off}] += MEM[${rec.mem + off}].recording `
				+ `? dX[${rec.aux.target.base + off}] : 0;`);
		}
	}

	// Decay and ingrowth are exactly linear in y, so their tangent is the same
	// expression with the seed in place of the state. Their coefficients come
	// from the half-lives, which are model data and not parameters, so along a
	// parameter this whole term is zero and is not emitted at all.
	for (const s of alongState ? (decaying ?? []) : []) {
		const strideM = space.strides(s.dims)[s.m];
		lines.push(`\t// decay and ingrowth in ${inComment(s.name)}`);
		emitLoop(lines, space, s.dims, '\t', (vars, offExpr, indent) => {
			const nm = vars[s.m];
			lines.push(`${indent}{`);
			lines.push(`${indent}\tconst si = ${s.base} + ${offExpr};`);
			lines.push(`${indent}\tconst D = DEC[${s.slot}];`);
			lines.push(`${indent}\tdout[si] -= D.lam[${nm}] * v[si];`);
			lines.push(`${indent}\tconst o = D.ioff[${nm}], c = D.icnt[${nm}];`);
			lines.push(`${indent}\tfor (let q = 0; q < c; q++) {`);
			lines.push(
				`${indent}\t\tdout[si] += D.icoef[o + q] * `
				+ `v[si + (D.ipar[o + q] - ${nm}) * ${strideM}];`,
			);
			lines.push(`${indent}\t}`);
			lines.push(`${indent}}`);
		});
	}

	lines.push('\treturn dout;');
	// The check above runs while the algebraic slots are emitted, which is
	// where the size comes from in every model that has any -- but the
	// assembly below it has its own unrolled loops, so the total is measured
	// once more before this is handed to `new Function`.
	if (lines.length > MAX_LINES) {
		throw new Refused(
			`the model generates more than ${MAX_LINES} lines of tangent code`,
		);
	}
	// The slot count goes with the source: the caller allocates the scratch
	// the prelude reaches for. See `tapePrelude` in ../parser/compile.js.
	return { source: lines.join('\n'), slots: tape.n };
}

// --- is the matrix the same at every point? ---------------------------------

/**
 * True when df/dy depends on neither the state nor the clock, so it can be
 * factorised once and reused. The test is structural
 * and deliberately conservative: a rate that mentions a compartment might still
 * have a constant derivative, but saying so would mean proving it.
 */
function isConstant(b, SX) {
	const { project, algebraic, algByName } = b;

	// A block that remembers moves with what has happened, not only with the
	// clock and the state: a min/max switches between its target and the
	// extreme so far, and a running mean divides by a time that grows. Neither
	// gives a matrix that can be factorised once.
	if ((b.recorders ?? []).some((r) => r.mem >= 0)) return false;

	const clock = new Map();
	// A reference is resolved before it is followed, exactly as the code
	// generator resolves it. Following the written name instead missed every
	// dependency inside a sub-system -- and reported a matrix that moves with
	// the clock as constant, which is the one direction of error a solver
	// cannot recover from: it would keep factorising a stale matrix.
	const known = (n) => algByName.has(n);
	// Topological order, so a block's dependencies are already decided.
	for (const a of algebraic) {
		// A lookup has no equation to inspect: it is read at the clock, so it
		// is time-dependent by construction.
		let dependsOnTime = a.kind === 'lookup' || a.asts.some(usesClock);
		if (!dependsOnTime) {
			for (const ast of a.asts) {
				for (const r of refNodes(ast)) {
					const q = resolveReference(r.name, a.system ?? '', known);
					if (q && clock.get(q)) { dependsOnTime = true; break; }
				}
				if (dependsOnTime) break;
			}
		}
		// A block that remembers parses no equation of its own, so the walk
		// above sees nothing and marked it clock-independent -- even though
		// every one of them reads the clock. The remembering kinds are caught
		// by the test at the top of this function; a discrete event is not,
		// and its value is `first - second`, so it follows the clock exactly
		// as far as those two do.
		if (a.recorder) {
			dependsOnTime = a.recorder.mem >= 0
				|| Object.values(a.recorder.aux ?? {}).some((slot) => clock.get(slot.name));
		}
		// Waste packages parse no equation either. The hazard reads the clock
		// whenever there is one -- a window, a rate from a start, a Weibull --
		// and never or all-at-once has none; the release follows the hazard,
		// the instant-release fraction and the degradation rate.
		if (a.kind === 'event:lambda') {
			// Gated by a window inside the run it switches with the clock; a
			// rate over the whole run is a constant. `ctx.dis` is a constant
			// of the run too.
			const D = a.event;
			dependsOnTime = D.timing === 'poisson'
				&& (!!D.setting.from || !!D.setting.until
					|| Object.values(D.setting).some((slot) => clock.get(slot.name)));
		}
		if (a.kind === 'waste_package:hazard') {
			const W = a.waste;
			dependsOnTime = !['never', 'at'].includes(W.failure)
				|| Object.entries(W.setting).some(([k, slot]) => k.startsWith('fail_') && clock.get(slot.name))
				|| (W.disrupted ?? []).some(({ D, share }) => clock.get(D.lambdaSlot.name) || clock.get(share.name));
		}
		if (a.kind === 'waste_package') {
			const W = a.waste;
			dependsOnTime = !!clock.get(W.hazardSlot.name)
				|| !!clock.get(W.setting.irf.name) || !!clock.get(W.setting.degradation_rate.name);
		}
		clock.set(a.name, dependsOnTime);
	}

	// A release out of a far-field path is the one rate that reads the state
	// and still has a constant derivative, and it is worth proving rather than
	// giving up on: the release is a fixed weighted sum of the path's own
	// cells, so its tangent is those same weights whatever the state is. The
	// weights move only if the path's settings do, and those are checked below
	// like any other rate.
	//
	// Proved narrowly, by shape: the equation has to be a bare reference to
	// the path -- which is what the editor writes and holds there. `Rock * 2`
	// is linear too and this will not say so, which is the right way round for
	// a test whose wrong answer is a solver reusing a stale matrix.
	// The same holds for a release out of waste packages -- `h P irf + d M`,
	// linear in the two inventories with coefficients that are constant
	// exactly when the release slot does not follow the clock, which is
	// decided above and checked here.
	const paths = new Set([
		...(b.farfLayout ?? []).map((p) => p.name),
		...(b.wasteLayout ?? []).filter((W) => !clock.get(W.q)).map((W) => W.q),
	]);
	const isBareRelease = (a) => {
		if (!paths.size || !a.asts?.length) return false;
		// ...and the rate has to be used *as* the flux. With
		// `multiply_by_donor` the flux is `donor * rate`, so df/dy carries the
		// rate's own value -- which a release's very much does move -- and the
		// matrix is not constant at all. `Project` refuses that combination on
		// a path, but this test is about what the file says, not about what
		// the validator happened to allow.
		if (a.block?.multiply_by_donor !== false) return false;
		return a.asts.every((ast) => {
			if (ast?.type !== 'ref' || (ast.indices ?? []).length) return false;
			const q = resolveReference(ast.name, a.system ?? '', (n) => paths.has(n));
			return !!q && paths.has(q);
		});
	};

	const rateBlocks = [...project.transfers, ...project.inflows]
		.map((t) => algByName.get(t.qname ?? t.name))
		.filter((a) => a && !isBareRelease(a));
	// A dy/dt term is a rate into its own compartment: one that follows the
	// state or the clock moves the matrix exactly as a transfer rate does.
	rateBlocks.push(...(b.dydtSlots ?? []));
	// A path's rates decide its whole matrix, so a travel time that follows
	// the clock or a compartment moves df/dy just as a transfer rate does.
	for (const p of project.farfields ?? []) {
		const name = p.qname ?? p.name;
		for (const key of FARF_EQUATION_KEYS) {
			const a = algByName.get(`${name}#${key}`);
			if (!a) continue;
			rateBlocks.push(a);
		}
	}
	// A waste package's hazard and settings are rates in the same sense: one
	// that follows the clock or the state moves the two inventories' rows.
	for (const W of b.wasteLayout ?? []) {
		rateBlocks.push(W.hazardSlot, W.setting.irf, W.setting.degradation_rate);
	}
	for (const D of b.disruptionLayout ?? []) rateBlocks.push(D.lambdaSlot, ...D.shares);
	for (const a of rateBlocks) {
		if (!a) continue;
		if (clock.get(a.name)) return false;
		for (let off = 0; off < a.width; off++) {
			if (SX[a.base + off].size) return false;
		}
	}
	return true;
}

function usesClock(ast) {
	switch (ast.type) {
		case 'call': {
			const name = FUNCTION_ALIASES[ast.name] ?? ast.name;
			if (FUNCTIONS[name]?.needsContext) return true;
			return ast.args.some(usesClock);
		}
		case 'unary': return usesClock(ast.operand);
		case 'binary': return usesClock(ast.left) || usesClock(ast.right);
		case 'cond':
			return usesClock(ast.test) || usesClock(ast.then) || usesClock(ast.otherwise);
		default: return false;
	}
}

function refNodes(ast, out = []) {
	switch (ast.type) {
		case 'ref': out.push(ast); break;
		case 'unary': refNodes(ast.operand, out); break;
		case 'binary': refNodes(ast.left, out); refNodes(ast.right, out); break;
		case 'cond':
			refNodes(ast.test, out); refNodes(ast.then, out); refNodes(ast.otherwise, out);
			break;
		case 'call': ast.args.forEach((a) => refNodes(a, out)); break;
		default: break;
	}
	return out;
}

// --- sparsity bookkeeping ---------------------------------------------------

/** Column-major structure, with the position of each diagonal entry. */
export function toCSC(cols, n) {
	const colPtr = new Int32Array(n + 1);
	for (let j = 0; j < n; j++) colPtr[j + 1] = colPtr[j] + cols[j].size;
	const nnz = colPtr[n];
	const rowIdx = new Int32Array(nnz);
	const diag = new Int32Array(n).fill(-1);
	for (let j = 0; j < n; j++) {
		const rows = [...cols[j]].sort((a, c) => a - c);
		let k = colPtr[j];
		for (const r of rows) {
			rowIdx[k] = r;
			if (r === j) diag[j] = k;
			k++;
		}
	}
	return { n, nnz, colPtr, rowIdx, diag };
}

/**
 * Groups columns so that no two in a group share a row.
 *
 * With that property one evaluation of J*v, seeded on a whole group at once,
 * carries exactly one column's entry in every row it touches -- so G
 * evaluations fill the matrix, where G is the number of groups rather than the
 * number of columns. Greedy, largest-degree first, which is the standard
 * heuristic and lands within one or two colours of optimal on matrices like
 * these.
 */
export function colourColumns(pattern) {
	const { n, colPtr, rowIdx } = pattern;

	// Rows -> the columns that touch them, so conflicts can be looked up.
	const rowCount = new Int32Array(n + 1);
	for (let k = 0; k < rowIdx.length; k++) rowCount[rowIdx[k] + 1]++;
	for (let i = 0; i < n; i++) rowCount[i + 1] += rowCount[i];
	const rowPtr = Int32Array.from(rowCount);
	const rowCols = new Int32Array(rowIdx.length);
	const fill = Int32Array.from(rowPtr);
	for (let j = 0; j < n; j++) {
		for (let k = colPtr[j]; k < colPtr[j + 1]; k++) rowCols[fill[rowIdx[k]]++] = j;
	}

	const order = Array.from({ length: n }, (_, j) => j)
		.sort((a, c) => (colPtr[c + 1] - colPtr[c]) - (colPtr[a + 1] - colPtr[a]));

	const colour = new Int32Array(n).fill(-1);
	const used = new Int32Array(n + 1).fill(-1);
	let ncolours = 0;
	for (const j of order) {
		for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
			const row = rowIdx[k];
			for (let q = rowPtr[row]; q < rowPtr[row + 1]; q++) {
				const other = rowCols[q];
				if (colour[other] >= 0) used[colour[other]] = j;
			}
		}
		let c = 0;
		while (used[c] === j) c++;
		colour[j] = c;
		if (c + 1 > ncolours) ncolours = c + 1;
	}

	const groups = Array.from({ length: ncolours }, () => []);
	for (let j = 0; j < n; j++) groups[colour[j]].push(j);
	return groups.map((g) => Int32Array.from(g));
}

/** True when no two columns in a group share a row. Used by the tests. */
export function colouringIsValid(pattern, groups) {
	const { colPtr, rowIdx } = pattern;
	const seen = new Int32Array(pattern.n).fill(-1);
	for (let g = 0; g < groups.length; g++) {
		for (const j of groups[g]) {
			for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
				if (seen[rowIdx[k]] === g) return false;
				seen[rowIdx[k]] = g;
			}
		}
	}
	return true;
}
