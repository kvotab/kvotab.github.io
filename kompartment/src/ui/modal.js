/**
 * A modal dialog.
 *
 * Built on the browser's own `<dialog>`, so Escape, the backdrop, the focus
 * trap and the inertness of everything behind it come for free rather than
 * being re-implemented badly.
 *
 * The one thing added is `refresh`: what a dialog here holds is an editor over
 * the live model, and an edit in it can change what the form should show --
 * ticking an index list adds a grid, renaming a block changes the title. The
 * caller hands over a `build` function rather than a finished node, and the
 * dialog runs it again whenever it is told to.
 */

import { el } from './parts.js';
import { infoButton, closeInfo } from './infopanel.js';

/**
 * The dialogs on screen, innermost last.
 *
 * A stack rather than a single slot, because a dialog can open another and the
 * one underneath has to come back: editing a distribution from a parameter's
 * settings and closing it should land back in the settings, not on the diagram
 * with the settings gone. `<dialog>` nests natively -- `showModal` over an open
 * dialog puts the new one on top and makes the old one inert -- so all this
 * has to do is remember the order and not close what it did not open.
 *
 * Replacing one dialog with another is still possible and is still what some
 * callers want; it is spelled `closeModal()` and then `open…`, which is what
 * they already did. *"the dialog gets out of the way"*, says the one that
 * opens the index lists.
 */
const stack = [];

/**
 * Whether this Escape has already shut something.
 *
 * Chrome sends the close request to *every* open dialog for one press rather
 * than only to the topmost, so opening a distribution over a parameter's
 * settings and pressing Escape once closed both -- verified at this module,
 * with no application code in the way, and with a real click first in case it
 * was user activation. So the press is claimed by the first dialog to see it,
 * and the ones underneath refuse.
 *
 * Reset on a macrotask rather than after a delay: every close request from one
 * press is dispatched in the same task, and a second press is a new one. So
 * two quick presses still close two dialogs, and no timing is guessed at.
 */
let escapeTaken = false;
function claimEscape() {
	if (escapeTaken) return false;
	escapeTaken = true;
	setTimeout(() => { escapeTaken = false; }, 0);
	return true;
}

/**
 * Closing by pressing the backdrop -- and *only* by pressing the backdrop.
 *
 * A `<dialog>` shown modally has no wrapper: the element is the box, and the
 * backdrop is its own pseudo-element, so a press out there is reported against
 * the dialog itself while a press on anything inside is reported against that
 * thing. `ev.target === dialog` is therefore the test for "on the backdrop".
 *
 * WHY NOT `click`. A click event is dispatched on the nearest common ancestor
 * of where the press began and where it ended. Select the text of a field by
 * dragging out past the edge of the box and the release lands on the backdrop,
 * so the common ancestor is the dialog -- indistinguishable, to a `click`
 * handler, from a press on the backdrop. The window shut in the middle of an
 * edit, which is the one moment it must not.
 *
 * So both ends of the gesture have to be on the backdrop: a press that starts
 * inside never dismisses however it ends, and one that starts on the backdrop
 * and is dragged into the box does not either.
 */
export function dismissOnBackdrop(dialog, close) {
	let pressed = false;
	dialog.addEventListener('pointerdown', (ev) => {
		// The primary button only: a right-click on the backdrop is a context
		// menu, not a dismissal.
		pressed = ev.target === dialog && (ev.button ?? 0) === 0;
	});
	dialog.addEventListener('pointerup', (ev) => {
		const dismiss = pressed && ev.target === dialog;
		pressed = false;
		if (dismiss) close();
	});
	// A press whose release never arrives here -- the pointer left the window,
	// or something took capture of it -- must not leave the flag standing for
	// whatever is pressed next.
	dialog.addEventListener('pointercancel', () => { pressed = false; });
}

/**
 * @param {object} opts
 * @param {() => string} opts.title       read again on every refresh
 * @param {() => string} [opts.subtitle]
 * @param {(body: HTMLElement) => void} opts.build fills the scrolling body
 * @param {() => void} [opts.onClose]
 * @param {boolean} [opts.wide] for a dialog that is panes rather than a form
 * @param {{key: string, topic: object|(() => object)}|null} [opts.info]  what the
 *   dialog is for, behind an (i) in its title bar -- see ./dialoginfo.js
 * @returns {{close: Function, refresh: Function, dialog: HTMLDialogElement}}
 */
