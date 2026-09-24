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
import { renderDualTree, dualTreeState } from './dualtree.js';
import { canBeEndpoint } from '../domain/edit.js';

/**
 * What can be written, in the order a reader looks for them.
 *
 * `picks` says which list the right-hand side shows: `series` for a run's
 * outputs, `data` for the parameters and lookup tables, nothing for a whole
 * model. `needs` is what has to be true, and the dialog turns it into a
 * sentence rather than a grey row. `browser` is whether the same file can go
 * straight to the HDF5 Browser instead of the disk; it reads HDF5 and nothing
 * else, so that is the file it gets whichever format is chosen. `holds` is
 * whether it asks which of a sample the file is of -- see `HOLDS`.
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
			+ 'The blocks under Endpoints are the model’s endpoints — what a probabilistic '
			+ 'run keeps — and they are saved with it.',
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
		label: 'Realisations',
		blurb: 'What a probabilistic run drew rather than the curve through it: every '
			+ 'realisation, their mean, or one of them.',
		formats: [['hdf5', 'HDF5', 'One matrix per series, or one curve per series']],
		needs: 'sample',
		picks: 'series',
		browser: true,
		holds: true,
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

/**
 * Which of a sample a Realisations file is of.
 *
 * One file cannot sensibly be all three. The runs, their mean and one named
 * run are different answers to "what happened", and for a skewed output -- a
 * dose -- they are not close: the mean of a thousand doses sits well above the
 * median. So it is asked. The deterministic run is the fourth answer, and it
 * is Results.
 */
