/**
 * The App designer tab: the parts on the left, the page in the middle, and
 * the settings of whatever is selected on the right.
 *
 * What an app is and how it is stored is ../domain/apps.js; what its inputs
 * set and its results read is ../domain/appinputs.js; how each part is drawn is
 * ./appwidgets.js. This file is the gestures: dragging a part onto the page or
 * into a panel, moving and resizing it on its grid or into another, and the
 * settings form.
 *
 * **Every change is an edit of the model** -- the app is in the model file --
 * and goes through the page's `commit`, which is `modelChanged` marked as one
 * that moves no number: the undo stack records it and nothing is run. The page
 * then draws this tab again from the model, so there is one way the tab comes
 * to show what it shows, whether the change was made here, undone, or arrived
 * with a file.
 *
 * **What is selected, which page is up and which tab of each set of tabs is
 * showing are the tab's**, not the model's: they are kept here, and a model
 * saved mid-design does not carry them.
 *
 * **The grid is CSS's.** A part is placed by `grid-column` and `grid-row` in
 * cells, so the page lays itself out and this only has to turn a pointer into
 * a cell. Every grid on the canvas -- the page's, and each container's -- knows
 * where a part dropped on it goes (`gridWhere`). While a part is dragged over
 * its own grid, the parts it would land on are moved as they would be
 * (`settle`), live; over another grid, a ghost says where it would land; and
 * the model is written once, on release.
 */

import { el } from './parts.js';
import { openMenu } from './menu.js';
import { infoButton } from './infopanel.js';
import { buildComponent, placeOnGrid } from './appwidgets.js';
import { appTopic } from './appinfo.js';
import * as apps from '../domain/apps.js';
import * as ai from '../domain/appinputs.js';
import { findBlock, effectiveDims } from '../domain/edit.js';

/** A row's height and the gap between cells, in pixels: css/app.css says the same. */
export const ROW = 28;
export const GAP = 8;

/** Empty rows kept under the last part of a page, to drop the next one into. */
const ROOM_BELOW = 6;

/** How far the pointer moves before a press on a part is a drag. */
const SLOP = 4;

/** What a part dragged from the list carries, so nothing else is mistaken for one. */
const PART_TYPE = 'application/x-kompartment-app-part';

/** The image types a picture may be. */
const PICTURE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml'];

/** A picture this small is kept as it is; a larger one is drawn smaller first. */
const PICTURE_AS_IS = 600000;

/** The longest side a picture is made smaller to. */
const PICTURE_SIDE = 1600;

/** The page on screen, the part selected and the tab of each set showing: the tab's, never the model's. */
const view = { page: 0, selected: null, tabs: new Map() };

let host = null;
let hooks = null;
/** The parts drawn on the canvas, every grid's: `{id, c, widget, item, grid, list}`. */
let drawn = [];
/** The type being dragged out of the list, which a drop target cannot read until the drop. */
let fromList = null;
/** A move or a resize in progress. */
let gesture = null;
/** Where a part dropped on each grid of the canvas goes. */
let gridWhere = new WeakMap();

/**
 * A redraw owed to a field of the settings form that was left.
 *
 * A text box saves when it is left, and the save redraws the tab. Drawn then
 * and there, that redraw took away whatever the focus or the pointer was
 * going to next: the field Tab was moving to, the button whose press had just
 * taken the focus away -- *Range from the model* after a new Min, say -- or
 * the page tab. So a field's save only marks a redraw owed, and it is drawn
 * once the focus has landed and the pointer has been let go (`oweRedraw`).
 */
let redrawOwed = false;
let fieldSaving = false;
let pointerDown = false;
/** The field Enter saved, which the redraw after it gives the focus back to. */
let refocus = null;

/** Which page the designer is on, for the running app to open at. */
export function designerPage() {
	return view.page;
}

/** Forgets the selection and goes back to the first page: a different model has arrived. */
export function resetDesigner() {
	view.page = 0;
	view.selected = null;
	view.tabs.clear();
	gesture = null;
}

/**
 * Draws the tab.
 *
 * @param {HTMLElement} panel
 * @param {object} h  what the page provides:
 *   `raw()` the model; `commit(label, opts)` records an edit made to it;
 *   `context()` what a part is drawn against (see ./appwidgets.js);
 *   `outputs()` the series the model reports, or null; `runApp()`; `share()`;
 *   `treeNames()` the blocks being dragged out of the tree; `flash(msg, tone)`
 */
export function renderAppDesigner(panel, h) {
	host = panel;
	hooks = h;
	watchPointer();
	if (fieldSaving || pointerDown) {
		fieldSaving = false;
		oweRedraw();
		return;
	}
	redrawOwed = false;
	// A gesture in hand is abandoned by a redraw: the element it holds is gone.
	gesture = null;
	const app = apps.readApp(hooks.raw());
	if (app) view.page = Math.min(Math.max(0, view.page), app.pages.length - 1);
	else view.page = 0;
	if (view.selected && !apps.findComponent(app, view.selected)) view.selected = null;
	const focus = rememberFocus() ?? (refocus ? { prop: refocus } : null);
	refocus = null;
	for (const d of drawn) d.widget?.destroy?.();
	drawn = [];
	gridWhere = new WeakMap();
	host.replaceChildren(
		toolbar(app),
		el('div', { className: 'appd-body' }, palette(), canvas(app), properties(app)),
	);
	restoreFocus(focus);
}

/** A redraw once the pointer is up, or on the next turn if it already is. */
function oweRedraw() {
	redrawOwed = true;
	if (!pointerDown) setTimeout(payRedraw, 0);
}

function payRedraw() {
	if (!redrawOwed || pointerDown || !host || !hooks) return;
	renderAppDesigner(host, hooks);
}

/**
 * Whether a pointer is down anywhere on the page, watched from the window's
 * capture phase: so it is known before any handler under the pointer runs,
 * and a press that ends on something the owed redraw would replace has
 * delivered its click by the time the redraw comes.
 */
function watchPointer() {
	if (watchPointer.done || typeof window === 'undefined') return;
	watchPointer.done = true;
	window.addEventListener('pointerdown', () => { pointerDown = true; }, true);
	const up = () => {
		pointerDown = false;
		if (redrawOwed) setTimeout(payRedraw, 0);
	};
	window.addEventListener('pointerup', up, true);
	window.addEventListener('pointercancel', up, true);
}

/**
 * The results again, without drawing anything else: a run has come in, or a
 * column of one. What each part says about itself can change with them -- a
 * series that is not among what the model reports is found once it has run.
 */
export function refreshAppDesigner() {
	if (!host || !hooks || !host.isConnected) return;
	const ctx = hooks.context();
	for (const d of drawn) {
		d.widget?.update?.(ctx);
		d.item.classList.toggle('has-problem', !!ctx.problemOf(d.c));
	}
}

// --- editing ---------------------------------------------------------------------------

/**
 * Makes one edit to the model and records it. Anything the edit refuses is
 * said, and nothing is recorded.
 */
function edit(label, fn, opts = {}) {
	let out;
	try {
		out = fn(hooks.raw());
	} catch (e) {
		fieldSaving = false;
		hooks.flash(e?.message ?? String(e), 'warn');
		return undefined;
	}
	hooks.commit(label, opts);
	return out;
}

/**
 * The part as the model holds it now. The settings form is drawn from the
 * part as it was, and a field's save no longer redraws it at once, so what a
 * handler reads -- the choices, the series, the place -- is read afresh.
 */
function now(c) {
	return apps.findComponent(apps.readApp(hooks.raw()), c.id)?.component ?? c;
}

/** Leaves the field being typed into, so that what is in it is saved before it goes. */
function leaveField() {
	const a = document.activeElement;
	if (a && host?.querySelector('.appd-props')?.contains(a) && typeof a.blur === 'function') a.blur();
}

function select(id) {
	if (view.selected === id) return;
	// A field taken away unsaved fires nothing: saved here, first.
	leaveField();
	view.selected = id;
	for (const d of drawn) d.item.classList.toggle('is-selected', d.id === id);
	const app = apps.readApp(hooks.raw());
	host.querySelector('.appd-props')?.replaceWith(properties(app));
}

/** The page on screen, as a place to put a part. */
function pageWhere() {
	return { page: view.page, parent: null, slot: 0 };
}

/** The grid a set of tabs shows while it is being designed. */
function tabShown(c) {
	return Math.min(view.tabs.get(c.id) ?? 0, (c.tabs?.length ?? 1) - 1);
}

/**
 * Where a part added from the list goes: into the selected panel, or the tab
 * of the selected set of tabs that is showing, when a container is selected
 * and has room for another level; on the page otherwise.
 */
function addWhere() {
	const app = apps.readApp(hooks.raw());
	const f = view.selected ? apps.findComponent(app, view.selected) : null;
	if (f && apps.CONTAINER_TYPES.has(f.component.type)) {
		return { page: view.page, parent: f.component.id, slot: f.component.type === 'tabs' ? tabShown(f.component) : 0 };
	}
	return pageWhere();
}

