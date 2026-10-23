/**
 * The bar over the top of the diagram.
 *
 * Everything the Build panel can do is on the canvas's right-click menu, and
 * stays there. The bar puts what is reached for most a click away from it:
 * the blocks a model is mostly made of, what the diagram shows, and the zoom.
 * It floats over the top of the canvas rather than taking a row of its own, so
 * the diagram keeps the room, and it can be put away -- its ×, or Canvas ▸
 * Show toolbar -- which this browser remembers. Whether it is up is not the
 * model's business, so it is not saved with the model.
 *
 * A block from the menu lands where the menu was opened. One from the bar
 * lands in the middle of what is in view, on the nearest spot nothing is
 * drawn at; dragged off the bar, it lands where it is dropped, centred on the
 * pointer. The menus behind its buttons -- More, Show, Canvas, Picture -- are
 * the canvas menu's own (`_otherBlockItems` and the rest, in ./graph.js), so
 * the two cannot come to say different things.
 *
 * A toolbar in the ARIA sense: one stop for Tab, and the arrow keys between its
 * buttons, so the keyboard on its way to the diagram does not walk past twenty
 * of them.
 */

import { el } from './parts.js';
import { blockIcon } from './icons.js';
import { openMenu } from './menu.js';
import { infoButton } from './infopanel.js';
import { panelTopic } from './panelinfo.js';
import * as ed from '../domain/edit.js';

const KEY = 'kompartment.canvasBar';

/**
 * During a zoom the level is written at most this often. Every pan and every
 * wheel step reaches `syncZoom`, and a label written has the browser lay the
 * whole page out again: on a sub-system of three thousand elements that was
 * half of each frame of a zoom. The level the zoom ends on is always written.
 */
const ZOOM_LABEL_MS = 150;

/** Whether the bar is wanted: this browser's choice, up unless it said otherwise. */
export function barWanted() {
	try { return localStorage.getItem(KEY) !== 'off'; } catch { return true; }
}

function keepWanted(on) {
	try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* a convenience */ }
}

/** How far a press travels before it is a drag rather than a click. */
const DRAG_SLOP = 4;

const NS = 'http://www.w3.org/2000/svg';

/** The bar's own glyphs, drawn in its text colour like the (i) beside them. */
const GLYPHS = {
	// A shape on the canvas: a box and a disc, the two it is mostly asked for.
	shape: [['rect', { x: 2, y: 6, width: 7.5, height: 7.5, rx: 1 }], ['circle', { cx: 10.5, cy: 5.5, r: 3.5 }]],
	// The lattice behind the diagram.
	grid: [['path', { d: 'M1.5 5.5h13M1.5 10.5h13M5.5 1.5v13M10.5 1.5v13' }]],
	// A magnet: what a drag is pulled to.
	snap: [['path', { d: 'M3.5 2.5h3v5.5a1.5 1.5 0 0 0 3 0V2.5h3V8a4.5 4.5 0 0 1-9 0z M3.5 5.5h3M9.5 5.5h3' }]],
};

function glyph(name) {
	const g = document.createElementNS(NS, 'svg');
	for (const [k, v] of Object.entries({
		viewBox: '0 0 16 16', width: 15, height: 15, fill: 'none', stroke: 'currentColor',
		'stroke-width': 1.25, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
		'aria-hidden': 'true', focusable: 'false', class: 'canvas-bar-glyph',
	})) g.setAttribute(k, String(v));
	for (const [tag, attrs] of GLYPHS[name]) {
		const part = document.createElementNS(NS, tag);
		for (const [k, v] of Object.entries(attrs)) part.setAttribute(k, String(v));
		g.append(part);
	}
	return g;
}

/** The blocks the bar makes with a click, or drops where it is dragged to. */
const BLOCKS = [
	{ kind: 'compartment', label: 'Compartment', what: 'a box that holds an inventory over time' },
	{ kind: 'expression', label: 'Expression', what: 'a quantity worked out from the others at each step' },
	{ kind: 'parameter', label: 'Parameter', what: 'a constant' },
];

const PLACE = 'Click to add one in the middle of the view, or drag it onto the diagram '
	+ 'to put it where it is dropped.';

