/**
 * Runs a project and collects results.
 *
 * Drives the solver over the project's output grid and then back-fills the
 * algebraic outputs (expressions and transfer rates), which the solver does
 * not carry in the state vector.
 */

import { Project } from '../domain/project.js';
import { switchTimes } from '../domain/switchtimes.js';
import {
	derivedBlocks, reduce as reduceDerived, derivedUnit as derivedUnitFor, isSeries as derivedIsSeries,
} from '../domain/derived.js';
import { buildSystem, tupleByList, describeTuple, BuildError } from './builder.js';
import { julia } from '../ode/julia-solvers.js';
import { audit as auditBudget } from '../domain/massbalance.js';
import { cellNames } from '../domain/farfield.js';
import { valueAt } from '../domain/project.js';
import { dormandPrince, SolverError } from '../ode/solvers/dormand-prince.js';
import { rosenbrock23 } from '../ode/solvers/rosenbrock23.js';
import { variableOrder } from '../ode/variable-order.js';
import { SOLVER_IDS, DEFAULT_SOLVER, solverLabel, solverName, solverOptions } from '../ode/solvers.js';
import { isScipySolver, scipySolver } from '../ode/scipy.js';
import { csvCell } from '../io/csv.js';

// Names and blurbs live in one place, shared with the interface.
export {
	SOLVER_INFO, SOLVER_IDS, LOCAL_SOLVER_IDS, DEFAULT_SOLVER,
	solverLabel, solverName, solverIsRemote,
} from '../ode/solvers.js';

// Keyed by id, in the order the catalogue offers them. The SciPy ones are
// built on demand: scipy.js holds no runtime until something asks it to, so
// importing it here costs nothing and keeps the dispatch in one place.
// Null prototype: the id comes out of a project file, and on a plain object
// `SOLVERS.constructor` is `Object` -- truthy, so `solverFor` handed back the
// Object constructor as the solver and the run failed somewhere downstream
// with nothing to say which setting was wrong.
const SOLVERS = Object.assign(Object.create(null), {
	// The NDFs; `simulation.bdf` runs the same integrator as the plain BDFs.
	ndf: variableOrder,
	ros23: rosenbrock23,
	dp45: dormandPrince,
	// The ported DifferentialEquations.jl methods, each wrapped in this
	// project's solver shape. See ../ode/julia-solvers.js.
	fbdf: julia('fbdf'),
	qndf: julia('qndf'),
	rodas5p: julia('rodas5p'),
	radau5: julia('radau5'),
	kencarp4: julia('kencarp4'),
	trbdf2: julia('trbdf2'),
});

function solverFor(id) {
	if (SOLVERS[id]) return SOLVERS[id];
	return isScipySolver(id) ? scipySolver(id) : null;
}

/**
 * Refuses a starting point that is not a set of numbers.
 *
 * `1/0` and `log(0)` are things a model may end up saying -- a parameter that
 * went to zero, an expression that divides by one -- and the answer from the
 * solver was "Failure at t=0. Unable to meet integration tolerances", which is
 * true and points at the wrong thing entirely. Only the first is named: the
 * rest are usually the same mistake seen once per index.
 */
function checkInitialState(system, y0) {
	for (let i = 0; i < y0.length; i++) {
		if (Number.isFinite(y0[i])) continue;
		const at = (system.layout.states ?? []).find(
			(s) => i >= s.base && i < s.base + s.width,
		);
		const where = at && at.dims.length
			? ` at ${describeTuple(tupleByList(system.layout.indexSpace, at.dims, i - at.base))}`
			: '';
		throw new SolverError(
			`${at ? at.name : `State ${i}`} starts at ${y0[i]}${where}, which is not a `
			+ `number the simulation can start from. Its initial inventory works out `
			+ `to ${y0[i]} -- most often a division by a parameter that is zero, or a `
			+ `log or square root of one.`,
			0,
		);
	}
}

/**
 * The absolute error tolerance for each state, or one number for all of them.
 *
 * The simulation's own setting is the default, and a compartment may say
 * otherwise -- for the whole block, or for one index of it. That is Ecolego's
 * rule exactly: `JavaSimulator` fills `atol` with the setting and then walks
 * the states, overriding each one where `PropertyHelper.getAbsTol(compartment,
 * indices)` returns something.
 *
 * It is worth having because one tolerance cannot fit a model whose
 * inventories span decades. At 1e-9 Bq a compartment holding 1e12 Bq is being
 * error-controlled to twenty-one significant figures it does not have, so the
 * solver works for a precision that means nothing; on the same run a trace
 * daughter really sitting at 1e-8 Bq needs that tolerance to be integrated at
 * all. Ecolego writes the field on every entry it saves and leaves it empty in
 * all 9,695 of them across the projects here, so nothing changes for a model
 * that says nothing -- which is why this returns the plain number in that
 * case, and a vector only when something asked for one.
 *
 * Only compartments: the rest of the state vector is a running mean's integral
 * and a delay's history, and neither is a thing a modeller names a tolerance
 * for.
 *
 * @returns {number|Float64Array}
 */
export function absoluteTolerance(project, layout) {
	const fallback = project.simulation.abstol;
	const perState = new Float64Array(layout.nstate).fill(fallback);
	let asked = false;
	for (const s of layout.states) {
		// A waste package's two inventories take the block's tolerance too.
		if (s.kind !== 'compartment' && s.kind !== 'waste_package') continue;
		for (let off = 0; off < s.width; off++) {
			const v = valueAt(
				s.block, 'abstol', tupleByList(layout.indexSpace, s.dims, off),
			);
			if (v == null || v === '') continue;
			const n = Number(v);
			// Validation refuses anything else; a project object built by
			// hand and never validated is not worth failing a run over.
			if (!Number.isFinite(n) || !(n > 0)) continue;
			perState[s.base + off] = n;
			asked = true;
		}
	}
	return asked ? perState : fallback;
}

/**
 * @param {object|Project} input  project JSON or a Project
 * @param {object} [opts] { onProgress(fraction), signal }
 * @returns {Results}
 */
