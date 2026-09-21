/**
 * A pop-up menu, for right-clicking things on the diagram.
 *
 * Plain HTML over the SVG rather than anything drawn in it: a menu wants text
 * that wraps, a scrollbar when a model has fifty compartments, and keyboard
 * focus, and all three come free here.
 *
 * The two things a menu has to get right are dismissal and staying on screen.
 * Every way out closes it -- a click anywhere else, Escape, a second
 * right-click, scrolling, resizing, losing the window -- because a menu left
 * behind over a diagram is worse than no menu. Placement measures itself after
 * mounting and flips when it would run off an edge, which is the only way to
 * know: a submenu's width depends on the longest block name in the model.
 */

import { el } from './parts.js';

/** The menu currently open, if any. Only ever one. */
let current = null;

/**
 * Closing a submenu is delayed; opening one is not.
 *
 * The pointer cannot get from a parent item to its submenu without crossing
 * whatever lies between them -- the item below it, the separator, the gap at
 * the panel's edge -- and treating any of that as "you have left" closed the
 * submenu before it could be reached. So leaving only *schedules* a close,
 * and arriving anywhere in the submenu cancels it.
 */
let closeTimer = null;
const SUBMENU_GRACE = 320;

function cancelSubClose() {
	if (closeTimer) clearTimeout(closeTimer);
	closeTimer = null;
}

function scheduleSubClose(panel) {
	cancelSubClose();
	closeTimer = setTimeout(() => {
		closeTimer = null;
		closeSubsBelow(panel);
	}, SUBMENU_GRACE);
}

export function closeMenu() {
	cancelSubClose();
	if (!current) return;
	const { root, cleanup, opener } = current;
	current = null;
	cleanup();
	// Only when the focus is about to be lost with the menu: a click on some
	// other control has already put it where the user wanted it.
	const inMenu = root.contains(document.activeElement) || document.activeElement === document.body;
	root.remove();
	if (inMenu && opener && opener !== document.body && opener.isConnected
		&& typeof opener.focus === 'function') {
		opener.focus({ preventScroll: true });
	}
}

export function menuIsOpen() {
	return !!current;
}

/**
 * @typedef {object} MenuItem
 * @property {string} [label]      the text; omit with `separator`
 * @property {boolean} [separator] a rule between groups
 * @property {Function} [onPick]   what it does
 * @property {string} [heading]  a label over the items that follow, rather than
 *   an item of its own: not focusable, and the arrow keys walk past it
 * @property {MenuItem[]} [items]  a submenu, opened by hover, click or ArrowRight
 * @property {boolean} [disabled]  shown, but not choosable, and it says why
 * @property {string} [hint]       trailing text: the reason, or a shortcut
 * @property {string} [swatch]     a CSS colour, shown as a square before the
 *   label -- for a menu whose items *are* colours
 * @property {boolean} [danger]    destructive, styled apart
 * @property {boolean|Function} [checked]  draws a tick; a function is re-read
 *   after each pick, so a `keepOpen` toggle updates in place
 * @property {boolean} [keepOpen]   a setting rather than an action: the menu
 *   stays up, because you rarely change only one
 * @property {string} [title]      tooltip
 *
 * @param {{x: number, y: number, items: MenuItem[], title?: string}} opts
 */
