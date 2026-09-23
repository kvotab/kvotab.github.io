/**
 * The solver catalogue: what exists, what it is called, and what it is for.
 *
 * Two names per solver, deliberately:
 *
 *  - the **id** (`ndf`) is what the project file stores and what error
 *    messages quote. It names the method, so it is the thing to search for
 *    when comparing one run against another, and it must not drift.
 *  - the **label** (`stiff, NDF`) is what the interface shows, because what a
 *    modeller needs at the moment of choosing is whether their problem is
 *    stiff, not which formulas are underneath.
 *
 * Kept in its own module, next to the integrators but importing none of them,
 * so that the interface can list and label the solvers, and the domain layer
 * can name a default, without any of them pulling in the simulation stack --
 * builder, parser, three integrators. Runs happen in a Worker.
 */

/** In the order they should be offered. The first is the default. */
export const SOLVER_INFO = Object.assign(Object.create(null), {
	ndf: {
		label: 'stiff, NDF',
		blurb: 'Variable-order numerical differentiation formulas \u2014 the method the '
			+ 'desktop tools default to for stiff problems, and the default here. '
			+ 'Usually the fewest steps on a stiff model, which is most of them.',
	},
	// The same code with the kappa terms set to zero, which is what turns an
	// NDF back into a BDF. Worth offering rather than hiding in a flag,
	// because kappa is precisely the difference between the two
	// formulas, so running both says what those terms are worth on a model,
	// and a reference worked out against plain BDF can be reproduced.
	bdf: {
		label: 'stiff, BDF',
		blurb: 'The variable-order solver with the NDF terms switched off: plain '
			+ 'backward differentiation formulas. Usually a few more steps than the '
			+ 'NDFs for the same answer \u2014 run both to see what those terms buy '
			+ 'here, or to match a result someone else worked out with BDF.',
	},
	ros23: {
		label: 'stiff, low order, Rosenbrock 2-3',
		blurb: 'Rosenbrock (2,3). Lower order than the variable-order solvers but '
			+ 'robust, and it re-forms its iteration matrix every step, which makes '
			+ 'it steadier than they are through a discontinuity.',
	},
	dp45: {
		label: 'non-stiff, Dormand-Prince 4-5',
		blurb: 'Dormand-Prince (4,5). Cheaper per step on a smooth, well-scaled '
			+ 'problem, but grinds to a halt on a stiff one.',
	},

	// --- ported from DifferentialEquations.jl ---------------------------------
	//
	// Six methods from SciML's stiff suite, vendored whole in ./julia/ and
	// adapted in ./julia-solvers.js. Two of them are families this tool has
	// nothing else of -- a Rosenbrock-Wanner with no nonlinear iteration at
	// all, and a fully implicit Runge-Kutta -- so they are a second opinion
	// that, unlike the SciPy ones below, needs no download and works offline.
	rodas5p: {
		label: 'stiff, Rosenbrock 5',
		blurb: 'Rodas5P, order 5, L-stable. It has no Newton iteration, so there is '
			+ 'nothing to fail to converge — the one to reach for when a model will not '
			+ 'run. On the bundled biosphere it is both the most accurate here and a '
			+ 'third of the variable-order solver\u2019s steps.',
	},
	radau5: {
		label: 'stiff, Radau IIA 5',
		blurb: 'Fully implicit Runge-Kutta of order 5, L-stable — a different family '
			+ 'from every BDF solver here, so it agrees with them for different reasons. '
			+ 'It suffers the least order reduction on a stiff problem: the one to '
			+ 'believe when two others disagree. It factorises densely, so prefer FBDF '
			+ 'above a few thousand states.',
	},
	fbdf: {
		label: 'stiff, fixed-leading-coefficient BDF',
		blurb: 'The same family as the variable-order solver but a different '
			+ 'formulation, and SciML\u2019s recommendation for the largest stiff '
			+ 'systems: it reuses one matrix factorisation across many steps, which on '
			+ 'hundreds of states is most of the cost.',
	},
	qndf: {
		label: 'stiff, quasi-constant-step NDF',
		blurb: 'The numerical differentiation formulas of Shampine and Reichelt — the '
			+ 'same method the variable-order solver implements, written independently '
			+ 'from the Julia sources. The closest thing here to a line-by-line check '
			+ 'of that solver.',
	},
	kencarp4: {
		label: 'stiff, ESDIRK 4',
		blurb: 'KenCarp4, order 4, L-stable. A reasonable middle: cheaper per step than '
			+ 'Radau and higher order than the low-order Rosenbrock.',
	},
	trbdf2: {
		label: 'stiff, ESDIRK 2 (loose tolerances)',
		blurb: 'TRBDF2, order 2, L-stable and forgiving — and second order is the catch: '
			+ 'on a problem with sharp transients it loses phase accuracy long before it '
			+ 'loses local accuracy, and reports success either way. Use it at loose '
			+ 'tolerances on smooth problems, or use the ESDIRK 4.',
	},

	// --- a second opinion, from another library ------------------------------
	//
	// The three above are this project's own: this code integrating equations
	// this code generated, checked against closed-form solutions. What that cannot catch
	// is a mistake shared between this tool and its tests. These run the same
	// model through SciPy instead -- other people's integrators, in Python,
	// compiled to WebAssembly -- so a disagreement means one of the two is
	// wrong and the answer is worth having.
	//
	// `remote` is what makes them different in kind: they need a runtime that
	// is downloaded on first use, so unlike everything else in this project
	// they do not work offline. Nothing loads it unless one of these is chosen.
	scipy_bdf: {
		label: 'SciPy BDF, stiff',
		blurb: 'scipy.integrate.solve_ivp(method="BDF") -- variable-order backward '
			+ 'differentiation formulas, the same family as ndf and written '
			+ 'independently of it. Slower, and the reason to reach for it is to '
			+ 'check a result rather than to get one.',
		remote: true,
	},
	scipy_radau: {
		label: 'SciPy Radau IIA, stiff',
		blurb: 'solve_ivp(method="Radau") -- implicit Runge-Kutta of order 5, a '
			+ 'different family altogether from the BDF solvers, so it agrees with '
			+ 'them for different reasons. The strongest check of the three.',
		remote: true,
	},
	scipy_lsoda: {
		label: 'SciPy LSODA, auto-switching',
		blurb: 'solve_ivp(method="LSODA") -- the ODEPACK routine that detects '
			+ 'stiffness and switches between Adams and BDF on its own, so it needs '
			+ 'no choice from you. Often the quickest of the three here.',
		remote: true,
	},
});

