// The application's Ecolego exporter, for the Python package's tests to compare with.
//
//   node eco_export.mjs <kompartment src directory> < request.json
//
// A request is one task, or { task: 'batch', requests: [...] } for several at
// once (one Node start-up instead of one per model); the answer is one JSON
// value on stdout, a list of answers for a batch. Binary data travels as base64.
//
//   fixtures   {}                                  -> { models }: the made-up models of
//                                                     ../test/eco-export-fixture.js
//   export     { model, modified? }                -> { base64, xml, report } from exportEco;
//                                                     modified = [y, month 1-12, d, h, mi, s], local
//   import     { base64 }                          -> { project, report } from importEcoFile
//   roundtrip  { model }                           -> the export, and what importEcoFile makes of it
//   canonical  { model, exclude, imported }        -> canonicalModel: what a model means, as JSON
//   numbers    { values }                          -> javaDouble of each, and secondsFor
//
// A task that throws answers { error: { name, message } } instead. The reports
// are written out as plain data, with `ok` and `summary()` alongside.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const eco = await load('io/ecoexport.js');
const { importEcoFile } = await load('io/eco.js');
const fixture = await import(pathToFileURL(path.join(src, '..', 'test', 'eco-export-fixture.js')).href);

const b64 = (u8) => Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength).toString('base64');
const unb64 = (s) => new Uint8Array(Buffer.from(s, 'base64'));
const plain = (x) => JSON.parse(JSON.stringify(x));

const exportReport = (r) => ({
	skipped: r.skipped, rewritten: r.rewritten, renamed: r.renamed, warnings: r.warnings,
	counts: r.counts, ok: r.ok, summary: r.summary(),
});
const importReport = (r) => ({
	skipped: r.skipped, notes: r.notes, renamed: r.renamed, disabled: r.disabled,
	disabled_systems: r.disabledSystems ? Object.fromEntries(r.disabledSystems) : null,
	warnings: r.warnings, counts: r.counts, ok: r.ok, summary: r.summary(),
});

async function answer(req) {
	try {
		switch (req.task) {
			case 'fixtures':
				return { models: plain(fixture.EXPORT_MODELS) };
			case 'export': {
				const options = req.modified ? { modified: new Date(req.modified[0], req.modified[1] - 1, ...req.modified.slice(2)) } : {};
				const out = await eco.exportEco(req.model, options);
				return { base64: b64(out.bytes), xml: out.xml, report: exportReport(out.report) };
			}
			case 'import': {
				const { project, report } = await importEcoFile(unb64(req.base64));
				return { project: plain(project), report: importReport(report) };
			}
			case 'roundtrip': {
				const out = await eco.exportEco(req.model);
				const { project, report } = await importEcoFile(out.bytes);
				return {
					base64: b64(out.bytes), report: exportReport(out.report),
					project: plain(project), imported: importReport(report),
				};
			}
			case 'canonical':
				return { canonical: plain(fixture.canonicalModel(req.model, { exclude: req.exclude ?? [], imported: !!req.imported })) };
			case 'numbers':
				return {
					java: req.values.map((v) => eco.javaDouble(v)),
					seconds: req.values.map((v) => (typeof v === 'number' && v > 0 && Number.isFinite(v) ? eco.javaDouble(eco.secondsFor(v)) : null)),
				};
			default:
				throw new Error(`No task '${req.task}'`);
		}
	} catch (e) {
		return { error: { name: e.name, message: e.message } };
	}
}

const req = JSON.parse(readFileSync(0, 'utf8'));
const out = req.task === 'batch'
	? await Promise.all(req.requests.map((r) => answer(r)))
	: await answer(req);
process.stdout.write(JSON.stringify(out));
