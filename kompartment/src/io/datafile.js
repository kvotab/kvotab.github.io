/**
 * A data table as a spreadsheet, and as an HDF5 tree.
 *
 * `../domain/datatable.js` says what a row *is*; this says how one is spelled
 * in each of the two formats an assessment's data actually travels in. Both
 * ends of both formats are here so the vocabulary they share -- which word
 * names which curve, which column holds which of its numbers -- is written
 * down once.
 *
 * ---------------------------------------------------------------------------
 * THE SPREADSHEET
 *
 * One row per value: a parameter is one row, a lookup table is one row per
 * point with the time in its own column. The columns are the ones these data
 * sets already use, so a file written here opens beside one written by hand
 * and a file written by hand reads here.
 *
 *   ID        the dotted path — sub-systems, block, then one segment per index
 *   Unit
 *   Subsystem, Name, Media, Position, Species
 *             **helpers, not data.** In a hand-made sheet these are what the
 *             ID is pasted together from, so they are filled in on the way out
 *             and read on the way in *only* when ID itself is empty.
 *   Time      empty for a parameter; the point's time for a lookup table
 *   Value     the deterministic value — what the model runs at
 *   Type      which curve: norm, unif, logn, logu, triang, dtriang, logt, logdt
 *   Group     inputs sharing a group share one underlying sample
 *   Min, Max  the two ends for a curve that has them, and the truncation for
 *             one that does not — see `SHAPES`
 *   Mean, Std the normal curve's two
 *   GM, GSD   the log-normal's two
 *   Pmin,Pmax truncation as percentiles of this curve rather than as values
 *
 * ---------------------------------------------------------------------------
 * THE HDF5 TREE
 *
 * The path *is* the ID: `/model/Atmosphere/height/L1` is the id
 * `Atmosphere.height.L1`. A parameter is a scalar dataset; a lookup table is a
 * dataset of its values carrying `lookup_table` and an `index` attribute
 * holding the times. Everything else about a row rides as attributes: `unit`,
 * and `pdf`, a JSON object in the same words the spreadsheet's columns use.
 *
 * ---------------------------------------------------------------------------
 * AN UNDERSCORE IS THE DEFAULT
 *
 * A path segment written `_` means *the block's own value*, not an index of
 * that name: `CR.food.herbiv._` is what `CR.food.herbiv` falls back to where
 * no index says otherwise. It is how a data set gives one number for every
 * element and then overrides four of them.
 */

import { readWorkbook, writeWorkbook } from './xlsx.js';
import { writeHDF5, group, dataset, put, F64, STR } from './hdf5.js';
import { readHDF5 } from './hdf5read.js';
import { parsePDF, complete, PDF_KINDS } from '../domain/pdf.js';

/** The segment that means "the block's own value, at no index". */
export const DEFAULT_SEGMENT = '_';

/**
 * A dataset that is not a distribution but a *sample*: the numbers themselves,
 * one per realisation.
 *
 * Some data is not quoted as a curve at all. A near-field release rate is the
 * output of a thousand runs of another model, and what the next model wants is
 * those thousand curves, not a shape fitted to them. Written two ways:
 *
 *   **A column.** `(1001,)` with `pdf: {"type": "raw",
 *   "include_deterministic": true}` -- the first value is the deterministic
 *   one and the thousand after it are the realisations.
 *
 *   **A matrix.** `(394, 1000)` beside a `/time` dataset of 394 times, so
 *   every column is one realisation's whole curve. `probabilistic` and
 *   `time_dependent` on the dataset say which it is.
 *
 * Either becomes a list of values taken in order, which is what
 * `../domain/pdf.js` calls `pg` -- a list is not drawn from, it is handed out,
 * one value per realisation, which is how a run reproduces somebody else's.
 * For a matrix that means one list per *point* of the table, and since every
 * point is read at the same realisation number the curve stays whole.
 */
const RAW = 'raw';

/** Where a file keeps the times a matrix is against. */
const TIME_PATHS = ['/time', '/Time', '/times'];

