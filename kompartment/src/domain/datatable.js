/**
 * The model's data as a flat table, and back again.
 *
 * A parameter's value, a lookup table's points, the distribution either of
 * them carries: the numbers an assessment argues about, separated from the
 * structure that consumes them. This module is the shape both file formats
 * agree on, so `../io/xlsx.js` and `../io/hdf5*.js` each only have to say how
 * a row is spelled in their own notation rather than what a row means.
 *
 * ---------------------------------------------------------------------------
 * A ROW
 *
 *   { id, unit, time, value, pdf, note }
 *
 * `id` is a dotted path: the sub-systems it lives in, then the block, then one
 * segment per index it is given at. `time` is null for a parameter and a
 * number for one point of a lookup table -- several rows sharing an `id` and
 * differing in `time` *are* the table. `pdf` is a spec from ./pdf.js or null.
 *
 * ---------------------------------------------------------------------------
 * READING AN ID BACK
 *
 * The hard half, and the reason this is done against the model rather than by
 * a rule. `CR.food.herbiv.Ac` is the parameter `CR.food.herbiv` at index `Ac`,
 * and `Atmosphere.height.L1` is the parameter `height` inside the sub-system
 * `Atmosphere` at index `L1` -- and nothing in either string says where the
 * name stops and the index begins. Asking the model does: the longest prefix
 * that is a block *is* the block, and what is left over are its indices, taken
 * in the order of its own index lists.
 *
 * Which is also why creating what is missing is a different rule and says so:
 * with no block to ask, the whole path has to be the name.
 */

import { DEFAULT_SEGMENT, usable } from '../io/datafile.js';
import { findBlock } from './blocks.js';
import { qualifiedName } from './systems.js';
import { parsePDF, PDF_KINDS } from './pdf.js';
import * as ed from './edit.js';

export class DataTableError extends Error {
	constructor(message) {
		super(message);
		this.name = 'DataTableError';
	}
}

/** The two kinds of block this carries. Nothing else has data in this sense. */
const CARRIES = ['parameters', 'lookups'];

/**
 * A number where there is one, and null where there is none.
 *
 * Blank is no value. `Number('')` is 0, so a cell of spaces used to arrive as
 * a zero -- a time of 0 on a table's point, a value of 0 on a parameter --
 * with nothing to say it had been blank.
 */
const num = (v) => {
	if (v == null || v === '') return null;
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	const text = String(v).trim();
	if (text === '') return null;
	const n = Number(text);
	return Number.isFinite(n) ? n : null;
};

/**
 * A spec the model can hold.
 *
 * A sample read out of a file arrives as a *view* into the one big array the
 * file was read into -- which is what keeps twenty million values from being
 * copied on the way in. A model is JSON, and `JSON.stringify` of a typed array
 * is an object with numbered keys rather than a list, so the view becomes a
 * plain array here, at the one boundary where the numbers actually enter the
 * model and only for what is actually imported.
 */
function held(spec) {
	if (!spec || !ArrayBuffer.isView(spec.values)) return spec;
	return { ...spec, values: Array.from(spec.values) };
}

/**
 * Counts a sample that went into the model. Only once it has: a table the
 * file gives two rows at one time is refused, and its samples were counted as
 * read all the same when this was done on the way past.
 */
function countSample(spec, out) {
	if (spec?.kind === 'pg' && spec.values?.length) {
		out.samples += 1;
		out.sampleValues += spec.values.length;
	}
}

/** A spec is a string of Ecolego's where a model file holds it as one. */
const specOf = (raw) => (!raw ? null : typeof raw === 'string' ? parsePDF(raw) : raw);

/** A number where it is one, the text otherwise -- see `value` in io/datafile.js. */
const value = (v) => {
	const n = num(v);
	if (n != null) return n;
	const t = v == null ? '' : String(v).trim();
	return t === '' ? null : t;
};

/**
 * The dotted id of a block at an index combination.
 *
 * The qualified name already carries the sub-systems, so an index is the only
 * thing added -- in the block's own list order, which is what makes the id
 * readable back.
 */
export function idFor(block, index = null) {
	const base = qualifiedName(block);
	const lists = block.index_lists ?? [];
	if (!index || !lists.length) return base;
	const tail = lists.map((l) => index[l]).filter((v) => v != null && v !== '');
	return tail.length ? `${base}.${tail.join('.')}` : base;
}