export function run(input, opts = {}) {
	const project = input instanceof Project ? input : new Project(input);
	const t0 = now();

	// A probabilistic run builds once and integrates a thousand times, so the
	// system can be handed in. Everything a realisation changes is read live:
	// `P` is the array the generated code holds, `initialState()` is a call and
	// not a value, and the Jacobian reads `P` on every evaluation. What is
	// *not* live is the algebra worked out once at build -- so a caller that
	// rewrites `P` calls `system.evaluateInvariant()` before running, which is
	// what ./probabilistic.js does. See *Three passes, not one* in INTERNALS.md.
	const system = opts.system ?? buildSystem(project);
	const buildMs = now() - t0;
	// Built. Said out loud because the caller may be showing a word about it:
	// on a large model this is seconds, and the first step can be seconds more
	// -- a page that says "building" through both of those has stopped telling
	// the truth halfway. See `onStage` in ../worker/sim-worker.js.
	opts.onStage?.('solving');

	const grid = project.timeGrid();
	const y0 = system.initialState();

	const { nstate, states } = system.layout;

	// An initial inventory that is not a number poisons the whole state vector
	// from t=0, and the solver's account of it is a tolerance it cannot meet
	// at the first step -- which sends the reader off tightening tolerances and
	// changing solvers over an equation that says `1/0`. Named here instead,
	// with the compartment and the index it came from.
	checkInitialState(system, y0);

	// Which states the solver must not let go negative -- the `nonNegative`
	// option, which every solver here implements.
	//
	// A compartment holds an inventory, so it is on by default; a model can
	// turn it off per compartment, which is worth being able to do because a
	// state pinned at zero by the constraint looks like a result and is
	// usually a modelling error being hidden.
	//
	// Nothing else in the state vector gets it. A running mean carries the
	// integral of whatever its target is, which may perfectly well be
	// negative; holding it at zero would silently change the mean it reports.
	//
	// Per state rather than per block, because the constraint *is* per state:
	// one nuclide of one compartment is one of them, and a daughter that dips
	// below zero while its parent is being integrated hard is exactly the cell
	// to let go of while the rest of the model keeps the floor. The flag is
	// read the way the tolerance beside it is -- the index's own value, then
	// the block's.
	//
	// Over all of it sits one switch. Ecolego's `saturation-enabled`, which
	// `JavaSimulator.createNonNegative` reads before it looks at a compartment
	// at all -- `if (!settings.getSetting(SATURATION_ENABLED)) return null;` --
	// and off, the solver is handed nothing and no state is held however each
	// one is set. Turned off here, the per-compartment flags are left exactly
	// as they are and simply not consulted, so turning it back on restores what
	// the model said rather than whatever was last edited.
	const nonNegative = new Array(nstate).fill(false);
	if (project.simulation.non_negative !== false) {
		for (const s of states) {
			// The inventories inside waste packages are inventories: floored
			// like a compartment's, by the block's own switch.
			if (s.kind !== 'compartment' && s.kind !== 'waste_package') continue;
			for (let i = 0; i < s.width; i++) {
				const v = valueAt(
					s.block, 'non_negative', tupleByList(system.layout.indexSpace, s.dims, i),
				);
				nonNegative[s.base + i] = v !== false;
			}
		}
	}

	const abstol = absoluteTolerance(project, system.layout);

	/**
	 * The solver's own steps, when those are what is wanted.
	 *
	 * A grid asks the solver to interpolate onto times somebody chose in
	 * advance, and choosing them well over a run of a hundred thousand years
	 * is the hard part -- everything that happens in the first year of a
	 * logarithmic grid starting at 1 is between two points. The solver has
	 * already solved that problem: it takes small steps where the answer is
	 * moving and large ones where it is not, which is exactly the distribution
	 * a result wants to be reported on.
	 *
	 * Every solver here already announces each accepted step, because the
	 * blocks that remember need to see them -- so this needs nothing from the
	 * solvers at all: the grid becomes the two ends of the run, and what comes
	 * back is thrown away in favour of what was collected on the way. The
	 * step *is* the output, not an interpolation onto it.
	 *
	 * Ecolego has no such mode; see INTERNALS.md.
	 */
	/**
	 * Where the output times come from, for *this* run.
	 *
	 * The model's own setting, unless the caller says otherwise. `onGrid` is
	 * for a probabilistic run: a thousand realisations each take their own
	 * steps, so there is no shared axis to read a percentile down, and the
	 * sample has to be reported on the grid whatever the model asked for. The
	 * solver is then given the grid and answers at exactly those times out of
	 * its own interpolant -- which is the accurate way to do it, and it also
	 * skips collecting, thinning and storing a quarter of a million steps that
	 * would be thrown away.
	 *
	 * Blocks that remember still see every accepted step: `system.storeStep`
	 * is wired below whether or not the steps are collected as *output*.
	 */
	const steps = project.solverPoints && !opts.onGrid
		? { t: [], y: [], stride: 1, seen: 0, last: -Infinity }
		: null;
	/**
	 * What the solver is asked for: the two ends, when it is choosing.
	 *
	 * Not the grid. A grid biases the solver's own first step -- dp45 takes
	 * `|tspan[1] - tspan[0]|` as its opening guess, and the first gap of a
	 * logarithmic grid starting at zero is the whole first year -- and every
	 * point of it would be discarded anyway. Two ends is the usual way of saying
	 * a two-element tspan, and it is what "let the solver choose" has to mean.
	 */
	// `both` keeps the grid *and* collects the steps: the solver has to be
	// asked for the specified times, or there would be nothing to merge them
	// with.
	const span = steps && project.outputMode === 'solver'
		? Float64Array.from([grid[0], grid[grid.length - 1]])
		: grid;
	const collect = steps
		? (t, y) => {
			// Monotone and without repeats: a solver that restarts at an event
			// re-announces the point it restarted from.
			if (!(t > steps.last)) return;
			steps.last = t;
			// Every stride-th step, and the stride doubles as soon as twice
			// the budget has been kept. Thinned *while* collecting, not after:
			// an explicit solver on a long run is stability-limited to a fixed
			// step -- a quarter of a million of them over a million years --
			// and keeping every one of a sixteen-state model is thirty
			// megabytes for a chart that cannot draw them.
			if (steps.seen++ % steps.stride) return;
			steps.t.push(t);
			steps.y.push(Float64Array.from(y));
			if (steps.t.length >= MAX_SOLVER_POINTS * 2) {
				let kept = 0;
				for (let j = 0; j < steps.t.length; j += 2, kept++) {
					steps.t[kept] = steps.t[j];
					steps.y[kept] = steps.y[j];
				}
				steps.t.length = kept;
				steps.y.length = kept;
				steps.stride *= 2;
			}
		}
		: null;

	const solveStart = now();
	let solution;

	// A model with no compartments has nothing to integrate: it reads a
	// released inventory, or a measured series, and works out a dose. Ecolego
	// runs these too -- 15 of the 71 real projects tested here are exactly
	// this shape. So the algebraic blocks are evaluated straight onto the
	// output grid, in the same dependency order, with the same clock.
	if (nstate === 0) {
		const empty = new Float64Array(0);
		solution = {
			t: grid,
			y: grid.map(() => empty),
			stats: {
				solver: null,
				integrated: false,
				points: grid.length,
			},
		};
		// The blocks that remember have to be told about the passage of time,
		// even here. A solver announces each accepted step and their histories
		// fill up as it goes; with nothing to integrate there are no steps, so
		// the output grid *is* the sequence of instants and it is walked in
		// order for them. Without this a min/max in a model with no
		// compartments reported its target's current value rather than the
		// extreme -- the peak dose of a post-processing model, which is the
		// one number that shape of model exists to produce, silently followed
		// the dose back down.
		if (system.storeStep) {
			system.primeRecorders?.(grid[0], empty);
			for (let i = 0; i < grid.length; i++) system.storeStep(grid[i], empty);
		}
		if (opts.onProgress) opts.onProgress(1);
		if (opts.signal?.aborted) throw new Error('Cancelled');
		return finish(solveStart);
	}

	const solverId = project.simulation.solver;
	const solver = solverFor(solverId);
	if (!solver) {
		// Two different failures wear the same face, and the fix for one is
		// nothing like the fix for the other.
		//
		// If the catalogue has never heard of the id, the model names a solver
		// that does not exist. But if the catalogue lists it and this function
		// cannot dispatch it, then solvers.js and this file came from different
		// versions of the application -- which in a browser means one of them
		// was served from the cache. That is not a hypothetical: a static
		// server that sends no cache headers lets Chromium heuristically cache
		// ES modules, and it will happily hold one module back while another is
		// fetched fresh.
		if (SOLVER_IDS.includes(solverId)) {
			throw new Error(
				`The solver list offers '${solverId}' but this copy of the simulation `
				+ `engine cannot run it. The two disagree, which means the browser is `
				+ `mixing old and new code: one file came from its cache. Reload `
				+ `ignoring the cache — ⌘⇧R on a Mac, Ctrl⇧R elsewhere. `
				+ `If it comes back, the pages are being served by something that `
				+ `caches; use the server in the project folder, which does not: `
				+ `python3 serve.py 8080`,
			);
		}
		throw new Error(
			`Unknown solver '${solverId}'. Available: `
			+ `${SOLVER_IDS.map(solverName).join(', ')}.`,
		);
	}

	// The blocks that remember start each run empty, and are filled as the
	// solver accepts steps.
	system.primeRecorders?.(grid[0], y0);

	const sim = project.simulation;
	const solverOpts = {
		rtol: project.simulation.rtol,
		// A number when nothing asked for otherwise, a per-state array when
		// something did; every solver here takes either.
		abstol,
		// Generated from the equations; absent when the model uses a
		// function with no derivative rule, in which case the solvers
		// difference it as they always did.
		jacobian: !system.jacobian?.available ? null
			// Asked to difference it (`Jacobian: finite differences`): the
			// generated pattern and its colouring, and never a value. Every
			// solver here differences through the pattern when `evaluate`
			// answers null, so this is facsimile.html's "differenced through
			// its pattern" -- with no dense rows to fall back on either. Never
			// constant, even for a linear model whose generated one is: a
			// difference taken once, at a start where most of the state is
			// empty, loses entries to rounding and would be kept for the whole
			// run (the bundled far field then never finishes). Re-formed when
			// Newton stalls, as a differenced Jacobian always has been.
			: sim.jacobian === 'numeric'
				? { pattern: system.jacobian.pattern, groups: system.jacobian.groups,
					constant: false, evaluate: () => null }
				: system.jacobian,
		nonNegative,
		// Let each component's absolute tolerance follow its own history
		// upwards. ndf only -- it is a property of the NDF error test, and
		// the other two solvers have no equivalent. See ../ode/solvers/ndf.js.
		autoUpdateAbsTol: project.simulation.auto_abstol === true,
		// The solver's own settings. Which of these the chosen solver reads is
		// in SOLVER_OPTIONS (../ode/solvers.js); the ones it does not are
		// simply absent from its options, and the interface does not offer
		// them. `max_step` and `initial_step` were settings of the model, in
		// the fingerprint, editable in the file -- and reached no solver at
		// all until this: a run with one set was identical to a run without.
		hmax: sim.max_step > 0 ? sim.max_step : undefined,
		h0: sim.initial_step > 0 ? sim.initial_step : undefined,
		maxSteps: sim.max_steps,
		maxOrder: sim.max_order,
		minOrder: sim.min_order,
		// Every κ zero: the NDF as the plain BDFs, and QNDF as QBDF. Read by
		// those two only; see SOLVER_OPTIONS in ../ode/solvers.js.
		bdf: sim.bdf === true,
		normControl: sim.norm_control === true,
		errorNorm: sim.error_norm,
		newtonKappa: sim.newton_kappa,
		stagnationTol: sim.stagnation_tol,
		maxJacAge: sim.max_jac_age,
		belowTolRun: sim.below_tol_run,
		matrix: sim.matrix,
		// Two things may want to see each accepted step: the blocks that
		// remember, and the collector above. Chained rather than one or the
		// other, since a model can perfectly well want both.
		onAccepted: collect && system.storeStep
			? (t, y) => { system.storeStep(t, y); collect(t, y); }
			: collect ?? system.storeStep ?? undefined,
		// The blocks that remember see the requested times as well as the
		// steps: a solver crossing a whole output interval in one step would
		// otherwise leave a min/max blind to the extreme the table reports
		// at that time. A repeat of a time already stored overwrites it.
		onOutput: system.storeStep ?? undefined,
		// Only the two ends of the solution are read back when the points
		// come from `onAccepted` above -- see fromSteps -- so the solver is
		// told not to build the rest. dp45 and ros23 size their output by
		// the tspan and never had the problem; ndf appends a row per step,
		// which on a long stiff run is the largest allocation in the program
		// and every byte of it was discarded.
		endsOnly: !!steps && project.outputMode === 'solver',
		events: system.events ?? undefined,
		onStep: opts.onProgress
			? (fraction, _n, at) => {
				if (opts.signal?.aborted) return false;
				// The clock as well as the fraction: see `onStep` in
				// ../ode/solvers/ndf.js. A run made of several segments -- one per
				// event -- reports a fraction of the segment it is in, so the
				// clock is the only part of this that means the same thing
				// from one end of a run to the other.
				opts.onProgress(fraction, at);
				return true;
			}
			: undefined,
	};

	// The times the model says it changes at. The solver is restarted at each
	// of them rather than allowed to step across: see ../domain/switchtimes.js.
	// Waste packages that fail all at one time are a jump in the state at that
	// time, and the time is a corner like any other. Read off the slot now,
	// not at the build: a probabilistic run moves the parameter behind it.
	// ...and a disruptive event's occurrences, drawn for this realisation or
	// declared at a time. One jump per occurrence.
	const jumps = (system.jumps ?? []).flatMap((j) => (j.slot != null
		? [{ ...j, at: system.slotValue(j.slot) }]
		: (j.times?.() ?? []).map((at) => ({ ...j, at }))));
	for (const j of jumps) {
		if (j.slot == null) continue; // drawn: a number by construction
		// A slot that moves with the clock or the state holds *a* number after
		// the build, not *the* number: only one worked out once for the run
		// is a time the packages can fail at.
		if (!Number.isFinite(j.at) || system.layout.slotClass?.[j.slot] !== 0) {
			throw new BuildError(
				`The time every package fails has to come to a number before the run; `
				+ `'${j.name}' says '${j.text}'.`, j.name,
			);
		}
	}
	const inside = (t) => t > span[0] && t < span[span.length - 1];
	const breaks = [...new Set([...switchTimes(project), ...jumps.map((j) => j.at)])]
		.filter(inside).sort((a, b) => a - b);
	// What happens to the state at a corner: every jump that falls there,
	// applied to a copy so that the row reported *at* the corner is the one
	// before the change, as the segment semantics say.
	let jumped = 0;
	const jumpAt = jumps.length ? (t, y) => {
		const due = jumps.filter((j) => j.at === t);
		if (!due.length) return y;
		const next = Float64Array.from(y);
		for (const j of due) j.apply(next);
		jumped += due.length;
		return next;
	} : null;
	// How often the clock-only algebra is really worth recomputing. Anchored at
	// the start of each segment, so an interval never spans a corner the model
	// declared -- see `useClockInterpolation` in ./builder.js.
	const minChange = Number(project.simulation.min_change_time ?? 0);
	const solveSpan = (grid2, start) => {
		system.useClockInterpolation?.(minChange, grid2[0]);
		return system.events
			? solveWithEvents(system, solver, grid2, start, solverOpts)
			: solver(system.dydt, grid2, start, solverOpts);
	};

	try {
		solution = breaks.length
			? solveAcrossBreaks(solveSpan, span, y0, breaks, jumpAt)
			: solveSpan(span, y0);
		// How many times the state was jumped: package failures at a time and
		// disruptive events, for the status line and the log.
		if (jumps.length && solution.stats) solution.stats.jumps = jumped;
		// What was collected, rather than the two ends the solver was asked
		// for. Thinned if it took a great many steps: 20,000 points across 32
		// series is a chart that redraws slowly on every hover, and the shape
		// of the answer survives keeping every k-th of them.
		if (steps) {
			solution = project.outputMode === 'both'
				? mergeSteps(solution, steps)
				: fromSteps(steps, solution);
		}
	} catch (e) {
		if (e instanceof SolverError) {
			const hints = [];
			if (solverId === 'dp45') {
				hints.push(`This model looks stiff; switch the solver to `
					+ `"${solverLabel('ndf')}" or "${solverLabel('ros23')}".`);
			}
			// A non-negativity constraint that actually binds makes the
			// derivative discontinuous at zero, and only ndf carries that:
			// its Newton iteration lands on the kink, where a one-step method's
			// stages straddle it and disagree by the whole jump, so no step
			// size passes the error test -- the constraint is offered on ndf
			// and not on ros23 for the same reason. Worth saying, because the
			// failure surfaces as an unreachable tolerance or a stall and reads
			// like a stiffness problem. Unless the solver has already said it,
			// which ros23 does when it stops at a held state.
			const saidAlready = /cannot go negative/.test(e.message);
			// The NDF integrator carries it with or without its BDF switch: it is
			// the Newton iteration that lands on the kink, and kappa does not
			// change that.
			const bindsHere = solverId === 'ndf';
			if (!saidAlready && !bindsHere && nonNegative.some(Boolean)) {
				hints.push(`If a compartment reaches zero at this time, its `
					+ `"cannot go negative" setting is the likely cause: `
					+ `"${solverLabel('ndf')}" carries a binding constraint, and `
					+ `turning the setting off on that compartment shows what the `
					+ `model is really doing.`);
			}
			if (hints.length) e.hint = hints.join(' ');
		}
		throw e;
	}
	return finish(solveStart);

	/**
	 * The algebraic blocks at every stored time point.
	 *
	 * The solver carries only the state vector, so everything derived from it
	 * -- expressions, transfer rates, lookup tables, reductions -- is worked
	 * out afterwards, at the times the results are reported for. For a model
	 * with no state vector this is the whole calculation.
	 */
	function finish(startedAt) {
		const solveMs = now() - startedAt;
		// Only the states are kept. Every other series -- an expression, a
		// rate, a table read at the clock, a reduction, what a recorder holds
		// -- is worked out from `(t, y)` when it is asked for, one algebraic
		// pass per row: see `Results.seriesMany`. Storing them all here as
		// well was a dense table of every value at every time, and on a
		// landscape model of 201,004 algebraic values over 498 times that is
		// 800 MB before the states or a single chart.
		return new Results({
			project, system, solution,
			timing: { buildMs, solveMs, totalMs: now() - t0 },
		});
	}
}