/** The middle of a sample, for a deterministic value where the file gives none. */
function middle(values) {
	const finite = Array.from(values).filter((v) => Number.isFinite(v));
	if (!finite.length) return null;
	finite.sort((a, b) => a - b);
	const half = finite.length >> 1;
	return finite.length % 2 ? finite[half] : (finite[half - 1] + finite[half]) / 2;
}

/** A list of values as a spec, or null where there is nothing to hand out. */
export function sampleSpec(values, group = null) {
	if (!values || !values.length) return null;
	return {
		kind: 'pg',
		params: {},
		values,
		trmin: null, trmax: null, pmin: null, pmax: null,
		group,
		// In the order written, one per realisation. Drawing from the list at
		// random would be a different experiment: these values *are* the
		// sample, and shuffling them breaks the pairing with every other
		// quantity that came out of the same run.
		inorder: true,
		pos: 0,
	};
}

/** Whether an attribute says "these are the numbers", and how to read them. */
function rawOf(attr) {
	if (attr == null) return null;
	let obj = attr;
	if (typeof attr === 'string') {
		const t = attr.trim();
		if (!t.startsWith('{')) return null;
		try { obj = JSON.parse(t); } catch { return null; }
	}
	if (String(obj?.type ?? '').toLowerCase() !== RAW) return null;
	return { deterministic: obj.include_deterministic === true };
}

/** `True`/`true`/1, however the file wrote it. */
const flagged = (v) => v != null && !/^(false|0|)$/i.test(String(v));

/**
 * Which columns hold which curve's numbers.
 *
 * `params` maps the spec's own parameter keys to column names. `cut` says
 * whether Min and Max are this curve's ends or a truncation of it: for a
 * uniform they are the distribution, for a normal they are a pair of scissors.
 */
export const SHAPES = {
	norm: { kind: 'norm', params: { mean: 'Mean', sd: 'Std' }, cut: true },
	unif: { kind: 'unif', params: { min: 'Min', max: 'Max' }, cut: false },
	logn: { kind: 'Logn4', params: { gm: 'GM', gsd: 'GSD' }, cut: true },
	logu: { kind: 'logu', params: { min: 'Min', max: 'Max' }, cut: false },
	triang: { kind: 'triang', params: { min: 'Min', max: 'Max', mode: 'Mean' }, cut: false },
	logt: { kind: 'logt', params: { min: 'Min', max: 'Max', mode: 'Mean' }, cut: false },
	// skbrnt's double triangulars, which SKB's SFK data sets use for release
	// fractions (dtriang) and diffusivities (logdt). The HDF5 form is
	// `{"type": "dtriang", "a", "b", "m"}`, and a sheet row gives Min, Max and
	// the mode in Value, as a triangular's does.
	dtriang: { kind: 'dtriang', params: { min: 'Min', max: 'Max', mode: 'Mean' }, cut: false },
	logdt: { kind: 'logdt', params: { min: 'Min', max: 'Max', mode: 'Mean' }, cut: false },
};

/** Back the other way: a spec's kind to the word a file uses for it. */
const WORD = new Map(Object.entries(SHAPES).map(([word, s]) => [s.kind, word]));

export const COLUMNS = [
	'ID', 'Unit', 'Subsystem', 'Name', 'Media', 'Position', 'Species',
	'Time', 'Value', 'Type', 'Group',
	'Min', 'Max', 'Mean', 'Std', 'GM', 'GSD', 'Pmin', 'Pmax',
	'Reference',
];

/** The helper columns, in the order a hand-made ID pastes them together. */
const HELPERS = ['Subsystem', 'Name', 'Media', 'Position', 'Species'];

const num = (v) => {
	if (v == null || v === '') return null;
	const n = typeof v === 'number' ? v : Number(String(v).trim());
	return Number.isFinite(n) ? n : null;
};

const str = (v) => (v == null ? '' : String(v).trim());

