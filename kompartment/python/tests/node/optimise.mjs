// The application's optimisers, local sensitivities and calibration, for the
// Python package's tests to compare with (tests/test_optimise.py).
//
//   node optimise.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } and the answer one JSON object on stdout:
//
//   optimise    { cases: [{ method, fn, start, lower, upper, opts, stopAfter }] }
//               -> per case { result, trace } or { error, type }. `method` is
//                  nelder, lm or de (the functions), or METHODS.nelder /
//                  METHODS.lm / METHODS.de (through the table, as calibrate
//                  calls them). `fn` names an objective below, `ss:<name>` the
//                  sum of squares of a residual vector below, and for lm a
//                  residual vector. `trace` is every onStep report. With
//                  `stopAfter` the signal reads aborted once that many
//                  evaluations have been reported.
//   objective   { cases: [{ readings, targets }] }       -> objectiveOf each
//   precision   { values }                               -> v.toPrecision(12) each
//   slots       { model }                                -> parameterSlots, with slotLabel
//   sensitivity { model, opts }                          -> runSensitivity, and the
//                                                           elasticity of every state
//   augmented   { model, opts, points }                  -> the augmented system runSensitivity
//                                                           would solve, at the points given
//   pvp         { model, points: [{ t, y, seed }] }      -> paramTangent's (df/dp)·seed at each
//   variables   { model }                                -> variablesOf
//   reading     { model, targets }                       -> readingOf each, on one run on the grid
//   calibrate   { model, opts, stopAfter }               -> calibrate, and every onProgress report
//
// JSON has no NaN, infinities, -0 or undefined, and they matter here, so both
// directions spell them { "$": "NaN" | "Infinity" | "-Infinity" | "-0" |
// "undefined" }. A thrown error comes back as { error, type }.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const opt = await load('domain/optimise.js');
const { Project } = await load('domain/project.js');
const { buildSystem } = await load('sim/builder.js');
const { run } = await load('sim/runner.js');
const { parameterSlots, slotLabel, runSensitivity, elasticity } = await load('sim/localsens.js');
const { calibrate, variablesOf, readingOf } = await load('sim/calibrate.js');

const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity, '-0': -0, undefined };

function decode(x) {
	if (Array.isArray(x)) return x.map(decode);
	if (x && typeof x === 'object') {
		const keys = Object.keys(x);
		if (keys.length === 1 && keys[0] === '$') return SPECIAL[x.$];
		const out = {};
		for (const k of keys) out[k] = decode(x[k]);
		return out;
	}
	return x;
}

function encode(x) {
	if (typeof x === 'number') {
		if (Number.isNaN(x)) return { $: 'NaN' };
		if (x === Infinity) return { $: 'Infinity' };
		if (x === -Infinity) return { $: '-Infinity' };
		if (x === 0 && 1 / x < 0) return { $: '-0' };
		return x;
	}
	if (x === undefined) return { $: 'undefined' };
	if (ArrayBuffer.isView(x)) return Array.from(x, encode);
	if (Array.isArray(x)) return x.map(encode);
	if (x instanceof Map) return encode(Object.fromEntries(x));
	if (x instanceof Set) return [...x].map(encode);
	if (x && typeof x === 'object') {
		const out = {};
		for (const [k, v] of Object.entries(x)) out[k] = encode(v);
		return out;
	}
	return x;
}

// --- the test functions: + - * / and Math.exp only, so both sides do the same
// arithmetic (the Python side has V8's exp).
const C4 = [0.3, -1.2, 2.5, 0.7];
const MM_T = [0.5, 1, 2, 4, 8, 16];
const MM_Y = [0.9, 1.5, 2.2, 2.9, 3.3, 3.6];
const EXP_T = [0, 1, 2, 3, 5, 8];
const EXP_Y = [5.1, 3.1, 1.8, 1.1, 0.42, 0.09];

