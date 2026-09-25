/**
 * SciPy's implicit solvers, run in the browser through Pyodide.
 *
 * WHY THIS EXISTS. Every other integrator in this directory is written here:
 * ndf.js is the numerical differentiation formulas, rosenbrock23.js the
 * Rosenbrock (2,3) pair, dormand-prince.js the explicit (4,5) pair. An
 * implementation is only as good as its testing, and testing an integrator
 * against closed-form solutions -- which test/run.js does
 * -- catches the errors that make it wrong everywhere, not the ones that make
 * it wrong on one model. The thing that catches those is a second, independent
 * implementation of the same mathematics, written by other people, and the
 * best-tested one in existence for this class of problem is SciPy's.
 *
 * So this is not here to be fast. `scipy.integrate.BDF` is the same family of
 * variable-order backward differentiation formulas as ndf and reaches the
 * same answers -- on the Robertson problem the two agree to 2.5e-9 while both
 * conserve mass to 1e-15 -- but it reaches them through a Python interpreter
 * compiled to WebAssembly, which costs between two and twenty times the
 * wall-clock. It is here to be *independent*: when a model's results look
 * wrong, running it again under SciPy says whether the model is wrong or this
 * tool is.
 *
 * HOW. Pyodide is a CPython build for WebAssembly with real NumPy and SciPy
 * wheels. It is downloaded on first use -- about 22 MB over the wire, roughly
 * two and a half seconds on a fast connection -- and then cached by the
 * browser. Nothing is downloaded unless one of these solvers is actually
 * chosen; the rest of the application, and every other solver, is untouched
 * and stays offline.
 *
 * The derivative stays in JavaScript. `buildSystem` compiles a model's
 * equations into a JavaScript function, and re-emitting them as Python would
 * be a second code generator to keep in step with the first -- the surest way
 * to make the "independent check" agree with the thing it is checking. Instead
 * Python calls back into the generated function through a pair of buffers that
 * live in the WebAssembly heap and are seen from both sides with no copying:
 * NumPy writes the state in, JavaScript writes the derivative back. What SciPy
 * integrates is therefore exactly the function the other solvers integrate.
 *
 * WHAT IS HOOKED. `solve_ivp` has no callback for accepted steps, which this
 * codebase needs for the blocks that remember (min/max, running mean, delay)
 * and for progress and cancellation. Rather than reimplement the driver -- and
 * with it the chance of a bug SciPy does not have -- each solver class is
 * subclassed and `_step_impl` is wrapped, so SciPy's own `solve_ivp` runs its
 * own numerics and this code is told when a step is accepted. See `DRIVER`.
 */

import { SolverError } from './solvers/dormand-prince.js';
import { colourColumns, differenceJacobian } from './core/sparse.js';

/**
 * Pinned, not floating.
 *
 * `latest` would mean an integrator that changes under a model without the
 * model changing, which is the one thing a reference implementation must not
 * do. Bumping this is a deliberate act with a re-run of the comparison tests
 * behind it.
 */
export const PYODIDE_VERSION = 'v314.0.6';
export const PYODIDE_INDEX = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`;

/** Roughly what the first use costs over the wire, for the interface to say. */
export const PYODIDE_BYTES = 22 * 1024 * 1024;

/** Solver id -> the `method` SciPy knows it by. */
export const SCIPY_METHODS = {
	scipy_bdf: 'BDF',
	scipy_radau: 'Radau',
	scipy_lsoda: 'LSODA',
};

export function isScipySolver(id) {
	return Object.prototype.hasOwnProperty.call(SCIPY_METHODS, id);
}

// --- the Python side ---------------------------------------------------------

/**
 * The driver, run once when the interpreter comes up.
 *
 * Everything here is bookkeeping around one `solve_ivp` call. The numerics are
 * SciPy's own and are not touched: `_hooked` subclasses the solver class only
 * to learn when a step is accepted, and calls `super()._step_impl()` for the
 * step itself.
 */
const DRIVER = `
import json
import numpy as np
from scipy.integrate import solve_ivp, BDF, Radau, LSODA
from scipy.sparse import csc_matrix