/**
 * A value cell: a number where it is one, and the text otherwise.
 *
 * Not every value in a data set is a number. `SRF.speciation.Ac` is
 * `GROUP1` -- which speciation class an element belongs to -- and dropping it
 * for not parsing would lose seventeen rows of a hundred and seventy without
 * saying so.
 */
const value = (v) => {
	const n = num(v);
	if (n != null) return n;
	const t = str(v);
	return t === '' ? null : t;
};

/* ==========================================================================
 * A DISTRIBUTION, EITHER WAY
 * ======================================================================= */

/** A spec from a row of columns, or null where the row names no curve. */
export function pdfFromColumns(at) {
	const word = str(at('Type')).toLowerCase();
	if (!word) return null;
	const shape = SHAPES[word];
	if (!shape) return { bad: `'${at('Type')}' is not a distribution this reads` };
	const spec = {
		kind: shape.kind,
		params: {},
		values: null,
		trmin: null, trmax: null,
		pmin: num(at('Pmin')), pmax: num(at('Pmax')),
		group: str(at('Group')) || null,
		inorder: true, pos: 0,
	};
	for (const [key, column] of Object.entries(shape.params)) spec.params[key] = num(at(column));
	// A triangular's most likely value is the `Value` column where `Mean` is
	// empty, which is how these sheets write one: the deterministic value a
	// model runs at *is* the mode, and repeating it in a second column would
	// be two places to get it wrong.
	if (shape.params.mode && spec.params.mode == null) spec.params.mode = num(at('Value'));
	// Min and Max are the curve's own ends for a shape that has them, and a
	// truncation of it for one that does not. A normal with `Min 0` is not a
	// normal from zero; it is a normal that nothing below zero came out of.
	if (shape.cut) {
		spec.trmin = num(at('Min'));
		spec.trmax = num(at('Max'));
	}
	return spec;
}

/** The columns a spec fills in. */
export function columnsFromPDF(spec) {
	const out = {};
	if (!spec) return out;
	const word = WORD.get(spec.kind);
	if (!word) return out;
	const shape = SHAPES[word];
	out.Type = word;
	for (const [key, column] of Object.entries(shape.params)) {
		const v = spec.params?.[key];
		if (v != null) out[column] = v;
	}
	if (shape.cut) {
		if (spec.trmin != null) out.Min = spec.trmin;
		if (spec.trmax != null) out.Max = spec.trmax;
	}
	if (spec.pmin != null) out.Pmin = spec.pmin;
	if (spec.pmax != null) out.Pmax = spec.pmax;
	if (spec.group) out.Group = spec.group;
	return out;
}

/** The same spec as the JSON object an HDF5 attribute carries. */
export function pdfToJSON(spec) {
	const cols = columnsFromPDF(spec);
	if (!cols.Type) return null;
	const shape = SHAPES[cols.Type];
	const out = { type: cols.Type };
	// The HDF5 form names the parameters rather than the spreadsheet's
	// columns: `gm`/`gsd`, `a`/`b`, `mean`/`std`, which is how the files these
	// read already spell them.
	const HDF_NAME = { min: 'a', max: 'b', sd: 'std', mode: 'm' };
	for (const key of Object.keys(shape.params)) {
		const v = spec.params?.[key];
		if (v != null) out[HDF_NAME[key] ?? key] = v;
	}
	if (spec.trmin != null) out.trmin = spec.trmin;
	if (spec.trmax != null) out.trmax = spec.trmax;
	if (spec.pmin != null) out.pmin = spec.pmin;
	if (spec.pmax != null) out.pmax = spec.pmax;
	if (spec.group) out.group = spec.group;
	return out;
}

/**
 * A list of specs, one per point, for a table whose points carry their own.
 *
 * The attribute is a JSON *array* then rather than an object, in the order the
 * values are in. A table that has one distribution for the whole of it is not
 * a thing either format expresses: a point is where a number is, so a point is
 * where its spread is.
 */
