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
 * So: the blocks a run produced, in two trees -- not kept, and kept. The
 * model's own endpoint list is what it opens on when the file had one, which
 * makes the common case one click. What is chosen is saved back to the model,
 * because an endpoint list is a property of the model in Ecolego and because
 * picking the same forty blocks for every run is not a thing to ask of anybody.
 *
 * **A block, not a series.** Ecolego's endpoints are blocks and so are these:
 * keep `Dose` and every nuclide of it is kept. Picking 831,314 series one at a
 * time is not a thing a dialog can offer.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { renderDualTree, dualTreeState } from './dualtree.js';
import { dialogInfo } from './dialoginfo.js';

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
 * Opens the picker: which blocks a run keeps.
 *
 * Reached from the probabilistic dialog, where the question is what the run
 * about to be made should keep -- so it asks that and nothing else. It used to
 * offer the chosen blocks as files as well, which is a different question
 * asked at a different time and is Save…'s; here it only muddled a choice
 * made before anything had run.
 *
 * Two trees rather than a list of tick boxes (see ./dualtree.js): what is not
 * kept on the left, the endpoints on the right, each searchable and filtered by
 * kind, and things moved between them by dragging, double-clicking, the
 * buttons or the menu.
 *
 * @param {object} opts
 * @param {Array} opts.outputs      the run's series descriptors
 * @param {number} opts.times       how many output times, for the estimate
 * @param {string[]} opts.endpoints the model's own list, if it has one
 * @param {string[]} opts.shown     what the table is showing, as a fallback
 * @param {(names: string[]) => void} [opts.onRemember] called with the choice on Done
 */
export function openEndpointPicker({
	outputs, times, endpoints = [], shown = [], onRemember,
}) {
	const blocks = blocksOf(outputs).sort((a, b) => a.name.localeCompare(b.name));
	const all = new Set(blocks.map((b) => b.name));
	const declared = endpoints.filter((n) => all.has(n));
	// What it opens on: the model's own endpoints when it has them, otherwise
	// whatever the table is showing, otherwise nothing -- never everything,
	// since "everything" is what keeping endpoints exists to be an
	// alternative to.
	const start = declared.length ? declared : shown.filter((n) => all.has(n));
	const chosen = new Set(start);
	const ui = dualTreeState();
	const items = blocks.map((b) => ({
		key: b.name, name: b.name, kind: b.kind, unit: b.unit, count: b.count,
	}));

	// What is kept, said in one line, and redrawn after every move rather
	// than with the dialog: the trees redraw themselves.
	const summary = el('p', { className: 'ep-sum' });
	let done = null;
	const retally = () => {
		const series = blocks.reduce((n, b) => n + (chosen.has(b.name) ? b.count : 0), 0);
		summary.textContent = `${chosen.size} of ${blocks.length} blocks kept — `
			+ `${series.toLocaleString()} series`
			// With no run behind it there is no output grid to price against,
			// so it says the rate instead of inventing a total -- and says
			// nothing at all while nothing is kept, where the rate is zero
			// and a size would be its own floor.
			+ (times > 0
				? ` over ${times.toLocaleString()} times, about ${estimate(series, times)} a realisation`
				: series ? `, ${size(series * 8)} per output time` : '');
		if (done) done.disabled = false;
	};

	const modal = openModal({
		info: dialogInfo('endpoints'),
		wide: true,
		title: 'Which endpoints to keep',
		subtitle: 'An endpoint keeps every index of its block. Saved with the model, '
			+ 'and read by the next run',
		build: (body) => {
			const bar = el('div', { className: 'ep-bar' }, summary);
			if (declared.length) {
				const back = el('button', {
					type: 'button', className: 'ghost ep-act',
					title: 'Back to the endpoint list this model was saved with',
				}, `The model’s ${declared.length}`);
				back.addEventListener('click', () => {
					chosen.clear();
					for (const n of declared) chosen.add(n);
					modal.refresh();
				});
				bar.append(back);
			}
			body.append(bar);

			const box = el('div', { className: 'ep-trees' });
			renderDualTree(box, {
				items, chosen, ui,
				titles: ['Not kept', 'Endpoints'],
				noun: 'block',
				onChange: retally,
			});
			body.append(box);

			done = el('button', { type: 'button', className: 'primary' }, 'Done');
			done.addEventListener('click', () => {
				onRemember?.(blocks.filter((b) => chosen.has(b.name)).map((b) => b.name));
				modal.close();
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'ep-foot' },
				el('span', { className: 'ep-note' },
					'Saved as this model’s endpoints; the probabilistic run keeps these. '
					+ 'To write any of them to a file, Save… after the run.'),
				cancel, done));
			retally();
		},
	});
	return modal;
}