/** The controls a form is made of, in document order. */
const FOCUSABLE = 'input, select, textarea, button, [tabindex="0"]';

/** How to find a control again after the form around it has been rebuilt. */
function focusKey(body, active) {
	if (!active || active === document.body || !body.contains(active)) return null;
	const all = [...body.querySelectorAll(FOCUSABLE)];
	return {
		id: active.id || null,
		label: active.getAttribute('aria-label') || null,
		name: active.getAttribute('name') || null,
		at: all.indexOf(active),
		caret: typeof active.selectionStart === 'number' && /^(text|search|number|)$/.test(active.type ?? '')
			? [active.selectionStart, active.selectionEnd] : null,
	};
}

function refocus(body, key) {
	const all = [...body.querySelectorAll(FOCUSABLE)];
	const same = all.find((n) => (key.id && n.id === key.id)
		|| (key.label && n.getAttribute('aria-label') === key.label)
		|| (key.name && n.getAttribute('name') === key.name));
	const next = same ?? all[key.at] ?? null;
	if (!next) return;
	next.focus({ preventScroll: true });
	if (key.caret && typeof next.setSelectionRange === 'function') {
		try { next.setSelectionRange(key.caret[0], key.caret[1]); } catch { /* not a text field */ }
	}
}

/**
 * Puts a dialog where it already is, in coordinates it can then be moved in.
 *
 * A `<dialog>` is centred by the browser, and centring is what makes an open
 * one *move* when its contents change: a validation message appears under a
 * field, the dialog grows by a line, and it grows by half a line in each
 * direction -- so the field under the pointer shifts while it is being typed
 * into. Pinned to where it opened, it grows downwards like anything else.
 *
 * Measured after `showModal`, because that is when the browser has laid it out.
 */
function pin(dialog) {
	const r = dialog.getBoundingClientRect();
	dialog.style.margin = '0';
	dialog.style.left = `${Math.round(r.left)}px`;
	dialog.style.top = `${Math.round(r.top)}px`;
}

/** Keeps it on the screen, whatever was dragged where. */
function within(x, y, dialog) {
	const r = dialog.getBoundingClientRect();
	// A strip of the header stays reachable at every edge, so a dialog cannot
	// be dropped somewhere it can never be picked up again.
	const edge = 60;
	return {
		x: Math.min(window.innerWidth - edge, Math.max(edge - r.width, x)),
		y: Math.min(window.innerHeight - edge, Math.max(0, y)),
	};
}

/**
 * Dragging by the header.
 *
 * The header and not the whole dialog: everything else in one is a control, and
 * a form whose fields drag the window is a form that cannot be text-selected.
 * The close button is excluded for the same reason.
 */
function draggable(dialog, handle) {
	handle.addEventListener('pointerdown', (ev) => {
		if ((ev.button ?? 0) !== 0) return;
		if (ev.target.closest('button, input, select, textarea, a')) return;
		const r = dialog.getBoundingClientRect();
		const dx = ev.clientX - r.left;
		const dy = ev.clientY - r.top;
		handle.setPointerCapture(ev.pointerId);
		handle.classList.add('is-dragging');
		const move = (e) => {
			const at = within(e.clientX - dx, e.clientY - dy, dialog);
			dialog.style.left = `${Math.round(at.x)}px`;
			dialog.style.top = `${Math.round(at.y)}px`;
		};
		const done = () => {
			handle.classList.remove('is-dragging');
			handle.removeEventListener('pointermove', move);
			handle.removeEventListener('pointerup', done);
			handle.removeEventListener('pointercancel', done);
		};
		handle.addEventListener('pointermove', move);
		handle.addEventListener('pointerup', done);
		handle.addEventListener('pointercancel', done);
		// So the press is not also read as the start of a text selection.
		ev.preventDefault();
	});
}

