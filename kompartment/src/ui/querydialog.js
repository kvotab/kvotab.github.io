/**
 * Asking the model a question, and pinning the answer over the block list.
 *
 * The name box beside this answers "where is the block called X". These answer
 * the questions that come up on a model somebody else built: what reads this,
 * what does this need, what does nothing read, which of these are transcribed
 * numbers and which are worked out. See ../domain/queries.js for the list and
 * for why each one earns its place.
 *
 * The answer is a set of names, and it is pinned as a *filter* rather than
 * shown in a list of its own. Two reasons. The tree already knows how to draw
 * blocks -- with their icons, under their sub-systems, selectable, with their
 * settings a double-click away -- and a second list would be a worse one. And
 * pinning composes: "everything that reads `leachRate`", then the kind chips to
 * narrow it to the transfers, then a name to find one of those.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { QUERIES, runQuery, referenceGraph } from '../domain/queries.js';
import { statuses, enabled as qaEnabled } from '../domain/qa.js';
import { dialogInfo } from './dialoginfo.js';

/** The order they are offered in: the two that walk references first. */
const ORDER = [
	'uses', 'usedBy', 'unused',
	'notApproved', 'lapsed', 'locked',
	'dataOnly', 'expressions', 'distributed', 'disabled',
	'indexedOver', 'inSystem',
	'withUnit', 'unitMentions', 'noUnit',
	'describedAs',
];

/**
 * @param {object} opts
 * @param {object} opts.project
 * @param {string[]} opts.blocks    every block name, for the block argument
 * @param {string[]} opts.lists     every index list
 * @param {string[]} opts.systems   every sub-system path
 * @param {string} [opts.selected]  what is selected, as the default subject
 * @param {(found: string[], label: string) => void} opts.onPin
 */
export function openQueryDialog({
	project, blocks = [], lists = [], systems = [], selected = '', onPin,
}) {
	let id = 'uses';
	let name = selected && blocks.includes(selected) ? selected : (blocks[0] ?? '');
	let text = '';
	let list = lists[0] ?? '';
	let system = systems[0] ?? '';
	let direct = false;
	// One walk of every equation in the model, shared by every question asked
	// while the dialog is open -- the two that need it are the two people ask
	// repeatedly, one block after another.
	let graph = null;
	let qa = null;

	const answer = () => {
		const q = QUERIES[id];
		if (!q) return [];
		if (q.needs === 'block' && !name) return [];
		if (q.needs === 'text' && !text.trim()) return [];
		graph ??= referenceGraph(project);
		// The QA questions need the statuses, which need the same graph.
		qa ??= statuses(project, graph);
		return runQuery(project, id, { name, text, list, system, direct, graph, qa });
	};

	const modal = openModal({
		info: dialogInfo('query'),
		wide: true,
		title: 'Ask the model',
		subtitle: 'Questions a name cannot answer — what reads this, what this needs, '
			+ 'what nothing reads',
		build: (body) => {
			const q = QUERIES[id];

			const pick = el('select', { className: 'q-which' });
			const qaOn = qaEnabled(project);
			for (const key of ORDER) {
				if (!QUERIES[key]) continue;
				// Not offered where nothing could answer them: a model with QA
				// switched off has no reviews to be behind on.
				if (!qaOn && ['notApproved', 'lapsed', 'locked'].includes(key)) continue;
				pick.append(el('option', {
					value: key, selected: key === id, title: QUERIES[key].hint,
				}, QUERIES[key].label));
			}
			pick.addEventListener('change', () => { id = pick.value; modal.refresh(); });
			body.append(el('div', { className: 'pdf-row pdf-row-wide' },
				el('label', {}, 'Question'), pick));
			body.append(el('p', { className: 'pdf-note' }, q.hint));

			// --- whatever this question needs to be asked.
			if (q.needs === 'block') {
				const who = el('select', { className: 'q-arg' });
				for (const b of blocks) {
					who.append(el('option', { value: b, selected: b === name }, b));
				}
				who.addEventListener('change', () => { name = who.value; modal.refresh(); });
				body.append(el('div', { className: 'pdf-row pdf-row-wide' },
					el('label', {}, 'Block'), who));

				const box = el('input', { type: 'checkbox', checked: direct });
				box.addEventListener('change', () => { direct = box.checked; modal.refresh(); });
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: 'Only the equations that name it outright, rather '
						+ 'than everything that depends on it however far away.' },
					'Named outright only'), box));
			}
			if (q.needs === 'text') {
				const input = el('input', {
					type: 'search', className: 'q-arg', value: text, spellcheck: false,
					placeholder: id === 'withUnit' ? 'Bq/m3' : 'text to look for',
				});
				input.addEventListener('input', () => { text = input.value; modal.refresh(); });
				body.append(el('div', { className: 'pdf-row pdf-row-wide' },
					el('label', {}, 'Containing'), input));
			}
			if (q.needs === 'list') {
				const which = el('select', { className: 'q-arg' });
				for (const l of lists) which.append(el('option', { value: l, selected: l === list }, l));
				which.addEventListener('change', () => { list = which.value; modal.refresh(); });
				body.append(el('div', { className: 'pdf-row pdf-row-wide' },
					el('label', {}, 'Index list'),
					lists.length ? which : el('span', { className: 'hint' }, 'This model has none.')));
			}
			if (q.needs === 'system') {
				const which = el('select', { className: 'q-arg' });
				for (const sPath of systems) {
					which.append(el('option', { value: sPath, selected: sPath === system }, sPath));
				}
				which.addEventListener('change', () => { system = which.value; modal.refresh(); });
				body.append(el('div', { className: 'pdf-row pdf-row-wide' },
					el('label', {}, 'Sub-system'),
					systems.length
						? which
						: el('span', { className: 'hint' }, 'This model has none.')));
			}

			// --- the answer, before it is pinned.
			const found = answer();
			const list2 = el('div', { className: 'prob-list' });
			for (const n of found.slice(0, 200)) {
				list2.append(el('div', { className: 'prob-item' }, el('code', {}, n)));
			}
			if (found.length > 200) {
				list2.append(el('div', { className: 'prob-more' },
					`and ${(found.length - 200).toLocaleString()} more`));
			}
			if (!found.length) {
				list2.append(el('p', { className: 'hint' }, 'Nothing.'));
			}
			body.append(el('p', { className: 'prob-more' },
				`${found.length.toLocaleString()} block${found.length === 1 ? '' : 's'}`));
			body.append(list2);

			const go = el('button', {
				type: 'button', className: 'primary', disabled: !found.length,
			}, 'Show these');
			go.addEventListener('click', () => {
				modal.close();
				onPin(found, labelFor(id, { name, text, list, system, direct }));
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'Shown in the panel, where the kind chips and the name box still '
					+ 'narrow it further.'),
				cancel, go));
		},
	});
	return modal;
}

/** What the pin is called once it is on. */
export function labelFor(id, { name = '', text = '', list = '', system = '', direct = false } = {}) {
	const q = QUERIES[id];
	if (!q) return 'a question';
	if (q.needs === 'block') return `${direct ? '' : 'all '}${q.label.replace('…', '')} ${name}`.trim();
	if (q.needs === 'text') return `${q.label.replace('…', '')} “${text}”`;
	if (q.needs === 'list') return `${q.label.replace('…', '')} ${list}`;
	if (q.needs === 'system') return `${q.label.replace('…', '')} ${system}`;
	return q.label;
}
