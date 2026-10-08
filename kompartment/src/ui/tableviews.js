/**
 * The Table tab's three shapes, as rules that can be tested without a page.
 *
 *   over time  a row per output time, a column per series -- or a row per
 *              time asked for, read off each curve there;
 *   peaks      a row per series: its largest value, when it got there, what
 *              it adds up to over the run, and its value at the times asked
 *              for -- the numbers an assessment quotes;
 *   pivot      one index list down the side and another -- or the blocks --
 *              across the top, each cell one number of the series there.
 *
 * A pivot cell can stand for several series: the picked series that differ
 * only in a list that is neither down the side nor across the top. Those are
 * added before the number is taken, since the peak of a sum is the number a
 * reader of the cell means, and the sum of the peaks is not.
 */

import { reduce, valueAt, integral } from '../domain/derived.js';

/** What each cell of a peaks row or a pivot can be. */
export const CELL_VALUES = ['peak', 'time_of_peak', 'integral', 'at'];

/**
 * A curve read at the times asked for: interpolated between output points and
 * held flat outside the run, as a derived `at_time` reads one.
 */
export function valuesAt(t, values, times) {
	const n = Math.min(t?.length ?? 0, values?.length ?? 0);
	return times.map((at) => valueAt(t, values, n, at));
}

/**
 * The numbers of one series, for a row of the peaks table.
 *
 * @returns {{peak: number, at: number, total: number, values: number[]}}
 */
export function peakRow(t, values, times = []) {
	const run = integral(t, values);
	return {
		peak: reduce('max', t, values),
		at: reduce('time_of_max', t, values),
		total: run.length ? run[run.length - 1] : NaN,
		values: valuesAt(t, values, times),
	};
}

/** One number of a curve: what a pivot's cells show. */
export function cellValue(kind, t, values, at = NaN) {
	if (kind === 'time_of_peak') return reduce('time_of_max', t, values);
	if (kind === 'integral') {
		const run = integral(t, values);
		return run.length ? run[run.length - 1] : NaN;
	}
	if (kind === 'at') {
		const n = Math.min(t?.length ?? 0, values?.length ?? 0);
		return valueAt(t, values, n, at);
	}
	return reduce('max', t, values);
}

/**
 * The lists the picked series are indexed by, in the order they come, and
 * whether there is more than one block: the choices a pivot can offer for its
 * rows and its columns.
 */
export function pivotChoices(outputs, selected) {
	const lists = [];
	const blocks = new Set();
	for (const i of selected) {
		const o = outputs[i];
		if (!o) continue;
		blocks.add(o.block ?? o.label);
		for (const d of o.dims ?? []) if (!lists.includes(d)) lists.push(d);
	}
	return { lists, blocks: [...blocks] };
}

/**
 * Which series each cell of a pivot adds up.
 *
 * `rows` is a list; `cols` a list or `'block'`. A series not indexed by the
 * list a side asks for has no row or column there and is counted as left out
 * rather than put somewhere it does not belong.
 *
 * @returns {{rowKeys: string[], colKeys: string[], cells: Map<string, number[]>,
 *   summed: string[], left: number, units: Map<string, string>}}
 *   `cells` is keyed `row \u0001 column`; `summed` names the lists a cell adds
 *   over; `units` is each column's unit, or '' where its series disagree
 */
export function pivotCells(outputs, selected, { rows, cols }) {
	const rowKeys = [];
	const colKeys = [];
	const cells = new Map();
	const summed = new Set();
	const units = new Map();
	let left = 0;
	for (const i of selected) {
		const o = outputs[i];
		if (!o) continue;
		const dims = o.dims ?? [];
		const r = dims.indexOf(rows);
		const c = cols === 'block' ? -2 : dims.indexOf(cols);
		if (r < 0 || c === -1) { left++; continue; }
		const rk = o.index[r];
		const ck = cols === 'block' ? (o.block ?? o.label) : o.index[c];
		if (!rowKeys.includes(rk)) rowKeys.push(rk);
		if (!colKeys.includes(ck)) colKeys.push(ck);
		dims.forEach((d, k) => { if (k !== r && k !== c) summed.add(d); });
		const key = `${rk}\u0001${ck}`;
		if (!cells.has(key)) cells.set(key, []);
		cells.get(key).push(i);
		const unit = o.unit ?? '';
		if (!units.has(ck)) units.set(ck, unit);
		else if (units.get(ck) !== unit) units.set(ck, '');
	}
	return { rowKeys, colKeys, cells, summed: [...summed], left, units };
}

/**
 * Rows of text as tab-separated lines, which is what a spreadsheet takes from
 * the clipboard: a tab or a line break inside a cell would start a new cell or
 * row, so they become spaces.
 *
 * @param {Array<Array<string|number>>} rows
 */
export function toTSV(rows) {
	return rows.map((row) => row.map((cell) => {
		if (typeof cell === 'number') return Number.isFinite(cell) ? String(cell) : '';
		return String(cell ?? '').replace(/[\t\r\n]+/g, ' ');
	}).join('\t')).join('\n');
}
