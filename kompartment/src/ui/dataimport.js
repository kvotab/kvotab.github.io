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
 *
 * **Only what would change is listed.** A data set holds every parameter, and a
 * model it was made for already holds most of them as written: 955 ids of
 * which 127 change anything is a list of 127, each with what the model has
 * now and what the file would put there. The rest are counted and left out,
 * and an id that matches nothing in the model has a list of its own -- it
 * used to sit in the one list with the others, under a line about ids that
 * match nothing, and read as though every id had failed to.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import * as dt from '../domain/datatable.js';
import { changes, changeLines } from '../domain/importchanges.js';
import { renderPicker, pickerState } from './pick.js';
import { dialogInfo } from './dialoginfo.js';

const many = (n) => n.toLocaleString();

/**
 * @param {object} opts
 * @param {string} opts.name       the file's name, for the title
 * @param {Array<object>} opts.rows
 * @param {string[]} opts.problems what the reader could not make sense of
 * @param {object} opts.project    the model, read for the dry run
 * @param {(opts: {create: boolean, keys: string[]}) => void} opts.onApply
 *   `keys` the ids to import: those ticked, all of them ones that change something
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
	const ui = pickerState();
	const timed = new Set(rows.filter((r) => r.time != null).map((r) => r.id));
	const withPdf = rows.filter((r) => r.pdf).length;
	// A raw sample is a different kind of thing to import: it is not a shape
	// with two numbers, it is every realisation, and a file of them is tens of
	// millions of values. Said before anybody presses anything.
	const samples = rows.filter((r) => r.pdf?.kind === 'pg' && r.pdf.values?.length);
	const sampleValues = samples.reduce((n, r) => n + r.pdf.values.length, 0);

	// The whole file against the model, once for each answer to *Create what
	// is missing*: which ids are worth a line depends on that answer and on
	// nothing else. Not on what is ticked -- an id unticked would otherwise
	// change nothing in the run of what is ticked, and leave the list.
	const runs = new Map();
	const whole = () => {
		if (!runs.has(create)) {
			const trial = structuredClone(project);
			const rep = dt.apply(trial, rows, { create });
			runs.set(create, { rep, of: changes(project, trial, rows) });
		}
		return runs.get(create);
	};
	// Ticked to begin with: everything that would change, and what would be
	// made once that is asked for -- each the first time its answer is given,
	// so an untick outlasts the box being ticked and unticked again.
	const chosen = new Set();
	const seeded = new Set();
	const seed = (run) => {
		if (seeded.has(create)) return;
		seeded.add(create);
		for (const [id, c] of run.of) if (c.status === (create ? 'created' : 'changed')) chosen.add(id);
	};

	let handle = null;
	const shut = () => handle?.close();
	handle = openModal({
		info: dialogInfo('data-import'),
		title: `Import data from ${name}`,
		wide: true,
		build(body) {
			body.replaceChildren();
			const run = whole();
			seed(run);
			const count = { changed: 0, same: 0, created: 0, unmatched: 0 };
			for (const c of run.of.values()) count[c.status] += 1;

			// --- what is in the file, before anything is decided.
			body.append(el('p', {},
				el('b', {}, `${many(rows.length)} rows`),
				` — ${many(ids.size)} ids, of which `
				+ `${many(timed.size)} are lookup tables. `
				+ `${many(withPdf)} rows carry a distribution.`));

			if (samples.length) {
				body.append(el('p', {},
					el('b', {}, `${many(samples.length)} of those are raw samples`),
					` — ${many(sampleValues)} values, `
					+ `${many(Math.round(sampleValues / Math.max(1, samples.length)))} `
					+ 'per row. Not a shape fitted to a sample but the sample itself, handed out '
					+ 'one value per realisation, in order — which is what makes a run '
					+ 'reproduce the one these came from.'));
			}
			for (const line of problems.slice(0, 6)) {
				body.append(el('p', { className: 'prob-warn' }, line));
			}
			if (problems.length > 6) {
				body.append(el('p', { className: 'hint' },
					`and ${problems.length - 6} more the reader could not make sense of.`));
			}

			// --- what it would change in this model.
			const listed = count.changed + count.created;
			const left = [];
			if (count.same) {
				left.push(`${many(count.same)} ${count.same === 1 ? 'is' : 'are'} as the model `
					+ `already has ${count.same === 1 ? 'it' : 'them'} and ${count.same === 1 ? 'is' : 'are'} not listed`);
			}
			if (count.unmatched) {
				left.push(`${many(count.unmatched)} ${count.unmatched === 1 ? 'matches' : 'match'} `
					+ 'nothing in it — see the end');
			}
			body.append(el('p', { className: 'di-verdict' },
				el('b', {}, count.changed
					? `${many(count.changed)} of the ${many(ids.size)} ids would change this model`
					: `None of the ${many(ids.size)} ids would change this model`),
				count.created ? `, and ${many(count.created)} would be made` : '',
				left.length ? ` — ${left.join('; ')}.` : '.'));

			// The one choice, offered only where it decides something: an id
			// nothing matches is left alone unless it is asked for.
			if (count.unmatched || count.created) {
				const box = el('input', { type: 'checkbox' });
				box.checked = create;
				box.addEventListener('change', () => { create = box.checked; handle?.refresh(); });
				body.append(el('label', { className: 'di-create' }, box, 'Create what is missing'));
				body.append(el('p', { className: 'hint' },
					create
						? 'An id nothing matches becomes a new block: the last segment is its '
							+ 'name and the rest are sub-systems. With no block to ask, there is '
							+ 'no way to tell a name from an index, so every segment is taken as '
							+ 'part of the name.'
						: 'Matching asks the model, so the longest prefix that is a block is the '
							+ 'block and the rest are its indices.'));
			}

			// --- which of them, each with what it would change -------------
			const items = [...byId.values()]
				.filter((it) => ['changed', 'created'].includes(run.of.get(it.key)?.status))
				.map((it) => {
					const c = run.of.get(it.key);
					return {
						...it,
						detail: [c.status === 'created' ? 'a new block' : null, ...changeLines(c)]
							.filter(Boolean).join('\n'),
					};
				});
			const keys = () => items.map((it) => it.key).filter((k) => chosen.has(k));
			// The dry run of what is ticked: the real thing, against a copy.
			const trialOf = (picked) => {
				const want = new Set(picked);
				const trial = structuredClone(project);
				return dt.apply(trial, rows.filter((r) => want.has(r.id)), { create });
			};
			const summary = el('p', { className: 'pdf-summary mono' });
			const go = el('button', { type: 'button', className: 'primary' }, 'Import');
			const recount = () => {
				const picked = keys();
				const rep = picked.length ? trialOf(picked) : null;
				summary.textContent = rep ? dt.describe(rep) : 'Nothing is ticked.';
				go.disabled = !rep || !(rep.values || rep.tables || rep.pdfs || rep.created);
			};
			if (listed) {
				const box2 = el('div', { className: 'save-pick' });
				renderPicker(box2, {
					items, chosen, ui, noun: 'id',
					onChange: () => handle?.refresh(),
					// A tick changes what would land, and the line saying so.
					onTick: recount,
				});
				body.append(box2);
			}
			recount();
			body.append(summary);

			const listing = (title, lines) => {
				if (!lines.length) return;
				const d = el('details', { className: 'prob-plan' });
				d.append(el('summary', {}, `${title} (${many(lines.length)})`));
				const box3 = el('div', { className: 'prob-lines mono' });
				for (const line of lines.slice(0, 200)) {
					box3.append(el('div', { className: 'prob-more' }, line));
				}
				if (lines.length > 200) {
					box3.append(el('div', { className: 'prob-more' },
						`and ${many(lines.length - 200)} more`));
				}
				d.append(box3);
				body.append(d);
			};
			// Of the whole file, whatever is ticked: these are not in the list
			// above, and each says why.
			listing('Match nothing in this model, and are left alone', run.rep.unmatched);
			listing('Could not be used', run.rep.problems);

			go.addEventListener('click', () => {
				shut();
				onApply({ create, keys: keys() });
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