/**
 * How many of the solver's own steps one run may report.
 *
 * Not a limit on the solve -- the solver takes whatever steps it needs -- but
 * on how many of them are kept as output. A stiff run over a hundred thousand
 * years can take tens of thousands, and every one of them is a row in the
 * table and a point in every series on the chart.
 */
const MAX_SOLVER_POINTS = 4000;

/**
 * The collected steps as a solution.
 *
 * The two ends come from what the solver itself returned -- it was asked for
 * exactly those two -- so the first row is the state the run started from and
 * the last is the state it ended at, whether or not the thinning happened to
 * keep the final step.
 */
function fromSteps(steps, solution) {
	const t = [solution.t[0]];
	const y = [solution.y[0]];
	for (let i = 0; i < steps.t.length; i++) {
		if (!(steps.t[i] > t[t.length - 1])) continue;
		t.push(steps.t[i]);
		y.push(steps.y[i]);
	}
	const endT = solution.t[solution.t.length - 1];
	if (endT > t[t.length - 1]) {
		t.push(endT);
		y.push(solution.y[solution.y.length - 1]);
	}
	return {
		...solution,
		t: Float64Array.from(t),
		y,
		stats: {
			...(solution.stats ?? {}),
			points: t.length,
			// Said, not hidden: a thinned result is not every step the solver
			// took, and the footer is where that belongs.
			solverPoints: steps.seen,
			thinnedBy: steps.stride > 1 ? steps.stride : 0,
		},
	};
}

