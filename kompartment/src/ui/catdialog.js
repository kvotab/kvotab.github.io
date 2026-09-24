/**
 * Sorting realisations into categories, and choosing which to show.
 *
 * See ../domain/categories.js for what a category is. This is the editor: a
 * row per category with its label, the series and statistic it reads, the
 * comparison, and whether it is *included* in what the charts and tables
 * show. The categories are the model's -- they are saved with it, as the
 * realisation count and the seed are -- and once a run stands they are applied
 * to it at once, so the counts beside each row are live.
 *
 * Order matters and is editable: a realisation goes in the first category it
 * meets, so "peak above 1" over "peak above 0.1" sorts the worst cases out
 * before the bad ones, and the other order never fills the first row.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { fmtTime } from '../domain/timeseries.js';
import { STATS, STAT_LABEL, OPS, categoryProblems } from '../domain/categories.js';
import { dialogInfo } from './dialoginfo.js';

/**
 * @param {object} opts
 * @param {Array} opts.categories   as `categoriesOf` reads them
 * @param {string[]} opts.outputs   the series a run kept, or the model's outputs
 * @param {Float64Array|number[]} opts.t  the output times, for 'value at a time'
 * @param {string} opts.timeUnit
 * @param {object|null} opts.screen  `{counts, kept, missing}` from the worker
 * @param {number} opts.iterations
 * @param {(categories: Array) => void} opts.onChange  every edit, to save and re-sort
 * @param {() => void} [opts.onClose]
 */
