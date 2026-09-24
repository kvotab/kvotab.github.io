/**
 * One door in, for a file that may hold several things.
 *
 * A `.zip` from this tool is a model *and* a run. A `.h5` is a thousand
 * realisations of somebody else's near-field, or a table of parameter values,
 * or the results of a run. A `.json` is a model. Which of those a reader wants
 * is not something the extension can answer, and it was being answered by
 * which button they happened to press: Open replaced the model, Import merged
 * blocks, and the data importer was three levels inside a menu under Save.
 *
 * So the file is read first and this says what is in it, one row per thing,
 * with what can be done to each. A row that cannot be acted on stays and says
 * why -- "this archive has no run in it" is the answer to a question somebody
 * is about to ask.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { dialogInfo } from './dialoginfo.js';

/**
 * @param {object} opts
 * @param {string} opts.name            the file's own name
 * @param {Array<object>} opts.holds    `{key, label, detail, why, actions}`
 *   where each action is `{label, title, run}` and `why` disables the row
 */
export function openImportChooser({ name, holds, onPickAnother = null }) {
	let handle = null;
	const shut = () => handle?.close();
	handle = openModal({
		info: dialogInfo('import-chooser'),
		title: `Import from ${name}`,
		build(body) {
			body.replaceChildren();
			const live = holds.filter((h) => !h.why);
			body.append(el('p', { className: 'hint' },
				live.length
					? 'What this file holds. Taking one thing does not take the others — '
						+ 'open it again for those.'
					: 'Nothing in this file is something this tool can take.'));

			for (const h of holds) {
				const row = el('div', { className: `imp-row${h.why ? ' is-off' : ''}` });
				row.append(el('div', { className: 'imp-what' },
					el('span', { className: 'imp-label' }, h.label),
					el('span', { className: 'imp-detail' }, h.why ?? h.detail ?? '')));
				const buttons = el('div', { className: 'imp-acts' });
				for (const a of h.actions ?? []) {
					const b = el('button', {
						type: 'button',
						className: a.primary ? 'primary' : 'ghost',
						disabled: !!h.why || !!a.disabled,
						title: a.title ?? '',
					}, a.label);
					b.addEventListener('click', () => { shut(); a.run(); });
					buttons.append(b);
				}
				row.append(buttons);
				body.append(row);
			}

			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => shut());
			const foot = el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'Nothing has been changed yet — each of these asks again.'));
			if (onPickAnother) {
				const other = el('button', { type: 'button', className: 'ghost' }, 'Another file…');
				other.addEventListener('click', () => { shut(); onPickAnother(); });
				foot.append(other);
			}
			foot.append(cancel);
			body.append(foot);
		},
	});
	return handle;
}