/**
 * The grid and the collected steps, in one list.
 *
 * Ecolego's "Produce additional output": the times somebody asked for, plus
 * every step the solver took on the way between them. Merged rather than
 * concatenated, because the two sets meet -- a step landing on a grid point
 * would otherwise be two rows for one time -- and the states at a shared time
 * are the same state either way, so the first of them wins.
 */
function mergeSteps(solution, steps) {
	const t = [];
	const y = [];
	let i = 0;
	let j = 0;
	const push = (tv, yv) => {
		const last = t[t.length - 1];
		// The same tolerance the series combiner uses, for the same reason.
		if (last !== undefined && Math.abs(tv - last) <= Math.abs(last || tv) * 1e-9) return;
		t.push(tv);
		y.push(yv);
	};
	while (i < solution.t.length || j < steps.t.length) {
		const a = i < solution.t.length ? solution.t[i] : Infinity;
		const b = j < steps.t.length ? steps.t[j] : Infinity;
		if (a <= b) { push(a, solution.y[i]); i++; } else { push(b, steps.y[j]); j++; }
	}
	return {
		...solution,
		t: Float64Array.from(t),
		y,
		stats: {
			...(solution.stats ?? {}),
			points: t.length,
			solverPoints: steps.seen,
			thinnedBy: steps.stride > 1 ? steps.stride : 0,
		},
	};
}

/**
 * Integrates in segments, restarting at every time the model declared.
 *
 * The same treatment a discrete event gets and for the same reason: a corner
 * is a place where the model has changed, and a solver that carried its step
 * size and its difference table over one would be fitting a polynomial through
 * a discontinuity. Restarting is not the cost worth avoiding.
 *
 * The break itself is an output point of the segment that ends at it, so the
 * value *at* the corner is the one before the change -- which is what "the
 * source switches on at 1,000" means. The next segment opens there and its
 * first row is dropped as a duplicate, exactly as the event path does.
 *
 * @param {(grid: Float64Array, y0: Float64Array) => object} solve one segment
 * @param {Float64Array} grid  what was asked for
 * @param {Float64Array} y0
 * @param {number[]} breaks    ascending, strictly inside the run
 * @param {((t: number, y: Float64Array) => Float64Array)|null} [jumpAt]  what
 *   the state becomes at a corner -- a set of waste packages failing all at
 *   once -- given what it was; null when nothing jumps
 */
