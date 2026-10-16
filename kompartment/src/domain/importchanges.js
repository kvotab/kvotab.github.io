/**
 * What a data import would change, id by id.
 *
 * The import dialog runs the import against a copy of the model before it
 * runs it for real (see ../ui/dataimport.js). This reads that copy against
 * the model it was made from -- read off the dry run rather than worked out
 * beside it, because an account of an import computed apart from the import
 * is a second implementation, and it is the second one that goes wrong.
 *
 * Each id the file names is looked up in both models the way `apply` looks it
 * up, and everything `apply` writes is compared: the value, the distribution,
 * the block's unit and a lookup table's points. So an id the file holds just
 * as the model does is `same`, and not worth a line in a list of what to
 * import; one the model has no block for is `unmatched`, or `created` where
 * the import was told to make what is missing.
 */

import { resolve } from './datatable.js';
import * as ed from './edit.js';
import { parsePDF, formatPDF } from './pdf.js';

/** What `apply` writes into a block, in the order a change is told. */
const FIELDS = ['value', 'distribution', 'unit', 'points'];

const specOf = (raw) => (!raw ? null : typeof raw === 'string' ? parsePDF(raw) : raw);

/** A block as `apply` leaves it, at the index an id names. */
function stateOf({ block, index }) {
	return {
		value: ed.effectiveValue(block, 'value', index) ?? null,
		distribution: specOf(ed.effectiveValue(block, 'pdf', index)),
		unit: block.unit ?? '',
		points: ed.effectiveValue(block, 'points', index) ?? null,
	};
}

/** What a block the import makes was before it: nothing. */
const NOTHING = { value: null, distribution: null, unit: '', points: null };

const blank = (v) => v == null || String(v).trim() === '';

/** A number where the text is one: `0.00002` and `2e-5` are one value. */
function number(v) {
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	const n = Number(String(v).trim());
	return Number.isFinite(n) ? n : null;
}

/**
 * The same value, whichever way it is written. A file's `2e-5` lands as the
 * text `0.00002`, and a model holds `1e-05` as a number: what is compared is
 * the number where both are one, and the text where either is an expression.
 */
function sameValue(a, b) {
	if (blank(a) || blank(b)) return blank(a) && blank(b);
	const x = number(a);
	const y = number(b);
	return x != null && y != null ? x === y : String(a).trim() === String(b).trim();
}

/** A distribution as the model file writes it, which is what two are compared by. */
const pdfText = (s) => (s ? formatPDF(s) : '');
const samePdf = (a, b) => pdfText(a) === pdfText(b);

const samePoint = (p, q) => sameValue(p[0], q[0]) && sameValue(p[1], q[1])
	&& samePdf(specOf(p[2]), specOf(q[2]));

function samePoints(a, b) {
	if (!a || !b) return !a && !b;
	return a.length === b.length && a.every((p, i) => samePoint(p, b[i]));
}

const SAME = {
	value: sameValue,
	distribution: samePdf,
	unit: (a, b) => a === b,
	points: samePoints,
};

/**
 * Every id `rows` names, and what importing them would do to it.
 *
 * @param {object} project  the model as it is
 * @param {object} trial    a copy of it that `apply` has written `rows` into
 * @param {Array<object>} rows
 * @returns {Map<string, {status: 'changed'|'same'|'created'|'unmatched',
 *   fields: Array<{field: string, before: *, after: *}>}>} in the file's order
 */
export function changes(project, trial, rows) {
	const out = new Map();
	for (const r of rows) {
		const id = r?.id;
		if (!id || out.has(id)) continue;
		const was = resolve(project, id);
		const now = resolve(trial, id);
		if (!now) {
			out.set(id, { status: 'unmatched', fields: [] });
			continue;
		}
		const before = was ? stateOf(was) : NOTHING;
		const after = stateOf(now);
		const fields = FIELDS.filter((f) => !SAME[f](before[f], after[f]))
			.map((field) => ({ field, before: before[field], after: after[field] }));
		out.set(id, { status: !was ? 'created' : fields.length ? 'changed' : 'same', fields });
	}
	return out;
}

const shown = (v) => (blank(v) ? '—' : String(v));
const many = (n) => n.toLocaleString();
const listOf = (s) => (s?.kind === 'pg' ? s.values ?? [] : null);

/** A distribution in a few words: a list of values by how many, any other written out. */
const pdfShort = (s) => (!s ? 'none'
	: s.kind === 'pg' ? `a list of ${many(s.values?.length ?? 0)} values` : formatPDF(s));

/** How a list hands its values out, without the values: `pg(inorder=true,pos=0)`. */
const listSettings = (s) => formatPDF({ ...s, values: [] }).replace('values=,', '');

function pdfLine(a, b) {
	const la = listOf(a);
	const lb = listOf(b);
	if (la && lb && la.length === lb.length) {
		const differ = la.filter((v, i) => !sameValue(v, lb[i])).length;
		if (differ) {
			return `a list of ${many(la.length)} values, `
				+ `${differ === la.length ? 'every one' : many(differ)} changed`;
		}
		// The numbers are the ones the model has; what moved is how they are
		// handed out.
		return `the same ${many(la.length)} values, ${listSettings(a)} → ${listSettings(b)}`;
	}
	if (la && lb) return `a list of ${many(la.length)} values → ${many(lb.length)}`;
	return `${pdfShort(a)} → ${pdfShort(b)}`;
}

function pointsLine(a, b) {
	const count = (p) => (p ? `${many(p.length)} points` : 'none');
	if (!a || !b || a.length !== b.length) return `${count(a)} → ${count(b)}`;
	const differ = a.filter((p, i) => !samePoint(p, b[i])).length;
	return `${count(a)}, ${differ === a.length ? 'every one' : many(differ)} changed`;
}

/**
 * An id's change as lines a reader takes in at a glance: `value 0.00001 →
 * 0.00002`, a distribution written out, a list of values by how many of them
 * changed -- seven thousand numbers either side of an arrow is not a
 * difference anybody can read.
 */
export function changeLines(entry) {
	return (entry?.fields ?? []).map(({ field, before, after }) => {
		if (field === 'value') return `value ${shown(before)} → ${shown(after)}`;
		if (field === 'unit') return `unit ${shown(before)} → ${shown(after)}`;
		if (field === 'distribution') return `distribution ${pdfLine(before, after)}`;
		return `table ${pointsLine(before, after)}`;
	});
}