_METHODS = {'BDF': BDF, 'Radau': Radau, 'LSODA': LSODA}


class EcoCancelled(Exception):
    """Raised out of the derivative when JavaScript asks the run to stop."""


class _Run:
    """Buffers and counters for one solve. Rebuilt per call, so a model that
    changes shape between runs cannot read a stale buffer."""


R = _Run()


def eco_alloc(n, nev, nnz):
    """The buffers both languages share. Allocated once per solve; JavaScript
    takes typed-array views onto these and writes into them directly."""
    R.n = n
    R.y_in = np.zeros(n)          # state, written by Python, read by JS
    R.dy = np.zeros(n)            # derivative, written by JS, read by Python
    R.y_step = np.zeros(n)        # state at an accepted step, for recorders
    R.ev = np.zeros(max(1, nev))  # event values, written by JS
    R.jv = np.zeros(max(1, nnz))  # Jacobian values, written by JS (CSC order)
    R.nsteps = 0
    R.nfailed = 0


def eco_solve(spec_json):
    spec = json.loads(spec_json)
    n = R.n
    t_eval = np.asarray(spec['t_eval'], dtype=float)
    y0 = np.asarray(spec['y0'], dtype=float)

    def f(t, y):
        R.y_in[:] = y
        # js_rhs returns False to abort. Raising here unwinds solve_ivp
        # cleanly -- the interpreter is reusable afterwards, which was
        # measured, not assumed.
        if js_rhs(float(t)) is False:
            raise EcoCancelled()
        # A copy, because the multistep solvers keep references to past
        # derivatives; handing back the one buffer would corrupt the history.
        return R.dy.copy()

    kwargs = {}

    # --- the analytic Jacobian, when the model generator produced one --------
    if spec['jac'] == 'sparse':
        indptr = np.asarray(spec['colPtr'], dtype=np.int32)
        indices = np.asarray(spec['rowIdx'], dtype=np.int32)

        def jac(t, y):
            R.y_in[:] = y
            js_jac(float(t))
            return csc_matrix((R.jv.copy(), indices, indptr), shape=(n, n))

        kwargs['jac'] = jac
    elif spec['jac'] == 'dense':
        rows = np.asarray(spec['rowIdx'], dtype=np.int32)
        cols = np.asarray(spec['colOf'], dtype=np.int32)

        def jac(t, y):
            R.y_in[:] = y
            js_jac(float(t))
            J = np.zeros((n, n))
            J[rows, cols] = R.jv
            return J

        kwargs['jac'] = jac

    if spec.get('max_step'):
        kwargs['max_step'] = float(spec['max_step'])
    if spec.get('first_step'):
        kwargs['first_step'] = float(spec['first_step'])

    base = _METHODS[spec['method']]

    class _Hooked(base):
        """SciPy's solver, plus a callback when a step is accepted.

        _step_impl is the one method every OdeSolver subclass implements to
        take a single step, so wrapping it is enough to see every accepted
        step without touching how the step is taken."""

        def _step_impl(self):
            ok, message = super()._step_impl()
            if ok:
                R.nsteps += 1
                R.y_step[:] = self.y
                js_accepted(float(self.t))
            else:
                R.nfailed += 1
            return ok, message

    # A scalar tolerance, or one per state. float() on the second is a
    # TypeError, so a model where any compartment set its own absolute
    # tolerance failed on every SciPy method with a message about a list --
    # though solve_ivp takes an array here as happily as the solvers here do.
    atol = spec['atol']
    atol = (np.asarray(atol, dtype=float)
            if isinstance(atol, (list, tuple)) else float(atol))

    try:
        s = solve_ivp(f, (float(t_eval[0]), float(t_eval[-1])), y0,
                      method=_Hooked, t_eval=t_eval,
                      rtol=float(spec['rtol']), atol=atol,
                      **kwargs)
    except EcoCancelled:
        return json.dumps({'cancelled': True})
    except BaseException as e:  # noqa: BLE001 - reported, not swallowed
        # A derivative that returns NaN does not come back as success=False:
        # the LU factorisation raises first. Both paths have to be reported.
        return json.dumps({'error': f'{type(e).__name__}: {e}'})

    # Results are handed over as buffers rather than as JSON: a model with 400
    # states over 300 output points is 120,000 numbers, and serialising those
    # through a string costs more than the solve.
    R.t_out = np.ascontiguousarray(s.t, dtype=float)
    R.y_out = np.ascontiguousarray(s.y.T, dtype=float).ravel()
    return json.dumps({
        'ok': bool(s.success),
        'status': int(s.status),
        'message': str(s.message),
        'points': int(len(s.t)),
        'nfev': int(s.nfev),
        'njev': int(s.njev),
        'nlu': int(s.nlu),
        'nsteps': int(R.nsteps),
        'nfailed': int(R.nfailed),
    })