/**
 * Every index combination a block is given at, as `{index, id}`.
 *
 * A block with no index lists is one combination with an empty index -- the
 * block itself -- so a caller never has to special-case the unindexed.
 */
function combinationsOf(project, block) {
	const lists = block.index_lists ?? [];
	if (!lists.length) return [{ index: {}, id: idFor(block) }];
	let rows = [{}];
	for (const name of lists) {
		// Read as the file has it. `findIndexList` normalises a list's indices
		// in place, so reading the data out of a model used to rewrite its
		// index lists -- a bare-string index became an object -- and an
		// export is not an edit. A bare string is an index's name.
		const list = ed.indexLists(project).find((l) => l.name === name) ?? null;
		const members = (list?.indices ?? [])
			.filter((i) => i != null && (typeof i !== 'object' || i.enabled !== false))
			.map((i) => (typeof i === 'object' ? i.name : i))
			.filter((m) => m != null && m !== '');
		// An index list nobody has filled in yet gives the block one row at no
		// index at all, which is the block's own default -- better than none,
		// which would drop the block out of the file entirely.
		if (!members.length) return [{ index: {}, id: idFor(block) }];
		rows = rows.flatMap((r) => members.map((m) => ({ ...r, [name]: m })));
	}
	// The block's own value first, where it has one: an id of underscores,
	// which is what a file writes for "and this is the default".
	const out = rows.map((index) => ({ index, id: idFor(block, index) }));
	const own = block.value ?? block.points;
	if (own != null) {
		out.unshift({
			index: {},
			id: `${qualifiedName(block)}.${lists.map(() => DEFAULT_SEGMENT).join('.')}`,
			isDefault: true,
		});
	}
	return out;
}

/** The pdf at one index, as a spec, or null. */
function pdfAt(block, index) {
	const raw = ed.effectiveValue(block, 'pdf', index);
	if (!raw) return null;
	if (typeof raw === 'string') return parsePDF(raw);
	return raw;
}

/**
 * The model's data as rows.
 *
 * Everything, distributed or not: a data file that carried only the
 * distributed half would be a file this could not read back as a complete
 * picture of the model.
 *
 * @param {object} project  the raw model
 * @returns {Array<{id, unit, time, value, pdf, note, block, index, kind}>}
 */
export function collect(project) {
	const out = [];
	for (const kind of CARRIES) {
		for (const block of project?.[kind] ?? []) {
			const unit = block.unit ?? '';
			for (const { index, id } of combinationsOf(project, block)) {
				if (kind === 'lookups') {
					const points = ed.effectiveValue(block, 'points', index) ?? [];
					// A table with no points is still a table, and a row with
					// no time says so rather than leaving the block out.
					if (!points.length) {
						out.push({ id, unit, time: null, value: null, pdf: null,
							note: block.comment ?? '', block, index, kind: 'lookup' });
						continue;
					}
					for (const p of points) {
						out.push({
							id, unit, time: num(p?.[0]), value: num(p?.[1]),
							// A point may carry its own spread -- see the third
							// element -- and most do not. Read as a parameter's
							// is, so Ecolego's text arrives as the spec it says.
							pdf: specOf(p?.[2] ?? null),
							note: block.comment ?? '', block, index, kind: 'lookup',
						});
					}
					continue;
				}
				out.push({
					id, unit, time: null,
					value: value(ed.effectiveValue(block, 'value', index)),
					pdf: pdfAt(block, index),
					note: block.comment ?? '', block, index, kind: 'parameter',
				});
			}
		}
	}
	return out;
}

/**
 * A path segment as a block name can be.
 *
 * A name here is an identifier -- letters, digits and underscore, not starting
 * with a digit -- because it has to be writable in an equation. A repository
 * called `1BMA` is not one, and vault names like it are what data files hold. It
 * becomes `_1BMA`, which is the same name in a form the language can hold.
 *
 * The *file* is left alone: this is what an id becomes on the way in, and
 * `resolve` tries it, so importing the same file again matches what the last
 * import made.
 */
export function legalName(segment) {
	const s = String(segment ?? '');
	if (/^[A-Za-z_]\w*$/.test(s)) return s;
	const body = s.replace(/\W/g, '_');
	return /^[A-Za-z_]/.test(body) ? body : `_${body}`;
}