function addPart(type, where, at = null, props = {}) {
	edit(`add a ${apps.COMPONENTS[type].name.toLowerCase()}`, (raw) => {
		view.selected = apps.addComponent(raw, apps.readApp(raw) ? where : pageWhere(), type, { at, props });
	});
}

function removePart(id) {
	edit('delete a part', (raw) => {
		apps.removeComponent(raw, id);
		if (view.selected === id) view.selected = null;
	});
}

function duplicatePart(id) {
	edit('duplicate a part', (raw) => { view.selected = apps.duplicateComponent(raw, id) ?? view.selected; });
}

/**
 * Changes a part. `change` is the settings, or a function of the part as the
 * model holds it now, for a change made from what it already has.
 */
function patch(c, change, label = 'change a part', opts = {}) {
	edit(label, (raw) => apps.updateComponent(raw, c.id, typeof change === 'function' ? change(now(c)) : change), opts);
}

// --- the toolbar -------------------------------------------------------------------------

function toolbar(app) {
	const pages = el('div', { className: 'appd-pages', role: 'tablist', 'aria-label': 'Pages of the app' });
	(app?.pages ?? [{ name: 'Main', components: [] }]).forEach((p, i) => {
		const on = i === view.page;
		const b = el('button', {
			type: 'button', className: `appd-page${on ? ' is-on' : ''}`, role: 'tab',
			'aria-selected': String(on), title: 'Right-click to rename, move or delete the page',
		}, p.name);
		b.dataset.page = String(i);
		b.addEventListener('click', () => {
			if (view.page === i) return;
			view.page = i;
			view.selected = null;
			renderAppDesigner(host, hooks);
		});
		b.addEventListener('contextmenu', (ev) => {
			ev.preventDefault();
			if (app) pageMenu(app, i, ev);
		});
		pages.append(b);
	});
	const add = el('button', {
		type: 'button', className: 'appd-page appd-page-add', title: 'Add a page', 'aria-label': 'Add a page',
	}, '+');
	add.addEventListener('click', () => edit('add a page', (raw) => {
		view.page = apps.addPage(raw);
		view.selected = null;
	}));

	const all = app ? apps.allComponents(app) : [];
	const ctx = hooks.context();
	const wrong = all.filter(({ component }) => ctx.problemOf(component)).length;
	const status = el('span', { className: 'hint appd-status' },
		!all.length ? 'Nothing on the app yet'
			: `${all.length} part${all.length === 1 ? '' : 's'}`
			+ (app.pages.length > 1 ? ` on ${app.pages.length} pages` : '')
			+ (wrong ? ` · ${wrong} need${wrong === 1 ? 's' : ''} setting up` : ''));
	if (wrong) status.classList.add('is-warn');
	const share = el('button', {
		type: 'button', className: 'ghost appd-share',
		title: 'A link that opens this model as its app, for somebody to use in their own browser',
	}, 'Share…');
	share.disabled = !all.length;
	share.addEventListener('click', () => hooks.share());
	const run = el('button', {
		type: 'button', className: 'primary appd-run',
		title: 'Show the app on its own, as somebody using it sees it — Esc comes back here',
	}, '▶ Run app');
	run.disabled = !all.length;
	run.addEventListener('click', () => hooks.runApp());
	return el('div', { className: 'toolbar appd-toolbar' },
		pages, add, el('span', { className: 'spacer' }), status, share, run,
		infoButton('app:designer', () => appTopic('designer')));
}

function pageMenu(app, i, ev) {
	const n = app.pages.length;
	openMenu({
		x: ev.clientX, y: ev.clientY, title: app.pages[i].name,
		items: [
			{
				label: 'Rename…', onPick: () => {
					view.page = i;
					view.selected = null;
					renderAppDesigner(host, hooks);
					const box = host.querySelector('[data-prop="page-name"]');
					box?.focus();
					box?.select();
				},
			},
			{ label: 'Move left', disabled: i === 0, onPick: () => edit('move a page', (raw) => { if (apps.movePage(raw, i, i - 1)) view.page = i - 1; }) },
			{ label: 'Move right', disabled: i === n - 1, onPick: () => edit('move a page', (raw) => { if (apps.movePage(raw, i, i + 1)) view.page = i + 1; }) },
			{ separator: true },
			{
				label: 'Delete the page', danger: true, disabled: n <= 1,
				hint: n <= 1 ? 'an app has one page at least' : `${app.pages[i].components.length} part(s) go with it`,
				onPick: () => edit('delete a page', (raw) => {
					apps.removePage(raw, i);
					// The page on screen stays on screen, a place further
					// left when one before it went; the one deleted gives
					// way to the one before it.
					if (i < view.page || (i === view.page && i > 0)) view.page -= 1;
					view.selected = null;
				}),
			},
		],
	});
}

// --- the list of parts -----------------------------------------------------------------------

const ICON_PATHS = {
	slider: 'M2 8h12M6 5v6',
	number: 'M2 4h12v8H2zM5 7v3M9 6.5h2v1.5H9v2h2',
	dropdown: 'M2 4h12v8H2zM9 7l1.5 2L12 7',
	radio: 'M5 5.5a2 2 0 1 1 0 .01M5 10.5a2 2 0 1 1 0 .01M9 5.5h5M9 10.5h5',
	switch: 'M5 5h6a3 3 0 0 1 0 6H5a3 3 0 0 1 0-6zM11 8h.01',
	button: 'M2 5h12v6H2zM6 8h4',
	chart: 'M2 2v12h12M4 11l3-4 3 2 4-6',
	value: 'M3 4v8M3 4l2 0M6 12h2M10 4h3l-2 4h2l-3 4',
	gauge: 'M2 12a6 6 0 0 1 12 0M8 12l3-4',
	bars: 'M3 13V9M7 13V4M11 13V7M2 13h12',
	table: 'M2 3h12v10H2zM2 6h12M2 9.5h12M6 3v10',
	panel: 'M2 3h12v10H2zM2 6h12',
	tabs: 'M2 5h12v8H2zM2 5V3h4v2M6 3h4v2',
	text: 'M3 4h10M8 4v9M6 13h4',
	image: 'M2 3h12v10H2zM2 11l4-4 3 3 2-2 3 3M10.5 6a1 1 0 1 1 0 .01',
};

function partIcon(type) {
	const pic = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	pic.setAttribute('viewBox', '0 0 16 16');
	pic.setAttribute('width', '16');
	pic.setAttribute('height', '16');
	pic.setAttribute('aria-hidden', 'true');
	pic.setAttribute('class', 'appd-icon');
	const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
	path.setAttribute('d', ICON_PATHS[type] ?? 'M2 2h12v12H2z');
	pic.append(path);
	return pic;
}

function palette() {
	const box = el('nav', { className: 'appd-palette', 'aria-label': 'Parts to add' });
	for (const g of apps.COMPONENT_GROUPS) {
		box.append(el('div', { className: 'appd-pal-head' }, g.name));
		for (const [type, spec] of Object.entries(apps.COMPONENTS)) {
			if (spec.group !== g.id) continue;
			const b = el('button', {
				type: 'button', className: 'appd-pal-item', draggable: true,
				title: `Drag onto the page or into a panel, or click to add a ${spec.name.toLowerCase()} where there is room`,
			}, partIcon(type), el('span', {}, spec.name));
			b.dataset.type = type;
			b.addEventListener('click', () => addPart(type, addWhere()));
			b.addEventListener('dragstart', (ev) => {
				fromList = type;
				ev.dataTransfer.effectAllowed = 'copy';
				ev.dataTransfer.setData(PART_TYPE, type);
				// And as text, so a drag that leaves the window carries a word.
				ev.dataTransfer.setData('text/plain', spec.name);
			});
			b.addEventListener('dragend', () => {
				fromList = null;
				hideGhosts();
			});
			box.append(b);
		}
	}
	box.append(el('p', { className: 'hint appd-pal-hint' },
		'Or drag a parameter out of the tree for a slider over it, anything else for a chart of it, and a picture file for a picture.'));
	return box;
}

// --- the page ---------------------------------------------------------------------------

/** The cell under a point of the window, on one grid. */
function cellAt(grid, x, y) {
	const r = grid.getBoundingClientRect();
	const pitchX = (r.width + GAP) / apps.APP_COLUMNS;
	const pitchY = ROW + GAP;
	return {
		col: Math.floor((x - r.left) / pitchX),
		row: Math.floor((y - r.top) / pitchY),
	};
}

function currentPage(app) {
	return app?.pages?.[view.page] ?? { name: 'Main', components: [] };
}

/** The look the app wears, on whatever it is drawn into. */
export function wearTheme(node, app) {
	const theme = app?.theme ?? 'standard';
	if (theme === 'standard') delete node.dataset.appTheme;
	else node.dataset.appTheme = theme;
}

