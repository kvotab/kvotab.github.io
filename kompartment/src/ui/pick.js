/**
 * A searchable list of things to tick.
 *
 * Every export in this tool asks the same question in the same shape -- which
 * of these several hundred named things do you want -- and it was being asked
 * three different ways: a menu with *what the table shows* and *all of it*, a
 * dialog of its own for endpoints, and nothing at all for the rest. So the
 * question is asked once, here, and the dialogs differ only in what they put
 * into it.
 *
 * **A block, not a series.** The things ticked are blocks: tick `Dose` and
 * every nuclide of it comes. Picking 831,314 series one at a time is not a
 * thing a dialog can offer, and nobody wants three of a block's four indices.
 *
 * **Only so many rows are drawn.** A model with thousands of blocks would
 * otherwise build thousands of checkboxes on every keystroke. The search is
 * how the rest are reached, and *All shown* acts on what the search matched --
 * which is what makes "tick every far-field path" one gesture.
 */

import { el } from './parts.js';

/** Rows drawn at once. The search is how the rest are reached. */
export const MOST_ROWS = 300;

/** What a picker remembers between rebuilds of the dialog around it. */
export function pickerState() {
	return { query: '', kind: '', system: '' };
}

/** The distinct values of one field, in the order they first appear. */
function optionsOf(items, field) {
	const seen = new Set();
	const out = [];
	for (const it of items) {
		const v = it[field] ?? '';
		if (!v || seen.has(v)) continue;
		seen.add(v);
		out.push(v);
	}
	return out.sort();
}

/** Which items the search and the filters leave. */
export function matching(items, ui) {
	const q = String(ui.query ?? '').trim().toLowerCase();
	return items.filter((it) => {
		if (ui.kind && it.kind !== ui.kind) return false;
		if (ui.system && (it.system ?? '') !== ui.system) return false;
		if (!q) return true;
		return `${it.name} ${it.kind ?? ''} ${it.unit ?? ''}`.toLowerCase().includes(q);
	});
}

/**
 * Draws the picker into `host`.
 *
 * @param {HTMLElement} host
 * @param {object} opts
 * @param {Array<{key, name, kind, unit, count, system}>} opts.items
 * @param {Set<string>} opts.chosen   ticked keys, edited in place
 * @param {object} opts.ui            from `pickerState()`, edited in place
 * @param {() => void} opts.onChange  rebuild the dialog around it
 * @param {string} [opts.noun]        what one of them is, for the counts
 * @returns {{shown: number, total: number, picked: number}}
 */
export function renderPicker(host, {
	items, chosen, ui, onChange, onTick = null, noun = 'block',
}) {
	const shown = matching(items, ui);
	const kinds = optionsOf(items, 'kind');
	const systems = optionsOf(items, 'system');

	const head = el('div', { className: 'pick-head' });
	const search = el('input', {
		type: 'search', className: 'pick-search', value: ui.query,
		placeholder: `Search ${items.length.toLocaleString()} ${noun}s…`,
		'aria-label': 'Search',
	});
	// `input` rather than `change`, so the list narrows as it is typed; the
	// caret is put back by the dialog's own refresh, which restores focus.
	search.addEventListener('input', () => { ui.query = search.value; onChange(); });
	head.append(search);

	const filter = (field, label, values) => {
		if (values.length < 2) return;
		const sel = el('select', { className: 'pick-filter-sel', 'aria-label': label });
		sel.append(el('option', { value: '' }, label));
		for (const v of values) sel.append(el('option', { value: v, selected: ui[field] === v }, v));
		sel.addEventListener('change', () => { ui[field] = sel.value; onChange(); });
		head.append(sel);
	};
	filter('kind', 'any kind', kinds);
	filter('system', 'anywhere', systems);

	const button = (text, title, run) => {
		const b = el('button', { type: 'button', className: 'ghost', title }, text);
		b.addEventListener('click', () => { run(); onChange(); });
		return b;
	};
	// On what the search matched, not on everything: that is what makes
	// "every far-field path" one gesture, and it is also the only way a cap of
	// three hundred rows can be worked around.
	head.append(
		button('All shown', 'Tick everything the search and filters leave',
			() => shown.forEach((it) => chosen.add(it.key))),
		button('None', 'Untick everything the search and filters leave',
			() => shown.forEach((it) => chosen.delete(it.key))),
	);
	// The same for the two buttons above the list, which tick and untick in
	// bulk: those *do* rebuild, since every row on screen changes.
	host.append(head);

	const list = el('div', { className: 'pick-list' });
	for (const it of shown.slice(0, MOST_ROWS)) {
		const box = el('input', { type: 'checkbox', checked: chosen.has(it.key) });
		box.addEventListener('change', () => {
			if (box.checked) chosen.add(it.key); else chosen.delete(it.key);
			// Not a full rebuild: a tick changes one box and the counts, and
			// rebuilding three hundred rows for that loses the scroll and the
			// caret. What *else* depends on how many are ticked -- a primary
			// button that is disabled while none are -- is told through
			// `onTick` instead, which is the cheap half of a refresh.
			count.textContent = countText();
			onTick?.(chosen.size);
		});
		list.append(el('label', { className: 'pick-row', title: it.title ?? it.name },
			box,
			el('span', { className: 'pick-name' }, it.name),
			el('span', { className: 'pick-kind' }, it.kind ?? ''),
			el('span', { className: 'pick-unit mono' }, it.unit ?? ''),
			el('span', { className: 'pick-count mono' },
				it.count > 1 ? `×${it.count.toLocaleString()}` : '')));
	}
	if (!shown.length) {
		list.append(el('p', { className: 'hint' },
			items.length ? 'Nothing matches that.' : `There are no ${noun}s to choose from.`));
	}
	host.append(list);

	const countText = () => {
		const picked = items.filter((it) => chosen.has(it.key));
		const series = picked.reduce((n, it) => n + (it.count ?? 1), 0);
		const bits = [`${picked.length.toLocaleString()} of ${items.length.toLocaleString()} `
			+ `${noun}${items.length === 1 ? '' : 's'} ticked`];
		if (series !== picked.length) bits.push(`${series.toLocaleString()} series`);
		if (shown.length > MOST_ROWS) {
			bits.push(`showing the first ${MOST_ROWS} of ${shown.length.toLocaleString()} matches `
				+ '— narrow the search to reach the rest');
		} else if (shown.length !== items.length) {
			bits.push(`${shown.length.toLocaleString()} match`);
		}
		return bits.join(' · ');
	};
	const count = el('p', { className: 'hint pick-count-line' }, countText());
	host.append(count);

	const picked = items.filter((it) => chosen.has(it.key)).length;
	return { shown: shown.length, total: items.length, picked };
}