export class CanvasBar {
	/** @param {import('./graph.js').GraphEditor} graph */
	constructor(graph) {
		this.graph = graph;
		this.shown = barWanted();
		/** The button whose menu is open, if one is. */
		this.menuFor = null;
		/** The zoom level to write, when it was last written, and the write waiting (see ZOOM_LABEL_MS). */
		this.zoomText = '';
		this.zoomAt = -Infinity;
		this.zoomTimer = 0;
		this.el = el('div', { className: 'canvas-bar', role: 'toolbar', 'aria-label': 'Diagram' });
		this.el.hidden = !this.shown;
		this.build();
		this.wireKeys();
	}

	build() {
		const g = this.graph;
		const sep = () => el('span', { className: 'tb-sep', 'aria-hidden': 'true' });

		const blocks = BLOCKS.map((b) => this.blockButton(b.kind, b.label,
			`${b.label} — ${b.what}. ${PLACE}`));
		this.inflow = this.menuButton([blockIcon('inflow'), null], 'Inflow',
			() => g._inflowItems(), 'An input from outside the model, into a compartment or a far-field path');
		this.more = this.menuButton('More', 'More blocks',
			() => [...g._transportOperationItems(g.viewSpot()), ...g._otherBlockItems(g.viewSpot())],
			'The rest of what a model is made of: lookup tables, functions, transports, far-field '
			+ 'pathways, events, waste packages, reductions and recorders. Each lands in the middle '
			+ 'of the view.');
		this.system = this.blockButton('system', 'Sub-system',
			`Sub-system — a named place to put blocks, with its own namespace. ${PLACE}`);
		const shape = this.button(glyph('shape'), 'Shape', () => g._pickShape((size) => g.viewSpot(size)), {
			title: 'Shape… — a box to group things in, an arrow to point with, or a picture of what '
				+ 'the model is about, drawn behind the blocks in the middle of the view',
		});

		const show = this.menuButton('Show', 'Show', () => g._showItems(),
			'Which blocks are drawn, what is written along the transfers, and the influence arrows');

		const zoomOut = this.button('−', 'Zoom out', () => g.zoomBy(0.8));
		this.level = this.button('100%', 'Back to 100%', () => g.zoomTo(1), { className: 'canvas-bar-level' });
		const zoomIn = this.button('+', 'Zoom in', () => g.zoomBy(1.25));
		const fit = this.button('Fit', 'Fit to view', () => g.fit(), { title: 'Fit to view — all of the diagram in sight' });

		this.grid = this.button(glyph('grid'), 'Show grid', () => this.flip('show_grid'), { pressed: false });
		this.snap = this.button(glyph('snap'), 'Snap to the grid', () => this.flip('snap_to_grid'), {
			pressed: false,
			title: 'Snap to the grid — a block lands on the grid when it is moved or resized; hold Alt '
				+ 'during a drag to do the opposite',
		});
		const canvas = this.menuButton('Canvas', 'Canvas', () => g._canvasItems(),
			'The grid, the help line, tooltips, auto-layout and the zoom');
		const picture = this.menuButton('Picture', 'Save as picture', () => g._pictureItems(),
			'The whole diagram of this sub-system as SVG, PNG or JPEG, at 1:1');

		// What the bar is, behind an (i), as everything else here explains
		// itself; and the way to put it away.
		const about = infoButton('panel:canvasbar', () => panelTopic('canvasbar'));
		about.tabIndex = -1;
		const close = this.button('×', 'Put the bar away', () => this.setShown(false, { say: true }), {
			className: 'canvas-bar-close',
			title: 'Put the bar away. Canvas ▸ Show toolbar, on the canvas menu, brings it back',
		});

		this.el.append(
			el('span', { className: 'canvas-bar-what' }, 'Add'),
			...blocks, this.inflow, this.more, this.system, shape,
			sep(), show,
			sep(), zoomOut, this.level, zoomIn, fit,
			sep(), this.grid, this.snap, canvas, picture,
			sep(), about, close,
		);
		// One stop for Tab: the first button until another has been used.
		this.el.querySelector('button').tabIndex = 0;
	}

	/** A button of the bar: not a stop for Tab of its own (see `wireKeys`). */
	button(content, label, act, { className = '', pressed = null, title = label } = {}) {
		const b = el('button', {
			type: 'button',
			className: `ghost canvas-bar-btn${className ? ` ${className}` : ''}`,
			title,
			'aria-label': label,
			tabIndex: -1,
		}, ...[content].flat());
		if (pressed !== null) b.setAttribute('aria-pressed', String(pressed));
		b.addEventListener('click', (ev) => {
			// The click a drag from this button ends with: the drag has done
			// whatever it was going to.
			if (b.dragged) { b.dragged = false; return; }
			if (!this.graph.project) return;
			act(ev, b);
		});
		return b;
	}

