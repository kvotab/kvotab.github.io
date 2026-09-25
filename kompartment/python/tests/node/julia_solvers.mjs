// The application's ported DifferentialEquations.jl solvers, for the Python port's tests.
//
//   node julia_solvers.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } and the answer one JSON object on stdout:
//
//   solve     { runs: [{ problem, solver, opts }] }  -> per run: t, y, stats, stopped, accepted
//             times (from onAccepted), progress calls, or the error it threw
//   tableaus  {}                                     -> the package's tableaux, as it holds them
//   orderings { patterns: [{ n, colPtr, rowIdx }] }  -> reverseCuthillMcKee and colourColumns
//   problems  {}                                     -> each problem's n, y0, grid and pattern
//   pow       { pairs: [[x, y]] }                     -> Math.pow(x, y) for each, as V8 computes it
//
// The problems are defined here and mirrored in test_engine_julia.py, expression for
// expression, so that f is the same function to the last bit on both sides.
//
// `opts` is the solver option bag in the application's names (rtol, abstol, hmax, ...),
// plus four of this bridge's: `jacobian: 'analytic' | 'declined' | 'none'` (default
// 'analytic'), `abortAfter` (the onStep call that answers false), `grid` (to replace
// the problem's) and `collect: false` (no onAccepted).
//
// Infinity and NaN travel as the strings 'Infinity', '-Infinity' and 'NaN'.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const { julia } = await load('ode/julia-solvers.js');
const pkg = await load('ode/julia/index.js');

const req = JSON.parse(readFileSync(0, 'utf8'), (k, v) => (
	v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : v === 'NaN' ? NaN : v));

const plain = (x) => JSON.parse(JSON.stringify(x, (k, v) => {
	if (typeof v === 'number' && !Number.isFinite(v)) return String(v);
	if (ArrayBuffer.isView(v)) return Array.from(v, (n) => (Number.isFinite(n) ? n : String(n)));
	return v;
}));

/** A CSC pattern from (row, col) pairs, rows ascending in each column. */
function csc(n, entries) {
	const sorted = entries.slice().sort((a, b) => (a[1] - b[1]) || (a[0] - b[0]));
	const colPtr = new Int32Array(n + 1);
	const rowIdx = new Int32Array(sorted.length);
	sorted.forEach(([r, c], k) => { rowIdx[k] = r; colPtr[c + 1]++; });
	for (let j = 0; j < n; j++) colPtr[j + 1] += colPtr[j];
	return { n, colPtr, rowIdx, entries: sorted };
}

/** Values in pattern order from a dense J(i, j). */
const inOrder = (pattern, J) => Float64Array.from(pattern.entries, ([r, c]) => J(r, c));

const linspace = (a, b, m) => Array.from({ length: m }, (_, i) => a + (b - a) * (i / (m - 1)));

// --- the problems ------------------------------------------------------------------------

const PROBLEMS = {};

// Robertson's chemical kinetics: stiff, three species, conserved total.
{
	const pattern = csc(3, [[0, 0], [1, 0], [0, 1], [1, 1], [2, 1], [0, 2], [1, 2]]);
	PROBLEMS.robertson = {
		y0: [1, 0, 0],
		grid: [0, 1e-3, 1e-1, 1, 10, 100, 1e3, 1e4, 1e5],
		pattern,
		f: (t, y, d) => {
			d[0] = -0.04 * y[0] + 1e4 * y[1] * y[2];
			d[1] = 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1];
			d[2] = 3e7 * y[1] * y[1];
			return d;
		},
		jac: (t, y) => inOrder(pattern, (r, c) => [
			[-0.04, 1e4 * y[2], 1e4 * y[1]],
			[0.04, -1e4 * y[2] - 6e7 * y[1], -1e4 * y[1]],
			[0, 6e7 * y[1], 0],
		][r][c]),
	};
}

// A decay chain of twelve with distinct rates: Bateman's closed form, and a
// pattern sparse enough (23 of 144) that `auto` factorises it sparsely.
{
	const n = 12;
	const k = Array.from({ length: n }, (_, i) => 10 ** (-i / 4));
	const entries = [];
	for (let i = 0; i < n; i++) {
		entries.push([i, i]);
		if (i + 1 < n) entries.push([i + 1, i]);
	}
	const pattern = csc(n, entries);
	const y0 = new Array(n).fill(0);
	y0[0] = 1;
	PROBLEMS.chain = {
		y0,
		grid: [0, 0.1, 1, 3, 10, 30, 100, 300, 1000],
		pattern,
		rates: k,
		f: (t, y, d) => {
			d[0] = -k[0] * y[0];
			for (let i = 1; i < n; i++) d[i] = k[i - 1] * y[i - 1] - k[i] * y[i];
			return d;
		},
		jac: (t, y) => inOrder(pattern, (r, c) => (r === c ? -k[c] : k[c])),
	};
}