export function openMenu({ x, y, items, title = '' }) {
	closeMenu();

	const root = el('div', { className: 'menu-layer' });
	const panel = buildPanel(items, title);
	root.append(panel);
	document.body.append(root);
	place(panel, x, y);

	/**
	 * Whether an event happened inside the menu.
	 *
	 * Against the whole layer, not just the top panel: a submenu is a sibling
	 * of it, so testing the panel alone counted a submenu as outside. `contains`
	 * only accepts a Node, and an event dispatched at the window itself has a
	 * target that is not one -- letting that throw would abort the listener and
	 * leave the menu stuck open.
	 */
	const inside = (ev) => {
		const t = ev.target;
		return t instanceof Node && root.contains(t);
	};

	// Dismissal. `pointerdown` rather than `click`, so the menu is gone before
	// whatever is underneath begins a drag.
	const onDown = (ev) => {
		if (!inside(ev)) closeMenu();
	};
	const onKey = (ev) => {
		if (ev.key === 'Escape') { ev.stopPropagation(); closeMenu(); }
	};
	const onBlur = () => closeMenu();
	// Scrolling *the page* moves the diagram out from under the menu, so it
	// closes. Scrolling the menu itself is how you reach the items past the
	// bottom of it -- a long menu has its own scrollbar -- and closing then
	// made those items unreachable: the wheel dismissed it, and dragging the
	// scrollbar dismissed it before the drag could move anywhere.
	//
	// And not the scroll the *opening* caused. Right-clicking a block in the
	// tree selects it first, which reveals its row -- and if that row was
	// below the fold, the panel scrolled and took the menu with it before it
	// could be read. Only a scroll that happens after the gesture has settled
	// is the user scrolling away from the menu; `scrollIntoView` lands within
	// a frame or two of the click that caused it.
	const opened = performance.now();
	const SETTLE = 300;
	const onScrollAway = (ev) => {
		if (inside(ev)) return;
		if (performance.now() - opened < SETTLE) return;
		closeMenu();
	};
	window.addEventListener('pointerdown', onDown, true);
	window.addEventListener('keydown', onKey, true);
	window.addEventListener('blur', onBlur);
	window.addEventListener('resize', onBlur);
	window.addEventListener('wheel', onScrollAway, { passive: true, capture: true });
	document.addEventListener('scroll', onScrollAway, true);

	current = {
		root,
		// Where the keyboard was when the menu opened, to be given it back
		// when the menu closes: `closeMenu` removes the element that holds
		// the focus, which otherwise falls to the body, and the next Tab
		// starts again from the top of the page.
		opener: document.activeElement,
		cleanup() {
			window.removeEventListener('pointerdown', onDown, true);
			window.removeEventListener('keydown', onKey, true);
			window.removeEventListener('blur', onBlur);
			window.removeEventListener('resize', onBlur);
			window.removeEventListener('wheel', onScrollAway, true);
			document.removeEventListener('scroll', onScrollAway, true);
		},
	};

	panel.querySelector('.menu-item:not([disabled])')?.focus();
	return root;
}

function buildPanel(items, title, { isSub = false } = {}) {
	const panel = el('div', { className: 'menu-panel', role: 'menu' });
	if (title) panel.append(el('div', { className: 'menu-title' }, title));

	for (const item of items) {
		if (item.separator) {
			panel.append(el('div', { className: 'menu-sep' }));
			continue;
		}
		// A heading over a run of items, for a group whose members do not say
		// what they are on their own: `Compartment` under `ADD HERE` rather
		// than `Add compartment here` repeated six times down the menu. Not a
		// control -- it takes no focus and the arrow keys walk past it, which
		// is why it is a div and the items are buttons.
		if (item.heading) {
			panel.append(el('div', { className: 'menu-heading' }, item.heading));
			continue;
		}
		panel.append(buildItem(item, panel, isSub));
	}
	panel.addEventListener('keydown', (ev) => onPanelKey(ev, panel));
	// Anywhere in a submenu counts as arriving, including its title, its
	// separators and the padding around its items.
	if (isSub) panel.addEventListener('pointerenter', cancelSubClose);
	return panel;
}

function buildItem(item, panel, isSub = false) {
	const hasSub = !!item.items?.length;
	const btn = el('button', {
		className: `menu-item${item.danger ? ' is-danger' : ''}`
			+ `${hasSub ? ' has-sub' : ''}`,
		type: 'button',
		role: 'menuitem',
		disabled: !!item.disabled,
		title: item.title ?? '',
	},
	// The tick has a column of its own, so labels line up whether or not the
	// menu holds any checkable items.
	item.checked !== undefined
		? el('span', { className: 'menu-tick' }, isChecked(item) ? '\u2713' : '')
		: null,
	// A colour, for a menu that offers colours: ten of them are told apart by
	// eye long before the words are read. The word stays, for the readers who
	// cannot tell two of them apart.
	item.swatch
		? Object.assign(el('span', { className: 'menu-swatch' }),
			{ style: `background:${item.swatch}` })
		: null,
	el('span', { className: 'menu-label' }, item.label),
	item.hint ? el('span', { className: 'menu-hint' }, item.hint) : null,
	hasSub ? el('span', { className: 'menu-arrow' }, '›') : null);

	btn._menuItem = item;

	if (hasSub) {
		btn.setAttribute('aria-haspopup', 'menu');
		const open = () => {
			cancelSubClose();
			// Already showing this one: reopening would rebuild it under the
			// pointer, which is how a submenu loses the hover it just gained.
			if (btn.classList.contains('is-open')) return;
			openSub(btn, item.items, panel);
		};
		btn.addEventListener('pointerenter', open);
		// Focus deliberately does *not* open it. Coming back out of a submenu
		// with ArrowLeft focuses the parent item, and an opening focus handler
		// reopened the submenu the keypress had just closed. The keyboard way
		// in is ArrowRight or Enter, which is what a menu is expected to do.
		btn.addEventListener('click', () => {
			open();
			panel.parentElement?.querySelector('.menu-sub')
				?.querySelector('.menu-item:not([disabled])')?.focus();
		});
	} else {
		btn.addEventListener('click', () => {
			if (item.keepOpen) {
				// A setting: act, then show the new state where it was read.
				item.onPick?.();
				const tick = btn.querySelector('.menu-tick');
				if (tick) tick.textContent = isChecked(item) ? '\u2713' : '';
				refreshSiblingTicks(panel);
				return;
			}
			// Close first: an action that re-renders the diagram would
			// otherwise leave the menu floating over the result.
			closeMenu();
			item.onPick?.();
		});
		// Only an item in the top panel dismisses an open submenu, and only
		// after the grace period: an item inside a submenu must never close
		// the submenu the pointer is in.
		if (!isSub) btn.addEventListener('pointerenter', () => scheduleSubClose(panel));
	}
	return btn;
}

