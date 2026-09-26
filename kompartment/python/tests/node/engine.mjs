// The application's own engine, for the Python engine's tests to compare with.
//
//   node engine.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } and the answer one JSON object on stdout:
//
//   project  { model }                 -> the Project the application builds from it
//   grid     { model }                 -> the output times
//   layout   { model }                 -> the built system's states, slots and flags
//   jacobian { model }                 -> whether df/dy is generated, and whether it is constant
//   dydt     { model, points: [{t, y}] } -> the derivative and every algebraic slot at each
//   run      { model, overrides }      -> the run's times and every output series
//   atstart  { model, names }          -> valuesAtStart(...).of(name) for each name
//   lu       { cases: [{n, a, colPtr, rowIdx, values, mass, b}] } -> the dense LU's factors and solution
//   partition { model }                -> partitionOf(system): ok, refusal, count, of, sizes, largest
//   plan     { model, opts: [...] }    -> stateKeys, stateMaterials and splitJobs of the built system,
//                                        planSplit(system, project, o) for each o of opts, and the
//                                        constants auto decides by
//
// Infinity and NaN travel as the strings 'Infinity', '-Infinity' and 'NaN'.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const { Project } = await load('domain/project.js');
const { buildSystem } = await load('sim/builder.js');
const { parse } = await load('parser/parser.js');
const { FUNCTIONS } = await load('parser/functions.js');
const { run } = await load('sim/runner.js');
const prob = await load('sim/probabilistic.js');
const { valuesAtStart } = await load('sim/atstart.js');
const { LU } = await load('ode/core/linalg.js');
const { partitionOf } = await load('sim/partition.js');
const split = await load('sim/split.js');
const { layerDepths } = await load('domain/farfield.js');
const farf = await load('domain/farfield.js');

const req = JSON.parse(readFileSync(0, 'utf8'), (k, v) => (
	v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : v === 'NaN' ? NaN : v));

const COLLECTIONS = [
	'parameters', 'compartments', 'expressions', 'transfers', 'inflows',
	'lookups', 'index_reductions', 'block_reductions', 'functions',
	'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
	'farfields', 'waste_packages', 'events',
];

const plain = (x) => JSON.parse(JSON.stringify(x, (k, v) => {
	if (typeof v === 'number' && !Number.isFinite(v)) return String(v);
	if (v instanceof Set) return [...v].sort();
	if (v instanceof Map) return Object.fromEntries(v);
	if (ArrayBuffer.isView(v)) return Array.from(v, (n) => (Number.isFinite(n) ? n : String(n)));
	return v;
}));

function projectDump(p) {
	const out = {
		name: p.name,
		simulation: p.simulation,
		outputTimes: p.outputTimes,
		outputMode: p.outputMode,
		nuclides: p.nuclides,
		decayUnit: p.decayUnit,
		decayCeiling: p.decayCeiling,
		index_lists: p.index_lists,
		materialListName: p.materialListName,
		nuclideListName: p.nuclideListName,
		chains: p.chains,
		scenario: p.scenario,
		scenarios: p.scenarios,
		disabled: p.disabled,
		implicitlyDisabled: p.implicitlyDisabled,
		systems: p.systems,
		transports: p.transports,
		disabledSystems: p.disabledSystems,
		decayModel: p.decayModel(),
		timeGrid: p.timeGrid(),
		blocks: {},
	};
	for (const c of COLLECTIONS) out.blocks[c] = p[c];
	return out;
}

