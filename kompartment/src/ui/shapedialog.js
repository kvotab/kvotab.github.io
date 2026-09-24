/**
 * Everything a shape on the canvas can be, in one place.
 *
 * A shape's settings used to live only on its right-click menu: six submenus,
 * a colour under each, and the label behind a prompt that asked for the text
 * and nothing else. That is a fine way to change *one* thing you already know
 * the name of, and a poor way to see what a shape is or to set three things at
 * once -- every change closed the menu, and finding the next one meant opening
 * it again and remembering which submenu it was under.
 *
 * So the menu keeps the *actions* -- bring to front, duplicate, delete -- and
 * the settings are here, in the dialog a double-click opens, which is what
 * double-clicking a thing with properties does everywhere else in this
 * application.
 *
 * **Every change applies at once.** There is no OK button: the shape is on the
 * canvas behind the dialog and the point of changing its colour is to see the
 * colour. That also means there is nothing to cancel, which is why the only
 * button is Close.
 *
 * **It edits a selection, not a shape.** Several shapes can be picked at once
 * and the menu already set them all; this does the same. The fields show the
 * first one's values -- with a note saying so -- and setting one sets all.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { FIGURES, FIGURE_GROUPS } from './figures.js';
import {
	SHAPE_COLORS, NO_COLOR, SHAPE_DASHES, SHAPE_WIDTHS,
	SHAPE_TEXT_SIZES, SHAPE_TEXT_FONTS, SHAPE_TEXT_ALIGNS,
	SHAPE_MIN, SHAPE_MAX,
} from '../domain/edit.js';
import { dialogInfo } from './dialoginfo.js';

const FONT_LABEL = {
	sans: 'the interface face', scribble: 'handwriting',
	serif: 'serif', mono: 'monospace',
};
const ALIGN_LABEL = { left: 'ranged left', center: 'centred', right: 'ranged right' };
const DASH_LABEL = { solid: 'solid', dashed: 'dashed', dotted: 'dotted' };

/** A labelled row, which is what every setting below is. */
function row(label, hint, ...controls) {
	return el('div', { className: 'shape-row' },
		el('label', { className: 'shape-label' },
			label,
			hint ? el('span', { className: 'shape-hint' }, hint) : null),
		el('div', { className: 'shape-control' }, ...controls));
}

/** A `<select>` over a list, with the current value chosen. */
function choose(values, current, label, onPick) {
	const sel = el('select', {});
	for (const v of values) {
		const o = el('option', { value: String(v) }, label ? label(v) : String(v));
		if (String(v) === String(current)) o.selected = true;
		sel.append(o);
	}
	sel.addEventListener('change', () => onPick(sel.value));
	return sel;
}

/**
 * The colours, as swatches rather than a list of words.
 *
 * Ten colours are quicker to tell apart by eye than by name, and the name is
 * there for anyone who cannot see the difference -- as the button's title, so
 * it reaches a screen reader as well as a tooltip.
 */
function swatches(current, onPick) {
	const wrap = el('div', { className: 'shape-swatches' });
	const one = (value, style, title) => {
		const b = el('button', {
			type: 'button', className: `shape-swatch${current === value ? ' is-on' : ''}`,
			title, 'aria-label': title, 'aria-pressed': String(current === value),
		});
		if (style) b.style.background = style;
		else b.classList.add('is-none');
		b.addEventListener('click', () => onPick(value));
		return b;
	};
	wrap.append(one(NO_COLOR, null, 'none'));
	for (const name of SHAPE_COLORS) wrap.append(one(name, `var(--shape-${name})`, name));
	return wrap;
}

/** A switch, as the settings dialogs elsewhere draw one. */
function toggle(label, on, onSet) {
	const box = el('input', { type: 'checkbox' });
	box.checked = !!on;
	box.addEventListener('change', () => onSet(box.checked));
	return el('label', { className: 'shape-toggle' }, box, label);
}

/** A number, bounded, applied as it is typed but only when it is a number. */
function number(value, min, max, onSet) {
	const input = el('input', {
		type: 'number', className: 'shape-number',
		min: String(min), max: String(max), value: String(Math.round(value)),
	});
	const apply = () => {
		const v = Number(input.value);
		if (!Number.isFinite(v)) return;
		onSet(Math.min(max, Math.max(min, v)));
	};
	input.addEventListener('change', apply);
	return input;
}

/**
 * Opens the settings for one shape, or for several at once.
 *
 * @param {object} opts
 * @param {() => object|null} opts.read   the first shape's settings, read fresh
 * @param {number} opts.count             how many are selected
 * @param {(patch: object) => void} opts.onChange
 */