function solveAcrossBreaks(solve, grid, y0, breaks, jumpAt = null) {
	const times = [];
	const rows = [];
	const stats = { nsteps: 0, nfailed: 0, nfevals: 0, restarts: 0, breaks: breaks.length };
	const ends = [...breaks, grid[grid.length - 1]];

	let y = y0;
	let at = grid[0];
	let next = 0;
	for (const end of ends) {
		if (!(end > at)) continue;
		// The output points of this segment, and the break as its last point.
		const inside = [at];
		while (next < grid.length && grid[next] <= at) next++;
		while (next < grid.length && grid[next] < end) inside.push(grid[next++]);
		inside.push(end);

		const seg = solve(Float64Array.from(inside), y);
		for (let i = 0; i < seg.t.length; i++) {
			// The seam: this segment opens where the last one closed, and
			// nothing about the state changed there.
			if (i === 0 && times.length && seg.t[0] === times[times.length - 1]) continue;
			times.push(seg.t[i]);
			rows.push(seg.y[i]);
		}
		for (const k of ['nsteps', 'nfailed', 'nfevals', 'restarts']) {
			stats[k] += seg.stats?.[k] ?? 0;
		}
		// The rest of what a segment reports, as the event path keeps it: the
		// solver's name and shape once, the counts summed, the held-at-zero
		// tally per state added up. These were dropped, so a model with a
		// switch time showed "solver undefined" and never a held state.
		if (seg.stats) {
			if (!stats.solver && seg.stats.solver) stats.solver = seg.stats.solver;
			if (seg.stats.sparse !== undefined) stats.sparse = seg.stats.sparse;
			if (seg.stats.fill !== undefined) stats.fill = seg.stats.fill;
			for (const k of ['npds', 'ndecomps', 'negative', 'events']) {
				if (seg.stats[k] !== undefined) stats[k] = (stats[k] ?? 0) + seg.stats[k];
			}
			if (seg.stats.held) {
				if (!stats.held) stats.held = new Int32Array(seg.stats.held.length);
				for (let i = 0; i < seg.stats.held.length; i++) stats.held[i] += seg.stats.held[i];
			}
		}
		y = seg.y[seg.y.length - 1];
		at = seg.t[seg.t.length - 1];
		if (jumpAt) y = jumpAt(at, y);
	}
	stats.restarts += ends.length - 1;
	return { t: Float64Array.from(times), y: rows, stats };
}

/** How many terminal events one run may hit before something is clearly wrong. */
const MAX_EVENTS = 10000;

/**
 * Integrates a model that has discrete events, in segments.
 *
 * Every discrete event is terminal: the solver stops at the crossing,
 * applies whatever the event does and starts again from there. That is what
 * this does -- the solver returns as soon as it locates a crossing, the event
 * is applied to the blocks watching for it, and a fresh solve carries on from
 * the event over the output points that are left.
 *
 * Restarting is not a cost worth avoiding: an event is a discontinuity, and a
 * solver that carried its step size and its difference table across one would
 * be extrapolating through a model that has changed.
 */
function solveWithEvents(system, solver, grid, y0, opts) {
	const events = system.events;
	const last = grid[grid.length - 1];
	const times = [];
	const rows = [];
	const stats = { nsteps: 0, nfailed: 0, nfevals: 0, events: 0, restarts: 0 };

	let t = grid[0];
	let y = y0;
	let next = 0;

	for (let guard = 0; ; guard++) {
		if (guard > MAX_EVENTS) {
			throw new Error(
				`The simulation hit ${MAX_EVENTS} discrete events without reaching `
				+ `t=${last}. An event whose two expressions stay equal fires again `
				+ `the moment the solver restarts; check the crossing direction.`,
			);
		}
		while (next < grid.length && grid[next] <= t) next++;
		if (next >= grid.length) break;

		const span = new Float64Array(grid.length - next + 1);
		span[0] = t;
		span.set(grid.subarray(next), 1);

		if (globalThis.__SEG) {
			const m = process.memoryUsage();
			console.log(`  segment ${guard} at t=${t.toFixed(3)}  heap `
				+ `${Math.round(m.heapUsed / 1048576)} MB  rows ${rows.length}`);
		}
		const seg = solver(system.dydt, span, y, opts);

		for (let i = 0; i < seg.t.length; i++) {
			// The seam: the segment opens at the time the last one closed on,
			// and nothing about the state changed there.
			if (i === 0 && times.length && seg.t[0] === times[times.length - 1]) continue;
			times.push(seg.t[i]);
			rows.push(seg.y[i]);
		}
		stats.nsteps += seg.stats.nsteps ?? 0;
		stats.nfailed += seg.stats.nfailed ?? 0;
		stats.nfevals += seg.stats.nfevals ?? 0;
		if (!stats.solver) Object.assign(stats, { solver: seg.stats.solver });
		stats.sparse = seg.stats.sparse ?? stats.sparse;
		// The constraint's account, summed over the segments.
		stats.negative = (stats.negative ?? 0) + (seg.stats.negative ?? 0);
		if (seg.stats.held) {
			if (!stats.held) stats.held = new Int32Array(seg.stats.held.length);
			for (let i = 0; i < seg.stats.held.length; i++) stats.held[i] += seg.stats.held[i];
		}

		if (!seg.stopped) break;
		t = seg.stopped.t;
		y = seg.stopped.y;
		events.fire(seg.stopped.which, t, y);
		// The blocks that remember see the event's own instant too, so that a
		// min/max reset at it does not immediately record the value it just
		// cleared.
		system.storeStep?.(t, y);
		stats.events += seg.stopped.which.length;
		stats.restarts++;
	}

	return {
		t: Float64Array.from(times),
		y: rows,
		stats,
	};
}

/**
 * The series one layout entry stands for: one per index tuple, or one flat.
 *
 * Lifted out of `Results.outputs` so that the editor can ask the same question
 * about one block without a run behind it -- see `sim/atstart.js`. What a
 * block is *called*, what it is measured in and which material it carries are
 * decided here and nowhere else: a value shown in the settings dialog and the
 * same value in the table have to read as the same thing, and two ways of
 * labelling it would eventually disagree.
 *
 * @param layout the system layout
 * @param entry one of `layout.states`, `.algebraic` or `.parameters`
 * @param {string} kind what to call it
 * @param {'y'|'X'|'P'} source which row array holds it
 */
export function describeEntry(layout, entry, kind, source) {
	const { indexSpace, materialUnits } = layout;
	const dims = entry.dims ?? [];
	// A waste package's inventories are in the inventory unit while the
	// block's own unit is its release's, so the entry may say its own.
	const unit = entry.unit ?? entry.block?.unit ?? '';
	const still = (offset) => (timeDependentOf(layout, kind, source, offset) ? {} : { timeDependent: false });
	if (!dims.length) {
		return [{
			kind, block: entry.name, nuclide: null, index: null, dims: [],
			label: entry.name, unit, source, offset: entry.base, ...still(entry.base),
		}];
	}
	const md = materialDim(layout, dims);
	const out = [];
	for (let off = 0; off < entry.width; off++) {
		const names = indexSpace.tupleAt(dims, off);
		const material = md ? names[dims.indexOf(md)] ?? null : null;
		out.push({
			kind, block: entry.name, nuclide: material,
			index: names, dims,
			label: `${entry.name} [${names.join(', ')}]`,
			// A block that states a unit means it at every index; one that
			// states none takes each index from the material there, which is
			// Ecolego's auto-managed unit -- `Compartment.getUnit(indices)`
			// reads the material at the index and returns its unit. So a
			// compartment on the catalogue of a model that carries stable
			// carbon reads kgC at that index and Bq at its radionuclides.
			// An event is the exception: its value is the crossing function,
			// `first - second`, a difference between two expressions whose
			// quantity nothing here knows. Falling back for it labelled a
			// dose-minus-a-limit as becquerels, in the legend, the table and
			// the CSV -- and, once the editor started showing what a block
			// comes to at the start, under the boxes as well.
			unit: unit || (material && kind !== 'trigger'
				? materialUnits?.get(material) ?? '' : ''),
			source, offset: entry.base + off, ...still(entry.base + off),
		});
	}
	return out;
}