function canvas(app) {
	const page = currentPage(app);
	const ctx = hooks.context();
	const grid = gridFor(page.components, pageWhere(), apps.rowsOf(page.components) + ROOM_BELOW, ctx, true);
	grid.addEventListener('pointerdown', (ev) => {
		// The page itself, not a part on it: nothing is selected.
		if (ev.target === grid) {
			grid.focus({ preventScroll: true });
			select(null);
		}
	});
	grid.tabIndex = -1;
	// Inside the grid, so that a drag over what it says is a drag over the page.
	if (!page.components.length) grid.append(emptyPage(app));
	const box = el('div', { className: 'appd-canvas app-themed' }, grid);
	wearTheme(box, app);
	return box;
}

/**
 * One grid of the canvas: its parts, in the order they are read in, a ghost
 * for what would land on it, and what a drop on it does.
 */
function gridFor(list, where, rows, ctx, top = false) {
	const grid = el('div', { className: `app-grid appd-grid${top ? '' : ' appd-inner-grid app-inner-grid'}` });
	grid.style.setProperty('--rows', String(Math.max(1, rows)));
	gridWhere.set(grid, where);
	for (const c of apps.stackOrder(list)) grid.append(partOnPage(c, grid, list, where, ctx));
	grid.append(el('div', { className: 'appd-ghost', hidden: true, 'aria-hidden': 'true' }));
	wireDrop(grid);
	return grid;
}

/** What an empty page says, and the way to fill it. */
function emptyPage(app) {
	const any = app && apps.allComponents(app).length;
	const box = el('div', { className: 'appd-empty' },
		el('b', {}, any ? 'This page is empty.' : 'This model has no app yet.'),
		el('span', {}, 'Drag a control or a result from the list on the left onto the page — or drag a '
			+ 'parameter out of the tree for a slider over it.'));
	if (!any) {
		const start = el('button', { type: 'button', className: 'primary' }, 'Start from the model');
		start.title = 'Sliders for the parameters that carry a distribution, the scenario where there is '
			+ 'one, and a chart of what the model is for';
		start.addEventListener('click', startFromModel);
		box.append(start);
	}
	return box;
}

function startFromModel() {
	edit('start an app from the model', (raw) => {
		// The look the app had, where it had one: starting its parts again is
		// not choosing another style.
		const theme = apps.readApp(raw)?.theme ?? 'standard';
		raw.app = { ...ai.starterApp(raw, hooks.outputs()), theme };
		view.page = 0;
		view.selected = null;
	});
}

/**
 * A container's inside, as the designer draws it: its title or its tabs, live
 * -- a tab is chosen here to put parts on it -- over a grid of its own that
 * takes drops and holds parts that move and resize as the page's do.
 */
function containerBody(c, where, ctx) {
	const slot = c.type === 'tabs' ? tabShown(c) : 0;
	const inner = gridFor(apps.slotsOf(c)[slot], { page: where.page, parent: c.id, slot }, c.h - 1, ctx);
	let head;
	if (c.type === 'panel') {
		head = el('div', { className: 'app-part-head app-container-head' },
			el('span', { className: 'app-part-label' }, c.title || 'Panel'));
	} else {
		head = el('div', { className: 'app-tab-strip appd-tab-strip', role: 'tablist' });
		c.tabs.forEach((t, i) => {
			const b = el('button', {
				type: 'button', role: 'tab', className: `app-tab${i === slot ? ' is-on' : ''}`, 'aria-selected': String(i === slot),
				title: 'Show this tab to put parts on it; right-click to rename, move or delete it',
			}, t.name);
			// A press on a tab is a choice of tab, not the start of a drag of the set.
			b.addEventListener('pointerdown', (ev) => ev.stopPropagation());
			b.addEventListener('click', () => {
				view.tabs.set(c.id, i);
				view.selected = c.id;
				renderAppDesigner(host, hooks);
			});
			b.addEventListener('contextmenu', (ev) => {
				ev.preventDefault();
				ev.stopPropagation();
				tabMenu(c, i, ev);
			});
			head.append(b);
		});
		const add = el('button', { type: 'button', className: 'app-tab appd-tab-add', title: 'Add a tab', 'aria-label': 'Add a tab' }, '+');
		add.addEventListener('pointerdown', (ev) => ev.stopPropagation());
		add.addEventListener('click', () => edit('add a tab', (raw) => {
			const at = apps.addTab(raw, c.id);
			if (at >= 0) view.tabs.set(c.id, at);
			view.selected = c.id;
		}));
		head.append(add);
	}
	return el('div', { className: `app-part app-${c.type} appd-container-body` }, head, inner);
}

function tabMenu(c, i, ev) {
	const n = c.tabs.length;
	openMenu({
		x: ev.clientX, y: ev.clientY, title: c.tabs[i].name,
		items: [
			{
				label: 'Rename…', onPick: () => {
					view.selected = c.id;
					view.tabs.set(c.id, i);
					renderAppDesigner(host, hooks);
					const box = host.querySelector(`[data-prop="tab-name-${i}"]`);
					box?.focus();
					box?.select();
				},
			},
			{ label: 'Move left', disabled: i === 0, onPick: () => edit('move a tab', (raw) => { if (apps.moveTab(raw, c.id, i, i - 1)) view.tabs.set(c.id, i - 1); }) },
			{ label: 'Move right', disabled: i === n - 1, onPick: () => edit('move a tab', (raw) => { if (apps.moveTab(raw, c.id, i, i + 1)) view.tabs.set(c.id, i + 1); }) },
			{ separator: true },
			{
				label: 'Delete the tab', danger: true, disabled: n <= 1,
				hint: n <= 1 ? 'a set of tabs has one at least' : `${c.tabs[i].components.length} part(s) go with it`,
				onPick: () => edit('delete a tab', (raw) => {
					apps.removeTab(raw, c.id, i);
					view.tabs.set(c.id, Math.max(0, i - 1));
				}),
			},
		],
	});
}

