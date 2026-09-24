/**
 * One room for everything this tool can write out.
 *
 * There were six ways to save and they were in four places: a button, a caret
 * menu beside it, the Table's right-click menu, and the canvas's. Each knew
 * about some of the formats and none of them let you say *which* series --
 * except the endpoint picker, which is a different question (what a run keeps)
 * wearing the same clothes.
 *
 * So: what, then how, then which. The left column is what kind of thing is
 * being written; the right is the format and, for everything that is a list of
 * named things, the list with a search over it.
 *
 * **What cannot be chosen says so rather than being missing.** A run that has
 * not happened, an archive whose model has moved on since the run, a sample
 * that is not there: each of those disables its row and puts the reason in it,
 * because "why is this greyed out" is the question a disabled control always
 * asks and almost never answers.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { renderPicker, pickerState } from './pick.js';

/**
 * What can be written, in the order a reader looks for them.
 *
 * `picks` says which list the right-hand side shows: `series` for a run's
 * outputs, `data` for the parameters and lookup tables, nothing for a whole
 * model. `needs` is what has to be true, and the dialog turns it into a
 * sentence rather than a grey row. `browser` is whether the same file can go
 * straight to the HDF5 Browser instead of the disk; it reads HDF5 and nothing
 * else, so that is the file it gets whichever format is chosen.
 */
export const KINDS = [
	{
		key: 'model',
		label: 'Model',
		blurb: 'The model on its own — blocks, equations, distributions, settings.',
		formats: [
			['json', 'JSON', 'Readable, and what every other tool takes'],
			['zip', 'ZIP', 'About a fifth of the size; double-clicks open on any desktop'],
			['gz', 'gzip', 'The same, in the form a command line makes'],
		],
	},
	{
		key: 'archive',
		label: 'Model with results',
		blurb: 'The model and the run it produced, so it opens again without the solve. '
			+ 'The ticked blocks are the model’s endpoints — what a run keeps, and what '
			+ 'an export writes — and they are saved with it.',
		// Only ZIP: a gzip holds one thing, and a run beside a model is two.
		formats: [['data', 'ZIP', 'The model at the root, the run under results/']],
		needs: 'fresh',
		picks: 'endpoints',
	},
	{
		key: 'results',
		label: 'Results',
		blurb: 'The series themselves — one row per output time.',
		formats: [
			['hdf5', 'HDF5', 'What the result browser reads'],
			['csv', 'CSV', 'One column per series, for a spreadsheet'],
		],
		needs: 'results',
		picks: 'series',
		browser: true,
	},
	{
		key: 'realisations',
		label: 'Every realisation',
		blurb: 'Not the curve through a probabilistic run but all of it: one row per '
			+ 'output time and one column per realisation.',
		formats: [['hdf5', 'HDF5', 'One matrix per series']],
		needs: 'sample',
		picks: 'series',
		browser: true,
	},
	{
		key: 'data',
		label: 'Data',
		blurb: 'Parameters and lookup tables — id, unit, value and distribution — '
			+ 'without the model around them.',
		formats: [
			['xlsx', 'Excel', 'One row per value; a lookup table is one row per point'],
			['h5', 'HDF5', 'One dataset per value, and the group path is the id'],
		],
		picks: 'data',
		browser: true,
	},
	{
		key: 'log',
		label: 'Run log',
		blurb: 'What the solver did: the settings, the timings, and what it said.',
		formats: [['txt', 'Text', 'Plain text, to paste into a report']],
		needs: 'results',
	},
];

/** Why a kind cannot be written, in a sentence, or null when it can. */
function refusal(kind, can) {
	if (kind.needs === 'results' && !can.results) return 'Nothing has run yet.';
	if (kind.needs === 'sample' && !can.sample) {
		return 'This needs a probabilistic run — Uncertainty → Probabilistic…';
	}
	if (kind.needs === 'fresh') {
		if (!can.results) return 'Nothing has run yet.';
		if (can.stale) return 'The model has changed since this run — press Run first.';
	}
	if (kind.picks === 'data' && !can.data) return 'This model has no parameters or lookup tables.';
	return null;
}

/**
 * @param {object} opts
 * @param {object} opts.can        `{results, sample, stale, data, fileName}`
 * @param {Array} opts.series      pickable result blocks
 * @param {Array} opts.data        pickable parameters and lookup tables
 * @param {string[]} opts.endpoints the model's endpoint list, pre-ticked
 * @param {object} opts.chosen     `{kind, format}` remembered between openings
 * @param {(choice) => void} opts.onSave  `{kind, format, keys, open}`; `open`
 *   is the HDF5 Browser rather than the disk, and is called from the click
 *   itself, so that the tab can be opened there
 */