/**
 * The kinds whose value is a history -- what the run did before now -- and so
 * never a constant of the run, whatever they read: the recorders, a trigger
 * and a disruptive event.
 */
const HISTORY_KINDS = new Set(['min_max', 'running_mean', 'snapshot', 'delay', 'trigger', 'event']);

/**
 * Whether a series can change over the run. Not for a parameter or a table
 * point, each a slot of `P`, nor for an expression the builder works out once
 * for the run (`slotClass` 0: it reads neither the clock nor the state). A
 * state always can, even one that happens to stay where it started: it is a
 * quantity that moves, and a chart of its siblings is where it belongs. A
 * result file writes a series that cannot as one value, not as the same number
 * at every output time (see ../io/resultfile.js); a descriptor says so with
 * `timeDependent: false`, and says nothing otherwise.
 */
export function timeDependentOf(layout, kind, source, offset) {
	if (source === 'P') return false;
	if (source === 'X' && !HISTORY_KINDS.has(kind)) return layout.slotClass?.[offset] !== 0;
	return true;
}

/**
 * Which of a block's dimensions the materials are, or null.
 *
 * Not one list for the whole model: a model carries a catalogue and the
 * radionuclide sub-set of it, and two compartments may be indexed by different
 * ones. Asking for one name gave `nuclide: null` for every series of every
 * block indexed by the other, which is what a chart filters on.
 */
function materialDim(layout, dims) {
	const { indexSpace, materialList } = layout;
	const materialRoot = materialList ? indexSpace.get(materialList).rootName : null;
	return dims.find((d) => {
		if (!materialRoot || !indexSpace.has(d)) return false;
		const l = indexSpace.get(d);
		return !l.mapping && l.rootName === materialRoot;
	}) ?? null;
}

/**
 * The list a lookup table's point is indexed along, beside the table's own
 * lists: the time the point sits at. Not one of the model's index lists -- a
 * name for the chart's index filter to offer the times under.
 */
export const POINT_LIST = 'Time point';

/**
 * A series for each point of a lookup table that carries a distribution.
 *
 * Such a point is an input a probabilistic run draws once per realisation, a
 * slot of `P` as a parameter's value is, so it is described the way a
 * parameter's series is: a constant over the run, read from that slot. The
 * time it sits at is one more index (`POINT_LIST`): `SRF [@8700]` is the table
 * `SRF` at year 8,700, and `SRF [Cs-137, @8700]` the same at Cs-137. That is
 * how a sample keeps what it drew there (`inputs` in ./probabilistic.js). A
 * point without a distribution is the table and nothing more, and has none.
 */
export function lookupPointOutputs(layout) {
	const { materialUnits } = layout;
	const out = [];
	for (const pt of layout.lookupPoints ?? []) {
		const dims = pt.dims ?? [];
		const names = dims.map((d) => pt.index?.[d]);
		const md = materialDim(layout, dims);
		const material = md ? pt.index?.[md] ?? null : null;
		const at = `@${pt.at}`;
		out.push({
			kind: 'lookup', block: pt.name, nuclide: material,
			index: [...names, at], dims: [...dims, POINT_LIST],
			label: `${pt.name} [${[...names, at].join(', ')}]`,
			unit: pt.unit || (material ? materialUnits?.get(material) ?? '' : ''),
			source: 'P', offset: pt.slot, timeDependent: false,
		});
	}
	return out;
}

// Re-exported: this is where everything that writes CSV from a `Results` in
// this process has always found it, and the rule itself is in ../io/csv.js so
// that the page -- which has no `Results`, only columns from its worker --
// can reach it too.
export { csvCell };

/**
 * Every series a run of this system can report, one per block per index
 * tuple.
 *
 * A function of the system and the project, and of no solution: none is read
 * and none has to exist. That is what lets the endpoint picker offer its list
 * before the model has been run -- which is the case it is most for, since the
 * whole point of choosing endpoints is to decide what a run will keep before
 * it has kept everything.
 */
export function outputsOf(system, project) {
	const out = [];
	const {
		states, algebraic, parameters, indexSpace, materialList,
	} = system.layout;
	// Appended one at a time rather than spread into `push`: a block can
	// carry a value per index, and a parameter over two lists of four
	// hundred is 160,000 of them -- past about 125,000 arguments V8 throws
	// `RangeError: Maximum call stack size exceeded`, which would take the
	// chart, the table and the CSV down for a run that had completed.
	const expand = (entry, kind, source) => {
		for (const d of describeEntry(system.layout, entry, kind, source)) out.push(d);
	};

	for (const s of states) {
		// A running mean's integral is machinery, not a result: the block's
		// own value is an algebraic slot like any other.
		if (s.kind === 'compartment') {
			// An element in the middle of a transport chain is a state
			// the run has and the model does not: its first and last are
			// Begin and End, and those are reported.
			if (!s.hidden) expand(s, 'compartment', 'y');
			continue;
		}
		// A far-field path holds one inventory per cell per nuclide, which
		// is hundreds of series for one block. What is always worth having
		// is the total it holds -- the other half of a mass balance, since
		// the block's own value is only what is leaving it. The cells
		// themselves are there when the block asks for them.
		if (s.kind === 'farfield') {
			for (const o of farfieldOutputs(s, indexSpace, materialList)) out.push(o);
		}
		// Waste packages: what is still inside intact packages, and what
		// the failed ones have exposed. The block's own value -- the
		// release -- is an algebraic slot listed with every other block's.
		if (s.kind === 'waste_package') expand(s, 'waste_inventory', 'y');
		// A disruptive event's value is its count of occurrences -- the
		// expected number, or the number a realisation drew.
		if (s.kind === 'event') expand(s, 'event', 'y');
	}
	for (const a of algebraic) {
		if (a.kind === 'inflow') continue; // internal
		// The slots holding a remembering block's target and its parameters
		// are machinery too, and are named with a `#` so that they cannot
		// be mistaken for a block.
		if (a.hidden) continue;
		expand(a, a.kind, 'X');
	}
	// Parameters, last, because they are the least interesting line on any
	// chart and the most numerous in a real model. They are constants, so
	// each is a flat line -- which is exactly why it is worth being able to
	// put one on the chart: a rate constant drawn beside the flux it scales
	// says whether the flux is following the constant or the inventory, and
	// a limit drawn beside a dose says whether the dose crosses it.
	for (const p of parameters ?? []) expand(p, 'parameter', 'P');
	// And the points of lookup tables that carry a spread, each a constant of
	// its own like a parameter -- see `lookupPointOutputs`.
	for (const o of lookupPointOutputs(system.layout)) out.push(o);

	// And the numbers read off the finished curves: the peak, the year it
	// peaked, the total. They are outputs like any other -- one more line
	// on the chart, one more column in an export -- and they cost the run
	// nothing, because they are worked out from `(t, y)` when something
	// asks. See ../domain/derived.js for why that is not what the
	// recorders do.
	// A derived value may be of another derived value -- the peak of an
	// annual mean is the number a limit is written against -- so they are
	// admitted in passes until none is left that can be, whatever order
	// they were written in. One that names nothing the run produces, or
	// only itself through a cycle, is left out; `derivedProblems` says so.
	const known = new Set(out.map((o) => o.label));
	let pending = derivedBlocks(project);
	for (let pass = 0; pending.length && pass <= pending.length; pass++) {
		const later = [];
		for (const d of pending) {
			if (!known.has(d.of) || known.has(String(d.name))) { later.push(d); continue; }
			out.push({
				kind: 'derived',
				source: 'D',
				block: String(d.name),
				label: String(d.name),
				unit: derivedUnitFor(d.kind, out.find((o) => o.label === d.of)?.unit,
					project.simulation?.time_unit ?? 'year'),
				derived: { kind: d.kind, of: d.of, at: Number(d.at), period: Number(d.period) },
				dims: [],
				index: null,
				// The peak, the year it peaked, the value at one time: one
				// number for the run, drawn as a flat line. The integral and the
				// per-period ones are curves.
				...(derivedIsSeries(d.kind) ? {} : { timeDependent: false }),
			});
			known.add(String(d.name));
		}
		if (later.length === pending.length) break;
		pending = later;
	}
	return out;
}

