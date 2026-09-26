/**
 * Importer for Ecolego project files (.eco) and assessment files (.eas).
 *
 * A .eco file is a ZIP of the project folder; the model itself lives in
 * model.xml. This reads that XML.
 *
 * An .eas file -- an assessment -- is the same archive with a run in it: the
 * same model.xml, views.xml and simulation.xml, plus a `simulation/` folder of
 * `.dta` result files and the raw data a lookup table was linked to. This tool
 * reads the model out of one exactly as it reads a project, and ignores the
 * results: they are the answer Ecolego got, and the point of this tool is to
 * get that answer here. Nothing extra is needed to accept one, which is why
 * this file has no code that mentions the extension -- the application decides
 * what to hand it (see OPEN_ACCEPT in ../ui/app.js).
 *
 * The mapping is deliberately lossy and says so. Ecolego's data model has
 * around thirty block types and a great deal of presentation state; this tool
 * implements five block types. Anything else is skipped and listed in the
 * report, so the result is either usable or explicitly incomplete -- never
 * silently wrong.
 *
 * Two container formats are accepted:
 *   - a ZIP archive with model.xml at its root (Ecolego 6)
 *   - a bare XML file, usually UTF-16 with a BOM (the older Ecolego 4/5 format)
 *
 * Where a file and the documentation disagree, the file wins: block type
 * names and their defaults are read off real project files rather than
 * assumed.
 */

import { unzip, ZipError } from './zip.js';
import { STABLE, KINDS, SINGULAR, KIND_LABEL, stateCount } from '../domain/edit.js';
import { FUNCTIONS, FUNCTION_ALIASES } from '../parser/functions.js';
import {
	parseXML,
	child,
	children,
	childText,
	childNumber,
	childBool,
	find,
	XMLError,
} from './xml.js';
import { SECONDS_PER_YEAR } from '../domain/nuclides.js';
import { interpolationFromEco } from '../domain/lookup.js';
import { parsePDF } from '../domain/pdf.js';
import { operationFromEco } from '../domain/reduce.js';
import {
	KIND_FROM_ECO,
	EQUATION_FIELDS,
	EVENT_FIELDS,
	extremeFromEco,
	directionFromEco,
} from '../domain/recorders.js';
import { resolveReference } from '../domain/systems.js';
import { DEFAULT_SOLVER, solverName } from '../ode/solvers.js';
import { DEFAULT_SIMULATION } from '../domain/project.js';

export class ImportError extends Error {
	constructor(message) {
		super(message);
		this.name = 'ImportError';
	}
}

/**
 * A fixed lookup table that is safe to index with text out of the file.
 *
 * On a plain object `UNITS['constructor']` is `Object`, so
 * `<time-unit>constructor</time-unit>` set the run's time unit to a function,
 * and `MODES['__proto__']` is `Object.prototype`, which is truthy. Every table
 * below that is indexed by something the file wrote goes through this, and so
 * answers only for the keys it was given.
 */
const lookup = (entries) => Object.assign(Object.create(null), entries);

/** Block types that become blocks in this tool. */
const SUPPORTED = new Set([
	'compartment', 'expression', 'parameter',
	// the file format treats these as expressions with an evaluation mode.
	'post-processing', 'constant',
	// Time-dependent data.
	'lookup-table',
	// Reductions: over one of a block's index lists, and over several blocks.
	'index-operation', 'aggregate',
	// The blocks that depend on what has already happened, and the events that
	// drive them. See ../domain/recorders.js.
	'min-max', 'running-mean', 'snapshot', 'delay', 'discrete-event',
	// Connections.
	'transfer', 'transfer-coefficient',
	// The parts of a transport sub-system: two compartments, an expression,
	// and two blocks of their own that this tool carries as expressions. See
	// ../domain/transport.js.
	'transport-begin', 'transport-end', 'transport-number',
	'transport-element-counter', 'transport-operation',
]);

/** The part each transport block type plays. */
const TRANSPORT_ROLE = lookup({
	'transport-begin': 'begin',
	'transport-end': 'end',
	'transport-number': 'number',
	'transport-element-counter': 'counter',
	'transport-operation': 'operation',
});

/**
 * Source and sink components are Ecolego's model boundary: transfers attach to
 * them. This tool represents the boundary as a null endpoint instead, so these
 * are not lost -- they are folded into the transfers that touch them.
 */
const BOUNDARY = new Set(['source', 'sink']);

/**
 * Connections that carry no mass and so do not affect the numbers. Influence
 * declares a dependency for evaluation ordering, which this tool derives from
 * the equations themselves.
 */
const NON_NUMERIC = new Set(['influence']);

/**
 * Ecolego's sub-system interface: a way to route a value across a sub-system
 * boundary, and nothing else.
 *
 * A `model-output` block lists blocks inside its sub-system that may be read
 * from outside; a `model-input` lists blocks inside its own that may be fed
 * from outside; and a `connector` between the two carries
 * `<model-connection source target/>` pairs naming one of each by GUID. What
 * that *means* is written out by the model-input code generator: the target's own
 * calculation is replaced by a reference to the source, and where several
 * sources feed one target they are combined with the operation named on the
 * input -- `sum`, `max`, `min`, `mean` or `prod`.
 *
 * The blocks exist so that a sub-system can be lifted out as a black box and
 * dropped into another project with its wiring left dangling, ready to be
 * connected. This tool has no library of ready-made sub-systems and so has no
 * use for the concept -- but a model that arrives already wired has to keep
 * working, and *not* carrying the wiring is not neutral: an unconnected input
 * block is a placeholder, and in the corpus those placeholders read `0.0`. An
 * import that dropped the connections left a biosphere model receiving nothing
 * at all, ran, and produced zeroes.
 *
 * So the three blocks are read for their wiring and then thrown away, and the
 * wiring is written straight into the blocks at each end -- see
 * `connectInterfaces`. Nothing of the interface survives into the model.
 */
const INTERFACE = new Set(['model-input', 'model-output', 'connector']);

/**
 * How several outputs into one input are combined. `ModelInput.Operation`,
 * and this tool's own functions happen to be spelled the same way.
 */
const INTERFACE_OPERATION = lookup({
	ADD: 'sum', MAX: 'max', MIN: 'min', MEAN: 'mean', PRODUCT: 'prod',
});

/**
 * multiply-with-donor defaults, from the file format: a plain `transfer` is
 * created with `new TransferEntry(null, false)` -- an absolute flux -- while
 * the legacy `transfer-coefficient` is created with `true`, a rate multiplied
 * by the donor. An explicit <multiply-with-donor> in an entry overrides both.
 */
const DONOR_DEFAULT = lookup({ transfer: false, 'transfer-coefficient': true });

/**
 * Reads a .eco archive.
 * @param {ArrayBuffer|Uint8Array} data
 * @param {{fileName?: string}} meta what the caller knows and the bytes do not
 * @returns {Promise<{project: object, report: ImportReport}>}
 */
export async function importEcoFile(data, meta = {}) {
	// `onStage` is the page's, for saying how far the import has got (see
	// `importModelXMLStepwise`); the rest is what the file is.
	const { onStage = null, ...info } = meta;
	meta = info;
	const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);

	// Ecolego 4/5 wrote the model as a bare XML file, usually UTF-16 with a
	// BOM. Ecolego 6 zips the project folder. Both carry the .eco extension.
	if (!looksLikeZip(bytes)) {
		const text = decodeXmlBytes(bytes);
		if (/<sheet[\s>]/.test(text)) {
			throw new ImportError(
				'This is an Ecolego 4/5 model: a <sheet> document with a different data '
				+ 'model from Ecolego 6 (compartments live in spreadsheet cells rather '
				+ 'than a block model). This importer reads the Ecolego 6 format. Open '
				+ 'the file in Ecolego and save it again to convert it.',
			);
		}
		if (!/<data-model[\s>]/.test(text)) {
			throw new ImportError(
				'This file is neither a ZIP archive nor an Ecolego model XML. '
				+ 'If it is a project folder, zip it or open its model.xml directly.',
			);
		}
		return importModelXMLStepwise(text, meta, onStage);
	}

	if (onStage) await onStage('unzip');
	let entries;
	try {
		entries = await unzip(bytes);
	} catch (e) {
		if (e instanceof ZipError) throw new ImportError(e.message);
		throw e;
	}

	// model.xml sits at the archive root in practice, but look for it by name
	// anywhere -- and note that these archives are written on Windows, so
	// entry names may use backslashes.
	//
	// By name first, and the bytes only of the one wanted: `unzip` produces
	// most entries on first access rather than up front (see ZipEntries in
	// zip.js), and iterating `[name, bytes]` pairs asked for every one of them
	// -- an .eas assessment's whole `simulation/` folder of results, inflated
	// and held so that its names could be read past.
	const base = (n) => n.split(/[/\\]/).pop();
	let modelXml = null;
	for (const name of entries.keys()) {
		if (base(name) === 'model.xml') { modelXml = decodeXmlBytes(entries.get(name)); break; }
	}
	if (modelXml == null) {
		for (const name of entries.keys()) {
			if (!name.toLowerCase().endsWith('.xml')) continue;
			const text = decodeXmlBytes(entries.get(name));
			if (/<data-model[\s>]/.test(text)) { modelXml = text; break; }
		}
	}
	if (modelXml == null) {
		throw new ImportError(
			`No model.xml in the archive (it holds: ${[...entries.keys()].join(', ') || 'nothing'}). ` +
			`This may be a library or workspace archive rather than a project.`,
		);
	}

	return importModelXMLStepwise(modelXml, { ...meta, version: ecolegoVersion(entries) }, onStage);
}

/**
 * Which Ecolego wrote the archive.
 *
 * `.version` is a properties file at the archive root -- `version=6.5
 * track-changes=false ode-required=true nuclidedb-required=true` -- and the
 * version in it is the one fact in this tool that can say whether a file is
 * older than the format this importer was written against.
 */
function ecolegoVersion(entries) {
	for (const name of entries.keys()) {
		if (name.split(/[/\\]/).pop() !== '.version') continue;
		try {
			const found = /(^|\s)version\s*=\s*([\w.-]+)/.exec(decodeXmlBytes(entries.get(name)));
			return found ? found[2] : null;
		} catch (e) {
			return null;
		}
	}
	return null;
}

function looksLikeZip(bytes) {
	return bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b
		&& (bytes[2] === 0x03 || bytes[2] === 0x05 || bytes[2] === 0x07);
}

/**
 * Decodes XML bytes, honouring a UTF-16 byte-order mark. Ecolego 5 wrote
 * UTF-16BE; a UTF-8 BOM also turns up.
 */
export function decodeXmlBytes(bytes) {
	if (bytes.length >= 2) {
		if (bytes[0] === 0xfe && bytes[1] === 0xff) {
			return new TextDecoder('utf-16be').decode(bytes.subarray(2));
		}
		if (bytes[0] === 0xff && bytes[1] === 0xfe) {
			return new TextDecoder('utf-16le').decode(bytes.subarray(2));
		}
	}
	if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
		return new TextDecoder('utf-8').decode(bytes.subarray(3));
	}
	return new TextDecoder('utf-8').decode(bytes);
}

/**
 * Reads a bare model.xml. Exported so the format can be tested directly.
 *
 * `meta` is what the file around the XML knows and the XML does not: which
 * file this is, and which Ecolego wrote it. Both go into the description.
 *
 * @param {string} text
 * @param {{fileName?: string, version?: string}} meta
 */
export function importModelXML(text, meta = {}) {
	const steps = importSteps(text, meta);
	let r = steps.next();
	while (!r.done) r = steps.next();
	return r.value;
}

/**
 * The same import, a step at a time: `onStage(stage)` is awaited between the
 * steps -- `'xml'` before the XML is parsed, `'blocks'` before the blocks are
 * read, `'settings'` before they are connected and the settings read -- so a
 * page can say where it has got to, and paint, while a large file comes in.
 * Each step is one synchronous stretch: on the largest imported assessment
 * about 0.2 s here, where the whole import is one of 0.4 s.
 *
 * @param {string} text
 * @param {object} meta  as `importModelXML` takes it
 * @param {((stage: string) => unknown)|null} onStage
 */
export async function importModelXMLStepwise(text, meta = {}, onStage = null) {
	const steps = importSteps(text, meta);
	for (let r = steps.next(); ; r = steps.next()) {
		if (r.done) return r.value;
		if (onStage) await onStage(r.value);
	}
}

/** The import, as steps: yields the name of each before it, returns what `importModelXML` does. */
function* importSteps(text, meta) {
	yield 'xml';
	let root;
	try {
		root = parseXML(text);
	} catch (e) {
		if (e instanceof XMLError) throw new ImportError(`model.xml is not valid XML: ${e.message}`);
		throw e;
	}

	const dataModel = root.name === 'data-model' ? root : find(root, 'data-model');
	if (!dataModel) {
		throw new ImportError('The XML has no <data-model> element');
	}

	yield 'blocks';
	const report = new ImportReport();
	const names = new NameMapper(report);

	const project = {
		name: 'Imported project',
		description: '',
		simulation: {},
		index_lists: [],
		parameters: [],
		compartments: [],
		expressions: [],
		transfers: [],
		inflows: [],
		lookups: [],
		index_reductions: [],
		block_reductions: [],
		min_maxes: [],
		running_means: [],
		snapshots: [],
		delays: [],
		triggers: [],
		functions: [],
	};

	const provenance = readProjectProperties(dataModel, project, meta);
	readFunctions(dataModel, project, names, report);
	const materials = readMaterials(dataModel, project, report);
	const indexIds = readIndexLists(dataModel, project, names, report, materials);
	readDecayChains(dataModel, project, report);
	const hierarchy = readHierarchy(dataModel, project, names, report);
	const { blockNameById, wiring } = readBlocks(
		dataModel, project, names, indexIds, report, hierarchy,
	);
	yield 'settings';
	readSimulationSettings(dataModel, project, report);

	// Two rewrites, both textual and both necessary:
	//  - Ecolego block names may contain spaces and punctuation that this
	//    tool's identifiers cannot, so those blocks were renamed above.
	//  - equations may use sub-system-qualified references (`NearField.QParBC`),
	//    which are the block ids. This tool has one flat namespace, so those
	//    resolve to the mapped block name.
	rewriteRenamedReferences(project, names, report, blockNameById);
	dropUnreachableTargets(project, report);

	// What Ecolego's sub-system inputs and outputs connected, connected
	// directly. Last, so the references it writes are the names the model
	// ended up with. See `connectInterfaces`.
	connectInterfaces(project, wiring, blockNameById, report);
	rewriteEndpointIds(project, blockNameById, report);

	const duplicated = names.duplicated();
	if (duplicated.length) {
		report.warn(
			`${duplicated.length} name(s) had to be spelled differently in different `
			+ `sub-systems (${duplicated.slice(0, 6).join(', ')}`
			+ `${duplicated.length > 6 ? '…' : ''}), because the original is not a valid `
			+ `identifier and the tidied form was already taken. A bare reference to one `
			+ `of those was left as written -- check those equations.`,
		);
	}

	// Anything the model uses that this tool has no equivalent for.
	report.finish(project);
	// Last, so the counts are of the model as it ended up rather than as the
	// file spelled it: blocks are renamed, groups flattened, interfaces
	// connected and unreachable targets dropped on the way here.
	project.description = describeModel(project, { ...provenance, ...meta });
	// Who wrote it, as the file says -- beside the name and the description,
	// where a model of this tool's own keeps it.
	if (provenance.author) {
		const { name, description, ...rest } = project;
		return { project: { name, description, author: provenance.author, ...rest }, report };
	}
	return { project, report };
}

