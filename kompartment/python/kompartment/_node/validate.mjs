// Kompartment's own checks on a model, for the Python package's Model.validate().
//
//   node validate.mjs <kompartment src directory> < model.json
//
// Loads the model the way the application opens a file, checks every equation
// with the editor's checker, reads the simulation settings, constructs the
// Project and builds the system as a run would. Prints one JSON object:
// { errors: [{message, block}], warnings: [{name, message}] }.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
if (!src) {
	process.stderr.write('usage: node validate.mjs <kompartment src directory> < model.json\n');
	process.exit(2);
}
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const { Project } = await load('domain/project.js');
const ed = await load('domain/edit.js');
const { buildSystem } = await load('sim/builder.js');

const out = { errors: [], warnings: [] };
const fail = (e, block = null) => out.errors.push({
	message: String(e?.message ?? e),
	block: block ?? e?.blockName ?? null,
});

let raw = null;
try {
	raw = JSON.parse(readFileSync(0, 'utf8'));
} catch (e) {
	fail(`The model is not JSON: ${e.message}`);
}
if (raw && (typeof raw !== 'object' || Array.isArray(raw))) {
	fail('A model is one JSON object');
	raw = null;
}
if (raw) {
	try {
		raw = ed.migrateKeys(raw);
		ed.materialiseShorthand(raw);
		ed.syncDerivedUnits(raw);
	} catch (e) {
		fail(e);
	}
	try {
		for (const p of ed.allEquationProblems(raw)) {
			fail(`${p.name}: ${p.field}${p.index ? ` [${Object.values(p.index).join(', ')}]` : ''}: ${p.message}`, p.name);
		}
	} catch (e) {
		fail(e);
	}
	try {
		for (const p of ed.simulationProblems(raw)) fail(`Simulation ${p.key}: ${p.message}`);
	} catch (e) {
		fail(e);
	}
	let project = null;
	try {
		project = new Project(raw);
	} catch (e) {
		fail(e);
	}
	if (project) {
		try {
			buildSystem(project, { jacobian: false });
		} catch (e) {
			fail(e);
		}
	}
	try {
		for (const w of ed.modelWarnings(raw)) out.warnings.push({ name: w.name ?? null, message: w.message });
	} catch (e) {
		out.warnings.push({ name: null, message: `The warnings could not be worked out: ${e.message}` });
	}
}
process.stdout.write(JSON.stringify(out));