/**
 * Pulling the corner.
 *
 * The dialog's width and the body's height are what the layout is made of --
 * the head is whatever it needs and the body takes the rest -- so those are
 * what a drag sets. Bounded below by something still usable and above by the
 * window, because a dialog dragged larger than the screen has no corner left
 * to drag back.
 */
function resizable(dialog, grip, body) {
	grip.addEventListener('pointerdown', (ev) => {
		if ((ev.button ?? 0) !== 0) return;
		const r = dialog.getBoundingClientRect();
		const startW = r.width;
		const startH = body.getBoundingClientRect().height;
		// The head, measured: it is taller with a subtitle, and a guess at it
		// let the body be pulled past the bottom of the window.
		const head = r.height - startH;
		const x0 = ev.clientX;
		const y0 = ev.clientY;
		grip.setPointerCapture(ev.pointerId);
		const move = (e) => {
			const w = Math.max(320, Math.min(window.innerWidth - r.left - 8,
				startW + (e.clientX - x0)));
			const h = Math.max(120, Math.min(window.innerHeight - r.top - head - 8,
				startH + (e.clientY - y0)));
			dialog.style.width = `${Math.round(w)}px`;
			// A dialog somebody has sized by hand is sized by hand: the cap on
			// its height is a share of the window, and it used to stop the drag
			// there, clipping whatever the body had been pulled out to.
			dialog.style.maxHeight = 'none';
			body.style.height = `${Math.round(h)}px`;
			body.style.maxHeight = `${Math.round(h)}px`;
		};
		const done = () => {
			grip.removeEventListener('pointermove', move);
			grip.removeEventListener('pointerup', done);
			grip.removeEventListener('pointercancel', done);
		};
		grip.addEventListener('pointermove', move);
		grip.addEventListener('pointerup', done);
		grip.addEventListener('pointercancel', done);
		ev.preventDefault();
	});
}