// Van der Pol at mu = 10: mildly stiff, and a limit cycle with sharp turns.
{
	const mu = 10;
	const pattern = csc(2, [[1, 0], [0, 1], [1, 1]]);
	PROBLEMS.vdp = {
		y0: [2, 0],
		grid: linspace(0, 30, 31),
		pattern,
		f: (t, y, d) => {
			d[0] = y[1];
			d[1] = mu * (1 - y[0] * y[0]) * y[1] - y[0];
			return d;
		},
		jac: (t, y) => inOrder(pattern, (r, c) => [
			[0, 1],
			[-2 * mu * y[0] * y[1] - 1, mu * (1 - y[0] * y[0])],
		][r][c]),
	};
}

// HIRES, from the Hairer-Wanner set: eight species, 25 of 64 entries, dense under `auto`.
{
	const J = (y) => [
		[-1.71, 0.43, 8.32, 0, 0, 0, 0, 0],
		[1.71, -8.75, 0, 0, 0, 0, 0, 0],
		[0, 0, -10.03, 0.43, 0.035, 0, 0, 0],
		[0, 8.32, 1.71, -1.12, 0, 0, 0, 0],
		[0, 0, 0, 0, -1.745, 0.43, 0.43, 0],
		[0, 0, 0, 0.69, 1.71, -280 * y[7] - 0.43, 0.69, -280 * y[5]],
		[0, 0, 0, 0, 0, 280 * y[7], -1.81, 280 * y[5]],
		[0, 0, 0, 0, 0, -280 * y[7], 1.81, -280 * y[5]],
	];
	const entries = [];
	const shape = J(new Array(8).fill(1));
	for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) if (shape[r][c] !== 0) entries.push([r, c]);
	const pattern = csc(8, entries);
	PROBLEMS.hires = {
		y0: [1, 0, 0, 0, 0, 0, 0, 0.0057],
		grid: [0, 1, 5, 10, 50, 100, 200, 321.8122],
		pattern,
		f: (t, y, d) => {
			d[0] = -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007;
			d[1] = 1.71 * y[0] - 8.75 * y[1];
			d[2] = -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4];
			d[3] = 8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3];
			d[4] = -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6];
			d[5] = -280 * y[5] * y[7] + 0.69 * y[3] + 1.71 * y[4] - 0.43 * y[5] + 0.69 * y[6];
			d[6] = 280 * y[5] * y[7] - 1.81 * y[6];
			d[7] = -280 * y[5] * y[7] + 1.81 * y[6];
			return d;
		},
		jac: (t, y) => { const m = J(y); return inOrder(pattern, (r, c) => m[r][c]); },
	};
}

// A decay that crosses a level: one terminal event, falling. y = e^-t, so it
// fires at ln 4. The second state rises and never crosses its own level.
{
	const pattern = csc(2, [[0, 0], [1, 0], [1, 1]]);
	const base = {
		y0: [1, 0],
		grid: linspace(0, 5, 11),
		pattern,
		f: (t, y, d) => {
			d[0] = -y[0];
			d[1] = y[0] - 0.1 * y[1];
			return d;
		},
		jac: (t, y) => inOrder(pattern, (r, c) => (r === 0 ? -1 : c === 0 ? 1 : -0.1)),
	};
	PROBLEMS.event = {
		...base,
		events: { n: 1, direction: Int8Array.from([-1]), fun: (t, y, out) => { out[0] = y[0] - 0.25; return out; } },
	};
	// Two event functions with a direction each: y falls through 0.25 at ln 4,
	// the clock rises through 0.5 first, and the earlier stops the run.
	PROBLEMS.two_events = {
		...base,
		events: {
			n: 2,
			direction: Int8Array.from([-1, 1]),
			fun: (t, y, out) => { out[0] = y[0] - 0.25; out[1] = t - 0.5; return out; },
		},
	};
	// One event in both directions (0): a rising second state crossing 0.3.
	PROBLEMS.event_rising = {
		...base,
		events: { n: 1, direction: Int8Array.from([0]), fun: (t, y, out) => { out[0] = y[1] - 0.3; return out; } },
	};
}

// The chain again with every state held at or above zero. At loose tolerances the
// fast members undershoot zero now and then and are clamped back: hundreds of
// clamps a run. (A compartment drained at a constant rate, which the constraint
// binds for good, is no test: FBDF takes ten million steps over it and stops.)
PROBLEMS.nonneg = { ...PROBLEMS.chain, nonNegative: new Array(12).fill(true) };

// A clock-driven forcing, to exercise df/dt in Rodas5P: y' = -50 (y - g(t)) with
// a rational g, so that f is the same to the last bit on both sides (Math.cos is not).
{
	const pattern = csc(1, [[0, 0]]);
	PROBLEMS.forced = {
		y0: [0],
		grid: linspace(0, 10, 21),
		pattern,
		f: (t, y, d) => { d[0] = -50 * (y[0] - t / (1 + 0.1 * t * t)); return d; },
		jac: () => Float64Array.from([-50]),
	};
}