export function pdfListFromJSON(raw) {
	if (raw == null) return null;
	let list = raw;
	if (typeof raw === 'string') {
		const text = raw.trim();
		if (!text.startsWith('[')) return null;
		try { list = JSON.parse(text); } catch { return null; }
	}
	if (!Array.isArray(list)) return null;
	return list.map((o) => pdfFromJSON(o));
}

/** And back. */
export function pdfFromJSON(raw) {
	if (!raw) return null;
	let obj = raw;
	if (typeof raw === 'string') {
		const text = raw.trim();
		if (!text) return null;
		// Some writers put the expression itself in the attribute rather than
		// a JSON object; both are read, since both say the same thing.
		if (text.startsWith('[')) return null;
		if (!text.startsWith('{')) return parsePDF(text);
		try { obj = JSON.parse(text); } catch { return null; }
	}
	const shape = SHAPES[String(obj.type ?? '').toLowerCase()];
	if (!shape) return null;
	const HDF_NAME = { min: 'a', max: 'b', sd: 'std', mode: 'm' };
	const spec = {
		kind: shape.kind,
		params: {},
		values: null,
		trmin: num(obj.trmin), trmax: num(obj.trmax),
		pmin: num(obj.pmin), pmax: num(obj.pmax),
		group: str(obj.group) || null,
		inorder: true, pos: 0,
	};
	for (const key of Object.keys(shape.params)) {
		spec.params[key] = num(obj[HDF_NAME[key] ?? key] ?? obj[key]);
	}
	// A truncation at the curve's own ends is not a truncation. These files
	// carry it on every uniform -- `a 0.2, b 0.4, trmin 0.2, trmax 0.4` --
	// which cuts nothing off and would otherwise come back as a distribution
	// the spreadsheet's spelling of the same numbers does not have.
	if (!shape.cut) {
		if (spec.trmin != null && spec.trmin === spec.params.min) spec.trmin = null;
		if (spec.trmax != null && spec.trmax === spec.params.max) spec.trmax = null;
	}
	return spec;
}

/* ==========================================================================
 * THE SPREADSHEET
 * ======================================================================= */

/** The rows of a data table as a grid, header first. */
export function toSheet(rows) {
	const at = (i) => COLUMNS[i];
	const grid = [COLUMNS.slice()];
	for (const r of rows) {
		const cells = new Array(COLUMNS.length).fill(null);
		const set = (name, v) => { cells[COLUMNS.indexOf(name)] = v; };
		set('ID', r.id);
		set('Unit', r.unit || null);
		// The helpers, as far as the model can honestly fill them in: where
		// the block lives and what it is called. The other three name roles
		// this tool does not have, and a guess in them would be read back.
		const parts = String(r.id).split('.');
		const own = r.block?.name ?? parts[parts.length - 1];
		const sub = r.block?.system ?? '';
		set('Subsystem', sub || null);
		set('Name', own || null);
		if (r.time != null) set('Time', r.time);
		if (r.value != null) set('Value', r.value);
		for (const [k, v] of Object.entries(columnsFromPDF(r.pdf))) set(k, v);
		if (r.note) set('Reference', r.note);
		// Trailing nulls are dropped so a sheet of values is not twenty empty
		// cells wide on every row.
		let last = cells.length;
		while (last > 0 && cells[last - 1] == null) last--;
		grid.push(cells.slice(0, last));
		void at;
	}
	return grid;
}

/**
 * A grid back to rows.
 *
 * The header decides which column is which, by name, so a sheet with the
 * columns in another order -- or with columns this does not know -- reads the
 * same. A sheet whose header has no `ID` and no helpers is refused rather than
 * read as 1,758 rows of nothing.
 */
