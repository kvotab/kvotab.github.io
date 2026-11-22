// The application's Check the run, for the Python package's tests to compare with
// (tests/test_checkrun.py).
//
//   node checkrun.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } and the answer one JSON object on stdout:
//
//   labels   { models: [...] }            -> stateLabels of each model's built system, or { error }
//   tighten  { models: [...] }            -> tightenTolerances of each, and the model it leaves
//   compare  { model, held, careful }     -> compareRuns of two runs given as { t, y } (y a row
//                                           per time) over the model's built system
//   check    { model }                    -> checkRun of a run of the model: the report (without
//                                           the careful run's ms) and both runs' { t, y, steps }
//
// JSON has no NaN or infinities, and they matter here, so both directions spell them
// { "$": "NaN" | "Infinity" | "-Infinity" }.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const { Project } = await load('domain/project.js');
const { buildSystem } = await load('sim/builder.js');
const { run } = await load('sim/runner.js');
const { stateLabels } = await load('sim/jaccheck.js');
const { tightenTolerances, compareRuns, checkRun } = await load('sim/checkrun.js');

const encode = (x) => {
	if (typeof x === 'number') {
		if (Number.isNaN(x)) return { $: 'NaN' };
		if (x === Infinity) return { $: 'Infinity' };
		if (x === -Infinity) return { $: '-Infinity' };
		return x;
	}
	if (ArrayBuffer.isView(x)) return Array.from(x, encode);
	if (Array.isArray(x)) return x.map(encode);
	if (x && typeof x === 'object') return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, encode(v)]));
	return x;
};
const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity };
const decode = (x) => {
	if (Array.isArray(x)) return x.map(decode);
	if (x && typeof x === 'object') {
		const keys = Object.keys(x);
		if (keys.length === 1 && keys[0] === '$') return SPECIAL[x.$];
		return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, decode(v)]));
	}
	return x;
};

const req = decode(JSON.parse(readFileSync(0, 'utf8')));
let out;
switch (req.task) {
	case 'labels':
		out = {
			labels: req.models.map((m) => {
				try {
					return stateLabels(buildSystem(new Project(m)).layout);
				} catch (e) {
					return { error: e.message };
				}
			}),
		};
		break;
	case 'tighten':
		out = {
			cases: req.models.map((m) => {
				const model = structuredClone(m);
				const said = tightenTolerances(model);
				return { said, model };
			}),
		};
		break;
	case 'compare': {
		const project = new Project(req.model);
		const system = buildSystem(project);
		const rows = (r) => r.y.map((row) => Float64Array.from(row));
		out = {
			report: compareRuns(
				{ project, system, t: Float64Array.from(req.held.t), y: rows(req.held) },
				{ t: Float64Array.from(req.careful.t), y: rows(req.careful) },
			),
		};
		break;
	}
	case 'check': {
		const held = run(req.model);
		let careful = null;
		const report = checkRun(held, (p) => { careful = run(p); return careful; });
		delete report.careful.ms;
		const plain = (r) => ({ t: Array.from(r.t), y: r.y.map((row) => Array.from(row)), steps: r.stats?.nsteps ?? null });
		out = { report, held: plain(held), careful: plain(careful) };
		break;
	}
	default:
		throw new Error(`No task '${req.task}'`);
}
process.stdout.write(JSON.stringify(encode(out)));