/**
 * Which block and index an id names, asking the model.
 *
 * The longest prefix that is a block wins, and what is left are its indices.
 * Returns null when nothing matches, which is what the import reports rather
 * than guesses about.
 */
export function resolve(project, id) {
	const raw = String(id ?? '').split('.').map((s) => s.trim()).filter(Boolean);
	if (!raw.length) return null;
	// As written first, then as a name can be: a model built by this module
	// from a file with `1BMA` in it holds `_1BMA`, and the same file read
	// again has to find it.
	const legal = raw.map(legalName);
	const hit = match(project, raw);
	if (hit) return hit;
	return legal.join('.') === raw.join('.') ? null : match(project, legal);
}

function match(project, parts) {
	for (let k = parts.length; k >= 1; k--) {
		const name = parts.slice(0, k).join('.');
		const found = findBlock(project, name);
		if (!found || !CARRIES.includes(found.collection)) continue;
		const rest = parts.slice(k);
		const lists = found.block.index_lists ?? [];
		// More segments than the block has index lists is not this block: the
		// prefix matched by accident and a shorter one may be the real answer.
		if (rest.length > lists.length) continue;
		// `_` is the block's own value at that position rather than an index of
		// that name: `CR.food.herbiv._` is what the block falls back to where no
		// element says otherwise, which is how a data set gives one number for
		// all of them and then overrides four.
		const index = {};
		rest.forEach((v, i) => { if (v !== DEFAULT_SEGMENT) index[lists[i]] = v; });
		return { block: found.block, kind: found.kind, name, index, extra: rest };
	}
	return null;
}

/**
 * One report line per id that could not be used, and the counts.
 *
 * Built by `apply`, and worth its own shape because an import of 1,758 rows
 * that quietly did 1,200 of them is worse than one that refuses: a reader has
 * to be told what did not land.
 */
function report() {
	return {
		values: 0, pdfs: 0, tables: 0, created: 0,
		// A list of values is not a distribution, it is a sample -- and it is
		// the one that costs something, so it is counted apart and by how many
		// numbers it brings.
		samples: 0, sampleValues: 0,
		unmatched: [], problems: [],
		// Segments a created block could not keep: `1BMA` starts with a digit
		// and a name here has to be writable in an equation.
		renamed: new Map(),
		say(kind, id, why) {
			const line = `${id}: ${why}`;
			if (kind === 'unmatched') this.unmatched.push(line); else this.problems.push(line);
		},
	};
}

/** Rows grouped by id, with the times in order. */
function byId(rows) {
	const out = new Map();
	for (const r of rows) {
		if (!r || !r.id) continue;
		if (!out.has(r.id)) out.set(r.id, []);
		out.get(r.id).push(r);
	}
	for (const list of out.values()) {
		list.sort((a, b) => (a.time ?? -Infinity) - (b.time ?? -Infinity));
	}
	return out;
}

/**
 * Writes rows into the model.
 *
 * `create` decides what an unmatched id does: nothing but a line in the report
 * by default, or a new block when asked. Creating cannot ask the model where
 * the name stops, so the whole path becomes the name -- the id `a.b.c` makes a
 * parameter called `c` inside the sub-system `a.b`, which is the only reading
 * available without a block to compare against.
 *
 * @param {object} project  the raw model, edited in place
 * @param {Array<object>} rows
 * @param {{create?: boolean}} [opts]
 */
export function apply(project, rows, opts = {}) {
	const out = report();
	const create = opts.create === true;
	for (const [id, list] of byId(rows)) {
		let hit = resolve(project, id);
		if (!hit) {
			if (!create) {
				out.say('unmatched', id, 'nothing in this model is called that');
				continue;
			}
			hit = make(project, id, list, out);
			if (!hit) continue;
		}
		const timed = list.filter((r) => present(r.time));
		if (hit.kind === 'lookup' || (timed.length && hit.kind !== 'parameter')) {
			writeTable(project, hit, timed.length ? timed : list, out, id);
		} else if (timed.length) {
			out.say('problems', id,
				`is a ${hit.kind}, and the file gives it ${timed.length} times — `
				+ 'only a lookup table has points over time');
		} else {
			writeValue(project, hit, list[0], out, id);
		}
	}
	return out;
}

