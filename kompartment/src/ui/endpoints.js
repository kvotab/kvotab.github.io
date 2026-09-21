/**
 * Choosing which endpoints a run saves.
 *
 * An **endpoint** is Ecolego's word for a block whose result is kept. Its
 * `<simulation-settings>` carries the list:
 *
 *     <outputs>
 *       <output id="NearField&#46;waste&#95;domain&#95;length"/>
 *       ...
 *     </outputs>
 *
 * and `JavaSimulator` writes a series for those and for nothing else. That is
 * why an Ecolego result file of a three-thousand-block model holds two groups:
 * somebody decided what was worth keeping.
 *
 * This tool keeps everything -- every series is worked out from the states on
 * request, so holding them costs nothing until they are asked for -- and that
 * is the right default for looking at a model. It is the wrong default for
 * *saving* one: a run of model G has 831,314 series, which is
 * 2.8 GB of HDF5 and more than a tab can build. The two exports that were here
 * already are the two ends of that -- what the table happens to show, or all of
 * it -- and neither is "the forty things this assessment is about".
 *
 * So: a list of the blocks a run produced, ticked. The model's own endpoint
 * list is what it opens on when the file had one, which makes the common case
 * one click. What is chosen is saved back to the model, because an endpoint
 * list is a property of the model in Ecolego and because picking the same
 * forty blocks on every export is not a thing to ask of anybody.
 *
 * **A block, not a series.** Ecolego's endpoints are blocks and so are these:
 * tick `Dose` and every nuclide of it goes. Picking 831,314 series one at a
 * time is not a thing a dialog can offer.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';

/** Rows drawn at once. The search box is how the rest are reached. */
const MOST_ROWS = 400;

