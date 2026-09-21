/**
 * What a data file would do to this model, before it does it.
 *
 * An import of 1,758 rows that quietly lands 1,200 of them is worse than one
 * that refuses: the twelve hundred are indistinguishable from the model as it
 * was, and nothing on screen says which of the numbers in front of a reader
 * came from the file. So the dialog is the whole feature. It runs the import
 * against a *copy* of the model, reports what that came to, and only then
 * offers to do it for real.
 *
 * **The dry run is the same code path**, not a description of it: `apply` on a
 * clone, with the same options the button will use. A preview that is worked
 * out separately from the thing it previews is a second implementation, and it
 * is the second one that goes wrong.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import * as dt from '../domain/datatable.js';
import { renderPicker, pickerState } from './pick.js';

/**
 * @param {object} opts
 * @param {string} opts.name       the file's name, for the title
 * @param {Array<object>} opts.rows
 * @param {string[]} opts.problems what the reader could not make sense of
 * @param {object} opts.project    the model, read for the dry run
 * @param {(opts: {create: boolean}) => void} opts.onApply
 */
export function openDataImport({ name, rows, problems = [], project, onApply }) {
	let create = false;
	const ids = new Set(rows.map((r) => r.id));
	// One row per *id*, since that is what a reader picks: a lookup table is
	// several rows of one thing, and ticking its points one at a time is not a
	// question anybody wants asked.
	const byId = new Map();
	for (const r of rows) {
		const found = byId.get(r.id);
		if (found) { found.count += 1; continue; }
		byId.set(r.id, {
			key: r.id, name: r.id, unit: r.unit ?? '',
			kind: r.time != null ? 'lookup table' : (r.pdf?.kind === 'pg' ? 'sample' : 'value'),
			count: 1,
			system: r.id.includes('.') ? r.id.slice(0, r.id.lastIndexOf('.')) : '',
		});
	}
	const items = [...byId.values()];
	const chosen = new Set(items.map((i) => i.key));
	const ui = pickerState();
	const timed = new Set(rows.filter((r) => r.time != null).map((r) => r.id));
	const withPdf = rows.filter((r) => r.pdf).length;
	// A raw sample is a different kind of thing to import: it is not a shape
	// with two numbers, it is every realisation, and a file of them is tens of
	// millions of values. Said before anybody presses anything.
	const samples = rows.filter((r) => r.pdf?.kind === 'pg' && r.pdf.values?.length);
	const sampleValues = samples.reduce((n, r) => n + r.pdf.values.length, 0);

	let handle = null;
	const shut = () => handle?.close();
	handle = openModal({
		title: `Import data from ${name}`,
		wide: true,
		build(body) {
			body.replaceChildren();

			// --- what is in the file, before anything is decided.
			body.append(el('p', {},
				el('b', {}, `${rows.length.toLocaleString()} rows`),
				` — ${ids.size.toLocaleString()} ids, of which `
				+ `${timed.size.toLocaleString()} are lookup tables. `
				+ `${withPdf.toLocaleString()} rows carry a distribution.`));

			if (samples.length) {
				body.append(el('p', {},
					el('b', {}, `${samples.length.toLocaleString()} of those are raw samples`),
					` — ${sampleValues.toLocaleString()} values, `
					+ `${Math.round(sampleValues / Math.max(1, samples.length)).toLocaleString()} `
					+ 'per row. Not a shape fitted to a sample but the sample itself, handed out '
					+ 'one value per realisation, in order — which is what makes a run '
					+ 'reproduce the one these came from.'));
				body.append(el('p', { className: 'hint' },
					'Only the rows that match land, so what this costs is what you keep. A '
					+ 'whole file of them is worth importing into a model that wants the '
					+ 'whole file.'));
			}
			for (const line of problems.slice(0, 6)) {
				body.append(el('p', { className: 'prob-warn' }, line));
			}
			if (problems.length > 6) {
				body.append(el('p', { className: 'hint' },
					`and ${problems.length - 6} more the reader could not make sense of.`));
			}

			// --- the one choice, and what it costs.
			const box = el('input', { type: 'checkbox', id: 'di-create' });
			box.checked = create;
			box.addEventListener('change', () => { create = box.checked; handle?.refresh(); });
			body.append(el('div', { className: 'field' },
				el('label', { htmlFor: 'di-create' }, 'Create what is missing'),
				box));
			body.append(el('p', { className: 'hint' },
				create
					? 'An id nothing matches becomes a new block: the last segment is its '
						+ 'name and the rest are sub-systems. With no block to ask, there is '
						+ 'no way to tell a name from an index, so every segment is taken as '
						+ 'part of the name.'
					: 'An id nothing matches is listed below and left alone. Matching asks '
						+ 'the model, so the longest prefix that is a block is the block and '
						+ 'the rest are its indices.'));

			// --- which of them ---------------------------------------------
			const box2 = el('div', { className: 'save-pick' });
			renderPicker(box2, {
				items, chosen, ui, onChange: () => handle?.refresh(), noun: 'id',
			});
			body.append(box2);

			// --- the dry run: the real thing, against a copy.
			const take = chosen.size === items.length ? rows : rows.filter((r) => chosen.has(r.id));
			const trial = structuredClone(project);
			const rep = dt.apply(trial, take, { create });
			body.append(el('p', { className: 'pdf-summary mono' }, dt.describe(rep)));

			const listing = (title, lines) => {
				if (!lines.length) return;
				const d = el('details', { className: 'prob-plan' });
				d.append(el('summary', {}, `${title} (${lines.length.toLocaleString()})`));
				const box2 = el('div', { className: 'prob-lines mono' });
				for (const line of lines.slice(0, 200)) {
					box2.append(el('div', { className: 'prob-more' }, line));
				}
				if (lines.length > 200) {
					box2.append(el('div', { className: 'prob-more' },
						`and ${(lines.length - 200).toLocaleString()} more`));
				}
				d.append(box2);
				body.append(d);
			};
			listing('Matched nothing in this model', rep.unmatched);
			listing('Could not be used', rep.problems);

			const go = el('button', { type: 'button', className: 'primary' }, 'Import');
			go.disabled = !(rep.values || rep.tables || rep.pdfs || rep.created);
			go.addEventListener('click', () => {
				shut();
				onApply({ create, keys: chosen.size === items.length ? null : [...chosen] });
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => shut());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'One undo step, so it can be taken back.'),
				cancel, go));
		},
	});
	return handle;
}