/**
 * The settings a solver may be given, beyond the tolerances every one reads.
 *
 * Two tables rather than one list, for the reason facsimile.html keeps them
 * that way: `SOLVER_OPTION_INFO` is what a setting *is* -- its label, its
 * shape, what it does -- and `SOLVER_OPTIONS` is which solvers actually read
 * it. The second is the half that goes stale, so it lives next to the
 * catalogue rather than in the interface, and the interface shows only the
 * rows the chosen solver reads and *names the ones it dropped*: a knob that
 * silently does nothing is worse than a missing one, because nothing on screen
 * tells the reader which it is.
 *
 * `kind` is how the interface draws it: a number, a choice, or a switch.
 */
export const SOLVER_OPTION_INFO = Object.assign(Object.create(null), {
	// The labels are facsimile.html's and rtm.html's, where they fit the
	// sidebar's name column, so a setting is called the same in all three;
	// `name` is how the note under the rows refers to one it drops, in the
	// words facsimile.html uses. `unit` is `true` for the model's time unit,
	// or the unit itself. `short` is what the sidebar shows where the label and
	// its unit would not fit the name column -- abbreviated as `Rel. tolerance`
	// is -- with the full label at the head of its tooltip.
	max_step: {
		label: 'Maximum step', short: 'Max. step', name: 'the maximum step', kind: 'number', unit: true,
		blurb: 'The longest step the solver may take. 0 leaves it to the solver, which is '
			+ 'almost always right; set it where a model changes faster than its output '
			+ 'grid can show and the solver steps over the change.',
	},
	initial_step: {
		label: 'First step', name: 'the first step', kind: 'number', unit: true,
		blurb: 'The first step to try. 0 lets the solver choose one from the derivative at '
			+ 'the start, which is usually better than a guess.',
	},
	max_steps: {
		label: 'Step budget', name: 'the step budget', kind: 'number',
		blurb: 'How many steps the solver may take before it gives up and says so. A run '
			+ 'that hits this has usually met something the model did not mean, rather '
			+ 'than needing a larger budget.',
	},
	max_order: {
		label: 'Maximum order', name: 'the maximum order', kind: 'choice', choices: [1, 2, 3, 4, 5],
		blurb: 'The highest order the variable-order formulas may reach. Lower is steadier '
			+ 'through a discontinuity and slower on a smooth stretch.',
	},
	min_order: {
		label: 'Minimum order', name: 'the minimum order', kind: 'choice', choices: [1, 2, 3, 4, 5],
		blurb: 'The lowest order to drop to. Raising it to the maximum gives a '
			+ 'fixed-order method.',
	},
	norm_control: {
		label: 'Norm control', name: 'norm control', kind: 'switch', on: false,
		blurb: 'Judge the error against the norm of the whole solution rather than each '
			+ 'component against its own size (MATLAB’s NormControl). Looser on a model '
			+ 'whose components differ by orders of magnitude — which is most of them '
			+ 'here, so it is off.',
	},
	error_norm: {
		label: 'Error norm', name: 'the error norm', kind: 'choice',
		choices: [['max', 'max'], ['rms', 'rms']],
		blurb: 'How the errors of the components are combined into the one number a step '
			+ 'is accepted or refused on: max lets the worst-resolved component decide, rms '
			+ 'averages over all of them, as CVODE does. The maximum is the stricter.',
	},
	stagnation_tol: {
		label: 'Stall tolerance', name: 'the stall tolerance', kind: 'number',
		blurb: 'How large a Newton correction may be and still be accepted once it has '
			+ 'stopped shrinking, as a fraction of the error tolerance; 0 never accepts '
			+ 'one, which is the default. Raise it to 0.5 only for a model whose rates '
			+ 'cancel so heavily that the correction cannot shrink any further — '
			+ 'constants of 1e16 against inventories of 1e-9. Such a run otherwise cuts '
			+ 'its step for ever, since round-off does not shrink with the step. On a '
			+ 'model that does not need it, it costs accuracy.',
	},
	newton_kappa: {
		label: 'Newton tolerance', name: 'the Newton tolerance', kind: 'number',
		blurb: 'How tightly each stage’s Newton iteration must converge, as a fraction '
			+ 'of the error tolerance (κ). Loose leaves a stage half-solved, which '
			+ 'contaminates the error estimate read off those stages; 1e-3 was measured, '
			+ 'not chosen.',
	},
	max_jac_age: {
		label: 'Jacobian reuse', name: 'how long a Jacobian is reused', kind: 'number',
		blurb: 'How many steps a Jacobian may be reused before it is formed again; 1 forms '
			+ 'it every step. Reusing it is most of what makes a stiff solver cheap on a '
			+ 'large model; reusing it too long costs Newton iterations instead.',
	},
	below_tol_run: {
		label: 'Steps at the floor', name: 'accepting failing steps at the floor', kind: 'number',
		blurb: 'How many failing steps at the smallest representable size may be accepted '
			+ 'in a row \u2014 steps that fail the error test, and for NDF and BDF steps whose '
			+ 'Newton iteration will not converge. 0 stops instead, which is what the published '
			+ 'methods do: accepting a step known to be inaccurate should be asked for. Empty '
			+ 'is the solver\u2019s own rule, which for NDF and BDF is twenty failed error tests '
			+ 'and no failed iteration. The status line counts every one taken.',
	},
	matrix: {
		label: 'Iteration matrix', name: 'the choice of iteration matrix', kind: 'choice',
		choices: [['auto', 'auto'], ['refactor', 'sparse LU, pivots kept'], ['sparse', 'sparse LU'], ['dense', 'dense LU']],
		blurb: 'How I − hJ, the matrix every implicit step solves with, is factorised: '
			+ 'a sparse LU that keeps its pivots from one factorisation to the next, a sparse '
			+ 'LU that chooses them each time, or a dense LU. auto measures the fill and '
			+ 'chooses, and is right almost always. The ported solvers have no LU that keeps '
			+ 'its pivots, and use their sparse one for it.',
	},
	jacobian: {
		label: 'Jacobian', name: 'the choice of Jacobian', kind: 'choice',
		choices: [['analytic', 'analytic'], ['numeric', 'finite differences']],
		blurb: 'Where df/dy comes from: generated from the equations, which is exact and '
			+ 'costs one pass per colour of its pattern, or by finite differences through '
			+ 'the same pattern. Differencing is slower and less exact; it is the check to '
			+ 'run when the generated one is in doubt. A model the generator declines is '
			+ 'differenced either way.',
	},
	auto_abstol: {
		label: 'Absolute tolerance follows the solution', name: 'letting the absolute tolerance follow the solution',
		kind: 'switch', on: false,
		blurb: 'Let each component’s absolute tolerance rise with it, so it is judged '
			+ 'against the largest it has ever been rather than a floor fixed before the '
			+ 'run. Much cheaper on a decay chain; it only ever loosens, so a quantity that '
			+ 'peaked and decayed is no longer controlled in its tail.',
	},
});