function partOnPage(c, grid, list, where, ctx) {
	const container = apps.CONTAINER_TYPES.has(c.type);
	let widget = null;
	let body;
	if (container) {
		body = containerBody(c, where, ctx);
	} else {
		widget = buildComponent(c, ctx);
		body = el('div', { className: 'appd-part-body' }, widget.node);
		// Drawn, not used: see ./appwidgets.js.
		body.inert = true;
	}
	const name = apps.COMPONENTS[c.type].name;
	const item = el('div', {
		className: `app-item appd-item${container ? ' appd-container' : ''}${view.selected === c.id ? ' is-selected' : ''}`,
		tabIndex: 0, role: 'button',
		'aria-label': `${name}${c.label || c.title ? `: ${c.label || c.title}` : ''} — arrow keys move it, shift and an arrow resizes it`,
	}, body,
	el('span', { className: 'appd-badge', 'aria-hidden': 'true' }, name),
	el('span', { className: 'appd-handle', title: 'Drag to resize', 'aria-hidden': 'true' }));
	item.dataset.id = c.id;
	if (ctx.problemOf(c)) item.classList.add('has-problem');
	placeOnGrid(item, c);
	drawn.push({ id: c.id, c, widget, item, grid, list });
	// A part inside a container is inside that container's item too: every
	// handler here answers only for what is its own.
	const mine = (ev) => ev.target?.closest?.('.appd-item') === item;

	item.addEventListener('pointerdown', (ev) => {
		if (ev.button !== 0 || !mine(ev)) return;
		ev.preventDefault();
		// The focus first, which saves a field being typed into; then the
		// settings of this part in place of that field's.
		item.focus({ preventScroll: true });
		select(c.id);
		gesture = {
			id: c.id, type: c.type, list, grid, item,
			resize: !!ev.target.closest?.('.appd-handle'),
			x0: ev.clientX, y0: ev.clientY,
			cell: cellAt(grid, ev.clientX, ev.clientY),
			from: { x: c.x, y: c.y, w: c.w, h: c.h },
			box: { x: c.x, y: c.y, w: c.w, h: c.h },
			into: null,
			moved: false, pointer: ev.pointerId,
		};
		// A pointer the browser is not tracking -- an event made by a script --
		// cannot be captured; the gesture still works without it.
		try { item.setPointerCapture?.(ev.pointerId); } catch { /* not an active pointer */ }
	});
	item.addEventListener('pointermove', (ev) => {
		const g = gesture;
		if (!g || g.pointer !== ev.pointerId || g.id !== c.id) return;
		if (!g.moved && Math.hypot(ev.clientX - g.x0, ev.clientY - g.y0) < SLOP) return;
		if (!g.moved) {
			g.moved = true;
			item.classList.add(g.resize ? 'is-resizing' : 'is-moving');
		}
		const f = g.from;
		// Over another grid -- into a panel, out of one, into another -- a
		// ghost says where it would go, and its own grid is as it was.
		//
		// Asked of the grid as it was, not as the preview has it: the
		// preview moves what the part is dragged over out of its way, and a
		// panel it is dragged towards was pushed down ahead of the pointer
		// and never under it to be dropped into.
		let under = null;
		if (!g.resize) {
			for (const d of drawn) if (d.grid === grid) placeOnGrid(d.item, d.c);
			under = gridUnder(ev.clientX, ev.clientY, item);
		}
		if (under && under !== grid) {
			const at = cellAt(under, ev.clientX, ev.clientY);
			const box = apps.clampBox(g.type, { x: Math.min(at.col, apps.APP_COLUMNS - f.w), y: Math.max(0, at.row), w: f.w, h: f.h });
			g.into = { grid: under, where: gridWhere.get(under), box };
			hideGhosts();
			showGhost(under, box);
			keepInView(ev.clientY);
			return;
		}
		g.into = null;
		hideGhosts();
		const now2 = cellAt(grid, ev.clientX, ev.clientY);
		const dc = now2.col - g.cell.col;
		const dr = now2.row - g.cell.row;
		g.box = g.resize
			? apps.clampBox(g.type, { x: f.x, y: f.y, w: f.w + dc, h: f.h + dr }, { keepLeft: true })
			: apps.clampBox(g.type, { x: f.x + dc, y: f.y + dr, w: f.w, h: f.h });
		preview(g);
		keepInView(ev.clientY);
	});
	const finish = (ev, keep) => {
		const g = gesture;
		if (!g || g.pointer !== ev.pointerId || g.id !== c.id) return;
		gesture = null;
		item.classList.remove('is-moving', 'is-resizing');
		hideGhosts();
		if (g.moved && keep && g.into?.where) {
			edit('move a part', (raw) => apps.moveComponent(raw, c.id, g.into.where, { x: g.into.box.x, y: g.into.box.y }));
			return;
		}
		const same = ['x', 'y', 'w', 'h'].every((k) => g.box[k] === g.from[k]);
		if (!g.moved || !keep || same) {
			// Put back what the preview moved.
			for (const d of drawn) if (d.grid === grid) placeOnGrid(d.item, d.c);
			return;
		}
		edit(g.resize ? 'resize a part' : 'move a part', (raw) => apps.placeComponent(raw, c.id, g.box));
	};
	item.addEventListener('pointerup', (ev) => finish(ev, true));
	item.addEventListener('pointercancel', (ev) => finish(ev, false));
	item.addEventListener('lostpointercapture', (ev) => finish(ev, true));

	item.addEventListener('keydown', (ev) => {
		if (ev.target !== item) return;
		const k = ev.key;
		if (k === 'Delete' || k === 'Backspace') { ev.preventDefault(); removePart(c.id); return; }
		if (k === 'Escape') { ev.preventDefault(); select(null); grid.focus({ preventScroll: true }); return; }
		if ((ev.metaKey || ev.ctrlKey) && (k === 'd' || k === 'D')) { ev.preventDefault(); duplicatePart(c.id); return; }
		if (k === 'Enter') {
			ev.preventDefault();
			host.querySelector('.appd-props [data-prop]')?.focus();
			return;
		}
		const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[k];
		if (!d || ev.metaKey || ev.ctrlKey || ev.altKey) return;
		ev.preventDefault();
		const box = ev.shiftKey
			? { x: c.x, y: c.y, w: c.w + d[0], h: c.h + d[1] }
			: { x: c.x + d[0], y: c.y + d[1], w: c.w, h: c.h };
		const to = apps.clampBox(c.type, box, { keepLeft: ev.shiftKey });
		if (['x', 'y', 'w', 'h'].every((key) => to[key] === c[key])) return;
		// One undo for a run of nudges to the same part.
		edit(ev.shiftKey ? 'resize a part' : 'move a part', (raw) => apps.placeComponent(raw, c.id, to),
			{ coalesce: `app-nudge-${c.id}` });
	});

	item.addEventListener('contextmenu', (ev) => {
		if (!mine(ev)) return;
		ev.preventDefault();
		ev.stopPropagation();
		select(c.id);
		const app = apps.readApp(hooks.raw());
		const nested = !!where.parent;
		openMenu({
			x: ev.clientX, y: ev.clientY, title: name,
			items: [
				{ label: 'Duplicate', hint: '⌘D', onPick: () => duplicatePart(c.id) },
				...(nested ? [{
					label: 'Take it out onto the page',
					onPick: () => edit('move a part onto the page', (raw) => apps.moveComponent(raw, c.id, pageWhere())),
				}] : []),
				...(app && app.pages.length > 1 ? [{
					label: 'Move to page',
					items: app.pages.map((p, i) => ({
						label: p.name, disabled: i === view.page && !nested,
						onPick: () => edit('move a part to another page', (raw) => apps.moveComponentToPage(raw, c.id, i)),
					})),
				}] : []),
				{ separator: true },
				{ label: 'Delete', danger: true, hint: 'Del', onPick: () => removePart(c.id) },
			],
		});
	});
	return item;
}

/** The innermost grid of the canvas under a point, other than any inside `item`. */
function gridUnder(x, y, item) {
	for (const n of document.elementsFromPoint(x, y)) {
		if (n.classList?.contains('appd-grid') && !item.contains(n) && host.contains(n)) return n;
	}
	return null;
}

/** Every part of the grid in hand where it would be with the one in hand where the pointer is. */
function preview(g) {
	const items = g.list.map((c) => (c.id === g.id ? { ...c, ...g.box } : c));
	const where = apps.settle(items, g.id);
	for (const d of drawn) {
		if (d.grid !== g.grid) continue;
		const at = where.get(d.id);
		if (at) placeOnGrid(d.item, at);
	}
	if (!g.grid.classList.contains('appd-inner-grid')) {
		g.grid.style.setProperty('--rows', String(apps.rowsOf([...where.values()]) + ROOM_BELOW));
	}
}

/** Scrolls the page when a part is dragged against its top or bottom edge. */
function keepInView(y) {
	const scroll = host?.querySelector('.appd-canvas');
	if (!scroll) return;
	const r = scroll.getBoundingClientRect();
	const EDGE = 28;
	if (y > r.bottom - EDGE) scroll.scrollTop += 12;
	else if (y < r.top + EDGE) scroll.scrollTop -= 12;
}

// --- dropping onto the page --------------------------------------------------------------------

/** The ghost of one grid: its own child, not one of an inner grid's. */
function ghostOf(grid) {
	return [...grid.children].find((n) => n.classList.contains('appd-ghost')) ?? null;
}

function showGhost(grid, box) {
	const g = ghostOf(grid);
	if (!g) return;
	g.hidden = false;
	placeOnGrid(g, box);
}

function hideGhosts() {
	for (const g of host?.querySelectorAll('.appd-ghost') ?? []) g.hidden = true;
}

/** Whether a drag carries picture files, which a drop on the page makes pictures of. */
export function carriesPictures(ev) {
	const items = [...(ev.dataTransfer?.items ?? [])];
	return items.length > 0 && items.some((i) => i.kind === 'file' && PICTURE_TYPES.includes(i.type));
}

/** What is being dragged over the page, if it is anything the page takes. */
function dragging(ev) {
	if (fromList) return { kind: 'part', type: fromList };
	if (carriesPictures(ev)) return { kind: 'picture', type: 'image' };
	const names = hooks.treeNames?.() ?? [];
	if (names.length) return { kind: 'tree', type: treeType(names), names };
	return null;
}

/** The box a drop would fill, with its top-left in the cell under the pointer. */
function dropBox(grid, type, ev) {
	const spec = apps.COMPONENTS[type];
	const at = cellAt(grid, ev.clientX, ev.clientY);
	return apps.clampBox(type, {
		x: Math.min(at.col, apps.APP_COLUMNS - spec.w), y: Math.max(0, at.row), w: spec.w, h: spec.h,
	});
}

/** What a drop from the tree lands as first: a slider for parameters, a chart for anything else. */
function treeType(names) {
	const raw = hooks.raw();
	return names.every((n) => findBlock(raw, n)?.kind === 'parameter') ? 'slider' : 'chart';
}

function wireDrop(grid) {
	// A container's grid is inside the page's: only the innermost under the
	// pointer takes the drag, and the page's own drop -- a model file -- does
	// not take a picture meant for this one.
	const innermost = (ev) => ev.target?.closest?.('.appd-grid') === grid;
	grid.addEventListener('dragenter', (ev) => {
		if (!innermost(ev) || !dragging(ev)) return;
		ev.preventDefault();
		if (carriesPictures(ev)) ev.stopPropagation();
	});
	grid.addEventListener('dragover', (ev) => {
		if (!innermost(ev)) return;
		const what = dragging(ev);
		if (!what) return;
		ev.preventDefault();
		if (what.kind === 'picture') ev.stopPropagation();
		// What the source allows: the list and a file offer a copy, the tree a move.
		ev.dataTransfer.dropEffect = what.kind === 'tree' ? 'move' : 'copy';
		hideGhosts();
		showGhost(grid, dropBox(grid, what.type, ev));
	});
	grid.addEventListener('dragleave', (ev) => {
		const ghost = ghostOf(grid);
		if (ghost && !grid.contains(ev.relatedTarget)) ghost.hidden = true;
	});
	grid.addEventListener('drop', (ev) => {
		if (!innermost(ev)) return;
		const what = dragging(ev);
		hideGhosts();
		if (!what) return;
		ev.preventDefault();
		ev.stopPropagation();
		const box = dropBox(grid, what.type, ev);
		const where = gridWhere.get(grid);
		fromList = null;
		if (what.kind === 'part') { addPart(what.type, where, { x: box.x, y: box.y }); return; }
		if (what.kind === 'picture') {
			const file = [...(ev.dataTransfer?.files ?? [])].find((f) => PICTURE_TYPES.includes(f.type));
			if (file) addPicture(file, where, { x: box.x, y: box.y });
			return;
		}
		dropFromTree(what.names, box, where);
	});
}