export function openShapeSettings({ read, count, onChange }) {
	let modal = null;
	const set = (patch) => {
		onChange(patch);
		// Re-read rather than trusting the patch: `updateShape` bounds what it
		// is given, and a field that showed 9,000 after the model stored 4,000
		// would be lying about the shape.
		modal?.refresh();
	};

	modal = openModal({
		info: dialogInfo('shape'),
		title: () => {
			const sh = read();
			const name = FIGURES[sh?.figure]?.label ?? 'Shape';
			return count > 1 ? `${count} shapes` : name;
		},
		subtitle: () => (count > 1
			? 'Showing the first one’s settings; changing one changes all of them.'
			: 'Every change applies at once — there is nothing to confirm.'),
		build: (body) => {
			const sh = read();
			if (!sh) {
				body.append(el('p', { className: 'hint' }, 'That shape is gone.'));
				return;
			}
			const figure = FIGURES[sh.figure] ?? null;

			// --- what it is ------------------------------------------------
			body.append(el('h3', { className: 'shape-head' }, 'Shape'));
			const byGroup = new Map(FIGURE_GROUPS.map((g) => [g, []]));
			for (const [key, f] of Object.entries(FIGURES)) {
				if (!byGroup.has(f.group)) byGroup.set(f.group, []);
				byGroup.get(f.group).push([key, f.label]);
			}
			const pick = el('select', {});
			for (const [group, entries] of byGroup) {
				if (!entries.length) continue;
				const og = el('optgroup', { label: group });
				for (const [key, label] of entries) {
					const o = el('option', { value: key }, label);
					if (key === sh.figure) o.selected = true;
					og.append(o);
				}
				pick.append(og);
			}
			pick.addEventListener('change', () => set({ figure: pick.value }));
			body.append(row('Figure', 'what it is drawn as', pick));

			body.append(row('Size', 'in model units, before the zoom',
				number(Math.abs(sh.w), SHAPE_MIN, SHAPE_MAX, (w) => set({ w: sh.w < 0 ? -w : w })),
				el('span', { className: 'shape-times' }, '×'),
				number(Math.abs(sh.h), SHAPE_MIN, SHAPE_MAX, (h) => set({ h: sh.h < 0 ? -h : h }))));

			body.append(row('Flip', 'mirror it',
				toggle('left to right', sh.flip_x, (v) => set({ flip_x: v })),
				toggle('top to bottom', sh.flip_y, (v) => set({ flip_y: v }))));

			// --- how it is painted -----------------------------------------
			body.append(el('h3', { className: 'shape-head' }, 'Colour'));
			body.append(row('Fill', 'the inside', swatches(sh.fill, (v) => set({ fill: v }))));
			body.append(row('Line', 'the outline', swatches(sh.line, (v) => set({ line: v }))));
			body.append(row('Line style', null,
				choose(SHAPE_DASHES, sh.dash, (d) => DASH_LABEL[d] ?? d, (v) => set({ dash: v })),
				choose(SHAPE_WIDTHS, sh.line_width, (w) => `${w} px`,
					(v) => set({ line_width: Number(v) }))));

			// --- what it says ----------------------------------------------
			body.append(el('h3', { className: 'shape-head' }, 'Label'));
			const text = el('textarea', {
				className: 'shape-text', rows: '3', spellcheck: 'false',
				placeholder: figure?.text === 'note' ? 'Write on the note…' : 'No label',
			});
			text.value = sh.text ?? '';
			// On input, not on change: the note is behind the dialog and the
			// point of typing on it is to watch it fill up.
			text.addEventListener('input', () => onChange({ text: text.value }));
			const textRow = row('Text', 'as many lines as you like', text);
			textRow.classList.add('is-full');
			body.append(textRow);

			body.append(row('Size', 'of the text',
				choose(SHAPE_TEXT_SIZES, sh.text_size, (s) => `${s} px`,
					(v) => set({ text_size: Number(v) }))));
			body.append(row('Face', null,
				choose(SHAPE_TEXT_FONTS, sh.text_font, (f) => FONT_LABEL[f] ?? f,
					(v) => set({ text_font: v }))));
			body.append(row('Alignment', null,
				choose(SHAPE_TEXT_ALIGNS, sh.text_align, (a) => ALIGN_LABEL[a] ?? a,
					(v) => set({ text_align: v }))));
			body.append(row('Weight', null,
				toggle('bold', sh.text_bold, (v) => set({ text_bold: v })),
				toggle('italic', sh.text_italic, (v) => set({ text_italic: v }))));

			body.append(el('p', { className: 'hint shape-foot' },
				'Bringing it to the front, duplicating it and deleting it are on its '
				+ 'right-click menu: they are things done ', el('i', {}, 'to'),
				' a shape rather than settings of one.'));
		},
	});
	return modal;
}
