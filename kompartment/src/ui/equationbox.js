/**
 * The box an equation is typed in.
 *
 * One line at rest, like every other field of a form, and the whole equation
 * while it is being written. Equations are written on one line and they are
 * long -- `x0*exp(-zeta*omega*time())*(cos(omega_d*time()) + ...)` is 89
 * characters, and one read in from another tool's file can run to a few
 * hundred -- and a one-line box half a window wide shows the first forty of
 * them, so the rest is edited by walking a caret through text that cannot be
 * seen. A column of a per-index grid shows thirty.
 *
 * So the box opens when it takes the keyboard. It grows to the right as far as
 * the text needs and the panel it is in leaves room for, then wraps the text
 * and grows down, up to a cap past which it scrolls. It is drawn over what lies
 * below and beside it rather than pushing that away, so nothing else in the
 * form moves, and when it is left it is one line again. Opened by a press, it
 * waits for the release: the caret goes where the click was, in the box that
 * was seen, and a drag selects what it was dragged across.
 *
 * It is a <textarea>, since an <input> cannot wrap, and the ways a textarea
 * differs from a one-line input are taken back out:
 *
 *  - a line break is not part of an equation. Enter commits the field, as it
 *    does an <input>, by raising `change`, which is what every caller listens
 *    for; a break in pasted text becomes a space and one at the end is
 *    dropped, which is what an <input> does with them; and one in a value
 *    given to the box is taken out, as an <input>'s value takes it out.
 *    The browser raises `change` of its own when the box is left, which after
 *    an Enter would be the same edit twice, so a `change` that carries no new
 *    text is stopped here.
 *  - Home and End go to the start and the end of the equation: not of the
 *    line the wrapping put the caret on, and not, as in a Mac's text fields,
 *    nowhere -- there they scroll the page and leave the caret where it was.
 *    With Shift they select to it. Taken before the completion list sees
 *    them, which closes: the caret has left the word it was completing.
 *  - Down is the other way of asking for the list (see ./complete.js), except
 *    where it has a line to go down to.
 */

import { el, visibleBox } from './parts.js';
import { completionIsOpen, closeCompletion } from './complete.js';

/** Room for the caret at the end of the longest line. */
const SLACK = 3;
/** How close an open box comes to an edge with no padding of its own. */
const MARGIN = 6;

const BREAK = /[\r\n]/;

/** A value as an <input> holds it: without its line breaks. */
const oneLine = (text) => String(text ?? '').replace(/[\r\n]/g, '');

/** Every line break a space. */
const spaced = (text) => text.replace(/\r\n|[\r\n]/g, ' ');

const px = (v) => parseFloat(v) || 0;

/**
 * How wide `text` is on one line in the field's font.
 *
 * Measured on a copy of the text rather than read off the field: a textarea's
 * scroll width counts the padding on its left and not the one on its right,
 * which is not something to build a width on.
 */
function textWidth(box, cs, text) {
	const probe = el('span', {}, text);
	Object.assign(probe.style, {
		position: 'absolute', left: '0', top: '0', visibility: 'hidden', whiteSpace: 'pre',
		fontFamily: cs.fontFamily, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
		fontStyle: cs.fontStyle, letterSpacing: cs.letterSpacing,
	});
	box.append(probe);
	const width = probe.getBoundingClientRect().width;
	probe.remove();
	return width;
}

/**
 * Where an open box has to stop on the right: the inside edge of the nearest
 * thing around it that would cut it off -- the window's body, a grid that
 * scrolls -- less that thing's padding, or the edge of what can be seen.
 */
function roomRight(box) {
	for (let n = box.parentElement; n && n !== document.body; n = n.parentElement) {
		const cs = getComputedStyle(n);
		if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
		const r = n.getBoundingClientRect();
		const pad = Math.max(parseFloat(cs.paddingRight) || 0, MARGIN);
		return r.left + n.clientLeft + n.clientWidth - pad;
	}
	return visibleBox().right - MARGIN;
}