/**
 * Parts for blocks dragged out of the tree: a slider for each parameter --
 * over its one value, or as a factor on every index of one that has index
 * lists -- stacked down from where they were dropped, and one chart of
 * everything else beside them.
 */
function dropFromTree(names, box, where) {
	const raw = hooks.raw();
	const params = [];
	const shown = [];
	for (const n of names) {
		const found = findBlock(raw, n);
		if (!found) continue;
		if (found.kind === 'parameter') params.push({ name: n, dims: effectiveDims(raw, found.block) });
		else shown.push(n);
	}
	if (!params.length && !shown.length) return;
	edit(`add ${names.length === 1 ? names[0] : `${names.length} blocks`} from the tree`, (r) => {
		let y = box.y;
		let last = null;
		for (const p of params.slice(0, 12)) {
			const target = p.dims.length ? { kind: 'value', block: p.name, factor: true } : { kind: 'value', block: p.name };
			const range = ai.defaultRange(r, target);
			last = apps.addComponent(r, where, 'slider', {
				at: { x: box.x, y },
				props: { target, min: range.min, max: range.max, scale: range.scale },
			});
			y += apps.COMPONENTS.slider.h;
		}
		if (shown.length) {
			const beside = params.length ? Math.min(box.x + apps.COMPONENTS.slider.w, apps.APP_COLUMNS - apps.COMPONENTS.chart.minW) : box.x;
			last = apps.addComponent(r, where, 'chart', {
				at: { x: beside, y: box.y },
				props: {
					w: Math.min(apps.COMPONENTS.chart.w, apps.APP_COLUMNS - beside),
					series: shown.slice(0, apps.MAX_SERIES).map((block) => ({ block })),
				},
			});
		}
		view.selected = last;
	});
}

// --- pictures ------------------------------------------------------------------------------

/** A file's contents as a data address. */
function readAsData(blob) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result));
		reader.onerror = () => reject(reader.error ?? new Error('The file could not be read.'));
		reader.readAsDataURL(blob);
	});
}

/**
 * A picture file as what an app keeps: the file itself where it is small, and
 * otherwise drawn again at most `PICTURE_SIDE` on its longer side, as WebP
 * where the browser writes it and JPEG where not -- a model file carries its
 * pictures, and a photograph straight off a camera would be most of it.
 *
 * @returns {Promise<string>} the data address
 */
export async function pictureFromFile(file) {
	if (!PICTURE_TYPES.includes(file.type)) {
		throw new Error('A picture has to be a PNG, JPEG, GIF, WebP or SVG file.');
	}
	if (file.size <= PICTURE_AS_IS) {
		const data = await readAsData(file);
		if (apps.readImageSrc(data)) return data;
	}
	if (file.type === 'image/svg+xml') {
		throw new Error(`That drawing is too large for a picture on an app: ${Math.round(PICTURE_AS_IS / 1000)} kB at most.`);
	}
	const bitmap = await createImageBitmap(file);
	for (const [side, quality] of [[PICTURE_SIDE, 0.85], [1200, 0.75], [800, 0.7]]) {
		const scale = Math.min(1, side / Math.max(bitmap.width, bitmap.height));
		const canvasEl = el('canvas', { width: Math.max(1, Math.round(bitmap.width * scale)), height: Math.max(1, Math.round(bitmap.height * scale)) });
		canvasEl.getContext('2d').drawImage(bitmap, 0, 0, canvasEl.width, canvasEl.height);
		let data = canvasEl.toDataURL('image/webp', quality);
		if (!data.startsWith('data:image/webp')) data = canvasEl.toDataURL('image/jpeg', quality);
		if (apps.readImageSrc(data)) return data;
	}
	throw new Error('That picture is too large for an app, even made smaller.');
}

/** A picture dropped or chosen: a new Picture part, or the picture of one already there. */
async function addPicture(file, where, at, onto = null) {
	let src;
	try {
		src = await pictureFromFile(file);
	} catch (e) {
		hooks.flash(e?.message ?? String(e), 'warn');
		return;
	}
	const alt = file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
	if (onto) {
		patch(onto, (cur) => ({ src, alt: cur.alt || alt }), 'choose a picture');
		return;
	}
	addPart('image', where, at, { src, alt });
}

// --- keeping the caret across a redraw ---------------------------------------------------------

function rememberFocus() {
	const a = document.activeElement;
	if (!host || !a || !host.contains(a)) return null;
	return {
		part: a.classList?.contains('appd-item') ? a.dataset.id : null,
		prop: a.dataset?.prop ?? null,
		start: typeof a.selectionStart === 'number' ? a.selectionStart : null,
		end: typeof a.selectionEnd === 'number' ? a.selectionEnd : null,
	};
}

function restoreFocus(f) {
	if (!f) return;
	const q = f.part ? `.appd-item[data-id="${CSS.escape(f.part)}"]` : f.prop ? `[data-prop="${CSS.escape(f.prop)}"]` : null;
	const node = q ? host.querySelector(q) : null;
	if (!node) return;
	node.focus({ preventScroll: true });
	if (f.start != null && typeof node.setSelectionRange === 'function') {
		try { node.setSelectionRange(f.start, f.end ?? f.start); } catch { /* not a field with a caret */ }
	}
}

// --- the settings on the right ------------------------------------------------------------------

/** A row: the name, the control, and its (i) where it has one. */
function row(label, control, info = null) {
	return el('div', { className: `appd-row${info ? ' has-info' : ''}` },
		el('label', {}, label), control, info);
}

/** A row under another, for one of its index lists. */
function subRow(label, control) {
	const r = row(label, control);
	r.classList.add('is-sub');
	return r;
}

function info(key) {
	return infoButton(`app:${key}`, () => appTopic(key));
}

/** A text box that writes on Enter and on leaving it. */
function textBox(prop, value, commit, { placeholder = '', area = false } = {}) {
	const input = area
		? el('textarea', { rows: 6, spellcheck: true, placeholder })
		: el('input', { type: 'text', spellcheck: false, placeholder });
	input.value = value ?? '';
	input.dataset.prop = prop;
	input.addEventListener('change', () => {
		fieldSaving = true;
		commit(input.value);
		// A commit that made no edit leaves nothing owed.
		fieldSaving = false;
	});
	if (!area) {
		input.addEventListener('keydown', (ev) => {
			if (ev.key !== 'Enter') return;
			refocus = prop;
			input.blur();
		});
	}
	return input;
}

/** A number box: empty is null, and something that is not a number is put back. */
function numberBox(prop, value, commit, { placeholder = '' } = {}) {
	return textBox(prop, value == null ? '' : String(value), (text) => {
		const t = text.trim();
		if (!t) { commit(null); return; }
		const n = Number(t.replace(/−/g, '-'));
		if (!Number.isFinite(n)) {
			hooks.flash(`'${t}' is not a number.`, 'warn');
			renderAppDesigner(host, hooks);
			return;
		}
		commit(n);
	}, { placeholder });
}

function choice(prop, options, value, commit) {
	const s = el('select', {});
	s.dataset.prop = prop;
	for (const [v, label] of options) s.append(el('option', { value: v, selected: v === value }, label));
	s.addEventListener('change', () => commit(s.value));
	return s;
}

function tick(prop, checked, commit, label) {
	const box = el('input', { type: 'checkbox', checked: !!checked });
	box.dataset.prop = prop;
	box.addEventListener('change', () => commit(box.checked));
	return el('label', { className: 'appd-tick' }, box, label);
}

/** A small button of the form, found again by its `prop` after a redraw. */
function formButton(text, prop, onClick, { danger = false, title = '' } = {}) {
	const b = el('button', { type: 'button', className: `ghost appd-small${danger ? ' appd-danger' : ''}`, title }, text);
	b.dataset.prop = prop;
	b.addEventListener('click', onClick);
	return b;
}

function properties(app) {
	const box = el('aside', { className: 'appd-props', 'aria-label': 'Settings' });
	const found = view.selected ? apps.findComponent(app, view.selected) : null;
	if (found) box.append(...partSettings(app, found.component, found));
	else box.append(...appSettings(app));
	return box;
}

function heading(text, key) {
	return el('div', { className: 'appd-props-head' }, el('b', {}, text), el('span', { className: 'spacer' }), key ? info(key) : null);
}