/** Result accessor: one series per output, read on demand. */
export class Results {
	constructor({ project, system, solution, timing }) {
		this.project = project;
		this.system = system;
		this.t = solution.t;
		this.y = solution.y;
		this.stats = solution.stats;
		this.timing = timing;
	}

	get nuclides() { return this.system.layout.nuclides; }

	/**
	 * The compartments "cannot go negative" held at zero, and for what share
	 * of the solver's steps.
	 *
	 * A held state is not a number the equations produced: the model was
	 * pushing it below zero and the constraint kept it there, which is
	 * the "cannot go negative" constraint, and is usually a modelling error
	 * -- a rate with the wrong sign, a transfer draining what was never
	 * filled -- being hidden. The solvers count it (`stats.held`, per state,
	 * for the steps the hold moved the state by more than its tolerance) so
	 * that the footer can say so instead of showing the flat line as a
	 * result. Empty when nothing was held, which is most runs.
	 *
	 * @returns {Array<{label: string, steps: number, fraction: number}>}
	 *   most-held first
	 */
	heldAtZero() {
		const held = this.stats.held;
		if (!held || !this.stats.nsteps) return [];
		const out = [];
		for (let i = 0; i < held.length; i++) {
			if (!held[i]) continue;
			const state = (this.system.layout.states ?? []).find(
				(s) => i >= s.base && i < s.base + s.width,
			);
			if (!state) continue;
			const label = state.dims?.length
				? `${state.name} [${Object.values(
					tupleByList(this.system.layout.indexSpace, state.dims, i - state.base),
				).join(', ')}]`
				: state.name;
			out.push({ label, steps: held[i], fraction: held[i] / this.stats.nsteps });
		}
		return out.sort((a, b) => b.fraction - a.fraction || a.label.localeCompare(b.label));
	}

	/**
	 * The mass-balance audit, when the run carried the budget states; null
	 * when it did not. See ../domain/massbalance.js.
	 */
	massBalance() {
		const budget = this.system.layout.budget;
		return budget ? auditBudget(budget, this.t, this.y, { rtol: this.project.simulation.rtol }) : null;
	}

	/**
	 * How df/dy was obtained, for the status line. A model the generator
	 * declined says so, with the reason, rather than silently costing more.
	 */
	get jacobian() {
		const j = this.system.jacobian;
		if (!j?.available) return { available: false, reason: j?.reason ?? null };
		// Differenced because it was asked for, through the generated pattern:
		// the same colours and non-zeros, and no generated values.
		const sim = this.project.simulation;
		if (sim.jacobian === 'numeric' && solverOptions(sim.solver ?? DEFAULT_SOLVER).includes('jacobian')) {
			return {
				available: false,
				asked: true,
				colours: j.colours,
				nnz: j.nnz,
				density: j.density,
				sparse: !!this.stats.sparse,
				fill: this.stats.fill ?? null,
			};
		}
		return {
			available: true,
			constant: j.constant,
			colours: j.colours,
			nnz: j.nnz,
			density: j.density,
			sparse: !!this.stats.sparse,
			fill: this.stats.fill ?? null,
		};
	}

	/**
	 * Every series a chart or table can show, one per block per index tuple.
	 * The label carries the full tuple, so a block indexed by two lists reads
	 * as `Soil [Cs-137, Lake]`.
	 */
	outputs() {
		return outputsOf(this.system, this.project);
	}

	/** Time series for one output descriptor. */
	series(output) {
		return this.seriesMany([output])[0];
	}

	/**
	 * Time series for several outputs at once, in the order given.
	 *
	 * Only the states were kept when the run finished; everything algebraic is
	 * worked out here from `(t, y)`, one evaluation of the whole algebraic
	 * vector per row -- a tenth of a millisecond -- with every requested value
	 * read out of it before moving on. So a chart of twelve lines costs one
	 * pass over the rows, not twelve, and a row is never evaluated at all for
	 * a request that reads only compartments and parameters.
	 *
	 * Working it out afterwards gives the same numbers the run saw. Every
	 * algebraic value is a function of the clock and the state, except what
	 * the remembering blocks hold -- and their histories are kept against the
	 * time they were recorded at, so `extreme(t, ...)`, `delayed(t, ...)` and
	 * the rest answer as of `t_i` whenever they are asked.
	 */
	seriesMany(outputs) {
		const n = this.t.length;
		const cols = outputs.map(() => new Float64Array(n));
		// The constants first: a parameter is its one value at every time.
		const live = [];
		const derived = [];
		outputs.forEach((o, k) => {
			if (o.source === 'P') cols[k].fill(this.constantOf(o));
			// A derived value is taken from another series, so it waits until
			// that one can be asked for -- after this pass, not during it.
			else if (o.source === 'D') derived.push(k);
			else live.push(k);
		});
		if (derived.length) {
			// One pass for everything they are taken from, however many of them
			// there are and however many share a source.
			const wanted = [...new Set(derived.map((k) => outputs[k].derived.of))];
			const all = this.outputs();
			const from = wanted
				.map((label) => all.find((o) => o.label === label))
				.filter(Boolean);
			const got = new Map();
			if (from.length) {
				const columns = this.seriesMany(from);
				from.forEach((o, i) => got.set(o.label, columns[i]));
			}
			for (const k of derived) {
				const { kind, of, at, period } = outputs[k].derived;
				const src = got.get(of);
				if (!src) { cols[k].fill(NaN); continue; }
				const v = reduceDerived(kind, this.t, src, { at, period });
				// A curve as it is; a single number as the flat line that is
				// the whole point of drawing it beside its own series.
				if (v instanceof Float64Array) cols[k].set(v.subarray(0, n));
				else cols[k].fill(v);
			}
		}
		if (!live.length) return cols;
		const needsX = live.some((k) => outputs[k].source !== 'y');
		for (let i = 0; i < n; i++) {
			const y = this.y[i];
			const X = needsX ? this.system.evaluateAlgebraic(this.t[i], y) : null;
			for (const k of live) {
				const o = outputs[k];
				const rows = o.source === 'y' ? y : X;
				// A descriptor may stand for a sum of states rather than one
				// of them: what a whole far-field path holds is its cells
				// added up, and adding them here rather than in the state
				// vector keeps the sum out of the equations, where it is not
				// a quantity the model has.
				if (o.offsets) {
					let total = 0;
					for (const j of o.offsets) total += rows[j];
					cols[k][i] = total;
				} else {
					cols[k][i] = rows[o.offset];
				}
			}
		}
		return cols;
	}