const OBJECTIVES = {
	rosenbrock: (x) => { const a = x[1] - x[0] * x[0]; const b = 1 - x[0]; return 100 * a * a + b * b; },
	sphere: (x) => {
		let s = 0;
		for (let k = 0; k < x.length; k++) { const d = x[k] - C4[k]; s += d * d; }
		return s;
	},
	himmelblau: (x) => {
		const a = x[0] * x[0] + x[1] - 11;
		const b = x[0] + x[1] * x[1] - 7;
		return a * a + b * b;
	},
	holes: (x) => (x[0] < 0 ? NaN
		: (x[1] > 1.5 ? Infinity : (x[0] - 1) * (x[0] - 1) + (x[1] - 0.5) * (x[1] - 0.5))),
	outside: (x) => (x[0] - 5) * (x[0] - 5) + (x[1] + 3) * (x[1] + 3),
	flat: () => 3,
	well: (x) => -1 / (1 + x[0] * x[0] + x[1] * x[1]),
	line: (x) => (x[0] - 0.25) * (x[0] - 0.25),
};

const RESIDUALS = {
	rosenbrock: (x) => [10 * (x[1] - x[0] * x[0]), 1 - x[0]],
	mm: (x) => MM_T.map((t, i) => (x[0] * t) / (x[1] + t) - MM_Y[i]),
	expdecay: (x) => EXP_T.map((t, i) => x[0] * Math.exp(-x[1] * t) - EXP_Y[i]),
	big: (x) => [x[0] - 1000000.004, (x[1] - 2) * 3],
	nanres: (x) => [x[0] > 2 ? NaN : x[0] - 1, x[1] - 2],
	line: (x) => [x[0] - 0.25],
};

const sumSquares = (res) => (x) => { let s = 0; for (const r of res(x)) s += r * r; return s; };
const objectiveNamed = (fn) => (fn.startsWith('ss:') ? sumSquares(RESIDUALS[fn.slice(3)]) : OBJECTIVES[fn]);

function optimiseCase(c) {
	const trace = [];
	let count = 0;
	const opts = { ...(c.opts ?? {}) };
	if (c.lower !== undefined) opts.lower = c.lower;
	if (c.upper !== undefined) opts.upper = c.upper;
	opts.onStep = (p) => {
		count += 1;
		trace.push({ evals: p.evals, fx: p.fx, best: p.best, x: Array.from(p.x), bestX: p.bestX ? Array.from(p.bestX) : null });
	};
	if (c.stopAfter != null) opts.signal = { get aborted() { return count >= c.stopAfter; } };
	let result;
	if (c.method.startsWith('METHODS.')) {
		const residuals = RESIDUALS[c.fn.startsWith('ss:') ? c.fn.slice(3) : c.fn];
		const ctx = { start: c.start, objective: objectiveNamed(c.fn), residuals };
		result = opt.METHODS[c.method.slice(8)].run(ctx, opts);
	} else if (c.method === 'nelder') {
		result = opt.nelderMead(objectiveNamed(c.fn), c.start, opts);
	} else if (c.method === 'lm') {
		result = opt.levenbergMarquardt(RESIDUALS[c.fn], c.start, opts);
	} else if (c.method === 'de') {
		if (c.start !== undefined) opts.start = c.start;
		result = opt.differentialEvolution(objectiveNamed(c.fn), opts);
	} else {
		throw new Error(`No method '${c.method}'`);
	}
	return { result, trace };
}

/**
 * localsens.js with one line added: a hook that hands out the augmented
 * system runSensitivity is about to solve, instead of solving it. Loaded from
 * memory, with its imports made absolute, so the application's file is read
 * and never written. Fails loudly if the line it hooks onto has moved.
 */