/**
 * Wires up what a sub-system interface connected, and drops the interface.
 *
 * A model input or output is a routing device for building a library of
 * ready-made sub-systems: a block inside one sub-system is exposed, a block
 * inside another is fed, and a connector says which feeds which. There is
 * nothing to build on here -- this application has no such library to lift
 * blocks out of -- but the wiring in a model that already has it is not
 * decoration. A model input replaces the fed block's whole calculation with a
 * reference to the one feeding it, and an unconnected input is a placeholder:
 * every one in the corpus reads `0.0` or a constant. Dropping the connections
 * therefore does not leave the model as its author wrote it; it leaves a
 * biosphere model reading zero from the near field, running, and reporting no
 * dose at all.
 *
 * So the two ends are connected directly, which is what the interface meant:
 *
 *   fed block's equation  :=  feeding block            (one source)
 *                             sum(a, b, ...)           (several, per the
 *                                                       operation on the input)
 *
 * A **parameter** that is fed becomes an expression: it no longer holds a
 * number of its own, and this tool's parameters are numbers. Its per-index
 * values go with it, because the generated code reads none of them --
 * the connection replaces the calculation at every index.
 *
 * An input nothing is connected to is left exactly as it is, which is what the
 * file says: it is a socket, and an empty socket has whatever value the block
 * carries.
 *
 * Runs after the two rewrites above rather than inside `readBlocks`, so the
 * references it writes are the names the model ended up with, and so a source
 * that was dropped along the way is seen to be missing rather than referenced.
 */
function connectInterfaces(project, wiring, blockNameById, report) {
	const { links, operations, idByGuid, exposed } = wiring;
	if (!links.length) {
		// Blocks with no connector at all: three projects here carry an input
		// or an output that was never wired to anything, which is exactly the
		// half-built black box the device exists to allow.
		if (exposed.size) {
			const one = exposed.size === 1;
			report.warn(
				`${exposed.size} sub-system input/output${one ? ' was' : 's were'} declared `
				+ `but connected to nothing, so nothing was routed: the `
				+ `${one ? 'block behind it keeps the value' : 'blocks behind them keep the values'} `
				+ `the file gives ${one ? 'it' : 'them'}.`,
			);
		}
		return;
	}

	// Every block that was built, by the qualified name the file gave it.
	const byName = new Map();
	const holders = [
		['parameters', 'parameter'], ['compartments', 'compartment'],
		['expressions', 'expression'], ['transfers', 'transfer'],
		['inflows', 'inflow'], ['lookups', 'lookup'],
		['index_reductions', 'index_reduction'], ['block_reductions', 'block_reduction'],
		['min_maxes', 'min_max'], ['running_means', 'running_mean'],
		['snapshots', 'snapshot'], ['delays', 'delay'],
		['triggers', 'trigger'],
	];
	for (const [collection, kind] of holders) {
		for (const block of project[collection] ?? []) {
			const qname = block.system ? `${block.system}.${block.name}` : block.name;
			byName.set(qname, { collection, kind, block, qname });
		}
	}
	const found = (guid) => {
		const id = idByGuid.get(guid);
		const qname = id == null ? null : blockNameById.get(id);
		return qname == null ? null : byName.get(qname) ?? null;
	};

	const bySource = new Map();
	for (const link of links) {
		if (!bySource.has(link.target)) bySource.set(link.target, []);
		bySource.get(link.target).push(link);
	}

	let joined = 0;
	const lost = [];
	const converted = [];
	for (const [targetGuid, incoming] of bySource) {
		const target = found(targetGuid);
		if (!target) {
			lost.push(incoming[0].via);
			continue;
		}
		const sources = incoming.map((l) => found(l.source)).filter(Boolean);
		if (sources.length !== incoming.length) lost.push(incoming[0].via);
		if (!sources.length) continue;

		const refs = sources.map((s) => s.qname);
		// One source is the reference itself. Several are combined with the
		// operation the input block names -- the model-input code generator prints
		// exactly this call, and defaults to adding them when the file states
		// nothing, which is what every multi-source input in the corpus says.
		const fn = INTERFACE_OPERATION[operations.get(targetGuid) ?? 'ADD'] ?? 'sum';
		const equation = refs.length === 1 ? refs[0] : `${fn}(${refs.join(', ')})`;

		const rewritten = wireInto(project, target, equation);
		if (!rewritten) {
			report.warn(
				`'${target.qname}' is fed by a sub-system interface, and a `
				+ `${String(target.kind).replace(/_/g, ' ')} cannot be: its value was `
				+ `left as the file gives it.`,
			);
			continue;
		}
		if (rewritten === 'converted') converted.push(target.qname);
		joined++;
	}

	if (joined) {
		report.warn(
			`${joined} sub-system input${joined === 1 ? '' : 's'} ${joined === 1 ? 'was' : 'were'} `
			+ `connected straight to what feeds ${joined === 1 ? 'it' : 'them'}. Ecolego routes `
			+ `those through model input and output blocks, which are a way to wire a `
			+ `ready-made sub-system into a project; this tool has no such library, so the `
			+ `two ends are joined directly and the interface blocks are left out.`
			+ (converted.length
				? ` ${converted.slice(0, 4).join(', ')}${converted.length > 4 ? ' and others' : ''} `
					+ `${converted.length === 1 ? 'was a parameter and is' : 'were parameters and are'} `
					+ `now expressions, since what feeds ${converted.length === 1 ? 'it' : 'them'} `
					+ `is not a number.`
				: ''),
		);
	}
	if (lost.length) {
		report.warn(
			`${lost.length} sub-system connection${lost.length === 1 ? '' : 's'} `
			+ `(${[...new Set(lost)].slice(0, 4).join(', ')}) named a block this tool did `
			+ `not import, so ${lost.length === 1 ? 'it' : 'they'} could not be joined up.`,
		);
	}
}

/**
 * Puts one equation where a block's own value was, and says what it had to do.
 *
 * @returns 'rewritten', 'converted' for a parameter that became an expression,
 *   or null for a kind that cannot be fed at all
 */
function wireInto(project, target, equation) {
	const { block, kind } = target;
	// The per-index values go: the generated code reads none of them, since
	// the connection replaces the calculation at every index. Left in place
	// they would override the connection at exactly the indices the model
	// cared enough about to write down.
	const clear = (key) => {
		block.entries = (block.entries ?? [])
			.map((e) => {
				const { [key]: _dropped, ...rest } = e;
				return rest;
			})
			.filter((e) => Object.keys(e).some((k) => k !== 'index'));
		if (!block.entries.length) delete block.entries;
	};

	if (kind === 'expression') {
		block.equation = equation;
		clear('equation');
		return 'rewritten';
	}
	if (kind === 'transfer') {
		block.rate = equation;
		clear('rate');
		return 'rewritten';
	}
	if (kind === 'parameter') {
		// A parameter is a number in this tool, and what feeds it is not one.
		const at = project.parameters.indexOf(block);
		if (at >= 0) project.parameters.splice(at, 1);
		delete block.value;
		clear('value');
		delete block.entries;
		block.equation = equation;
		(project.expressions ??= []).push(block);
		return 'converted';
	}
	return null;
}

/**
 * Substitutes renamed blocks throughout every equation.
 *
 * This is textual rather than token-based, because the original names are
 * exactly the ones the tokenizer cannot handle -- `Deep soil` is three tokens,
 * not one. Longest names are replaced first so that `Soil` never eats part of
 * `Deep soil`, and a match is only accepted when it is not butted up against
 * another identifier character.
 */
function rewriteRenamedReferences(project, names, report, blockNameById = new Map()) {
	// Qualified ids first: they are longer, and `NearField.Water` must be
	// replaced whole rather than having its `Water` tail rewritten. A qualified
	// reference stays qualified -- it is a path through the sub-systems, and
	// only changes here when one of its parts had to be tidied.
	const qualified = [...blockNameById.entries()]
		.filter(([id, to]) => id !== to);
	// Bare references are rewritten only when the tidied name is the same
	// wherever it appears. Ecolego resolves a bare name in the block's own
	// sub-system, and a textual substitution cannot tell those apart, so a name
	// that mapped two ways is left alone and reported instead.
	const ambiguous = new Set(names.duplicated());
	const bare = [...names.byOriginal.entries()]
		.filter(([from, to]) => from !== to && !ambiguous.has(from));

	const seen = new Set();
	const pairs = [...qualified, ...bare]
		.filter(([from, to]) => {
			// An empty `from` is found at every position and the scan below
			// never moves past it, so the import hung; one with no identifier
			// character in it at all -- a block called `" "` -- is not a name
			// anything could have referred to, and rewriting it turned
			// `(a) + (b)` into `(a)_+_(b)`. Neither is a reference.
			if (from === '' || from === to || !IDENT_CHAR.test(from)) return false;
			const k = `${from}\u0000${to}`;
			if (seen.has(k)) return false;
			seen.add(k);
			return true;
		})
		.sort((a, b) => b[0].length - a[0].length);
	if (!pairs.length) return;

	let touched = 0;
	// The pairs that actually changed something, for the warning below.
	const fired = new Map();
	const rewrite = (text) => {
		if (Array.isArray(text)) return text.map(rewrite);
		if (typeof text !== 'string' || text === '') return text;
		let out = text;
		for (const [from, to] of pairs) {
			let at = 0;
			for (;;) {
				const i = out.indexOf(from, at);
				if (i === -1) break;
				const before = out[i - 1];
				const after = out[i + from.length];
				// '.' counts as part of a name here, so the bare `thickness`
				// never eats the tail of `Overpack.thickness`.
				const boundary = (c) => c === undefined || !/[A-Za-z0-9_.]/.test(c);
				if (boundary(before) && boundary(after)) {
					out = out.slice(0, i) + to + out.slice(i + from.length);
					at = i + to.length;
					fired.set(from, to);
				} else {
					at = i + from.length;
				}
			}
		}
		if (out !== text) touched++;
		return out;
	};

	const collections = [
		[project.compartments, ['initial']],
		[project.transfers, ['rate']],
		[project.inflows, ['rate']],
		[project.expressions, ['equation']],
		// A function's body is an equation like any other, and a call of one
		// is a reference to it, so both ends of a rename land here.
		[project.functions, ['equation']],
		// A reducing block names its targets rather than writing an equation,
		// but they are references like any other and have to follow a rename.
		[project.index_reductions, ['target']],
		[project.block_reductions, ['targets']],
		// A block that remembers names its target, and its event fields name a
		// discrete event, which is a reference like any other.
		[project.min_maxes, ['target', 'reset_trigger', 'start_trigger', 'stop_trigger']],
		[project.running_means, ['target', 'reset_trigger', 'start_trigger', 'stop_trigger']],
		[project.snapshots, ['target', 'trigger', 'initial']],
		[project.delays, ['target', 'delay']],
		[project.triggers, ['first', 'second']],
	];
	for (const [list, keys] of collections) {
		for (const block of list ?? []) {
			for (const k of keys) block[k] = rewrite(block[k]);
			for (const entry of block.entries ?? []) {
				for (const k of keys) {
					if (Object.prototype.hasOwnProperty.call(entry, k)) {
						entry[k] = rewrite(entry[k]);
					}
				}
			}
		}
	}

	if (touched) {
		report.warn(
			`Rewrote ${touched} equation(s) to use this tool's block names, including `
			+ `sub-system-qualified references. The substitution is textual, because the `
			+ `original names are not valid identifiers -- check the results.`,
		);
		// A name with an operator in it is also an expression: a block called
		// `A-B` turned every `A - B` in the model into a reference to `A_B`,
		// and the generic line above gave no hint which equations to look at.
		// A name with only spaces in it (`Deep soil`) is not: the text could
		// never have parsed as anything else, so it stays under the line above.
		const risky = [...fired].filter(([from]) => OPERATOR_CHAR.test(from));
		if (risky.length) {
			const shown = risky.slice(0, 6).map(([from, to]) => `'${from}' → '${to}'`).join(', ');
			report.warn(
				`${risky.length} of those names contain${risky.length === 1 ? 's' : ''} `
				+ `operator or bracket characters `
				+ `(${shown}${risky.length > 6 ? ', …' : ''}). Every occurrence of the text `
				+ `in an equation was read as the block -- including where it was written `
				+ `as arithmetic between two other blocks. Check those equations by hand.`,
			);
		}
	}
}

/** One character a name has to contain before a match can be a reference. */
const IDENT_CHAR = /[A-Za-z0-9_]/;
/** The characters that make a name readable as an expression in its own right. */
const OPERATOR_CHAR = /[+\-*/^()[\],]/;