export function openSaveDialog({
	can, series = [], data = [], endpoints = [], chosen = {}, onSave,
}) {
	// The first thing that can actually be written, so the dialog does not
	// open on a row it will refuse.
	const usable = KINDS.filter((k) => !refusal(k, can));
	let what = KINDS.find((k) => k.key === chosen.kind && !refusal(k, can))
		?? usable[0] ?? KINDS[0];
	let format = what.formats.some(([f]) => f === chosen.format)
		? chosen.format : what.formats[0][0];

	// One selection per list, kept while the dialog is open so switching
	// between Results and Every realisation does not lose the ticks.
	const picks = {
		series: { chosen: new Set(series.filter((s) => s.on).map((s) => s.key)), ui: pickerState() },
		// The endpoints the model already declares, or everything when it
		// declares none -- which is what a run keeps today.
		endpoints: {
			chosen: new Set(endpoints.length ? endpoints : series.map((s) => s.key)),
			ui: pickerState(),
		},
		data: { chosen: new Set(data.map((d) => d.key)), ui: pickerState() },
	};

	let handle = null;
	const shut = () => handle?.close();
	handle = openModal({
		title: 'Save',
		wide: true,
		build(body) {
			body.replaceChildren();
			const cols = el('div', { className: 'save-cols' });

			// --- what ------------------------------------------------------
			const left = el('div', { className: 'save-what' });
			for (const k of KINDS) {
				const why = refusal(k, can);
				const row = el('button', {
					type: 'button',
					className: `save-kind${k === what ? ' is-on' : ''}${why ? ' is-off' : ''}`,
					disabled: !!why,
					title: why ?? k.blurb,
				},
				el('span', { className: 'save-kind-name' }, k.label),
				el('span', { className: 'save-kind-why' }, why ?? k.blurb));
				row.addEventListener('click', () => {
					what = k;
					format = k.formats[0][0];
					handle.refresh();
				});
				left.append(row);
			}
			cols.append(left);

			// --- how, and which --------------------------------------------
			const right = el('div', { className: 'save-how' });
			right.append(el('p', { className: 'hint' }, what.blurb));

			if (what.formats.length > 1) {
				const row = el('div', { className: 'field' }, el('label', {}, 'Format'));
				const sel = el('select');
				for (const [value, label, title] of what.formats) {
					sel.append(el('option', { value, selected: value === format, title }, label));
				}
				sel.addEventListener('change', () => { format = sel.value; handle.refresh(); });
				row.append(sel);
				right.append(row);
				const why = what.formats.find(([f]) => f === format)?.[2];
				if (why) right.append(el('p', { className: 'hint' }, why));
			}

			let picked = null;
			// Declared before the picker so a tick can reach them: the buttons
			// are disabled while nothing is ticked, and a tick does not rebuild.
			const go = el('button', { type: 'button', className: 'primary' },
				what.key === 'model' && can.fileName && format === 'json'
					? `Save to ${can.fileName}` : 'Save…');
			// The same file into the reader instead of onto the disk. Beside
			// Save rather than a format of its own: it is somewhere to send the
			// file, not another kind of file.
			const open = what.browser
				? el('button', {
					type: 'button',
					className: 'ghost save-open',
					title: 'Opens the HDF5 Browser at kvotab.se in a new tab and hands it this '
						+ 'file directly, without saving it first. It reads HDF5, so that is '
						+ 'what it is sent whichever format is chosen.',
				}, 'Open in the HDF5 Browser')
				: null;
			const able = (yes) => {
				go.disabled = !yes;
				if (open) open.disabled = !yes;
			};
			if (what.picks) {
				const items = what.picks === 'data' ? data : series;
				const box = el('div', { className: 'save-pick' });
				picked = renderPicker(box, {
					items,
					chosen: picks[what.picks].chosen,
					ui: picks[what.picks].ui,
					onChange: () => handle.refresh(),
					onTick: (n) => able(!refusal(what, can) && n > 0),
					noun: 'block',
				});
				right.append(box);
				if (what.picks === 'endpoints') {
					// What ticking one actually does, since it outlives the
					// file: an endpoint list is a property of the model.
					right.append(el('p', { className: 'hint' },
						'Saved with the model, so a re-run keeps these and an export offers '
						+ 'them. The archive itself holds the whole run — every series is '
						+ 'worked out from it again when the file opens.'));
				}
			}
			cols.append(right);
			body.append(cols);

			// --- the buttons ----------------------------------------------
			const nothing = what.picks && picked && picked.picked === 0;
			able(!refusal(what, can) && !nothing);
			const send = (toBrowser) => {
				shut();
				onSave({
					kind: what.key,
					format,
					keys: what.picks ? [...picks[what.picks].chosen] : null,
					open: toBrowser,
				});
			};
			go.addEventListener('click', () => send(false));
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => shut());
			const buttons = [cancel];
			if (open) {
				open.addEventListener('click', () => send(true));
				buttons.push(open);
			}
			buttons.push(go);
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					nothing ? 'Nothing is ticked.'
						: what.key === 'model' && can.fileName
							? 'Where it was last saved. ⇧⌘S asks for somewhere else.'
							: 'Asks where to put it.'),
				...buttons));
		},
	});
	return handle;
}
