/**
 * Transfer matrix.
 *
 * Laid out the way a Jacobian is drawn: **the blocks are on the diagonal and
 * the interactions are off it**. Row i, column j is what flows out of the
 * block named at (i,i) and into the block named at (j,j), so the diagonal is a
 * staircase of names and everything beside it is a transfer.
 *
 * That saves the header band a from/to grid needs -- the diagonal is the
 * header, in both directions at once -- and it is the shape anyone who has
 * looked at a sparsity pattern already knows how to read. Each filled cell
 * carries the elbow that says which way it runs: in along its row from the
 * name on the diagonal, out down or up its column to the other one.
 *
 * The extra row and column marked "outside" are transfers with no compartment
 * at one end -- inflows from, and outflows to, the world beyond the model.
 *
 * A click selects and a double-click opens, as everywhere else; nothing is
 * made by a click. What can be made, and done, is on the right-click, which
 * depends on where it lands -- see `wireMenu`.
 */

import * as ed from '../domain/edit.js';
import { qualifiedName, baseName } from '../domain/systems.js';
import { inkFor } from './ink.js';
import { el } from './parts.js';
import { openMenu } from './menu.js';
import { wheelPixels } from './wheel.js';
import { symbolNodes } from './symbol.js';
import { hasSymbol } from '../domain/symbol.js';

const OUTSIDE = 'outside';