	/**
	 * The one value behind a constant output, or null for one that varies.
	 *
	 * Worth having separately from `series`: a parameter indexed by nuclide
	 * and object is several hundred slots, and a column of two thousand copies
	 * of one number, several hundred times over, is megabytes of nothing to
	 * carry out of the worker.
	 */
	constantOf(output) {
		if (output.source !== 'P') return null;
		return this.system.parameterValues[output.offset];
	}

	/**
	 * Sum a compartment over its index tuples -- Ecolego's index operation.
	 * Pass `over` to sum only along particular index lists, keeping the rest.
	 */
	total(blockName, over = null) {
		const s = this.system.layout.states.find((x) => x.name === blockName);
		if (!s) throw new Error(`No compartment named '${blockName}'`);
		const { indexSpace } = this.system.layout;

		if (!over) {
			const v = new Float64Array(this.t.length);
			for (let i = 0; i < this.t.length; i++) {
				let acc = 0;
				for (let j = 0; j < s.width; j++) acc += this.y[i][s.base + j];
				v[i] = acc;
			}
			return v;
		}

		// Partial sum: collapse the named dimensions, keep the others.
		const keep = s.dims.filter((d) => !over.includes(d));
		const keepWidth = indexSpace.width(keep);
		const groups = new Map();
		for (let off = 0; off < s.width; off++) {
			const names = indexSpace.tupleAt(s.dims, off);
			const key = keep.map((d) => names[s.dims.indexOf(d)]).join('\u0000');
			if (!groups.has(key)) groups.set(key, []);
			groups.get(key).push(s.base + off);
		}
		const out = [];
		for (const [key, offsets] of groups) {
			const v = new Float64Array(this.t.length);
			for (let i = 0; i < this.t.length; i++) {
				let acc = 0;
				for (const o of offsets) acc += this.y[i][o];
				v[i] = acc;
			}
			out.push({
				index: key ? key.split('\u0000') : [],
				dims: keep,
				label: keep.length ? `${blockName} [${key.split('\u0000').join(', ')}]` : blockName,
				values: v,
			});
		}
		return keepWidth === 1 && !keep.length ? out[0].values : out;
	}

	/** Peak value and its time, the statistic an assessment table reports. */
	max(output) {
		const v = this.series(output);
		let best = -Infinity, at = this.t[0];
		for (let i = 0; i < v.length; i++) {
			if (v[i] > best) { best = v[i]; at = this.t[i]; }
		}
		return { value: best, time: at };
	}

	/**
	 * CSV export, matching the column layout of Ecolego's Excel export.
	 *
	 * Yielded a line at a time as well as returned whole (`toCSV`), because
	 * the whole is a single string and a big run makes it enormous: 200 series
	 * over 4,210 times is 16 MB, and all 1,297 series of the far-field example
	 * would be a hundred. A caller writing to a file or a stream can take the
	 * lines instead and never hold more than one.
	 */
	* csvLines(outputs = this.outputs()) {
		yield ['time', ...outputs.map((o) => csvCell(o.label))].join(',');
		const cols = this.seriesMany(outputs);
		for (let i = 0; i < this.t.length; i++) {
			const row = new Array(cols.length + 1);
			row[0] = this.t[i];
			for (let k = 0; k < cols.length; k++) row[k + 1] = cols[k][i];
			yield row.join(',');
		}
	}

	toCSV(outputs = this.outputs()) {
		const lines = [];
		for (const line of this.csvLines(outputs)) lines.push(line);
		return lines.join('\n');
	}
}

/**
 * What a far-field path reports.
 *
 * Its own value -- the release out of the far end -- is an algebraic slot and
 * is listed with every other block's. These are the inventories underneath it:
 * the total the path is holding, always, and one series per cell when the
 * block asks for them. A 20 x 20 path over ten nuclides is 4,200 cells, which
 * is not a list anybody can read, so `report_cells` is off unless it is
 * wanted -- and when it is, the names are the reference implementation's own:
 * `F3` is the third fracture cell, `M3_1` the first matrix layer behind it.
 */
function farfieldOutputs(entry, indexSpace, materialList) {
	const { farf, block } = entry;
	const {
		nnuc, otherDims, otherWidth, ncells, listName,
	} = farf;
	// The release is an inventory per unit time; what the cells hold is the
	// inventory itself, so the unit is that one with the time taken off.
	const unit = String(block.unit ?? '').replace(/\/[^/]*$/, '') || 'Bq';
	const cells = block.report_cells ? cellNames(block) : null;
	// A path indexed by nothing holds one quantity: no nuclide names, and no
	// index in any label.
	const names = listName ? indexSpace.indexNames(listName) : [null];
	const out = [];
	for (let o = 0; o < otherWidth; o++) {
		const others = otherDims.length ? indexSpace.tupleAt(otherDims, o) : [];
		const base = entry.base + o * ncells * nnuc;
		for (let m = 0; m < nnuc; m++) {
			const nuclide = names[m];
			// The tuple in the block's own dimension order, so a label reads
			// the way every other block's does.
			const index = [];
			let k = 0;
			for (const dim of entry.dims) {
				index.push(dim === listName ? nuclide : others[k++]);
			}
			const suffix = index.length ? ` [${index.join(', ')}]` : '';
			const offsets = new Int32Array(ncells);
			for (let cell = 0; cell < ncells; cell++) offsets[cell] = base + cell * nnuc + m;
			out.push({
				kind: 'farfield_inventory', block: `${entry.name} held`,
				nuclide: materialList ? nuclide : null,
				index: index.length ? index : null, dims: entry.dims,
				label: `${entry.name} held${suffix}`,
				unit, source: 'y', offsets,
			});
			if (!cells) continue;
			for (let cell = 0; cell < ncells; cell++) {
				out.push({
					kind: 'farfield_cell', block: `${entry.name}.${cells[cell]}`,
					nuclide: materialList ? nuclide : null,
					index: index.length ? index : null, dims: entry.dims,
					label: `${entry.name}.${cells[cell]}${suffix}`,
					unit, source: 'y', offset: base + cell * nnuc + m,
				});
			}
		}
	}
	return out;
}

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