export function openCategoriesDialog({
	categories, outputs = [], t = [], timeUnit = 'year', screen = null, iterations = 0,
	onChange, onClose,
}) {
	let cats = categories.map((c) => ({ ...c }));
	let view = { screen, iterations };

	const changed = () => { onChange?.(cats.map((c) => ({ ...c }))); modal.refresh(); };

	const modal = openModal({
		info: dialogInfo('categories'),
		wide: true,
		title: 'Categories of realisation',
		subtitle: 'Sort the realisations by what they did, then show only the ones you mean',
		onClose,
		build: (body) => {
			const problems = categoryProblems(cats, outputs.length ? outputs : null);
			const counts = view.screen?.counts ?? null;

			const list = el('div', { className: 'cat-list' });
			cats.forEach((c, i) => {
				const row = el('div', { className: `cat-row${c.include ? '' : ' is-out'}` });
				const inc = el('input', { type: 'checkbox', checked: c.include,
					title: 'Included in what the charts, tables and analyses show. Untick to screen '
						+ 'these realisations out.' });
				inc.addEventListener('change', () => { c.include = inc.checked; changed(); });
				const label = el('input', { type: 'text', className: 'cat-label', value: c.label,
					placeholder: 'label' });
				label.addEventListener('change', () => { c.label = label.value.trim() || `Category ${i + 1}`; changed(); });
				const out = el('select', { className: 'cat-output' });
				if (!outputs.includes(c.output)) out.append(el('option', { value: c.output, selected: true }, c.output || '— series —'));
				for (const o of outputs.slice(0, 300)) out.append(el('option', { value: o, selected: o === c.output }, o));
				out.addEventListener('change', () => { c.output = out.value; changed(); });
				const stat = el('select', { className: 'cat-stat' });
				for (const s2 of STATS) stat.append(el('option', { value: s2, selected: s2 === c.stat }, STAT_LABEL[s2]));
				stat.addEventListener('change', () => { c.stat = stat.value; changed(); });
				const when = el('select', { className: 'cat-at', hidden: c.stat !== 'at' });
				for (let j = 0; j < t.length; j++) {
					when.append(el('option', { value: String(j), selected: j === c.at }, `${fmtTime(t[j])} ${timeUnit}`));
				}
				when.addEventListener('change', () => { c.at = Number(when.value); changed(); });
				const op = el('select', { className: 'cat-op' });
				for (const o of OPS) op.append(el('option', { value: o, selected: o === c.op }, o));
				op.addEventListener('change', () => { c.op = op.value; changed(); });
				const v1 = el('input', { type: 'text', className: 'mono cat-value', value: Number.isFinite(c.value) ? String(c.value) : '' });
				v1.addEventListener('change', () => { c.value = Number(v1.value); changed(); });
				const v2 = el('input', { type: 'text', className: 'mono cat-value', hidden: c.op !== 'between',
					value: Number.isFinite(c.value2) ? String(c.value2) : '' });
				v2.addEventListener('change', () => { c.value2 = Number(v2.value); changed(); });
				const count = el('span', { className: 'cat-count mono' },
					counts ? `${counts[i].toLocaleString()}${view.iterations ? ` (${((100 * counts[i]) / view.iterations).toFixed(1)}%)` : ''}` : '');
				const up = el('button', { type: 'button', className: 'ghost icon', title: 'Earlier: sorted into before the rows below', disabled: i === 0 }, '▲');
				up.addEventListener('click', () => { [cats[i - 1], cats[i]] = [cats[i], cats[i - 1]]; changed(); });
				const down = el('button', { type: 'button', className: 'ghost icon', title: 'Later', disabled: i === cats.length - 1 }, '▼');
				down.addEventListener('click', () => { [cats[i + 1], cats[i]] = [cats[i], cats[i + 1]]; changed(); });
				const del = el('button', { type: 'button', className: 'ghost icon', title: 'Remove this category' }, '×');
				del.addEventListener('click', () => { cats.splice(i, 1); changed(); });
				row.append(inc, label, out, stat, when, op, v1, v2, count, up, down, del);
				list.append(row);
			});
			// Other: what meets none of them. Always included.
			list.append(el('div', { className: 'cat-row cat-other' },
				el('span', {}, ''), el('i', {}, 'Other'),
				el('span', { className: 'cat-span' }, 'everything that meets none of the above — always shown'),
				el('span', { className: 'cat-count mono' },
					counts ? `${counts[cats.length].toLocaleString()}${view.iterations ? ` (${((100 * counts[cats.length]) / view.iterations).toFixed(1)}%)` : ''}` : '')));
			body.append(list);

			const add = el('button', { type: 'button', className: 'ghost' }, 'Add a category');
			add.addEventListener('click', () => {
				cats.push({ label: `Category ${cats.length + 1}`, output: outputs[0] ?? '', stat: 'max',
					at: 0, op: '>', value: NaN, value2: NaN, include: true });
				changed();
			});
			body.append(el('div', { className: 'pdf-row' }, add));

			for (const p of problems) body.append(el('p', { className: 'prob-warn' }, p));
			if (view.screen?.missing?.length) {
				body.append(el('p', { className: 'prob-warn' },
					`The run did not keep ${view.screen.missing.join(', ')}, so those categories are empty. `
					+ 'Run again with the series kept, or name one it did keep.'));
			}
			if (view.screen && view.iterations) {
				body.append(el('p', { className: 'prob-more' },
					`${view.screen.kept.toLocaleString()} of ${view.iterations.toLocaleString()} realisations `
					+ 'are shown; the bands, What drove it and the distribution summary are over those.'));
			} else if (!view.screen) {
				body.append(el('p', { className: 'hint' },
					'Counts appear once a probabilistic run stands. The categories are saved with the model either way.'));
			}
			body.append(el('p', { className: 'sens-note' },
				'A realisation belongs to the first row whose condition it meets, so the order '
				+ 'is part of the definition. The comparison reads one number of one series '
				+ 'per realisation: its peak, its lowest value, its value at the end, or at a time.'));

			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, 'Every change is applied at once and saved with the model.'),
				done));
		},
	});
	return {
		close: () => modal.close(),
		update(next) { view = { ...view, ...next }; modal.refresh(); },
	};
}