/**
 * Whether a row's value is one a parameter cannot hold: a word that is neither
 * a number nor the name of a block the model could evaluate.
 */
const unwritable = (project, row) => typeof row?.value === 'string' && row.value.trim() !== ''
	&& num(row.value) == null && !findBlock(project, row.value);

/** Whether a row gives a time or a value at all: blank is none. */
const present = (v) => v != null && !(typeof v === 'string' && v.trim() === '');

/**
 * A block for an id nothing matched. The last segment is the name.
 *
 * Refused, and said, where the block could not be what the rows ask for: an id
 * with no name in it, a name the model already gives to a block or a
 * sub-system, or a reserved word -- a parameter called after `exp`, or after
 * the compartment it was meant to describe, is a model that will not build --
 * and rows that would write nothing into it. Refused before anything is made,
 * so a refusal leaves no half-made block behind and is not counted as one.
 */
function make(project, id, list, out) {
	const raw = id.split('.').filter(Boolean);
	if (!raw.length) {
		out.say('problems', id, 'could not be created — there is no name in it');
		return null;
	}
	const parts = raw.map(legalName);
	const name = parts[parts.length - 1];
	const system = parts.slice(0, -1).join('.');
	const timed = list.filter((r) => present(r.time));
	// What would be written, first: a table with no point it could hold, or a
	// value that is a word the model cannot evaluate, is nothing worth making.
	if (timed.length) {
		const { why } = tablePoints(timed);
		if (why) {
			out.say('problems', id, why);
			return null;
		}
	} else if (unwritable(project, list[0])) {
		out.say('problems', id, `'${list[0].value}' is not a number, so there is nothing `
			+ 'here to make a parameter out of');
		return null;
	}
	const clash = ed.validateName(project, name, { system });
	if (clash) {
		out.say('problems', id, `could not be created — ${clash}`);
		return null;
	}
	try {
		// The sub-systems on the way, first: a block's `system` names a path
		// that has to exist, and a file whose ids are four deep describes
		// three sub-systems nobody has declared.
		const known = new Set(ed.systems(project));
		for (let k = 1; k <= parts.length - 1; k++) {
			const path = parts.slice(0, k).join('.');
			if (known.has(path)) continue;
			ed.addSystem(project, { name: parts[k - 1], parent: parts.slice(0, k - 1).join('.') });
			known.add(path);
		}
		const block = timed.length
			? ed.addLookup(project, { name, system })
			: ed.addParameter(project, { name, system });
		const made = block?.block ?? block;
		if (!made) throw new DataTableError('nothing was made');
		// A created block carries no index lists, so the id reads back whole.
		made.index_lists = [];
		if (list[0]?.unit) made.unit = list[0].unit;
		// Segments a created block could not keep, said once it is made.
		raw.forEach((was, i) => {
			if (was !== parts[i]) out.renamed.set(was, parts[i]);
		});
		out.created += 1;
		return { block: made, kind: timed.length ? 'lookup' : 'parameter', name: id, index: {}, extra: [] };
	} catch (e) {
		out.say('problems', id, `could not be created — ${e.message}`);
		return null;
	}
}

/**
 * Sets a parameter's value and distribution at one index.
 *
 * A row's unit is its block's, whichever index the row is for: a block has one
 * unit, and every row of it in a file carries that one. Only the block's own
 * row used to set it here, while a table's rows set it at any index -- two
 * rules for what is one case.
 */