`;

// --- loading -----------------------------------------------------------------

let pyodide = null;
let loading = null;

/** Whether a solve can start right now without waiting for a download. */
export function scipyReady() { return pyodide !== null; }

/**
 * Brings up the interpreter, once.
 *
 * Idempotent and safe to call concurrently: the second caller awaits the first
 * one's promise rather than starting a second 22 MB download. A failure clears
 * the promise, so a run attempted again after the network comes back works
 * rather than replaying the old error forever.
 *
 * @param {{onProgress?: (stage: string, detail?: string) => void}} [opts]
 */
export async function loadScipy(opts = {}) {
	if (pyodide) return pyodide;
	if (loading) return loading;

	const report = opts.onProgress ?? (() => {});
	loading = (async () => {
		let loadPyodide;
		try {
			report('runtime', `Downloading the Python runtime from ${PYODIDE_INDEX}`);
			({ loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_INDEX}pyodide.mjs`));
		} catch (e) {
			throw new SolverError(
				`Could not reach ${PYODIDE_INDEX} to download the Python runtime that `
				+ `the SciPy solvers need (${e.message}). This is the only part of the `
				+ `application that is not self-contained: choose one of the built-in `
				+ `solvers to run offline.`,
				0,
			);
		}

		try {
			const py = await loadPyodide({ indexURL: PYODIDE_INDEX });
			report('packages', 'Downloading NumPy and SciPy');
			await py.loadPackage(['numpy', 'scipy']);
			report('starting', 'Starting the interpreter');
			py.runPython(DRIVER);
			pyodide = py;
			report('ready');
			return py;
		} catch (e) {
			throw new SolverError(
				`The Python runtime loaded but SciPy did not start: ${e.message}`, 0,
			);
		}
	})();

	try {
		return await loading;
	} catch (e) {
		loading = null;
		throw e;
	}
}

/** For tests: forget the interpreter so a fresh one can be brought up. */
export function _resetScipy() { pyodide = null; loading = null; }

/**
 * The Jacobian's values at `(t, y)`, into `out` (the pattern's entries), for
 * the SciPy methods: the generated one's -- or, where it answers null,
 * differences through its pattern.
 *
 * A generated Jacobian answers null where an entry is not a number at this
 * state: an exact derivative is infinite where sqrt or log meets an empty
 * compartment. Every other solver here then differences the matrix through the
 * pattern, and so does this. It used to hand the null to `set`, which threw,
 * and the run stopped over a matrix the step could have done without.
 *
 * @param {object} jac  `{evaluate, pattern, groups?}`
 * @param {(t, y, out) => Float64Array|void} f  the model's derivative, raw
 * @param {{threshold: Float64Array, work?: object}} opts  `threshold` is
 *   abstol/rtol per state, as the NDF's; `work` keeps the scratch between calls
 * @returns {number} the derivative evaluations spent
 */