let out;
switch (req.task) {
	case 'project': {
		try {
			out = { project: projectDump(new Project(req.model)) };
		} catch (e) {
			out = { error: e.message, kind: e.name };
		}
		break;
	}
	case 'parse': {
		out = {
			results: req.equations.map((eq) => {
				try {
					return { ast: parse(eq, { calls: (n) => (req.calls ?? []).includes(n) }) };
				} catch (e) {
					return { error: e.message, position: e.position ?? null };
				}
			}),
		};
		break;
	}
	case 'functions': {
		const ctx = { t: 12.5, startTime: 0, endTime: 1000 };
		out = {
			results: req.calls.map(([name, ...args]) => {
				try {
					const spec = FUNCTIONS[name];
					return { value: spec.needsContext ? spec.fn(ctx, ...args) : spec.fn(...args) };
				} catch (e) {
					return { error: e.message };
				}
			}),
		};
		break;
	}
	case 'layout': {
		try {
			const sys = buildSystem(new Project(req.model), { jacobian: false });
			const L = sys.layout;
			out = {
				nstate: L.nstate, nalg: L.nalg, nparam: L.nparam,
				slotClass: L.slotClass,
				states: L.states.map((s) => ({
					name: s.name, base: s.base, width: s.width, dims: s.dims, kind: s.kind,
					hidden: !!s.hidden, role: s.role ?? null,
				})),
				algebraic: L.algebraic.map((a) => ({
					name: a.name, base: a.base, width: a.width, dims: a.dims, kind: a.kind,
					hidden: !!a.hidden, uniform: !!a.uniform, readsAlg: a.readsAlg ?? [],
				})),
				parameters: L.parameters.map((p) => ({ name: p.name, base: p.base, width: p.width, dims: p.dims })),
				P: sys.parameterValues,
				X: sys.evaluateAlgebraic(new Project(req.model).simulation.start_time, sys.initialState()),
				y0: sys.initialState(),
			};
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'jacobian': {
		try {
			const sys = buildSystem(new Project(req.model));
			const j = sys.jacobian ?? {};
			out = { available: !!j.available, constant: j.available ? !!j.constant : null, reason: j.reason ?? null,
				nnz: j.pattern?.nnz ?? null, colours: j.groups?.length ?? null };
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'dydt': {
		try {
			const sys = buildSystem(new Project(req.model), { jacobian: false });
			out = {
				points: req.points.map(({ t, y }) => {
					const yy = Float64Array.from(y);
					const X = Float64Array.from(sys.evaluateAlgebraic(t, yy));
					const d = new Float64Array(yy.length);
					sys.dydt(t, yy, d);
					return { X, dydt: d };
				}),
			};
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'run': {
		try {
			const model = structuredClone(req.model);
			model.simulation = { ...(model.simulation ?? {}), ...(req.overrides ?? {}) };
			const t0 = performance.now();
			const res = run(model);
			const ms = performance.now() - t0;
			const outs = res.outputs();
			const cols = res.seriesMany(outs);
			out = {
				t: res.t, labels: outs.map((o) => o.label), columns: cols, stats: res.stats, ms,
				mass: res.massBalance?.() ?? null,
			};
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'atstart': {
		try {
			const v = valuesAtStart(new Project(req.model));
			const one = (n) => {
				const r = v.of(n);
				return r ? { ...r, fields: Object.fromEntries(r.fields) } : null;
			};
			out = { t0: v.t0, size: v.size, of: Object.fromEntries(req.names.map((n) => [n, one(n)])) };
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'lu': {
		out = req.cases.map((c) => {
			const lu = new LU(c.n);
			lu.formAndFactor(c.a, { n: c.n, colPtr: c.colPtr, rowIdx: c.rowIdx }, c.values, null, c.mass ?? null);
			if (lu.singular) return { singular: true, column: lu.failColumn, nonFinite: lu.nonFinite };
			return { lu: lu.lu.map((r) => Array.from(r)), piv: Array.from(lu.piv), x: Array.from(lu.solve(Float64Array.from(c.b))) };
		});
		break;
	}
	case 'layer_depths': {
		out = req.cases.map(([penDep, nm, aw, first]) => Array.from(layerDepths(penDep, nm, aw, first)));
		break;
	}
	case 'farfield_grids': {
		// The matched matrix layers, the semi-infinite outlet's extra cells and
		// one nuclide's rates over them, for cases the test makes up.
		out = {
			grids: req.grids.map((g) => {
				try {
					const r = farf.matchedGrid(g);
					return { d: Array.from(r.d), h: Array.from(r.h), q: r.q };
				} catch (e) { return { error: e.message }; }
			}),
			extra: req.extra.map(([nf, pe]) => farf.autoExtraCells(nf, pe)),
			rates: req.rates.map((s) => {
				try {
					const c = farf.coefficients(s);
					return {
						aw: c.aw, advF: c.advF, dF: c.dF, fDf: c.fDf, diffFM1: c.diffFM1, diffM1F: c.diffM1F,
						diffMMF: Array.from(c.diffMMF), diffMMB: Array.from(c.diffMMB), d: Array.from(c.d),
					};
				} catch (e) { return { error: e.message }; }
			}),
		};
		break;
	}
	case 'probabilistic': {
		try {
			const o = { ...(req.opts ?? {}) };
			if (req.keep) o.keep = (name, out) => req.keep.includes(name) || req.keep.includes(out.label);
			const r = prob.runProbabilistic(req.model, o);
			out = {
				t: r.t, labels: r.outputs.map((x) => x.label), values: r.values, samples: r.samples,
				names: r.plan.map(prob.slotName), iterations: r.iterations, ran: r.ran,
				stats: { ...r.stats, ms: undefined },
				quantiles: r.outputs.length
					? prob.quantiles(r.values[0], r.t.length, r.iterations).map((q) => q.y) : null,
			};
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'partition': {
		try {
			const p = partitionOf(buildSystem(new Project(req.model)));
			out = { ok: p.ok, refusal: p.refusal, count: p.count, of: p.of, sizes: p.sizes, largest: p.largest };
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	case 'plan': {
		try {
			const project = new Project(req.model);
			const sys = buildSystem(project);
			const jobs = split.splitJobs(sys);
			const plans = (req.opts ?? [{}]).map((o) => {
				const p = split.planSplit(sys, project, o);
				return {
					use: p.use, mode: p.mode, why: p.why, predicted: p.predicted ?? null,
					jobs: p.jobs ?? null, owner: p.owner ?? null, bins: p.bins ?? null, parts: p.parts ?? null,
				};
			});
			out = {
				keys: split.stateKeys(sys.layout), materials: split.stateMaterials(sys.layout),
				jobs: jobs.ok ? { ok: true, jobs: jobs.jobs, owner: jobs.owner, parts: jobs.parts } : { ok: false, why: jobs.why },
				plans,
				constants: {
					SHARED_WORK: split.SHARED_WORK, START_MS: split.START_MS, AUTO_SOLVE_MS: split.AUTO_SOLVE_MS,
					AUTO_STATES: split.AUTO_STATES, AUTO_GAIN: split.AUTO_GAIN, AUTO_GAIN_UNTIMED: split.AUTO_GAIN_UNTIMED,
				},
			};
		} catch (e) {
			out = { error: e.message, kind: e.name, stack: e.stack };
		}
		break;
	}
	default:
		throw new Error(`No task '${req.task}'`);
}
process.stdout.write(JSON.stringify(plain(out)));