const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(NS, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/**
 * Which way a cell runs, drawn as the path it takes.
 *
 * A cell's donor is the name on the diagonal along its own row and its
 * receiver is the name on the diagonal down its own column, so the flow is an
 * elbow: in along the row, a quarter turn, out along the column. Which way it
 * turns follows from which side of the diagonal the cell is on, and that is
 * the whole of what has to be said -- above it the receiver is further down
 * the list, below it the receiver is further up.
 *
 * Drawn rather than written, because an arrow that traces the route needs no
 * convention remembered: the line starts where the donor's name is and ends
 * pointing at the receiver's.
 *
 * @param {boolean} down true above the diagonal, where the flow turns down
 */
function flowArrow(down) {
	const g = svg('svg', {
		class: 'matrix-arrow', viewBox: '0 0 22 22', width: 16, height: 16,
		'aria-hidden': 'true', focusable: 'false',
	});
	g.append(svg('path', {
		class: 'matrix-arrow-line',
		// Above the diagonal: in from the left (the donor is back along the
		// row), turning down. Below it: in from the right, turning up.
		d: down ? 'M 2 5 H 11 Q 15 5 15 9 V 12' : 'M 20 17 H 11 Q 7 17 7 13 V 10',
		fill: 'none',
	}));
	g.append(svg('path', {
		class: 'matrix-arrow-head',
		d: down ? 'M 15 18.5 l 3.4 -5.4 h -6.8 z' : 'M 7 3.5 l 3.4 5.4 h -6.8 z',
	}));
	return g;
}

/**
 * A block's own colour, if it was given one.
 *
 * Only the explicit choice: a block with no colour keeps the cell's theme
 * background, the way it keeps the diagram's default fill. `findBlock` walks
 * every collection, so this is the one lookup rather than a guess from which
 * list the name came out of.
 */
function colorOf(project, name) {
	const block = ed.findBlock(project, name)?.block;
	const color = String(block?.color ?? '').trim();
	return color || null;
}

/**
 * Whether no flux can ever run from a block of kind `ka` into one of kind
 * `kb` -- `null` for outside the model.
 *
 * The rule a line drawn on the diagram follows (`_legalTargets` in
 * ./graph.js): nothing is delivered into waste packages, and a release -- out
 * of a path, or out of packages -- is not delivered straight into a path. The
 * grid had only the second, and for paths alone: a cell offered to deliver
 * into a set of packages and then reported that it could not.
 */
function refused(ka, kb) {
	return kb === 'waste_package' || (ed.RELEASING.has(ka) && kb === 'farfield');
}

/** What `refused` says, in words, about the pair named `from` and `to`. */
function refusalText(kb, from, to) {
	return kb === 'waste_package'
		? `${to} is a set of waste packages: nothing flows into them, their release comes out.`
		: `A release from ${from} cannot be delivered straight into ${to}: give it a `
			+ 'compartment in between.';
}

// --- slots -------------------------------------------------------------------

/** What a slot stands for when a flux lands on it; undefined for a label. */
const idOf = (slot) => (slot.kind === 'block' ? slot.name
	: slot.kind === 'group' ? slot.path
		: slot.kind === 'outside' ? null : undefined);
/** What to call it on screen, and what to call it in a tooltip. */
const nameOf = (slot) => (slot.kind === 'outside' ? OUTSIDE : slot.local);
const fullOf = (slot) => (slot.kind === 'block' ? slot.name
	: slot.kind === 'outside' ? 'outside the model' : slot.path);

/** Whether a slot is inside the open sub-system at `f`. */
const within = (f, at) => at > f.from && at <= f.to;

/**
 * The open sub-system whose band a cell is part of, if any: the band runs
 * along the top row and down the left column of the group its header opens.
 */
function bandOf(frames, r, c, i, j) {
	return r.kind === 'head'
		? frames.find((f) => f.path === r.path && within(f, j))
		: frames.find((f) => f.path === c.path && within(f, i));
}

// --- zoom ------------------------------------------------------------------
//
// Every cell is the same square (`--cell` in app.css), so the grid reads as
// the matrix it is -- a pattern whose shape says something about the model --
// rather than as a table whose columns are as wide as their longest rate. A
// square big enough to read a rate in is too big to see a landscape model's
// pattern in, so the grid zooms: the buttons above it, or the wheel -- a
// pinch on a trackpad too -- about the pointer, as the diagram does.
// By CSS `zoom` on the table, which scales its layout and not only its
// picture, so the panel's scrollbars stay true.

const ZOOM_MIN = 0.2;
const ZOOM_MAX = 2.5;
const ZOOM_STEP = 1.25;
const ZOOM_KEY = 'kompartment.matrixZoom';

/**
 * How far a pixel of wheel zooms: the diagram's rate (`_onWheel` in
 * ./graph.js), so that a notch does the same to both views of one model.
 */
const WHEEL_RATE = 0.0015;

/** The zoom, kept for the next visit: a view setting, so the browser's, not the model's. */
let zoom = (() => {
	try {
		const z = Number(localStorage.getItem(ZOOM_KEY));
		return Number.isFinite(z) && z > 0 ? clampZoom(z) : 1;
	} catch {
		return 1;
	}
})();

function clampZoom(z) {
	return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
}

/** The zoom the grid is drawn at. */
export function matrixZoom() {
	return zoom;
}

/**
 * Zooms the grid in `host` to `next`, keeping the point at (`cx`, `cy`) --
 * window coordinates -- where it is on screen; the middle of the view when no
 * point is given, which is what the buttons mean.
 */
export function setMatrixZoom(host, next, cx = null, cy = null) {
	const table = host.querySelector('table.matrix');
	const z = clampZoom(next);
	if (!table || z === zoom) { zoom = z; return; }
	const r = host.getBoundingClientRect();
	const px = (cx ?? r.left + host.clientWidth / 2) - r.left;
	const py = (cy ?? r.top + host.clientHeight / 2) - r.top;
	// Where the table starts in the scrolled content, and where the point is
	// within it: the table is what scales, so the point scales about its
	// corner.
	const t = table.getBoundingClientRect();
	const ox = t.left - r.left + host.scrollLeft;
	const oy = t.top - r.top + host.scrollTop;
	const k = z / zoom;
	const inX = px + host.scrollLeft - ox;
	const inY = py + host.scrollTop - oy;
	zoom = z;
	table.style.zoom = String(z);
	host.scrollLeft = ox + inX * k - px;
	host.scrollTop = oy + inY * k - py;
	try { localStorage.setItem(ZOOM_KEY, String(z)); } catch { /* a convenience */ }
	const level = host.querySelector('.matrix-zoom-level');
	if (level) level.textContent = `${Math.round(z * 100)}%`;
}

/** The zoom that puts the whole grid in the panel, no larger than 100%. */
function fitZoom(host) {
	const table = host.querySelector('table.matrix');
	if (!table) return zoom;
	const t = table.getBoundingClientRect();
	const bar = host.querySelector('.matrix-zoom')?.getBoundingClientRect().height ?? 0;
	// The size at 100%: what is on screen, divided by the zoom it is drawn at.
	const w = t.width / zoom;
	const h = t.height / zoom;
	if (!(w > 0 && h > 0)) return zoom;
	return clampZoom(Math.min(1, (host.clientWidth - 24) / w, (host.clientHeight - bar - 24) / h));
}

/** The zoom's buttons, above the grid and staying there as it scrolls. */
function zoomBar(host) {
	const button = (text, title, act, cls = '') => {
		const b = el('button', { type: 'button', className: `ghost ${cls}`.trim(), title, 'aria-label': title }, text);
		b.addEventListener('click', act);
		return b;
	};
	return el('div', { className: 'matrix-zoom', role: 'group', 'aria-label': 'Zoom' },
		button('\u2212', 'Zoom out', () => setMatrixZoom(host, zoom / ZOOM_STEP)),
		button(`${Math.round(zoom * 100)}%`, 'Back to 100%', () => setMatrixZoom(host, 1), 'matrix-zoom-level'),
		button('+', 'Zoom in', () => setMatrixZoom(host, zoom * ZOOM_STEP)),
		button('Fit', 'The whole grid in view', () => setMatrixZoom(host, fitZoom(host))),
		el('span', { className: 'hint matrix-zoom-hint' }, 'or the wheel \u00b7 drag the grid to move it'));
}

// --- the panel's gestures -----------------------------------------------------
//
// Wired once per panel: the grid is drawn again on every edit and the panel
// is not, and a listener added with each drawing would answer every gesture
// once for every edit made since the tab was opened. What a gesture needs from
// the drawing in front of it -- the model, the slots, the hooks -- is filed
// under the panel by `renderMatrix`, and read when the gesture happens.

/** What the grid on screen in a panel was drawn from. */
const views = new WeakMap();
const wired = new WeakSet();

function wire(host) {
	if (wired.has(host)) return;
	wired.add(host);
	wireWheel(host);
	wirePan(host);
	wireMenu(host);
}

/**
 * The wheel zooms, about the pointer, as it does on the diagram.
 *
 * The two views of one model answer the same gesture the same way and at the
 * same rate. What a plain wheel did here before -- scroll -- is a drag on the
 * grid's empty space now (`wirePan`), and the scrollbars are still there. A
 * pinch on a trackpad arrives as a wheel with Ctrl held, and zooms the grid
 * rather than the whole page.
 *
 * Sideways is left to scroll: a trackpad swiped left or right, or Shift and a
 * mouse wheel, still moves the grid along its rows, since nothing about a
 * zoom is sideways.
 *
 * At most once a frame. A trackpad sends sixty of these a second, and each
 * one lays the table out again at its new size, which on a grid of forty
 * thousand cells is a frame's work by itself.
 */
function wireWheel(host) {
	let pending = null;
	host.addEventListener('wheel', (ev) => {
		if (!host.querySelector('table.matrix')) return;
		if (!ev.ctrlKey && Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) return;
		ev.preventDefault();
		const factor = Math.exp(-wheelPixels(ev.deltaY, ev.deltaMode, host.clientHeight) * WHEEL_RATE);
		if (pending) {
			pending.factor *= factor;
			pending.x = ev.clientX;
			pending.y = ev.clientY;
			return;
		}
		pending = { factor, x: ev.clientX, y: ev.clientY };
		requestAnimationFrame(() => {
			const { factor: f, x, y } = pending;
			pending = null;
			setMatrixZoom(host, zoom * f, x, y);
		});
	}, { passive: false });
}

/** How far a press may wander and still be a click rather than a drag. */
const PAN_SLACK = 4;

/**
 * A drag on the grid's empty space moves it.
 *
 * What the wheel did before it zoomed, and what a drag on the diagram's empty
 * canvas does: a grid of any size is larger than its panel, and a drag moves
 * it both ways at once. From empty space only -- a cell with nothing in it,
 * the band along an open sub-system, the margin round the grid -- since
 * everything else on it is a button that a click selects. The middle button
 * moves it from anywhere, over the tiles too. A finger is left to the
 * browser, which already scrolls a panel under one.
 *
 * A press that never became a drag is a click on nothing, and clears the
 * selection, as it does on the diagram.
 */
function wirePan(host) {
	let drag = null;
	host.addEventListener('pointerdown', (ev) => {
		if (drag || ev.pointerType === 'touch') return;
		const middle = ev.button === 1;
		// Ctrl and a click is the Mac's right-click, and belongs to the menu.
		if (!middle && (ev.button !== 0 || ev.ctrlKey || !isEmptySpace(host, ev))) return;
		drag = {
			id: ev.pointerId, middle, x: ev.clientX, y: ev.clientY,
			left: host.scrollLeft, top: host.scrollTop, moved: false,
		};
		host.setPointerCapture(ev.pointerId);
		// No text selected across the panel while it moves, and the keyboard
		// left wherever it was.
		ev.preventDefault();
	});
	host.addEventListener('pointermove', (ev) => {
		if (!drag || ev.pointerId !== drag.id) return;
		const dx = ev.clientX - drag.x;
		const dy = ev.clientY - drag.y;
		if (!drag.moved) {
			if (Math.hypot(dx, dy) < PAN_SLACK) return;
			drag.moved = true;
			host.classList.add('is-panning');
		}
		host.scrollLeft = drag.left - dx;
		host.scrollTop = drag.top - dy;
	});
	const end = (ev) => {
		if (!drag || ev.pointerId !== drag.id) return;
		const clicked = ev.type === 'pointerup' && !drag.moved && !drag.middle;
		drag = null;
		host.classList.remove('is-panning');
		const view = views.get(host);
		if (clicked && view?.selection) view.hooks.onSelect?.(null);
	};
	host.addEventListener('pointerup', end);
	host.addEventListener('pointercancel', end);
	host.addEventListener('lostpointercapture', end);
}

/** Whether a press is on the grid's empty space rather than on something on it. */
function isEmptySpace(host, ev) {
	const t = ev.target;
	if (!(t instanceof Element) || !host.contains(t)) return false;
	// Everything that is a control: the tiles, which are buttons, and the
	// zoom's bar.
	if (t.closest('button, a, input, select, textarea, .matrix-zoom')) return false;
	// A crowded square's stack is only ever hit on its own scrollbar, or in
	// the two pixels between its tiles.
	if (t.classList.contains('is-crowded')) return false;
	// And the panel's own scrollbars, where a press is the scrollbar's.
	if (t === host) {
		const r = host.getBoundingClientRect();
		if (ev.clientX - r.left - host.clientLeft >= host.clientWidth
			|| ev.clientY - r.top - host.clientTop >= host.clientHeight) return false;
	}
	return true;
}

/**
 * The right-click, which offers what can be done where it lands.
 *
 * A block on the diagonal and a transfer off it get the menu the diagram gives
 * them -- they are the same blocks, and a menu that depended on which view a
 * block was found in would be two menus to learn -- with what only the grid
 * can add to it. A sub-system's tile gets its menu and the fold. And the empty
 * places get what can be put there: an empty cell is a pair of blocks, so the
 * transfer between them; the dashed `outside` on the diagonal is the world
 * beyond the model, so an inflow or an outflow; and the margin round the grid
 * is the model itself, where a block goes -- inside the sub-system whose band
 * was pointed at, when it was one.
 */
function wireMenu(host) {
	host.addEventListener('contextmenu', (ev) => {
		const view = views.get(host);
		if (!view) return;
		ev.preventDefault();
		const menu = menuAt(host, view, ev.target);
		if (!menu) return;
		// From the keyboard -- the menu key, Shift+F10 -- there is no pointer,
		// and the menu opens over what has the focus.
		let { clientX: x, clientY: y } = ev;
		if (!x && !y && ev.target instanceof Element) {
			const r = ev.target.getBoundingClientRect();
			x = r.left + r.width / 2;
			y = r.top + r.height / 2;
		}
		openMenu({ x, y, ...menu });
	});
}

/** The menu for whatever `target` is part of, or null when there is none. */
function menuAt(host, view, target) {
	const t = target instanceof Element ? target : null;
	if (t?.closest('.matrix-zoom')) return { title: 'zoom', items: viewItems(host) };
	const table = host.querySelector('table.matrix');
	const cell = t?.closest('td, th');
	if (!cell || !table?.contains(cell)) return placeMenu(host, view, '');
	const i = cell.parentElement.rowIndex;
	const j = cell.cellIndex;
	const row = view.slots[i];
	const col = view.slots[j];
	if (!row || !col) return placeMenu(host, view, '');

	// The diagonal: the thing itself, wherever in its square the click was.
	if (i === j) {
		if (row.kind === 'block') return view.hooks.blockMenu?.(row.name, []) ?? null;
		if (row.kind === 'group' || row.kind === 'head') return systemMenu(host, view, row);
		return outsideMenu(host, view);
	}
	// An open sub-system's band, which is a place in it rather than a pair.
	if (row.kind === 'head' || col.kind === 'head') {
		return placeMenu(host, view, bandOf(view.frames, row, col, i, j)?.path ?? '');
	}
	const tile = t.closest('[data-name]');
	if (tile) {
		// One of the transfers in the cell: its own menu, and another beside it.
		const another = pairItem(view, i, j);
		return view.hooks.blockMenu?.(tile.dataset.name, another.disabled ? [] : [another]) ?? null;
	}
	if (t.closest('.matrix-summary')) return summaryMenu(host, view, i, j);
	return {
		title: `${fullOf(row)} \u2192 ${fullOf(col)}`,
		items: [{ heading: 'Add' }, pairItem(view, i, j), { separator: true }, ...viewItems(host)],
	};
}

/**
 * The item that adds a flux to the cell at row `i`, column `j`: out of the
 * block named along the row and into the one down the column.
 *
 * What the `+` in an empty cell used to do on a click -- which made a click
 * on the grid an edit, where everywhere else in the application it selects.
 * Refused, with the reason, where the pair cannot be joined by hand: a fold at
 * either end has no one block to connect, and `refused` is the diagram's rule.
 *
 * @param {object} view  a `matrixGrid`, with the `project` and the `hooks`
 */
export function pairItem(view, i, j) {
	const r = view.slots[i];
	const c = view.slots[j];
	const a = idOf(r);
	const b = idOf(c);
	const ka = view.kinds.get(a) ?? null;
	const kb = view.kinds.get(b) ?? null;
	const another = view.pairAt(i, j).length > 0;
	const release = ed.RELEASING.has(ka);
	const label = a == null
		? `${another ? 'Another inflow' : 'Inflow'} into ${c.local}`
		: release
			? `${r.local}\u2019s release ${b == null ? 'out of the model' : `into ${c.local}`}`
			: b == null
				? `${another ? 'Another outflow' : 'Outflow'} from ${r.local} out of the model`
				: `${another ? 'Another transfer' : 'Transfer'} from ${r.local} to ${c.local}`;
	const folded = r.kind === 'group' ? r : c.kind === 'group' ? c : null;
	const why = folded
		? `${folded.path} is folded up. Unfold it to connect the block inside it that a flux `
			+ 'would belong to.'
		: refused(ka, kb) ? refusalText(kb, fullOf(r), fullOf(c))
			: release ? ed.releaseTaken(view.project, a) : '';
	if (why) return { label, disabled: true, title: why };
	return {
		label,
		title: a == null ? `A source term: what comes into ${b} from outside the model`
			: kb === 'farfield' ? `Into the first fracture cell of ${b}`
				: another ? 'Beside the one already here; their fluxes add' : '',
		onPick: () => addFlux(view, a == null ? 'inflow' : 'transfer', a, b),
	};
}

/** Adds a flux, and selects it: the new tile, in its cell. */
function addFlux(view, kind, a, b) {
	const { project, hooks } = view;
	try {
		// Into the model from outside is a source term, as the diagram's
		// `Inflow` makes it, rather than a transfer with no donor.
		const block = kind === 'inflow'
			? ed.addSource(project, { to: b })
			: ed.addTransfer(project, a, b);
		hooks.onChange?.();
		hooks.onSelect?.({ kind, name: qualifiedName(block) });
	} catch (e) {
		hooks.onStatus?.(e.message, 'warn');
	}
}

/** A sub-system's tile: the fold, and the menu the diagram gives it. */
function systemMenu(host, view, slot) {
	const open = slot.kind === 'head';
	const fold = {
		label: open ? `Fold ${slot.local} up` : `Unfold ${slot.local}`,
		hint: 'click',
		title: open
			? 'Back to one row and one column, where every flux in and out of it lands'
			: 'Its blocks on the grid, framed together, with each flux against the block it joins',
		onPick: () => view.hooks.onToggleSystem?.(slot.path),
	};
	const shared = view.hooks.blockMenu?.(slot.path, addItems(host, view, slot.path)) ?? null;
	return {
		title: shared?.title ?? `sub-system ${slot.path}`,
		items: [fold, ...(shared ? [{ separator: true }, ...shared.items] : [])],
	};
}

/** Several fluxes folded into one cell: the fold, and a way to each of them. */
function summaryMenu(host, view, i, j) {
	const r = view.slots[i];
	const c = view.slots[j];
	const group = r.kind === 'group' ? r : c;
	const here = view.pairAt(i, j);
	return {
		title: `${here.length} fluxes, ${fullOf(r)} \u2192 ${fullOf(c)}`,
		items: [
			{
				label: `Unfold ${group.local}`,
				hint: 'click',
				title: `Each of them against the block inside ${group.path} that it joins`,
				onPick: () => view.hooks.onToggleSystem?.(group.path),
			},
			{
				label: 'Select',
				items: here.map((t) => {
					const name = qualifiedName(t);
					return {
						label: name,
						hint: `${t.from ?? OUTSIDE} \u2192 ${t.to ?? OUTSIDE}`,
						onPick: () => view.hooks.onSelect?.({
							kind: t.from === undefined || t._source ? 'inflow' : 'transfer', name,
						}),
					};
				}),
			},
			{ separator: true },
			...viewItems(host),
		],
	};
}

/** The world beyond the model, on the diagonal: what comes in, and what leaves. */
function outsideMenu(host, view) {
	const { project } = view;
	const named = (list) => (list ?? []).map((b) => qualifiedName(b));
	const into = [...named(project.compartments), ...named(project.farfields)];
	const from = [...into, ...named(project.waste_packages)];
	return {
		title: 'outside the model',
		items: [
			{ heading: 'Add' },
			{
				label: 'Inflow into',
				title: 'A source term: what comes into the model from outside it',
				disabled: !into.length,
				items: into.map((b) => ({ label: b, onPick: () => addFlux(view, 'inflow', null, b) })),
			},
			{
				label: 'Outflow from',
				title: 'What leaves the model',
				disabled: !from.length,
				items: from.map((a) => {
					// A path or a set of packages has one release, and it may
					// already be going somewhere.
					const taken = ed.RELEASING.has(ed.findBlock(project, a)?.kind)
						? ed.releaseTaken(project, a) : '';
					return {
						label: a,
						disabled: !!taken,
						title: taken,
						onPick: () => addFlux(view, 'transfer', a, null),
					};
				}),
			},
			{ separator: true },
			...viewItems(host),
		],
	};
}

/**
 * The margin round the grid, or the band along an open sub-system: a place in
 * the model, `''` for the top level, and what can be put there.
 */
function placeMenu(host, view, system) {
	const paste = view.hooks.pasteItem?.(system) ?? null;
	return {
		title: system ? `sub-system ${system}` : 'the top level',
		items: [
			{ heading: 'Add here' },
			...addItems(host, view, system),
			...(paste ? [{ separator: true }, paste] : []),
			...foldItems(view),
			...(host.querySelector('table.matrix') ? [{ separator: true }, ...viewItems(host)] : []),
		],
	};
}

/**
 * The blocks this grid has a place for, made in a sub-system -- `''` for the
 * top level. Compartments, far-field paths and waste packages are what sit on
 * the diagonal, and a sub-system is what folds; the rest of what a model is
 * made of is drawn nowhere on the grid, and is on the diagram's menu and
 * beside the tree's search, where it can be seen arriving.
 */
function addItems(host, view, system) {
	const transport = !!system && ed.isTransport(view.project, system);
	const item = (label, title, what) => ({
		label, title, onPick: () => addBlock(host, view, what, system),
	});
	return [
		item('Compartment', 'A box that holds an inventory over time', 'compartment'),
		item('Far-field pathway', 'Transport along a fracture in rock, with diffusion into the '
			+ 'rock matrix. A source term goes into it and the release comes out the other side.',
		'farfield'),
		item('Waste packages', 'The source term with its barriers: an inventory inside packages '
			+ 'that fail over time, and a release drawn out of the block into the near field.',
		'waste_package'),
		transport
			? {
				label: 'Sub-system', disabled: true,
				title: 'A transport is a chain of compartments and holds no sub-system of its own',
			}
			: item('Sub-system', 'A named place to put blocks, with its own namespace', 'system'),
	];
}

/** Makes one of `addItems`' blocks, selects it and brings it into view. */
function addBlock(host, view, what, system) {
	const { project, hooks } = view;
	try {
		const made = {
			compartment: () => qualifiedName(ed.addCompartment(project, { system })),
			farfield: () => qualifiedName(ed.addFarfield(project, { system })),
			waste_package: () => qualifiedName(ed.addWastePackage(project, { system })),
			system: () => ed.addSystem(project, { parent: system }),
		}[what]();
		// Unfolded to where it went: inside a fold it would arrive nowhere
		// to be seen.
		if (system) hooks.onUnfoldTo?.(system);
		hooks.onChange?.();
		hooks.onSelect?.({ kind: what, name: made });
		reveal(host, made);
	} catch (e) {
		hooks.onStatus?.(e.message, 'warn');
	}
}

/** Scrolls the grid to the tile for `name`, if it is on it. */
function reveal(host, name) {
	for (const tile of host.querySelectorAll('[data-name]')) {
		if (tile.dataset.name !== name) continue;
		tile.scrollIntoView({ block: 'nearest', inline: 'nearest' });
		return;
	}
}

/** How many rows unfolding everything may make before it is refused. */
const UNFOLD_MOST = 300;

/** Every sub-system folded, or every one open -- where the grid can hold that. */
function foldItems(view) {
	const all = ed.systems(view.project);
	if (!all.length) return [];
	// Unfolded, every block on the grid is a row, and a model of thousands of
	// blocks is millions of squares: the folds are what make it drawable.
	const rows = ed.matrixPlan(view.project, new Set(all)).slots.length;
	const big = rows > UNFOLD_MOST;
	const shut = !all.some((p) => view.open.has(p));
	return [
		{ separator: true },
		{
			label: 'Fold every sub-system',
			disabled: shut,
			title: shut ? 'They are all folded already' : 'Each back to one row and one column',
			onPick: () => view.hooks.onFoldAll?.(false),
		},
		{
			label: 'Unfold every sub-system',
			disabled: big || all.every((p) => view.open.has(p)),
			title: big
				? `Unfolded, the grid would be ${rows.toLocaleString()} rows by `
					+ `${rows.toLocaleString()} columns, too many squares to draw at once. `
					+ 'Unfold the ones you want to read.'
				: 'Every block on the grid, with each sub-system framed round its own',
			onPick: () => view.hooks.onFoldAll?.(true),
		},
	];
}

/** What the zoom's buttons do, for a menu opened on the grid's empty space. */
function viewItems(host) {
	return [
		{ label: 'Zoom in', hint: 'scroll', onPick: () => setMatrixZoom(host, zoom * ZOOM_STEP) },
		{ label: 'Zoom out', hint: 'scroll', onPick: () => setMatrixZoom(host, zoom / ZOOM_STEP) },
		{ label: 'Back to 100%', disabled: zoom === 1, onPick: () => setMatrixZoom(host, 1) },
		{
			label: 'Fit to view',
			title: 'The whole grid in view',
			onPick: () => setMatrixZoom(host, fitZoom(host)),
		},
	];
}

// --- the grid ----------------------------------------------------------------

/**
 * What the grid shows, worked out from the model without drawing any of it:
 * its rows and the frames round open sub-systems (`matrixPlan`), what each
 * block on the diagonal is, the fluxes in each cell, and what each folded
 * sub-system swallowed. Apart from the drawing so that what a cell holds and
 * offers can be worked out -- and tested -- without a page.
 *
 * @param {Set<string>} open  the sub-systems unfolded
 * @returns {{slots: object[], frames: object[], kinds: Map<string, string>,
 *   inside: Map<string, number>, pairAt: (i: number, j: number) => object[]}}
 */
export function matrixGrid(project, open = new Set()) {
	const { slots, frames, representative } = ed.matrixPlan(project, open);
	// What each block on the diagonal is, looked up once rather than once per
	// cell it heads: a row and a column each, of a grid that may be forty
	// thousand cells.
	const kinds = new Map(slots.filter((s) => s.kind === 'block')
		.map((s) => [s.name, ed.findBlock(project, s.name)?.kind ?? 'compartment']));

	// donor -> receiver -> the transfers between them, keyed by what each end
	// *lands on*: a block, or the closed sub-system standing for it. A list,
	// not one transfer: two blocks may be joined by several, and folding a
	// sub-system up puts more of them in the same cell.
	const byPair = new Map();
	const key = (a, b) => `${a ?? ''}\u0000${b ?? ''}`;
	const add = (k, block) => {
		if (!byPair.has(k)) byPair.set(k, []);
		byPair.get(k).push(block);
	};
	// What a closed sub-system has swallowed: transfers between two blocks
	// inside it, which have no row and no column left to sit on. Counted
	// rather than dropped -- a grid that quietly stops showing part of the
	// model is worse than one that says how much it is not showing.
	const inside = new Map();
	const connections = [
		...(project.transfers ?? []),
		...(project.inflows ?? []).map((x) => ({ ...x, from: null, _source: true })),
	];
	for (const t of connections) {
		const a = representative(t.from);
		const b = representative(t.to);
		if (a != null && a === b) {
			inside.set(a, (inside.get(a) ?? 0) + 1);
			continue;
		}
		add(key(a, b), t);
	}
	return {
		slots, frames, kinds, inside,
		pairAt: (i, j) => byPair.get(key(idOf(slots[i]), idOf(slots[j]))) ?? [],
	};
}

/**
 * Moves the highlight to a different connection, leaving the grid alone.
 *
 * The grid is (compartments + paths + 1) squared: a model of two hundred
 * compartments is forty thousand cells, and rebuilding all of them because the
 * selection moved -- which happens on every click anywhere in the application,
 * since `setSelection` re-renders this view -- is the whole cost of the view
 * paid for a class on one cell.
 */
export function markSelection(host, selection) {
	const view = views.get(host);
	if (view) view.selection = selection;
	const name = selection?.name ?? null;
	for (const td of host.querySelectorAll('td[data-names]')) {
		td.classList.toggle('is-selected',
			!!name && td.dataset.names.split('\u0000').includes(name));
	}
	// And every button that stands for one block: the connections inside a
	// cell -- a cell may hold several -- and the blocks on the diagonal.
	for (const btn of host.querySelectorAll('[data-name]')) {
		btn.classList.toggle('is-selected', btn.dataset.name === name);
	}
}

/**
 * @param {HTMLElement} host
 * @param {object} project
 * @param {{kind: string, name: string}|null} selection
 * @param {{onChange: Function, onSelect: Function, onStatus: Function,
 *          onOpenSettings: Function, onToggleSystem: Function,
 *          onFoldAll: Function, onUnfoldTo: Function,
 *          blockMenu: Function, pasteItem: Function}} hooks
 *   `blockMenu(name, adds)` is the diagram's menu for a block or a
 *   sub-system as items, with the grid's own `adds` in it; `pasteItem` its
 *   Paste, aimed at a sub-system. See `menuAbout` in ./graph.js.
 * @param {{open?: Set<string>}} [opts]  the sub-systems unfolded
 */
export function renderMatrix(host, project, selection, hooks = {}, opts = {}) {
	// Where the panel was scrolled to, put back once the grid is drawn again:
	// every edit redraws it, and one made from a cell far down the grid should
	// leave that cell where it was.
	const scrolled = { left: host.scrollLeft, top: host.scrollTop };
	host.replaceChildren();
	// Compartments are listed by qualified name: two called Water in different
	// sub-systems are two blocks, and something has to say which is which. On
	// this grid that something is the frame around the sub-system, so the cell
	// shows the local name and keeps the path for its tooltip.
	const comps = (project.compartments ?? []).map((c) => qualifiedName(c));
	const paths = (project.farfields ?? []).map((f) => qualifiedName(f));

	// Which sub-systems are unfolded. The view's, not the model's: it changes
	// nothing and is never saved.
	const open = opts.open ?? new Set();
	// What the panel's gestures read -- see `wire`. Filed before anything is
	// drawn, so that the empty panel of a new model has its menu too.
	const view = {
		project, selection, hooks, open,
		slots: [], frames: [], kinds: new Map(), pairAt: () => [],
	};
	views.set(host, view);
	wire(host);

	if (!comps.length) {
		host.append(el('div', { className: 'empty' },
			'Add a compartment to start building the model: right-click here, or use the '
			+ 'buttons beside the search.'));
		return;
	}

	const grid = matrixGrid(project, open);
	const { slots, frames, kinds, inside } = grid;
	Object.assign(view, grid);

	const isPath = new Set(paths);
	// A folded sub-system's tile carries a second line -- what it holds -- and
	// the tile is placed out of flow, so it cannot make the row taller for
	// itself. The rows are given the room when any group is on the grid.
	const anyGroups = slots.some((x) => x.kind === 'group');
	const table = el('table', {
		className: `matrix${anyGroups ? ' has-groups' : ''}`,
	});
	// A fixed layout needs a width to be fixed against: every column one
	// square, so the table is `--cell` times the number of slots.
	table.style.setProperty('--n', String(slots.length));
	table.style.zoom = String(zoom);
	const body = el('tbody');

	// The frame each cell sits on the edge of. A cell may be on more than one
	// -- a sub-system whose last member is itself a sub-system shares its
	// bottom and right edge -- so the shadows are composed rather than set as
	// a border, which cannot stack. The outermost frame wins the colour.
	const edgesAt = (i, j) => {
		const parts = [];
		let depth = null;
		for (const f of frames) {
			const inRows = i >= f.from && i <= f.to;
			const inCols = j >= f.from && j <= f.to;
			if (!inRows || !inCols) continue;
			const want = [];
			if (i === f.from) want.push('inset 0 2px 0 0 var(--matrix-frame)');
			if (i === f.to) want.push('inset 0 -2px 0 0 var(--matrix-frame)');
			if (j === f.from) want.push('inset 2px 0 0 0 var(--matrix-frame)');
			if (j === f.to) want.push('inset -2px 0 0 0 var(--matrix-frame)');
			if (!want.length) continue;
			for (const w of want) if (!parts.includes(w)) parts.push(w);
			depth = depth == null ? f.depth : Math.min(depth, f.depth);
		}
		return { shadow: parts.join(', '), depth };
	};

	for (let i = 0; i < slots.length; i++) {
		const r = slots[i];
		const tr = el('tr', {});

		for (let j = 0; j < slots.length; j++) {
			const c = slots[j];
			const frame = edgesAt(i, j);

			// --- the diagonal: the thing itself ---------------------------
			if (i === j) {
				tr.append(diagonalCell(r, {
					project, selection, hooks, isPath, kinds, inside, frame,
				}));
				continue;
			}

			// --- a sub-system's header band -------------------------------
			// Nothing flows into or out of a header: it is the label of the
			// group it opens. The band runs along the group's top row and
			// left column, which is where the eye looks for a heading on a
			// grid that is read both ways.
			if (r.kind === 'head' || c.kind === 'head') {
				const band = bandOf(frames, r, c, i, j);
				const td = el('td', {
					className: band ? 'matrix-band' : 'matrix-void',
					title: band
						? `${band.path} \u2014 everything inside it is framed here`
						: '',
				});
				if (frame.shadow) td.style.setProperty('box-shadow', frame.shadow);
				tr.append(td);
				continue;
			}

			const a = idOf(r);
			const b = idOf(c);
			const here = grid.pairAt(i, j);
			// A pair no line may join, whatever is open -- see `refused`.
			const impossible = refused(kinds.get(a), kinds.get(b));
			// A pair with a folded sub-system at either end cannot be joined
			// *by hand* -- there is no single block at that end to connect --
			// which is a different thing, and must not look like the first: a
			// cell holding seven fluxes should not be greyed out as forbidden.
			const folded = r.kind === 'group' || c.kind === 'group';
			const td = el('td', {
				className: [
					impossible ? 'matrix-na' : '',
					here.length ? 'matrix-has' : 'matrix-empty',
					here.some((t) => selection?.name === qualifiedName(t)) ? 'is-selected' : '',
				].filter(Boolean).join(' '),
			});
			if (frame.shadow) td.style.setProperty('box-shadow', frame.shadow);
			if (here.length) td.dataset.names = here.map((t) => qualifiedName(t)).join('\u0000');

			// Which way this cell runs. Above the diagonal the receiver is
			// further down the list, so the elbow turns down; below it, up.
			const down = j > i;

			if (here.length > 1 && folded) {
				// Several fluxes across a folded boundary. Summarised rather
				// than listed: every one of them belongs to a block that is
				// not on the grid, so reading its rate here says less than
				// the count does -- and a dozen of them stacked in one cell
				// made the row a screen tall, which is the opposite of what
				// folding a sub-system is for. Unfolding the group is one
				// click away, and that is where the detail belongs.
				td.append(summaryCell(here, {
					hooks, down, from: fullOf(r), to: fullOf(c),
					open: r.kind === 'group' ? r.path : c.path,
				}));
			} else if (here.length) {
				td.append(cellStack(here, {
					project, selection, hooks, down, from: fullOf(r), to: fullOf(c),
				}));
			} else if (impossible) {
				td.title = refusalText(kinds.get(b), fullOf(r), fullOf(c));
			} else if (folded) {
				td.title = `${fullOf(r.kind === 'group' ? r : c)} is folded up. Unfold it `
					+ `to connect the block inside it that a flux would belong to.`;
			}
			tr.append(td);
		}
		body.append(tr);
	}
	table.append(body);
	host.append(zoomBar(host), table);

	host.append(el('p', { className: 'hint' },
		'The blocks are on the diagonal, the flows between them off it \u2014 the '
		+ 'shape a Jacobian is drawn in. A cell is what leaves the name on the '
		+ 'diagonal along its row and arrives at the name down its column, and '
		+ 'the elbow in it traces that route: above the diagonal it turns down, '
		+ 'below it turns up. Click anything here to select it and double-click '
		+ 'to open its settings, blocks and transfers alike. Right-click for what '
		+ 'can be done where you click: on an empty cell, add the transfer between '
		+ 'its two blocks \u2014 a pair may hold more than one, and their fluxes add '
		+ '\u2014 and on the margin, add a block. The wheel zooms about the pointer, '
		+ 'and dragging the empty grid moves it.'
		+ (frames.length || slots.some((x) => x.kind === 'group')
			? ' A sub-system folds up into a single row and column, with every '
				+ 'flux in and out of it landing there; unfold it with a click on '
				+ 'its tile to see the blocks inside, framed together.'
			: '')
		+ (paths.length
			? ' A far-field path sits on the diagonal like any other block: a flux '
				+ 'goes into its first fracture cell, and its release comes out of '
				+ 'its last \u2014 and that rate is the release itself, so it is not '
				+ 'editable.'
			: '')));
	host.scrollLeft = scrolled.left;
	host.scrollTop = scrolled.top;
}

/** The diagonal: a block, a folded sub-system, or an open one's header. */
function diagonalCell(slot, ctx) {
	const { project, selection, hooks, isPath, kinds, inside, frame } = ctx;
	// `matrix-slot-<kind>`, not `matrix-<kind>`: a block's slot would then be
	// `matrix-block`, the tile's own class, and the cell took the tile's
	// border, corners and `inset: 2px` -- which on a cell that is
	// `position: relative` moved the whole diagonal two pixels right and down.
	const th = el('th', {
		className: `matrix-self matrix-slot-${slot.kind}${
			slot.kind === 'outside' ? ' matrix-outside'
				: slot.kind === 'block' && isPath.has(slot.name) ? ' matrix-path' : ''}`,
		scope: 'row',
	});
	if (frame.shadow) th.style.setProperty('box-shadow', frame.shadow);

	if (slot.kind === 'outside') {
		th.title = 'The world beyond the model: its row is what comes in from '
			+ 'outside, its column what leaves. Right-click it to add either.';
		// A tile of its own, like every other thing on the diagonal, so the
		// grid does not have one cell that is a bare word. Not a control:
		// there is nothing to select and nothing to open.
		th.append(el('span', { className: 'matrix-block matrix-nowhere' }, OUTSIDE));
		return th;
	}

	// A sub-system: its name, what it holds, and the one control that folds it.
	if (slot.kind === 'group' || slot.kind === 'head') {
		const isOpen = slot.kind === 'head';
		const held = slot.kind === 'group'
			? [
				`${slot.blocks} block${slot.blocks === 1 ? '' : 's'}`,
				slot.systems ? `${slot.systems} sub-system${slot.systems === 1 ? '' : 's'}` : '',
				inside.get(slot.path) ? `${inside.get(slot.path)} flux inside` : '',
			].filter(Boolean).join(', ')
			: '';
		const btn = el('button', {
			className: `matrix-block matrix-system${isOpen ? ' is-open' : ''}`,
			type: 'button',
			title: `${slot.path} \u2014 ${isOpen
				? 'unfolded: the blocks inside it are framed here. Click to fold it up.'
				: `folded up, holding ${held}. Click to unfold it.`}`,
		});
		btn.dataset.name = slot.path;
		btn.append(el('span', { className: 'matrix-fold' }, isOpen ? '\u25be' : '\u25b8'));
		btn.append(el('span', { className: 'matrix-system-name' }, slot.local));
		if (!isOpen && held) {
			btn.append(el('span', { className: 'matrix-system-held' }, held));
		}
		btn.addEventListener('click', () => hooks.onToggleSystem?.(slot.path));
		// Selecting it is what the rest of the application means by clicking a
		// sub-system; folding is what this view is for, so the click folds and
		// the selection follows.
		btn.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			hooks.onSelect?.({ kind: 'system', name: slot.path });
		});
		th.append(btn);
		return th;
	}

	// A block. A click selects it, a double-click opens its settings -- the
	// same two gestures it answers on the diagram and in the tree.
	const kind = kinds.get(slot.name) ?? 'compartment';
	// The name in one element of its own, so the tile can centre it as one
	// thing: loose, the name, the bracket and the symbol would each be a flex
	// item and be laid out side by side as three.
	const label = el('span', { className: 'matrix-label' }, nameOf(slot));
	const btn = el('button', {
		className: 'matrix-block', type: 'button',
		title: `${fullOf(slot)} \u2014 its row is what flows out of it, its column `
			+ `what flows in.${isPath.has(slot.name)
				? ' A far-field path: a flux goes into its first fracture cell and '
					+ 'its release comes out of its last.'
				: ''}\nClick to select it, double-click to open its settings, right-click `
			+ 'for its menu.',
	}, label);
	// What it is shown as, in brackets after its name, as the tree has it.
	const named = ed.findBlock(project, slot.name)?.block;
	if (named && hasSymbol(named)) {
		label.append(' (', el('span', { className: 'matrix-symbol' }, ...symbolNodes(named.symbol)), ')');
	}
	btn.dataset.name = slot.name;
	if (selection?.name === slot.name) btn.classList.add('is-selected');
	// Whatever colour the block was given on the diagram. Written as a
	// property, never pasted into a style string: the value comes out of a
	// project file. The label is picked from the fill rather than from the
	// theme, so a dark colour does not hide it.
	const own = colorOf(project, slot.name);
	if (own) paint(btn, own);
	btn.addEventListener('click', () => hooks.onSelect?.({ kind, name: slot.name }));
	btn.addEventListener('dblclick', (ev) => {
		ev.preventDefault();
		hooks.onOpenSettings?.(slot.name);
	});
	th.append(btn);
	return th;
}