	/**
	 * A button that opens one of the canvas menu's own menus under it. A
	 * second press closes it again, as a menu button's does: the menu closes
	 * itself on any press outside it, this one included, so the press is
	 * noted before its click would open the menu a second time.
	 */
	menuButton(content, label, items, title) {
		const b = this.button([content, el('span', { className: 'canvas-bar-caret', 'aria-hidden': 'true' }, '▾')],
			label, () => {
				if (b.closing) { b.closing = false; return; }
				this.openMenuUnder(b, items());
			}, { title });
		b.setAttribute('aria-haspopup', 'menu');
		b.setAttribute('aria-expanded', 'false');
		b.addEventListener('pointerdown', () => { b.closing = this.menuFor === b; });
		return b;
	}

	openMenuUnder(b, items) {
		const r = b.getBoundingClientRect();
		openMenu({
			x: r.left,
			y: r.bottom + 4,
			items,
			onClose: () => {
				b.setAttribute('aria-expanded', 'false');
				// Cleared after the press that closed it has reached the button,
				// so that press can tell it closed this button's own menu.
				setTimeout(() => { if (this.menuFor === b) this.menuFor = null; });
			},
		});
		this.menuFor = b;
		b.setAttribute('aria-expanded', 'true');
	}

	/**
	 * A block's button: a click adds one in the middle of the view, a drag
	 * drops one where it is let go. The drag is followed by an outline of the
	 * block at the size it will be drawn, so it is put down where it is meant
	 * to go rather than where its corner happens to land.
	 */
	blockButton(kind, label, title) {
		const b = this.button(blockIcon(kind), label, () => this.graph.addFromBar(kind), { title });
		b.classList.add('canvas-bar-drag');
		b.addEventListener('pointerdown', (ev) => {
			// A press of its own: whatever an earlier drag left to swallow is
			// not this press's click.
			b.dragged = false;
			if (ev.button !== 0 || !this.graph.project) return;
			const x0 = ev.clientX;
			const y0 = ev.clientY;
			let ghost = null;
			// The button keeps the pointer, so the canvas under the drag is
			// not hovered and the click that ends it is the button's. Listened
			// for on the window all the same, which works whether or not the
			// capture is had.
			b.setPointerCapture?.(ev.pointerId);
			const stop = () => {
				window.removeEventListener('pointermove', move, true);
				window.removeEventListener('pointerup', up, true);
				window.removeEventListener('pointercancel', cancel, true);
				window.removeEventListener('keydown', escape, true);
				ghost?.remove();
			};
			const move = (e) => {
				if (!ghost) {
					if (Math.hypot(e.clientX - x0, e.clientY - y0) < DRAG_SLOP) return;
					ghost = this.ghost(kind, label);
					document.body.append(ghost);
				}
				ghost.style.left = `${e.clientX}px`;
				ghost.style.top = `${e.clientY}px`;
				ghost.classList.toggle('is-over', this.overCanvas(e));
			};
			const up = (e) => {
				const dropped = ghost && this.overCanvas(e);
				// A drag, landed or not, is not a click as well: the button
				// has the pointer, so the click that follows is its own.
				if (ghost) b.dragged = true;
				stop();
				if (dropped) this.graph.addFromBar(kind, e);
			};
			// A cancelled pointer gets no click, so there is nothing to swallow.
			const cancel = () => stop();
			// Escape puts the block back: nothing is added, and the release
			// that is still to come is not a click either.
			const escape = (e) => {
				if (e.key !== 'Escape' || !ghost) return;
				e.preventDefault();
				e.stopPropagation();
				b.dragged = true;
				stop();
			};
			window.addEventListener('pointermove', move, true);
			window.addEventListener('pointerup', up, true);
			window.addEventListener('pointercancel', cancel, true);
			window.addEventListener('keydown', escape, true);
		});
		return b;
	}