/** A size estimate, from the numbers alone. */
function size(bytes) {
	if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`;
	if (bytes >= 1048576) return `${Math.round(bytes / 1048576)} MB`;
	if (bytes >= 1024) return `${Math.round(bytes / 1024)} kB`;
	return `${Math.round(bytes)} bytes`;
}

/**
 * A file's size, which is never usefully said as a handful of bytes: a
 * kilobyte is the floor because anything smaller is header.
 */
function estimate(series, times) {
	return size(Math.max(1024, series * times * 8));
}

/**
 * The blocks a run produced, each with what it stands for.
 *
 * @param {Array<{block: string, kind: string, unit: string}>} outputs
 * @returns {Array<{name: string, kind: string, unit: string, count: number}>}
 */
export function blocksOf(outputs) {
	const by = new Map();
	for (const o of outputs ?? []) {
		const name = o.block ?? o.label ?? '';
		if (!name) continue;
		const found = by.get(name);
		if (found) {
			found.count += 1;
			// A block's unit is the same at every index unless it takes the
			// material's, in which case saying one of them would be a lie.
			if (found.unit !== (o.unit ?? '')) found.unit = '';
			continue;
		}
		by.set(name, { name, kind: o.kind ?? '', unit: o.unit ?? '', count: 1 });
	}
	return [...by.values()];
}

/**
 * Which blocks a set of names covers, as output indices.
 *
 * @returns {number[]} in the order the run reports them
 */
export function indicesFor(outputs, names) {
	const want = new Set(names);
	const out = [];
	(outputs ?? []).forEach((o, i) => {
		if (want.has(o.block ?? o.label ?? '')) out.push(i);
	});
	return out;
}

/**
 * Opens the picker.
 *
 * @param {object} opts
 * @param {Array} opts.outputs      the run's series descriptors
 * @param {number} opts.times       how many output times, for the estimate
 * @param {string[]} opts.endpoints the model's own list, if it has one
 * @param {string[]} opts.shown     what the table is showing, as a fallback
 * @param {(names: string[], format: 'csv'|'hdf5'|'browser', holding: *) => void}
 *   opts.onExport  `browser` hands the file to the HDF5 reader instead of
 *   saving it; `holding` says which of a probabilistic result to write
 * @param {(names: string[]) => void} [opts.onRemember] called with the choice
 * @param {number} [opts.realisations] how many runs a probabilistic result has,
 *   when there is one -- offered as a third thing to save
 */
export function openEndpointPicker({
	outputs, times, endpoints = [], shown = [], onExport = null, onRemember,
	realisations = 0,
}) {
	// Whether there is anything to write. The list of blocks comes from the
	// *layout*, which exists as soon as the model builds -- so this dialog
	// opens before a run, which is the case it is most for: choosing what a
	// run will keep is a thing to do before it has kept everything. The files
	// are the half that needs numbers.
	const canExport = typeof onExport === 'function';
	const blocks = blocksOf(outputs).sort((a, b) => a.name.localeCompare(b.name));
	const all = new Set(blocks.map((b) => b.name));
	const declared = endpoints.filter((n) => all.has(n));
	// What it opens on: the model's own endpoints when it has them, otherwise
	// whatever the table is showing, otherwise nothing -- never everything,
	// since "everything" is the export this one exists to be an alternative to.
	const start = declared.length ? declared : shown.filter((n) => all.has(n));
	const chosen = new Set(start);
	let query = '';
	// What an HDF5 save writes, when there is a probabilistic result to choose
	// from. `deterministic` is what this dialog has always written.
	let holdKind = 'deterministic';
	let holdOne = 1;
	const holds = () => (holdKind === 'one' ? holdOne : holdKind);

	const matches = () => {
		const q = query.trim().toLowerCase();
		if (!q) return blocks;
		// The kind counts as text, so `parameter` narrows to parameters and
		// `soil` to the blocks called that.
		return blocks.filter((b) => `${b.name} ${b.kind}`.toLowerCase().includes(q));
	};

	// What is ticked, said in one line. Its own element rather than the
	// dialog's subtitle, because the subtitle is only redrawn when the whole
	// body is -- and rebuilding four hundred rows on every tick of a checkbox
	// is both slow and a good way to lose the keyboard.
	const summary = el('p', { className: 'ep-sum' });
	let buttons = [];
	const retally = () => {
		const series = blocks.reduce((n, b) => n + (chosen.has(b.name) ? b.count : 0), 0);
		summary.textContent = `${chosen.size} of ${blocks.length} blocks — `
			+ `${series.toLocaleString()} series`
			// With no run behind it there is no output grid to price against,
			// so it says the rate instead of inventing a total -- and says
			// nothing at all while nothing is ticked, where the rate is zero
			// and a file size would be its own floor.
			+ (times > 0
				? ` over ${times.toLocaleString()} times, about ${estimate(series, times)}`
				: series ? `, ${size(series * 8)} per output time` : '');
		for (const b of buttons) b.disabled = !chosen.size;
	};

	const modal = openModal({
		wide: true,
		title: 'Which endpoints to save',
		subtitle: canExport
			? 'Ticking a block saves every index of it'
			: 'Ticking a block keeps every index of it. Saved with the model, '
				+ 'and read by the next run',
		build: (body) => {
			const found = matches();

			// --- the toolbar, which stays put while the list scrolls.
			const search = el('input', {
				type: 'search', className: 'ep-search', value: query,
				placeholder: `Search ${blocks.length} blocks by name or kind`,
				'aria-label': 'Search blocks',
			});
			search.addEventListener('input', () => { query = search.value; modal.refresh(); });

			const button = (label, title, act) => {
				const b = el('button', { type: 'button', className: 'ghost ep-act', title }, label);
				b.addEventListener('click', () => { act(); modal.refresh(); });
				return b;
			};
			const bar = el('div', { className: 'ep-bar' },
				search,
				button('All shown', 'Tick everything the search matches',
					() => { for (const b of found) chosen.add(b.name); }),
				button('None', 'Untick everything the search matches',
					() => { for (const b of found) chosen.delete(b.name); }),
				declared.length
					? button(`The model’s ${declared.length}`,
						'Back to the endpoint list this model was saved with',
						() => { chosen.clear(); for (const n of declared) chosen.add(n); })
					: null,
			);
			body.append(bar, summary);

			// --- the list.
			const list = el('div', { className: 'ep-list' });
			for (const b of found.slice(0, MOST_ROWS)) {
				const box = el('input', { type: 'checkbox', checked: chosen.has(b.name) });
				box.addEventListener('change', () => {
					if (box.checked) chosen.add(b.name);
					else chosen.delete(b.name);
					// Only the tally moves; the rows stay as they are, and so
					// does the checkbox that was just clicked.
					retally();
				});
				list.append(el('label', { className: 'ep-row' },
					box,
					el('span', { className: 'ep-name mono' }, b.name),
					el('span', { className: 'ep-kind' }, b.kind.replace(/_/g, ' ')),
					el('span', { className: 'ep-count' },
						b.count === 1 ? '1 series' : `${b.count.toLocaleString()} series`),
					el('span', { className: 'ep-unit mono' }, b.unit)));
			}
			if (!found.length) {
				list.append(el('p', { className: 'ep-none' },
					`Nothing matches “${query}”.`));
			}
			body.append(list);
			if (found.length > MOST_ROWS) {
				body.append(el('p', { className: 'ep-more' },
					`Showing ${MOST_ROWS} of ${found.length.toLocaleString()} matches. `
					+ 'Narrow the search to reach the rest — All shown and None act on '
					+ 'every match, not only the ones drawn.'));
			}

			// --- what to do with them.
			const go = (format, holding) => {
				const names = blocks.filter((b) => chosen.has(b.name)).map((b) => b.name);
				if (!names.length) return;
				onRemember?.(names);
				modal.close();
				onExport(names, format, holding);
			};

			// --- and, where a probabilistic run stands behind these series,
			// which of it to write.
			//
			// One file cannot sensibly be all three. The runs, their mean, and
			// one named run are different answers to "what happened", and for a
			// skewed quantity -- which a dose is -- they are not close to each
			// other: the mean of a thousand doses sits well above the median and
			// nowhere near the run at the central parameter values. So it is
			// asked rather than assumed, and the deterministic run stays the
			// default, which is what this button has always written.
			if (realisations > 1) {
				const pick = el('select', { className: 'ep-holds' });
				for (const [value, label] of [
					['deterministic', 'The deterministic run'],
					['mean', `The mean of ${realisations.toLocaleString()} realisations`],
					['all', `All ${realisations.toLocaleString()} realisations`],
					['one', 'One realisation…'],
				]) {
					pick.append(el('option', { value, selected: value === holdKind }, label));
				}
				pick.addEventListener('change', () => { holdKind = pick.value; modal.refresh(); });

				const which = el('input', {
					type: 'number', className: 'mono ep-which', min: '1',
					max: String(realisations), value: String(holdOne),
					'aria-label': 'Which realisation',
				});
				which.addEventListener('change', () => {
					const v = Math.round(Number(which.value));
					holdOne = Number.isFinite(v) ? Math.min(realisations, Math.max(1, v)) : 1;
					which.value = String(holdOne);
				});

				body.append(el('div', { className: 'ep-holdrow' },
					el('label', { title: 'What the HDF5 file holds. CSV always writes the '
						+ 'deterministic values.' }, 'HDF5 holds'),
					pick,
					...(holdKind === 'one'
						? [which, el('span', { className: 'ep-holdnote' },
							`of ${realisations.toLocaleString()}`)]
						: []),
					el('span', { className: 'ep-holdnote ep-holdwhy' },
						holdKind === 'all'
							? 'One row per time, one column per realisation — the shape '
								+ 'Ecolego writes. Large.'
							: holdKind === 'mean'
								? 'One curve: the average of the runs at each time.'
								: holdKind === 'one'
									? 'One curve: that run, exactly as it was integrated.'
									: 'The values the model holds, with no sampling.')));
			}
			if (!canExport) {
				const done = el('button', { type: 'button', className: 'primary' }, 'Done');
				done.addEventListener('click', () => {
					onRemember?.(blocks.filter((b) => chosen.has(b.name)).map((b) => b.name));
					modal.close();
				});
				buttons = [done];
				body.append(el('div', { className: 'ep-foot' },
					el('span', { className: 'ep-note' },
						'Saved as this model’s endpoints. Run it and this dialog writes '
						+ 'them out as well.'),
					done));
				retally();
				return;
			}
			const csv = el('button', { type: 'button', className: 'ghost' }, 'Save as CSV');
			csv.addEventListener('click', () => go('csv'));
			const h5 = el('button', { type: 'button', className: 'primary' }, 'Save as HDF5');
			h5.addEventListener('click', () => go('hdf5', holds()));
			// The same file, into the reader instead of onto the disk. The
			// click matters: the tab is opened from this handler and the bytes
			// follow when they exist, because a pop-up is allowed out of a
			// gesture and not out of a promise that settles after one.
			const open = el('button', { type: 'button', className: 'ghost' }, 'Open in browser');
			open.title = 'Opens the HDF5 result browser and hands it this file directly, '
				+ 'without saving it first.';
			open.addEventListener('click', () => go('browser', holds()));
			buttons = [csv, open, h5];
			body.append(el('div', { className: 'ep-foot' },
				el('span', { className: 'ep-note' },
					'What you choose is remembered as this model’s endpoints.'),
				csv, open, h5));
			retally();
		},
	});
	return modal;
}