/** A fill, with the label and the marks on it inked from that fill. */
function paint(el2, color) {
	el2.style.setProperty('background-color', color);
	el2.style.setProperty('--own', color);
	const ink = inkFor(color);
	if (!ink) return;
	el2.style.setProperty('color', ink.strong);
	el2.style.setProperty('--matrix-ink', ink.strong);
	el2.style.setProperty('--matrix-ink-dim', ink.dim);
}

/**
 * How many transfers one square holds before it has to scroll: each needs its
 * rate and its name. Two fit; a third is where it gets tight.
 */
const STACK_FITS = 2;

/** The transfers in one cell, newest last. */
function cellStack(here, { selection, hooks, down, from, to }) {
	// Scrolling only when it has to. It used to whenever its content came to
	// more than its box, which a fraction of a pixel of rounding is enough for
	// -- a zoom left at 100.4% by the wheel reads as 100% -- and put a
	// scrollbar beside squares with room to spare.
	const stack = el('div', { className: `matrix-stack${here.length > STACK_FITS ? ' is-crowded' : ''}` });
	for (const t of here) {
		// A source has no `from` key at all; a transfer out of the model has
		// one set to null.
		const isSource = t.from === undefined || t._source;
		const btn = el('button', {
			className: `matrix-cell matrix-flow${
				selection?.name === qualifiedName(t) ? ' is-selected' : ''}`,
			type: 'button',
			title: `${qualifiedName(t)}: ${t.rate}\n${from} \u2192 ${to}\n`
				+ 'Click to select it, double-click to open its settings, right-click for its menu.',
		},
		// The elbow first: it is the one part of the cell that says which of
		// the two names on the diagonal is the donor.
		flowArrow(down),
		el('span', { className: 'matrix-flux' },
			el('span', { className: 'matrix-rate' }, t.rate || '0'),
			el('span', { className: 'matrix-name' }, t.name)));
		btn.dataset.name = qualifiedName(t);
		// Its own colour, if it was given one on the diagram. A line's weight
		// and dash are about a line and have nothing to say in a cell, so only
		// the colour crosses.
		const own = ed.connectionLook(t).color;
		if (own) paint(btn, own);
		btn.addEventListener('click', () => hooks.onSelect?.({
			kind: isSource ? 'inflow' : 'transfer', name: qualifiedName(t),
		}));
		// The same gesture the diagram, the tree and the diagonal use.
		btn.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			hooks.onOpenSettings?.(qualifiedName(t));
		});
		stack.append(btn);
	}
	return stack;
}

/**
 * Several fluxes across a folded boundary, as a count.
 *
 * Clicking it unfolds the sub-system, which is where each of them can be read
 * against the block it actually joins.
 */
function summaryCell(here, { hooks, down, from, to, open }) {
	const names = here.map((t) => qualifiedName(t));
	const shown = names.slice(0, 8);
	const stack = el('div', { className: 'matrix-stack' });
	const btn = el('button', {
		className: 'matrix-cell matrix-flow matrix-summary', type: 'button',
		title: `${here.length} fluxes from ${from} to ${to}:\n  ${shown.join('\n  ')}`
			+ `${names.length > shown.length ? `\n  \u2026and ${names.length - shown.length} more` : ''}`
			+ `\nClick to unfold ${open} and read them against the blocks they join; `
			+ 'right-click to select one of them.',
	},
	flowArrow(down),
	el('span', { className: 'matrix-flux' },
		el('span', { className: 'matrix-rate' }, `${here.length} fluxes`),
		el('span', { className: 'matrix-name' }, `unfold ${baseName(open)}`)));
	btn.addEventListener('click', () => hooks.onToggleSystem?.(open));
	stack.append(btn);
	return stack;
}
