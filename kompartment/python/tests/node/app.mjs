// The application's own code, for the Python package's tests to compare with.
//
//   node app.mjs <kompartment src directory> < request.json
//
// A request is { task, ... } and the answer one JSON object on stdout:
//
//   normalise  { model }           -> the model as the application holds it on opening
//   edit       { model, ops }      -> each [fn, ...args] of edit.js applied in turn, the
//                                     after-edit tidy (pruneLayout, syncDerivedUnits)
//                                     after each; { model } or { error, at }
//   chains     { nuclides, ceiling } -> defaultChains
//   stamps     { model }           -> { name: stamp } for every block
//   numbers    { values }          -> String(x) for each
//   count      { model }           -> stateCount

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const ed = await load('domain/edit.js');
const qa = await load('domain/qa.js');
const nuclides = await load('domain/nuclides.js');
const { qualifiedName } = await load('domain/systems.js');

const req = JSON.parse(readFileSync(0, 'utf8'));
const open = (raw) => {
	const m = ed.migrateKeys(raw);
	ed.materialiseShorthand(m);
	ed.syncDerivedUnits(m);
	return m;
};
const plain = (x) => JSON.parse(JSON.stringify(x));
let out;
switch (req.task) {
	case 'normalise':
		out = { model: open(req.model) };
		break;
	case 'edit': {
		const m = req.opened ? req.model : open(req.model);
		out = { model: null };
		let at = 0;
		try {
			for (const [fn, ...args] of req.ops) {
				if (typeof ed[fn] !== 'function') throw new Error(`edit.js has no ${fn}`);
				ed[fn](m, ...args);
				ed.pruneLayout(m);
				ed.syncDerivedUnits(m);
				at++;
			}
			out.model = m;
		} catch (e) {
			out = { error: e.message, at, model: m };
		}
		break;
	}
	case 'chains':
		out = { chains: nuclides.defaultChains(req.nuclides, req.ceiling ?? Infinity) };
		break;
	case 'stamps': {
		const m = open(req.model);
		const stamps = {};
		for (const kind of ed.KINDS) for (const b of m[kind] ?? []) stamps[qualifiedName(b)] = qa.stamp(b);
		out = { stamps };
		break;
	}
	case 'numbers':
		out = { strings: req.values.map((v) => String(v)) };
		break;
	case 'count':
		out = { count: ed.stateCount(open(req.model)) };
		break;
	default:
		throw new Error(`No task '${req.task}'`);
}
process.stdout.write(JSON.stringify(plain(out)));