function isChecked(item) {
	return typeof item.checked === 'function' ? !!item.checked() : !!item.checked;
}

/**
 * Re-reads every tick in a panel.
 *
 * A group of settings can be exclusive -- the transfer-label modes are one of
 * three -- so picking one changes the tick on a sibling, not only on the item
 * that was clicked.
 */
function refreshSiblingTicks(panel) {
	for (const btn of panel.querySelectorAll('.menu-item')) {
		const tick = btn.querySelector('.menu-tick');
		if (tick && btn._menuItem) tick.textContent = isChecked(btn._menuItem) ? '\u2713' : '';
	}
}

function openSub(btn, items, panel) {
	// The panel may be gone by the time this runs. A submenu opens on
	// `pointerenter`, and a right-click whose release lands on a submenu item
	// dismisses the menu with that hover already queued -- so this was a
	// TypeError on `panel.parentElement.append` that took the gesture down
	// with it and left the diagram with no menu and no explanation.
	if (!panel.parentElement) return null;
	closeSubsBelow(panel);
	const sub = buildPanel(items, '', { isSub: true });
	sub.classList.add('menu-sub');
	sub.dataset.parent = '1';
	panel.parentElement.append(sub);
	const r = btn.getBoundingClientRect();
	// Overlap the parent by a few pixels: a gap between the two is a place for
	// the pointer to fall through and dismiss the submenu on its way across.
	place(sub, r.right - 4, r.top - 4, { preferLeftOf: r.left + 4 });
	btn.classList.add('is-open');
	return sub;
}

function closeSubsBelow(panel) {
	cancelSubClose();
	if (!panel.parentElement) return;
	for (const s of panel.parentElement.querySelectorAll('.menu-sub')) {
		// Every panel is a sibling in one container, so "below" cannot be read
		// off the DOM -- but the one thing that is certainly not below this
		// panel is the panel itself. A submenu inside a submenu asked for its
		// own parent to be closed, which took the box out from under the thing
		// being opened: `panel.parentElement.append` then threw, and the menu
		// vanished mid-gesture with nothing said.
		if (s !== panel) s.remove();
	}
	for (const b of panel.querySelectorAll('.menu-item.is-open')) b.classList.remove('is-open');
}

function onPanelKey(ev, panel) {
	const items = [...panel.querySelectorAll('.menu-item:not([disabled])')];
	const at = items.indexOf(document.activeElement);
	if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
		ev.preventDefault();
		const step = ev.key === 'ArrowDown' ? 1 : -1;
		items[(at + step + items.length) % items.length]?.focus();
		return;
	}
	if (ev.key === 'ArrowRight' && items[at]?.classList.contains('has-sub')) {
		ev.preventDefault();
		items[at].click();
		return;
	}
	if (ev.key === 'ArrowLeft' && panel.classList.contains('menu-sub')) {
		ev.preventDefault();
		const parent = panel.parentElement.querySelector('.menu-item.is-open');
		panel.remove();
		parent?.classList.remove('is-open');
		parent?.focus();
	}
}

/** Keeps a panel on screen, flipping rather than sliding where it can. */
function place(panel, x, y, { preferLeftOf = null } = {}) {
	const pad = 6;
	panel.style.left = '0px';
	panel.style.top = '0px';
	const { width, height } = panel.getBoundingClientRect();
	const maxX = window.innerWidth - pad;
	const maxY = window.innerHeight - pad;

	let left = x;
	if (left + width > maxX) {
		left = preferLeftOf != null ? preferLeftOf - width : maxX - width;
	}
	let top = y;
	if (top + height > maxY) top = Math.max(pad, maxY - height);

	panel.style.left = `${Math.max(pad, left)}px`;
	panel.style.top = `${Math.max(pad, top)}px`;
}