const BUTTON_ACTIONS = [['run', 'Run the model'], ['sample', 'Run the spread'], ['reset', 'Put the controls back']];
const BUTTON_PLACEHOLDER = { run: 'Run', sample: 'Run the spread', reset: 'Reset' };

function partSettings(app, c, found) {
	const spec = apps.COMPONENTS[c.type];
	const out = [heading(spec.name, `part:${c.type}`)];
	const problem = hooks.context().problemOf(c);
	if (problem) out.push(el('p', { className: 'appd-problem', role: 'status' }, problem));
	if (spec.group === 'input' && c.type !== 'button') {
		out.push(row('Label', textBox('label', c.label, (v) => patch(c, { label: v }), { placeholder: ai.describeTarget(c.target) })));
		out.push(...targetRows(c));
		out.push(...inputRows(c));
	} else if (c.type === 'button') {
		out.push(row('Does', choice('action', BUTTON_ACTIONS, c.action, (v) => patch(c, { action: v }))));
		out.push(row('Label', textBox('label', c.label, (v) => patch(c, { label: v }), { placeholder: BUTTON_PLACEHOLDER[c.action] })));
		if (c.action === 'sample') out.push(el('p', { className: 'hint appd-note' }, spreadNote(app)));
	} else if (spec.group === 'output') {
		out.push(row('Title', textBox('title', c.title, (v) => patch(c, { title: v }), { placeholder: 'from what it shows' })));
		out.push(...seriesRows(c));
		out.push(...outputRows(c, app));
	} else if (c.type === 'panel') {
		out.push(row('Title', textBox('title', c.title, (v) => patch(c, { title: v }), { placeholder: 'none' })));
		out.push(el('p', { className: 'hint appd-note' }, 'Drag parts into it, or select it and click one in the list on the left.'));
	} else if (c.type === 'tabs') {
		out.push(...tabRows(c));
	} else if (c.type === 'image') {
		out.push(...pictureRows(c));
	} else {
		const words = textBox('text', c.text, (v) => patch(c, { text: v }), { area: true, placeholder: '**Bold**, *italic*, lists starting - ' });
		words.maxLength = apps.TEXT_MAX;
		out.push(el('div', { className: 'appd-stack' }, el('label', {}, 'Text'), words));
		out.push(row('Style', choice('style', [['body', 'Body'], ['title', 'Title'], ['heading', 'Heading'], ['note', 'Note']],
			c.style, (v) => patch(c, { style: v }))));
		out.push(row('Align', choice('align', [['left', 'Left'], ['center', 'Centre'], ['right', 'Right']],
			c.align, (v) => patch(c, { align: v }))));
	}
	out.push(placeRows(app, c, found));
	return out;
}

/** A set of tabs' own tabs: a name each, their order, and one more. */
function tabRows(c) {
	const out = [el('div', { className: 'appd-sub' }, 'Tabs')];
	c.tabs.forEach((t, i) => {
		const name = textBox(`tab-name-${i}`, t.name, (v) => edit('rename a tab', (raw) => apps.renameTab(raw, c.id, i, v)));
		const up = el('button', { type: 'button', className: 'ghost appd-x', title: 'Move the tab left', 'aria-label': 'Move the tab left' }, '↑');
		up.disabled = i === 0;
		up.addEventListener('click', () => edit('move a tab', (raw) => { if (apps.moveTab(raw, c.id, i, i - 1)) view.tabs.set(c.id, i - 1); }));
		const drop = el('button', { type: 'button', className: 'ghost appd-x', title: 'Delete the tab and what is on it', 'aria-label': 'Delete the tab' }, '×');
		drop.disabled = c.tabs.length <= 1;
		drop.addEventListener('click', () => edit('delete a tab', (raw) => {
			apps.removeTab(raw, c.id, i);
			view.tabs.set(c.id, Math.max(0, i - 1));
		}));
		out.push(el('div', { className: 'appd-option appd-tab-row' }, name, up, drop));
	});
	const add = formButton('Add a tab', 'tab-add', () => edit('add a tab', (raw) => {
		const at = apps.addTab(raw, c.id);
		if (at >= 0) view.tabs.set(c.id, at);
	}));
	add.disabled = c.tabs.length >= apps.MAX_TABS;
	out.push(el('div', { className: 'appd-actions' }, add));
	out.push(el('p', { className: 'hint appd-note' }, 'Choose a tab on the page to put parts on it.'));
	return out;
}

/** A picture's settings: the picture, what it shows, how it fills its box. */
function pictureRows(c) {
	const pick = el('input', { type: 'file', accept: PICTURE_TYPES.join(','), hidden: true });
	pick.addEventListener('change', () => {
		const file = pick.files?.[0];
		if (file) addPicture(file, null, null, c);
	});
	const choose = formButton(c.src ? 'Another picture…' : 'Choose a picture…', 'picture-choose', () => pick.click(),
		{ title: 'A PNG, JPEG, GIF, WebP or SVG file. A large one is made smaller: the model file carries it.' });
	const clear = formButton('Remove it', 'picture-clear', () => patch(c, { src: '' }, 'remove a picture'), { danger: true });
	clear.disabled = !c.src;
	const out = [el('div', { className: 'appd-actions' }, choose, clear, pick)];
	if (c.src) out.push(el('p', { className: 'hint appd-note' }, `${Math.round((c.src.length * 3) / 4 / 1000).toLocaleString()} kB in the model file.`));
	out.push(row('Describes', textBox('alt', c.alt, (v) => patch(c, { alt: v }), { placeholder: 'what it shows, for a screen reader' })));
	out.push(row('Fits', choice('fit', [['contain', 'shown whole'], ['cover', 'filling the box']], c.fit, (v) => patch(c, { fit: v }))));
	out.push(row('Caption', textBox('caption', c.caption, (v) => patch(c, { caption: v }), { placeholder: 'none' })));
	return out;
}

/** What an input sets: the thing, and the index of it. */
function targetRows(c) {
	const raw = hooks.raw();
	const choices = ai.inputChoices(raw);
	const current = c.target
		? (c.target.kind === 'value' || c.target.kind === 'enabled' ? `${c.target.kind}:${c.target.block}` : c.target.kind)
		: '';
	const s = el('select', {});
	s.dataset.prop = 'target';
	s.append(el('option', { value: '', disabled: true, selected: !current }, 'Choose what it sets…'));
	const group = (label, entries) => {
		if (!entries.length) return;
		const g = el('optgroup', { label });
		for (const [v, text] of entries) g.append(el('option', { value: v, selected: v === current }, text));
		s.append(g);
	};
	if (ai.canSet(c.type, 'value')) {
		group('Parameters', choices.values.filter((v) => v.kind === 'parameter').map((v) => [`value:${v.block}`, v.block]));
		group('Values at the start', choices.values.filter((v) => v.kind === 'compartment').map((v) => [`value:${v.block}`, v.block]));
	}
	const run = [];
	if (ai.canSet(c.type, 'scenario') && choices.scenarios.length) run.push(['scenario', 'Scenario']);
	if (ai.canSet(c.type, 'end_time')) run.push(['end_time', 'End of the run']);
	group('The run', run);
	if (ai.canSet(c.type, 'enabled')) group('A block on or off', choices.blocks.map((b) => [`enabled:${b}`, b]));
	// Pointed at something the model does not have: said, and kept selected.
	if (current && ![...s.options].some((o) => o.value === current)) {
		s.append(el('option', { value: current, selected: true }, `${ai.describeTarget(c.target)} (not in the model)`));
	}
	s.addEventListener('change', () => {
		const v = s.value;
		let target;
		if (v === 'scenario' || v === 'end_time') target = { kind: v };
		else if (v.startsWith('enabled:')) target = { kind: 'enabled', block: v.slice(8) };
		else {
			const block = v.slice(6);
			const entry = choices.values.find((x) => x.block === block);
			const index = {};
			(entry?.dims ?? []).forEach((d, k) => { if (entry.indices[k]?.length) index[d] = entry.indices[k][0]; });
			target = Object.keys(index).length ? { kind: 'value', block, index } : { kind: 'value', block };
		}
		patch(c, retargeted(c, target, raw), 'connect a control');
	});
	const out = [row('Sets', s, info('target'))];
	if (c.target?.kind === 'value') {
		const entry = choices.values.find((x) => x.block === c.target.block);
		(entry?.dims ?? []).forEach((d, k) => {
			const every = !Object.prototype.hasOwnProperty.call(c.target.index ?? {}, d);
			const opts = [['', 'every one, as a factor'], ...entry.indices[k].map((i) => [`=${i}`, i])];
			out.push(subRow(d, choice(`index-${d}`, opts, every ? '' : `=${c.target.index[d]}`, (v) => {
				const index = { ...(now(c).target?.index ?? {}) };
				if (v) index[d] = v.slice(1); else delete index[d];
				const open = entry.dims.some((x) => !Object.prototype.hasOwnProperty.call(index, x));
				const target = { kind: 'value', block: c.target.block, ...(Object.keys(index).length ? { index } : {}), ...(open ? { factor: true } : {}) };
				patch(c, retargeted(c, target, raw), 'connect a control');
			})));
		});
	}
	return out;
}