export function jacobianValues(jac, f, t, y, out, { threshold, work = {} }) {
	const values = jac.evaluate(t, y);
	if (values) {
		out.set(values);
		return 0;
	}
	const n = y.length;
	work.groups ??= jac.groups ?? colourColumns(jac.pattern);
	work.ytry ??= new Float64Array(n);
	work.fd ??= new Float64Array(n);
	work.del ??= new Float64Array(n);
	work.f0 ??= new Float64Array(n);
	work.y ??= new Float64Array(n);
	// A copy of the state: `y` may be the buffer Python has just written, and
	// the model's derivative writes into buffers of its own.
	work.y.set(y);
	const fill = (tt, yy, into) => f(tt, yy, into) ?? into;
	const f0 = fill(t, work.y, work.f0);
	differenceJacobian(fill, t, work.y, f0, jac.pattern, work.groups, threshold, out, work);
	return 1 + work.groups.length;
}

// --- the solver --------------------------------------------------------------

/**
 * A view onto a NumPy array's memory, re-acquired when WebAssembly grows.
 *
 * Growing the WebAssembly heap replaces its backing store, which detaches
 * every typed array pointing into it -- a detached one has byteLength 0 and
 * reads as an empty array rather than throwing, so a solver that did not check
 * would quietly integrate zeros. It was measured happening on the smallest of
 * the bundled models, so the check is not theoretical.
 */
function sharedBuffer(py, name) {
	let proxy = null;
	let view = null;
	const take = () => {
		proxy?.destroy();
		proxy = py.runPython(`R.${name}`);
		view = proxy.getBuffer('f64').data;
	};
	take();
	return {
		get data() {
			if (view.byteLength === 0) take();
			return view;
		},
		release() { proxy?.destroy(); proxy = null; view = null; },
	};
}

/** How many f-evals between progress reports, matching ndf.js. */
const TICK = 64;

/**
 * One of the SciPy solvers, with the same signature as ndf/ros23/dp45.
 *
 * Synchronous, like they are: `solve_ivp` itself is an ordinary blocking call
 * once the interpreter is up. Only the download is asynchronous, and that
 * happens before `run()` is entered -- see src/worker/sim-worker.js.
 *
 * @param {string} id  one of SCIPY_METHODS' keys
 */