/**
 * An equation box.
 *
 * Given `colour`, the equation is drawn in colour: a copy of its text under
 * the field, each part in a span, and the field's own text made invisible
 * over it, as the JSON tab's box is (./jsoneditor.js) -- so the caret, the
 * selection, undo and paste are still the textarea's own. The copy is laid
 * out by the same rules as the field, at rest and open, and is moved with it
 * when it scrolls.
 *
 * @param {{value?: string, className?: string, placeholder?: string,
 *   title?: string, colour?: (text: string) => Array<{text: string,
 *   part: string|null, kind?: string}>, muted?: boolean}} [opts]
 *   `className` goes on the text field, which is what carries the look of a
 *   field -- invalid, inherited -- and what listeners go on. `colour` says
 *   what each part of the text is (`equationColourer` in
 *   ../domain/edit.js); `muted` draws all of it in the colour of a value that
 *   is inherited rather than set.
 * @returns {{box: HTMLElement, field: HTMLTextAreaElement}} the box goes in
 *   the form; the field is the control
 */
export function equationBox({
	value = '', className = '', placeholder = '', title = '', colour = null, muted = false,
} = {}) {
	const field = el('textarea', {
		className: `eq-field mono${className ? ` ${className}` : ''}`,
		rows: 1,
		spellcheck: false,
		placeholder,
	});
	if (title) field.title = title;
	field.value = oneLine(value);
	const box = el('div', { className: 'eq-box' }, field);

	const copy = colour
		? el('div', { className: `eq-hl${muted ? ' is-muted' : ''}`, 'aria-hidden': 'true' })
		: null;
	if (copy) {
		box.prepend(copy);
		box.classList.add('is-coloured');
	}
	/** The copy where the field is: scrolled sideways under a drag at rest, down past an open box's cap. */
	const follow = () => {
		if (!copy) return;
		copy.scrollTop = field.scrollTop;
		copy.scrollLeft = field.scrollLeft;
	};
	const paint = () => {
		if (!copy) return;
		copy.replaceChildren(...colour(field.value).map((p) => (p.part
			? el('span', { className: `eqh-${p.part}${p.kind ? ` eqh-${p.kind}` : ''}` }, p.text)
			: document.createTextNode(p.text))));
		follow();
	};
	paint();
	field.addEventListener('scroll', follow);

	const isOpen = () => box.classList.contains('is-open');

	/** As wide as the text on one line, within the room; then as tall as it wraps. */
	const fit = () => {
		const at = box.getBoundingClientRect();
		const room = Math.max(at.width, roomRight(box) - at.left);
		const cs = getComputedStyle(field);
		// An empty box shows what it inherits as its placeholder, and shows
		// all of that too.
		const needed = textWidth(box, cs, field.value || field.placeholder)
			+ px(cs.paddingLeft) + px(cs.paddingRight) + px(cs.borderLeftWidth) + px(cs.borderRightWidth);
		const wide = needed > at.width ? Math.min(needed + SLACK, room) : at.width;
		field.style.width = `${wide}px`;
		// As many lines as the text wraps to at that width, measured with no
		// scrollbar to take a column of it away. Counted in lines because the
		// scroll height is a whole number of pixels and a line is not: a box of
		// one line is then exactly the height it was at rest.
		field.style.overflow = 'hidden';
		field.style.height = '0px';
		const pads = px(cs.paddingTop) + px(cs.paddingBottom);
		const inner = field.scrollHeight - pads;
		const line = px(cs.lineHeight);
		const tall = Math.max(at.height, (line ? Math.max(1, Math.round(inner / line)) * line : inner)
			+ pads + px(cs.borderTopWidth) + px(cs.borderBottomWidth));
		field.style.overflow = '';
		field.style.height = `${tall}px`;
		if (copy) {
			copy.style.width = field.style.width;
			copy.style.height = field.style.height;
			// The copy never scrolls of itself -- given a scrollbar the moment
			// it opened, before it was wide, it kept it and wrapped narrower
			// than the field -- so the field's, when past the cap it has one,
			// is made up as padding, and the two wrap at the same width.
			const bar = field.offsetWidth - field.clientWidth
				- px(cs.borderLeftWidth) - px(cs.borderRightWidth);
			copy.style.paddingRight = bar > 0 ? `${px(cs.paddingRight) + bar}px` : '';
			follow();
		}
		// Lifted off the form only when it is bigger than the box it came out of.
		box.classList.toggle('is-grown', wide > at.width + 0.5 || tall > at.height + 0.5);
	};

	const open = () => {
		if (isOpen() || document.activeElement !== field) return;
		// The room it leaves in the form, held while it is out of the flow.
		box.style.height = `${box.getBoundingClientRect().height}px`;
		box.classList.add('is-open');
		fit();
		// All of it in sight: a box near the foot of a window or a grid scrolls
		// them up by what it grew.
		field.scrollIntoView({ block: 'nearest', inline: 'nearest' });
	};

	const close = () => {
		if (!isOpen()) return;
		box.classList.remove('is-open', 'is-grown');
		box.style.height = '';
		field.style.width = '';
		field.style.height = '';
		if (copy) {
			copy.style.width = '';
			copy.style.height = '';
			copy.style.paddingRight = '';
		}
		// A box at rest shows where its equation starts.
		field.scrollTop = 0;
		field.scrollLeft = 0;
		follow();
	};

	// A press opens it on the release, after the click has put the caret down
	// and a drag has finished selecting. Every other way in -- Tab, the focus
	// given back after the form is rebuilt -- opens it at once.
	let pressing = false;
	field.addEventListener('pointerdown', (ev) => {
		if (isOpen() || ev.button !== 0) return;
		pressing = true;
		const release = () => {
			window.removeEventListener('pointerup', release, true);
			window.removeEventListener('pointercancel', release, true);
			setTimeout(() => { pressing = false; open(); });
		};
		window.addEventListener('pointerup', release, true);
		window.addEventListener('pointercancel', release, true);
	});
	field.addEventListener('focus', () => { if (!pressing) open(); });
	field.addEventListener('blur', close);

	field.addEventListener('beforeinput', (ev) => {
		if (ev.inputType === 'insertLineBreak' || ev.inputType === 'insertParagraph') ev.preventDefault();
	});
	// First among the listeners, so that the completion list and the caller
	// see the text as it will stay, and the box its size. A paste or a drop
	// is taken as an <input> takes it: the line breaks at the end dropped,
	// and every other one a space.
	field.addEventListener('input', () => {
		if (BREAK.test(field.value)) {
			const text = spaced(field.value.replace(/[\r\n]+$/, ''));
			const caret = Math.min(spaced(field.value.slice(0, field.selectionEnd)).length, text.length);
			field.value = text;
			field.setSelectionRange(caret, caret);
		}
		paint();
		if (isOpen()) fit();
	});

	let committed = field.value;
	field.addEventListener('change', (ev) => {
		if (field.value === committed) {
			ev.stopImmediatePropagation();
			return;
		}
		committed = field.value;
	});

	// In the capture phase, so that these run before the completion list's
	// own keys, whatever order the two were attached in.
	field.addEventListener('keydown', (ev) => {
		if (ev.isComposing || ev.defaultPrevented) return;
		if (ev.key === 'Enter') {
			// With the list open, Enter is the list's: it takes the row.
			if (completionIsOpen(field)) return;
			ev.preventDefault();
			if (field.value !== committed) field.dispatchEvent(new Event('change', { bubbles: true }));
			return;
		}
		if ((ev.key === 'Home' || ev.key === 'End') && !ev.altKey) {
			ev.preventDefault();
			if (completionIsOpen(field)) closeCompletion();
			const end = ev.key === 'End';
			const to = end ? field.value.length : 0;
			if (ev.shiftKey) {
				const anchor = field.selectionDirection === 'backward'
					? field.selectionEnd : field.selectionStart;
				if (to < anchor) field.setSelectionRange(to, anchor, 'backward');
				else field.setSelectionRange(anchor, to, 'forward');
			} else {
				field.setSelectionRange(to, to);
			}
			// The caret in sight, in a box tall enough to scroll.
			field.scrollTop = end ? field.scrollHeight : 0;
			return;
		}
		// Down asks for the list at the end of the equation, or in a box of one
		// line; anywhere else it is the textarea's, and goes down a line.
		if (ev.key === 'ArrowDown' && !ev.altKey && !completionIsOpen(field)
			&& isOpen() && field.selectionEnd < field.value.length
			&& field.offsetHeight > box.offsetHeight + 1) {
			ev.stopImmediatePropagation();
		}
	}, true);

	return { box, field };
}