const HOLDS = [
	['all', (n) => `All ${n} realisations`,
		'One row per output time and one column per realisation — the shape Ecolego writes. Large.'],
	['mean', (n) => `The mean of ${n} realisations`,
		'One curve per series: the average of the runs at each time.'],
	['one', () => 'One realisation…',
		'One curve per series: that run, exactly as it was integrated.'],
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
 * @param {object} opts.can        `{results, sample, iterations, stale, data, fileName}`
 * @param {Array} opts.series      pickable result blocks
 * @param {Array} opts.data        pickable parameters and lookup tables
 * @param {string[]} opts.endpoints the model's endpoint list, under Endpoints to start with
 * @param {string} [opts.log]      what Run log would write, to be shown before it is
 * @param {object} opts.chosen     `{kind, format, holds, which}` remembered between openings
 * @param {(choice) => void} opts.onSave  `{kind, format, keys, open, holds, which}`;
 *   `open` is the HDF5 Browser rather than the disk, and is called from the
 *   click itself, so that the tab can be opened there; `holds` and `which` say
 *   which of a sample a Realisations file is of
 */
export function openSaveDialog({
	can, series = [], data = [], endpoints = [], log = '', chosen = {}, onSave,
}) {
	// The first thing that can actually be written, so the dialog does not
	// open on a row it will refuse.
	const usable = KINDS.filter((k) => !refusal(k, can));
	let what = KINDS.find((k) => k.key === chosen.kind && !refusal(k, can))
		?? usable[0] ?? KINDS[0];
	let format = what.formats.some(([f]) => f === chosen.format)
		? chosen.format : what.formats[0][0];
	// Which of a sample, for Realisations: every run, their mean, or one of
	// them by its number, from 1.
	const iterations = Math.max(1, Math.round(Number(can.iterations) || 1));
	let holds = HOLDS.some(([v]) => v === chosen.holds) ? chosen.holds : 'all';
	let which = Math.min(iterations, Math.max(1, Math.round(Number(chosen.which)) || 1));

	// What an endpoint can be chosen from: every series but a parameter's
	// (`canBeEndpoint`).
	const candidates = series.filter((s) => canBeEndpoint(s.kind));
	const itemsOf = (list) => (list === 'data' ? data : list === 'endpoints' ? candidates : series);
	// One choice per list, kept while the dialog is open so switching
	// between Results and Realisations does not lose it -- and the two trees'
	// searches, filters and open sub-systems with it.
	const picks = {
		series: { chosen: new Set(series.filter((s) => s.on).map((s) => s.key)), ui: dualTreeState() },
		// The endpoints the model already declares, or everything when it
		// declares none -- which is what a run keeps today.
		endpoints: {
			chosen: new Set(endpoints.length ? endpoints : candidates.map((s) => s.key)),
			ui: dualTreeState(),
		},
		data: { chosen: new Set(data.map((d) => d.key)), ui: dualTreeState() },
	};
	// What the two sides are called, for each list.
	const TITLES = {
		series: ['Not in the file', 'In the file'],
		endpoints: ['Not kept', 'Endpoints'],
		data: ['Not in the file', 'In the file'],
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

			// The log itself, before it is saved, as the log window shows it:
			// what is about to be written is the one thing worth seeing here.
			if (what.key === 'log' && log) {
				right.append(el('pre', { className: 'runlog save-log', tabIndex: 0 }, log));
				right.append(el('p', { className: 'hint' },
					`${log.split('\n').length.toLocaleString()} lines, all of which are saved.`));
			}

			if (what.holds) {
				const n = iterations.toLocaleString();
				const sel = el('select', { 'aria-label': 'What the file holds' });
				for (const [value, label] of HOLDS) {
					sel.append(el('option', { value, selected: value === holds }, label(n)));
				}
				sel.addEventListener('change', () => { holds = sel.value; handle.refresh(); });
				const row = el('div', { className: 'save-holds' }, sel);
				if (holds === 'one') {
					const box = el('input', {
						type: 'number', className: 'mono save-which', min: '1', max: String(iterations),
						value: String(which), 'aria-label': 'Which realisation',
					});
					box.addEventListener('change', () => {
						const v = Math.round(Number(box.value));
						which = Number.isFinite(v) ? Math.min(iterations, Math.max(1, v)) : 1;
						box.value = String(which);
					});
					row.append(box, el('span', { className: 'save-of' }, `of ${n}`));
				}
				right.append(el('div', { className: 'field' },
					el('label', { title: 'Which of the probabilistic run the file is of. The '
						+ 'deterministic run is Results.' }, 'Holds'), row));
				right.append(el('p', { className: 'hint' }, HOLDS.find(([v]) => v === holds)[2]));
			}

			// Declared before the trees so a move can reach them: the buttons
			// are disabled while nothing is chosen, and a move does not
			// rebuild the dialog -- the trees redraw themselves.
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
			const note = el('span', { className: 'pdf-note' });
			const noteText = (none) => (none ? 'Nothing is chosen.'
				: what.key === 'model' && can.fileName
					? 'Where it was last saved. ⇧⌘S asks for somewhere else.'
					: 'Asks where to put it.');
			const able = (yes) => {
				go.disabled = !yes;
				if (open) open.disabled = !yes;
			};
			// Whether the list, where there is one, has anything in it.
			const none = () => {
				if (!what.picks) return false;
				return !itemsOf(what.picks).some((it) => picks[what.picks].chosen.has(it.key));
			};
			const settle = () => {
				able(!refusal(what, can) && !none());
				note.textContent = noteText(none());
			};
			if (what.picks) {
				const box = el('div', { className: 'save-pick' });
				renderDualTree(box, {
					items: itemsOf(what.picks),
					chosen: picks[what.picks].chosen,
					ui: picks[what.picks].ui,
					titles: TITLES[what.picks],
					noun: 'block',
					onChange: settle,
				});
				right.append(box);
				if (what.picks === 'endpoints') {
					// What choosing one actually does, since it outlives the
					// file: an endpoint list is a property of the model.
					right.append(el('p', { className: 'hint' },
						'Saved with the model, so a re-run keeps these. The archive itself '
						+ 'holds the whole run — every series is worked out from it again '
						+ 'when the file opens.'));
				}
			}
			cols.append(right);
			body.append(cols);

			// --- the buttons ----------------------------------------------
			// Save is the end of the dialog. The HDF5 Browser is a look at the
			// file in another tab, and the dialog stays for what usually comes
			// next: another choice of blocks, or saving the file after all.
			const send = (toBrowser) => {
				if (!toBrowser) shut();
				onSave({
					kind: what.key,
					format,
					keys: what.picks ? [...picks[what.picks].chosen] : null,
					open: toBrowser,
					holds,
					which,
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
			body.append(el('div', { className: 'pdf-foot' }, note, ...buttons));
			settle();
		},
	});
	return handle;
}