export function scipySolver(id) {
	const method = SCIPY_METHODS[id];
	if (!method) throw new Error(`'${id}' is not a SciPy solver`);

	return function solve(f, tspan, y0, opts = {}) {
		const neq = y0.length;
		const t0 = tspan[0];
		const tfinal = tspan[tspan.length - 1];
		if (!(Math.abs(tfinal - t0) > 0)) {
			throw new SolverError('Simulation start and end time are equal', t0);
		}
		if (!pyodide) {
			throw new SolverError(
				`${id} needs the Python runtime, which has not been loaded. This `
				+ `solver only runs in a browser with a network connection the first `
				+ `time it is used; under Node, or offline, choose ndf, ros23 or `
				+ `dp45.`,
				t0,
			);
		}

		// --- what SciPy cannot do, said out loud rather than ignored ---------
		if (opts.events) {
			throw new SolverError(
				`${id} does not support discrete events. This tool's events are terminal `
				+ `and are located by its own event locator, including the rule that a `
				+ `crossing at the instant a previous event fired is not a new one; `
				+ `reproducing that on top of SciPy would risk a subtly different `
				+ `model rather than an independent check of this one. Use ndf, `
				+ `ros23 or dp45 for a model with events.`,
				t0,
			);
		}

		const py = pyodide;
		const jac = opts.jacobian?.available ? opts.jacobian : null;
		const nnz = jac ? jac.nnz : 0;

		// The third argument is the event count, which is always zero: events
		// are refused above. It is still passed so that the Python side has one
		// allocation path rather than two.
		py.runPython(`eco_alloc(${neq}, 0, ${nnz})`);
		const yIn = sharedBuffer(py, 'y_in');
		const dy = sharedBuffer(py, 'dy');
		const yStep = sharedBuffer(py, 'y_step');
		const jv = jac ? sharedBuffer(py, 'jv') : null;

		// As a list of indices rather than a mask over every state: the same
		// shape ndf.js hands to ndf.js, and the loop runs per f-eval.
		const nnIdx = [];
		if (opts.nonNegative) {
			for (let i = 0; i < neq; i++) if (opts.nonNegative[i]) nnIdx.push(i);
		}

		const span = Math.abs(tfinal - t0) || 1;
		let nfevals = 0;
		let lastReport = 0;
		let aborted = false;

		// --- the callbacks Python reaches back through -----------------------
		const jsRhs = (t) => {
			nfevals++;
			f(t, yIn.data, dy.data);
			// The non-negativity clamp, which ndf.js applies for the same
			// option: where a state has gone negative, do not let its
			// derivative carry it further down.
			//
			// This is the part of non-negativity that lives in the derivative,
			// so it can be applied to a function SciPy is calling. The other
			// part -- projecting an accepted step back onto zero and folding
			// the violation into the error estimate, so the step is rejected --
			// belongs to the step controller, which is SciPy's and not ours.
			// Applying this much makes the comparison closer rather than
			// looser: it is the same ODE the built-in solvers integrate. What
			// is left over is counted, and reported as `stats.negative`.
			if (nnIdx.length) {
				const y = yIn.data;
				const d = dy.data;
				for (let m = 0; m < nnIdx.length; m++) {
					const i = nnIdx[m];
					if (y[i] < 0 && d[i] < 0) d[i] = 0;
				}
			}
			if (opts.onStep && (nfevals % TICK) === 0) {
				// Reported monotonically, because the solver evaluates ahead of
				// and behind the accepted point and raw t jitters -- but polled
				// unconditionally, because onStep is also the only way a run
				// learns it has been cancelled. ndf.js reports and polls in
				// the same test, so a run that grinds without advancing t
				// cannot be stopped; here it can, which matters more because a
				// Python f-eval costs more than a JavaScript one.
				lastReport = Math.max(lastReport, Math.min(1, Math.abs(t - t0) / span));
				if (opts.onStep(lastReport, nfevals, t) === false) {
					aborted = true;
					return false;
				}
			}
			return true;
		};

		const jsAccepted = opts.onAccepted
			? (t) => { opts.onAccepted(t, Float64Array.from(yStep.data)); }
			: () => {};

		// abstol/rtol per state, which the differencing increment is scaled
		// by where the generated Jacobian has to be differenced after all.
		const threshold = new Float64Array(neq);
		for (let i = 0; i < neq; i++) {
			const a = typeof opts.abstol === 'number' || opts.abstol == null ? (opts.abstol ?? 1e-6) : opts.abstol[i];
			threshold[i] = a / (opts.rtol ?? 1e-3);
		}
		const jacWork = {};
		const jsJac = jac
			? (t) => { nfevals += jacobianValues(jac, f, t, yIn.data, jv.data, { threshold, work: jacWork }); }
			: () => {};

		py.globals.set('js_rhs', jsRhs);
		py.globals.set('js_accepted', jsAccepted);
		py.globals.set('js_jac', jsJac);

		// A sparse factorisation only pays off once the matrix is big enough
		// that its zeros outnumber the bookkeeping. Below that, building a
		// scipy.sparse matrix per Jacobian costs more than it saves -- measured
		// on landscape.json (n=28), where dense beat sparse.
		const useSparse = !!jac && neq >= 60 && jac.density < 0.25;
		const spec = {
			method,
			t_eval: Array.from(tspan),
			y0: Array.from(y0),
			rtol: opts.rtol ?? 1e-3,
			// SciPy takes a scalar or a per-state array, and so does this:
			// runner.js sends a scalar unless a compartment asked for a
			// tolerance of its own, in which case the whole vector crosses.
			atol: typeof opts.abstol === 'number' || opts.abstol == null
				? (opts.abstol ?? 1e-6)
				: Array.from(opts.abstol),
			jac: jac ? (useSparse ? 'sparse' : 'dense') : 'none',
			max_step: opts.hmax && opts.hmax > 0 ? opts.hmax : null,
			first_step: opts.h0 && opts.h0 > 0 ? opts.h0 : null,
		};
		if (jac) {
			spec.colPtr = Array.from(jac.pattern.colPtr);
			spec.rowIdx = Array.from(jac.pattern.rowIdx);
			// A dense build needs the column of every stored entry; CSC only
			// stores where each column starts.
			if (!useSparse) {
				const colOf = new Int32Array(jac.nnz);
				for (let j = 0; j < neq; j++) {
					for (let k = jac.pattern.colPtr[j]; k < jac.pattern.colPtr[j + 1]; k++) {
						colOf[k] = j;
					}
				}
				spec.colOf = Array.from(colOf);
			}
		}

		try {
			let report;
			try {
				report = JSON.parse(
					py.runPython(`eco_solve(${JSON.stringify(JSON.stringify(spec))})`),
				);
			} catch (e) {
				throw new SolverError(`${id} failed: ${e.message}`, t0);
			}

			if (report.cancelled || aborted) {
				throw new SolverError('Simulation aborted', t0);
			}
			if (report.error) {
				throw new SolverError(
					`${id} failed: ${report.error}. A derivative that returns NaN or `
					+ `infinity stops SciPy in the linear algebra rather than in the `
					+ `step controller, so this usually means an equation divided by `
					+ `zero rather than that the tolerances were too tight.`,
					t0,
				);
			}
			if (!report.ok) {
				throw new SolverError(
					`${id} did not reach the end of the simulation: ${report.message} `
					+ `This model may be stiffer than the tolerances allow; try `
					+ `loosening them, or ndf.`,
					t0,
				);
			}

			// --- results back out, through the buffers ------------------------
			const tProxy = py.runPython('R.t_out');
			const yProxy = py.runPython('R.y_out');
			const tBuf = tProxy.getBuffer('f64');
			const yBuf = yProxy.getBuffer('f64');
			const npoints = report.points;
			const t = Float64Array.from(tBuf.data);
			const flat = yBuf.data;
			const y = new Array(npoints);
			for (let i = 0; i < npoints; i++) {
				y[i] = Float64Array.from(flat.subarray(i * neq, (i + 1) * neq));
			}
			tBuf.release(); yBuf.release();
			tProxy.destroy(); yProxy.destroy();

			if (!npoints) throw new SolverError(`${id} produced no output`, t0);

			// This tool's own solvers keep compartments non-negative; SciPy has
			// no such option, so say how far it went the other way rather than
			// let a negative inventory pass as a result.
			let negative = 0;
			if (opts.nonNegative) {
				// How far below zero counts as more than round-off is the
				// tolerance that state was integrated to, which is per state
				// as soon as one compartment sets its own.
				const floor = new Float64Array(neq);
				for (let s = 0; s < neq; s++) {
					const tol = typeof opts.abstol === 'number'
						? opts.abstol
						: opts.abstol?.[s] ?? 1e-6;
					floor[s] = -Math.abs(tol);
				}
				for (let i = 0; i < npoints; i++) {
					for (let s = 0; s < neq; s++) {
						if (opts.nonNegative[s] && y[i][s] < floor[s]) negative++;
					}
				}
			}

			return {
				t,
				y,
				// Events are refused above, so a SciPy run always runs to the end.
				stopped: null,
				stats: {
					nsteps: report.nsteps,
					nfailed: report.nfailed,
					nfevals,
					// SciPy's own names for the same three counters ndf
					// reports in the same vocabulary.
					npds: report.njev,
					ndecomps: report.nlu,
					nsolves: null,
					sparse: useSparse,
					fill: null,
					negative,
					points: npoints,
					solver: id,
				},
			};
		} finally {
			yIn.release(); dy.release(); yStep.release(); jv?.release();
			// The proxies Python holds for these would otherwise keep the
			// previous run's closures -- and its model -- alive.
			py.globals.set('js_rhs', null);
			py.globals.set('js_accepted', null);
			py.globals.set('js_jac', null);
		}
	};
}