// The groups the per-solver lists are built from.
const STEPS = ['max_step', 'initial_step', 'max_steps'];
// Every ported method: they share one integrator loop and one Newton.
const JULIA = [...STEPS, 'matrix', 'jacobian', 'max_jac_age', 'below_tol_run', 'error_norm', 'auto_abstol'];
// ...but a Rosenbrock is linearly implicit, so there is no iteration to give a
// tolerance to, and it re-forms the Jacobian every step by definition -- a
// stale one changes its order rather than its speed, so there is no age to set.
const ROSENBROCK = JULIA.filter((k) => k !== 'max_jac_age');
const NEWTON = [...JULIA, 'newton_kappa'];
// Only the variable-order multistep methods have an order to cap.
const ORDER = ['max_order', 'min_order'];

/**
 * Which settings each solver actually reads.
 *
 * A solver absent from here reads none of them -- the SciPy ones take their
 * own options over the wire and are configured where they are launched.
 */
export const SOLVER_OPTIONS = Object.assign(Object.create(null), {
	// The NDF integrator, under both its names.
	// facsimile.html's NDF reads the same, less norm control and the first
	// step, which are this one's own: its Newton has its own convergence test
	// rather than a kappa, it keeps a Jacobian until Newton stalls, and its
	// error estimate is not smoothed, so those are not its settings there
	// either.
	ndf: [...STEPS, 'max_order', 'norm_control', 'error_norm', 'stagnation_tol', 'below_tol_run',
		'matrix', 'jacobian', 'auto_abstol'],
	bdf: [...STEPS, 'max_order', 'norm_control', 'error_norm', 'stagnation_tol', 'below_tol_run',
		'matrix', 'jacobian', 'auto_abstol'],
	// A Jacobian to difference or not, and nothing else: its order and its
	// linear algebra are its own.
	ros23: [...STEPS, 'jacobian'],
	dp45: STEPS,
	fbdf: [...NEWTON, ...ORDER],
	qndf: [...NEWTON, ...ORDER],
	// Radau measures its error against Hairer's own transformed tolerances in
	// a fixed norm, and does not read this one.
	radau5: NEWTON.filter((k) => k !== 'error_norm'),
	kencarp4: NEWTON,
	trbdf2: NEWTON,
	rodas5p: ROSENBROCK,
});

