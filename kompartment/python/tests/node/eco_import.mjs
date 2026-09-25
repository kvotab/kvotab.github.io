// The application's Ecolego importer, for the Python package's tests to compare with.
//
//   node eco_import.mjs <kompartment src directory> < request.json
//
// A request is one task, or { task: 'batch', requests: [...] } for several at
// once (one Node start-up instead of one per file); the answer is one JSON
// value on stdout, a list of answers for a batch:
//
//   fixtures  {}                                  -> the texts test/eco-fixture.js exports
//   xml       { text, fileName?, version? }       -> importModelXML: { project, report } or { error }
//   file      { base64, fileName?, version? }     -> importEcoFile on those bytes: the same
//   zip       { files: [{ name, text, deflate }] } -> { base64 } of the fixture's makeZip archive
//   utf16     { text }                            -> { base64 } of the fixture's toUtf16BE
//
// The fixture is the hand-written synthetic model in ../test/eco-fixture.js,
// next to the src directory; the report is written out as plain data, with
// `disabledSystems` (a Map) as an object and `ok` and `summary()` alongside.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const eco = await load('io/eco.js');
const fixture = await import(pathToFileURL(path.join(src, '..', 'test', 'eco-fixture.js')).href);

const reportOf = (r) => ({
	skipped: r.skipped,
	notes: r.notes,
	renamed: r.renamed,
	disabled: r.disabled,
	disabled_systems: r.disabledSystems ? Object.fromEntries(r.disabledSystems) : null,
	warnings: r.warnings,
	counts: r.counts,
	ok: r.ok,
	summary: r.summary(),
});

const meta = (req) => ({ fileName: req.fileName ?? undefined, version: req.version ?? undefined });

const imported = async (read) => {
	try {
		const { project, report } = await read();
		// Through JSON, as a saved file would be: what the Python side is
		// compared with is what the application would write.
		return { project: JSON.parse(JSON.stringify(project)), report: reportOf(report) };
	} catch (e) {
		return { error: { name: e.name, message: e.message } };
	}
};

const base64 = (bytes) => Buffer.from(bytes).toString('base64');

async function answer(req) {
	switch (req.task) {
		case 'fixtures':
			return {
				MODEL_XML: fixture.MODEL_XML,
				VIEWS_XML: fixture.VIEWS_XML,
				REAL_SHAPES_XML: fixture.REAL_SHAPES_XML,
				SHEET_XML: fixture.SHEET_XML,
				TRANSPORT_XML: fixture.TRANSPORT_XML,
			};
		case 'xml':
			return imported(() => eco.importModelXML(req.text, meta(req)));
		case 'file':
			return imported(() => eco.importEcoFile(
				new Uint8Array(Buffer.from(req.base64, 'base64')), meta(req)));
		case 'zip':
			return { base64: base64(await fixture.makeZip(req.files)) };
		case 'utf16':
			return { base64: base64(fixture.toUtf16BE(req.text)) };
		default:
			throw new Error(`No task '${req.task}'`);
	}
}

const req = JSON.parse(readFileSync(0, 'utf8'));
const out = req.task === 'batch'
	? await Promise.all(req.requests.map((r) => answer(r)))
	: await answer(req);
process.stdout.write(JSON.stringify(out));