/**
 * Drops a reduction whose target was never imported.
 *
 * An `index-operation` or `aggregate` names the blocks it reduces, and this
 * tool implements a fraction of Ecolego's block types, so a target may simply
 * not be here -- one assessment model reduces a `running-mean`. Keeping the block
 * would fail the whole build over one post-processing quantity; dropping it
 * silently would be worse. So it is removed and listed in the report beside
 * everything else that could not come across.
 */
function dropUnreachableTargets(project, report) {
	const known = new Set();
	for (const kind of ['parameters', 'compartments', 'expressions', 'transfers',
		'inflows', 'lookups', 'index_reductions', 'block_reductions', 'functions',
		'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers']) {
		for (const b of project[kind] ?? []) {
			known.add(b.system ? `${b.system}.${b.name}` : b.name);
		}
	}
	const resolve = (ref, system) => resolveReference(ref, system ?? '', (n) => known.has(n));

	project.index_reductions = (project.index_reductions ?? []).filter((o) => {
		if (o.target && resolve(o.target, o.system)) return true;
		report.skip('index-operation', o.name,
			`it reduces '${o.target ?? '(nothing)'}', which is not in this model`);
		known.delete(o.system ? `${o.system}.${o.name}` : o.name);
		return false;
	});

	project.block_reductions = (project.block_reductions ?? []).filter((g) => {
		const kept = (g.targets ?? []).filter((t) => resolve(t, g.system));
		if (kept.length === (g.targets ?? []).length) return true;
		const lost = (g.targets ?? []).filter((t) => !resolve(t, g.system));
		if (!kept.length) {
			report.skip('aggregate', g.name,
				`none of the blocks it reduces (${lost.join(', ')}) is in this model`);
			known.delete(g.system ? `${g.system}.${g.name}` : g.name);
			return false;
		}
		g.targets = kept;
		report.warn(
			`'${g.name}' reduces ${lost.length} block(s) this tool did not import `
			+ `(${lost.slice(0, 4).join(', ')}${lost.length > 4 ? '…' : ''}); `
			+ `they were left out of the total.`,
		);
		return true;
	});
}

// --- report ------------------------------------------------------------------

export class ImportReport {
	constructor() {
		this.skipped = [];   // { type, name, why }
		this.notes = [];     // { type, name } -- present but numerically inert
		this.renamed = [];   // { from, to }
		this.disabled = [];  // qualified names: imported, and switched off as in Ecolego
		this.warnings = [];
		this.counts = {};
	}

	skip(type, name, why) { this.skipped.push({ type, name, why }); }
	/**
	 * Imported whole, and left out of the run, exactly as the file says.
	 * `via` is the disabled sub-system it is inside, when that is the reason.
	 */
	disable(name) { this.disabled.push(name); }
	/** A block inside a sub-system the file switches off as a whole. */
	inDisabledSystem(path) {
		(this.disabledSystems ??= new Map()).set(path, (this.disabledSystems.get(path) ?? 0) + 1);
	}
	/** Recorded but harmless: carries no mass, so the numbers are unaffected. */
	note(type, name) { this.notes.push({ type, name }); }
	warn(message) { if (!this.warnings.includes(message)) this.warnings.push(message); }
	rename(from, to) { this.renamed.push({ from, to }); }

	finish(project) {
		this.counts = {
			index_lists: project.index_lists.length,
			compartments: project.compartments.length,
			transfers: project.transfers.length,
			parameters: project.parameters.length,
			expressions: project.expressions.length,
			inflows: project.inflows.length,
			lookups: (project.lookups ?? []).length,
			index_reductions: (project.index_reductions ?? []).length,
			block_reductions: (project.block_reductions ?? []).length,
			min_maxes: (project.min_maxes ?? []).length,
			running_means: (project.running_means ?? []).length,
			snapshots: (project.snapshots ?? []).length,
			delays: (project.delays ?? []).length,
			triggers: (project.triggers ?? []).length,
			nuclides: (project.nuclides ?? []).length,
		};
	}

	get ok() { return this.skipped.length === 0; }

	/** A short human summary, for the UI and the console. */
	summary() {
		const c = this.counts;
		const lines = [
			`Imported ${c.compartments} compartment(s), ${c.transfers} transfer(s), ` +
			`${c.parameters} parameter(s), ${c.expressions} expression(s), ` +
			(c.lookups ? `${c.lookups} lookup table(s), ` : '') +
			(c.index_reductions ? `${c.index_reductions} index operation(s), ` : '') +
			(c.block_reductions ? `${c.block_reductions} aggregate(s), ` : '') +
			`${c.index_lists} index list(s), ${c.nuclides} nuclide(s).`,
		];
		if (this.skipped.length) {
			const byType = new Map();
			for (const s of this.skipped) {
				byType.set(s.type, (byType.get(s.type) ?? 0) + 1);
			}
			lines.push(
				`Skipped ${this.skipped.length} block(s) this tool cannot represent: `
				+ [...byType].map(([t, n]) => `${n} ${t}`).join(', ') + '.',
			);
		}
		if (this.notes.length) {
			const byType = new Map();
			for (const n of this.notes) byType.set(n.type, (byType.get(n.type) ?? 0) + 1);
			lines.push(
				`Ignored ${[...byType].map(([t, n]) => `${n} ${t}`).join(', ')}: these carry `
				+ `no mass, so the results are unaffected.`,
			);
		}
		if (this.renamed.length) {
			lines.push(`Renamed ${this.renamed.length} block(s) to valid identifiers.`);
		}
		if (this.disabled.length) {
			lines.push(`${this.disabled.length} block(s) are disabled, as they were in `
				+ 'Ecolego, and take no part in the run.');
		}
		if (this.disabledSystems?.size) {
			lines.push([...this.disabledSystems].map(([p, n]) => `Sub-system '${p}' is switched `
				+ `off as a whole, as it was in Ecolego, with ${n} block${n === 1 ? '' : 's'} in it; `
				+ 'they keep their own switches and come back with it.').join(' '));
		}
		for (const w of this.warnings) lines.push(w);
		return lines.join('\n');
	}
}

/**
 * The names a block cannot have. Every function name, because the parser
 * resolves `min(` as a call before it looks for a block; and the three words
 * that pass the identifier test without being names -- see RESERVED in
 * ../domain/edit.js for what a block called `__proto__` did to the layout map.
 *
 * The same set is built in ../domain/edit.js (the editor's gate) and
 * ../domain/project.js (the loader's). It is built a third time here because
 * an import that lets `min` through produces a project the loader then refuses
 * with "reserved name" -- after reporting the import a success. Keep the three
 * in step.
 */
const RESERVED = new Set([
	...Object.keys(FUNCTIONS),
	...Object.keys(FUNCTION_ALIASES),
	'__proto__', 'constructor', 'prototype',
]);

/**
 * Ecolego names may contain spaces, dots and hyphens; this tool's equation
 * language cannot. Names are rewritten and the mapping recorded, so equations
 * can be rewritten to match and the user can see what changed.
 */
class NameMapper {
	constructor(report) {
		this.report = report;
		this.byKey = new Map();      // identity (block id) -> mapped local name
		this.byOriginal = new Map(); // first mapping for each original name
		this.used = new Map();       // sub-system -> the names taken in it
		this.ambiguous = new Set();
	}

	/**
	 * Maps one Ecolego name onto an identifier this tool can parse.
	 *
	 * Uniqueness is per sub-system, because that is where Ecolego's own names
	 * are unique: two blocks called `Water` in different sub-systems are two
	 * different blocks and both keep the name. Only a genuine clash inside one
	 * sub-system is numbered.
	 *
	 * The mapping is keyed by block id rather than by name, so the same name in
	 * two places maps independently.
	 *
	 * `fallback` is what to call a block whose name is missing or blank --
	 * its id, usually.
	 */
	map(original, key = original, system = '', fallback = 'block') {
		if (this.byKey.has(key)) return this.byKey.get(key);

		// Trimmed, and a blank name treated as no name. `name=""` used to
		// arrive here as the empty string -- the callers' `?? id` does not
		// catch it -- and was mapped to `block`, which recorded the pair
		// '' -> 'block' for `rewriteRenamedReferences`, where `indexOf('')`
		// matches at every position and the scan never moved on. The import
		// hung, on a file Ecolego writes for a block whose name was cleared.
		const given = String(original ?? '').trim();
		const absent = given === '';
		let clean = (absent ? String(fallback ?? '') : given)
			.replace(/[^A-Za-z0-9_]/g, '_')
			.replace(/^([0-9])/, '_$1');
		if (clean === '') clean = 'block';

		if (!this.used.has(system)) this.used.set(system, new Set());
		const taken = this.used.get(system);
		let candidate = clean;
		let n = 1;
		// A reserved word is taken before the file says anything, so `min`
		// is numbered like a clash: `min_1`. Left alone it imported cleanly
		// and the model then refused to load.
		while (taken.has(candidate) || RESERVED.has(candidate)) candidate = `${clean}_${n++}`;

		// A bare reference is rewritten by name, so a name that maps two ways
		// cannot be rewritten safely; remember which those are. A block with
		// no name has nothing an equation could have referred to it by.
		if (!absent) {
			const seen = this.byOriginal.get(given);
			if (seen === undefined) this.byOriginal.set(given, candidate);
			else if (seen !== candidate) this.ambiguous.add(given);
		}

		taken.add(candidate);
		this.byKey.set(key, candidate);
		if (candidate !== given) this.report.rename(absent ? '(unnamed)' : given, candidate);
		return candidate;
	}

	/** Original names that mapped to more than one identifier. */
	duplicated() { return [...this.ambiguous]; }
}

/**
 * The three words that pass every other test without being names: on a plain
 * object each is a key into `Object.prototype`, and this tool keys half-lives,
 * entry indices and the material catalogue by exactly these strings.
 */
const PROTOTYPE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/**
 * A nuclide's, material's, index's or decay pair's name, as the file gives it.
 *
 * These are not made into identifiers the way block names are: `Cs-137` is
 * what the decay data and the chains are keyed by, and an equation reaches a
 * nuclide through its index, never by spelling the name. So the name is taken
 * as written and trimmed, with two exceptions. A blank one is no name -- it is
 * left out, and said so, where it used to pass as a real index called `" "`.
 * And the three prototype keys are refused outright: a nuclide called
 * `__proto__` silently had no half-life, because `halfLives['__proto__'] =`
 * wrote to the prototype and `project.half_lives` never saw it. Ecolego never
 * writes any of these, so a file that carries one is not a model this tool
 * can read, and it says so rather than importing a hole.
 *
 * @returns the trimmed name, or null for a blank one
 */
function keyName(raw, what, report) {
	const name = String(raw ?? '').trim();
	const an = /^[aeiou]/i.test(what) ? 'An' : 'A';
	if (name === '') {
		report.warn(`${an} ${what} with no name was left out.`);
		return null;
	}
	if (PROTOTYPE_KEYS.has(name)) {
		throw new ImportError(
			`${an} ${what} in this file is called '${name}', which is not a name but a key `
			+ `into every object's prototype; this tool keys its tables by these names `
			+ `and cannot hold one. Ecolego never writes it -- rename the ${what} in `
			+ `Ecolego, or check that the file has not been tampered with.`,
		);
	}
	return name;
}

// --- sections ------------------------------------------------------------------

/**
 * `<hierarchy-model>` lists every sub-system, parents before children, the root
 * first and nameless.
 *
 * A sub-system is a namespace: a block inside one has the id
 * `Parent.Child.Block`, and that is the name the rest of this tool addresses it
 * by. A *group* (`type="group"`) is only a visual grouping -- Ecolego computes
 * the ids of its blocks against the enclosing namespace instead
 * so it contributes nothing to a path and is
 * flattened away here, which is what the ids in the file already say.
 *
 * @returns {{pathById: Map<string, string>, systems: string[]}}
 */
function readHierarchy(dataModel, project, names, report) {
	const model = child(dataModel, 'hierarchy-model');
	const pathById = new Map();
	const systems = [];
	// Sub-systems the file switches off. Ecolego's `enabled` sits on a
	// sub-system as on anything else, and the implicitly-enabled rule
	// is a block's own flag *and* its sub-system's -- so everything inside one
	// of these is off. Four of the real projects here do it, to keep a
	// screening version of a landscape beside the real one.
	const disabledPaths = [];
	// Sub-systems that are transports: a chain of N compartments drawn as
	// two. `type="transport"` is written on one.
	const transports = [];
	if (!model) return { pathById, systems, disabledPaths, transports };

	let groups = 0;
	for (const el of children(model, 'sub-system-block')) {
		const id = childText(el, 'id');
		const original = el.attrs.name;
		// The root carries neither, and is not a level of anything.
		if (!id || !original) continue;

		const parentId = childText(el, 'sub-system');
		const parentPath = parentId ? (pathById.get(parentId) ?? '') : '';
		const kind = el.attrs.type ?? '';

		if (kind === 'group') {
			groups++;
			pathById.set(id, parentPath);
			continue;
		}
		if (kind === 'external') {
			report.warn(
				`Sub-system '${original}' is an external sub-system; this tool reads it `
				+ 'as an ordinary one, so its linked library is not applied.',
			);
		}

		const local = names.map(original, `subsystem:${id}`, parentPath, 'subsystem');
		const path = parentPath ? `${parentPath}.${local}` : local;
		pathById.set(id, path);
		systems.push(path);
		if (kind === 'transport') transports.push(path);
		if (!childBool(el, 'enabled', true)) disabledPaths.push(path);
	}

	if (groups) {
		report.warn(
			`${groups} group${groups === 1 ? ' was' : 's were'} flattened: a group is a `
			+ `visual grouping in Ecolego and does not scope names, so its blocks belong `
			+ `to the sub-system around it.`,
		);
	}
	if (systems.length) project.systems = systems;
	if (transports.length) project.transports = transports;
	// Carried as what it is: a switch on the sub-system, which this tool now
	// has. The blocks inside keep their own switches untouched, as they do in
	// Ecolego, so turning the sub-system back on is one click here as there.
	if (disabledPaths.length) project.disabled_systems = disabledPaths;
	return { pathById, systems, disabledPaths, transports };
}