function writeValue(project, hit, row, out, id) {
	const { block, index } = hit;
	const has = Object.keys(index).length > 0;
	const set = (key, value) => {
		if (has) ed.setEntryValue(project, qualifiedName(block), index, key, value);
		else block[key] = value;
	};
	const clear = (key) => {
		if (has) ed.clearEntryValue(project, qualifiedName(block), index, key);
		else delete block[key];
	};
	try {
		// Blank is no value, whatever held it.
		const given = typeof row.value === 'string' && row.value.trim() === '' ? null : row.value;
		// A value has to be a number or an expression the model can evaluate.
		// A data set may hold neither -- a word naming a class of something,
		// say -- and writing it into a parameter makes a model that will not
		// build. Said rather than written.
		if (unwritable(project, row)) {
			out.say('problems', id,
				`'${row.value}' is not a number and names no block — the value was left alone`);
		} else if (given != null) { set('value', String(given)); out.values += 1; }
		if (row.unit) block.unit = row.unit;
		if (row.pdf === undefined) return;
		if (row.pdf && usable(row.pdf)) {
			const spec = held(row.pdf);
			set('pdf', spec);
			out.pdfs += 1;
			countSample(spec, out);
		} else if (row.pdf === null) clear('pdf');
		else if (row.pdf) {
			out.say('problems', id, Object.hasOwn(PDF_KINDS, row.pdf.kind ?? '')
				? 'the distribution is not filled in — it was left alone'
				: `'${row.pdf.kind}' is not a kind of distribution — it was left alone`);
		}
	} catch (e) {
		out.say('problems', id, e.message);
	}
}

/**
 * A table's points from its rows, or why there are none: every row with both
 * a time and a value, and no two at one time. A table is strictly increasing,
 * and two rows at one time is a mistake in the file rather than a table with a
 * step in it.
 */
function tablePoints(rows) {
	const points = rows
		.filter((r) => present(r.time) && present(r.value))
		.map((r) => (r.pdf ? [r.time, r.value, held(r.pdf)] : [r.time, r.value]));
	if (!points.length) return { why: 'no point in the file has both a time and a value' };
	for (let i = 1; i < points.length; i++) {
		if (points[i][0] === points[i - 1][0]) return { why: `two rows are both at time ${points[i][0]}` };
	}
	return { points };
}

/** Replaces a lookup table's points. */
function writeTable(project, hit, rows, out, id) {
	const { block, index } = hit;
	const { points, why } = tablePoints(rows);
	if (why) {
		out.say('problems', id, why);
		return;
	}
	try {
		if (Object.keys(index).length) {
			ed.setEntryValue(project, qualifiedName(block), index, 'points', points);
		} else {
			block.points = points;
		}
		if (rows[0]?.unit) block.unit = rows[0].unit;
		out.tables += 1;
		// A point's own spread counts as a distribution read: it is one, and a
		// report that said "34 tables, 0 distributions" of a file with
		// sixty-eight of them would be telling the reader the wrong thing.
		out.pdfs += points.filter((pt) => pt.length > 2).length;
		for (const pt of points) if (pt.length > 2) countSample(pt[2], out);
	} catch (e) {
		out.say('problems', id, e.message);
	}
}

/** What an import did, in one paragraph. */
export function describe(rep) {
	if (!rep) return '';
	const bits = [];
	if (rep.values) bits.push(`${rep.values.toLocaleString()} value${rep.values === 1 ? '' : 's'}`);
	if (rep.tables) bits.push(`${rep.tables.toLocaleString()} lookup table${rep.tables === 1 ? '' : 's'}`);
	// A sample is a distribution as far as the model is concerned, so the two
	// are not added together -- the sample line says how many of them were
	// lists of numbers, and how many numbers that came to.
	if (rep.pdfs) bits.push(`${rep.pdfs.toLocaleString()} distribution${rep.pdfs === 1 ? '' : 's'}`);
	if (rep.samples) {
		bits.push(`${rep.samples.toLocaleString()} of them raw samples `
			+ `(${rep.sampleValues.toLocaleString()} values)`);
	}
	if (rep.created) bits.push(`${rep.created.toLocaleString()} block${rep.created === 1 ? '' : 's'} created`);
	const head = bits.length ? bits.join(', ') : 'nothing';
	const left = rep.unmatched.length
		? ` ${rep.unmatched.length.toLocaleString()} id${rep.unmatched.length === 1 ? '' : 's'} `
			+ 'matched nothing in this model.'
		: '';
	const bad = rep.problems.length
		? ` ${rep.problems.length.toLocaleString()} could not be used.`
		: '';
	const renamed = rep.renamed?.size
		? ` ${rep.renamed.size} name${rep.renamed.size === 1 ? '' : 's'} could not be kept as `
			+ `written (${[...rep.renamed].slice(0, 3).map(([a, b]) => `${a} → ${b}`).join(', ')}`
			+ `${rep.renamed.size > 3 ? ', …' : ''}).`
		: '';
	return `Read ${head}.${left}${bad}${renamed}`;
}