	/** The outline a dragged block is shown as: its own size at the zoom on screen. */
	ghost(kind, label) {
		const size = ed.DEFAULT_SIZE[kind] ?? ed.DEFAULT_SIZE.compartment;
		const k = this.graph.camera.k;
		const g = el('div', { className: 'canvas-bar-ghost', 'aria-hidden': 'true' }, label);
		g.style.width = `${size.w * k}px`;
		g.style.height = `${size.h * k}px`;
		return g;
	}

	/** Whether a point is over the diagram, and not over the bar on top of it. */
	overCanvas(e) {
		const inside = (r) => e.clientX >= r.left && e.clientX <= r.right
			&& e.clientY >= r.top && e.clientY <= r.bottom;
		return inside(this.graph.root.getBoundingClientRect()) && !inside(this.el.getBoundingClientRect());
	}

	flip(key) {
		this.graph.setViewOption({ [key]: !this.graph.view[key] });
	}

	/** Up or away, and kept so. */
	setShown(on, { say = false } = {}) {
		this.shown = !!on;
		this.el.hidden = !this.shown;
		keepWanted(this.shown);
		if (this.shown) this.sync();
		if (say && !this.shown) {
			this.graph.hooks.onStatus?.('The bar is put away. Canvas ▸ Show toolbar, on the canvas’s '
				+ 'right-click menu, brings it back.', 'info');
		}
	}

	/** The room the bar takes at the top of the canvas, which a fit leaves clear. */
	inset() {
		return this.shown ? this.el.offsetTop + this.el.offsetHeight + 6 : 0;
	}

	/** The switches and the zoom, as the model and the camera have them now. */
	sync() {
		const g = this.graph;
		if (!g.project || !this.shown) return;
		const v = g.view;
		this.grid.setAttribute('aria-pressed', String(!!v.show_grid));
		this.snap.setAttribute('aria-pressed', String(!!v.snap_to_grid));
		const targets = g._inflowTargets().length;
		this.inflow.disabled = !targets;
		this.inflow.title = targets
			? 'Inflow — an input from outside the model, into a compartment or a far-field path'
			: 'Inflow — a source needs a compartment to flow into';
		// A transport is a chain of compartments and holds no sub-system.
		const inTransport = ed.isTransport(g.project, g.currentSystem);
		this.system.disabled = inTransport;
		this.syncZoom();
	}

	/**
	 * The zoom level, as the label says it: written only when it changes -- a
	 * pan, which leaves it as it was, writes nothing -- and during a zoom at
	 * most every ZOOM_LABEL_MS, the last level always.
	 */
	syncZoom() {
		if (!this.shown) return;
		this.zoomText = `${Math.round(this.graph.camera.k * 100)}%`;
		if (this.level.textContent === this.zoomText || this.zoomTimer) return;
		const wait = ZOOM_LABEL_MS - (performance.now() - this.zoomAt);
		if (wait <= 0) this.writeZoom();
		else this.zoomTimer = setTimeout(() => this.writeZoom(), wait);
	}

	writeZoom() {
		this.zoomTimer = 0;
		this.zoomAt = performance.now();
		if (this.level.textContent !== this.zoomText) this.level.textContent = this.zoomText;
	}

	/**
	 * One stop for Tab; the arrows, Home and End move between the buttons, and
	 * Down opens a menu button's menu. The stop is the last button used, so
	 * coming back to the bar comes back to it.
	 */
	wireKeys() {
		const buttons = () => [...this.el.querySelectorAll('button')].filter((b) => !b.disabled);
		this.el.addEventListener('keydown', (ev) => {
			const list = buttons();
			const at = list.indexOf(document.activeElement);
			if (at < 0) return;
			let next = null;
			if (ev.key === 'ArrowRight') next = list[(at + 1) % list.length];
			else if (ev.key === 'ArrowLeft') next = list[(at - 1 + list.length) % list.length];
			else if (ev.key === 'Home') next = list[0];
			else if (ev.key === 'End') next = list[list.length - 1];
			else if (ev.key === 'ArrowDown' && list[at].getAttribute('aria-haspopup')) {
				ev.preventDefault();
				list[at].click();
				return;
			}
			if (!next) return;
			ev.preventDefault();
			next.focus();
		});
		this.el.addEventListener('focusin', (ev) => {
			const b = ev.target.closest?.('button');
			if (!b) return;
			for (const other of this.el.querySelectorAll('button')) other.tabIndex = other === b ? 0 : -1;
		});
	}
}