// A run that starts late, just after a jump: a chain M -> B -> R -> W restarted at
// t = 5000.123456789 with M = 9e12, B = 1e12 and R = W = 0, as a model whose
// packages all fail at once opens its next segment. R starts at zero and rises at
// 1e10 a unit of time; the clock there is good to 9e-13. FBDF used to stop on its
// first step or its fourth.
{
	const T = 5000.123456789;
	const pattern = csc(4, [[0, 0], [1, 0], [1, 1], [2, 1], [2, 2], [3, 2]]);
	PROBLEMS.jump = {
		y0: [9e12, 1e12, 0, 0],
		grid: [T, ...[1e-6, 1e-3, 1, 10, 100, 1000].map((d) => T + d), 20000],
		pattern,
		f: (t, y, d) => {
			d[0] = -1e-4 * y[0];
			d[1] = 1e-4 * y[0] - 0.01 * y[1];
			d[2] = 0.01 * y[1] - 1e-3 * y[2];
			d[3] = 1e-3 * y[2];
			return d;
		},
		jac: () => inOrder(pattern, (r, c) => [
			[-1e-4, 0, 0, 0],
			[1e-4, -0.01, 0, 0],
			[0, 0.01, -1e-3, 0],
			[0, 0, 1e-3, 0],
		][r][c]),
	};
}

// --- running them ------------------------------------------------------------------------

function jacobianOption(problem, how) {
	if (how === 'none') return null;
	const { n, colPtr, rowIdx } = problem.pattern;
	const pattern = { n, colPtr, rowIdx, nnz: colPtr[n] };
	if (how === 'declined') return { pattern, available: true, evaluate: () => null };
	return { pattern, available: true, evaluate: (t, y) => problem.jac(t, y) };
}

function runOne({ problem: name, solver, opts = {} }) {
	const problem = PROBLEMS[name];
	if (!problem) return { error: `no problem '${name}'` };
	const o = { ...opts };
	const how = o.jacobian ?? 'analytic';
	const abortAfter = o.abortAfter;
	const collect = o.collect !== false;
	const grid = o.grid ?? problem.grid;
	delete o.jacobian; delete o.abortAfter; delete o.collect; delete o.grid;
	const accepted = [];
	let calls = 0;
	const solverOpts = {
		...o,
		jacobian: jacobianOption(problem, how),
		nonNegative: o.nonNegative ?? problem.nonNegative,
		events: problem.events,
		onAccepted: collect ? (t) => { accepted.push(t); } : undefined,
		onStep: abortAfter != null ? () => (++calls < abortAfter) : undefined,
	};
	if (Array.isArray(o.abstol)) solverOpts.abstol = Float64Array.from(o.abstol);
	const f = (t, y, d) => problem.f(t, y, d);
	try {
		const s = julia(solver)(f, Float64Array.from(grid), Float64Array.from(problem.y0), solverOpts);
		return { t: s.t, y: s.y, stats: s.stats, stopped: s.stopped, accepted, calls };
	} catch (e) {
		return { error: e.message, name: e.name, t: e.t ?? null, accepted, calls };
	}
}

let out;
switch (req.task) {
	case 'solve':
		out = { runs: req.runs.map(runOne) };
		break;
	case 'problems': {
		out = {};
		for (const [name, p] of Object.entries(PROBLEMS)) {
			out[name] = {
				n: p.pattern.n, y0: p.y0, grid: p.grid, colPtr: p.pattern.colPtr, rowIdx: p.pattern.rowIdx,
				nonNegative: p.nonNegative ?? null, rates: p.rates ?? null,
				events: p.events ? { n: p.events.n, direction: p.events.direction } : null,
			};
		}
		break;
	}
	case 'tableaus':
		out = {
			rodas5p: pkg.Rodas5PTableau, radau5: pkg.RadauIIA5Tableau,
			trbdf2: pkg.TRBDF2Tableau, kencarp4: pkg.KenCarp4Tableau,
		};
		break;
	case 'pow':
		// The one built-in whose last bit V8 and the C library disagree on often
		// enough to matter: the Python side asks for V8's values to show that,
		// given them, a run is the application's step for step.
		out = { values: req.pairs.map(([x, y]) => Math.pow(x, y)) };
		break;
	case 'orderings':
		out = {
			results: req.patterns.map(({ n, colPtr, rowIdx }) => {
				const cp = Int32Array.from(colPtr);
				const ri = Int32Array.from(rowIdx);
				return {
					rcm: pkg.reverseCuthillMcKee(n, cp, ri),
					groups: pkg.colourColumns(n, cp, ri).groups,
				};
			}),
		};
		break;
	default:
		throw new Error(`No task '${req.task}'`);
}
process.stdout.write(JSON.stringify(plain(out)));