/**
 * What the file says about itself: who wrote it, when, and what they called it.
 *
 * `<project-properties>` carries the author and the comment as
 * `<property name="...">` elements rather than as elements of their own, which
 * is where `propertyText` looks -- read as `<comment>` they were never found,
 * so every imported model arrived with an empty description.
 *
 * The name is usually no help. Every file in the corpus says
 * `<project-properties name="model">`, which is Ecolego's default and is what
 * the exported HDF5 then called the model; the file's own name is the one
 * anybody uses for it. So that default is passed over when there is a file
 * name to use instead.
 *
 * @returns {{author: string|null, comment: string|null, modified: Date|null}}
 */
function readProjectProperties(dataModel, project, meta = {}) {
	const props = child(dataModel, 'project-properties');
	const fromFile = baseName(meta.fileName);
	if (!props) {
		project.name = fromFile ?? 'Imported project';
		return { author: null, comment: null, modified: null };
	}
	const declared = props.attrs.name
		?? childText(props, 'name')
		?? childText(props, 'full-name');
	project.name = (!declared || declared === 'model' ? fromFile : null)
		?? declared ?? 'Imported project';
	const stamp = Number(childText(props, 'modification-date'));
	return {
		author: propertyText(props, 'author') || null,
		comment: propertyText(props, 'comment') || childText(props, 'comment') || null,
		modified: Number.isFinite(stamp) && stamp > 0 ? new Date(stamp) : null,
	};
}

/** `…/model C -> model C. */
function baseName(path) {
	if (!path) return null;
	const last = String(path).split(/[/\\]/).pop();
	return last.replace(/\.(eco|eas|xml)$/i, '').trim() || null;
}

/**
 * What this model is, in four lines, written into its description.
 *
 * An imported model used to arrive with an empty description and a name of
 * `model`, and a safety assessment of fifteen thousand blocks is not a thing
 * anybody reconstructs by browsing it. Two different sorts of fact go in here
 * and neither survives the import otherwise:
 *
 *  - **where it came from** -- the file, the Ecolego that wrote it, the author
 *    and the date. This is the half that cannot be worked out again later.
 *  - **what it is** -- how many of each kind of block, in how many
 *    sub-systems, what it is indexed by, and what a run of it does. All of
 *    this *is* derivable, which is exactly why it belongs in a summary: it is
 *    the reading somebody would otherwise do by hand before they could say
 *    anything at all about the file.
 *
 * Plain text, because that is what the description field is: the sidebar shows
 * it in a textarea and the Information view as a paragraph, and a tag typed
 * into either would be shown as a tag. The HDF5 export turns it into HTML on
 * the way out (see ./resultfile.js).
 *
 * The author's own comment leads, when there is one worth keeping. Ecolego
 * writes `Created at <date>` into that field by default and every file in the
 * corpus still has exactly that, so it is read as the date it is rather than
 * repeated as a remark.
 */
function describeModel(project, { author, comment, modified, fileName, version } = {}) {
	const lines = [];
	const created = /^Created at\s+(.+)$/i.exec(String(comment ?? '').trim());
	if (comment && !created) lines.push(comment.trim());

	// Where it came from.
	const from = [];
	const file = String(fileName ?? '').split(/[/\\]/).pop();
	from.push(file ? `Imported from ${file}` : 'Imported from Ecolego');
	if (version) from.push(`written by Ecolego ${version}`);
	if (author) from.push(`by ${author}`);
	if (created) from.push(`created ${created[1].trim()}`);
	else if (modified) from.push(`last changed ${modified.toISOString().slice(0, 10)}`);
	lines.push(`${from.join(', ')}.`);

	// What is in it. Every kind that is there, counted, in the order the
	// panels list them; the sub-systems and the states after, because those
	// are what say how big a run of it will be.
	const counts = [];
	for (const collection of KINDS) {
		const n = (project[collection] ?? []).length;
		if (!n) continue;
		const label = (KIND_LABEL[SINGULAR[collection]] ?? collection).toLowerCase();
		counts.push(`${n} ${n === 1 ? singularise(label) : label}`);
	}
	if (counts.length) {
		const systems = (project.systems ?? []).length;
		const states = stateCount(project);
		lines.push(`Holds ${listOf(counts)}`
			+ (systems ? `, in ${systems} sub-system${systems === 1 ? '' : 's'}` : '')
			+ (states ? `; ${states} state${states === 1 ? '' : 's'} to integrate` : '')
			+ '.');
	}

	// What it is indexed by, which is the first question anybody asks of a
	// strange safety assessment. **The lists blocks actually carry**, most
	// used first: a real project declares a dimension for every collection it
	// has -- model C has sixteen, among them `Transfers (565)` and
	// `AdvectiveTransfers (336)` -- and naming all of them says less than
	// naming the four that anything is indexed by.
	const used = new Map();
	for (const collection of KINDS) {
		for (const block of project[collection] ?? []) {
			for (const dim of block?.index_lists ?? []) used.set(dim, (used.get(dim) ?? 0) + 1);
		}
	}
	const dims = [...used]
		.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
		.map(([name]) => {
			const list = (project.index_lists ?? []).find((l) => l.name === name);
			const n = (list?.indices ?? []).filter((i) => i.enabled !== false).length;
			return n ? `${name} (${n})` : name;
		});
	if (dims.length) {
		const MOST = 6;
		const shown = dims.slice(0, MOST);
		if (dims.length > MOST) shown.push(`${dims.length - MOST} more`);
		lines.push(`Indexed by ${listOf(shown)}.`);
	}

	// What a run of it does. The solver by its id rather than by its label:
	// `stiff, var. order (variableOrder)` is a phrase for a settings row, not for
	// the middle of a sentence.
	const sim = project.simulation ?? {};
	if (sim.end_time != null) {
		const unit = sim.time_unit ?? 'year';
		lines.push(`Runs ${fmtCount(sim.start_time ?? 0)} to ${fmtCount(sim.end_time)} `
			+ `${unit}s with ${sim.solver ?? DEFAULT_SOLVER}.`);
	}
	return lines.join('\n');
}

/** `compartments` -> `compartment`, for the one-of case. */
function singularise(label) {
	if (label.endsWith('ies')) return `${label.slice(0, -3)}y`;
	if (label.endsWith('es') && !label.endsWith('ses')) return label.slice(0, -2);
	return label.endsWith('s') ? label.slice(0, -1) : label;
}