export function fromSheet(grid, { sheet = '' } = {}) {
	const rows = [];
	const problems = [];
	const header = (grid?.[0] ?? []).map((h) => str(h));
	const where = new Map();
	header.forEach((h, i) => { if (h && !where.has(h)) where.set(h, i); });
	const has = (name) => where.has(name);
	if (!has('ID') && !HELPERS.some(has)) {
		return { rows, problems: [`${sheet || 'The sheet'} has no ID column.`] };
	}
	for (let i = 1; i < (grid?.length ?? 0); i++) {
		const line = grid[i] ?? [];
		const at = (name) => (where.has(name) ? line[where.get(name)] : null);
		// The ID as written, or pasted together from the helpers for a sheet
		// that has only those -- which is what a half-made one looks like.
		let id = str(at('ID'));
		if (!id) id = HELPERS.map((h) => str(at(h))).filter(Boolean).join('.');
		if (!id) continue;
		const cell = value(at('Value'));
		const time = num(at('Time'));
		const spec = pdfFromColumns(at);
		if (spec?.bad) {
			problems.push(`Row ${i + 1}: ${spec.bad}.`);
		}
		rows.push({
			id, unit: str(at('Unit')), time, value: cell,
			pdf: spec && !spec.bad ? spec : null,
			note: str(at('Reference')), row: i + 1, sheet,
		});
	}
	return { rows, problems };
}

/** A workbook of one sheet per model, or one sheet called `data`. */
export async function writeDataWorkbook(rows, { name = 'data' } = {}) {
	return writeWorkbook({ sheets: [{ name, rows: toSheet(rows) }] });
}

/** Every sheet of a workbook, read as rows. */
export async function readDataWorkbook(bytes) {
	const book = await readWorkbook(bytes);
	const rows = [];
	const problems = [];
	for (const sheet of book.sheets) {
		const got = fromSheet(sheet.rows, { sheet: sheet.name });
		rows.push(...got.rows);
		problems.push(...got.problems);
	}
	return { rows, problems };
}

/* ==========================================================================
 * THE HDF5 TREE
 * ======================================================================= */