async function augmentedModule() {
	const dir = path.join(src, 'sim');
	let text = readFileSync(path.join(dir, 'localsens.js'), 'utf8');
	text = text.replace(/from '(\.\.?\/[^']+)'/g,
		(_, rel) => `from '${pathToFileURL(path.join(dir, rel)).href}'`);
	const anchor = '\tconst results = run(project, {';
	if (!text.includes(anchor)) throw new Error('localsens.js has changed: no place for the hook');
	text = text.replace(anchor, '\tif (opts.expose) return opts.expose({ dydt, bigJacobian, Y0, atol, n, m });\n'
		+ anchor);
	return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}`);
}

const guarded = (f) => {
	try {
		return f();
	} catch (e) {
		return { error: e.message, type: e.name };
	}
};

const req = decode(JSON.parse(readFileSync(0, 'utf8')));
let out;
switch (req.task) {
	case 'optimise':
		out = { results: req.cases.map((c) => guarded(() => optimiseCase(c))) };
		break;
	case 'objective':
		out = { results: req.cases.map((c) => guarded(() => opt.objectiveOf(c.readings, c.targets))) };
		break;
	case 'precision':
		out = { results: req.values.map((v) => v.toPrecision(12)) };
		break;
	case 'slots':
		out = guarded(() => {
			const sys = buildSystem(new Project(req.model));
			return { slots: parameterSlots(sys).map((e) => ({ ...e, label: slotLabel(e), keys: Object.keys(e.index) })) };
		});
		break;
	case 'sensitivity':
		out = guarded(() => {
			const r = runSensitivity(req.model, req.opts ?? {});
			return {
				t: r.t,
				y: r.y,
				sens: r.sens,
				chosen: r.chosen,
				states: r.states.map((s) => ({ name: s.name, base: s.base, width: s.width, kind: s.kind })),
				series: r.series,
				stats: { nsteps: r.stats.nsteps, states: r.stats.states, restarts: r.stats.restarts },
				elasticity: r.chosen.map((c, k) => r.y.map((row, i) => elasticity(row, r.sens[k][i], c.value))),
			};
		});
		break;
	case 'augmented': {
		const mod = await augmentedModule();
		out = guarded(() => mod.runSensitivity(req.model, {
			...(req.opts ?? {}),
			expose: ({ dydt, bigJacobian, Y0, atol, n, m }) => ({
				y0: Y0, atol, n, m,
				pattern: { n: bigJacobian.pattern.n, colPtr: bigJacobian.pattern.colPtr, rowIdx: bigJacobian.pattern.rowIdx },
				groups: bigJacobian.groups,
				points: req.points.map(({ t, Y }) => {
					const f = dydt(t, Float64Array.from(Y), new Array(Y.length));
					const J = bigJacobian.evaluate(t, Float64Array.from(Y));
					return { f: Array.from(f), J: J ? Array.from(J) : null };
				}),
			}),
		}));
		break;
	}
	case 'pvp':
		out = guarded(() => {
			const sys = buildSystem(new Project(req.model));
			const pt = sys.paramTangent();
			return {
				available: pt.available,
				reason: pt.reason ?? null,
				points: pt.available ? req.points.map(({ t, y, seed }) => Array.from(
					pt.pvp(t, Float64Array.from(y), Float64Array.from(seed)))) : [],
			};
		});
		break;
	case 'variables':
		out = guarded(() => ({ variables: variablesOf(req.model) }));
		break;
	case 'reading':
		out = guarded(() => {
			const res = run(req.model, { onGrid: true });
			return { readings: req.targets.map((t) => readingOf(res, t)) };
		});
		break;
	case 'calibrate':
		out = guarded(() => {
			const progress = [];
			const opts = { ...(req.opts ?? {}) };
			opts.onProgress = (p) => { progress.push(p); };
			if (req.stopAfter != null) {
				opts.signal = { get aborted() { return progress.length >= req.stopAfter; } };
			}
			const result = calibrate(req.model, opts);
			delete result.ms;
			return { result, progress };
		});
		break;
	default:
		throw new Error(`No task '${req.task}'`);
}
process.stdout.write(JSON.stringify(encode(out)));