/**
 * A control pointed somewhere new, with the settings that follow from where:
 * a slider takes the range of what it now sets, and a switch its two values.
 */
function retargeted(c, target, raw) {
	const out = { target };
	if (c.type === 'slider') {
		const r = ai.defaultRange(raw, target);
		Object.assign(out, { min: r.min, max: r.max, scale: r.scale, step: null });
	}
	if (c.type === 'number') Object.assign(out, { min: null, max: null });
	return out;
}

function inputRows(c) {
	const out = [];
	if (c.type === 'slider') {
		out.push(row('Min', numberBox('min', c.min, (v) => patch(c, { min: v }))));
		out.push(row('Max', numberBox('max', c.max, (v) => patch(c, { max: v }))));
		out.push(row('Scale', choice('scale', [['linear', 'Linear'], ['log', 'Logarithmic']], c.scale, (v) => patch(c, { scale: v }))));
		if (c.scale !== 'log') out.push(row('Step', numberBox('step', c.step, (v) => patch(c, { step: v }), { placeholder: 'smooth' })));
		if (c.target) {
			out.push(el('div', { className: 'appd-actions' }, formButton('Range from the model', 'range-again', () => patch(c, (cur) => {
				const r = ai.defaultRange(hooks.raw(), cur.target);
				return { min: r.min, max: r.max, scale: r.scale };
			}, 'set a range'), { title: 'The parameter’s distribution where it has one, and a decade either side of its value where not' })));
		}
	}
	if (c.type === 'number') {
		out.push(row('Min', numberBox('min', c.min, (v) => patch(c, { min: v }), { placeholder: 'none' })));
		out.push(row('Max', numberBox('max', c.max, (v) => patch(c, { max: v }), { placeholder: 'none' })));
	}
	if (c.type === 'switch' && c.target?.kind === 'value') {
		out.push(row('On', numberBox('on', c.on, (v) => patch(c, { on: v ?? 1 }))));
		out.push(row('Off', numberBox('off', c.off, (v) => patch(c, { off: v ?? 0 }))));
	}
	if ((c.type === 'dropdown' || c.type === 'radio') && c.target?.kind === 'value') {
		out.push(el('div', { className: 'appd-sub' }, 'Choices'));
		const opts = c.options ?? [];
		const each = (fn) => (cur) => ({ options: fn(cur.options ?? []) });
		opts.forEach((o, k) => {
			const label = textBox(`opt-label-${k}`, o.label,
				(v) => patch(c, each((list) => list.map((x, j) => (j === k ? { ...x, label: v } : x)))), { placeholder: 'label' });
			const value = numberBox(`opt-value-${k}`, o.value, (v) => {
				if (v == null) return;
				patch(c, each((list) => list.map((x, j) => (j === k ? { ...x, value: v } : x))));
			});
			const drop = el('button', { type: 'button', className: 'ghost appd-x', 'aria-label': 'Remove the choice', title: 'Remove the choice' }, '×');
			drop.dataset.prop = `opt-drop-${k}`;
			drop.addEventListener('click', () => patch(c, each((list) => list.filter((_, j) => j !== k))));
			out.push(el('div', { className: 'appd-option' }, label, value, drop));
		});
		const add = formButton('Add a choice', 'opt-add', () => patch(c, each((list) => {
			const v = ai.modelValue(hooks.raw(), c.target);
			const base = list.length ? list[list.length - 1].value : (Number.isFinite(v) ? v : 0);
			const next = list.length ? (base === 0 ? 1 : base * 10) : base;
			return [...list, { label: '', value: next }];
		}), 'add a choice'));
		add.disabled = opts.length >= apps.MAX_OPTIONS;
		out.push(el('div', { className: 'appd-actions' }, add));
	}
	if ((c.type === 'dropdown' || c.type === 'radio') && c.target?.kind === 'scenario') {
		const names = ai.inputChoices(hooks.raw()).scenarios;
		out.push(el('p', { className: 'hint appd-note' }, `Offers the model’s scenarios: ${names.join(', ') || 'none'}.`));
	}
	return out;
}

/** The kinds of series, as the picker groups them. */
const SERIES_GROUPS = [
	['compartment', 'Compartments'], ['expression', 'Expressions'], ['transfer', 'Transfers'],
	['parameter', 'Parameters'],
];

/** What an output shows: a row per block, with its indices. */
function seriesRows(c) {
	const outputs = hooks.outputs();
	const single = apps.SINGLE_SERIES.has(c.type);
	const choices = ai.seriesChoices(outputs ?? []);
	const out = [el('div', { className: 'appd-sub' }, 'Shows', info('series'))];
	if (!outputs) {
		out.push(el('p', { className: 'hint appd-note' },
			'The model does not build as it stands, so what it reports cannot be listed. The series named are kept.'));
	}
	const refs = c.series ?? [];
	refs.forEach((ref, k) => out.push(seriesRow(c, refs, k, choices, single)));
	if (!single || !refs.length) {
		const add = formButton(single ? 'Choose a series' : 'Add a series', 'series-add', () => patch(c, (cur) => {
			const have = cur.series ?? [];
			const used = new Set(have.map((r) => r.block));
			const pick = choices.find((x) => !used.has(x.block) && x.kind !== 'parameter') ?? choices[0];
			return { series: [...have, refFor(pick, single)] };
		}, 'add a series'));
		add.disabled = !choices.length || refs.length >= apps.MAX_SERIES;
		out.push(el('div', { className: 'appd-actions' }, add));
	}
	return out;
}

/** A reference to a block's series: every index, or the first of each for one number. */
function refFor(entry, single) {
	if (!entry) return { block: '' };
	if (!single || !entry.dims.length) return { block: entry.block };
	const index = {};
	entry.dims.forEach((d, k) => { if (entry.indices[k]?.length) index[d] = entry.indices[k][0]; });
	return { block: entry.block, index };
}

function seriesRow(c, refs, k, choices, single) {
	const ref = refs[k];
	const s = el('select', { 'aria-label': 'Which block' });
	s.dataset.prop = `series-${k}`;
	const seen = new Set();
	for (const [kind, label] of [...SERIES_GROUPS, ['*', 'Other results']]) {
		const members = choices.filter((x) => (kind === '*' ? !SERIES_GROUPS.some(([g]) => g === x.kind) : x.kind === kind));
		if (!members.length) continue;
		const g = el('optgroup', { label });
		for (const x of members) {
			seen.add(x.block);
			g.append(el('option', { value: x.block, selected: x.block === ref.block }, x.block));
		}
		s.append(g);
	}
	if (!seen.has(ref.block)) s.prepend(el('option', { value: ref.block, selected: true }, `${ref.block || 'Choose…'}${ref.block ? ' (not reported)' : ''}`));
	const replace = (next) => patch(c, (cur) => ({ series: (cur.series ?? []).map((r, j) => (j === k ? next : r)) }), 'change what a result shows');
	s.addEventListener('change', () => replace(refFor(choices.find((x) => x.block === s.value), single)));
	const drop = el('button', { type: 'button', className: 'ghost appd-x', 'aria-label': 'Remove the series', title: 'Remove the series' }, '×');
	drop.dataset.prop = `series-drop-${k}`;
	drop.addEventListener('click', () => patch(c, (cur) => ({ series: (cur.series ?? []).filter((_, j) => j !== k) }), 'remove a series'));
	const line = el('div', { className: 'appd-series' }, s, drop);
	const out = el('div', { className: 'appd-series-block' }, line);
	const entry = choices.find((x) => x.block === ref.block);
	(entry?.dims ?? []).forEach((d, j) => {
		const every = !Object.prototype.hasOwnProperty.call(ref.index ?? {}, d);
		const opts = [...(single ? [] : [['', 'every one']]), ...entry.indices[j].map((i) => [`=${i}`, i])];
		out.append(subRow(d, choice(`series-${k}-${d}`, opts, every ? '' : `=${ref.index[d]}`, (v) => {
			const index = { ...(now(c).series?.[k]?.index ?? {}) };
			if (v) index[d] = v.slice(1); else delete index[d];
			replace(Object.keys(index).length ? { block: ref.block, index } : { block: ref.block });
		})));
	});
	return out;
}

/** Where a result reading a sample stands: which sample, and when it runs. */
function spreadNote(app) {
	const n = (app?.realisations ?? 200).toLocaleString();
	return app?.spread_when === 'change'
		? `The spread is sampled, ${n} realisations, after every change of a control: see the app’s settings.`
		: `The spread is sampled, ${n} realisations, when Run the spread is pressed: see the app’s settings.`;
}