/** The settings `id` reads, in the order the interface should show them. */
export function solverOptions(id) {
	const keys = SOLVER_OPTIONS[id] ?? [];
	return Object.keys(SOLVER_OPTION_INFO).filter((k) => keys.includes(k));
}

/** The settings `id` does not read, in prose, for the note that says so. */
export function solverIgnores(id) {
	const keys = new Set(SOLVER_OPTIONS[id] ?? []);
	return Object.keys(SOLVER_OPTION_INFO)
		.filter((k) => !keys.has(k))
		.map((k) => SOLVER_OPTION_INFO[k].name);
}

/**
 * The solvers whose error test can let `abstol` float up with the solution.
 *
 * `ndf` has it as an extension (see AutoUpdateAbsTol in ./ndf.js) and
 * the ported methods have it as `autoAbstol`. `ros23`, `dp45` and the SciPy
 * ones have no equivalent, and a switch that silently does nothing on the
 * solver you happen to have chosen is worse than no switch -- so the interface
 * asks this and greys it out with the reason.
 */
export const FLOATING_ABSTOL_IDS = Object.keys(SOLVER_OPTIONS)
	.filter((id) => SOLVER_OPTIONS[id].includes('auto_abstol'));

/** Whether a solver honours `simulation.auto_abstol`. */
export function solverFloatsAbsTol(id) { return FLOATING_ABSTOL_IDS.includes(id); }

/** The solver a new or under-specified model gets. */
export const DEFAULT_SOLVER = 'ndf';

export const SOLVER_IDS = Object.keys(SOLVER_INFO);

/**
 * The ones that run anywhere -- in Node, offline, with no download.
 *
 * Kept separate because the difference is not a matter of taste: a model saved
 * with a remote solver opens on a machine with no network but will not run
 * there, and the test suite has no browser to load a runtime into.
 */
export const LOCAL_SOLVER_IDS = SOLVER_IDS.filter((id) => !SOLVER_INFO[id].remote);

/** Whether a solver needs something downloaded before it can run. */
export function solverIsRemote(id) { return !!SOLVER_INFO[id]?.remote; }

/** The interface name, falling back to the id for anything unrecognised. */
export function solverLabel(id) {
	return SOLVER_INFO[id]?.label ?? String(id);
}

/** Both names, for error messages and tooltips: `stiff, var. order (ndf)`. */
export function solverName(id) {
	return SOLVER_INFO[id] ? `${SOLVER_INFO[id].label} (${id})` : String(id);
}