/** A path segment HDF5 can hold: `/` is the separator and cannot be in one. */
const segment = (s) => String(s).replace(/\//g, '_');

/**
 * The rows as a tree, under one root group named after the model.
 *
 * A lookup table goes out as its values with the times beside them in an
 * `index` attribute, which is how the files these read already carry one: the
 * dataset is the quantity and the attribute is what it is a function of.
 */
export function toTree(rows, { root = 'model' } = {}) {
	const tree = group({});
	const tables = new Map();
	for (const r of rows) {
		// `put` takes the segments, not a path: `/` is the one character a
		// link name may not hold, so the split has to happen before it.
		const path = [segment(root), ...String(r.id).split('.').map(segment)];
		if (r.time != null) {
			const at = path.join('/');
			if (!tables.has(at)) tables.set(at, { path, times: [], values: [], pdfs: [], row: r });
			const t = tables.get(at);
			t.times.push(r.time);
			t.values.push(r.value ?? NaN);
			t.pdfs.push(r.pdf ?? null);
			continue;
		}
		const attrs = { unit: r.unit ?? '' };
		const pdf = pdfToJSON(r.pdf);
		if (pdf) attrs.pdf = JSON.stringify(pdf);
		if (r.note) attrs.reference = r.note;
		// A value that is not a number goes out as text rather than as NaN:
		// `GROUP1` is the answer, not a failure to parse one.
		put(tree, path, typeof r.value === 'string'
			? dataset([r.value], STR, attrs)
			: dataset([r.value ?? NaN], F64, attrs));
	}
	for (const t of tables.values()) {
		const order = t.times.map((v, i) => i).sort((a, b) => t.times[a] - t.times[b]);
		const attrs = {
			unit: t.row.unit ?? '',
			lookup_table: 'true',
			index: order.map((i) => t.times[i]).join(','),
		};
		// A list, one per point, in the order the values are in -- and only
		// where some point actually carries one.
		const specs = order.map((i) => pdfToJSON(t.pdfs[i]));
		if (specs.some(Boolean)) attrs.pdf = JSON.stringify(specs);
		if (t.row.note) attrs.reference = t.row.note;
		put(tree, t.path, dataset(order.map((i) => t.values[i]), F64, attrs));
	}
	return tree;
}

/** The tree written out. */
export function writeDataHDF5(rows, opts = {}) {
	return writeHDF5(toTree(rows, opts));
}

/**
 * An HDF5 file read as rows.
 *
 * The first path segment is the file's own root name and is dropped: it is the
 * model, not part of any id. Everything below it joins with dots.
 */
export async function readDataHDF5(bytes) {
	const { datasets, problems } = await readHDF5(bytes);
	const rows = [];
	// The times a matrix is against, where the file keeps them in one place.
	const clock = datasets.find((d) => TIME_PATHS.includes(d.path))?.values ?? null;
	for (const d of datasets) {
		const parts = d.path.split('/').filter(Boolean);
		if (parts.length < 2) continue;
		// The shared time axis and the index lists are how the file is put
		// together, not data anybody asked for.
		if (TIME_PATHS.includes(d.path) || parts[0] === 'IndexLists') continue;
		const id = parts.slice(1).join('.');
		const unit = str(d.attrs?.unit);
		const note = str(d.attrs?.reference);
		const times = indexTimes(d.attrs?.index);
		const isTable = d.attrs?.lookup_table != null
			&& String(d.attrs.lookup_table).toLowerCase() !== 'false';
		const raw = rawOf(d.attrs?.pdf);
		const sampled = !!raw || flagged(d.attrs?.probabilistic);

		// --- a matrix of realisations: one whole curve per column ----------
		if (d.dims?.length === 2 && sampled) {
			const [T, N] = d.dims;
			const when = times && times.length === T ? times
				: (clock && clock.length === T ? clock : null);
			if (!when) {
				problems.push(`${d.path}: is ${T}×${N} and nothing in the file says what the `
					+ `${T} are times of.`);
				continue;
			}
			for (let t = 0; t < T; t++) {
				// A row of the matrix is contiguous, so this is a view rather
				// than a copy -- fifty-three of these is twenty million values
				// and copying them would be twice that.
				const at = d.values.subarray(t * N, (t + 1) * N);
				rows.push({
					id, unit, time: when[t], value: middle(at), pdf: sampleSpec(at), note,
				});
			}
			continue;
		}

		// --- a column of realisations: one value each ----------------------
		if (d.dims?.length === 1 && sampled && !isTable) {
			// `include_deterministic` means the first value is the one the
			// model runs at and the rest are the sample; without it the
			// middle of the sample is the honest stand-in.
			const all = d.values;
			const sample = raw?.deterministic ? all.subarray(1) : all;
			rows.push({
				id, unit, time: null,
				value: raw?.deterministic ? all[0] : middle(sample),
				pdf: sampleSpec(sample), note,
			});
			continue;
		}
		if (isTable && times && times.length === d.values.length) {
			// One spec per point where the attribute is a list, and none where
			// it is not: a table's points each have their own spread or none
			// of them does.
			const specs = pdfListFromJSON(d.attrs?.pdf);
			for (let i = 0; i < times.length; i++) {
				rows.push({
					id, unit, time: times[i], value: d.values[i],
					pdf: specs?.[i] ?? null, note,
				});
			}
			continue;
		}
		rows.push({
			id, unit, time: null,
			value: d.values.length ? d.values[0] : null,
			pdf: pdfFromJSON(d.attrs?.pdf),
			note,
		});
	}
	return { rows, problems };
}

/** The `index` attribute, however it was written: a list or a string of them. */
function indexTimes(raw) {
	if (raw == null) return null;
	if (Array.isArray(raw) || ArrayBuffer.isView(raw)) return Array.from(raw, Number);
	const parts = String(raw).split(/[,\s]+/).map((s) => Number(s)).filter((n) => Number.isFinite(n));
	return parts.length ? parts : null;
}

/** Whether a spec is worth writing: an empty one says less than nothing. */
export function usable(spec) {
	return !!spec && !!PDF_KINDS[spec.kind] && complete(spec);
}