/** `a, b and c`. */
function listOf(parts) {
	if (parts.length <= 1) return parts.join('');
	return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

/** A number short enough for a sentence: 1e5 rather than 100000. */
function fmtCount(v) {
	const n = Number(v);
	if (!Number.isFinite(n)) return String(v);
	if (n !== 0 && (Math.abs(n) >= 1e6 || Math.abs(n) < 1e-3)) {
		return Number(n.toPrecision(4)).toExponential().replace('e+', 'e');
	}
	return String(Number(n.toPrecision(6)));
}

/**
 * `<material-model>` holds `<nuclide name="..."><half-life>` in standard units,
 * which for time is seconds (the standard conversion converts *from* standard).
 */
function readMaterials(dataModel, project, report) {
	const model = child(dataModel, 'material-model');
	const byId = new Map();
	const byName = new Map();
	// Which of them are radionuclides, and what the others are measured in.
	// A file's contaminant catalogue holds both kinds -- a `<nuclide>` element
	// for a radionuclide and a `<material>` for anything else -- and that is
	// the fact decay is keyed off: an index decays if it is a nuclide.
	const nuclideNames = new Set();
	const units = new Map();
	if (!model) return { byId, byName, nuclideNames, units };

	// Prototype-free: keyed by what the file calls its nuclides. See keyName.
	const halfLives = Object.create(null);
	// What the inventories are in. Ecolego keeps this on the material model as
	// `decayUnit`, and keeps every nuclide's own unit in step with it -- which
	// is how the file carries it, since the model-level property is never
	// written. `Bq` when nothing says otherwise, which is the format's default.
	let decayUnit = null;
	for (const nuc of children(model, 'nuclide')) {
		const name = keyName(nuc.attrs.name, 'nuclide', report);
		if (!name) continue;
		const id = childText(nuc, 'id');
		const unit = normaliseDecayUnit(childText(nuc, 'unit'));
		if (unit) {
			if (decayUnit && decayUnit !== unit) {
				report.warn(
					`The nuclides disagree about their unit (${decayUnit} and ${unit}); `
					+ `the model is read as ${decayUnit}.`,
				);
			} else if (!decayUnit) {
				decayUnit = unit;
			}
		}
		const rawHalfLife = childText(nuc, 'half-life');
		const seconds = Number(rawHalfLife);
		if (Number.isFinite(seconds) && seconds > 0) {
			halfLives[name] = seconds / SECONDS_PER_YEAR;
		} else {
			// Stable isotopes are written with an infinite (or absent) half-life
			// and belong in the material list all the same. The word, not
			// Infinity: JSON has no infinity, so an imported model that was
			// saved and reopened came back with a null half-life and refused to
			// run. `Project` reads either spelling.
			halfLives[name] = STABLE;
			if (rawHalfLife && !/inf/i.test(rawHalfLife)) {
				report.warn(`'${name}' has no usable half-life; it is treated as stable.`);
			}
		}
		if (id) byId.set(id, name);
		byName.set(name, { id, name });
		nuclideNames.add(name);
	}

	// Plain materials are not radionuclides; they carry no decay, and they do
	// carry a unit of their own. A model's stable carbon is in kgC beside its
	// C-14 in Bq, its water in m^3, and Lotka-Volterra's two materials are
	// measured in rabbits and foxes. A radionuclide's unit is not read here:
	// Ecolego holds every nuclide's equal to the model's decay unit, which is
	// read above, and the oldest file here writes a *half-life* unit in that
	// field -- `<unit>d</unit>` on a Cs-134 whose inventory is Bq.
	for (const mat of children(model, 'material')) {
		const name = keyName(mat.attrs.name, 'material', report);
		if (!name) continue;
		const id = childText(mat, 'id');
		if (id) byId.set(id, name);
		byName.set(name, { id, name });
		const unit = (childText(mat, 'unit') ?? '').trim();
		if (unit) units.set(name, unit);
	}

	if (Object.keys(halfLives).length) project.half_lives = halfLives;
	// Written whichever it is, so a round trip through this editor cannot turn
	// an amount model into an activity one by saying nothing.
	project.decay_unit = decayUnit ?? 'Bq';
	return { byId, byName, nuclideNames, units };
}

/**
 * A nuclide's `<unit>` as one of the two an inventory can be held in.
 *
 * Only those two: a nuclide carrying something else is not saying anything
 * about the decay unit, and guessing from it would be worse than the default.
 */
function normaliseDecayUnit(raw) {
	const given = String(raw ?? '').trim();
	if (/^(mol|mole|moles)$/i.test(given)) return 'mol';
	if (/^(bq|becquerel|bequerel)$/i.test(given)) return 'Bq';
	return null;
}

function readIndexLists(dataModel, project, names, report, materials) {
	const model = child(dataModel, 'index-list-model');
	// Index ids are scoped to their list, not global: two lists may each hold
	// an index with id "H". the file format resolves an entry's ids against
	// the block's own index lists, so the maps here are kept per list.
	const listById = new Map();
	const indexById = new Map(); // only for resolving mapping pairs, see below
	if (!model) return { listById, indexById };

	const raw = [];
	for (const listEl of children(model, 'index-list')) {
		const rawName = listEl.attrs.name;
		const listId = childText(listEl, 'id');
		// The mapper treats a blank name as none and falls back to `IndexList`;
		// the original kept for the messages below is whichever it had.
		const name = names.map(rawName, `indexlist:${listId ?? rawName ?? ''}`, '', 'IndexList');
		const originalName = String(rawName ?? '').trim() || name;

		const indices = [];
		const ownIndexById = new Map();
		for (const idxEl of children(listEl, 'index')) {
			const idxName = keyName(idxEl.attrs.name, `index of '${originalName}'`, report);
			if (!idxName) continue;
			const idxId = childText(idxEl, 'id');
			const enabled = idxEl.attrs.enabled == null
				? true
				: idxEl.attrs.enabled.toLowerCase() === 'true';
			indices.push({ name: idxName, enabled });
			if (idxId) {
				ownIndexById.set(idxId, idxName);
				// A global view, used only where the file itself is ambiguous
				// (mapping pairs name ids without saying which list they mean).
				if (!indexById.has(idxId)) {
					indexById.set(idxId, { name: idxName, listName: name });
				}
			}
		}

		const entry = {
			name, indices, indexById: ownIndexById, _id: listId, _original: originalName,
			// Ecolego's scenario dimension, marked by a predefined type: the
			// list one index of which is live at a time, which every reduction
			// has to leave out of its dimension count the way
			// the scenario rule does, and which this tool runs one
			// index of.
			for_scenarios: predefinedType(listEl) === 'SCENARIOS',
			// The element dimension, which chemistry is a property of. Marked
			// so that this tool does not derive a second one beside it.
			for_elements: predefinedType(listEl) === 'ELEMENTS',
			_predefined: predefinedType(listEl),
		};

		const subSet = child(listEl, 'sub-set');
		if (subSet && subSet.attrs.of) entry._subSetOfId = subSet.attrs.of;

		const mapping = child(listEl, 'mapping');
		if (mapping && mapping.attrs.to) {
			entry._mappingToId = mapping.attrs.to;
			entry._mappingPairs = children(mapping, 'map')
				.map((m) => ({ fromId: m.attrs.from, toId: m.attrs.to }));
		}

		raw.push(entry);
		if (listId) listById.set(listId, entry);
	}

	// Resolve id references now that every list is known.
	for (const entry of raw) {
		if (entry._subSetOfId) {
			const root = listById.get(entry._subSetOfId);
			if (root) entry.sub_set_of = root.name;
			else report.warn(`Index list '${entry._original}' is a sub-set of a list that is not in the file.`);
		}
		if (entry._mappingToId) {
			const target = listById.get(entry._mappingToId);
			if (target) {
				// `from` names an index of this list, `to` one of the target's.
				entry.mapping = {
					to: target.name,
					pairs: entry._mappingPairs
						.map((p) => ({
							from: entry.indexById.get(p.fromId) ?? indexById.get(p.fromId)?.name,
							to: target.indexById.get(p.toId) ?? indexById.get(p.toId)?.name,
						}))
						.filter((p) => p.from && p.to),
				};
			} else {
				report.warn(`Index list '${entry._original}' maps to a list that is not in the file.`);
			}
		}
	}

	// The material dimensions. Ecolego builds three lists out of its material
	// model and marks each with a predefined type: `MATERIALS`, every material
	// the model knows; `RADIONUCLIDES`, a sub-set of it holding the ones that
	// have a half-life; and `ELEMENTS`, a grouping of it. All 87 readable
	// projects here carry all three -- the index-list model creates them in
	// its constructor and `materialAdded` keeps them in step -- so they are
	// read as what they are rather than guessed at.
	//
	// Guessing is still the fall-back, because the oldest files write no
	// `predefined-type` on any list at all: then the name, which is Ecolego's
	// own for them, and then the shape -- the radionuclides are a sub-set of
	// the materials and never the other way round.
	const known = new Set(materials.byName.keys());
	const candidates = raw.filter((e) => e.indices.length
		&& e.indices.every((i) => known.has(i.name)));
	const listNamed = (want) => raw.find((e) => e.name.trim().toLowerCase() === want);
	const usable = (e) => e && (!e.indices.length || candidates.includes(e));

	let catalogue = raw.find((e) => e._predefined === 'MATERIALS') ?? null;
	let nuclides = raw.find((e) => e._predefined === 'RADIONUCLIDES') ?? null;
	if (!catalogue && usable(listNamed('materials'))) catalogue = listNamed('materials');
	if (!nuclides && usable(listNamed('radionuclides'))) nuclides = listNamed('radionuclides');
	// The shape: a sub-set of the materials is the radionuclides, and the list
	// a radionuclide sub-set is taken from is the materials.
	if (!catalogue && nuclides?.sub_set_of) {
		catalogue = raw.find((e) => e.name === nuclides.sub_set_of) ?? null;
	}
	if (!catalogue) {
		catalogue = candidates.find((e) => !e.sub_set_of && !e.mapping)
			?? candidates.slice().sort((a, b) => b.indices.length - a.indices.length)[0]
			?? null;
	}
	if (!nuclides && catalogue) {
		nuclides = candidates.find((e) => e !== catalogue && e.sub_set_of === catalogue.name)
			?? null;
	}

	if (catalogue) {
		catalogue.for_contaminants = true;
		// A material that is not a radionuclide is measured in its own unit,
		// and that unit belongs to the material rather than to the block that
		// holds it -- `Compartment.getUnit(indices)` reads it off the material
		// at the index. A radionuclide's follows the model's decay unit and is
		// not written down. See ../domain/units.js.
		for (const i of catalogue.indices) {
			const unit = materials.units.get(i.name);
			if (unit) i.unit = unit;
		}
	}
	if (nuclides && nuclides !== catalogue) {
		nuclides.for_nuclides = true;
		if (!nuclides.sub_set_of && catalogue) nuclides.sub_set_of = catalogue.name;
		// A file may carry the list without its contents: two projects here
		// write `Radionuclides` empty while their material model holds ten
		// nuclides with half-lives, and Ecolego runs them all the same --
		// decay is keyed off the material, not off this list. `materialAdded`
		// would have put every one of them here, so that is what goes here.
		const have = new Set(nuclides.indices.map((i) => i.name));
		const added = [];
		for (const i of catalogue?.indices ?? []) {
			if (have.has(i.name) || !materials.nuclideNames.has(i.name)) continue;
			nuclides.indices.push({ name: i.name, enabled: i.enabled });
			added.push(i.name);
		}
		if (added.length && !have.size) {
			report.warn(
				`'${nuclides.name}' is empty in this file; its ${added.length} `
				+ `radionuclide${added.length === 1 ? '' : 's'} were read from the `
				+ `material model, which is what Ecolego decays them from.`,
			);
		}
	}
	const decaying = nuclides ?? catalogue;
	if (decaying) {
		project.nuclides = decaying.indices.filter((i) => i.enabled).map((i) => i.name);
	}

	// A file that says nothing about its lists at all -- the oldest Ecolego
	// here writes no `predefined-type` on any of them -- still names them.
	// `Scenarios` and `Elements` are what Ecolego calls its own, so a list of
	// that name is that list when nothing else claims to be: the alternative
	// is a scenario dimension read as an ordinary axis, which a reduction
	// would then count and the run would hold every index of at once.
	if (!raw.some((e) => e.for_scenarios)) {
		const found = listNamed('scenarios');
		if (found) found.for_scenarios = true;
	}
	if (!raw.some((e) => e.for_elements)) {
		const found = listNamed('elements');
		if (found && !found.for_contaminants && !found.for_nuclides) found.for_elements = true;
	}

	const scenarios = raw.filter((e) => e.for_scenarios);
	const named = scenarios.flatMap((e) => e.indices.filter((i) => i.enabled));
	if (named.length > 1) {
		report.warn(
			`This model has ${named.length} scenarios (${scenarios[0].name}). Ecolego `
			+ `runs one simulation per scenario; this tool runs one at a time -- pick `
			+ `which under Simulation, and every block indexed by that list is read at `
			+ `the one selected. It opened on '${named[0].name}'.`,
		);
	}

	project.index_lists = raw.map((e) => {
		const out = { name: e.name, indices: e.indices };
		if (e.for_contaminants) out.for_contaminants = true;
		if (e.for_nuclides) out.for_nuclides = true;
		if (e.for_scenarios) out.for_scenarios = true;
		if (e.for_elements) out.for_elements = true;
		if (e.sub_set_of) out.sub_set_of = e.sub_set_of;
		if (e.mapping) out.mapping = e.mapping;
		return out;
	});

	return { listById, indexById };
}

function readDecayChains(dataModel, project, report) {
	const model = child(dataModel, 'nuclide-decay-model');
	if (!model) return;
	const chains = [];
	for (const pair of children(model, 'decay-pair')) {
		const { rate } = pair.attrs;
		const parent = keyName(pair.attrs.parent, 'decay pair parent', report);
		const daughter = keyName(pair.attrs.daughter, 'decay pair daughter', report);
		if (!parent || !daughter) continue;
		const ratio = Number(rate);
		chains.push([parent, daughter, Number.isFinite(ratio) ? ratio : 1]);
	}
	if (chains.length) project.chains = chains;
}

function readBlocks(dataModel, project, names, indexIds, report, hierarchy = null) {
	const model = child(dataModel, 'block-model');
	if (!model) {
		report.warn('The file has no <block-model>; nothing to import.');
		return {
			blockNameById: new Map(),
			wiring: {
				links: [], operations: new Map(), exposed: new Set(), idByGuid: new Map(),
			},
		};
	}

	const elements = [...children(model, 'component'), ...children(model, 'connection')];

	// What the sub-system interfaces say, gathered as they are read and applied
	// once every block exists. See INTERFACE and `connectInterfaces`.
	const wiring = { links: [], operations: new Map(), exposed: new Set(), idByGuid: null };

	// Pass one: block id -> mapped name, so connections can resolve endpoints.
	// Boundary components are recorded separately: a transfer touching one gets
	// a null endpoint rather than a dangling reference.
	const blockNameById = new Map();
	// Which sub-system a block sits in. `<sub-system>` names its parent by id;
	// the hierarchy has already turned those ids into paths, but a file that
	// declares none still says where its blocks live, so an undeclared parent
	// is taken at its word rather than dropped.
	const pathById = hierarchy?.pathById ?? new Map();
	const declared = new Set(hierarchy?.systems ?? []);
	const systemOfElement = (el) => {
		const parentId = childText(el, 'sub-system');
		if (!parentId) return '';
		if (pathById.has(parentId)) return pathById.get(parentId);
		const path = parentId.split('.')
			.map((part, i, all) => names.map(part, `subsystem:${all.slice(0, i + 1).join('.')}`,
				all.slice(0, i).join('.'), 'subsystem'))
			.join('.');
		pathById.set(parentId, path);
		if (!declared.has(path)) {
			declared.add(path);
			(project.systems ??= []).push(path);
		}
		return path;
	};

	// What each block is indexed by, so that a transfer written over the
	// *intersection* of its two ends can be given the list that stands for it.
	// See `intersectionDims`.
	const dimIdsOf = (el) => (el.attrs['index-lists'] ?? '')
		.split(',')
		.map((s) => s.trim())
		.filter(Boolean);
	const dimListsOf = (el) => dimIdsOf(el)
		.map((listId) => indexIds.listById.get(listId))
		.filter(Boolean);
	const dimsById = new Map();

	const boundaryIds = new Set();
	const systemById = new Map();
	// Ecolego writes `<enabled>false</enabled>` on a block that is switched
	// off: still in the model, left out of the run. Kept by id here and put
	// on the blocks once they exist, since they are built by kind below.
	const disabledIds = new Set();
	// A sub-system interface names the blocks it exposes by GUID rather than by
	// id, so the two have to be held together. Every element, not only the
	// imported ones: a connection to a block this tool has no equivalent for is
	// worth saying so about rather than reporting as an unknown GUID.
	const idByGuid = new Map();
	for (const el of elements) {
		const id = childText(el, 'id');
		const type = el.attrs.type;
		if (!id) continue;
		const guid = childText(el, 'guid');
		if (guid) idByGuid.set(guid.trim(), id);
		if (!childBool(el, 'enabled', true)) disabledIds.add(id);
		if (BOUNDARY.has(type)) { boundaryIds.add(id); continue; }
		if (!SUPPORTED.has(type)) continue;
		dimsById.set(id, dimListsOf(el));
		const system = systemOfElement(el);
		systemById.set(id, system);
		// The map holds the qualified name, so a transfer's endpoints and an
		// equation's qualified references land on the right block. A block
		// with no name, or a blank one, is called by its id.
		const local = names.map(el.attrs.name, id, system, id);
		blockNameById.set(id, system ? `${system}.${local}` : local);
	}

	for (const el of elements) {
		const type = el.attrs.type;
		const original = el.attrs.name ?? '(unnamed)';

		if (BOUNDARY.has(type)) {
			// Folded into the transfers that attach to it; nothing is lost.
			continue;
		}
		if (INTERFACE.has(type)) {
			// Read for its wiring, then dropped. See INTERFACE. A disabled one
			// routes nothing: one assessment model switches off two connectors
			// into a simplified biosphere it no longer uses, and wiring them
			// would feed blocks the file says are not fed.
			if (disabledIds.has(childText(el, 'id'))) continue;
			if (type === 'connector') {
				for (const link of children(el, 'model-connection')) {
					const source = (link.attrs.source ?? '').trim();
					const target = (link.attrs.target ?? '').trim();
					if (source && target) wiring.links.push({ source, target, via: original });
				}
			} else {
				for (const obj of children(el, 'interface-object')) {
					const guid = (obj.attrs.guid ?? '').trim();
					if (!guid) continue;
					wiring.exposed.add(guid);
					const op = (obj.attrs.operation ?? '').trim().toUpperCase();
					if (op) wiring.operations.set(guid, op);
				}
			}
			continue;
		}
		if (NON_NUMERIC.has(type)) {
			report.note(type, original);
			continue;
		}
		if (!SUPPORTED.has(type)) {
			report.skip(type ?? 'unknown', original,
				'this tool has no equivalent block type');
			continue;
		}

		const id = childText(el, 'id');
		const system = systemById.get(id) ?? systemOfElement(el);
		const qualified = blockNameById.get(id)
			?? names.map(original, id ?? original, system);
		// Blocks carry their own local name and the sub-system holding them.
		const name = system && qualified.startsWith(`${system}.`)
			? qualified.slice(system.length + 1)
			: qualified;
		// Dimension list objects, in declared order, for resolving entry ids --
		// and, where the file names none but says there is one, the list that
		// stands for the intersection of a transfer's two ends.
		const dimLists = dimListsOf(el).length
			? dimListsOf(el)
			: intersectionDims(el, original, dimsById, report);
		const dims = dimLists.map((l) => l.name).filter(Boolean);
		// An .eco file states every block's dimension, so a block with no index
		// lists is scalar and says so. Left implicit, an empty `index_lists` is
		// dropped on the way out and the project falls back to "one value per
		// nuclide" -- which turns a scalar parameter into a nuclide-indexed one
		// and makes every equation that reads it from a non-nuclide block
		// unresolvable.
		const dimSpec = dims.length ? { index_lists: dims } : { per_nuclide: false };

		const unit = childText(el, 'unit') ?? '';
		const comment = childText(el, 'comment') ?? '';
		const entries = readEntries(el, dimLists, report, original);

		const isExpression = type === 'expression' || type === 'post-processing'
			|| type === 'constant' || type === 'transport-number';
		// A part of a transport, carried as the compartment or expression it
		// is with its part marked. TransportBegin extends Compartment and
		// TransportNumber extends Expression, so their entries are written as
		// a compartment's and an expression's are; the counter and the
		// operation have no equation of their own, and this tool writes
		// theirs when the model is built.
		const role = TRANSPORT_ROLE[type] ?? null;
		const rolePatch = role ? { transport: role } : {};
		// A part of a transport outside a transport sub-system is a part of
		// nothing: Ecolego only ever makes one inside a TransportSubSystem,
		// so a file that has one elsewhere is a file that has been edited by
		// hand, and the block means nothing this tool can run.
		if (role && !(hierarchy?.transports ?? []).includes(system)) {
			report.skip(type, original, 'it is a part of a transport, and is not inside one');
			continue;
		}

		if (type === 'compartment' || role === 'begin' || role === 'end') {
			readableTolerances(entries, original, report);
			project.compartments.push(trimEmpty({
				name, system, ...dimSpec, unit, comment, ...rolePatch,
				handle_decay: childBool(el, 'handle-decay', true),
				initial: pickDefault(entries, 'initial') ?? '0',
				abstol: pickDefault(entries, 'abstol'),
				dydt: pickDefault(entries, 'dydt'),
				non_negative: readNonNegative(entries, original, report),
				entries: keepIndexed(entries, ['initial', 'abstol', 'dydt']),
			}));
		} else if (role === 'counter') {
			project.expressions.push(trimEmpty({
				name, system, ...dimSpec, unit: '', comment, transport: 'counter', equation: '1',
			}));
		} else if (role === 'operation') {
			// `<operation>` is the name the format uses; how it is read follows
			// from how many arguments it declares -- none, a point, or a
			// range -- which is how the argument option
			// works it out too.
			const args = children(el, 'argument').length;
			project.expressions.push(trimEmpty({
				name, system, ...dimSpec, unit, comment, transport: 'operation',
				operation: childText(el, 'operation') ?? 'MEAN',
				argument: args >= 2 ? 'range' : args === 1 ? 'point' : 'all',
			}));
		} else if (isExpression) {
			if (type !== 'expression' && type !== 'transport-number') {
				report.warn(
					`'${original}' is a ${type} expression; this tool evaluates every `
					+ `expression at each step, which is equivalent unless it depended on `
					+ `the evaluation order.`,
				);
			}
			// An expression with `<argument>` elements is a function: it is
			// called with those values rather than read, and Ecolego's own
			// editor calls them arguments (`IArgumentable`, which Expression
			// implements). That is this tool's `functions` collection -- see
			// ../sim/functions.js -- and the one block type where the entries
			// cannot come across, since a call brings its own arguments and
			// nothing indexes by them.
			const argNames = children(el, 'argument')
				.map((a) => childText(a, 'argument-key') ?? childText(a, 'argument-name'))
				.filter(Boolean);
			if (argNames.length && !role) {
				const parameters = [];
				for (const a of argNames) parameters.push(safeParameter(a, parameters));
				const perIndex = keepIndexed(entries, ['equation']);
				if (perIndex.length) {
					report.warn(
						`'${original}' is a function of ${parameters.join(', ')} with `
						+ `${perIndex.length} equation(s) set per index. A function is `
						+ `worked out where it is called, at the caller's index, so only `
						+ `its default equation came across.`,
					);
				}
				project.functions.push(trimEmpty({
					name, system, unit, comment,
					parameters,
					equation: pickDefault(entries, 'equation') ?? '',
				}));
				continue;
			}
			project.expressions.push(trimEmpty({
				name, system, ...dimSpec, unit, comment, ...rolePatch,
				equation: pickDefault(entries, 'equation') ?? '0',
				entries: keepIndexed(entries, ['equation']),
			}));
		} else if (type === 'lookup-table') {
			// An <argument> makes the table a function of whatever the caller
			// passes -- `Table(x)` -- instead of a series read at the clock.
			// Ecolego's LookupTable.OptionArgument; there is at most one.
			const argEl = child(el, 'argument');
			const argument = argEl
				? (childText(argEl, 'argument-key') || childText(argEl, 'argument-name') || 'X')
				: null;
			const option = childText(el, 'lookup-option');
			const interpolation = interpolationFromEco(option);
			if (option && !interpolation) {
				report.warn(
					`'${original}' uses the interpolation rule '${option}', which this `
					+ `tool does not know; straight lines between the points were used.`,
				);
			}
			project.lookups.push(trimEmpty({
				name, system, ...dimSpec, unit, comment,
				interpolation: interpolation ?? 'linear',
				cyclic: childBool(el, 'lookup-cyclic', false),
				...(argument ? { argument } : {}),
				points: pickDefault(entries, 'points') ?? [],
				entries: keepIndexed(entries, ['points']),
			}));
			// `index-operation` and `aggregate` are Ecolego's own type names in
			// the file. They stay as the file spells them however this tool renames
			// the blocks it reads them into.
		} else if (type === 'index-operation' || type === 'aggregate') {
			// The target is the block's own equation: one id for an index
			// operation, ids joined with `+` for an aggregate.
			const spec = pickDefault(entries, 'equation') ?? '';
			const raw = childText(el, 'operation');
			const operation = operationFromEco(raw);
			if (raw && !operation) {
				report.warn(
					`'${original}' reduces with '${raw}', which this tool does not know; `
					+ `it was summed instead.`,
				);
			}
			const common = {
				name, system, ...dimSpec, unit, comment,
				operation: operation ?? 'sum',
			};
			if (type === 'index-operation') {
				// Only when it is actually there: Number(null) is 0, which
				// would look like a stated percentile of zero.
				const stated = propertyText(el, 'percentile');
				const pct = childNumber(el, 'percentile')
					?? (stated == null || stated === '' ? null : Number(stated));
				project.index_reductions.push(trimEmpty({
					...common,
					target: spec.trim() || null,
					...(Number.isFinite(pct) ? { percentile: pct } : {}),
					entries: keepIndexed(entries, ['equation'])
						.map((e) => ({ index: e.index, target: String(e.equation).trim() })),
				}));
			} else {
				project.block_reductions.push(trimEmpty({
					...common,
					targets: splitTargets(spec),
					entries: keepIndexed(entries, ['equation'])
						.map((e) => ({ index: e.index, targets: splitTargets(e.equation) })),
				}));
			}
		} else if (KIND_FROM_ECO[type]) {
			// The blocks that remember, and the events that drive them. Each
			// field is an equation like any other; an event field names a
			// discrete-event block, which is a reference like any other too.
			const kind = KIND_FROM_ECO[type];
			const keys = [...EQUATION_FIELDS[kind], ...EVENT_FIELDS[kind]];
			const common = { name, system, ...dimSpec, unit, comment };
			const pick = (key, fallback) => pickDefault(entries, key) ?? fallback;
			const perIndex = keepIndexed(entries, keys);
			if (kind === 'min_max') {
				const raw = childText(el, 'operation');
				const op = extremeFromEco(raw);
				if (raw && !op) {
					report.warn(
						`'${original}' records '${raw}', which this tool does not know; `
						+ `its maximum was recorded instead.`,
					);
				}
				project.min_maxes.push(trimEmpty({
					...common, operation: op ?? 'max',
					target: pick('target', '0'),
					reset_trigger: pick('reset_trigger', null),
					start_trigger: pick('start_trigger', null),
					stop_trigger: pick('stop_trigger', null),
					entries: perIndex,
				}));
			} else if (kind === 'running_mean') {
				project.running_means.push(trimEmpty({
					...common,
					target: pick('target', '0'),
					reset_trigger: pick('reset_trigger', null),
					start_trigger: pick('start_trigger', null),
					stop_trigger: pick('stop_trigger', null),
					entries: perIndex,
				}));
			} else if (kind === 'snapshot') {
				project.snapshots.push(trimEmpty({
					...common,
					target: pick('target', '0'),
					trigger: pick('trigger', null),
					initial: pick('initial', '0'),
					entries: perIndex,
				}));
			} else if (kind === 'delay') {
				project.delays.push(trimEmpty({
					...common,
					target: pick('target', '0'),
					delay: pick('delay', '0'),
					entries: perIndex,
				}));
			} else {
				project.triggers.push(trimEmpty({
					...common,
					first: pick('first', '0'),
					second: pick('second', '0'),
					direction: pick('direction', 'rising'),
					entries: perIndex,
				}));
			}
		} else if (type === 'parameter') {
			// Only what could not be read is worth saying. A distribution that
			// arrived intact is on the parameter, shown in the panel and drawn
			// in the editor -- it is not a loss and does not belong in a list of
			// them. A run is still deterministic and still uses the value beside
			// it; that is said once, in the summary, rather than per parameter.
			const unread = entries.filter((e) => e.pdfUnread).length;
			if (unread) {
				report.warn(
					`'${original}' has ${unread === 1 ? 'a probability distribution' : `${unread} probability distributions`} `
					+ `this tool could not read; the constant value is used for `
					+ `${unread === 1 ? 'it' : 'them'}.`,
				);
			}
			project.parameters.push(trimEmpty({
				name, system, ...dimSpec, unit, comment,
				value: pickDefault(entries, 'value') ?? 0,
				pdf: pickDefault(entries, 'pdf') ?? undefined,
				entries: keepIndexed(entries, ['value', 'pdf']),
			}));
		} else if (type === 'transfer' || type === 'transfer-coefficient') {
			const resolveEnd = (idAttr, which) => {
				if (!idAttr) return { name: null, ok: true };
				if (boundaryIds.has(idAttr)) return { name: null, ok: true };
				const n = blockNameById.get(idAttr);
				if (!n) {
					report.warn(
						`Transfer '${original}' ${which} a block that was not imported; `
						+ `that end was left open.`,
					);
					return { name: null, ok: false };
				}
				return { name: n, ok: true };
			};
			const from = resolveEnd(el.attrs.source, 'starts at');
			const to = resolveEnd(el.attrs.target, 'ends at');

			if (from.name == null && to.name == null) {
				report.skip(type, original, 'neither endpoint is a compartment in this model');
				continue;
			}

			// Per the file format; an explicit entry value still wins.
			const donorDefault = DONOR_DEFAULT[type] ?? false;
			const donor = pickDefault(entries, 'multiply_by_donor') ?? donorDefault;

			project.transfers.push(trimEmpty({
				name, system, ...dimSpec, unit, comment,
				from: from.name, to: to.name,
				rate: pickDefault(entries, 'rate') ?? '0',
				// A transfer with no donor cannot be multiplied by one.
				multiply_by_donor: from.name == null ? false : donor,
				entries: keepIndexed(entries, ['rate', 'multiply_by_donor']),
			}));
		}
	}

	// The blocks the file switches off, now that they exist. By qualified
	// name, since that is what the first pass mapped each id to. A block
	// inside a sub-system the file switches off is left as the file has it:
	// the sub-system's switch is carried as its own (`disabled_systems`, set
	// in `readHierarchy`), which is what the implicitly-enabled rule
	// -- a block's own flag *and* its sub-system's -- reads too. The report
	// counts what each switched-off sub-system holds, so the summary can say
	// how much of the model that is.
	const offNames = new Set([...disabledIds].map((id) => blockNameById.get(id)).filter(Boolean));
	const offPaths = hierarchy?.disabledPaths ?? [];
	const inOffSystem = (system) => offPaths.find((p) => system === p || system.startsWith(`${p}.`));
	if (offNames.size || offPaths.length) {
		for (const collection of [
			'compartments', 'expressions', 'transfers', 'parameters', 'inflows',
			'lookups', 'index_reductions', 'block_reductions',
			'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
		]) {
			for (const block of project[collection] ?? []) {
				const qname = block.system ? `${block.system}.${block.name}` : block.name;
				const viaSystem = block.system ? inOffSystem(block.system) : null;
				if (viaSystem) report.inDisabledSystem(viaSystem);
				if (!offNames.has(qname)) continue;
				block.enabled = false;
				report.disable(qname);
			}
		}
	}

	wiring.idByGuid = idByGuid;
	return { blockNameById, wiring };
}

/**
 * The list a transfer written over the intersection of its two ends stands on.
 *
 * Ecolego has a fourth kind of index list that this tool does not:
 * `IntersectionIndexList`, whose own comment says what it is for -- *"a special
 * type of IndexList used by Transfers. When the Transfer is connecting two
 * Compartments, and these Compartments have different sets of indices, this
 * index list will make sure to contain only indices that are present in both
 * sets of indices."* It is built with `super("")`, so it has no name and no
 * id, and `createIds` writes it out as nothing at all: the file says
 * `dimension="1" index-lists=""`.
 *
 * Read as written that is a scalar, and a scalar transfer between two
 * compartments of 49 indices is a model that will not build -- *"'A' is
 * indexed by 'Materials', which 'flow' is not indexed by and cannot reach"*.
 * That is what 94 transfers in three of the projects here looked like.
 *
 * The intersection is by index *name*, so when one end's dimension is a
 * sub-set of the other's it **is** the intersection: every name in the sub-set
 * is in its root, and no other name is in both. Every one of those 94 is that
 * shape -- one end on `Materials` and the other on `Radionuclides`, either way
 * round -- and takes the sub-set.
 *
 * Two lists that merely overlap have an intersection no list of the model
 * names, and this tool has nowhere to put it. That is said rather than
 * guessed at, and the transfer is left as the file's own words make it.
 */
function intersectionDims(el, original, dimsById, report) {
	const width = Number(el.attrs.dimension ?? 0);
	if (!Number.isFinite(width) || width < 1) return [];
	const from = dimsById.get(el.attrs.source) ?? [];
	const to = dimsById.get(el.attrs.target) ?? [];
	// One end outside the model -- a flux across the boundary -- has nothing
	// to intersect with, so the dimensions are the end that is here.
	if (!from.length || !to.length) {
		const only = from.length ? from : to;
		return only.length === width ? only : [];
	}

	const picks = [];
	for (const a of from) {
		for (const b of to) {
			const narrower = a.name === b.name ? a
				: a.sub_set_of === b.name ? a
					: b.sub_set_of === a.name ? b
						: null;
			if (narrower && !picks.includes(narrower)) picks.push(narrower);
		}
	}
	if (picks.length === width) return picks;

	report.warn(
		`'${original}' is written over the indices its two ends have in common `
		+ `(${from.map((l) => l.name).join(' × ') || 'none'} and `
		+ `${to.map((l) => l.name).join(' × ') || 'none'}), which is a list `
		+ `Ecolego works out and does not write down. Neither end's dimension is `
		+ `a sub-set of the other's, so there is no list here that holds exactly `
		+ `those indices: '${original}' was read as the file spells it, and will `
		+ `need a dimension chosen by hand.`,
	);
	return [];
}

/**
 * Reads `<entry>` elements into a neutral shape:
 *   { index: { listName: indexName }, initial, rate, value, equation, ... }
 */
function readEntries(el, dimLists, report, blockLabel) {
	const out = [];
	for (const entryEl of children(el, 'entry')) {
		// Prototype-free: keyed by list name, which comes out of the file.
		const index = Object.create(null);
		const ids = (entryEl.attrs.index ?? '')
			.split(',').map((s) => s.trim()).filter(Boolean);

		ids.forEach((idxId, position) => {
			// BlockModelXMLPersistence.sort() writes the ids in the order the
			// block declares its index lists, so position i belongs to
			// dimension i. Fall back to a search when that does not hold.
			const positional = dimLists[position];
			if (positional?.indexById.has(idxId)) {
				index[positional.name] = positional.indexById.get(idxId);
				return;
			}
			const owner = dimLists.find((l) => l.indexById.has(idxId));
			if (owner) {
				index[owner.name] = owner.indexById.get(idxId);
				return;
			}
			report.warn(
				`An entry of '${blockLabel}' is keyed by an index ('${idxId}') that none `
				+ `of its index lists contains; that entry was dropped.`,
			);
		});

		const rec = { index };
		const type = entryEl.attrs.type;

		if (type === 'compartment') {
			assignIf(rec, 'initial', childText(entryEl, 'initial-condition'));
			assignNumberIf(rec, 'lower', childText(entryEl, 'lower-saturation'));
			assignNumberIf(rec, 'upper', childText(entryEl, 'upper-saturation'));
			// `<abs-tol>`: this compartment's own absolute error tolerance, at
			// this index, or nothing to use the simulation's. Written on every
			// entry the format saves and empty in all 9,695 of
			// them across the 87 real projects here -- but it is one number
			// and it changes what the solver does, so it comes across.
			assignNumberIf(rec, 'abstol', childText(entryEl, 'abs-tol'));
			// `<differential-equation>`: the extra term in the
			// compartment's rate of change. Set in 3 entries of 2 of the 242
			// real files here -- a predator-prey pair and a carbon balance --
			// and absent from every other entry Ecolego writes.
			assignIf(rec, 'dydt', childText(entryEl, 'differential-equation'));
		} else if (type === 'transfer') {
			assignIf(rec, 'rate', childText(entryEl, 'transfer-equation'));
			const mult = childText(entryEl, 'multiply-with-donor');
			if (mult != null && mult !== '') rec.multiply_by_donor = mult.toLowerCase() === 'true';
			if (childText(entryEl, 'transfer-event')) {
				report.warn(
					`'${blockLabel}' has a transfer event (a discrete transfer), which `
					+ `this tool does not support.`,
				);
			}
		} else if (type === 'expression') {
			assignIf(rec, 'equation', childText(entryEl, 'equation'));
		} else if (type === 'parameter') {
			assignNumberIf(rec, 'value', childText(entryEl, 'value'));
			// The distribution, kept rather than counted. `function=` names the
			// class and the expression names only the family, so both go to the
			// parser: three parameterisations of the log-normal spell
			// themselves `logn(...)` and are told apart by the attribute. See
			// ../domain/pdf.js.
			const pdfEl = child(entryEl, 'pdf');
			if (pdfEl) {
				const spec = parsePDF(
					childText(pdfEl, 'pdf-value') ?? '',
					pdfEl.attrs?.function ?? '',
				);
				if (spec) rec.pdf = spec;
				else rec.pdfUnread = childText(pdfEl, 'pdf-value') ?? '';
			}
		} else if (type === 'min-max' || type === 'running-mean') {
			// What to watch, and the events that reset it or start and stop
			// the recording.
			assignIf(rec, 'target', childText(entryEl, 'target-expression'));
			assignIf(rec, 'reset_trigger', childText(entryEl, 'reset-event'));
			assignIf(rec, 'start_trigger', childText(entryEl, 'start-recording-event'));
			assignIf(rec, 'stop_trigger', childText(entryEl, 'stop-recording-event'));
		} else if (type === 'snapshot') {
			assignIf(rec, 'target', childText(entryEl, 'snapshot-target'));
			assignIf(rec, 'trigger', childText(entryEl, 'snapshot-event'));
			assignIf(rec, 'initial', childText(entryEl, 'snapshot-initial-value'));
		} else if (type === 'delay') {
			assignIf(rec, 'target', childText(entryEl, 'delay-target'));
			assignIf(rec, 'delay', childText(entryEl, 'delay-time'));
		} else if (type === 'discrete-event') {
			assignIf(rec, 'first', childText(entryEl, 'first-expression'));
			assignIf(rec, 'second', childText(entryEl, 'second-expression'));
			const dir = directionFromEco(childText(entryEl, 'direction'));
			if (dir) rec.direction = dir;
		} else if (type === 'lookup-table') {
			const xs = numberList(childText(entryEl, 'lookup-table-time-points'));
			const ys = numberList(childText(entryEl, 'lookup-table-values'));
			// LookupTableEntry.setValues walks the shorter of the two, so a
			// truncated file loses the tail rather than the whole table.
			const n = Math.min(xs.length, ys.length);
			if (n < xs.length || n < ys.length) {
				report.warn(
					`'${blockLabel}' has ${xs.length} time point(s) but ${ys.length} `
					+ `value(s); the extra ones were dropped.`,
				);
			}
			const points = [];
			for (let i = 0; i < n; i++) points.push([xs[i], ys[i]]);
			if (points.length) rec.points = points;
			if (child(entryEl, 'link')) {
				report.warn(
					`'${blockLabel}' takes its table from a linked result, which this `
					+ `tool cannot follow; the stored points were used.`,
				);
			}
		}

		const entryUnit = childText(entryEl, 'entry-unit');
		if (entryUnit) rec.unit = entryUnit;

		// An entry whose key could not be fully resolved would silently apply
		// to the wrong cells, so drop it rather than guess.
		if (Object.keys(index).length !== ids.length) continue;

		out.push(rec);
	}
	return out;
}

/** An aggregate's targets, as the format joins them. */
function splitTargets(text) {
	return String(text ?? '').split('+').map((t) => t.trim()).filter(Boolean);
}

/** The text of a `<property name="...">`, which is where the odd one hides. */
/**
 * The `PredefinedType` an index list declares, upper-cased.
 *
 * Two spellings are in the wild, and the case is the difference: one small vault model
 * writes `SCENARIOS`, `MATERIALS`, `RADIONUCLIDES`, `ELEMENTS`, while
 * an older file -- written by an older Ecolego -- writes `Scenarios`, `Materials`,
 * `Radionuclides`, `Elements`. Compared as written, the second kind lost both
 * the scenario dimension and the element one: the marker was right there in
 * the file, spelled the other way. (The material dimension survived because it
 * has two fallbacks behind the marker; these had none.)
 */
function predefinedType(el) {
	const text = propertyText(el, 'predefined-type');
	return text ? text.trim().toUpperCase() : null;
}

function propertyText(el, name) {
	for (const p of children(el, 'property')) {
		if (p.attrs.name === name) return (p.text ?? '').trim();
	}
	return null;
}

/**
 * An array as the format writes it: `[1.0, 2.5, 3.0]`, and `[]` for
 * an empty one. Anything that is not a number is dropped, which loses a point
 * rather than turning the whole table into NaN.
 */
function numberList(text) {
	if (text == null) return [];
	const inner = String(text).trim().replace(/^\[/, '').replace(/\]$/, '');
	if (!inner.trim()) return [];
	const out = [];
	for (const part of inner.split(',')) {
		const n = Number(part.trim());
		if (Number.isFinite(n)) out.push(n);
	}
	return out;
}

function assignIf(rec, key, value) {
	if (value != null && value !== '') rec[key] = value;
}

function assignNumberIf(rec, key, value) {
	if (value == null || value === '') return;
	const n = Number(value);
	if (Number.isFinite(n)) rec[key] = n;
	else if (value.toLowerCase() === 'infinity') rec[key] = Infinity;
}

/** The value of an entry with no index -- Ecolego's default entry. */
/**
 * Drops a tolerance this tool cannot carry, rather than letting it fail a load.
 *
 * `Infinity` is a value Ecolego's own editor offers -- it is the prototype for
 * the abs-tol column -- and it means "do not error-control this state at all".
 * There are two reasons not to keep it: a project file is JSON, where
 * `Infinity` serialises as `null`, so it would not survive one save; and none
 * of the solvers here has a way to switch a single state out of the error test.
 * A negative or zero one is not a tolerance at all.
 *
 * Said rather than silently ignored, because a dropped tolerance is a solver
 * doing different work from the one the file describes.
 */
function readableTolerances(entries, blockLabel, report) {
	let dropped = 0;
	for (const e of entries) {
		if (!Object.prototype.hasOwnProperty.call(e, 'abstol')) continue;
		if (Number.isFinite(e.abstol) && e.abstol > 0) continue;
		delete e.abstol;
		dropped++;
	}
	if (dropped) {
		report.warn(
			`'${blockLabel}' sets an absolute tolerance this tool cannot carry `
			+ `(${dropped} of them -- infinite, zero or negative). The `
			+ `simulation's own absolute tolerance applies to those states.`,
		);
	}
}

/**
 * Ecolego's saturation band, read as the one constraint this tool keeps.
 *
 * A Compartment there carries `lower-saturation` and `upper-saturation`. In
 * practice the lower one is 0 and the upper one is empty, which says exactly
 * what the "cannot go negative" constraint here says and is what every solver
 * implements -- so that case maps across with nothing lost and nothing to report.
 *
 * A *negative* lower bound is the file saying this compartment may go below
 * zero, which maps just as cleanly, the other way.
 *
 * Anything else -- a positive floor, or a finite ceiling -- is a band this
 * tool has no equivalent for. It is dropped, and said so, once per block:
 * an import that quietly relaxed a cap would produce a model that runs and is
 * not the one in the file.
 */
function readNonNegative(entries, blockLabel, report) {
	let bounded = false;
	let negativeFloor = false;
	for (const e of entries) {
		const lo = e.lower;
		const hi = e.upper;
		if (lo != null && Number.isFinite(Number(lo))) {
			if (Number(lo) < 0) negativeFloor = true;
			else if (Number(lo) > 0) bounded = true;
		}
		if (hi != null && Number.isFinite(Number(hi))) bounded = true;
	}
	if (bounded) {
		report.warn(
			`'${blockLabel}' has a saturation band. This tool keeps only the `
			+ `"cannot go negative" part of it, so the `
			+ `floor and ceiling were dropped -- express a cap as a rate term `
			+ `instead, or the model will not be the one in the file.`,
		);
	}
	return !negativeFloor;
}

function pickDefault(entries, key) {
	const def = entries.find(
		(e) => Object.keys(e.index).length === 0
			&& Object.prototype.hasOwnProperty.call(e, key),
	);
	return def ? def[key] : undefined;
}

/** Entries that actually carry an index, with only the keys we understand. */
function keepIndexed(entries, keys) {
	const out = [];
	for (const e of entries) {
		if (Object.keys(e.index).length === 0) continue;
		const rec = { index: e.index };
		let any = false;
		for (const k of keys) {
			if (Object.prototype.hasOwnProperty.call(e, k)) { rec[k] = e[k]; any = true; }
		}
		if (any) out.push(rec);
	}
	return out;
}

function trimEmpty(obj) {
	const out = {};
	for (const [k, v] of Object.entries(obj)) {
		if (v === '' || v == null) continue;
		if (Array.isArray(v) && v.length === 0) continue;
		out[k] = v;
	}
	return out;
}

/**
 * Maps the solver an imported file names onto one this tool has.
 *
 * The keys are the words that appear in the file; the values are this tool's
 * own ids. Three of them are the same method under another name, and the rest
 * are the nearest thing available -- which is worth telling the reader about,
 * so `SOLVER_EXACT` separates the two cases.
 */
const SOLVER_MAP = lookup({
	ODE45: 'dp45', ODE23: 'dp45', ODE113: 'dp45', ODE853: 'dp45',
	ODE15S: 'ndf',
	ODE23S: 'ros23', ODE23T: 'ros23', ODE23TB: 'ros23',
	RADAU5: 'ndf', KRYLOV: 'ndf', PADE: 'ndf', TAYLOR: 'ndf',
});

/**
 * The names above that arrive at the same method rather than at a substitute.
 *
 * The numerical differentiation formulas, the Rosenbrock (2,3) pair and
 * Dormand-Prince (4,5) are all here, so a file asking for one of those gets
 * what it asked for and needs no warning. Everything else in the map is the
 * closest available method, which does need one.
 */
const SOLVER_EXACT = new Set(['ODE15S', 'ODE23S', 'ODE45']);

/**
 * Ecolego's "not set": a “not set” sentinel, one magic double written
 * into a file wherever a number was left alone. 86 of the 87 readable
 * projects here carry it -- as a step size, as a Newton threshold, and, the
 * reason it has to be recognised, as a time series' own first and last time,
 * where 28 of 145 series say it. Read as a number it is a time 800 billion
 * years before the run, which silences the series that says it.
 *
 * It is compared exactly, so an exact comparison is the
 * faithful one: `-7.92842341234234E11`, the shortest round-tripping form the
 * persister writes, parses back to this very double.
 */
const D_AUTO = -792842341234.23404823434;

/**
 * One number from the file, with Ecolego's "not set" read as absent.
 *
 * A tolerance as well as the equality, because a value rounded by hand or by
 * another writer is still the sentinel and cannot be anything else: no model
 * has a real time within a millionth of -7.9e11.
 */
function autoNumber(el, tag) {
	const v = childNumber(el, tag);
	if (v == null || !Number.isFinite(v)) return null;
	return Math.abs(v - D_AUTO) <= Math.abs(D_AUTO) * 1e-9 ? null : v;
}

/**
 * When Ecolego saves results, and on what times.
 *
 * Three modes, from `<output-options>`, which `JavaSimulatorNextGeneration`
 * turns into an `EOutputMode`:
 *
 *   Produce no additional output    the solver's accepted steps -- Ecolego's
 *                                   *default*, and this tool's `solver`
 *   Produce additional output       those and the specified times: `both`
 *   Produce specified output only   the time series alone: `series`
 *
 * Older files write the index into the setting's allowed values rather than
 * the words, which is why `0`, `1` and `2` are read as well. Batch mode
 * overrides all of it -- the format forces `Specified` there -- and so does this.
 *
 * The times themselves are a `<time-series-list>` of geometric, linear,
 * increment and custom series, plus a `<discrete-times>` list of the same
 * shape; both become series of this tool's own, which are the same three
 * generators. 24 of the 87 readable projects here carry one, four of them with
 * five series each, and this tool used to throw all of that away and report on
 * 250 logarithmic points instead.
 */
function readOutputTimes(s, sim, report) {
	const MODES = lookup({
		'produce no additional output': 'solver',
		'produce additional output': 'both',
		'produce specified output only': 'series',
		0: 'solver',
		1: 'both',
		2: 'series',
	});
	const written = (childText(s, 'output-options') ?? '').trim();
	const mode = MODES[written.toLowerCase()] ?? MODES[Number(written)] ?? null;

	const series = [
		...readTimeSeries(child(s, 'time-series-list'), sim, report),
		...readTimeSeries(child(s, 'discrete-times'), sim, report),
	];
	if (series.length) sim.output_times = series;

	// Batch mode reports on the specified times whatever the option says:
	// `getOutputMode` tests it first.
	const batch = (childText(s, 'batch-mode') ?? '').trim().toLowerCase() === 'true';
	const wanted = batch ? 'series' : mode;
	if (!wanted) return;

	if (wanted === 'solver') {
		sim.spacing = 'solver';
		return;
	}
	// The specified times are asked for and there are none: the file says
	// "these times" and lists nothing, so there is nothing to switch to.
	if (!series.length) {
		report.warn(
			`The file asks for output on specified times but lists none; `
			+ `${sim.output_points} logarithmic points were used instead.`,
		);
		return;
	}
	sim.spacing = wanted;
}

/** The `<time-series>` children of one list, as this tool's own series. */
function readTimeSeries(host, sim, report) {
	if (!host) return [];
	const out = [];
	for (const el of children(host, 'time-series')) {
		const type = (el.attrs.type ?? '').toLowerCase();
		if (type === 'custom') {
			// `[1000.0, 2000.0, 3000.0]` -- the format's list syntax, and `[]` for
			// an empty one, which every model of one assessment series has as its
			// `<discrete-times>`.
			//
			// The empty tokens are dropped **before** they are read as
			// numbers, because `Number('')` is 0 and `Number.isFinite(0)` is
			// true: splitting `[]` gives one empty string, which became the
			// single time zero. Every one of those eleven models arrived with
			// a second output series holding a time before its own start --
			// harmless, since the run never reaches it, and reported as a
			// warning on every one of them until the warning was what found
			// this.
			const times = (childText(el, 'values') ?? '')
				.replace(/[[\]]/g, '')
				.split(/[\s,;]+/)
				.filter((v) => v !== '')
				.map((v) => Number(v))
				.filter((v) => Number.isFinite(v));
			if (times.length) out.push({ kind: 'times', times: times.sort((a, b) => a - b) });
			continue;
		}
		// Either end may be Ecolego's AUTO, which means "follow the
		// simulation": `LinearTimeSeries.generateValues` and its two siblings
		// all begin by replacing D_AUTO with the simulation's own start and
		// end. Kept as null here, which is what this tool's own generators
		// read as the same thing -- and a promise that survives the run's
		// span being edited afterwards.
		const from = autoNumber(el, 'time-series-start-time');
		const to = autoNumber(el, 'time-series-end-time');
		const kind = type === 'geometric' ? 'log' : 'linear';
		let points = childNumber(el, 'n');
		if (points == null) {
			// An incrementing series says how far apart its points are rather
			// than how many there are; the two are the same series said two
			// ways, and this tool's editor is written in points.
			const step = childNumber(el, 'increment');
			// A count needs two ends, so AUTO is resolved against the run --
			// which the reader has already read, a few lines above the call.
			const a = from ?? sim.start_time;
			const b = to ?? sim.end_time;
			if (step != null && step > 0 && b > a) {
				points = Math.floor((b - a) / step) + 1;
				if (Math.abs((b - a) / step - Math.round((b - a) / step)) > 1e-9) {
					report.warn(
						`An output series steps by ${step} from ${a} to ${b}, which `
						+ `does not divide evenly; ${points} points were used.`,
					);
				}
			}
		}
		if (points == null || !(points >= 2)) {
			report.warn('An output series had no usable number of points and was dropped.');
			continue;
		}
		out.push({ kind, points: Math.round(points), from, to });
	}
	return out;
}

function readSimulationSettings(dataModel, project, report) {
	const s = child(dataModel, 'simulation-settings');
	// A file that carries no settings has no opinion, so it takes this tool's
	// own defaults rather than a second copy of them kept here.
	//
	// Those defaults are also what the corpus says: of the 147 readable
	// projects on this machine, 84 state `rel-error-tolerance` 0.001 and
	// `abs-error-tolerance` 1.0E-6 exactly, and most of the rest state the
	// same relative tolerance with something else beside it. Seven carry the
	// "not set" sentinel for both, and those are the files this line is for --
	// giving them what every one of their siblings asks for out loud.
	const sim = { ...DEFAULT_SIMULATION };
	if (!s) {
		project.simulation = sim;
		report.warn('No simulation settings in the file; defaults were used.');
		return;
	}

	const start = childNumber(s, 'start-time');
	const end = childNumber(s, 'end-time');
	if (start != null) sim.start_time = start;
	if (end != null) sim.end_time = end;
	if (!(sim.end_time > sim.start_time)) {
		sim.start_time = 0;
		sim.end_time = Math.max(1, end ?? 1e5);
		report.warn('The stored time span was not usable; it was reset.');
	}

	// `saturation-enabled` is Ecolego's master switch over every compartment's
	// bounds, and `JavaSimulator.createNonNegative` reads it before it looks at
	// a compartment at all: off, the solver is handed nothing and no state is
	// held. This tool carries only the floor of that -- see *The saturation
	// band is not carried at all* -- so the switch maps onto the floor, which
	// is the part of it there is.
	//
	// Said out loud when it is off, because it is the one import that turns a
	// constraint off for a whole model: eleven of the twelve real assessments
	// here set it true and one sets it false, so Ecolego
	// runs that model with no floor while this tool, before this, clamped it.
	const saturation = childText(s, 'saturation-enabled');
	if (saturation != null && /^\s*false\s*$/i.test(saturation)) {
		sim.non_negative = false;
		report.warn(
			'Saturation is switched off in this model, so no compartment is held at '
			+ 'zero -- which is how Ecolego runs it. Each compartment keeps its own '
			+ '*cannot go negative* setting; none of them is consulted while the '
			+ 'switch is off. Turn it back on under Simulation if you want the floor.',
		);
	}

	// What a probabilistic run would do. Ecolego keeps these in their own
	// `<probabilistic-settings>` beside the simulation's; all three corpus
	// models that have them say 1000 realisations by Latin hypercube.
	//
	// Read and kept, and they do not make Run probabilistic: a file saying
	// 1000 must not turn one press into a thousand integrations of a
	// twenty-thousand-state model. They are the defaults the probabilistic
	// dialog opens with.
	const prob = child(dataModel, 'probabilistic-settings');
	if (prob) {
		const n = Number(childText(prob, 'no-simulations'));
		if (Number.isFinite(n) && n > 0) sim.iterations = Math.round(n);
		const seed = Number(childText(prob, 'seed'));
		if (Number.isFinite(seed)) sim.seed = Math.round(seed);
		const how = (childText(prob, 'sampling') ?? '').toLowerCase();
		if (how) sim.sampling = /latin/.test(how) ? 'latin' : 'random';
		// Which parameters it varies, where the model says. One assessment lists
		// 40-odd of them; most list none, which means all of them.
		const chosen = children(child(prob, 'probabilistic-parameters') ?? { children: [] },
			'selected-parameter').map((n2) => (n2.text ?? '').trim()).filter(Boolean);
		if (chosen.length) sim.varied = chosen;
		// Correlated sampling is a real feature and is not supported here: the pairs
		// are read out so the count can be said, and nothing uses them.
		const pairs = children(child(prob, 'correlation-matrix') ?? { children: [] },
			'correlation-pair').length;
		if (pairs && childText(prob, 'correlation-enabled') !== 'false') {
			report.warn(
				`The model correlates ${pairs} pair(s) of parameters when it samples `
				+ `them. This tool samples each one independently, so a probabilistic `
				+ `run here spreads wider than Ecolego's would.`,
			);
		}
	}

	const unit = (childText(s, 'time-unit') ?? '').toLowerCase();
	const UNITS = lookup({
		second: 'second', seconds: 'second', s: 'second',
		minute: 'minute', minutes: 'minute',
		hour: 'hour', hours: 'hour', h: 'hour',
		day: 'day', days: 'day', d: 'day',
		year: 'year', years: 'year', y: 'year', a: 'year',
	});
	if (UNITS[unit]) sim.time_unit = UNITS[unit];
	else if (unit) report.warn(`Unrecognised time unit '${unit}'; years were assumed.`);

	const solver = (childText(s, 'java-solver') ?? '').toUpperCase().replace(/[^A-Z0-9]/g, '');
	if (SOLVER_MAP[solver]) {
		sim.solver = SOLVER_MAP[solver];
		if (!SOLVER_EXACT.has(solver)) {
			report.warn(
				`The model used the ${solver} solver, which this tool does not have; `
				+ `${solverName(sim.solver)} was chosen as the closest.`,
			);
		}
	}

	const rtol = childNumber(s, 'rel-error-tolerance');
	const atol = childNumber(s, 'abs-error-tolerance');
	if (rtol != null && rtol > 0) sim.rtol = rtol;
	if (atol != null && atol > 0) sim.abstol = atol;

	if (sim.start_time < 0) {
		sim.spacing = 'linear';
		report.warn(
			'The simulation starts before zero, so linear output spacing was used '
			+ '(logarithmic time needs a non-negative start).',
		);
	}

	readOutputTimes(s, sim, report);
	readEndpoints(s, sim);

	const type = (childText(s, 'simulation-type') ?? '').toUpperCase();
	if (type && type !== 'DETERMINISTIC') {
		report.warn(
			`The model is set up for a ${type.toLowerCase()} simulation; this tool `
			+ `runs the deterministic case only.`,
		);
	}

	project.simulation = sim;
}

/**
 * The project's user-defined functions.
 *
 * `<function-model>` holds one `<function>` per function, and the metadata
 * beside it names the parameters: the name, the source file and the source
 * type, then a `<parameter-metadata>` per argument.
 *
 * What cannot come across is the body. It is a source file inside the archive,
 * in a language the desktop tools compile when a run starts and a browser
 * cannot run at all. So the block arrives with its signature and an
 * empty body, the report says so, and the problem strip asks for the equation
 * before the model will run. See ../sim/functions.js.
 */
function readFunctions(dataModel, project, names, report) {
	const model = find(dataModel, 'function-model');
	if (!model) return;
	for (const el of children(model, 'function')) {
		const original = el.attrs.name ?? el.attrs['source-file-name'] ?? 'function';
		const name = names.map(original, `fn:${original}`, '', original);
		const meta = child(el, 'function-metadata');
		const parameters = [];
		for (const p of meta ? children(meta, 'parameter-metadata') : []) {
			// The key is the identifier; the name is what the dialog showed.
			const raw = p.attrs.key ?? p.attrs.name ?? `p${parameters.length + 1}`;
			parameters.push(safeParameter(raw, parameters));
		}
		project.functions.push(trimEmpty({
			name,
			parameters,
			equation: '',
			unit: '',
			comment: childText(meta ?? el, 'function-description') ?? '',
		}));
		report.warn(
			`'${original}' is a user-defined function, whose body is compiled code in the project `
			+ `archive (${el.attrs['source-file-name'] ?? 'a compiled source file'}). This tool keeps `
			+ `its name and its ${parameters.length} parameter(s); write what it works out `
			+ `to as an equation before the model will run.`,
		);
	}
}

/**
 * The endpoints, by the names the blocks ended up with.
 *
 * `<output id="...">` names a block id, and this tool renames blocks whose
 * Ecolego names its identifiers cannot spell. Run after every other rewrite,
 * so the names here are the ones the model kept. An id with nothing behind it
 * is dropped in silence: an endpoint on a block that did not come across is
 * answered by the report entry for that block, not by a second complaint.
 */
function rewriteEndpointIds(project, blockNameById, report) {
	const ids = project.simulation?.endpoints;
	if (!Array.isArray(ids) || !ids.length) return;
	const known = new Set();
	for (const collection of KINDS) {
		for (const b of project[collection] ?? []) {
			known.add(b.system ? `${b.system}.${b.name}` : b.name);
		}
	}
	const out = [];
	const seen = new Set();
	let unresolved = 0;
	for (const id of ids) {
		// The id first, because in these files an id *is* the qualified name
		// (`NearField.waste_domain_length`) and the map is older than the
		// model: it was built before groups were flattened, so a block that
		// moved out of a group is under a name the map no longer knows. The
		// map is what answers for a block this tool had to rename.
		const name = known.has(id) ? id : blockNameById.get(id) ?? id;
		// Repeats are not a fault and are not counted as one: Ecolego writes
		// one `<output>` per index of an endpoint, so model B
		// lists 746 of them for 102 blocks. An endpoint is a block here, and
		// a block's indices go with it.
		if (seen.has(name)) continue;
		if (!known.has(name)) { unresolved += 1; continue; }
		seen.add(name);
		out.push(name);
	}
	if (out.length) project.simulation.endpoints = out;
	else delete project.simulation.endpoints;
	if (unresolved) {
		report.warn(
			`${unresolved} of the model's saved endpoints name blocks that are not in `
			+ `the imported model; they were left out of the endpoint list.`,
		);
	}
}

/**
 * Which blocks the model is set up to save: Ecolego's **endpoints**.
 *
 *     <outputs>
 *       <output id="NearField&#46;waste&#95;domain&#95;length"/>
 *       ...
 *     </outputs>
 *
 * `JavaSimulator` writes a result series for each of these and for nothing
 * else, which is why an Ecolego result file holds two groups where the model
 * has three thousand blocks. This tool keeps every series a run produces --
 * they are worked out from the states on request, so keeping them costs
 * nothing until they are asked for -- but the list is still the modeller's own
 * answer to "which of these did I want?", and that is exactly what an export
 * needs to be offered.
 *
 * Ids, not names: they are block ids here, and the id-to-name rewrite happens
 * after every block has been read. `rewriteEndpointIds` does that.
 */
function readEndpoints(s, sim) {
	const list = child(s, 'outputs');
	if (!list) return;
	const ids = children(list, 'output')
		.map((el) => el.attrs.id)
		.filter((id) => typeof id === 'string' && id);
	if (ids.length) sim.endpoints = ids;
}

/** A parameter name this tool's parser can read, kept clear of its siblings. */
function safeParameter(raw, taken) {
	let name = String(raw ?? '').trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^(?=\d)/, 'p');
	if (!name || RESERVED.has(name)) name = `p${taken.length + 1}`;
	while (taken.includes(name)) name = `${name}_`;
	return name;
}