function outputRows(c, app) {
	const out = [];
	const stat = () => {
		const s = row('Reads', choice('statistic', Object.entries(apps.STATISTICS), c.statistic, (v) => patch(c, { statistic: v })), info('statistic'));
		out.push(s);
		if (c.statistic === 'at') out.push(row('At time', numberBox('at', c.at, (v) => patch(c, { at: v }), { placeholder: hooks.raw()?.simulation?.time_unit ?? 'year' })));
	};
	const curve = () => {
		out.push(row('Of', choice('curve', Object.entries(apps.CURVES), c.curve, (v) => patch(c, { curve: v })), info('spread')));
		if (c.curve !== 'run') out.push(el('p', { className: 'hint appd-note' }, spreadNote(app)));
	};
	if (c.type === 'chart') {
		out.push(row('X axis', choice('x_scale', [['log', 'Logarithmic'], ['linear', 'Linear']], c.x_scale, (v) => patch(c, { x_scale: v }))));
		out.push(row('Y axis', choice('y_scale', [['log', 'Logarithmic'], ['linear', 'Linear']], c.y_scale, (v) => patch(c, { y_scale: v }))));
		out.push(row('Spread', choice('spread', [['none', 'none'], ['bands', 'percentile bands']], c.spread, (v) => patch(c, { spread: v })), info('spread')));
		out.push(el('div', { className: 'appd-actions' },
			tick('mean', c.mean, (v) => patch(c, { mean: v }), 'The mean of the realisations, as a line'),
			tick('legend', c.legend, (v) => patch(c, { legend: v }), 'A legend under two or more lines')));
		if (c.spread !== 'none' || c.mean) out.push(el('p', { className: 'hint appd-note' }, spreadNote(app)));
	}
	if (c.type === 'value') {
		stat();
		curve();
		out.push(row('Digits', numberBox('digits', c.digits, (v) => patch(c, { digits: v ?? 3 }))));
		out.push(row('Limit', numberBox('limit', c.limit, (v) => patch(c, { limit: v }), { placeholder: 'none' })));
	}
	if (c.type === 'gauge') {
		stat();
		curve();
		out.push(row('Min', numberBox('min', c.min, (v) => patch(c, { min: v }), { placeholder: 'auto' })));
		out.push(row('Max', numberBox('max', c.max, (v) => patch(c, { max: v }), { placeholder: 'auto' })));
		out.push(row('Limit', numberBox('limit', c.limit, (v) => patch(c, { limit: v }), { placeholder: 'none' })));
		out.push(row('Scale', choice('scale', [['linear', 'Linear'], ['log', 'Logarithmic']], c.scale, (v) => patch(c, { scale: v }))));
	}
	if (c.type === 'bars') {
		stat();
		curve();
		out.push(row('Scale', choice('scale', [['log', 'Logarithmic'], ['linear', 'Linear']], c.scale, (v) => patch(c, { scale: v }))));
		out.push(el('div', { className: 'appd-actions' }, tick('sort', c.sort, (v) => patch(c, { sort: v }), 'Largest first')));
	}
	if (c.type === 'table') {
		curve();
		out.push(row('Times', textBox('times', (c.times ?? []).join(', '), (text) => {
			const times = text.split(/[,;\s]+/).filter(Boolean).map(Number).filter(Number.isFinite);
			patch(c, { times });
		}, { placeholder: 'the run’s own' })));
		if (!c.times?.length) out.push(row('Rows', numberBox('rows', c.rows, (v) => patch(c, { rows: v ?? 10 }))));
	}
	return out;
}

/** Where the part is, in cells, and what can be done with it. */
function placeRows(app, c, found) {
	const cell = (key, label) => {
		const box = numberBox(`place-${key}`, key === 'x' || key === 'y' ? c[key] + 1 : c[key], (v) => {
			if (v == null) return;
			const cur = now(c);
			const to = { x: cur.x, y: cur.y, w: cur.w, h: cur.h, [key]: key === 'x' || key === 'y' ? v - 1 : v };
			// A new width grows the part to the right, as its corner does; a new
			// column moves it.
			edit(key === 'w' || key === 'h' ? 'resize a part' : 'move a part',
				(raw) => apps.placeComponent(raw, c.id, apps.clampBox(cur.type, to, { keepLeft: key === 'w' })));
		});
		box.setAttribute('aria-label', label);
		return el('label', { className: 'appd-cell' }, el('span', {}, label), box);
	};
	// In cells of the grid it is on, which for a part in a container is the
	// container's: said, since the numbers mean nothing without it.
	const holder = found?.parent ?? null;
	let inWhat = '';
	if (holder?.type === 'tabs') inWhat = ` — in the tab ${holder.tabs?.[found.slot]?.name ?? ''}`;
	else if (holder) inWhat = ` — in the panel${holder.title ? ` ${holder.title}` : ''}`;
	const box = el('div', { className: 'appd-place' },
		el('div', { className: 'appd-sub' }, `Place${inWhat}`),
		el('div', { className: 'appd-cells' }, cell('x', 'Column'), cell('y', 'Row'), cell('w', 'Width'), cell('h', 'Height')));
	if (app && app.pages.length > 1 && !found?.parent) {
		box.append(row('Page', choice('page', app.pages.map((p, i) => [String(i), p.name]), String(view.page), (v) => {
			const to = Number(v);
			edit('move a part to another page', (raw) => apps.moveComponentToPage(raw, c.id, to));
		})));
	}
	const actions = [formButton('Duplicate', 'part-duplicate', () => duplicatePart(c.id))];
	if (found?.parent) {
		actions.push(formButton('Take it out', 'part-out', () => edit('move a part onto the page', (raw) => apps.moveComponent(raw, c.id, pageWhere())),
			{ title: 'Onto the page, out of the panel or the tabs it is in' }));
	}
	actions.push(formButton('Delete', 'part-delete', () => removePart(c.id), { danger: true }));
	box.append(el('div', { className: 'appd-actions' }, ...actions));
	return box;
}

/** With nothing selected: the page, and the app as a whole. */
function appSettings(app) {
	if (!app) {
		const start = el('button', { type: 'button', className: 'primary' }, 'Start from the model');
		start.addEventListener('click', startFromModel);
		return [heading('App', 'designer'),
			el('p', { className: 'hint appd-note' }, 'This model has no app. Put a first part on the page, or '
				+ 'let the model suggest one: sliders for what it is uncertain about and a chart of what it is for.'),
			el('div', { className: 'appd-actions' }, start)];
	}
	const page = currentPage(app);
	const out = [heading('Page', 'page'),
		row('Name', textBox('page-name', page.name, (v) => edit('rename a page', (raw) => apps.renamePage(raw, view.page, v))))];
	const del = formButton('Delete the page', 'page-delete', () => edit('delete a page', (raw) => {
		apps.removePage(raw, view.page);
		view.page = Math.max(0, view.page - 1);
	}), { danger: true });
	del.disabled = app.pages.length <= 1;
	del.title = del.disabled ? 'An app has one page at least' : 'The parts on it go with it; Undo brings them back';
	out.push(el('div', { className: 'appd-actions' }, del));

	out.push(heading('App', 'app'));
	const set = (key) => (v) => edit('change the app', (raw) => apps.setAppSettings(raw, { [key]: v }));
	out.push(row('Title', textBox('app-title', app.title, set('title'), { placeholder: hooks.raw()?.name ?? '' })));
	out.push(el('div', { className: 'appd-stack' }, el('label', {}, 'Description'),
		textBox('app-description', app.description, set('description'), { area: true, placeholder: 'What the app is for, under its title' })));
	out.push(row('Looks', choice('app-theme', apps.THEMES.map((t) => [t.id, `${t.name}${t.mode === 'dark' ? ' (dark)' : ''}`]), app.theme, set('theme')), info('theme')));
	out.push(row('Runs', choice('app-run', [['change', 'whenever a control changes'], ['button', 'when Run is pressed']], app.run, set('run'))));
	out.push(row('Opens as', choice('app-open', [['editor', 'the editor'], ['app', 'the app']], app.open, set('open'))));
	out.push(el('div', { className: 'appd-actions' }, tick('app-edit', app.edit_button, set('edit_button'), 'Offer Edit while it runs')));

	out.push(heading('The spread', 'spread'));
	out.push(row('Realisations', numberBox('app-realisations', app.realisations, (v) => set('realisations')(v ?? 200))));
	out.push(row('Sampled', choice('app-spread', [['button', 'when Run the spread is pressed'], ['change', 'after every change']], app.spread_when, set('spread_when'))));
	out.push(el('p', { className: 'hint appd-note' }, 'The model run many times at the controls: a control moved from the '
		+ 'model’s value holds its input there, a factor scales a distribution, and every other distribution is drawn '
		+ 'from. Results read it where they ask to.'));

	const again = formButton('Start again from the model', 'app-again', startFromModel,
		{ title: 'Replace the parts with the ones the model suggests; Undo brings these back' });
	const drop = formButton('Remove the app', 'app-remove', () => edit('remove the app', (raw) => {
		apps.removeApp(raw);
		view.page = 0;
		view.selected = null;
	}), { danger: true, title: 'Take the app out of the model; Undo brings it back' });
	out.push(el('div', { className: 'appd-actions' }, again, drop));
	return out;
}