export function openModal({ title, subtitle, build, onClose, wide = false, info = null }) {
	// Where the keyboard was: a dialog opened with Enter on a diagram node
	// hands the focus back to that node when it closes, rather than dropping
	// it on the body so that the next Tab starts from the top of the page.
	const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;


	const heading = el('h2', { className: 'modal-title' });
	const sub = el('p', { className: 'modal-sub' });
	const body = el('div', { className: 'modal-body' });
	const close = el('button', {
		className: 'modal-close', type: 'button', title: 'Close (Esc)',
		'aria-label': 'Close',
	}, '×');

	// `wide` is for a dialog that is two panes rather than a form: the form
	// width is chosen so that a column of fields reads well, and a chooser
	// with a plan beside it needs the room instead.
	// What the dialog is for, behind an (i) beside the close button: see
	// ./infopanel.js, which opens its panel inside this dialog so that the
	// dialog's inertness does not reach it.
	const about = info?.key ? infoButton(info.key, info.topic) : null;
	const head = el('div', { className: 'modal-head' },
		el('div', { className: 'modal-heading' }, heading, sub), about, close);
	head.title = 'Drag to move this window';
	// The corner to pull. A native `resize` on the dialog is the obvious way
	// and cannot be used: `resize` needs `overflow` other than `visible`, and
	// the dialog clips its own rounded corners with `overflow: hidden`, which
	// puts the browser's grip under the clip and out of reach.
	const grip = el('div', { className: 'modal-grip', title: 'Drag to resize' });
	const dialog = el('dialog', { className: `modal${wide ? ' modal-wide' : ''}` },
		head, body, grip);

	const refresh = () => {
		// A string, or the nodes a title is made of: a block's title carries
		// its symbol, and a symbol is `<sub>` and `<sup>` elements rather than
		// text -- built, never `innerHTML`, since it comes out of a file.
		const heads = typeof title === 'function' ? title() : title;
		if (Array.isArray(heads)) heading.replaceChildren(...heads.filter((n) => n != null));
		else heading.textContent = heads ?? '';
		const s = typeof subtitle === 'function' ? subtitle() : subtitle;
		sub.textContent = s ?? '';
		sub.hidden = !s;
		// Editing in place, so the body is rebuilt where it stood: losing the
		// scroll position on every keystroke would make a long form unusable.
		// And the keyboard with it: every control in here is destroyed and
		// rebuilt, so the field that had the focus is found again by what it
		// is -- its label, its id -- or failing that by where it was, and
		// given the focus and the caret back. Without this, Tab out of an
		// equation box committed the edit, rebuilt the form, and dropped the
		// focus on the body, so the next Tab started from the Close button.
		const top = body.scrollTop;
		const had = focusKey(body, document.activeElement);
		// The height it had, kept for the length of the rebuild. Without it a
		// form whose fields come and go -- a validation line under an equation,
		// a section that opens when a box is ticked -- resizes under the
		// pointer between one keystroke and the next, and with the window
		// pinned in place that is a jump of the bottom edge rather than of
		// both. Released straight after, so growing is still possible and only
		// the flicker is gone.
		const was = body.getBoundingClientRect().height;
		if (was > 0) body.style.minHeight = `${Math.round(was)}px`;
		body.replaceChildren();
		build(body);
		body.scrollTop = top;
		if (had) refocus(body, had);
		requestAnimationFrame(() => { body.style.minHeight = ''; });
	};

	// Off the stack the moment it is asked to go, not when the browser gets
	// round to the `close` event -- that one is queued, and a caller that
	// closes a dialog and then edits the model would otherwise have its
	// `refreshModal` land on the dialog that is on its way out instead of the
	// one underneath. Which is exactly what the distribution editor does: it
	// closes, then saves.
	const drop = () => {
		const at = stack.findIndex((m) => m.dialog === dialog);
		if (at >= 0) stack.splice(at, 1);
	};

	// Escape, which the browser reports as a cancel before it closes anything.
	// Only the dialog on top may take it, and only once per press.
	dialog.addEventListener('cancel', (ev) => {
		if (stack[stack.length - 1]?.dialog !== dialog || !claimEscape()) {
			ev.preventDefault();
			return;
		}
		// The panel an (i) in here opened is in front of the window, so it is
		// what this press closes, wherever in the window the keyboard is; the
		// window goes on the next. (Chrome lets a page refuse a close request
		// only once per user activation, and pressing Escape is not one, so
		// the second press closes the window even when nothing was clicked in
		// between -- which is what it should do anyway.)
		if (dialog.querySelector(':scope > .info-panel')) {
			ev.preventDefault();
			closeInfo();
			return;
		}
		drop();
	});

	close.addEventListener('click', () => { drop(); dialog.close(); });
	dismissOnBackdrop(dialog, () => { drop(); dialog.close(); });
	dialog.addEventListener('close', () => {
		dialog.remove();
		drop();
		onClose?.();
		// Only if nothing else has taken it meanwhile, and the opener is still
		// on the page -- a block deleted from its own settings has no node to
		// go back to.
		if (opener?.isConnected && (document.activeElement === document.body || !document.activeElement)) {
			opener.focus();
		}
	});

	document.body.append(dialog);
	refresh();
	dialog.showModal();
	// Where the browser put it becomes where it *is*, so that everything after
	// -- a message appearing under a field, a section opening, a drag -- moves
	// it only when something asks it to.
	pin(dialog);
	draggable(dialog, head);
	resizable(dialog, grip, body);

	const handle = { dialog, refresh, close: () => { drop(); dialog.close(); } };
	stack.push(handle);
	return handle;
}

/**
 * Refreshes the innermost dialog.
 *
 * The one underneath is not rebuilt while something is over it: it is inert,
 * nobody is reading it, and it is refreshed when it comes back up -- by
 * whatever edit the dialog above it made, which reaches `republish` like any
 * other.
 */
export function refreshModal() {
	stack[stack.length - 1]?.refresh();
}

/** Closes the innermost dialog, which is the one a caller inside it means. */
export function closeModal() {
	stack[stack.length - 1]?.close();
}

/** Closes all of them: a new model has nothing to do with the old one's forms. */
export function closeAllModals() {
	while (stack.length) stack[stack.length - 1].close();
}

export function modalIsOpen() {
	return stack.length > 0;
}
