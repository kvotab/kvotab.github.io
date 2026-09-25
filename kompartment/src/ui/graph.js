/**
 * Graphical model editor.
 *
 * SVG rather than canvas: nodes and edges are real elements, so hit-testing,
 * focus, keyboard handling and accessibility come from the DOM instead of
 * being rebuilt by hand.
 *
 * What is drawn:
 *   compartments   solid rounded boxes -- the state variables
 *   expressions    dashed boxes -- algebraic quantities
 *   transfers      curved arrows, labelled with the rate equation
 *   influences     dotted arrows into an expression from what it reads
 *   terminals      small bars for a transfer with no compartment at one end
 *
 * Geometry lives in project.layout, keyed by block name -- and, for a
 * connection's bend point, by "edge:<name>". That is the same separation
 * Ecolego keeps between its data model and its presentation model.
 *
 * Interaction notes, all learned the hard way:
 *
 *  - Dragging updates the DOM directly and re-renders only on release. A
 *    re-render mid-drag would replace the element the pointer is captured on,
 *    which looked like the node refusing to move while its edges followed.
 *  - Selection therefore toggles classes rather than re-rendering.
 *  - Every edge is a cubic Bezier leaving one node's side and entering
 *    another's, so a diagram of boxes does not read as a bundle of straight
 *    lines. A selected edge grows a handle you can drag to bend it.
 */

import * as ed from '../domain/edit.js';
import {
	qualifiedName,
	systemOf,
	baseName,
	parentOf,
	isWithin,
	reparent as reparentSystem,
} from '../domain/systems.js';
import {
	shapePath,
	shapeInset,
	shapeDecoration,
	shapeCorner,
	borderPoint,
	radiationTrefoil,
	sinkCloud,
	pipeTag,
} from './shapes.js';
import { openMenu, closeMenu } from './menu.js';
import { GRID } from '../domain/layout.js';

/**
 * What each line style is, as a dash pattern in model units.
 *
 * In model units so a dash keeps its proportions when the diagram is zoomed,
 * the way the line's own width does. The names are the canvas shapes' --
 * `SHAPE_DASHES` -- so the file format has one vocabulary for a line.
 */
const DASH_PATTERN = Object.assign(Object.create(null), {
	dashed: '7 5',
	dotted: '1.5 4',
});

/**
 * The kinds that carry a connect port on their right edge.
 *
 * A compartment takes transfers both ways; a far-field path is dragged *from*,
 * to deliver its release. Both therefore lose the `e` resize grip, which would
 * sit on this tool -- one list, so the two cannot drift apart again.
 */
const HAS_PORT = new Set(['compartment', 'farfield', 'waste_package']);

/** Which way each arrow key moves a selection, in grid steps. */
const NUDGE = Object.assign(Object.create(null), {
	ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
});
import { figureParts, figureSize, figureText, isDiagonal, ROLES } from './figures.js';
import { wheelPixels } from './wheel.js';
import {
	PICTURE_KINDS,
	diagramSvgText,
	rasterise,
	saveBlob,
	fileName,
	unionBox,
} from './picture.js';
import { INTERPOLATION_BLURB } from '../domain/lookup.js';
import { summariseTable, summarise } from './summary.js';
import { symbolTspans, symbolText, displayName } from './symbol.js';
import { inkFor } from './ink.js';
import { hasSymbol } from '../domain/symbol.js';
import { sparkPath, tablePoints } from './lookup-editor.js';
import { markPath, MARK_W, MARK_H } from './icons.js';

const NS = 'http://www.w3.org/2000/svg';

// Fallbacks only: every node carries its own size, from ed.blockSize().
const NODE_W = 136;
const NODE_H = 54;

/**
 * The kinds that wear their tree glyph on the canvas as well.
 *
 * A far-field pathway, a waste package and the three blocks that remember are
 * all drawn as rectangles, and a transport as the same folder an ordinary
 * sub-system gets. Shape says which family a block is in and colour separates
 * the members -- but colour alone is a weak thing to ask a reader to hold, and
 * nothing at all for a reader who cannot tell two of them apart. So the glyph
 * the tree already uses is drawn in the corner of the body, once, in the same
 * geometry.
 *
 * **The rounded box is the crowded one.** Five kinds wear it -- a compartment,
 * an expression, the two reductions and a function -- and on the canvas they
 * carry a name and a dimension line and nothing else, so what tells them apart
 * is the fill colour and only that. A reader who is not holding five fills in
 * their head, or who cannot tell two of them apart at all, is looking at five
 * identical boxes. So the four that are *not* compartments say so.
 *
 * The compartment itself stays bare, and that is the rule rather than an
 * oversight: the shape's plain reading is "a compartment", a glyph means "this
 * looks like one and is not", and marking all five would leave the mark saying
 * nothing.
 *
 * Not every kind with a mark: a lookup table already draws its own curve, and
 * a parameter has a shape of its own. These are the ones whose shape is shared
 * with something else.
 *
 * **The diamond is left out on purpose.** A trigger and a disruptive event
 * share it, so by the rule above a trigger should be marked -- but a diamond
 * is 35 pixels tall by default and the guard below wants 45 before it will put
 * a glyph beside a name. Marking it would mean either a taller diamond or a
 * glyph at half scale, and both are a change to the shape language rather than
 * to this list. The two are told apart in the tree instead, where a trigger's
 * mark now exists; see `step` in ./icons.js.
 */
const GLYPH_KINDS = new Set([
	// Shares the rounded box with a compartment.
	'expression', 'index_reduction', 'block_reduction', 'function',
	// Shares a rectangle with a lookup table, and a folder with a sub-system.
	'farfield', 'waste_package', 'min_max', 'running_mean', 'snapshot', 'transport',
]);

/** How big the glyph is drawn on a node, and how far in from the corner. */
const GLYPH_SCALE = 1.5;
const GLYPH_PAD = 8;
const PORT_R = 7;
/** How far a terminal for an open-ended transfer sits from its node. */
const TERMINAL_GAP = 74;
/**
 * How far apart transfers that join the same two compartments are drawn.
 * Several are allowed -- two routes between the same places, or one per
 * process -- and on one path they would be a single line with two labels
 * written over each other.
 */
const BUNDLE_GAP = 34;
/**
 * How far apart two loose ends of the same block are stacked. Wide enough for
 * the tallest marker that sits at one: they used to be 26 apart, which was
 * room for a cloud and four short of a pipe tag, so a block with two of them
 * had the two drawn over each other.
 */
const TERMINAL_SLOT = 38;
/**
 * The pipe tag at an end that is in another sub-system: how much it holds and
 * how big that makes it. `gport` was taken -- that is the grip on a
 * compartment’s edge a connection is dragged out of -- so this wears the
 * other half of the name the request used for it.
 *
 * Sized from the character count rather than measured, like every other label
 * in this file: measuring means laying the text out first, and the tag has to
 * be drawn before it can be laid out. Mono at 10.5px advances 6.3px.
 */
const PIPE_CHARS = 12;
const PIPE_CHAR_W = 6.3;
/** The second line is smaller and proportional: sans at 9px averages 4.7px. */
const PIPE_SUB_CHARS = 15;
const PIPE_SUB_W = 4.7;
const PIPE_PAD = 8;
const PIPE_H = 30;
const pipeWidth = (name, sub) => PIPE_PAD * 2 + 13
	+ Math.max(name.length * PIPE_CHAR_W, sub.length * PIPE_SUB_W);
const PIPE_W_MAX = pipeWidth('x'.repeat(PIPE_CHARS), 'x'.repeat(PIPE_SUB_CHARS));
// How much room an open end needs beyond the node: the gap, plus the widest
// marker that sits at the end of it, plus a little air.
const TERMINAL_ROOM = TERMINAL_GAP + 40;
// A pipe tag is a good deal wider than the cloud that room was measured for,
// and reserving its width around every node in a diagram that has no pipes in
// it would zoom every flat model out by a sixth for a mark it does not have.
const PIPE_ROOM = TERMINAL_GAP + PIPE_W_MAX + 8;
/** Smallest node that still gets a resize grip rather than just handles. */
const GRIP = 7;

const svg = (name, attrs = {}) => {
	const n = document.createElementNS(NS, name);
	for (const [k, v] of Object.entries(attrs)) {
		if (v != null) n.setAttribute(k, String(v));
	}
	return n;
};

export class GraphEditor {
	/**
	 * @param {HTMLElement} container the box the canvas fills
	 * @param {object} hooks
	 * @param {{wheelHost?: HTMLElement}} [opts] where the wheel is listened
	 *   for, when that is something wider than the canvas itself -- the tab
	 *   the canvas fills, so the frame around it is not dead. See `_onWheel`.
	 */
	constructor(container, hooks = {}, { wheelHost = null } = {}) {
		this.container = container;
		this.hooks = hooks;
		this.wheelHost = wheelHost ?? null;
		this.project = null;
		this.selection = null;
		// Everything selected, as qualified names. `selection` is the one of
		// them the inspector shows; this is what an edit acts on. A connection
		// is selected on its own, so this holds at most one of those.
		this.picked = new Set();
		// The blocks a Cut has marked to be moved. Nothing has happened to
		// them; a Paste moves them and any edit takes the mark off.
		this.pendingCut = null;
		// The shapes selected, by id. Apart from the block selection rather
		// than mixed into it: a shape is annotation, so nothing that acts on a
		// selection of blocks -- copy, paste, move into a sub-system, the
		// inspector -- has anything to say about one. Picking either kind
		// clears the other, so Del and the menus never have to guess.
		this.pickedShapes = new Set();
		// Names the block search matched, or null when nothing is being
		// searched for. Emphasis only -- it hides nothing.
		this.matches = null;
		// Pan and zoom. Named camera, not view: `view` is the diagram's
		// show/hide flags, which live on the project.
		this.camera = { x: 0, y: 0, k: 1 };
		this.drag = null;
		this.connect = null;

		this.root = svg('svg', { class: 'graph-svg' });
		this.root.setAttribute('tabindex', '0');
		this.defs = svg('defs');
		this.root.append(this.defs);
		this._defineMarkers();

		this.viewport = svg('g', { class: 'graph-viewport' });
		// The shapes drawn on the canvas, behind everything: a group box round
		// four compartments has to be behind the four compartments. Called
		// `decor` in the DOM because `gshape-` already means a *block's*
		// outline -- see _renderNode.
		this.decorLayer = svg('g', { class: 'graph-decor' });
		this.edgeLayer = svg('g', { class: 'graph-edges' });
		this.nodeLayer = svg('g', { class: 'graph-nodes' });
		this.overlay = svg('g', { class: 'graph-overlay' });
		this.viewport.append(
			this.decorLayer, this.edgeLayer, this.nodeLayer, this.overlay,
		);
		this.root.append(this.viewport);
		container.append(this.root);

		// A floating hint that follows the pointer while connecting.
		this.hint = document.createElement('div');
		this.hint.className = 'graph-hint';
		this.hint.hidden = true;
		container.append(this.hint);

		// What an empty diagram says. In the container rather than the
		// viewport, so it stays put and stays legible whatever the camera is
		// doing -- a note that zooms out with the model it is standing in for
		// is a note nobody can read.
		this.blank = document.createElement('div');
		this.blank.className = 'graph-blank';
		this.blank.hidden = true;
		container.append(this.blank);

		this._bind();
		// How many times the diagram has been drawn; see `_changed`.
		this._renders = 0;
		// A resize moves nothing in the diagram: every node and every line is
		// placed in the model's own coordinates, and only the viewport
		// transform and the grid behind it depend on the size of the box they
		// are drawn in. Re-rendering rebuilt every node and every edge, and
		// re-tokenised every equation in the model to find the influence
		// links -- sixty times a second while the splitter is being dragged.
		this._ro = new ResizeObserver(() => { if (this.project) this._applyView(); });
		this._ro.observe(container);
	}

	destroy() {
		this._ro.disconnect();
		if (this._onEscape) window.removeEventListener('keydown', this._onEscape, true);
	}

	/**
	 * The arrowhead for a line of a given colour, made once and reused.
	 *
	 * A marker cannot inherit its line's stroke without SVG 2's
	 * `context-stroke`, and that keyword survives to the *screen* everywhere
	 * this runs but not out of it: `diagramSvgText` inlines computed values,
	 * so an exported figure carried `fill:context-stroke` and a viewer without
	 * SVG 2 markers -- Illustrator, among others -- drew every arrowhead
	 * black. One marker per colour instead, which is a handful for any real
	 * model and needs nothing of the viewer.
	 */
	_arrowFor(color) {
		this._arrows ??= new Map();
		const had = this._arrows.get(color);
		if (had) return had;
		const id = `arrow-c${this._arrows.size}`;
		const m = svg('marker', {
			id, viewBox: '0 0 10 10', refX: 9, refY: 5,
			markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse',
		});
		const head = svg('path', { d: 'M 0 0 L 10 5 L 0 10 z' });
		head.style.setProperty('fill', color);
		m.append(head);
		this.defs.append(m);
		this._arrows.set(color, id);
		return id;
	}

	_defineMarkers() {
		for (const [id, cls] of [
			['arrow', 'mk-arrow'], ['arrow-sel', 'mk-arrow-sel'], ['arrow-dot', 'mk-arrow-dot'],
		]) {
			const m = svg('marker', {
				id, viewBox: '0 0 10 10', refX: 9, refY: 5,
				markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse',
			});
			m.append(svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', class: cls }));
			this.defs.append(m);
		}
	}

	// --- data ------------------------------------------------------------

	setProject(project) {
		// A menu is about one block, so a *different* model invalidates it.
		// Only a different one: this is called again on every edit with the
		// same object, and closing then would dismiss the menu the edit was
		// made from -- which is how a menu of toggles becomes one toggle.
		if (this.project && this.project !== project) {
			closeMenu();
			// The per-colour arrowheads belong to the model that asked for
			// them. A session that opens a dozen models would otherwise
			// accumulate a marker per colour of each.
			for (const el of this.defs.querySelectorAll('marker[id^="arrow-c"]')) el.remove();
			this._arrows = null;
		}
		this.project = project;
		ed.autoLayout(project);
		this._placeLooseNodes();
		this.render();
	}

	/**
	 * @param {{kind: string, name: string}|null} sel the block the inspector shows
	 * @param {string[]|null} [picked] everything selected, when there is more
	 *   than one. Passed back by the application after its own round trip, so
	 *   that echoing a selection does not quietly collapse it to one block.
	 */
	/**
	 * @param {{kind: string, name: string}|null} sel
	 * @param {string[]|null} [picked]
	 * @param {{reveal?: boolean}} [opts] `reveal` brings the block's own
	 *   sub-system up on the canvas. Set by a selection made *elsewhere* -- a
	 *   row in the tree, a search result, a reference followed in the
	 *   Information view -- which is otherwise real and invisible: the
	 *   inspector fills in and the canvas goes on showing somewhere the block
	 *   is not. Not set when the diagram is merely being told what it already
	 *   knows, after an edit: dragging a block into a sub-system would then
	 *   dive into that sub-system, taking the canvas away from the diagram
	 *   being arranged.
	 */
	setSelection(sel, picked = null, { reveal = false } = {}) {
		const was = this.selection?.name ?? null;
		// Before the selection is stored, not after: `setSystem` clears the
		// selection, on the reasoning that what was selected is no longer on
		// screen. Here it is exactly what will be.
		if (reveal && sel?.name) {
			// A sub-system is shown by opening the one that holds it, so the
			// container itself is on screen rather than its contents.
			if (sel.kind === 'system') this.setSystem(parentOf(sel.name));
			else if (ed.findBlock(this.project, sel.name)) this.setSystem(parentOf(sel.name));
		}
		this.selection = sel;
		const names = picked ?? (sel?.name ? [sel.name] : []);
		this.picked = new Set(names.filter((n) => this._selectable(n)));
		this._applySelection();
	}

	/**
	 * A block has just been made and is nowhere to be seen.
	 *
	 * Parameters and lookup tables are not drawn unless asked for -- they are
	 * the model's inputs rather than its flow, and on a model of any size
	 * drawing them buries it. So a kind switched off in `Show` is added to a
	 * canvas that does not change, which reads as a click that did not take;
	 * this says where it went and where the switch is. It does not throw the
	 * switch itself: `show_parameters` is saved with the project, and turning
	 * on several hundred nodes because somebody added one is not a decision to
	 * make for them.
	 *
	 * **Only on adding, and only with the diagram in view.** It used to be said
	 * on every selection, from wherever the selection came from -- so clicking
	 * a parameter in the tree while reading the chart explained the diagram
	 * nobody was looking at. What is selected is answered by the Information
	 * view, which is on screen; this answers "where did the thing I just made
	 * go", which is only a question while the canvas is the thing in front of
	 * you. Public, because the left panel's own add buttons have to ask it too.
	 */
	sayIfNotDrawn(name) {
		const found = ed.findBlock(this.project, name);
		// A connection is an edge, and an edge is drawn whenever its ends are.
		if (!found || !ed.NODE_KINDS.includes(found.kind)) return;
		if (this._nodes().some((n) => n.name === name)) return;
		const plural = (ed.KIND_LABEL[found.kind] ?? found.kind).toLowerCase();
		this.hooks.onStatus?.(
			`${found.block.name} is here, but ${plural} are not drawn on the diagram. `
			+ 'Right-click the canvas for Show.', 'info',
		);
	}

	/**
	 * Sets a diagram view toggle: show_expressions, show_parameters or
	 * show_influences. Stored on the project, so it survives a save.
	 */
	setViewOption(patch) {
		ed.setView(this.project, patch);
		// Nodes may have appeared: give any newcomer a position.
		this._placeLooseNodes();
		this.render();
		this.hooks.onChange?.({ layoutOnly: true });
	}

	setShowInfluences(on) {
		this.setViewOption({ show_influences: on });
	}

	/**
	 * Gives a position to any node that has none.
	 *
	 * A block added from the block list, or one a diagram toggle has just
	 * revealed, arrives without geometry. `placeLoose` puts it under the middle
	 * of whatever reads it, below what is already drawn -- so a new parameter
	 * lands beneath the transfer that uses it rather than in a row of its own
	 * at the bottom of the model.
	 */
	_placeLooseNodes() {
		ed.placeLoose(this.project);
	}

	/** The current diagram view settings. */
	get view() { return ed.view(this.project); }

	/**
	 * Nodes currently drawn. Compartments are always shown; expressions and
	 * parameters are toggles, since a large model has far more of them than
	 * compartments and they clutter the flow.
	 */
	/**
	 * The nodes of the sub-system being shown: its own blocks, plus one node
	 * per sub-system inside it. A real model has hundreds of blocks in a dozen
	 * sub-systems, and drawing them all at once is a wall of boxes; this is the
	 * drill-down the desktop application has.
	 */
	_nodes() {
		const p = this.project;
		const v = this.view;
		const here = this.system ?? '';
		const out = [];

		const push = (block, kind) => {
			if (systemOf(block) !== here) return;
			const name = qualifiedName(block);
			const pos = p.layout?.[name] ?? { x: 0, y: 0 };
			const size = ed.blockSize(p, name, kind);
			out.push({
				kind,
				name,
				label: block.name,
				block,
				x: pos.x ?? 0,
				y: pos.y ?? 0,
				w: size.w,
				h: size.h,
				shape: block.shape ?? ed.defaultShapeFor(kind),
			});
		};

		for (const c of p.compartments ?? []) push(c, 'compartment');
		// A path is always drawn: it holds inventory and takes connections, so
		// hiding it would hide part of the flow rather than part of the
		// annotation.
		for (const f of p.farfields ?? []) push(f, 'farfield');
		// So is a set of waste packages: it holds the inventory the model
		// starts from, and its release is a line drawn out of it.
		for (const w of p.waste_packages ?? []) push(w, 'waste_package');
		// And a disruptive event: it moves mass, so it is part of the flow.
		for (const d of p.events ?? []) push(d, 'event');
		if (v.show_expressions) for (const e of p.expressions ?? []) push(e, 'expression');
		if (v.show_parameters) for (const q of p.parameters ?? []) push(q, 'parameter');
		if (v.show_lookups) for (const l of p.lookups ?? []) push(l, 'lookup');
		if (v.show_recorders) {
			for (const b of p.min_maxes ?? []) push(b, 'min_max');
			for (const b of p.running_means ?? []) push(b, 'running_mean');
			for (const b of p.snapshots ?? []) push(b, 'snapshot');
			for (const b of p.delays ?? []) push(b, 'delay');
			for (const b of p.triggers ?? []) push(b, 'trigger');
		}
		if (v.show_reductions) {
			for (const o of p.index_reductions ?? []) push(o, 'index_reduction');
			for (const g of p.block_reductions ?? []) push(g, 'block_reduction');
		}
		// A function is drawn where it lives. It carries no inventory and
		// takes no connection -- what joins it to the rest of the model is the
		// influence arrows: in from what its body reads, out to every equation
		// that calls it.
		if (v.show_functions) for (const f of p.functions ?? []) push(f, 'function');

		for (const child of ed.childSystems(p, here)) {
			const pos = p.layout?.[child] ?? { x: 0, y: 0 };
			const size = ed.blockSize(p, child, 'system');
			out.push({
				kind: 'system',
				name: child,
				label: baseName(child),
				block: { name: baseName(child), system: here },
				count: ed.blocksIn(p, child, { deep: true }).length,
				// A transport runs as a chain of compartments; the node says so.
				transport: ed.isTransport(p, child),
				x: pos.x ?? 0,
				y: pos.y ?? 0,
				w: size.w,
				h: size.h,
				shape: 'rounded',
			});
		}
		return out;
	}

	/**
	 * Which visible node an endpoint belongs to: the block itself when it is in
	 * this sub-system, the sub-system node when it is inside one of them, and
	 * null when it is somewhere else in the model entirely.
	 */
	_visibleEnd(name) {
		if (name == null) return null;
		const here = this.system ?? '';
		const system = parentOf(name);
		if (system === here) return name;
		if (!isWithin(system, here)) return null;
		// Inside a child: the first path component below this sub-system.
		const rest = here ? system.slice(here.length + 1) : system;
		const child = rest.split('.')[0];
		return here ? `${here}.${child}` : child;
	}

	_nodeMap() { return new Map(this._nodes().map((n) => [n.name, n])); }

	// --- rendering ---------------------------------------------------------

	render() {
		if (!this.project) return;
		// Counted so `_changed` can tell whether the host re-rendered.
		this._renders++;
		// Which block reads which is a fact about the model, and working it
		// out means tokenising every equation in it -- 6.8 ms on the largest
		// model in the corpus. `_redrawEdges` needs it on every pointer move
		// of a node drag, where the model has not changed at all; it is
		// re-derived here instead, which is to say once per edit.
		this._influenceCache = null;
		// Which connections a disabled compartment takes with it, once per
		// render rather than once per line.
		this._impliedOff = ed.implicitlyDisabled(this.project);
		// Whether the keyboard was on this diagram. Every node is thrown away
		// and rebuilt below, so the focused one stops existing and focus falls
		// to the document -- and the key listener is on this root, which means
		// ⌘C, ⌘X, ⌘V and Del quietly stopped working after any edit until
		// the canvas was clicked again. Cloning twice in a row is the obvious
		// way to meet it.
		const had = this.root.contains(document.activeElement);
		this._openSlots = new Map();
		// Where each connection was actually drawn. The open-end slot counter
		// advances on every call, so asking _geometry twice for the same
		// connection gives two different answers: everything that needs a
		// connection's geometry after it is drawn reads it from here.
		this._geo = new Map();
		const nodes = this._nodeMap();
		this._bundles = this._bundleConnections(nodes);
		this.decorLayer.replaceChildren();
		this.edgeLayer.replaceChildren();
		this.nodeLayer.replaceChildren();
		this.overlay.replaceChildren();
		this._applyView();

		this._renderDecor();
		this._renderEdges(nodes);
		for (const n of nodes.values()) this.nodeLayer.append(this._renderNode(n));
		this._applySelection();
		this._applyDecorSelection();
		this._applySearch();
		// A re-render throws the badges away with everything else, so they go
		// back on here rather than only when the problem list changes.
		this._applyProblems();
		// The same for a pending cut, which outlives a redraw -- going into a
		// sub-system to paste there *is* a redraw, and is the one navigation
		// the mark exists to allow.
		this._applyPendingCut();
		this._renderBlank(nodes.size);
		// Back to the diagram itself rather than to the node that had it: what
		// is selected after an edit is often something else, and the root is
		// where the keys are listened for.
		if (had && !this.root.contains(document.activeElement)) {
			this.root.focus({ preventScroll: true });
		}
	}

	/**
	 * The note on an empty diagram, and a way out of it.
	 *
	 * An empty canvas gives no clue that right-clicking it is how a model gets
	 * started -- and the line under the diagram that used to say so is off by
	 * default. So the emptiness says it itself, and only while it lasts: one
	 * block on the canvas and the note is gone.
	 *
	 * Three different things look identical from here, and saying the wrong
	 * one is worse than saying nothing: a model with nothing in it, a
	 * sub-system with nothing in it, and a view whose blocks are all switched
	 * off under Show. Only the first of them is an invitation to add a block.
	 */
	_renderBlank(count) {
		if (count) { this.blank.hidden = true; return; }
		const here = this.system ?? '';
		const all = ed.allBlocks(this.project);
		const mine = all.filter((b) => systemOf(b) === here);

		let title;
		let detail;
		if (!all.length) {
			title = 'This model has no blocks yet.';
			detail = 'Right-click the background to add one — a compartment to '
				+ 'hold an inventory, an expression to work something out, a '
				+ 'parameter for a constant. Drag the handle on a '
				+ 'compartment’s right edge onto another to connect them.';
		} else if (mine.length) {
			// Blocks here, none of them drawn: every kind they belong to is
			// switched off. Adding another would go the same way.
			title = `Nothing shown${here ? ` in ${here}` : ''}.`;
			detail = `${mine.length} block${mine.length === 1 ? '' : 's'} here, `
				+ 'all of a kind the diagram is not showing. Right-click the '
				+ 'background and look under Show.';
		} else {
			title = here ? `Nothing in ${here} yet.` : 'Nothing at the top level yet.';
			detail = here
				? 'Right-click the background to add a block to this sub-system, '
					+ 'or go up to where the rest of the model is.'
				: 'The model’s blocks are all inside sub-systems. Right-click '
					+ 'the background to add one here.';
		}

		this.blank.replaceChildren();
		this.blank.append(Object.assign(document.createElement('b'), {
			textContent: title,
		}));
		this.blank.append(Object.assign(document.createElement('span'), {
			textContent: detail,
		}));
		if (!mine.length) {
			const add = document.createElement('button');
			add.type = 'button';
			add.className = 'primary';
			add.textContent = 'Add a compartment';
			add.addEventListener('click', () => {
				// The middle of what is on screen, in the model's own
				// coordinates, so the first block lands where the eye already
				// is rather than at an origin that may be off-screen.
				const r = this.root.getBoundingClientRect();
				this._addNodeAt('compartment', {
					x: (r.width / 2 - this.camera.x) / this.camera.k,
					y: (r.height / 2 - this.camera.y) / this.camera.k,
				});
			});
			this.blank.append(add);
		}
		this.blank.hidden = false;
	}

	/** Every shape on this canvas, in the order they are drawn. */
	_renderDecor() {
		this._shapes = ed.shapesIn(this.project, this.system ?? '')
			.map((sh) => ed.readShape(sh));
		for (const sh of this._shapes) this.decorLayer.append(this._renderShape(sh));
		// A note's text is wrapped to its page, and wrapping needs to know how
		// wide the words come out -- which is only true once the element is in
		// the document and wearing its face. So it is laid out here rather
		// than built above.
		for (const sh of this._shapes) {
			if (figureText(sh.figure) !== 'note') continue;
			const t = this.decorLayer.querySelector(`[data-note="${sh.id}"]`);
			if (t) this._layoutNoteText(t, sh);
		}
	}

	/**
	 * Wraps a note's text across its page.
	 *
	 * SVG has no wrapping: a `<text>` is one line however long it is. So the
	 * words are measured against the page's inner width and broken into one
	 * `<tspan>` per line -- measured on this very element, so the answer is in
	 * the face and size it is actually drawn in rather than in an estimate of
	 * them. Lines the writer typed are kept: a note is written in lines.
	 *
	 * The block is centred down the page, which reads right whether the note
	 * holds two words or twenty. Overflowing it is allowed and deliberate --
	 * the note can be dragged larger, and silently cutting somebody's words
	 * off would be worse than showing them past the edge.
	 */
	_layoutNoteText(t, sh) {
		const pad = Math.max(10, Math.min(sh.w, sh.h) * 0.09);
		const room = Math.max(12, sh.w - pad * 2);
		const measure = (text) => { t.textContent = text; return t.getComputedTextLength(); };
		const lines = [];
		for (const written of String(sh.text ?? '').split('\n')) {
			const words = written.split(/\s+/).filter(Boolean);
			if (!words.length) { lines.push(''); continue; }
			let line = words[0];
			for (const word of words.slice(1)) {
				const wider = `${line} ${word}`;
				if (measure(wider) <= room) line = wider;
				else { lines.push(line); line = word; }
			}
			lines.push(line);
		}
		t.textContent = '';
		const step = sh.text_size * 1.25;
		const x = { left: pad, center: sh.w / 2, right: sh.w - pad }[sh.text_align] ?? sh.w / 2;
		// The first line's baseline, so that the block of them sits centred.
		const top = sh.h / 2 - ((lines.length - 1) * step) / 2 + sh.text_size * 0.34;
		for (const [i, line] of lines.entries()) {
			const span = svg('tspan', {
				x: String(Math.round(x * 100) / 100),
				y: String(Math.round((top + i * step) * 100) / 100),
			});
			span.textContent = line;
			t.append(span);
		}
	}

	/**
	 * One shape.
	 *
	 * Three groups, and each has a reason. The art is what you see. The hit
	 * layer is the same outlines with a fat transparent stroke, because a
	 * shape with no fill has no interior to click and a two-pixel line is not
	 * a target -- the same trick the connections use. And the text sits
	 * outside the flip, or a flipped arrow would carry mirrored writing.
	 */
	_renderShape(sh) {
		const g = svg('g', {
			class: 'gdecor',
			'data-decor': sh.id,
			// The line style as an attribute rather than a property, so the
			// dash pattern can be written once in the stylesheet in terms of
			// the line's own width -- a two-pixel dash and a five-pixel one
			// want different gaps.
			'data-dash': sh.dash,
			transform: `translate(${sh.x} ${sh.y})`,
		});
		// Colours as custom properties on the shape itself, so the stylesheet
		// decides what each token *is* -- once per theme -- and the export
		// picks up whatever it resolved to. A fill of `none` has to stay
		// `none` rather than become transparent: transparent is painted, and a
		// painted interior would swallow every click inside a group box.
		g.style.setProperty('--decor-line',
			sh.line === 'none' ? 'none' : `var(--shape-${sh.line})`);
		g.style.setProperty('--decor-width', String(sh.line_width));
		// No fill is a class rather than a value, and that is not a style
		// choice: the fill is mixed down from the token with `color-mix`, and
		// `color-mix(in oklab, none 22%, transparent)` is not a colour -- the
		// declaration would be thrown out and `fill` would fall back to its
		// initial value, which is black. A shape asked to be see-through would
		// come out solid.
		if (sh.fill === 'none') g.classList.add('is-unfilled');
		else g.style.setProperty('--decor-fill', `var(--shape-${sh.fill})`);

		const body = svg('g', { class: 'gdecor-flip' });
		if (sh.flip_x || sh.flip_y) {
			body.setAttribute('transform',
				`translate(${sh.flip_x ? sh.w : 0} ${sh.flip_y ? sh.h : 0}) `
				+ `scale(${sh.flip_x ? -1 : 1} ${sh.flip_y ? -1 : 1})`);
		}
		const parts = figureParts(sh.figure, sh.w, sh.h);
		const filled = sh.fill !== 'none';
		// No fill *and* no line is a shape that paints nothing. It is still
		// there, still catches the pointer along its outline, and still exports
		// as the nothing it is -- but on screen there was no way to find it
		// again: you would have to click within a few pixels of an edge you
		// cannot see, having forgotten where you drew it. So the editor draws a
		// ghost of it, and only the editor: `gdecor-ghost` is in picture.js's
		// list of chrome, so a saved picture has the shape the model has.
		const invisible = !filled && sh.line === 'none';
		const hit = svg('g', { class: 'gdecor-hit' });
		const art = svg('g', { class: 'gdecor-art' });
		const ghost = invisible ? svg('g', { class: 'gdecor-ghost' }) : null;
		for (const part of parts) {
			const role = ROLES[part.role] ?? ROLES.body;
			art.append(this._shapePart(part, {
				class: `gdecor-part gdecor-${part.role}`,
			}));
			// Only the areas that are painted can be hit inside; the rest is
			// caught by the fat stroke along their outlines.
			hit.append(this._shapePart(part, {
				class: 'gdecor-hit-part',
				fill: filled && role.fill !== 'none' ? 'transparent' : 'none',
			}));
			ghost?.append(this._shapePart(part, { class: 'gdecor-ghost-part' }));
		}
		body.append(hit, ...(ghost ? [ghost] : []), art);
		g.append(body);

		if (sh.text) g.append(this._shapeText(sh));
		return g;
	}

	/** A path or an ellipse, whichever the figure asked for. */
	_shapePart(part, attrs) {
		if (part.ellipse) {
			const [cx, cy, rx, ry] = part.ellipse;
			return svg('ellipse', { cx, cy, rx: Math.abs(rx), ry: Math.abs(ry), ...attrs });
		}
		return svg('path', { d: part.d, ...attrs });
	}

	/**
	 * A shape's own label.
	 *
	 * Where it goes is the figure's business: inside the boxes, along the top
	 * bar of a group box -- which is what that bar is for -- and underneath a
	 * picture, which is where a caption reads from.
	 */
	_shapeText(sh) {
		const where = figureText(sh.figure);
		const classes = ['gdecor-text', `gdecor-text-${where}`];
		// `sans` is the diagram's own face and needs no class; the other three
		// are named in app.css, where the stacks live.
		if (sh.text_font && sh.text_font !== 'sans') classes.push(`is-${sh.text_font}`);
		if (sh.text_bold) classes.push('is-bold');
		if (sh.text_italic) classes.push('is-italic');
		const t = svg('text', { class: classes.join(' ') });
		t.style.setProperty('--decor-text-size', `${sh.text_size}px`);
		if (where === 'note') {
			// Wrapped once it is in the document -- see `_layoutNoteText`.
			t.dataset.note = sh.id;
			t.setAttribute('text-anchor',
				{ left: 'start', right: 'end' }[sh.text_align] ?? 'middle');
			t.textContent = sh.text;
			return t;
		}
		if (where === 'top') {
			t.setAttribute('x', String(10));
			t.setAttribute('y', String(Math.min(30, Math.max(14, sh.h * 0.2)) / 2));
			t.setAttribute('text-anchor', 'start');
		} else if (where === 'below') {
			t.setAttribute('x', String(sh.w / 2));
			t.setAttribute('y', String(sh.h + sh.text_size * 0.9));
			t.setAttribute('text-anchor', 'middle');
		} else {
			t.setAttribute('x', String(sh.w / 2));
			t.setAttribute('y', String(sh.h / 2));
			t.setAttribute('text-anchor', 'middle');
		}
		t.textContent = sh.text;
		return t;
	}

	/** Marks the selected shapes, and puts the grips on a single one. */
	_applyDecorSelection() {
		for (const el of this.decorLayer.children) {
			el.classList.toggle('is-selected', this.pickedShapes.has(el.dataset.decor));
		}
		this._renderShapeHandles();
	}

	_renderShapeHandles() {
		for (const old of this.overlay.querySelectorAll('[data-decorbox]')) old.remove();
		// One at a time, as for a block: grips on one of several would offer
		// to resize whichever was clicked last.
		if (this.pickedShapes.size !== 1) return;
		const id = [...this.pickedShapes][0];
		const sh = (this._shapes ?? []).find((x) => x.id === id);
		if (!sh) return;
		this.overlay.append(this._renderShapeGrips(sh));
	}

	/**
	 * The ring and the grips round one shape.
	 *
	 * Eight for an area, two for a line: a line is drawn from one corner of
	 * its box to the other, so its ends *are* those corners and the six other
	 * grips would sit on nothing.
	 */
	_renderShapeGrips(sh) {
		const g = svg('g', { class: 'gdecor-handles', 'data-decorbox': sh.id });
		const x0 = Math.min(sh.x, sh.x + sh.w);
		const y0 = Math.min(sh.y, sh.y + sh.h);
		const w = Math.abs(sh.w);
		const h = Math.abs(sh.h);
		const diagonal = isDiagonal(sh.figure);
		if (!diagonal) {
			g.append(svg('rect', {
				class: 'gdecor-ring',
				x: x0 - 3, y: y0 - 3, width: w + 6, height: h + 6,
			}));
		} else {
			g.append(svg('line', {
				class: 'gdecor-ring gdecor-ring-line',
				x1: sh.x, y1: sh.y, x2: sh.x + sh.w, y2: sh.y + sh.h,
			}));
		}
		const corners = diagonal
			? [['nw', sh.x, sh.y], ['se', sh.x + sh.w, sh.y + sh.h]]
			: [
				['nw', x0, y0], ['n', x0 + w / 2, y0], ['ne', x0 + w, y0],
				['e', x0 + w, y0 + h / 2], ['se', x0 + w, y0 + h],
				['s', x0 + w / 2, y0 + h], ['sw', x0, y0 + h],
				['w', x0, y0 + h / 2],
			];
		for (const [corner, cx, cy] of corners) {
			const handle = svg('g', {
				class: `ggrip gdecor-grip ggrip-${corner}`,
				'data-decorgrip': corner,
				'data-decorid': sh.id,
			});
			handle.append(svg('rect', {
				class: 'ggrip-hit', x: cx - 9, y: cy - 9, width: 18, height: 18,
			}));
			handle.append(svg('rect', {
				class: 'ggrip-dot',
				x: cx - GRIP / 2, y: cy - GRIP / 2, width: GRIP, height: GRIP, rx: 2,
			}));
			const title = svg('title');
			title.textContent = diagonal ? 'Drag to move this end' : 'Drag to resize';
			handle.append(title);
			g.append(handle);
		}
		return g;
	}

	_renderEdges(nodes) {
		// A connection is drawn where both of its ends are visible from here:
		// as themselves, as the sub-system node containing them, or -- when an
		// end is elsewhere in the model -- as an open end that says so.
		const here = this.system ?? '';
		const place = (conn, kind) => {
			// One end outside the model -- a source term coming in, an outflow
			// going out. The other end is the only thing such a connection
			// says, so it belongs on that block's own canvas and nowhere else.
			// Drawn on the ancestors as well, it was the same arrow a second
			// time against the sub-system node standing for the block: every
			// model with a source term deep in it grew a disc at the top level
			// pointing at a sub-system, saying nothing the canvas holding the
			// block does not say better.
			if (kind === 'inflow' || conn.from == null || conn.to == null) {
				const real = (kind === 'inflow' ? null : conn.from) ?? conn.to;
				// Both ends outside is not a connection the editor will make,
				// and a file that has one should still show it -- once, at the
				// top, rather than on every canvas.
				if (real == null) { if (here) return null; }
				else if (parentOf(real) !== here) return null;
			}
			const from = kind === 'inflow' ? null : this._visibleEnd(conn.from);
			const to = this._visibleEnd(conn.to);
			const fromOff = kind !== 'inflow' && conn.from != null && from == null;
			const toOff = conn.to != null && to == null;
			if (fromOff && toOff) return null;
			// A connection wholly inside a child sub-system is that child's
			// business, not this view's.
			if (from != null && from === to) return null;
			return {
				...conn,
				from: kind === 'inflow' ? null : from,
				to,
				_elsewhere: (fromOff ? 'from' : null) ?? (toOff ? 'to' : null),
				_awayFrom: fromOff ? conn.from : (toOff ? conn.to : null),
			};
		};

		// Which of them end in a pipe here, for the edits that move a bend or
		// a pipe to know whose point they are moving: see `_wayView`.
		this._pipesHere = new Set();
		for (const t of this.project.transfers ?? []) {
			const shown = place(t, 'transfer');
			if (shown?._elsewhere) this._pipesHere.add(qualifiedName(t));
			if (shown) this.edgeLayer.append(...this._renderConnection(shown, nodes, 'transfer'));
		}
		for (const s of this.project.inflows ?? []) {
			const shown = place({ ...s, from: null }, 'inflow');
			if (shown?._elsewhere) this._pipesHere.add(qualifiedName(s));
			if (shown) this.edgeLayer.append(...this._renderConnection(shown, nodes, 'inflow'));
		}
		if (this.view.show_influences) {
			for (const g of this._influences(nodes)) this.edgeLayer.append(g);
		}
	}

	/**
	 * Which of a connection's points this canvas moves: its own pipe's, when
	 * it is drawn here as a pipe into another sub-system, or the bend of the
	 * whole drawing. See `waypointKey` in ../domain/edit.js.
	 */
	_wayView(name) {
		return this._pipesHere?.has(name) ? (this.system ?? '') : null;
	}

	_applyView() {
		const { x, y, k } = this.camera;
		this.viewport.setAttribute('transform', `translate(${x} ${y}) scale(${k})`);
		this._applyGrid();
	}

	/**
	 * A coordinate as the grid wants it.
	 *
	 * `Snap to grid` decides, and holding Alt during the drag does the
	 * opposite of whatever it says -- read off the move event rather than the
	 * press, so it can be taken and released in the middle of a gesture, which
	 * is what the modifier is for: one block placed between the lines without
	 * changing the setting for everything after it.
	 *
	 * Not snapping still rounds to whole units. Model coordinates are written
	 * to the project file, and sub-pixel positions in a file are noise nobody
	 * asked for.
	 */
	_snap(v, ev = null) {
		const on = !!ed.view(this.project).snap_to_grid !== (ev?.altKey === true);
		return on ? Math.round(v / GRID) * GRID : Math.round(v);
	}

	/**
	 * The lattice behind the diagram: the one a drag snaps to, at the zoom it
	 * is being looked at.
	 *
	 * A CSS background rather than drawn geometry -- it is behind everything,
	 * never hit-tested, and repeating a gradient is what a browser is fastest
	 * at. It follows the camera, which it did not before: the grid was a fixed
	 * 20px screen lattice while a drag snapped to 10 model units, so the lines
	 * a block appeared to land on were not the ones it landed on.
	 *
	 * Stepped up when the pitch would be too fine to read: at a quarter zoom
	 * 10 units is 2.5 pixels, which is moire rather than a grid. Doubling
	 * keeps every drawn line a line the drag can land on.
	 */
	_applyGrid() {
		const on = !!ed.view(this.project).show_grid;
		this.root.classList.toggle('has-grid', on);
		if (!on) return;
		let step = GRID * this.camera.k;
		while (step > 0 && step < 9) step *= 2;
		this.root.style.setProperty('--grid-step', `${step}px`);
		this.root.style.setProperty('--grid-x', `${this.camera.x}px`);
		this.root.style.setProperty('--grid-y', `${this.camera.y}px`);
	}


	/**
	 * Which blocks the search above the block list matched, or null for "not
	 * searching". Marked with a class rather than re-rendering, the same way
	 * selection is: nothing about the diagram changes, only its emphasis.
	 */
	setSearch(names) {
		this.matches = names ?? null;
		this._applySearch();
	}

	/**
	 * Which blocks the model cannot run because of, and why.
	 *
	 * A Map from block name to the message, so the badge can say what is
	 * wrong when it is hovered. Applied the way search and selection are --
	 * classes on what is already drawn, never a re-render -- because this
	 * changes on every keystroke and the diagram of a real model is expensive
	 * to rebuild.
	 *
	 * The mark itself is the halo that selection uses: a wide stroke behind
	 * the body, so only its outer half shows and the block's own outline --
	 * solid for a compartment, dashed for everything algebraic -- survives
	 * intact. In red rather than the accent, plus a badge, because a red halo
	 * alone would be ambiguous on a block whose own colour is red.
	 */
	setProblems(byName) {
		this.problems = byName ?? null;
		this._applyProblems();
	}

	_applyProblems() {
		const bad = this.problems;
		// A mark is `{ level, message }`; a bare string is an error, which is
		// what the map held before warnings joined it.
		const markOf = (name) => {
			const m = bad?.get(name) ?? null;
			if (!m) return null;
			return typeof m === 'string' ? { level: 'error', message: m } : m;
		};
		const sized = new Map(this._nodes().map((n) => [n.name, n]));
		// Putting the warning list away turns the amber *halo* off with it and
		// leaves the badge. The two marks are not the same size of statement:
		// a halo is a ring around the whole block, drawn in the colour
		// selection uses, and on a model where a third of the blocks carry a
		// unit warning it is most of the diagram. The badge is one small
		// circle in a corner with the reason on it, which is what somebody who
		// has read the warnings and decided about them still wants -- a way to
		// find one again, not a way to be told about it.
		//
		// A problem is not affected: a model that will not run says so however
		// loudly it has to.
		const quiet = ed.view(this.project).show_warning_list === false;
		for (const el of this.nodeLayer.children) {
			// A sub-system node carries the mark of what is inside it -- see
			// `edit.propagateMarks` -- so a fault three levels down is a badge
			// on the box you can open to go and find it.
			const mark = markOf(el.dataset.name);
			el.classList.toggle('has-problem', mark?.level === 'error');
			el.classList.toggle('has-warning', mark?.level === 'warning' && !quiet);
			const badge = el.querySelector('.gnode-problem');
			if (!mark) { badge?.remove(); continue; }
			const n = sized.get(el.dataset.name);
			if (!n) continue;
			// Rebuilt rather than patched: it is one small group, and the
			// message it carries changes as the equation is typed.
			badge?.remove();
			el.append(this._problemBadge(n, mark.message, mark.level));
		}
		for (const el of this.edgeLayer.querySelectorAll('[data-edge]')) {
			const mark = markOf(el.dataset.edge);
			const message = mark?.message ?? null;
			el.classList.toggle('has-problem', mark?.level === 'error');
			el.classList.toggle('has-warning', mark?.level === 'warning');
			if (message) {
				let title = el.querySelector('title.gedge-problem');
				if (!title) {
					title = svg('title', { class: 'gedge-problem' });
					el.append(title);
				}
				title.textContent = message;
			} else {
				el.querySelector('title.gedge-problem')?.remove();
			}
		}
	}

	/** The `!` in the corner, with the reason on it. */
	_problemBadge(n, message, level = 'error') {
		const g = svg('g', {
			class: `gnode-problem${level === 'warning' ? ' is-warning' : ''}`,
			transform: `translate(${n.w - 4} 4)`,
		});
		g.append(svg('circle', { class: 'gnode-problem-dot', r: 7.5 }));
		const mark = svg('text', { class: 'gnode-problem-mark', x: 0, y: 3.6 });
		mark.textContent = '!';
		g.append(mark);
		const title = svg('title');
		title.textContent = message;
		g.append(title);
		return g;
	}

	_applySearch() {
		const names = this.matches;
		this.root.classList.toggle('is-searching', !!names);
		for (const el of this.nodeLayer.children) {
			el.classList.toggle('is-match', !!names && names.has(el.dataset.name));
		}
		for (const el of this.edgeLayer.querySelectorAll('[data-edge]')) {
			el.classList.toggle('is-match', !!names && names.has(el.dataset.edge));
		}
	}

	/** Selection is a class toggle, never a re-render -- see the header note. */
	_applySelection() {
		const name = this.selection?.name ?? null;
		const nodes = [...this.nodeLayer.children];
		// The one node Tab reaches: the primary selection, else the first.
		const stop = nodes.find((el) => el.dataset.name === name) ?? nodes[0] ?? null;
		for (const el of nodes) {
			el.classList.toggle('is-selected', this.picked.has(el.dataset.name)
				|| (this.selection?.kind === 'system' && el.dataset.name === name));
			// Which of several is the one the inspector and the Information
			// view are describing. The rail and the tree both say so already;
			// on the diagram every member used to look identical, so the
			// answer to "which one am I editing" was somewhere else.
			el.classList.toggle('is-primary', el.dataset.name === name);
			el.setAttribute('tabindex', el === stop ? '0' : '-1');
		}
		for (const el of this.edgeLayer.querySelectorAll('[data-edge]')) {
			el.classList.toggle('is-selected', el.dataset.edge === name);
		}
		// Everything the selected block is joined to: what flows in and out of
		// it, and what reads it or is read by it. On a diagram of any size that
		// is the question you have when you click a block.
		for (const el of this.edgeLayer.querySelectorAll('[data-edge],[data-influence]')) {
			el.classList.toggle('is-linked', !!name && this._touches(el, name));
		}
		this._renderEdgeHandle();
		this._renderNodeHandles();
	}

	/** Whether an edge element has the named block at either end. */
	_touches(el, name) {
		const influence = el.dataset.influence;
		if (influence) {
			const [from, to] = influence.split('->');
			return from === name || to === name;
		}
		// A connection carries its own name too: the line for the selected
		// transfer is already marked as selected, not merely linked.
		if (el.dataset.edge === name) return false;
		return el.dataset.from === name || el.dataset.to === name;
	}

	/**
	 * Saves what is on the canvas as a picture.
	 *
	 * The whole diagram of the sub-system being shown, not the part in view:
	 * see picture.js for what travels with it and what is left behind.
	 *
	 * @param {'svg'|'png'|'jpeg'} kind
	 */
	async savePicture(kind) {
		const spec = PICTURE_KINDS[kind];
		if (!spec) return;
		// The shapes count: a group box drawn *round* the blocks reaches past
		// them, and a box taken from the blocks alone cropped its edges off --
		// so a diagram whose annotation was the point of the picture came out
		// with the annotation cut away.
		const box = unionBox([
			this.decorLayer.getBBox(), this.edgeLayer.getBBox(), this.nodeLayer.getBBox(),
		]);
		if (!box) {
			this.hooks.onStatus?.(
				'There is nothing on this diagram to make a picture of.', 'warn',
			);
			return;
		}
		// The ground the canvas is drawn on, so a picture of a dark diagram is
		// not black shapes on nothing.
		const background = getComputedStyle(this.root).backgroundColor;
		const opaque = background && background !== 'rgba(0, 0, 0, 0)'
			? background
			: getComputedStyle(this.container).backgroundColor;
		const name = ed.modelName(this.project);
		const where = this.system ?? '';
		const { text, width, height } = diagramSvgText({
			root: this.root,
			viewport: this.viewport,
			drop: [this.overlay],
			box,
			background: opaque,
			title: [name, where].filter(Boolean).join(' — '),
		});
		const file = fileName([name, where], spec.extension);
		try {
			if (kind === 'svg') {
				saveBlob(file, new Blob([text], { type: spec.mime }));
			} else {
				saveBlob(file, await rasterise(text, {
					width, height, mime: spec.mime, background: opaque,
				}));
			}
			this.hooks.onStatus?.(
				`Saved ${file} — the whole ${where ? `${baseName(where)} ` : ''}diagram, `
				+ `${Math.round(width)}×${Math.round(height)}`
				+ (kind === 'svg' ? '.' : ' at 2× for print.'),
				'info',
			);
		} catch (e) {
			this.hooks.onStatus?.(`The picture could not be saved: ${e.message}`, 'warn');
		}
	}

	/** Resize grips for the selected node, if the selection is one. */
	_renderNodeHandles() {
		for (const old of this.overlay.querySelectorAll('[data-resize]')) old.remove();
		// Grips on one of several selected blocks would offer to resize the
		// one you happened to click last, which is not what the selection is
		// about any more.
		if (!this.selection || this.picked.size > 1) return;
		const n = this._nodes().find((x) => x.name === this.selection.name);
		if (!n) return;
		this.overlay.append(this._renderResizeHandles(n));
	}

	_renderNode(n) {
		const g = svg('g', {
			class: `gnode gnode-${n.kind} gshape-${n.shape}`
				// Off by its own switch, or with the sub-system around it; a
				// sub-system node fades when it is the thing switched off.
				+ `${n.kind !== 'system' && !ed.isEffectivelyEnabled(this.project, n.block) ? ' is-disabled' : ''}`
				+ `${n.kind === 'system' && !ed.isSystemEnabled(this.project, n.name) ? ' is-disabled' : ''}`
				+ `${n.kind === 'system' && n.transport ? ' is-transport' : ''}`
				+ `${n.kind !== 'system' && ed.transportOf(this.project, n.block) ? ' is-transport-part' : ''}`,
			transform: `translate(${n.x} ${n.y})`,
			'data-name': n.name,
			// One tab stop for the whole diagram, not one per node: Tab lands
			// on the selected block, or the first when nothing is selected,
			// which `_applySelection` keeps up to date; Enter opens it and the
			// arrow keys nudge it. A model of four hundred blocks was four
			// hundred stops between the toolbar and the panel beside it.
			tabindex: '-1',
			role: 'button',
			'aria-label': `${n.kind} ${n.name}`,
		});

		// The selection ring: two strokes of the block's own outline, drawn
		// *behind* the body so that only their outer halves show. The body's
		// fill is opaque, so a wide faint stroke becomes a soft aura and a
		// narrow solid one becomes a crisp edge -- an exact echo of whatever
		// shape this block is, at no cost in geometry, and without repainting
		// the block's own outline. That outline is part of what the block is,
		// solid for a compartment and dashed for everything algebraic, and
		// losing it to a thick accent stroke meant a selected block stopped
		// saying what kind of block it was.
		const ring = shapePath(n.shape, n.w, n.h);
		g.append(svg('path', { class: 'gnode-glow', d: ring }));
		g.append(svg('path', { class: 'gnode-halo', d: ring }));

		// One path for every shape, so colour, stroke and hit area are shared.
		const body = svg('path', {
			class: 'gnode-body', d: shapePath(n.shape, n.w, n.h),
		});
		// A block may be any colour, so the label cannot rely on a theme ink:
		// light text on a pale fill is invisible. Pick the ink from the fill.
		// A colour comes out of the file, so it is written as a *property*
		// rather than pasted into a style string. `setAttribute('style', …)`
		// takes whatever it is given, so `red;stroke:url(#x)` set a second
		// property nobody asked for -- not script, since setAttribute does not
		// parse markup, but not the model's business either. The property
		// setter takes a colour or ignores it.
		const ink = n.block.color ? inkFor(n.block.color) : null;
		if (n.block.color) body.style.setProperty('fill', String(n.block.color));
		g.append(body);

		const decor = shapeDecoration(n.shape, n.w, n.h);
		if (decor) g.append(svg('path', { class: 'gnode-decor', d: decor }));

		// The kind's own glyph, in the top-left of the body. A transport is a
		// sub-system whose `kind` is `system`, so it is asked for by the flag
		// that makes it one.
		const glyphKind = n.kind === 'system' && n.transport ? 'transport' : n.kind;
		const glyph = GLYPH_KINDS.has(glyphKind) ? markPath(glyphKind) : null;
		// What the glyph takes from the label's room, which is nothing unless
		// one is drawn. A centred name over a glyph in the corner is a name
		// with a mark through it: `Mean_dose_after` on a 136-wide node reaches
		// the left edge, which is exactly where the glyph is.
		//
		// Taken from *both* sides rather than shifting the name right. The name
		// is the thing on the node and it is centred on every other block; a
		// name that sits off-centre because the block happens to be a kind with
		// a mark reads as a mistake, and a row of them reads as several.
		let gutter = 0;
		if (glyph) {
			const at = shapeInset(n.shape, n.w, n.h) + GLYPH_PAD;
			const gw = MARK_W * GLYPH_SCALE;
			const gh = MARK_H * GLYPH_SCALE;
			// Only where the body has room for it beside the name: a node
			// dragged down to forty across has room for its label and nothing
			// else, and a glyph there is most of the block.
			if (n.w >= at * 2 + gw + 44 && n.h >= gh + GLYPH_PAD + 20) {
				g.append(svg('path', {
					class: 'gnode-glyph',
					d: glyph,
					transform: `translate(${at} ${GLYPH_PAD}) scale(${GLYPH_SCALE})`,
				}));
				gutter = at + gw + 4;
			}
		}

		// A sub-system is drawn as a folder-ish tab so it reads as a container
		// rather than as one more box, and says how much is inside.
		if (n.kind === 'system') {
			g.append(svg('path', {
				class: 'gsystem-tab',
				d: `M 8 0 L 8 -7 L ${Math.min(n.w * 0.45, 56)} -7 `
					+ `L ${Math.min(n.w * 0.45, 56) + 7} 0 Z`,
			}));
			const title = svg('title');
			title.textContent = (n.transport
				? `Transport ${n.name} -- runs as a chain of ${this._chainLength(n.name)} `
					+ `compartments from its Begin to its End; ${n.count} block`
					+ `${n.count === 1 ? '' : 's'} inside. Double-click to open it. Drag the `
					+ 'handle to connect from its End; drop a connection on it to feed its Begin.'
				: `Sub-system ${n.name} -- ${n.count} block`
					+ `${n.count === 1 ? '' : 's'} inside. Double-click to open it.`)
				+ (ed.isSystemEnabled(this.project, n.name)
					? '' : ' Disabled: nothing in it takes part in the run.');
			g.append(title);
		}

		// A lookup table shows the shape of its own data: the name says which
		// driver it is, the curve says what it does, which is the thing you
		// actually want off a diagram of forty boxes.
		const spark = n.kind === 'lookup';
		if (spark) {
			// With the rule the table is read by: a five-point step table drawn
			// as a sloping line shows a quantity ramping where the model holds
			// it flat, which is the one thing this thumbnail is for.
			const d = sparkPath(tablePoints(n.block), 10, 24, n.w - 20, n.h - 32,
				n.block.interpolation ?? 'linear');
			if (d) g.append(svg('path', { class: 'gnode-spark', d }));
			const title = svg('title');
			title.textContent = `${n.name} -- ${summariseTable(n.block)}; `
				+ `${INTERPOLATION_BLURB[n.block.interpolation ?? 'linear']}`
				+ `${n.block.argument ? `, read at its argument ${n.block.argument}` : ''}`;
			g.append(title);
		}

		// Labels are centred and clipped to the width the shape leaves free --
		// centred in what is left of it, where a glyph has taken a corner.
		const inset = shapeInset(n.shape, n.w, n.h);
		const textW = Math.max(20, n.w - inset * 2 - gutter * 2);
		const twoLines = n.h >= 44 && !spark;

		const label = svg('text', {
			class: 'gnode-name',
			x: n.w / 2,
			y: spark ? 17 : twoLines ? n.h / 2 - 3 : n.h / 2 + 4,
		});
		// A block may be shown under a symbol rather than its name -- `14C` with
		// the 14 raised. Plain text is still plain text, and still truncated to
		// the width the shape leaves; a symbol is laid out as tspans, which is
		// what a superscript is in SVG.
		const shown = n.block ? displayName(n.block) : (n.label ?? n.name);
		const plain = symbolText(shown);
		// Fitted on what is *seen*: the markup is not on screen, so counting
		// its characters would truncate a three-letter label mid-tag.
		const fitted = fitText(plain, textW, 6.6);
		if (n.block && hasSymbol(n.block) && fitted === plain) {
			label.append(...symbolTspans(shown));
			const title = svg('title');
			title.textContent = `${n.name} — shown as ${plain}`;
			g.append(title);
		} else {
			label.textContent = fitted;
		}
		// A property, like every other colour written here. These two come
		// from `inkFor` and are safe either way, but one rule for the whole
		// file is easier to keep than a rule with two exceptions in it.
		if (ink) label.style.setProperty('fill', ink.strong);
		g.append(label);

		if (twoLines) {
			const sub = svg('text', { class: 'gnode-sub', x: n.w / 2, y: n.h / 2 + 13 });
			sub.textContent = n.kind === 'system'
				? (n.transport
					? `chain of ${this._chainLength(n.name)}`
					: `${n.count} block${n.count === 1 ? '' : 's'}`)
				: fitText(this._subtitle(n), textW, 5.6);
			if (ink) sub.style.setProperty('fill', ink.dim);
			g.append(sub);
		}

		// The connect handle. Only the kinds a flux can leave get one -- see
		// HAS_PORT. It is always faintly present rather than appearing on
		// hover, because a control you cannot see is a control you will not
		// find.
		// A transport too: it is a block as well as a sub-system, and a line
		// out of it is a line out of its End. See `transportEndpoint`.
		if (this._hasPort(n)) {
			const cy = n.h / 2;
			const port = svg('g', { class: 'gport', 'data-port': n.name });
			port.append(svg('circle', { class: 'gport-hit', cx: n.w, cy, r: 13 }));
			port.append(svg('circle', { class: 'gport-dot', cx: n.w, cy, r: PORT_R }));
			port.append(svg('path', {
				class: 'gport-glyph',
				d: `M ${n.w - 3} ${cy} L ${n.w + 3} ${cy} `
					+ `M ${n.w + 0.5} ${cy - 2.5} L ${n.w + 3} ${cy} `
					+ `L ${n.w + 0.5} ${cy + 2.5}`,
			}));
			const title = svg('title');
			title.textContent = n.kind === 'farfield'
				? 'Drag onto a compartment to deliver this path\u2019s release there'
				: n.kind === 'waste_package'
					? 'Drag onto a compartment to deliver what leaves these packages there'
					: n.kind === 'system'
					? 'Drag onto a compartment to connect from the chain\u2019s End'
					: 'Drag onto another compartment to connect them';
			port.append(title);
			g.append(port);
		}
		return g;
	}

	/**
	 * Whether a node carries the connect handle: the kinds a flux can leave,
	 * and a transport, which is a block as well as a sub-system and whose
	 * handle connects from its End (see `transportEndpoint`). One answer for
	 * this tool and for the resize grip that gives way to it.
	 */
	_hasPort(n) {
		return HAS_PORT.has(n.kind) || (n.kind === 'system' && !!n.transport);
	}

	/** Resize grips, drawn only on the selected node. */
	_renderResizeHandles(n) {
		const g = svg('g', { class: 'gresize', 'data-resize': n.name });
		// A block with a connect port carries it at the middle of its right
		// edge, and this tool is a 14-pixel disc: an `e` grip there is drawn on
		// top of it and, being in the overlay, takes the click as well, so the
		// one control for drawing a flux out was unreachable at its own centre
		// whenever the block was selected. The corner grip changes the width,
		// so nothing is lost but the collision.
		//
		// Tested against HAS_PORT, not against `compartment`: a far-field path
		// has the same port for the same reason -- its release is dragged out
		// of it -- and kept the `e` grip on top of it, which is exactly the
		// gesture that was hard to make.
		// The corner grip goes on the shape's own corner rather than on the
		// corner of its box: on a diamond the two are a quarter of the block
		// apart, and the grip was left hanging in the space outside it.
		const c = shapeCorner(n.shape, n.w, n.h);
		const corners = this._hasPort(n)
			? [['se', c.x, c.y], ['s', n.w / 2, n.h]]
			: [['se', c.x, c.y], ['e', n.w, n.h / 2], ['s', n.w / 2, n.h]];
		for (const [corner, cx, cy] of corners) {
			const h = svg('g', {
				class: `ggrip ggrip-${corner}`,
				'data-grip': corner,
				'data-gripnode': n.name,
			});
			h.append(svg('rect', {
				class: 'ggrip-hit', x: cx - 9, y: cy - 9, width: 18, height: 18,
			}));
			h.append(svg('rect', {
				class: 'ggrip-dot',
				x: cx - GRIP / 2, y: cy - GRIP / 2, width: GRIP, height: GRIP, rx: 2,
			}));
			const t = svg('title');
			t.textContent = corner === 'se' ? 'Drag to resize (double-click to reset)'
				: corner === 'e' ? 'Drag to change the width' : 'Drag to change the height';
			h.append(t);
			g.append(h);
		}
		// The grips sit in the node's coordinate system.
		g.setAttribute('transform', `translate(${n.x} ${n.y})`);
		return g;
	}

	/** How many compartments a transport runs as, or `N` while that is not known. */
	_chainLength(path) {
		const { n } = ed.transportNumber(this.project, ed.transportParts(this.project, path));
		return n ?? 'N';
	}

	_subtitle(n) {
		// A path first: its dimensions are in the block list and in the panel,
		// and what a reader needs from the diagram is that this box is a
		// hundred cells of rock rather than one compartment.
		if (n.kind === 'farfield') {
			return truncate(`${n.block.n_f ?? 20} x ${n.block.n_m ?? 20} cells`, 22);
		}
		// Waste packages say how they fail, which is the one thing about them
		// a reader cannot tell from the box.
		if (n.kind === 'waste_package') return truncate(ed.describeWaste(n.block), 24);
		if (n.kind === 'event') return truncate(ed.describeDisruption(n.block), 26);
		// The parts of a transport that are not compartments say what they
		// are, since an expression called `i` says nothing on its own.
		const role = ed.transportOf(this.project, n.block) ? ed.transportRole(n.block) : null;
		if (role === 'number') return 'length of the chain';
		if (role === 'counter') return 'element counter';
		if (role === 'operation') {
			return truncate(`${n.block.operation ?? 'mean'} over `
				+ `${{ all: 'the chain', point: 'a point', range: 'a stretch' }[n.block.argument ?? 'all']}`, 22);
		}
		const dims = n.block.index_lists ?? [];
		if (dims.length) {
			const total = dims.reduce((acc, d) => {
				const list = (this.project.index_lists ?? []).find((l) => l.name === d);
				return acc * (list
					? list.indices.filter((i) => i.enabled !== false).length
					: 1);
			}, 1);
			return truncate(`${dims.join(' x ')} (${total})`, 22);
		}
		if (n.kind === 'compartment') {
			const entries = n.block.entries ?? [];
			if (entries.length) return `${entries.length} entr${entries.length === 1 ? 'y' : 'ies'}`;
			return `init ${truncate(String(n.block.initial ?? '0'), 14)}`;
		}
		if (n.kind === 'index_reduction') {
			return truncate(`${n.block.operation ?? 'sum'} ${n.block.target ?? '—'}`, 22);
		}
		// The blocks that remember say what they are watching, since that is
		// the one thing you need to read one of them.
		if (n.kind === 'min_max') {
			return truncate(`${n.block.operation ?? 'max'} of ${n.block.target ?? '—'}`, 22);
		}
		if (n.kind === 'running_mean') return truncate(`mean ${n.block.target ?? '—'}`, 22);
		if (n.kind === 'snapshot') return truncate(`${n.block.target ?? '—'} at event`, 22);
		if (n.kind === 'delay') {
			return truncate(`${n.block.target ?? '—'} − ${n.block.delay ?? '0'}`, 22);
		}
		if (n.kind === 'trigger') {
			const arrow = { rising: '↗', falling: '↘', both: '↕' }[n.block.direction] ?? '↗';
			return truncate(`${n.block.first ?? '0'} ${arrow} ${n.block.second ?? '0'}`, 22);
		}
		if (n.kind === 'block_reduction') {
			const t = n.block.targets ?? [];
			return truncate(t.length === 1
				? `${n.block.operation ?? 'sum'} ${t[0]}`
				: `${n.block.operation ?? 'sum'} of ${t.length}`, 22);
		}
		// A function's signature, which is the one thing to know about it from
		// the outside: what it is called with. Its body is on the second line
		// of every other kind of block, and here it is the part you read in
		// the panel instead.
		if (n.kind === 'function') {
			return truncate(`(${(n.block.parameters ?? []).join(', ')})`, 22);
		}
		return truncate(n.block.equation ?? '', 20);
	}

	/** Geometry for one connection: endpoints, the path, and its midpoint. */
	_geometry(conn, nodes) {
		const a = conn.from ? nodes.get(conn.from) : null;
		const b = conn.to ? nodes.get(conn.to) : null;
		if (!a && !b) return null;

		// Qualified, like everything else the layout is keyed by. Read with
		// the bare name -- which is what this did -- a bend or a moved
		// terminal inside a sub-system was written under `edge:NearField.out`
		// and looked for under `edge:out`, so it was stored and then ignored:
		// the handle sprang back the moment the pointer was released.
		// And this canvas's own: a pipe into another sub-system has a place of
		// its own on each canvas it is drawn on, and the line drawn whole on
		// the canvas above keeps its bend apart from them. See `waypointKey`.
		const waypoint = ed.getWaypoint(this.project, qualifiedName(conn), conn._elsewhere ? (this.system ?? '') : null);
		let p0;
		let p1;
		let openEnd = null;
		// Which end is loose, not just where it is: an end hanging off the
		// donor is an outflow to outside, one hanging off the recipient is an
		// inflow from it, and the two are drawn differently.
		let openSide = null;

		// An explicit waypoint the user dragged wins; otherwise a connection
		// that shares its pair is bowed aside.
		const bend = waypoint ?? bundlePoint(a, b, this._bundles?.get(conn.name));

		if (a && b) {
			[p0, p1] = anchors(a, b, bend);
		} else if (a) {
			const k = this._openSlot(a.name);
			p0 = { x: a.x + a.w, y: a.y + a.h / 2 };
			p1 = waypoint
				? { x: waypoint.x, y: waypoint.y }
				: { x: p0.x + TERMINAL_GAP, y: p0.y + TERMINAL_SLOT * (k + 1) };
			openEnd = p1;
			openSide = 'to';
		} else {
			const k = this._openSlot(b.name);
			p1 = { x: b.x, y: b.y + b.h / 2 };
			p0 = waypoint
				? { x: waypoint.x, y: waypoint.y }
				: { x: p1.x - TERMINAL_GAP, y: p1.y - TERMINAL_SLOT * (k + 1) };
			openEnd = p0;
			openSide = 'from';
		}

		const useBend = bend && a && b;
		const d = useBend
			? quadThrough(p0, p1, bend)
			: curve(p0, p1, a && b);
		const mid = useBend
			? { x: bend.x, y: bend.y }
			: midOf(p0, p1, a && b);

		return { p0, p1, d, mid, openEnd, openSide, hasWaypoint: !!waypoint };
	}

	/**
	 * The marker at an end that hangs outside this view.
	 *
	 * Three different things end up here. A flow that crosses the *model's*
	 * own boundary gets a cloud, the stock-and-flow convention for what lies
	 * beyond it: the material comes from, or goes to, somewhere that is not
	 * this model's business. Both directions wear the same one -- an inflow
	 * used to get a filled disc instead, which read as a block among the
	 * blocks and could not take the colour its line was given, the fill being
	 * its meaning. The exception is a source carrying the radionuclide
	 * dimension, which keeps the standard sign: the cloud says where the
	 * material comes from and the sign says what it is, and what it is is the
	 * thing these models are about. And a flow whose far end is a real block
	 * in another sub-system gets a pipe: it has not gone anywhere, it has gone
	 * *there*, and saying "leaves the model" about it was simply wrong. See
	 * `pipeTag`.
	 *
	 * No marker is centred on its end point. The path starts at an open
	 * inflow, so a mark centred there would have the line drawn across it, and
	 * it ends at an open outflow, where the arrowhead has to point *into* the
	 * cloud rather than over it. So each is offset by half its own size,
	 * backwards at the start and forwards at the end.
	 *
	 * Every one of them is draggable, by the same waypoint the bend handle
	 * writes: for a connection with one loose end the waypoint *is* that end,
	 * so a mark that can be picked up is the whole of the feature. Before
	 * this, a cloud was scenery -- clicking it panned the canvas.
	 */
	_renderTerminal(conn, geo) {
		const at = geo.openEnd;
		// A colour given to the line reaches its end as well. The mark is a
		// sibling of the line rather than a child of it -- it has to sit
		// outside the group the line's hit area is in -- so the property it
		// reads has to be put on it too, and not only on the line.
		const own = ed.connectionLook(conn).color;
		const tint = (g) => {
			if (own) g.style.setProperty('--edge-own', own);
			return g;
		};

		// Along the axis the path leaves or arrives on -- curve() aims its
		// control points at one axis or the other, so following the straight
		// line between the ends would leave the marker slightly off it.
		const axis = (from, to) => {
			const dx = to.x - from.x;
			const dy = to.y - from.y;
			return Math.abs(dx) >= Math.abs(dy)
				? { x: Math.sign(dx || 1), y: 0 }
				: { x: 0, y: Math.sign(dy || 1) };
		};

		// Grabbable, and marked as this connection's so that a click selects
		// it and a right-click gets its menu.
		const grab = (g, box) => {
			g.setAttribute('data-terminal', qualifiedName(conn));
			g.insertBefore(svg('rect', {
				class: 'gterm-hit',
				x: box.x, y: box.y, width: box.w, height: box.h, rx: 6,
			}), g.firstChild);
			return g;
		};

		if (conn._elsewhere) return tint(grab(...this._renderPipe(conn, geo)));

		if (geo.openSide !== 'from') {
			// Out of the model: a cloud, past the arrowhead, so the arrow
			// points into it. Optional -- on a diagram where most flows leave,
			// it is the same mark over and over.
			if (!this.view.show_sinks) return null;
			const { d, w, h } = sinkCloud(34);
			const dir = axis(geo.p0, at);
			const cx = at.x + (dir.x * w) / 2;
			const cy = at.y + (dir.y * h) / 2;

			const g = svg('g', { class: 'gsink' });
			g.append(svg('path', {
				class: 'gsink-cloud', d,
				transform: `translate(${cx - w / 2} ${cy - h / 2})`,
			}));
			const t = svg('title');
			t.textContent = `${conn.name}: leaves the model — drag to move it`;
			g.append(t);
			return tint(grab(g, { x: cx - w / 2 - 3, y: cy - h / 2 - 3, w: w + 6, h: h + 6 }));
		}

		// Into the model. Two icons, and which one says what the material is:
		// a source carrying the radionuclide dimension wears the standard
		// sign, the black trefoil on yellow, which is read at a glance and by
		// everyone who reads these models. Anything else gets the cloud the
		// other end of the boundary gets -- it used to get a filled disc,
		// which read as a block among the blocks and could not take the colour
		// its line was given, the fill being its meaning.
		//
		// The two do not compose. A cloud is a wide, flat shape -- 34 by 14 --
		// and a trefoil inside one is a smudge rather than a symbol at any
		// size either of them can reasonably be, which is why this is a choice
		// between them rather than one drawn on the other.
		if (!this.view.show_sources) return null;
		const material = ed.materialDimensionName(this.project);
		const nuclear = !!material
			&& ed.effectiveDims(this.project, conn).includes(material);
		const dir = axis(at, geo.p1);
		const g = svg('g', { class: `gsource${nuclear ? ' gsource-nuclear' : ''}` });
		const title = svg('title');
		title.textContent = (nuclear
			? `${conn.name}: radionuclide input from outside the model`
			: `${conn.name}: input from outside the model`)
			+ ' — drag to move it';

		if (nuclear) {
			// Behind the open end, so the line starts at the disc's edge
			// rather than being drawn across it.
			const r = 12;
			const cx = at.x - dir.x * r;
			const cy = at.y - dir.y * r;
			g.append(svg('circle', { class: 'gsource-disc', cx, cy, r }));
			const { core, blades } = radiationTrefoil(r * 0.82);
			g.append(svg('path', {
				class: 'gsource-blades', d: blades,
				transform: `translate(${cx} ${cy})`,
			}));
			g.append(svg('circle', { class: 'gsource-core', cx, cy, r: core }));
			g.append(title);
			// Wider than the disc: the hit area is what makes a mark feel like
			// a block rather than a decoration.
			const pad = 4;
			return tint(grab(g, {
				x: cx - r - pad, y: cy - r - pad, w: (r + pad) * 2, h: (r + pad) * 2,
			}));
		}

		const { d, w, h } = sinkCloud(34);
		const cx = at.x - (dir.x * w) / 2;
		const cy = at.y - (dir.y * h) / 2;
		g.append(svg('path', {
			class: 'gsource-cloud', d,
			transform: `translate(${cx - w / 2} ${cy - h / 2})`,
		}));
		g.append(title);
		return tint(grab(g, { x: cx - w / 2 - 3, y: cy - h / 2 - 3, w: w + 6, h: h + 6 }));
	}

	/**
	 * The pipe at an end that is in another sub-system, and what it says.
	 *
	 * The name of the block at the far end, and under it where that block
	 * lives -- `in NearField`, or `at the top level` -- because inside a
	 * sub-system that is exactly the question the diagram cannot otherwise
	 * answer. Truncated to what the tag holds; the tooltip has all of it,
	 * with the block's own summary.
	 *
	 * @returns {[SVGElement, {x: number, y: number, w: number, h: number}]}
	 *   the group and the box a drag can grab it by
	 */
	_renderPipe(conn, geo) {
		const at = geo.openEnd;
		const away = conn._awayFrom;
		const found = ed.findBlock(this.project, away);
		const name = truncate(baseName(away), PIPE_CHARS);
		const home = parentOf(away);
		// Where it lives, in the fewest words that answer the question. The
		// leaf of a nested path rather than the whole of it, which would not
		// fit; the tooltip carries the path in full.
		const sub = truncate(home ? `in ${baseName(home)}` : 'top level', PIPE_SUB_CHARS);

		// Three separate questions, and one number used to answer all three.
		//
		// Which side of its end point the tag sits on: the far side from the
		// block on screen, always, or the line would be drawn across it.
		// Which way the point faces: along the flow -- away from the block for
		// an outflow, towards it for an inflow. And which edge carries the
		// wall: the one facing the block, since that is where the boundary is.
		const inward = geo.openSide === 'from';
		const anchor = inward ? geo.p1 : geo.p0;
		const side = Math.sign((at.x - anchor.x) || 1);
		const nose = inward ? -side : side;

		const w = pipeWidth(name, sub);
		const h = PIPE_H;
		const { d, bar, nose: point } = pipeTag(w, h, nose, -side);

		const left = side > 0 ? at.x : at.x - w;
		const top = at.y - h / 2;

		const g = svg('g', {
			class: `gpipe gpipe-${inward ? 'in' : 'out'}`,
			transform: `translate(${left} ${top})`,
			// Where it leads, for the double-click that follows it.
			'data-goto': found ? away : null,
		});
		g.append(svg('path', { class: 'gpipe-body', d }));
		g.append(svg('path', { class: 'gpipe-bar', d: bar }));
		// Text inside the flat part, kept clear of the point.
		const tx = nose > 0 ? (w - point) / 2 : point + (w - point) / 2;
		const label = svg('text', { class: 'gpipe-name', x: tx, y: 13 });
		label.textContent = name;
		g.append(label);
		const under = svg('text', { class: 'gpipe-sub', x: tx, y: 23.5 });
		under.textContent = sub;
		g.append(under);

		const title = svg('title');
		const summary = found ? summarise(found.collection, found.block) : '';
		title.textContent = `${conn.name} ${inward ? 'comes from' : 'goes to'} ${away}`
			+ (found ? ` — ${found.kind.replace(/_/g, ' ')}` : ' — not in the model')
			+ (summary ? `, ${summary}` : '')
			+ '. Double-click to go there; drag to move this pipe.';
		g.append(title);
		// In its own coordinates: the group is translated, and the hit area is
		// a child of it.
		return [g, { x: -3, y: -3, w: w + 6, h: h + 6 }];
	}

	_renderConnection(conn, nodes, kind) {
		const geo = this._geometry(conn, nodes);
		if (!geo) return [];
		// Keyed by the qualified name, like everything else the editor
		// addresses a block by. With the bare name a connection inside a
		// sub-system answered to a key nothing ever asked for -- see the
		// `data-edge` note below.
		this._geo?.set(qualifiedName(conn), { ...geo, kind });
		const out = [];

		if (geo.openEnd) {
			const marker = this._renderTerminal(conn, geo);
			if (marker) out.push(marker);
		}

		const g = svg('g', {
			// Off by its own switch, or with its donor: a transfer out of a
			// disabled compartment has no inventory to move, and is drawn the
			// same way. See edit.implicitlyDisabled.
			class: `gedge gedge-${kind}${ed.isEffectivelyEnabled(this.project, conn)
				&& !this._impliedOff?.has(qualifiedName(conn))
				? '' : ' is-disabled'}`,
			// Qualified. Every selection, search hit and menu in this editor
			// names a block by its path, and with the bare name here none of
			// them matched a connection inside a sub-system: clicking one
			// selected nothing, the search never lit one up, and its bend
			// handle never appeared. Invisible at the top level, where the two
			// spellings are the same thing.
			'data-edge': qualifiedName(conn),
			// Its endpoints, so selecting a block can pick out the lines that
			// touch it without looking the connection up again.
			'data-from': conn.from ?? '',
			'data-to': conn.to ?? '',
		});
		g.append(svg('path', { class: 'gedge-hit', d: geo.d }));
		const line = svg('path', {
			class: 'gedge-line', d: geo.d, 'marker-end': 'url(#arrow)',
		});
		// A connection's own colour, weight and dash, when it has been given
		// any. Written as *custom properties* rather than as `stroke` and
		// `stroke-width` directly: an inline `stroke` beats every rule in the
		// stylesheet, so a coloured line would stop showing that it is
		// selected, hovered, joined to the selection or carrying a problem.
		// The base rule reads these through `var()` and the state rules
		// override it, which is the whole point -- and the selected and linked
		// widths are written as `calc()` on the same property, so a line the
		// modeller made thick stays thick when it lights up.
		//
		// A property setter also takes a colour or ignores it, where
		// `setAttribute('style', ...)` would take whatever a file said.
		const look = ed.connectionLook(conn);
		if (look.color) {
			line.style.setProperty('--edge-own', look.color);
			// ...and an arrowhead to match, so the line is its colour all the
			// way to its point.
			line.setAttribute('marker-end', `url(#${this._arrowFor(look.color)})`);
		}
		if (look.width) line.style.setProperty('--edge-own-width', String(look.width));
		if (look.dash) {
			line.style.setProperty('--edge-own-dash', DASH_PATTERN[look.dash]);
		}
		g.append(line);

		const text = truncate(ed.connectionLabelText(this.project, conn, kind), 20);
		if (text) {
			const halo = svg('text', {
				class: 'gedge-label-halo', x: geo.mid.x, y: geo.mid.y - 8,
			});
			halo.textContent = text;
			const label = svg('text', {
				class: 'gedge-label', x: geo.mid.x, y: geo.mid.y - 8,
			});
			label.textContent = text;
			g.append(halo, label);
		}
		out.push(g);
		return out;
	}

	/** The bend handle, drawn only for the selected connection. */
	_renderEdgeHandle() {
		for (const old of this.overlay.querySelectorAll(
			'[data-waypoint],[data-endedge]',
		)) old.remove();
		if (!this.selection) return;
		const named = (b) => qualifiedName(b) === this.selection.name;
		const conn = (this.project.transfers ?? []).find(named)
			?? (this.project.inflows ?? []).find(named);
		if (!conn) return;

		// Read where the line was drawn rather than working it out again: the
		// slot counter for open ends makes a second call disagree with the
		// first, and this used to be kept in step by replaying every earlier
		// transfer to advance the counter by the right amount.
		const geo = this._geo?.get(qualifiedName(conn));
		if (!geo) return;

		// Endpoint handles: grab either end to re-attach it elsewhere.
		const isSource = conn.from === undefined;
		for (const [end, point] of [['from', geo.p0], ['to', geo.p1]]) {
			if (isSource && end === 'from') continue; // a source is always from outside
			const attached = end === 'from' ? conn.from : conn.to;
			const h = svg('g', {
				class: `gend gend-${end}${attached ? '' : ' is-open'}`,
				'data-end': end,
				'data-endedge': qualifiedName(conn),
			});
			h.append(svg('circle', { class: 'gend-hit', cx: point.x, cy: point.y, r: 13 }));
			h.append(svg('circle', { class: 'gend-dot', cx: point.x, cy: point.y, r: 5.5 }));
			const t = svg('title');
			t.textContent = attached
				? `${end === 'from' ? 'Starts at' : 'Ends at'} ${attached} — drag to re-attach`
				: `${end === 'from' ? 'Comes from' : 'Goes'} outside — drag onto a compartment`;
			h.append(t);
			this.overlay.append(h);
		}

		const handle = svg('g', {
			class: 'gwaypoint', 'data-waypoint': qualifiedName(conn),
		});
		handle.append(svg('circle', {
			class: 'gwaypoint-hit', cx: geo.mid.x, cy: geo.mid.y, r: 12,
		}));
		handle.append(svg('circle', {
			class: `gwaypoint-dot${geo.hasWaypoint ? ' is-set' : ''}`,
			cx: geo.mid.x, cy: geo.mid.y, r: 5,
		}));
		const title = svg('title');
		title.textContent = geo.hasWaypoint
			? 'Drag to reshape; right-click for Straighten'
			: 'Drag to bend this connection';
		handle.append(title);
		this.overlay.append(handle);
	}

	_bundleConnections(nodes) {
		return bundleOffsets(this.project.transfers ?? [], (name) => nodes.has(name));
	}

	/**
	 * Shows one sub-system. '' is the model itself.
	 *
	 * The camera is refitted rather than kept: the sub-system's blocks are laid
	 * out in their own coordinates, and holding the old camera would open onto
	 * empty canvas.
	 */
	setSystem(path = '') {
		const next = path ?? '';
		if (next === (this.system ?? '')) return;
		this.system = next;
		this.selection = null;
		this.render();
		this.fit();
		this.hooks.onSystem?.(next);
	}

	/** The sub-system currently shown. */
	get currentSystem() { return this.system ?? ''; }

	/** Opens the sub-system a node stands for. */
	openSystem(name) {
		this.setSystem(name);
	}

	_openSlot(nodeName) {
		if (!this._openSlots) this._openSlots = new Map();
		const k = this._openSlots.get(nodeName) ?? 0;
		this._openSlots.set(nodeName, k + 1);
		return k;
	}

	/**
	 * Dotted arrows from what a block reads to the block that reads it.
	 *
	 * Every equation counts, not just expressions': a transfer's rate and a
	 * source's rate are equations too, and a parameter feeding a transfer is
	 * exactly the relationship most worth seeing. So is a reduction, which
	 * names the blocks it reduces instead of writing an equation about them.
	 *
	 * Either end can be a connection rather than a node. A transfer is drawn
	 * as a line, so an influence into one points at its midpoint -- and an
	 * equation may equally read a transfer *by name*, which is its flux, and
	 * then the arrow starts from that midpoint. `examples/four-compartment`
	 * does exactly that: `Outflow = TCOut*C3`.
	 *
	 * What is deliberately not drawn is the flow itself. A transfer moves
	 * material between its two compartments, so both depend on it, but the
	 * transfer arrow already says so; a dotted arrow beside every solid one
	 * would be noise.
	 */
	_influences(nodes) {
		const out = [];

		/**
		 * Where an influence can start or end: a node, the midpoint of a
		 * connection as it was drawn, or the sub-system node standing in for
		 * something inside it.
		 *
		 * That last one is the whole reason this is not a map lookup. A
		 * sub-system is a fold in the diagram, not a wall: an expression
		 * inside `NearField` reading `Kd` out here is a dependency that
		 * crosses it, and the connections have always been drawn to the folded
		 * node -- `_visibleEnd` is the same substitution they use. The
		 * influences were not, so every one that crossed a sub-system boundary
		 * was dropped, and a diagram of a model organised into sub-systems
		 * showed influences only *within* each one.
		 */
		const place = (name) => {
			const node = nodes.get(name);
			if (node) return { node, kind: node.kind, name };
			const through = this._visibleEnd(name);
			const stand = through && through !== name ? nodes.get(through) : null;
			if (stand) return { node: stand, kind: stand.kind, name: through, folded: true };
			const geo = this._geo?.get(name);
			// Only what is actually on the canvas: an arrow from nowhere is
			// worse than no arrow.
			return geo ? { point: geo.mid, kind: geo.kind, name } : null;
		};

		// Several blocks inside one sub-system reading the same thing outside
		// it are one arrow, not five identical ones on top of each other.
		const drawn = new Map();

		// Which block reads which is a fact about the model, so it is worked
		// out there; what is left here is where the two ends are drawn. Held
		// from one render to the next, because a drag redraws the edges on
		// every pointer move and the model is the same each time.
		this._influenceCache ??= ed.influences(this.project);
		for (const { from: read, to: reader } of this._influenceCache) {
			const to = place(reader);
			const from = place(read);
			if (!to || !from) continue;
			// Both ends inside the same sub-system: that is an arrow from a
			// node to itself, and what it stands for is not visible from here.
			if (from.name === to.name) continue;
			const key = `${from.name}\u0000${to.name}`;
			const already = drawn.get(key);
			if (already) { already.count++; already.pairs.push([read, reader]); continue; }
			drawn.set(key, { count: 1, pairs: [[read, reader]] });

			let p0;
			let p1;
			if (from.node && to.node) {
				[p0, p1] = anchors(from.node, to.node, null);
			} else if (from.node) {
				p1 = to.point;
				p0 = sidePoint(from.node, centreOf(from.node), p1);
			} else if (to.node) {
				p0 = from.point;
				p1 = sidePoint(to.node, centreOf(to.node), p0);
			} else {
				// One line reading another: midpoint to midpoint.
				p0 = from.point;
				p1 = to.point;
			}

			const g = svg('g', {
				class: `gedge gedge-influence gedge-influence-${from.kind}`
					+ `${from.folded || to.folded ? ' is-folded' : ''}`,
				// The names as *drawn*, so that selecting a sub-system lights
				// up what reaches it. See _touches.
				'data-influence': `${from.name}->${to.name}`,
			});
			g.append(svg('path', {
				class: 'gedge-line', d: curve(p0, p1, true),
				'marker-end': 'url(#arrow-dot)',
			}));
			const title = svg('title');
			g.append(title);
			// Filled in below: what this one line stands for is not known
			// until every pair has been seen.
			g._says = { title, entry: drawn.get(key) };
			out.push(g);
		}

		// One arrow can be several dependencies -- three blocks inside a
		// sub-system reading the same parameter -- and `Kd is used by
		// NearField` says less than naming what actually reads it.
		for (const g of out) {
			const { title, entry } = g._says;
			delete g._says;
			const [[read, reader]] = entry.pairs;
			title.textContent = entry.count === 1
				? `${read} is used by ${reader}`
				: `${entry.count} dependencies: `
					+ entry.pairs.slice(0, 4)
						.map(([a, b]) => `${a} \u2192 ${b}`).join(', ')
					+ (entry.count > 4 ? ', \u2026' : '');
		}
		return out;
	}

	// --- interaction ---------------------------------------------------------

	/**
	 * The node under a point, tested in model space.
	 *
	 * Not `ev.target.closest('.gnode')`: while a drag holds a pointer capture,
	 * every pointer event is retargeted to the capture element, so `ev.target`
	 * is the SVG root and never the node under the cursor. Relying on it made
	 * every connection land "outside".
	 */
	_nodeAt(point) {
		const nodes = this._nodes();
		// Reverse order so the topmost drawn node wins.
		for (let i = nodes.length - 1; i >= 0; i--) {
			const n = nodes[i];
			if (point.x >= n.x && point.x <= n.x + n.w
				&& point.y >= n.y && point.y <= n.y + n.h) {
				return n;
			}
		}
		return null;
	}

	_toModel(ev) {
		const r = this.root.getBoundingClientRect();
		return {
			x: (ev.clientX - r.left - this.camera.x) / this.camera.k,
			y: (ev.clientY - r.top - this.camera.y) / this.camera.k,
		};
	}

	_bind() {
		this.root.addEventListener('pointerdown', (ev) => this._onDown(ev));
		this.root.addEventListener('pointermove', (ev) => this._onMove(ev));
		this.root.addEventListener('pointerup', (ev) => this._onUp(ev));
		this.root.addEventListener('pointercancel', () => {
			if (this.connect) { this._endConnect(); this.render(); return; }
			if (this.drag?.kind === 'reconnect') { this._endReconnect(); this.render(); return; }
			this._endDrag();
		});
		this.root.addEventListener('dblclick', (ev) => this._onDblClick(ev));
		// A gesture is modal: while one is running, Escape belongs to it
		// wherever the focus happens to be. The diagram's own key handler is
		// on its root, and a press on a node leaves the focus on the body --
		// so Escape could not reach the one thing it is most for, and the two
		// gestures that did handle it only cancelled when the canvas had been
		// clicked beforehand. Capturing, so nothing else claims the key first,
		// and inert unless a gesture is actually in progress.
		this._onEscape = (ev) => {
			if (ev.key !== 'Escape') return;
			if (!this.drag && !this.connect) return;
			ev.preventDefault();
			ev.stopPropagation();
			if (this.connect) { this._endConnect(); this.render(); return; }
			this._cancelDrag();
		};
		window.addEventListener('keydown', this._onEscape, true);
		this.root.addEventListener('keydown', (ev) => this._onKey(ev));
		// On the tab rather than on the canvas when the application says so:
		// the canvas has a frame around it -- the panel's padding, the
		// breadcrumb above it, the help line under it -- and a wheel there did
		// nothing, which reads as a zoom that only works over blocks.
		(this.wheelHost ?? this.root)
			.addEventListener('wheel', (ev) => this._onWheel(ev), { passive: false });
		this.root.addEventListener('contextmenu', (ev) => this._onContextMenu(ev));
	}

	_onDown(ev) {
		if (!this.project || ev.button !== 0) return;
		this.root.focus({ preventScroll: true });

		const port = ev.target.closest('[data-port]');
		const grip = ev.target.closest('[data-grip]');
		const endHandle = ev.target.closest('[data-endedge]');
		const waypoint = ev.target.closest('[data-waypoint]');
		const terminal = ev.target.closest('[data-terminal]');
		const node = ev.target.closest('.gnode');
		const edge = ev.target.closest('[data-edge]');
		const decorGrip = ev.target.closest('[data-decorgrip]');
		const decor = ev.target.closest('[data-decor]');

		if (port) {
			this._beginConnect(port.dataset.port, ev);
			return;
		}

		if (grip) {
			const name = grip.dataset.gripnode;
			const n = this._nodes().find((x) => x.name === name);
			if (n) {
				const m = this._toModel(ev);
				this.drag = {
					kind: 'resize', name, corner: grip.dataset.grip,
					ox: m.x, oy: m.y, w0: n.w, h0: n.h, moved: false,
					// What Escape puts back.
					undo: () => ed.setBlockSize(this.project, name, { w: n.w, h: n.h }),
				};
				this.root.setPointerCapture(ev.pointerId);
			}
			return;
		}

		if (endHandle) {
			this._beginReconnect(endHandle.dataset.endedge, endHandle.dataset.end, ev);
			return;
		}

		if (decorGrip) {
			const id = decorGrip.dataset.decorid;
			const sh = (this._shapes ?? []).find((x) => x.id === id);
			if (sh) {
				const m = this._toModel(ev);
				const was = { x: sh.x, y: sh.y, w: sh.w, h: sh.h };
				this.drag = {
					kind: 'shape-resize', id, corner: decorGrip.dataset.decorgrip,
					ox: m.x, oy: m.y,
					box: { ...was },
					diagonal: isDiagonal(sh.figure),
					moved: false,
					undo: () => ed.updateShape(this.project, id, was),
				};
				this.root.setPointerCapture(ev.pointerId);
			}
			return;
		}

		// A shape is picked up like a block, and like a block the modifier
		// adds to the selection instead of starting a drag.
		if (decor) {
			const id = decor.dataset.decor;
			if (additive(ev)) { this._pickShapeToggle(id); return; }
			if (!this.pickedShapes.has(id)) this._selectShape(id);
			const m = this._toModel(ev);
			this.drag = {
				kind: 'shape', id, ox: m.x, oy: m.y,
				ids: [...this.pickedShapes],
				// Where each one was when the drag began, so that snapping is
				// against the shape's own position rather than against the
				// accumulated remainder of every move so far.
				from: (this._shapes ?? [])
					.filter((x) => this.pickedShapes.has(x.id))
					.map((x) => ({ id: x.id, x: x.x, y: x.y })),
				moved: false,
			};
			this.drag.undo = () => {
				for (const w of this.drag.from) {
					ed.updateShape(this.project, w.id, { x: w.x, y: w.y });
				}
			};
			this.root.setPointerCapture(ev.pointerId);
			return;
		}

		if (waypoint) {
			const wname = waypoint.dataset.waypoint;
			const view = this._wayView(wname);
			// The bend as it stands, so Escape can put it back -- including
			// the case of there being no bend, which `setWaypoint(null)` is.
			const wasBend = ed.getWaypoint(this.project, wname, view);
			this.drag = {
				kind: 'waypoint', name: wname, view, moved: false,
				undo: () => ed.setWaypoint(this.project, wname,
					wasBend ? { ...wasBend } : null, view),
			};
			this.root.setPointerCapture(ev.pointerId);
			return;
		}

		// A loose end -- a source's disc, an outflow's cloud, a pipe into
		// another sub-system -- is picked up and put down like a block. The
		// waypoint of a connection with one open end *is* that end, so this is
		// the same edit the bend handle makes, reached by grabbing the thing
		// itself rather than by selecting the line first and finding a handle.
		if (terminal) {
			const name = terminal.dataset.terminal;
			this._select(name);
			const geo = this._geo?.get(name);
			const m = this._toModel(ev);
			// The grab offset, so the mark stays where it was taken hold of
			// instead of jumping its end point under the cursor.
			const view = this._wayView(name);
			const wasEnd = ed.getWaypoint(this.project, name, view);
			this.drag = {
				kind: 'terminal', name, view, moved: false,
				dx: geo ? geo.openEnd.x - m.x : 0,
				dy: geo ? geo.openEnd.y - m.y : 0,
				undo: () => ed.setWaypoint(this.project, name,
					wasEnd ? { ...wasEnd } : null, view),
			};
			this.root.setPointerCapture(ev.pointerId);
			return;
		}

		if (node) {
			const name = node.dataset.name;
			// Shift (or the platform's own modifier) adds to the selection
			// rather than replacing it, and does not begin a drag: you are
			// picking things out, not moving them yet.
			if (additive(ev)) { this._pickToggle(name); return; }
			// Clicking something that is already part of the selection keeps
			// the selection, so the whole group can be dragged. Narrowing to
			// the one clicked happens on release, if it turns out to have
			// been a click rather than a drag.
			if (!this.picked.has(name)) this._select(name);

			const m = this._toModel(ev);
			const members = this._dragMembers(name);
			this.drag = {
				kind: 'node', name, ox: m.x, oy: m.y, members, moved: false, raised: false,
				undo: () => {
					for (const mem of members) {
						ed.setPosition(this.project, mem.name, { x: mem.x0, y: mem.y0 });
					}
				},
				// Anything can be dropped into a sub-system, a sub-system
				// included: moving one is renaming the path its blocks wear.
				// What it cannot be dropped into is itself, which
				// `_dropTargetAt` decides as the pointer passes over.
				canNest: members.length > 0,
				into: null,
			};
			this.root.setPointerCapture(ev.pointerId);
			return;
		}

		if (edge) {
			this._select(edge.dataset.edge);
			return;
		}

		// On the background: a plain drag pans, and with the modifier held it
		// draws a box round everything it touches.
		if (additive(ev)) {
			const m = this._toModel(ev);
			const base = new Set(this.picked);
			this.drag = {
				kind: 'marquee', x0: m.x, y0: m.y, x1: m.x, y1: m.y,
				base, moved: false,
				undo: () => this._pick([...base]),
			};
			this.root.setPointerCapture(ev.pointerId);
			return;
		}

		this._select(null);
		const cam = { x: this.camera.x, y: this.camera.y };
		this.drag = {
			kind: 'pan', sx: ev.clientX, sy: ev.clientY,
			ox: cam.x, oy: cam.y,
			undo: () => { this.camera.x = cam.x; this.camera.y = cam.y; },
		};
		this.root.setPointerCapture(ev.pointerId);
		this.root.classList.add('is-panning');
	}

	/**
	 * The nodes a drag from `name` carries: the whole selection when the block
	 * grabbed is part of it, and otherwise just that one.
	 */
	_dragMembers(name) {
		const wanted = this.picked.has(name) ? [...this.picked] : [name];
		const out = [];
		for (const n of this._nodes()) {
			if (!wanted.includes(n.name)) continue;
			const el = this.nodeLayer.querySelector(`.gnode[data-name="${cssEscape(n.name)}"]`);
			if (el) out.push({ name: n.name, kind: n.kind, el, x0: n.x, y0: n.y });
		}
		return out;
	}

	/** Starts a connection and marks every legal target. */
	_beginConnect(from, ev) {
		// A release out of a path goes to a compartment: one path straight
		// into another would hide where the mass is.
		const isPath = ed.RELEASING.has(ed.findBlock(this.project, from)?.kind);
		// And a path has one release, as have waste packages. Refused here rather than on release of
		// the pointer: a gesture that is going to be turned down should be
		// turned down before it is made, not after the line has been dragged
		// across the canvas onto a target that was marked as legal.
		if (isPath) {
			const taken = ed.releaseTaken(this.project, from);
			if (taken) { this.hooks.onStatus?.(taken, 'warn'); return; }
		}
		const legal = this._legalTargets({ exclude: from, paths: !isPath });
		this.connect = { from, to: null, point: this._toModel(ev), legal };
		this.root.setPointerCapture(ev.pointerId);
		this.root.classList.add('is-connecting');
		this._markTargets(legal, from);
		this._drawConnectPreview();
		const fromChain = ed.isTransport(this.project, from);
		this._showHint(ev, isPath
			? `Delivering ${from}’s release — drop on a compartment`
			: fromChain
				? `Connecting from the End of ${baseName(from)} — drop on a compartment, `
					+ 'a transport or a far-field path'
				: `Connecting from ${from} — drop on a compartment, a transport or a far-field path`);
	}

	/**
	 * Compartments that could legally be the far end of a connection: any but
	 * the near end, since nothing can flow into itself. A pair that is already
	 * joined stays a legal target -- several transfers may run between the same
	 * two compartments, and the diagram draws them side by side.
	 *
	 * A far-field path counts when the end being dragged is the receiving one:
	 * a flux can be delivered into a path, and what comes back out is the
	 * block's own release rather than a transfer.
	 */
	_legalTargets({ exclude = null, paths = true } = {}) {
		const out = new Set();
		for (const c of this.project.compartments ?? []) {
			const name = qualifiedName(c);
			if (name === exclude) continue;
			out.add(name);
		}
		if (paths) {
			for (const f of this.project.farfields ?? []) out.add(qualifiedName(f));
		}
		// Nothing is delivered into waste packages: they are never a target.
		// A transport drawn on this canvas is a target too: a line dropped on
		// it feeds its Begin, which is what `addTransfer` makes of the name.
		// Only the ones with a Begin to feed, since a chain that has lost its
		// head has nothing in it to connect to.
		for (const child of ed.childSystems(this.project, this.system ?? '')) {
			if (child === exclude || !ed.isTransport(this.project, child)) continue;
			if (ed.transportParts(this.project, child).begin) out.add(child);
		}
		return out;
	}

	_markTargets(legal, nearEnd) {
		for (const el of this.nodeLayer.children) {
			const name = el.dataset.name;
			const ok = legal.has(name);
			el.classList.toggle('is-target', ok);
			el.classList.toggle('is-not-target', !ok && name !== nearEnd);
			el.classList.toggle('is-connect-source', name === nearEnd);
		}
	}

	_onMove(ev) {
		if (this.connect) {
			const point = this._toModel(ev);
			this.connect.point = point;
			const over = this._nodeAt(point);
			const name = over?.name ?? null;
			const legal = !!name && this.connect.legal.has(name);
			this.connect.to = legal ? name : null;

			for (const el of this.nodeLayer.children) {
				el.classList.toggle('is-drop', legal && el.dataset.name === name);
			}
			this._drawConnectPreview();
			this._showHint(ev, this._dropHint(name, legal, this.connect));
			return;
		}

		if (this.drag?.kind === 'reconnect') {
			const point = this._toModel(ev);
			this.drag.point = point;
			const over = this._nodeAt(point);
			const name = over?.name ?? null;
			const legal = !!name && this.drag.legal.has(name);
			this.drag.target = legal ? name : null;
			this.drag.overName = name;
			this.drag.moved = true;

			for (const el of this.nodeLayer.children) {
				el.classList.toggle('is-drop', legal && el.dataset.name === name);
			}
			this._drawReconnectPreview();
			this._showHint(ev, this._dropHint(name, legal, this.drag));
			return;
		}

		if (!this.drag) return;

		if (this.drag.kind === 'pan') {
			this.camera.x = this.drag.ox + (ev.clientX - this.drag.sx);
			this.camera.y = this.drag.oy + (ev.clientY - this.drag.sy);
			this._applyView();
			return;
		}

		const m = this._toModel(ev);

		if (this.drag.kind === 'resize') {
			const { corner, ox, oy, w0, h0, name } = this.drag;
			const next = {};
			if (corner === 'se' || corner === 'e') next.w = this._snap(w0 + (m.x - ox), ev);
			if (corner === 'se' || corner === 's') next.h = this._snap(h0 + (m.y - oy), ev);
			this.drag.moved = true;
			ed.setBlockSize(this.project, name, next);
			// A resize changes the outline every edge attaches to, so the whole
			// node is redrawn rather than nudged.
			this._redrawNode(name);
			this._redrawEdges();
			this._renderNodeHandles();
			return;
		}

		if (this.drag.kind === 'shape') {
			this.drag.moved = true;
			const dx = m.x - this.drag.ox;
			const dy = m.y - this.drag.oy;
			for (const was of this.drag.from) {
				ed.updateShape(this.project, was.id, {
					x: this._snap(was.x + dx, ev),
					y: this._snap(was.y + dy, ev),
				});
			}
			this._redrawDecor();
			return;
		}

		if (this.drag.kind === 'shape-resize') {
			this.drag.moved = true;
			this._resizeShape(m, ev);
			this._redrawDecor();
			return;
		}

		if (this.drag.kind === 'waypoint') {
			this.drag.moved = true;
			ed.setWaypoint(this.project, this.drag.name,
				{ x: this._snap(m.x, ev), y: this._snap(m.y, ev) }, this.drag.view);
			this._redrawEdges();
			return;
		}

		if (this.drag.kind === 'terminal') {
			this.drag.moved = true;
			ed.setWaypoint(this.project, this.drag.name, {
				x: this._snap(m.x + this.drag.dx, ev),
				y: this._snap(m.y + this.drag.dy, ev),
			}, this.drag.view);
			// The whole edge layer, not one path: the mark, its line and its
			// label all follow, and the handles on the selected connection sit
			// on geometry that has just changed.
			this._redrawEdges();
			this._renderEdgeHandle();
			return;
		}

		if (this.drag.kind === 'marquee') {
			this.drag.x1 = m.x;
			this.drag.y1 = m.y;
			this.drag.moved = true;
			const box = marqueeBox(this.drag);
			const hit = this._nodes()
				.filter((n) => overlaps(n, box))
				.map((n) => n.name);
			// The classes are toggled as the box sweeps, but the application
			// is told once, on release: re-rendering the panels on every
			// pointer move would make the box crawl.
			this.picked = new Set([...this.drag.base, ...hit]);
			this._applySelection();
			this._drawMarquee(box);
			return;
		}

		// Node drag. Nothing happens until the pointer has actually travelled:
		// a press that stays put is a click, and the second half of a
		// double-click has to find the diagram exactly as it left it.
		if (!this.drag.moved
			&& Math.abs(m.x - this.drag.ox) < DRAG_SLOP
			&& Math.abs(m.y - this.drag.oy) < DRAG_SLOP) return;

		// Dragged nodes come to the top for the duration. Sub-systems are
		// drawn last and so sit above everything, and a block dragged over one
		// disappeared underneath it at the moment you were aiming. Done here
		// rather than on the press: moving an element in the document between
		// mousedown and mouseup costs that press its `click`, and with it the
		// `dblclick` that opens a sub-system.
		if (!this.drag.raised) {
			for (const mem of this.drag.members) this.nodeLayer.append(mem.el);
			this.drag.raised = true;
		}

		// The elements are moved directly. A full render here would replace
		// the very element the pointer is captured on.
		//
		// What is snapped is where the block *under the pointer* lands, and
		// everything else moves by the same delta -- so the one you are
		// dragging sits on the lattice and a group keeps its shape. Snapping
		// each member on its own would collapse the offsets between them, two
		// blocks five units apart landing on one line; snapping the delta
		// alone, which this did, moved a block in grid-sized steps without
		// ever putting it on the grid, and with the grid drawn at the same
		// pitch that is a visible untruth.
		const anchor = this.drag.members.find((mem) => mem.name === this.drag.name)
			?? this.drag.members[0];
		const rawX = m.x - this.drag.ox;
		const rawY = m.y - this.drag.oy;
		const dx = anchor
			? this._snap(anchor.x0 + rawX, ev) - anchor.x0
			: this._snap(rawX, ev);
		const dy = anchor
			? this._snap(anchor.y0 + rawY, ev) - anchor.y0
			: this._snap(rawY, ev);
		this.drag.moved = true;
		for (const mem of this.drag.members) {
			const x = mem.x0 + dx;
			const y = mem.y0 + dy;
			ed.setPosition(this.project, mem.name, { x, y });
			mem.el.setAttribute('transform', `translate(${x} ${y})`);
			// The grips live in the overlay, in the node's own coordinates, so
			// they are carried along rather than rebuilt: re-rendering them
			// would mean recomputing the whole node list on every pointer
			// move, and leaving them alone left them behind.
			const grips = this.overlay.querySelector(
				`[data-resize="${cssEscape(mem.name)}"]`,
			);
			grips?.setAttribute('transform', `translate(${x} ${y})`);
		}
		this._redrawEdges();

		// Held over a sub-system, the same gesture puts what is being dragged
		// inside it -- blocks and sub-systems alike, since a sub-system is a
		// path its blocks wear and moving one is renaming that path.
		// Aimed with the pointer rather than with the box the block is drawn
		// in: a wide block overlaps a container long before you meant it to.
		if (this.drag.canNest) {
			const into = this._dropTargetAt(m)?.name ?? null;
			this.drag.into = into;
			this._markDropSystem(into);
			if (into) {
				this._showHint(ev, `Release to move ${
					this._what(this.drag.members.map((mem) => mem.name))
				} into ${baseName(into)}`);
			} else {
				this.hint.hidden = true;
			}
		}
	}

	/**
	 * The sub-system drawn under a point, if any, topmost first.
	 *
	 * `barred` names the ones that cannot be the answer. It has to skip them
	 * and go on looking rather than giving up on the first hit: a sub-system
	 * being dragged is drawn on top and directly under the pointer, so with
	 * one hit test it shadowed the container it was being dropped into and
	 * every drop was quietly a no-op.
	 */
	_systemAt(point, barred = null) {
		const nodes = this._nodes();
		for (let i = nodes.length - 1; i >= 0; i--) {
			const n = nodes[i];
			if (n.kind !== 'system' || barred?.(n.name)) continue;
			if (point.x >= n.x && point.x <= n.x + n.w
				&& point.y >= n.y && point.y <= n.y + n.h) {
				return n;
			}
		}
		return null;
	}

	/**
	 * The sub-system a drag could be dropped into, if the pointer is over one.
	 *
	 * A sub-system being dragged is not a place to put itself, and neither is
	 * anything inside it: a container inside its own contents is the one
	 * nesting that cannot mean anything, and the domain refuses it. Better not
	 * to offer it than to offer it and explain afterwards.
	 */
	_dropTargetAt(point) {
		const carried = (this.drag?.members ?? [])
			.filter((mem) => mem.kind === 'system')
			.map((mem) => mem.name);
		return this._systemAt(point, (name) => carried.some((p) => isWithin(name, p)));
	}

	_markDropSystem(name) {
		for (const el of this.nodeLayer.children) {
			el.classList.toggle('is-drop', !!name && el.dataset.name === name);
		}
	}

	_onUp(ev) {
		if (this.connect) {
			const point = this._toModel(ev);
			const over = this._nodeAt(point);
			const name = over?.name ?? null;
			const legal = !!name && this.connect.legal.has(name);
			const { from } = this.connect;
			this._endConnect();

			if (legal) {
				this._createTransfer(from, name);
			} else if (name && name !== from) {
				this.hooks.onStatus?.(this._rejectReason(name), 'warn');
				this.render();
			} else if (!name) {
				this._createTransfer(from, null, `Added an outflow from ${from}.`);
			} else {
				this.render();
			}
			return;
		}

		if (this.drag?.kind === 'shape' || this.drag?.kind === 'shape-resize') {
			const { kind, id, moved } = this.drag;
			this._endDrag();
			// A click rather than a drag narrows the selection to the one
			// under the pointer, the way clicking a block does.
			if (!moved) {
				if (kind === 'shape') this._selectShape(id);
				return;
			}
			// Moving a shape changes nothing about the numbers, so the model
			// is not made dirty by it -- the same bargain as moving a block.
			this.hooks.onChange?.({ layoutOnly: true });
			this.render();
			return;
		}

		if (this.drag?.kind === 'reconnect') {
			const { name, end, target, overName, legal } = {
				...this.drag, legal: this.drag.legal,
			};
			const dropped = this._nodeAt(this._toModel(ev));
			const finalName = dropped?.name ?? null;
			const ok = !!finalName && legal.has(finalName);
			this._endReconnect();

			if (finalName && !ok) {
				this.hooks.onStatus?.(
					`${finalName} cannot be that end of ${name}.`, 'warn',
				);
				this.render();
				return;
			}
			try {
				ed.setConnectionEnd(this.project, name, end, ok ? finalName : null);
				// The old bend, and every pipe, was placed against the old
				// geometry.
				ed.clearWaypoints(this.project, name);
				this._changed();
				this._select(name);
				this.hooks.onStatus?.(
					ok ? `${name} now ${end === 'from' ? 'starts at' : 'ends at'} ${finalName}.`
						: `${name} now ${end === 'from' ? 'comes from' : 'goes'} outside the model.`,
					'info',
				);
			} catch (e) {
				this.hooks.onStatus?.(e.message, 'warn');
				this.render();
			}
			return;
		}

		if (this.drag?.kind === 'marquee') {
			const picked = [...this.picked];
			this._endDrag();
			this._pick(picked);
			return;
		}

		if (this.drag?.kind === 'node') {
			// Recomputed from where the pointer actually came up, rather than
			// trusting the last move event.
			const { name, moved, members } = this.drag;
			// Only a drag drops: a plain click on a block that happens to sit
			// over a container is a click, not a request to move it inside.
			const into = this.drag.canNest && moved
				? this._dropTargetAt(this._toModel(ev))?.name ?? null
				: null;
			this._endDrag();
			if (into) {
				this._moveInto(members.map((mem) => mem.name), into, { forget: true });
				return;
			}
			if (moved) { this._changed({ layoutOnly: true }); return; }
			// A click that went nowhere, on a block that was part of a group:
			// now that it is clearly a click and not the start of a drag, it
			// narrows the selection to the one under the pointer.
			if (!additive(ev) && this.picked.size > 1) this._select(name);
			return;
		}

		if (this.drag?.moved) this._changed({ layoutOnly: true });
		this._endDrag();
	}

	/**
	 * Puts a set of blocks down with their top-left corner at a point.
	 *
	 * Their offsets from each other are kept, so a group that was cut arrives
	 * looking like the group that was cut rather than as a stack at one point.
	 * A block that was never placed has no offset to keep and is left unplaced,
	 * to be laid out among its new neighbours.
	 */
	_placeAt(names, at) {
		const placed = names
			.map((n) => ({ n, p: ed.getPosition(this.project, n) }))
			.filter(({ p }) => p && Number.isFinite(p.x) && Number.isFinite(p.y));
		if (!placed.length) return;
		const x0 = Math.min(...placed.map(({ p }) => p.x));
		const y0 = Math.min(...placed.map(({ p }) => p.y));
		for (const { n, p } of placed) {
			ed.setPosition(this.project, n, { x: at.x + (p.x - x0), y: at.y + (p.y - y0) });
		}
	}

	/**
	 * The blocks a Cut has marked to be moved, drawn so that they say so.
	 *
	 * The diagram holds the names rather than the editor telling it on every
	 * render: a pending cut outlives a redraw -- going into a sub-system to
	 * paste there is a redraw -- and would otherwise be forgotten by the one
	 * navigation it exists to allow.
	 */
	setPendingCut(names) {
		this.pendingCut = names?.length ? new Set(names) : null;
		this._applyPendingCut();
	}

	_applyPendingCut() {
		const cut = this.pendingCut;
		this.root?.classList.toggle('has-cut', !!cut);
		for (const el of this.nodeLayer?.children ?? []) {
			el.classList.toggle('is-cut', !!cut && cut.has(el.dataset.name));
		}
	}

	/**
	 * Performs a pending cut: the marked blocks move here.
	 *
	 * A move, not a paste -- `_moveInto` is the same call the tree's drop and
	 * the menu's *Move into* make, so a compartment still takes its transfers
	 * and a sub-system still takes everything inside it. What this adds is the
	 * point: a paste lands where it was asked for, which a move chosen from a
	 * menu has no way to know.
	 */
	movePendingCut(names, system, at = null) {
		const live = names.filter((n) => ed.findBlock(this.project, n)
			|| ed.systems(this.project).includes(n));
		if (!live.length) {
			this.hooks.onStatus?.('What was cut is no longer in the model.', 'warn');
			this.setPendingCut(null);
			return;
		}
		this.setPendingCut(null);
		// Pasted back into the sub-system it was already in, which is an
		// ordinary thing to do -- cut a block, right-click where you want it,
		// paste. Nothing moves *between* systems then, so `_moveInto` would
		// report "Soil is now in the top level" about a block that never left
		// it. It is a reposition, and says so.
		const staying = live.every((n) => systemOf(ed.findBlock(this.project, n)?.block
			?? { system: parentOf(n) }) === system
			|| parentOf(n) === system);
		if (staying) {
			if (at) this._placeAt(live, at);
			this._pick(live);
			this._changed({ layoutOnly: true });
			this.hooks.onStatus?.(`${this._what(live)} moved.`, 'info');
			return;
		}
		this._moveInto(live, system, { at });
	}

	/**
	 * Moves a selection into a sub-system: from a menu, or from a drop.
	 *
	 * `forget` throws away where the things moved were drawn, which is what a
	 * drop wants: the coordinates something was released at belong to the
	 * diagram it just left and mean nothing on the one it lands on, so left
	 * unplaced they are laid out with their new neighbours. A move chosen from
	 * the menu is not about position at all, and keeps it.
	 */
	_moveInto(names, system, { forget = false, at = null } = {}) {
		// Every way of moving something arrives here -- the menu, a drop in the
		// tree, a drop on the canvas -- so the one rule a move has to obey is
		// checked here rather than at each of them. A connection goes where its
		// compartments go: on its own it would end up in a sub-system its own
		// two ends are not in, which is not a model. See `canTravel`.
		if (!ed.canTravel(this.project, names)) {
			this.hooks.onStatus?.('A connection goes where its compartments go — '
				+ 'move those and it follows.', 'warn');
			this.render();
			return;
		}
		try {
			const asked = this._what(names);
			const parts = ed.selectionParts(this.project, names);
			const wanted = parts.blocks.length;
			// Singular by what was *asked for*, not by what landed: one
			// compartment takes its transfers with it, and "Waste are now in
			// FarField" is what counting the result gives you.
			const one = parts.blocks.length + parts.systems.length === 1;
			const r = ed.moveSelection(this.project, names, system);
			const landed = [...r.systems.values(), ...r.moved.values()];
			if (forget) for (const to of landed) ed.clearPosition(this.project, to);
			// Where a paste was aimed. The blocks keep the shape they were in
			// -- their offsets from each other -- so a group that was cut
			// arrives looking like the group that was cut, with its top-left
			// corner at the point asked for.
			if (at) this._placeAt(landed, at);
			// The canvas may be showing something *inside* what just moved --
			// dragged from the tree, it need not be on screen at all -- and
			// its path has changed. Follow it, rather than leaving the view
			// pointing at a sub-system that no longer exists and drawing an
			// empty diagram.
			for (const [was, now] of r.systems) {
				if (was !== now && isWithin(this.system ?? '', was)) {
					this.system = reparentSystem(this.system, was, now);
					this.hooks.onSystem?.(this.system);
				}
			}
			this._pick(landed);
			this._changed();
			const where = system || 'the top level';
			// More may have gone than was asked for: a compartment takes the
			// connections that belong to it, and a sub-system takes everything
			// inside it. Saying so is better than a count that does not match
			// what was dragged.
			const extra = r.moved.size - wanted;
			this.hooks.onStatus?.(
				`${asked} ${one ? 'is' : 'are'} now in ${where}`
				+ (extra > 0
					? `, with the ${extra} connection${extra === 1 ? '' : 's'} that `
						+ `${extra === 1 ? 'belongs' : 'belong'} to `
						+ `${one ? 'it' : 'them'}.`
					: '.')
				+ (system ? ` Double-click ${baseName(system)} to go in.` : ''),
				'info',
			);
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
			this.render();
		}
	}

	/** What will happen if the pointer is released here. */
	/**
	 * Where a shape's grip has been dragged to.
	 *
	 * The corner named is the one moving, so `nw` moves the origin and takes
	 * the width and height with it, while `se` only changes the size. A line's
	 * box keeps its sign -- dragging one end past the other turns the line
	 * round, which is what it looks like it should do -- and an area's is
	 * normalised, so it flips instead of going inside out.
	 */
	_resizeShape(m, ev) {
		const { id, corner, box, diagonal } = this.drag;
		const x = this._snap(m.x, ev);
		const y = this._snap(m.y, ev);
		let next = { ...box };
		if (diagonal) {
			if (corner === 'nw') {
				next = { x, y, w: box.x + box.w - x, h: box.y + box.h - y };
			} else {
				next = { x: box.x, y: box.y, w: x - box.x, h: y - box.y };
			}
			ed.setShapeBox(this.project, id, next, { keepSign: true });
			return;
		}
		if (corner.includes('w')) { next.w = box.x + box.w - x; next.x = x; }
		if (corner.includes('n')) { next.h = box.y + box.h - y; next.y = y; }
		if (corner.includes('e')) next.w = x - box.x;
		if (corner.includes('s')) next.h = y - box.y;
		ed.setShapeBox(this.project, id, next);
	}

	/** The shape layer alone: nothing else on the canvas has moved. */
	_redrawDecor() {
		this.decorLayer.replaceChildren();
		this._renderDecor();
		this._applyDecorSelection();
	}

	_dropHint(name, legal, ctx) {
		if (legal) {
			// Dropped on a transport, the line goes into the head of its
			// chain; said, since the node is the whole chain.
			const into = ed.isTransport(this.project, name)
				? ` — into its ${ed.transportParts(this.project, name).begin?.name ?? 'Begin'}`
				: '';
			return ctx.end
				? `Release to attach to ${name}${into}`
				: `Release to connect to ${name}${into}`;
		}
		if (name && name !== ctx.from) return `${name} cannot be a target`;
		return ctx.end
			? 'Release on empty space to detach from the model'
			: 'Release on empty space for an outflow';
	}

	_rejectReason(name) {
		const found = ed.findBlock(this.project, name);
		if (found?.kind === 'farfield') {
			return `${name} is a far-field path, and a release cannot be delivered `
				+ `straight into another path: give it a compartment in between.`;
		}
		if (found?.kind === 'waste_package') {
			return `${name} is a set of waste packages: nothing flows into them, `
				+ `their release comes out.`;
		}
		if (!found && ed.systems(this.project).includes(name)) {
			return ed.isTransport(this.project, name)
				? `${name} is a transport with no Begin compartment, so there is nothing in it to feed.`
				: `${name} is a sub-system: open it and connect to a compartment inside, or `
					+ 'make it a transport.';
		}
		return `${name} is not a compartment, so it cannot be a transfer target.`;
	}

	_createTransfer(from, to, note) {
		try {
			const t = ed.addTransfer(this.project, from, to);
			this._changed();
			this._select(qualifiedName(t));
			if (note) this.hooks.onStatus?.(note, 'info');
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
			this.render();
		}
	}

	/** Starts dragging one end of an existing connection to somewhere else. */
	_beginReconnect(name, end, ev) {
		const found = ed.findBlock(this.project, name);
		if (!found) return;
		const conn = found.block;
		const nearEnd = end === 'from' ? conn.to : conn.from;

		// A path is a legal end either way round -- a flux goes into its first
		// cell, a release comes out of its last -- but never at both ends of
		// one transfer.
		const nearIsPath = nearEnd != null
			&& ed.RELEASING.has(ed.findBlock(this.project, nearEnd)?.kind);
		const legal = found.kind === 'inflow'
			? this._legalTargets({ exclude: null })
			: this._legalTargets({ exclude: nearEnd, paths: !nearIsPath });

		this.drag = {
			kind: 'reconnect', name, end, legal,
			target: null, point: this._toModel(ev), moved: false,
			from: nearEnd,
		};
		this.root.setPointerCapture(ev.pointerId);
		this.root.classList.add('is-connecting');
		this._markTargets(legal, nearEnd);
		this._drawReconnectPreview();
		this._showHint(ev,
			`Moving the ${end === 'from' ? 'start' : 'end'} of ${name}`);
	}

	/** The rubber band while an endpoint is being moved. */
	_drawReconnectPreview() {
		const nodes = this._nodeMap();
		const anchor = this.drag.from ? nodes.get(this.drag.from) : null;
		this.overlay.replaceChildren();

		const target = this.drag.target ? nodes.get(this.drag.target) : null;
		let p0;
		let p1;
		if (anchor && target) {
			[p0, p1] = anchors(anchor, target, null);
		} else if (anchor) {
			p0 = sidePoint(anchor, centreOf(anchor), this.drag.point);
			p1 = this.drag.point;
		} else {
			p0 = this.drag.point;
			p1 = this.drag.point;
		}
		// Drawn in the direction the connection actually flows.
		const [a, b] = this.drag.end === 'from' ? [p1, p0] : [p0, p1];
		this.overlay.append(svg('path', {
			class: 'gconnect-preview', d: curve(a, b, true),
			'marker-end': 'url(#arrow-sel)',
		}));
	}

	_endReconnect() {
		this.drag = null;
		this.root.classList.remove('is-connecting');
		for (const el of this.nodeLayer.children) {
			el.classList.remove('is-target', 'is-not-target', 'is-drop', 'is-connect-source');
		}
		this.hint.hidden = true;
	}

	_endConnect() {
		this.connect = null;
		this.overlay.replaceChildren();
		this.root.classList.remove('is-connecting');
		for (const el of this.nodeLayer.children) {
			el.classList.remove('is-target', 'is-not-target', 'is-drop', 'is-connect-source');
		}
		this.hint.hidden = true;
	}

	/** The selection box, drawn while the pointer sweeps it out. */
	_drawMarquee(box) {
		let rect = this.overlay.querySelector('.gmarquee');
		if (!rect) {
			rect = svg('rect', { class: 'gmarquee' });
			this.overlay.append(rect);
		}
		rect.setAttribute('x', box.x);
		rect.setAttribute('y', box.y);
		rect.setAttribute('width', box.w);
		rect.setAttribute('height', box.h);
	}

	_endDrag() {
		if (this.drag?.canNest) this._markDropSystem(null);
		this.overlay.querySelector('.gmarquee')?.remove();
		this.drag = null;
		this.root.classList.remove('is-panning');
		this.hint.hidden = true;
	}

	_showHint(ev, text) {
		const r = this.container.getBoundingClientRect();
		this.hint.textContent = text;
		this.hint.hidden = false;
		this.hint.style.left = `${ev.clientX - r.left + 16}px`;
		this.hint.style.top = `${ev.clientY - r.top + 16}px`;
	}

	_drawConnectPreview() {
		this.overlay.replaceChildren();
		const nodes = this._nodeMap();
		const a = nodes.get(this.connect.from);
		if (!a) return;
		const p0 = { x: a.x + a.w, y: a.y + a.h / 2 };
		const target = this.connect.to ? nodes.get(this.connect.to) : null;
		const p1 = target
			? anchors(a, target, null)[1]
			: this.connect.point;
		this.overlay.append(svg('path', {
			class: 'gconnect-preview',
			d: curve(p0, p1, true),
			'marker-end': 'url(#arrow-sel)',
		}));
	}

	/** Replaces a single node's element, keeping the rest of the diagram. */
	_redrawNode(name) {
		const n = this._nodes().find((x) => x.name === name);
		const old = this.nodeLayer.querySelector(`.gnode[data-name="${cssEscape(name)}"]`);
		if (!n || !old) return null;
		const fresh = this._renderNode(n);
		if (this.selection?.name === name) fresh.classList.add('is-selected');
		// The tab stop stays where it was, whichever node is redrawn.
		fresh.setAttribute('tabindex', old.getAttribute('tabindex') ?? '-1');
		old.replaceWith(fresh);
		return fresh;
	}

	/** Cheaper than a full render while something is being dragged. */
	_redrawEdges() {
		this._openSlots = new Map();
		const nodes = this._nodeMap();
		this.edgeLayer.replaceChildren();
		this._renderEdges(nodes);
		this._applySelection();
	}

	// --- context menu --------------------------------------------------------

	/**
	 * Right-clicking a block or a connection.
	 *
	 * The menu offers what the drag gestures offer -- connect, re-attach,
	 * delete -- for the cases where a gesture is awkward: connecting two boxes
	 * at opposite ends of a large diagram, or re-attaching an end onto a
	 * compartment that is currently off screen.
	 */
	_onContextMenu(ev) {
		ev.preventDefault();
		if (!this.project) return;

		// The selected connection's own handles -- the two ends and the bend --
		// sit on top of its line, so a right-click on one of those is still a
		// right-click on that connection.
		const onEdge = ev.target.closest(
			'[data-edge],[data-endedge],[data-waypoint],[data-terminal]',
		);
		const edgeName = onEdge?.dataset.edge
			?? onEdge?.dataset.endedge ?? onEdge?.dataset.waypoint
			?? onEdge?.dataset.terminal ?? null;
		// Nodes are found in model space: a right-click over a node's label or
		// its resize grip should still be a right-click on the node.
		const node = edgeName ? null : this._nodeAt(this._toModel(ev));
		const name = edgeName ?? node?.name ?? null;

		// A shape, when nothing of the model is over it. Its own handles
		// count as it, the way a connection's do.
		const decor = name ? null : ev.target.closest('[data-decor],[data-decorgrip]');
		const decorId = decor?.dataset.decor ?? decor?.dataset.decorid ?? null;
		if (decorId) {
			// Right-clicking one that is not in the selection makes it the
			// selection: a menu about something you have not chosen is a menu
			// about the wrong thing.
			if (!this.pickedShapes.has(decorId)) this._selectShape(decorId);
			const ids = [...this.pickedShapes];
			openMenu({
				x: ev.clientX,
				y: ev.clientY,
				items: this._shapeMenu(ids),
				title: ids.length > 1 ? `${ids.length} shapes` : 'shape',
			});
			return;
		}

		// Empty canvas: what used to be the toolbar above the diagram. The
		// point at which it was opened is where a new block goes, which a
		// button on a toolbar can never know.
		if (!name) {
			openMenu({
				x: ev.clientX,
				y: ev.clientY,
				items: this._canvasMenu(this._toModel(ev)),
				title: 'diagram',
			});
			return;
		}

		this.openMenuFor(name, ev.clientX, ev.clientY);
	}

	/**
	 * Putting what is selected onto the chart, when the chart is what is on
	 * screen.
	 *
	 * Only then. These menus are opened from the diagram, the tree and the
	 * Information view, and the first of those is on a tab the chart is not --
	 * so in practice this is the tree's menu and the reading view's, which are
	 * the two that are beside the chart. A block's route onto the chart is
	 * otherwise the line picker above it, which lists every series in the model
	 * and is a poor way to reach one block you are looking at in the tree.
	 *
	 * The chart and the table draw the same choice of series, so this is one
	 * pair of items with two spellings -- `seriesView` says which of them is in
	 * front, or nothing when neither is, and `onChart` does the work.
	 */
	/**
	 * Bringing what the menu is about to the middle of the canvas.
	 *
	 * Offered wherever a block's menu is -- the diagram, the tree and the
	 * Information view -- because the two places it is most wanted are the two
	 * that are not the diagram: you find a block by name in a tree of four
	 * thousand and then have to find it again, by eye, on a canvas it may not
	 * even be the current sub-system of.
	 *
	 * The tab is the caller's business, not this view's: `onShowDiagram` is
	 * what puts the canvas in front, and the graph does the centring. Nothing
	 * here knows there are tabs.
	 */
	_centreItem(names) {
		const many = names.length > 1;
		return {
			label: many ? 'Centre these on the canvas' : 'Centre on the canvas',
			title: `Brings ${many ? 'them' : 'it'} to the middle of the diagram at `
				+ 'the zoom it is at — and into the sub-system it is in, if that is '
				+ 'not the one on screen. Fit shows everything; this shows this.',
			onPick: () => {
				this.hooks.onShowDiagram?.();
				// A frame after the tab is in front, not the same instant.
				// Centring is arithmetic on the canvas's own rectangle, and
				// the canvas has just been shown -- read in the same turn it
				// still measures as whatever it was while the chart was over
				// it, which put the block 85 pixels off centre every time this
				// was picked from the tree. One frame is what it costs to
				// measure the canvas somebody is actually looking at.
				requestAnimationFrame(() => this.centreOn(names));
			},
		};
	}

	_chartItems(names) {
		const view = this.hooks.seriesView?.();
		if (!view) return [];
		const many = names.length > 1;
		return [
			{
				label: `Add to ${view}`,
				title: `Puts ${many ? 'these' : 'it'} in the ${view} beside what is `
					+ 'already there',
				onPick: () => this.hooks.onChart?.(names, 'add'),
			},
			{
				label: `Show in ${view}`,
				title: `Shows ${many ? 'these' : 'it'} and nothing else`,
				onPick: () => this.hooks.onChart?.(names, 'only'),
			},
			{ separator: true },
		];
	}

	/**
	 * A menu for a place rather than for a thing: what can be put here.
	 *
	 * The block tree's empty space. Pointing at no row is pointing at the model
	 * rather than at anything in it, so the place is the top level -- and the
	 * one thing there is to do to a place is paste into it.
	 *
	 * @returns {boolean} whether there was anything to show
	 */
	openPasteMenu(system, x, y) {
		if (!this.project) return false;
		openMenu({
			x,
			y,
			items: [this._pasteItem(system ?? '')],
			title: system ? `sub-system ${system}` : 'the top level',
		});
		return true;
	}

	/**
	 * The menu for one block or sub-system, opened at a point on the screen.
	 *
	 * Public because the diagram is not the only view of a model. The tree and
	 * the Information view are two more, and a right-click on a block in one
	 * of them should offer what a right-click on the diagram offers rather
	 * than a smaller menu that has to be learned separately. Nothing in the
	 * menu depends on where the pointer was or on the block being drawn: every
	 * item acts on the project and on the selection, so the only thing that
	 * changes is where the panel appears.
	 *
	 * @returns {boolean} whether there was anything to show
	 */
	openMenuFor(name, x, y) {
		if (name == null || !this.project) return false;

		// Right-clicking inside a group keeps the group: the menu is about all
		// of it. A sub-system in the group is part of it, so this comes before
		// the sub-system's own menu.
		if (this.picked.size > 1 && this.picked.has(name)) {
			const many = [...this.picked];
			openMenu({
				x,
				y,
				items: [
					...this._chartItems(many),
					this._centreItem(many),
					{ separator: true },
					...this._menuForMany(many),
				],
				title: this._what(many),
			});
			return true;
		}

		// A sub-system is a node without being a block -- and the top level,
		// which the block tree offers as a row of its own, is one whose path
		// is the empty string. Testing it for truth is why right-clicking that
		// row used to report that the model no longer existed.
		if (name === '' || ed.systems(this.project).includes(name)) {
			// Selected first, like anything else with a menu, so the panels
			// show what the menu is about while the menu is open. The top
			// level is not a thing that can be selected: it is where you are.
			if (name) this._select(name);
			openMenu({
				x,
				y,
				items: [
					// A sub-system stands for everything in it here too: its
					// blocks are what would go on the chart.
					...(name ? this._chartItems([name]) : []),
					// The top level is not drawn on anything, so there is
					// nowhere to centre it.
					...(name ? [this._centreItem([name]), { separator: true }] : []),
					...this._menuFor({ name: name ? baseName(name) : 'the model', path: name }, 'system'),
				],
				title: name ? `sub-system ${name}` : 'the top level',
			});
			return true;
		}

		const found = ed.findBlock(this.project, name);
		if (!found) return false;

		// Right-clicking anything outside the selection selects that one
		// first, so the panels show what the menu is about.
		this._select(name);

		const items = [
			...this._chartItems([name]),
			this._centreItem([name]),
			{ separator: true },
			...this._menuFor(found.block, found.kind),
		];
		if (!items.length) return false;
		openMenu({ x, y, items, title: `${found.kind} ${name}` });
		return true;
	}

	/**
	 * Moves blocks into a sub-system from outside the diagram -- a drop in the
	 * tree. Where they were drawn is forgotten, as with a drop on the canvas:
	 * coordinates on the diagram they left mean nothing on the one they land
	 * on, and left unplaced they are laid out among their new neighbours.
	 */
	moveInto(names, system) {
		this._moveInto(names, system, { forget: true });
	}

	/**
	 * What a selection is, in words.
	 *
	 * One thing is named; several are counted, by kind, because a selection
	 * that holds a sub-system as well as blocks cannot honestly be called
	 * blocks -- and what a menu item is about is most of what tells you
	 * whether to pick it.
	 */
	_what(names) {
		const parts = ed.selectionParts(this.project, names);
		const n = parts.blocks.length;
		const s = parts.systems.length;
		if (n + s === 1) return baseName(parts.systems[0] ?? parts.blocks[0]);
		const bits = [];
		if (n) bits.push(n === 1 ? '1 block' : `${n} blocks`);
		if (s) bits.push(s === 1 ? '1 sub-system' : `${s} sub-systems`);
		return bits.join(' and ') || 'nothing';
	}

	/**
	 * Cut and Copy, which every menu here offers.
	 *
	 * The clipboard belongs to the application, not to the diagram: the block
	 * tree opens these same menus, and two clipboards that disagreed about
	 * what had been copied would be worse than one that is sometimes empty.
	 *
	 * There was a `Clone` here as well -- a copy put down beside the original,
	 * renaming whatever collided. It went because Copy and Paste do it: a
	 * paste lands where the menu was opened, so copying and pasting beside
	 * something is the same act in two steps that can also be done in one
	 * somewhere else, which is one idea rather than two.
	 */
	_copyItems(names) {
		const systems = ed.selectionParts(this.project, names).systems.length;
		// A transfer is the arrow between two compartments and is nothing
		// without them: copied on its own it would paste as a connection
		// pointing at blocks that are not in the copy, which is not a copy of
		// anything. `connectionsWith` already strands such a connection rather
		// than carrying it; declining here says so before the paste produces
		// nothing, and a selection holding the compartments as well is fine --
		// then the arrow travels with them.
		const can = ed.canTravel(this.project, names);
		const why = 'A connection is the arrow between two compartments and cannot '
			+ 'be taken on its own. Select the compartments at its ends as well and '
			+ 'it comes along with them.';
		return [
			{
				label: 'Cut',
				hint: '⌘X',
				disabled: !can,
				title: can
					? 'Marks this to be moved. Nothing changes until a Paste says '
						+ 'where it goes, and any other edit calls it off.'
					: why,
				onPick: () => this.hooks.onCut?.(names),
			},
			{
				label: 'Copy',
				hint: '⌘C',
				disabled: !can,
				title: !can ? why
					: 'Takes a copy, with any connection whose compartments are '
					+ 'all in the selection'
					+ (systems
						? ', and everything inside the sub-systems: their blocks '
							+ 'however deep, the sub-systems nested in them, and '
							+ 'the arrows between them'
						: '')
					+ '. Paste it with a right-click on the canvas, here or in '
					+ 'another sub-system.',
				onPick: () => this.hooks.onCopy?.(names),
			},
		];
	}

	/**
	 * Copy format and Paste format: how a block looks, taken from one and put
	 * on others -- a node's colour and shape, a connection's colour, weight
	 * and line style. See `formatOf` and `applyFormat` in ../domain/edit.js.
	 *
	 * A clipboard of its own, beside the blocks': taking a block's look is not
	 * taking the block, and it must not throw away a copy waiting to be
	 * pasted. Copy wants one block, since a look copied from three is three
	 * looks; Paste takes the whole selection, and skips the block the format
	 * came from.
	 */
	_formatItems(names) {
		const clip = this.hooks.formatClipboard?.();
		const single = names.length === 1 ? names[0] : null;
		const source = single ? ed.formatOf(this.project, single) : null;
		const targets = names.filter((n) => n !== clip?.from && ed.formatOf(this.project, n));
		const items = [];
		if (single) {
			items.push({
				label: 'Copy format',
				hint: '\u2325\u2318C',
				disabled: !source,
				title: !source ? 'It has no look of its own to copy.'
					: source.kind === 'node'
						? 'Takes its colour and shape, to paste onto other blocks.'
						: 'Takes its colour, weight and line style, to paste onto other connections.',
				onPick: () => this.hooks.onCopyFormat?.(single),
			});
		}
		const n = targets.length;
		items.push({
			label: n > 1 ? `Paste format onto ${n} blocks` : 'Paste format',
			hint: '\u2325\u2318V',
			disabled: !clip || !n,
			title: !clip ? 'Nothing copied yet: Copy format on a block first.'
				: !n ? `This is ${clip.from}, where the format came from.`
					: `Gives ${n === 1 ? 'it' : 'them'} the look of ${clip.from}: `
						+ (clip.kind === 'node' ? 'its colour and shape' : 'its colour, weight and line style')
						+ ', as far as each can take it.',
			onPick: () => this.hooks.onPasteFormat?.(targets),
		});
		return items;
	}

	/**
	 * Paste, aimed at a particular sub-system.
	 *
	 * `at` is where the group's top-left corner lands, which only the canvas
	 * menu knows -- a right-click in the tree has no point on the diagram, so
	 * the copies go a little way off where they were and can be dragged.
	 */
	_pasteItem(system, at = null) {
		const clip = this.hooks.clipboard?.();
		// Where it will land is not in the label. It is wherever the menu was
		// opened, which is where the pointer already is, and naming it made
		// the longest item in the menu out of the one fact the reader does not
		// need told -- `Paste the sub-system NearField into Geosphere` for an
		// act whose whole gesture was pointing at Geosphere. What it will
		// paste is worth saying, because that came from somewhere else; the
		// destination is said in the tooltip, where a doubt can be settled.
		const where = system ? baseName(system) : 'the top level';
		// A pending cut answers this item too, and says something different:
		// those blocks move here, where a copy arrives as a second one. The
		// title says which, since that is the whole of what the reader needs
		// to know before pressing it.
		const cut = this.pendingCut;
		if (cut?.size) {
			const what = cut.size === 1 ? [...cut][0] : `${cut.size} blocks`;
			return {
				label: `Paste ${what}`,
				hint: '⌘V',
				title: `Moves ${cut.size === 1 ? 'it' : 'them'} into ${where} — nothing `
					+ 'is copied and nothing was deleted. Any other edit calls the cut off.',
				onPick: () => this.hooks.onPaste?.({ system, at }),
			};
		}
		return {
			label: clip
				? `Paste ${clip.whole ? `the sub-system ${clip.what}` : clip.what}`
				: 'Paste',
			hint: '⌘V',
			disabled: !clip,
			title: clip
				// Where it came from, and -- when that was another tab of this
				// application -- which model, because a paste that produced
				// blocks from a window the reader is not looking at is the one
				// case worth naming before it happens.
				? `Into ${where}, from ${clip.from
					? `${clip.from}, copied in another tab`
					: clip.system === null ? 'several sub-systems'
						: clip.system || 'the top level'}`
				: 'Nothing has been cut or copied yet',
			onPick: () => this.hooks.onPaste?.({ system, at }),
		};
	}

	/** The menu for a selection of several things: where they go, or go away. */
	_menuForMany(names) {
		const parts = ed.selectionParts(this.project, names);
		const here = parts.blocks.length
			? systemOf(ed.findBlock(this.project, parts.blocks[0])?.block ?? {})
			: (parts.systems.length ? parentOf(parts.systems[0]) : (this.system ?? ''));
		const inside = parts.systems.reduce(
			(n, p) => n + ed.blocksIn(this.project, p, { deep: true }).length, 0,
		);
		// Only what this diagram draws can be lined up on it -- see
		// `_alignPicked` for what else a selection can be holding.
		const shown = this._nodeMap();
		const drawn = names.filter((n) => shown.has(n)).length;
		return [
			...this._copyItems(names),
			...this._formatItems(names),
			{ separator: true },
			this._alignItem(drawn, (how) => this._alignPicked(names, how)),
			this._moveItem(names, here),
			{ separator: true },
			{
				label: 'Delete',
				hint: 'Del',
				danger: true,
				title: inside
					? `A sub-system takes everything inside it: ${inside} more `
						+ `block${inside === 1 ? '' : 's'} would go`
					: '',
				onPick: () => this.deleteSelected(),
			},
		];
	}

	/**
	 * The `Align` item: line a selection up, or spread it out.
	 *
	 * What every drawing program puts under that name, and what a diagram
	 * drawn by hand needs most -- six blocks nudged into place one at a time
	 * are six blocks that are nearly level. The submenu is built once and used
	 * for blocks and for shapes alike, so `run` says what the eight
	 * arrangements are done to.
	 *
	 * @param {number} count how many things would move
	 * @param {(how: string) => void} run
	 */
	_alignItem(count, run) {
		const few = count < 2;
		const line = (label, how, title) => ({ label, title, onPick: () => run(how) });
		// Three is the first number that can be spread: with two, the ends of
		// the span are all there is, and there is nothing between them to
		// place. Offered and greyed rather than hidden, so the menu says the
		// same thing every time it is opened.
		const spread = (label, how) => ({
			label,
			disabled: count < 3,
			title: count < 3
				? 'Three or more are needed: with two there is nothing between them'
				: 'Equal space between them. The outer edges of the selection '
					+ 'stay where they are, and what is between them is spaced out '
					+ 'evenly — so boxes of different sizes end up with equal '
					+ 'gaps rather than equal centres.',
			onPick: () => run(how),
		});
		return {
			label: 'Align',
			disabled: few,
			title: few ? 'Two or more, on this diagram, to line up' : '',
			items: [
				line('Align left', 'left', 'Left edges, on the leftmost'),
				line('Align centre', 'centre', 'Centred across, on the middle of the selection'),
				line('Align right', 'right', 'Right edges, on the rightmost'),
				{ separator: true },
				line('Align top', 'top', 'Top edges, on the topmost'),
				line('Align middle', 'middle', 'Centred down, on the middle of the selection'),
				line('Align bottom', 'bottom', 'Bottom edges, on the bottommost'),
				{ separator: true },
				spread('Distribute horizontally', 'across'),
				spread('Distribute vertically', 'down'),
			],
		};
	}

	/**
	 * Lines up the blocks of a selection that are drawn on this diagram.
	 *
	 * The selection can hold more than the diagram shows: a connection, which
	 * is a line rather than a box; a block in another sub-system, picked in
	 * the tree; one of a kind the view is currently hiding. None of those has
	 * a place on this canvas to be lined up on, so the arrangement is over
	 * what is actually drawn here.
	 */
	_alignPicked(names, how) {
		const here = this._nodeMap();
		const on = names.filter((n) => here.has(n));
		try {
			const moved = ed.alignBlocks(this.project, on, how);
			if (!moved) {
				this.hooks.onStatus?.('Already lined up: nothing moved.', 'info');
				return;
			}
			this._changed({ layoutOnly: true });
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	/** The same, for the drawing layer. */
	_alignShapes(ids, how) {
		try {
			const moved = ed.alignShapes(this.project, ids, how);
			if (!moved) {
				this.hooks.onStatus?.('Already lined up: nothing moved.', 'info');
				return;
			}
			this._changed({ layoutOnly: true });
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	/**
	 * The `Move into` item.
	 *
	 * Disabled as a whole when every target under it is, with the reason in
	 * its place: a submenu that opens onto nothing but greyed lines makes you
	 * work out why for yourself.
	 */
	_moveItem(names, here, label = 'Move into') {
		// A connection cannot go anywhere on its own, for the reason it cannot
		// be copied on its own: a transfer between two compartments in
		// `NearField` does not belong in `Biosphere`, whatever is done to the
		// arrow -- it belongs where its ends are, and moving those is what
		// moves it. See `canTravel`.
		const can = ed.canTravel(this.project, names);
		const items = can ? this._moveTargets(names, here) : [];
		const nowhere = !items.length || items.every((i) => i.separator || i.disabled);
		return {
			label,
			items,
			disabled: nowhere,
			title: !can
				? 'A connection goes where its compartments go. Move those and it '
					+ 'follows; there is nowhere it can go without them.'
				: nowhere
					? `Already in ${here || 'the top level'}; every other sub-system is `
						+ 'in the selection or inside it'
					: '',
		};
	}

	/**
	 * Where a selection can be moved to.
	 *
	 * Every sub-system except the ones it cannot go into: the sub-systems
	 * being moved and anything inside them, since nothing can end up inside
	 * itself. The one they are already in is offered but marked, so the list
	 * says where they are rather than hiding it.
	 */
	_moveTargets(names, here) {
		const parts = ed.selectionParts(this.project, names);
		const barred = (path) => parts.systems.some((p) => isWithin(path, p));
		const targets = ed.systems(this.project).filter((p) => p !== here && !barred(p));
		return [
			{
				// The way a flat model gets organised: there is nowhere to
				// move a block to until something makes the first place.
				label: 'a new sub-system…',
				disabled: !parts.blocks.length,
				title: parts.blocks.length
					? `Makes a sub-system in ${here || 'the top level'} and puts `
						+ `${this._what(parts.blocks)} in it`
					: 'A sub-system is made around blocks; move one into an '
						+ 'existing sub-system instead',
				onPick: () => this._moveIntoNewSystem(parts.blocks),
			},
			{ separator: true },
			{
				label: 'the top level',
				disabled: !here,
				onPick: () => this._moveInto(names, ''),
			},
			...targets.map((path) => ({
				label: path,
				onPick: () => this._moveInto(names, path),
			})),
		];
	}

	/** The compartments a connection end can be moved to, plus outside. */
	_endTargets(current, forbidden, pick) {
		const items = (this.project.compartments ?? []).map((c) => {
			const target = qualifiedName(c);
			return {
				label: target,
				hint: target === current ? 'current' : '',
				disabled: target === current || target === forbidden,
				title: target === forbidden
					? 'A transfer cannot start and end at the same compartment'
					: '',
				onPick: () => pick(target),
			};
		});
		items.push({ separator: true });
		items.push({
			label: 'outside the model',
			hint: current == null ? 'current' : '',
			disabled: current == null || forbidden === null,
			title: forbidden === null
				? 'A transfer needs a compartment at one end'
				: '',
			onPick: () => pick(null),
		});
		return items;
	}

	/**
	 * The menu for empty canvas: adding blocks, what the diagram shows, and
	 * the view actions. This is the Build toolbar, moved to where it is used.
	 *
	 * @param at model-space point of the right-click -- where new blocks land
	 */
	/**
	 * What can be done to the shapes that are selected.
	 *
	 * Everything a shape has is here, because a shape has nowhere else: it is
	 * not a block, so it has no row in the tree and nothing in the inspector,
	 * and a panel of its own for eight properties would be a panel in the way
	 * of the diagram the rest of the time.
	 */
	_shapeMenu(ids) {
		const first = ed.findShape(this.project, ids[0]);
		const sh = first ? ed.readShape(first) : null;
		const many = ids.length > 1;
		const set = (patch) => {
			try {
				for (const id of ids) ed.updateShape(this.project, id, patch);
				this._changed({ layoutOnly: true });
			} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
		};
		// A swatch beside the name: ten colours are quicker to tell apart by
		// eye than by word, and the words are only there for the ones who
		// cannot see the difference.
		const colours = (key) => [
			{
				label: 'none',
				hint: key === 'fill' ? 'see through' : 'no outline',
				checked: () => sh?.[key] === ed.NO_COLOR,
				keepOpen: true,
				onPick: () => set({ [key]: ed.NO_COLOR }),
			},
			{ separator: true },
			...ed.SHAPE_COLORS.map((name) => ({
				label: name,
				swatch: `var(--shape-${name})`,
				checked: () => sh?.[key] === name,
				keepOpen: true,
				onPick: () => set({ [key]: name }),
			})),
		];

		return [
			{
				label: 'Fill',
				hint: many ? '' : sh?.fill ?? '',
				items: colours('fill'),
			},
			{
				label: 'Line',
				hint: many ? '' : sh?.line ?? '',
				items: colours('line'),
			},
			{
				label: 'Line style',
				items: [
					...ed.SHAPE_DASHES.map((dash) => ({
						label: dash,
						checked: () => sh?.dash === dash,
						keepOpen: true,
						onPick: () => set({ dash }),
					})),
					{ separator: true },
					...ed.SHAPE_WIDTHS.map((width) => ({
						label: `${width} px`,
						checked: () => sh?.line_width === width,
						keepOpen: true,
						onPick: () => set({ line_width: width }),
					})),
				],
			},
			{ separator: true },
			{
				label: 'Settings…',
				hint: 'dbl',
				onPick: () => this.openShapeSettings(ids[0]),
			},
			{ separator: true },
			{
				label: sh?.text ? 'Change the label…' : 'Add a label…',
				title: 'A word or two on the shape itself — what this group is, '
					+ 'what the arrow means',
				onPick: () => this._labelShape(ids, sh),
			},
			...(sh?.text || many ? [{
				label: 'Label size',
				items: ed.SHAPE_TEXT_SIZES.map((size) => ({
					label: `${size} px`,
					checked: () => sh?.text_size === size,
					keepOpen: true,
					onPick: () => set({ text_size: size }),
				})),
			}, {
				// How it is written, all in one submenu: the hand, the weight
				// and where it is ranged. A note starts out in the scribble --
				// see FIGURE_DEFAULTS in ../domain/edit.js -- and every other
				// shape in the diagram's own face, which is what a label on an
				// arrow should look like.
				label: 'Label style',
				items: [
					...ed.SHAPE_TEXT_FONTS.map((font) => ({
						label: {
							sans: 'the diagram\u2019s face',
							scribble: 'a scribble',
							serif: 'serif',
							mono: 'monospaced',
						}[font] ?? font,
						checked: () => (sh?.text_font ?? 'sans') === font,
						keepOpen: true,
						onPick: () => set({ text_font: font }),
					})),
					{ separator: true },
					{
						label: 'bold',
						checked: () => !!sh?.text_bold,
						keepOpen: true,
						onPick: () => set({ text_bold: !sh?.text_bold }),
					},
					{
						label: 'italic',
						checked: () => !!sh?.text_italic,
						keepOpen: true,
						onPick: () => set({ text_italic: !sh?.text_italic }),
					},
					{ separator: true },
					...ed.SHAPE_TEXT_ALIGNS.map((align) => ({
						label: { left: 'ranged left', center: 'centred', right: 'ranged right' }[align],
						checked: () => (sh?.text_align ?? 'center') === align,
						keepOpen: true,
						onPick: () => set({ text_align: align }),
					})),
				],
			}] : []),
			{
				label: 'Flip',
				items: [
					{
						label: 'left to right',
						checked: () => !!sh?.flip_x,
						keepOpen: true,
						onPick: () => set({ flip_x: !sh?.flip_x }),
					},
					{
						label: 'top to bottom',
						checked: () => !!sh?.flip_y,
						keepOpen: true,
						onPick: () => set({ flip_y: !sh?.flip_y }),
					},
				],
			},
			this._alignItem(ids.length, (how) => this._alignShapes(ids, how)),
			{
				label: 'Order',
				title: 'Among the shapes. Every shape is drawn behind every '
					+ 'block, which is what makes a group box a group box.',
				items: [
					{
						label: 'Bring to front',
						onPick: () => {
							ed.orderShapes(this.project, ids, 'front');
							this._changed({ layoutOnly: true });
						},
					},
					{
						label: 'Send to back',
						onPick: () => {
							ed.orderShapes(this.project, ids, 'back');
							this._changed({ layoutOnly: true });
						},
					},
				],
			},
			{ separator: true },
			{
				label: 'Duplicate',
				onPick: () => {
					const made = ed.duplicateShapes(this.project, ids);
					this.pickedShapes = new Set(made.map((x) => x.id));
					this._changed({ layoutOnly: true });
				},
			},
			{
				label: 'Delete',
				hint: 'Del',
				danger: true,
				onPick: () => this.deleteShapes(ids),
			},
		];
	}

	/**
	 * Asks for a shape's label.
	 *
	 * In as many lines as somebody wants to write, because a sticky note is
	 * written in lines and `window.prompt` cannot hold one: the lines a writer
	 * types are kept as they were typed, and the words between them are
	 * wrapped to the page. `onPromptLines` opens a box for that; where the
	 * host has not given one, the one-line prompt still works.
	 */
	_labelShape(ids, sh) {
		const apply = (next) => {
			if (next == null) return;
			try {
				for (const id of ids) ed.updateShape(this.project, id, { text: next });
				this._changed({ layoutOnly: true });
			} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
		};
		if (this.hooks.onPromptLines) {
			this.hooks.onPromptLines('Label', sh?.text ?? '', apply);
			return;
		}
		apply(this.hooks.onPrompt ? this.hooks.onPrompt('Label', sh?.text ?? '') : null);
	}

	/** Puts a shape on the canvas, in the sub-system being shown. */
	_addShapeAt(figure, at) {
		try {
			const shape = ed.addShape(this.project, figure, {
				system: this.system ?? '',
				at,
				size: figureSize(figure),
			});
			this.pickedShapes = new Set([shape.id]);
			this.picked.clear();
			this.selection = null;
			this.hooks.onSelect?.(null);
			this._changed({ layoutOnly: true });
			this.hooks.onStatus?.(
				'Added a shape. Drag it to move it, its grips to resize it, '
				+ 'and right-click it for its colours and label.', 'info',
			);
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_canvasMenu(at) {
		const here = this.system ?? '';
		const inTransport = ed.isTransport(this.project, here);
		// Only the compartments of this sub-system can take a source term
		// drawn here.
		// ...and a far-field path is somewhere a source term can be delivered
		// too: it lands in the first cell of the fracture.
		const comps = [
			...(this.project.compartments ?? []),
			...(this.project.farfields ?? []),
		].filter((c) => systemOf(c) === here);
		// ...but not waste packages: a source term goes into a compartment or a
		// path, and the packages already are one.
		const v = ed.view(this.project);
		const paths = ed.systems(this.project);
		// A block with no dimension has no index to reduce over.
		const reducible = ed.reducibleBlocks(this.project, { indexed: true });
		const aggregable = ed.reducibleBlocks(this.project);
		// Anything with a value of its own can be watched, and only a discrete
		// event can drive a snapshot.
		const watchable = ed.watchableBlocks(this.project);
		const events = ed.discreteEvents(this.project);
		// A path is one path per nuclide by construction, so it cannot exist
		// in a model with no radionuclides.
		const hasNuclides = !!ed.nuclideList(this.project);
		const toggle = (key, label, title = null) => ({
			label,
			title,
			checked: () => !!ed.view(this.project)[key],
			keepOpen: true,
			onPick: () => this.setViewOption({ [key]: !ed.view(this.project)[key] }),
		});

		// Arranged as a list of what this menu is for, in the order somebody
		// reaches for them: make something, move something, go somewhere, then
		// the settings that are about the canvas rather than about the model.
		//
		// The first group carries a heading rather than repeating the verb.
		// Every item in it used to say it -- `Add compartment here`, `Add
		// source term`, `New sub-system here` -- which is the same word six
		// times down a menu, and `here` said on some of them and not others
		// even though it is true of all of them.
		const picked = [...this.picked];
		return [
			{ heading: 'Add here' },
			{
				label: 'Compartment',
				title: 'A box that holds an inventory over time',
				onPick: () => this._addNodeAt('compartment', at),
			},
			{
				label: 'Expression',
				title: 'A quantity worked out from the others at each step',
				onPick: () => this._addNodeAt('expression', at),
			},
			{
				label: 'Parameter',
				title: 'A constant',
				onPick: () => this._addNodeAt('parameter', at),
			},
			{
				label: 'Inflow',
				disabled: !comps.length,
				title: comps.length
					? 'An input from outside the model, into a compartment or a '
						+ 'far-field path'
					: 'A source needs a compartment to flow into',
				items: comps.map((c) => ({
					label: `into ${c.name}`,
					onPick: () => this._addSourceTo(qualifiedName(c)),
				})),
			},
			{
				// Everything else a model is made of. Grouped because the list
				// grew past what a context menu can show without a scrollbar,
				// and a menu you have to scroll is a menu whose last item you
				// will not find. Compartments, expressions, parameters and
				// source terms stay outside it: they are what you reach for.
				label: 'Other blocks',
				items: [
					{
						label: 'Lookup table',
						title: 'A value that follows a series of points as time passes',
						onPick: () => this._addNodeAt('lookup', at),
					},
					{
						// Created with one parameter and an empty body: a body
						// this could invent would be a guess, and the problem
						// strip asks for the real one by name.
						label: 'Function',
						title: 'Arithmetic written once and called from any equation, '
							+ 'as Func(x)',
						onPick: () => this._addNodeAt('function', at),
					},
					{
						label: '1-D transport',
						title: inTransport
							? 'A transport holds no sub-system, and a transport is one'
							: 'A chain of N identical compartments drawn as two, Begin and End: '
								+ 'transport through a soil column or a sediment, discretised without '
								+ 'drawing every slice. Comes with Begin, End, N and an element counter.',
						disabled: inTransport,
						onPick: () => this._addTransportHere(at),
					},
					{
						label: 'Far-field pathway',
						title: hasNuclides
							? 'FARFCOMP: transport along a fracture in rock, with diffusion '
								+ 'into the rock matrix. A source term goes into it and the '
								+ 'release comes out the other side.'
							: 'Needs the model to have radionuclides',
						disabled: !hasNuclides,
						onPick: () => this._addNodeAt('farfield', at),
					},
					{
						label: 'Event',
						title: 'Something that happens to the model at an instant — at a time, or at '
							+ 'random at a rate: a share of some packages fail, a share of a compartment '
							+ 'moves elsewhere. A deterministic run takes the expected-value form; a '
							+ 'probabilistic realisation draws the occurrences.',
						onPick: () => this._addNodeAt('event', at),
					},
					{
						label: 'Waste packages',
						title: 'The source term with its barriers: an inventory inside packages '
							+ 'that fail over time, a waste form that degrades, and a release '
							+ 'drawn out of the block into the near field.',
						onPick: () => this._addNodeAt('waste_package', at),
					},
					{
						// A reduction with nothing to reduce is not a model, so
						// one is created already pointed at something and the
						// inspector changes it -- the same bargain as a new
						// compartment, which starts at zero.
						label: 'Reduce over an index',
						title: reducible.length
							? 'Sums, averages or takes the extreme of one block '
								+ `along one of its index lists — starts on ${reducible[0]}`
							: 'Needs a block with at least one index list',
						disabled: !reducible.length,
						onPick: () => this._addReductionAt('index_reduction', at, reducible),
					},
					{
						label: 'Combine blocks',
						title: aggregable.length
							? 'Combines several blocks, index by index — starts on '
								+ `${aggregable[0]}`
							: 'Needs a block to combine',
						disabled: !aggregable.length,
						onPick: () => this._addReductionAt('block_reduction', at, aggregable),
					},
					{
						// The blocks that depend on what has already happened.
						// Each is created watching something, for the same
						// reason a reduction is created pointed at something: a
						// block with nothing to watch is not yet a model.
						label: 'Recorder',
						title: watchable.length
							? `What a block has been, not only what it is — starts on ${watchable[0]}`
							: 'Needs a block to watch',
						disabled: !watchable.length,
						items: [
							{
								label: 'Min/max',
								title: 'The largest or smallest value its target has taken',
								onPick: () => this._addRecorderAt('min_max', at, watchable),
							},
							{
								label: 'Running mean',
								title: 'The mean of its target over the time it has been recording',
								onPick: () => this._addRecorderAt('running_mean', at, watchable),
							},
							{
								label: 'Snapshot',
								title: events.length
									? 'Its target as it was when an event last fired'
									: 'Needs a discrete event to take the snapshot',
								disabled: !events.length,
								onPick: () => this._addRecorderAt('snapshot', at, watchable, events[0]),
							},
							{
								label: 'Delay',
								title: 'Its target as it was a given time ago',
								onPick: () => this._addRecorderAt('delay', at, watchable),
							},
							{ separator: true },
							{
								label: 'Trigger',
								title: 'The instant one expression crosses another. The solver '
									+ 'stops there, so whatever it drives happens when it happens — '
									+ 'a snapshot taken, a recording started or stopped. It moves no mass '
									+ 'itself; an Event does that.',
								onPick: () => this._addRecorderAt('trigger', at, watchable),
							},
						],
					},
				],
			},
			// A transport holds the compartments of its chain and nothing else
			// -- the rule for what may be moved where refuses a sub-system in one -- so
			// this is not offered inside one, and the reason is said.
			{
				label: 'Sub-system',
				title: inTransport
					? 'A transport is a chain of compartments and holds no sub-system of its own'
					: 'A named place to put blocks, with its own namespace',
				disabled: inTransport,
				onPick: () => this._addSystemHere(at),
			},
			// Inside a transport, the one block that belongs to a transport
			// and nowhere else: an operation over the chain, at the point
			// clicked. It is also on the transport's own menu from outside.
			...(inTransport ? [{
				label: 'Transport operation',
				title: 'The sum or the mean of the chain’s compartments — all of them, '
					+ 'or a stretch a caller asks for.',
				onPick: () => this._addOperationTo(here, at),
			}] : []),

			{ separator: true },
			// What is on the clipboard and what goes onto it.
			//
			// Cut and Copy act on the selection, which a right-click on empty
			// canvas does not clear -- so they are about whatever is still
			// ringed on the diagram. With nothing ringed they are not there at
			// all rather than there and grey: this is the menu for a patch of
			// empty canvas, and an item about a selection that does not exist
			// has nothing to say to somebody who has not made one. A block's
			// own menu always has a subject, so it always offers the pair.
			...(picked.length ? this._copyItems(picked) : []),
			this._pasteItem(here, at),
			// Beside Paste because it is the same idea reached a different
			// way: blocks from somewhere else, landing here.
			{
				label: 'Import…',
				title: 'Bring blocks out of another model file into this one',
				disabled: !this.hooks.onImport,
				onPick: () => this.hooks.onImport?.(),
			},

			// Where to go, when there is anywhere: a model with no sub-system
			// has neither of these, and a separator with nothing between it
			// and the next one is a rule drawn under nothing.
			...(here || paths.length ? [{ separator: true }] : []),
			...(here ? [{
				label: `Leave ${baseName(here)}`,
				hint: 'up',
				onPick: () => this.setSystem(parentOf(here)),
			}] : []),
			...(paths.length ? [{
				label: 'Go to',
				items: [
					{
						label: 'the whole model',
						hint: here ? '' : 'here',
						disabled: !here,
						onPick: () => this.setSystem(''),
					},
					...paths.map((path) => ({
						label: path,
						hint: path === here ? 'here' : '',
						disabled: path === here,
						onPick: () => this.setSystem(path),
					})),
				],
			}] : []),

			{ separator: true },
			{
				// Three groups, in the order a reader narrows down: which
				// blocks are drawn, then what is drawn *between* them, then
				// the one thing here that is not on the diagram at all.
				label: 'Show',
				items: [
					toggle('show_expressions', 'expressions'),
					toggle('show_parameters', 'parameters'),
					toggle('show_lookups', 'lookup tables'),
					toggle('show_reductions', 'index operations & aggregates'),
					toggle('show_functions', 'functions'),
					toggle('show_recorders', 'recorders & events'),
					toggle('show_sources', 'inflow icons'),
					toggle('show_sinks', 'outflow icons'),
					{ separator: true },
					// What runs between the blocks. The first is not a switch
					// but it is the same question -- what a transfer shows on
					// the diagram -- so it belongs beside the other one rather
					// than in a group of its own.
					{
						label: 'Transfer labels',
						hint: v.connection_label,
						items: ed.CONNECTION_LABELS.map((mode) => ({
							label: mode,
							checked: () => ed.view(this.project).connection_label === mode,
							keepOpen: true,
							onPick: () => this.setViewOption({ connection_label: mode }),
						})),
					},
					toggle('show_influences', 'influences'),
					{ separator: true },
					// Not a kind of block, and not the amber marks either --
					// those stay whatever this says. It is the list under the
					// tabs, here because this is where the other "show me /
					// do not show me" switches are. The ⚠ button in the
					// header is the other way to it.
					toggle('show_warning_list', 'the warning list'),
				],
			},
			{
				// Down here with the rest of what is about the canvas rather
				// than about the model: a shape is drawn on it, a picture is
				// taken of it, and the settings below decide how it behaves.
				// It goes where it was asked for, which is what this menu
				// knows and a toolbar button never could.
				label: 'Add shape…',
				title: 'A box to group things in, an arrow to point with, or a '
					+ 'picture of what the model is about — drawn behind the '
					+ 'blocks, saved with the model, and read by nothing in it',
				onPick: async () => {
					const { openShapePicker } = await import('./shapepicker.js');
					openShapePicker({
						onPick: (figure) => this._addShapeAt(figure, at),
					});
				},
			},
			{
				label: 'Save as picture',
				title: 'The whole diagram of this sub-system, at 1:1 — not the part '
					+ 'in view, and without the selection rings and handles, which '
					+ 'are about the editor rather than the model.',
				items: Object.entries(PICTURE_KINDS).map(([kind, spec]) => ({
					label: spec.label,
					title: kind === 'svg'
						? 'Lines and text rather than pixels: it scales to any size '
							+ 'and can be edited in a drawing program.'
						: kind === 'jpeg'
							? 'Photographic compression, so the lines soften a little; '
								+ 'PNG is the better choice for a diagram.'
							: 'Pixels, at twice the size on screen so it stays sharp '
								+ 'in print.',
					onPick: () => this.savePicture(kind),
				})),
			},
			{
				// What is about the canvas rather than about the model: the
				// three settings that decide what it looks like and how a drag
				// behaves on it, then four things it already does by wheel and
				// drag. None of them is part of the model, which is why they
				// are not under *Show* with the blocks.
				label: 'Canvas',
				items: [
					toggle('show_grid', 'Show grid',
						'The lattice behind the diagram, at whatever spacing the zoom '
						+ 'can show. It is drawn or not drawn; whether a drag lands on '
						+ 'it is the setting below.'),
					{
						label: 'Snap to the grid',
						checked: () => !!ed.view(this.project).snap_to_grid,
						keepOpen: true,
						title: 'Whether a block lands on the grid when it is moved '
							+ 'or resized — and a bend or a loose end when it is '
							+ 'dragged. Hold Alt during a drag to do the opposite '
							+ 'of whatever this says, for one placement without '
							+ 'changing the setting.',
						onPick: () => this.setViewOption({
							snap_to_grid: !ed.view(this.project).snap_to_grid,
						}),
					},
					toggle('show_help', 'Show help',
						'The line under the diagram saying what the pointer can do '
						+ 'here. It costs the diagram the room, so it is worth turning '
						+ 'off once the gestures are familiar.'),
					{ separator: true },
					{ label: 'Auto-layout', onPick: () => this.relayout() },
					{ label: 'Fit to view', onPick: () => this.fit() },
					{ label: 'Zoom in', hint: 'scroll', onPick: () => this.zoomBy(1.25) },
					{ label: 'Zoom out', hint: 'scroll', onPick: () => this.zoomBy(0.8) },
				],
			},
		];
	}

	/** A new node, at the point the menu was opened from. */
	/**
	 * Adds a block where the menu was opened -- and in the sub-system being
	 * shown, since that is what "here" means. Everything downstream addresses
	 * it by its qualified name.
	 */
	_addNodeAt(kind, at) {
		try {
			const system = this.system ?? '';
			const make = {
				compartment: () => ed.addCompartment(this.project, { at, system }),
				expression: () => ed.addExpression(this.project, { system }),
				parameter: () => ed.addParameter(this.project, { system }),
				lookup: () => ed.addLookup(this.project, { system }),
				function: () => ed.addFunction(this.project, { system }),
				farfield: () => ed.addFarfield(this.project, { at, system }),
				waste_package: () => ed.addWastePackage(this.project, { at, system }),
				event: () => ed.addDisruption(this.project, { at, system }),
			}[kind];
			const block = make();
			const name = qualifiedName(block);
			// addCompartment takes a position; the others do not, so place
			// them here rather than letting the auto-placer guess.
			ed.setPosition(this.project, name, at);
			this._select(name);
			this._changed();
			this.hooks.onSelect?.({ kind, name });
			// A kind that is switched off in `Show` has just been added and is
			// nowhere to be seen: it is in the model, in the tree and in the
			// rail, and the canvas is the one place it is not. Said, with the
			// switch named -- clicking Add and getting nothing reads as a
			// click that did not take.
			this.sayIfNotDrawn(name);
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	/**
	 * Adds a reduction already pointed at something, so the model stays valid
	 * the moment it exists. Which block that is matters less than that there
	 * is one: the inspector's "Reduce" list changes it, and re-derives the
	 * dimensions with it.
	 */
	_addReductionAt(kind, at, candidates) {
		try {
			const system = this.system ?? '';
			const first = candidates[0];
			const block = kind === 'index_reduction'
				? ed.addIndexOperation(this.project, { target: first, system })
				: ed.addAggregate(this.project, { targets: [first], system });
			const name = qualifiedName(block);
			ed.setPosition(this.project, name, at);
			this._select(name);
			this._changed();
			this.hooks.onSelect?.({ kind, name });
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	/**
	 * Adds a block that remembers, already watching something -- the same
	 * bargain as a new reduction. It takes its target's dimensions with it, so
	 * a peak of a per-nuclide dose is per nuclide without being asked.
	 */
	_addRecorderAt(kind, at, candidates, event = null) {
		try {
			const system = this.system ?? '';
			const first = candidates[0];
			const block = ed.addRecorder(this.project, kind, {
				system,
				...(kind === 'trigger'
					? { first, second: '0' }
					: { target: first }),
				...(event ? { event } : {}),
			});
			const name = qualifiedName(block);
			ed.setPosition(this.project, name, at);
			this._select(name);
			this._changed();
			this.hooks.onSelect?.({ kind, name });
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	_menuFor(block, kind) {
		const name = kind === 'system' ? block.path : qualifiedName(block);
		const del = {
			label: 'Delete',
			hint: 'Del',
			danger: true,
			onPick: () => { this._select(name); this.deleteSelected(); },
		};

		// A sub-system node stands for everything inside it. The top level is
		// one of these too, reached by right-clicking the root row of the
		// block tree -- which used to say the model no longer existed.
		if (kind === 'system') {
			const path = block.path;
			if (!path) {
				return [
					{ label: 'Show the top level', onPick: () => this.setSystem('') },
					{ separator: true },
					this._pasteItem(''),
				];
			}
			const inside = ed.blocksIn(this.project, path, { deep: true }).length;
			const transport = ed.isTransport(this.project, path);
			const on = ed.isSystemEnabled(this.project, path);
			// Off because of a sub-system further out: the switch to find is
			// that one, so this one is not offered as though it would help.
			const byOuter = !on && !ed.disabledSystems(this.project).includes(path);
			return [
				{ label: 'Open', hint: 'dbl', onPick: () => this.setSystem(path) },
				...(transport ? [{
					label: 'Add operation over the chain',
					title: 'The sum or the mean of the chain’s compartments — all of '
						+ 'them, or a stretch a caller asks for.',
					onPick: () => this._addOperationTo(path),
				}] : []),
				// A sub-system is a block too, with a block's switch: off, it
				// takes everything in it out of the run, and the blocks keep
				// their own switches for when it comes back.
				{
					label: on ? 'Disable' : 'Enable',
					title: byOuter
						? `${block.name} is off because ${ed.disablingSystem(this.project, { system: path })
							?? 'a sub-system around it'} is; enable that one.`
						: on
							? `Leaves everything in ${block.name} out of the run. The blocks keep `
								+ 'their own settings and switches, and come back with it.'
							: `Puts ${block.name} and everything in it back into the run.`,
					disabled: byOuter,
					onPick: () => this._setSystemEnabled(path, !on),
				},
				{ separator: true },
				...this._copyItems([path]),
				this._pasteItem(path),
				{ separator: true },
				// Moving one is renaming the path its blocks wear, which is
				// why this sits beside Rename rather than being the thing the
				// format cannot say.
				this._moveItem([path], parentOf(path)),
				{
					label: 'Rename…',
					onPick: () => this._renameSystem(path),
				},
				// A transport is deleted whole or kept whole: its parts are not
				// blocks that happen to share a sub-system, so there is no
				// dissolving one. See `deleteSystem`.
				...(transport ? [] : [{
					label: 'Dissolve',
					title: 'Removes the sub-system; its blocks move out into this one',
					danger: true,
					onPick: () => this._dissolveSystem(path),
				}]),
				{
					label: 'Delete, and everything in it',
					hint: 'Del',
					title: `The ${inside} block${inside === 1 ? '' : 's'} inside `
						+ `${inside === 1 ? 'goes' : 'go'} too.`
						+ (transport
							? ' A transport is deleted whole: Begin, End, N and the counter are the chain.'
							: ' Dissolve keeps them.'),
					danger: true,
					onPick: () => { this._select(path); this.deleteSelected(); },
				},
			];
		}

		const settings = {
			label: 'Settings…',
			hint: 'dbl',
			title: `Unit, dimensions, per-index values, appearance and comment for ${block.name}`,
			onPick: () => this.hooks.onOpenSettings?.(name),
		};
		// Ecolego's own switch. Off, the block stays -- equations, values,
		// place on the diagram -- and is left out of the run, which is how a
		// model with a broken block in it still runs.
		const on = ed.isEnabled(block);
		const toggle = {
			label: on ? 'Disable' : 'Enable',
			title: on
				? 'Leaves it out of the run. It keeps everything it has, and '
					+ 'anything still enabled that reads it will say so.'
				: 'Puts it back into the run.',
			onPick: () => this._setEnabled(name, !on),
		};
		const here = systemOf(block);
		const moveTo = this._moveItem([name], here);

		// Cut, Copy -- and Paste, into the sub-system this block is in. A block
		// holds nothing, so pointing at one cannot mean "into it"; it means
		// where it lives, which is what somebody pointing at a block in the
		// tree is pointing at. On the diagram that is the canvas being shown,
		// so the item reads the same there as the canvas menu's own.
		//
		// Not on a connection, which is neither a container nor a place: a
		// transfer is the arrow between two compartments, and "paste into the
		// arrow" is not a thing anybody means. Its own Cut and Copy decline for
		// the matching reason -- see `_copyItems`.
		const isLink = kind === 'transfer' || kind === 'inflow';
		const copies = [
			...this._copyItems([name]),
			...(isLink ? [] : [this._pasteItem(systemOf(block))]),
			...this._formatItems([name]),
		];

		if (kind === 'compartment') {
			// A compartment is named by its path: the list reaches across
			// sub-systems, where two of them may be called the same thing.
			const others = (this.project.compartments ?? [])
				.map((c) => qualifiedName(c))
				.filter((c) => c !== name);
			const connect = others.map((target) => {
				// Connecting twice is allowed -- two routes between the same
				// places, one per process -- so this says what is already
				// there rather than refusing.
				const existing = ed.transfersBetween(this.project, name, target).length;
				return {
					label: target,
					hint: existing ? `${existing} already` : '',
					title: existing
						? `Adds another transfer from ${name} to ${target}; their fluxes add`
						: '',
					onPick: () => this._connectTo(name, target),
				};
			});
			connect.push({ separator: true });
			connect.push({
				label: 'outside the model',
				onPick: () => this._connectTo(name, null),
			});

			// What can be made from this compartment, under a heading of its
			// own -- the same arrangement as the canvas menu's `Add here`, and
			// for the same reason: the verb said once over the group instead
			// of on each item. Both make something new *attached to this one*,
			// which is what a compartment's menu is for that no other block's
			// is: an inflow into it, and a transfer out of it.
			return [
				settings,
				{ heading: 'Add' },
				{
					label: 'Inflow',
					title: `An inflow into ${name} from outside the model`,
					onPick: () => this._addSourceTo(name),
				},
				{
					// `Transfer to`, not `Connect to`: what it makes is a
					// transfer, which is the word the rest of the editor uses
					// for it -- the tree, the matrix and the problem strip all
					// say transfer, and the menu that creates one said connect.
					label: 'Transfer to',
					items: connect,
					disabled: !connect.length,
				},
				{ separator: true },
				...copies,
				{ separator: true },
				moveTo,
				toggle,
				del,
			];
		}

		if (kind === 'transfer') {
			// Where the line goes, beside where its ends go. Shown even with
			// nothing to undo, so that a line someone has bent by accident has
			// a visible way back rather than a gesture to remember.
			const view = this._wayView(name);
			const bent = !!ed.getWaypoint(this.project, name, view);
			const straighten = {
				label: 'Straighten',
				disabled: !bent,
				title: bent
					? `Drops the bend and runs ${block.name} straight between its ends`
					: `${block.name} is already straight. Drag the handle at its `
						+ `midpoint to bend it.`,
				onPick: () => {
					ed.setWaypoint(this.project, name, null, view);
					this._changed({ layoutOnly: true });
					this.hooks.onStatus?.(`${name} straightened.`, 'info');
				},
			};

			return [
				settings,
				{ separator: true },
				{
					label: 'Starts at',
					items: this._endTargets(block.from, block.to, (to) =>
						this._moveEnd(name, 'from', to)),
				},
				{
					label: 'Ends at',
					items: this._endTargets(block.to, block.from, (to) =>
						this._moveEnd(name, 'to', to)),
				},
				straighten,
				{ separator: true },
				...copies,
				{ separator: true },
				moveTo,
				toggle,
				del,
			];
		}

		if (kind === 'inflow') {
			return [
				settings,
				{ separator: true },
				{
					label: 'Flows into',
					items: (this.project.compartments ?? []).map((c) => {
						const target = qualifiedName(c);
						return {
							label: target,
							hint: target === block.to ? 'current' : '',
							disabled: target === block.to,
							onPick: () => this._moveEnd(name, 'to', target),
						};
					}),
				},
				{ separator: true },
				...copies,
				{ separator: true },
				moveTo,
				toggle,
				del,
			];
		}

		// An expression or a parameter is a value, with nothing to connect.
		//
		// Every one of these menus ends the same way: what to do with the block
		// as it stands -- move it, switch it out of the run, remove it -- after
		// what to make from it and what to put on the clipboard. Disable used
		// to sit second, above everything, which put the least-used item of the
		// menu where the eye lands first.
		return [
			settings,
			{ separator: true },
			...copies,
			{ separator: true },
			moveTo,
			toggle,
			del,
		];
	}

	/** Switches a block into or out of the run. */
	_setEnabled(name, on) {
		try {
			ed.setBlockEnabled(this.project, name, on);
			this._changed();
			this.hooks.onStatus?.(on
				? `${name} is enabled again.`
				: `${name} is disabled: it stays in the model and takes no part in the run.`,
			'info');
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_setSystemEnabled(path, on) {
		try {
			ed.setSystemEnabled(this.project, path, on);
			const inside = ed.blocksIn(this.project, path, { deep: true }).length;
			this._changed();
			this.hooks.onStatus?.(on
				? `${path} is enabled again, with the ${inside} block${inside === 1 ? '' : 's'} in it.`
				: `${path} is disabled: its ${inside} block${inside === 1 ? '' : 's'} stay${inside === 1 ? 's' : ''} `
					+ 'in the model and take no part in the run.',
			'info');
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	// --- sub-system actions --------------------------------------------------

	_addSystemHere(at) {
		try {
			const path = ed.addSystem(this.project, { parent: this.system ?? '' });
			if (at) ed.setPosition(this.project, path, at);
			this._changed();
			this.hooks.onStatus?.(
				`Added ${path}. Right-click it to open, rename or dissolve it.`, 'info',
			);
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_addTransportHere(at) {
		try {
			const path = ed.addTransport(this.project, { parent: this.system ?? '', at });
			this._changed();
			this.hooks.onStatus?.(
				`Added transport ${path}: Begin, End, N and the counter i are inside. Draw `
				+ 'the transfers between Begin and End, connect the outside to them, and set N.',
				'info',
			);
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_addOperationTo(path, at = null) {
		try {
			const block = ed.addTransportOperation(this.project, {
				system: path, at: at ?? ed.freeSpotIn(this.project, path),
			});
			this._changed();
			const name = qualifiedName(block);
			this.hooks.onStatus?.(
				`Added ${name}: the mean over the chain. Its settings choose sum or mean, `
				+ 'and whether it is read by name or called with a position.', 'info',
			);
			this.hooks.onOpenSettings?.(name);
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_renameSystem(path) {
		const next = this.hooks.onPrompt
			? this.hooks.onPrompt(`Rename ${baseName(path)} to`, baseName(path))
			: null;
		if (!next || next === baseName(path)) return;
		try {
			const to = ed.renameSystem(this.project, path, next);
			this._changed();
			if (isWithin(this.system ?? '', path)) this.system = reparentSystem(this.system, path, to);
			this.hooks.onStatus?.(`Renamed to ${to}.`, 'info');
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_dissolveSystem(path) {
		try {
			const inside = ed.blocksIn(this.project, path, { deep: true }).length;
			ed.deleteSystem(this.project, path, { contents: 'move' });
			if (isWithin(this.system ?? '', path)) this.system = parentOf(path);
			this._changed();
			this.hooks.onStatus?.(
				`Dissolved ${baseName(path)}; its ${inside} block${inside === 1 ? '' : 's'} `
				+ `moved out.`, 'info',
			);
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	/**
	 * Makes a sub-system where the block already is, and moves it in.
	 *
	 * The name is asked for first: creating the sub-system and then finding
	 * out the question was cancelled would leave an empty one behind.
	 */
	_moveIntoNewSystem(names) {
		const wanted = Array.isArray(names) ? names : [names];
		const found = ed.findBlock(this.project, wanted[0]);
		if (!found) return;
		const here = systemOf(found.block);
		const suggested = ed.nextSystemName(this.project, here);
		const what = wanted.length === 1 ? found.block.name : `${wanted.length} blocks`;
		const typed = this.hooks.onPrompt
			? this.hooks.onPrompt(
				`Move ${what} into a new sub-system of `
				+ `${here || 'the top level'}, called`, suggested)
			: suggested;
		if (typed == null) return;

		try {
			const { system, moved, created } = ed.moveIntoNewSystem(this.project, wanted, typed);
			const to = [...moved.values()];
			this._pick(to);
			this._changed();
			const subject = to.length === 1 ? baseName(to[0]) : `${to.length} blocks`;
			this.hooks.onStatus?.(created
				? `${subject} ${to.length === 1 ? 'is' : 'are'} now in ${system}. `
					+ 'Double-click it to go in.'
				: `${system} already existed, so ${subject} went into that one.`,
			'info');
		} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
	}

	_connectTo(from, to) {
		try {
			const t = ed.addTransfer(this.project, from, to);
			const added = qualifiedName(t);
			this._select(added);
			this._changed();
			this.hooks.onSelect?.({ kind: 'transfer', name: added });
			this.hooks.onStatus?.(
				to ? `Connected ${from} to ${to}.` : `${from} now flows out of the model.`,
				'info',
			);
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	_addSourceTo(name) {
		try {
			// The source lives with the compartment it feeds, not with whatever
			// view happened to be open. `addSource` knows that rule; saying it
			// twice is how the two spellings drift apart.
			const s = ed.addSource(this.project, { to: name });
			const added = qualifiedName(s);
			this._select(added);
			this._changed();
			this.hooks.onSelect?.({ kind: 'inflow', name: added });
			this.hooks.onStatus?.(`Added ${s.name}, flowing into ${name}.`, 'info');
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	_moveEnd(name, end, target) {
		try {
			// Re-attaching the donor moves the transfer into that donor's
			// sub-system, so it may not be called what it was a moment ago.
			const conn = ed.setConnectionEnd(this.project, name, end, target);
			const now = qualifiedName(conn);
			this._select(now);
			this._changed();
			this.hooks.onStatus?.(
				`${now} now ${end === 'from' ? 'starts at' : 'ends at'} `
				+ `${target ?? 'outside the model'}.`
				+ (now === name ? '' : ` It moved with its donor, from ${name}.`),
				'info',
			);
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	/**
	 * Double-click opens the thing under the pointer: a block's settings, or a
	 * sub-system. A resize grip is the exception -- it returns the node to its
	 * default size, because that is undoing the grip's own doing.
	 *
	 * `ev.target` is not to be trusted here. Each of the two clicks began with
	 * a pointerdown that captured the pointer on the SVG root, and while a
	 * capture is in force every event derived from that pointer is retargeted
	 * to the capturing element -- so the double-click arrives with the root as
	 * its target, whatever was under the cursor. That is the same trap
	 * `_nodeAt` exists to avoid, and it is why double-clicking a sub-system did
	 * nothing: the branch that opens one never matched. The point is hit-tested
	 * instead.
	 *
	 * Empty space does nothing. It used to add a compartment, which made
	 * straightening a connection hazardous -- the bend handle is a small
	 * target, and a double-click that missed it left a stray compartment
	 * behind. Adding blocks belongs to the right-click menu, where it says what
	 * it will do before doing it.
	 */
	_onDblClick(ev) {
		if (!this.project) return;

		// The handles are not model nodes, so they are found in the document
		// rather than in the layout -- from the point, again, not the event.
		const under = document.elementFromPoint?.(ev.clientX, ev.clientY) ?? null;
		const at = (selector) => under?.closest?.(selector)
			?? ev.target?.closest?.(selector)
			?? null;

		// A resize grip returns the node to its default size. Checked first:
		// it sits on the node's own edge, so hit-testing the point would find
		// the node instead.
		const grip = at('[data-grip]');
		if (grip) {
			ed.clearBlockSize(this.project, grip.dataset.gripnode);
			this._changed({ layoutOnly: true });
			return;
		}

		// A connection opens its settings, the same as a box does. It used to
		// straighten instead, which made the gesture mean one thing on a line
		// and another on everything else -- and this menu had claimed `dbl`
		// opened Settings all along. Straightening is on the right-click menu,
		// where it says what it will do and does not compete with the only way
		// into a transfer's rate.
		// A pipe leads somewhere, so double-clicking it goes there -- the
		// sub-system the far block lives in, with that block selected. It is
		// the one mark on the diagram that stands for something you cannot
		// otherwise reach from here.
		const terminal = at('[data-terminal]');
		const goto = terminal?.dataset.goto;
		if (goto) {
			this.setSystem(parentOf(goto));
			this._select(goto);
			this.hooks.onStatus?.(
				`${baseName(goto)}, ${parentOf(goto) ? `in ${parentOf(goto)}` : 'at the top level'}.`,
				'info',
			);
			return;
		}

		const handle = at('[data-waypoint]');
		const edge = at('[data-edge]');
		const name = handle?.dataset.waypoint ?? edge?.dataset.edge
			?? terminal?.dataset.terminal ?? null;
		if (name) {
			if (ed.findBlock(this.project, name)) this.hooks.onOpenSettings?.(name);
			return;
		}

		// A sub-system opens; anything else opens its settings, which is what
		// double-clicking a thing with properties is expected to do.
		const node = this._nodeAt(this._toModel(ev));
		if (node?.kind === 'system') { this.setSystem(node.name); return; }
		if (node) { this.hooks.onOpenSettings?.(node.name); return; }

		// A shape has properties too, and until now double-clicking one did
		// nothing at all -- its settings were six submenus deep in its
		// right-click menu, one change per opening.
		const decor = at('[data-decor]');
		if (decor?.dataset.decor) this.openShapeSettings(decor.dataset.decor);
	}

	/**
	 * The settings of a shape, or of every shape picked if it is one of them.
	 *
	 * The dialog reads the shape back from the model on every refresh rather
	 * than holding a copy: `updateShape` bounds what it is given, and a field
	 * that went on showing what was typed after the model stored something
	 * else would be describing a shape that does not exist.
	 */
	openShapeSettings(id) {
		const ids = this.pickedShapes?.has?.(id) && this.pickedShapes.size > 1
			? [...this.pickedShapes] : [id];
		this.hooks.onShapeSettings?.({
			ids,
			read: () => {
				const found = ed.findShape(this.project, ids[0]);
				return found ? ed.readShape(found) : null;
			},
			apply: (patch) => {
				try {
					for (const each of ids) ed.updateShape(this.project, each, patch);
					this._changed({ layoutOnly: true });
				} catch (e) { this.hooks.onStatus?.(e.message, 'warn'); }
			},
		});
	}

	_onKey(ev) {
		// The three clipboard keys, on the canvas only: this listener is on the
		// SVG root, which has to have focus, so ⌘C over a text field is still
		// the browser's own.
		const mod = ev.metaKey || ev.ctrlKey;
		const key = ev.key.toLowerCase();

		// A node carries tabindex, role="button" and an aria-label, and until
		// now nothing behind them: Tab reached it, a screen reader announced a
		// button, and pressing it did nothing at all. Either the claims go or
		// the behaviour arrives, and the behaviour is worth having -- a
		// diagram that cannot be driven without a mouse puts half of what it
		// is for out of reach.
		if (!mod && (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar')) {
			const focused = document.activeElement?.closest?.('.gnode');
			const name = focused?.dataset?.name ?? this.selection?.name ?? null;
			if (name) {
				ev.preventDefault();
				this.hooks.onOpenSettings?.(name);
				return;
			}
		}
		if (!mod && NUDGE[ev.key] && this.picked.size) {
			ev.preventDefault();
			// One grid step, or one unit with Alt held -- the same bargain a
			// drag makes, and the modifier means the same thing there.
			const step = ev.altKey ? 1 : GRID;
			const [kx, ky] = NUDGE[ev.key];
			let moved = false;
			for (const name of this.picked) {
				const at = ed.getPosition(this.project, name);
				if (!at) continue;
				ed.setPosition(this.project, name, {
					x: at.x + kx * step, y: at.y + ky * step,
				});
				moved = true;
			}
			if (moved) this._changed({ layoutOnly: true });
			return;
		}
		// Copy format and Paste format, on the keys the drawing programs and
		// Google Docs use. By the key's place rather than its character:
		// Option turns C into ç on a Mac. First, because with Ctrl for the
		// Command key the plain copy below would take them.
		if (mod && ev.altKey && (ev.code === 'KeyC' || ev.code === 'KeyV')) {
			ev.preventDefault();
			const names = [...this.picked];
			if (ev.code === 'KeyC') {
				if (names.length !== 1) {
					this.hooks.onStatus?.('Copy format takes one block: select the one whose look you want.', 'warn');
					return;
				}
				this.hooks.onCopyFormat?.(names[0]);
			} else if (names.length) {
				this.hooks.onPasteFormat?.(names);
			}
			return;
		}
		if (mod && (key === 'c' || key === 'x')) {
			// Blocks and sub-systems alike: a sub-system is part of the
			// selection like anything else on the canvas.
			const names = [...this.picked];
			if (!names.length) return;
			ev.preventDefault();
			// The same rule the menu declines by, so ⌘C on a lone transfer
			// does nothing rather than copying something that cannot be
			// pasted.
			if (!ed.canTravel(this.project, names)) {
				this.hooks.onStatus?.('A connection cannot be copied on its own — '
					+ 'select the compartments at its ends as well.', 'warn');
				return;
			}
			if (key === 'c') this.hooks.onCopy?.(names);
			else this.hooks.onCut?.(names);
			return;
		}
		if (mod && key === 'v') {
			ev.preventDefault();
			// Into the middle of what is on screen: a keystroke has no point
			// on the canvas the way a right-click does.
			const r = this.root.getBoundingClientRect();
			this.hooks.onPaste?.({
				system: this.system ?? '',
				at: {
					x: (r.width / 2 - this.camera.x) / this.camera.k,
					y: (r.height / 2 - this.camera.y) / this.camera.k,
				},
			});
			return;
		}
		if ((ev.key === 'a' || ev.key === 'A') && (ev.metaKey || ev.ctrlKey)) {
			ev.preventDefault();
			this._pick(this._allNodeNames());
		} else if (ev.key === 'Delete' || ev.key === 'Backspace') {
			if (this.pickedShapes.size) {
				ev.preventDefault();
				this.deleteShapes([...this.pickedShapes]);
				return;
			}
			if (!this.picked.size) return;
			ev.preventDefault();
			this.deleteSelected();
		} else if (ev.key === 'Escape') {
			if (this.connect) { this._endConnect(); this.render(); return; }
			if (this._cancelDrag()) return;
			this._clearShapes();
			this._select(null);
		}
	}

	/**
	 * Abandons whatever gesture is in progress, from outside.
	 *
	 * Undo needs this: a drag writes to the model as the pointer moves, and
	 * one still in hand when the model is replaced would go on writing to the
	 * model that was replaced.
	 */
	cancelGesture() {
		if (this.connect) { this._endConnect(); this.render(); return true; }
		return this._cancelDrag();
	}

	/**
	 * Abandons whatever gesture is in progress, putting back what it moved.
	 *
	 * Escape used to cancel two of the nine: drawing a connection, and
	 * re-attaching one. Everything else -- moving blocks, moving shapes,
	 * resizing either, bending a line, dragging a loose end, sweeping a
	 * selection box, panning -- carried on to its release and committed,
	 * because each of them writes to the model as the pointer moves rather
	 * than at the end. So Escape did nothing about the thing it is for, and a
	 * drag begun by accident had to be undone by hand.
	 *
	 * Each gesture records what to put back when it begins; this runs it.
	 *
	 * @returns {boolean} whether there was a gesture to cancel.
	 */
	_cancelDrag() {
		if (this.drag?.kind === 'reconnect') { this._endReconnect(); this.render(); return true; }
		const drag = this.drag;
		if (!drag) return false;
		// Nothing to put back for a gesture that never went anywhere: a press
		// and a release in the same place is a click, and it is handled as
		// one on release. A pan has no `moved` flag and always has something
		// to put back.
		if (drag.moved !== false || drag.kind === 'pan') drag.undo?.();
		this._endDrag();
		this.render();
		return true;
	}

	/**
	 * Removes shapes.
	 *
	 * No confirmation, unlike a block: nothing in the model refers to a shape,
	 * so nothing else changes, and it is a moment's work to draw another. A
	 * block deletion asks because it can take connections with it.
	 */
	deleteShapes(ids) {
		const gone = ed.deleteShapes(this.project, ids);
		if (!gone) return;
		this.pickedShapes.clear();
		this._changed({ layoutOnly: true });
		this.hooks.onStatus?.(
			`Removed ${gone} shape${gone === 1 ? '' : 's'}.`, 'info',
		);
	}

	deleteSelected() {
		const names = [...this.picked];
		if (!names.length) return;
		const parts = ed.selectionParts(this.project, names);
		const inside = parts.systems.reduce(
			(n, p) => n + ed.blocksIn(this.project, p, { deep: true }).length, 0,
		);
		// Said now, while the names still name something: worked out after the
		// edit, "3 blocks and a sub-system" came back as "nothing".
		const naming = this._what(names);
		// A sub-system stands for everything inside it, and what goes with it
		// is not on the screen to be looked at first, so this is the one
		// delete here that asks. Blocks on their own do not: what goes is what
		// is highlighted, you can see all of it, and Cmd+Z brings it back.
		if (parts.systems.length && this.hooks.onConfirm) {
			const ok = this.hooks.onConfirm(
				`Delete ${naming} and the ${inside} block`
				+ `${inside === 1 ? '' : 's'} inside?`,
			);
			if (!ok) return;
		}
		try {
			const r = ed.deleteSelection(this.project, names);
			this._select(null);
			this._changed();
			// The difference between the counts is the connections that could
			// not outlive an endpoint, which went unasked.
			const extra = r.removed.length - parts.blocks.length - inside;
			const what = !parts.systems.length && parts.blocks.length === 1
				? `Deleted ${parts.blocks[0]}`
				: `Deleted ${naming}`
					+ (inside
						? `, with the ${inside} block${inside === 1 ? '' : 's'} inside`
						: '');
			this.hooks.onStatus?.(
				`${what}${extra > 0
					? ` and ${extra} attached connection${extra === 1 ? '' : 's'}`
					: ''}.`,
				'info',
			);
		} catch (e) {
			this.hooks.onStatus?.(e.message, 'warn');
		}
	}

	/**
	 * The wheel zooms, about wherever the pointer is.
	 *
	 * `deltaY` has to be read together with `deltaMode`, which is the whole
	 * difference between a trackpad and a mouse. A trackpad reports pixels --
	 * a hundred or so per gesture -- while a wheel reports *lines*, three per
	 * notch. Taking the number at face value made one notch worth three
	 * pixels, a zoom of half a percent, so on a mouse the canvas looked as
	 * though it did not zoom at all.
	 */
	_onWheel(ev) {
		ev.preventDefault();
		const r = this.root.getBoundingClientRect();
		// Clamped into the canvas: with the whole tab taking the wheel the
		// pointer may be over the frame around it, and a focal point outside
		// the viewport would send the diagram sideways instead of zooming it.
		const cx = Math.min(Math.max(ev.clientX - r.left, 0), r.width);
		const cy = Math.min(Math.max(ev.clientY - r.top, 0), r.height);
		const factor = Math.exp(-wheelPixels(ev.deltaY, ev.deltaMode, r.height) * 0.0015);
		const k = Math.min(2.5, Math.max(0.25, this.camera.k * factor));
		this.camera.x = cx - ((cx - this.camera.x) * k) / this.camera.k;
		this.camera.y = cy - ((cy - this.camera.y) * k) / this.camera.k;
		this.camera.k = k;
		this._applyView();
	}

	/**
	 * Selects a sub-system.
	 *
	 * Not a block, so nothing that edits blocks acts on it -- but it is a node
	 * on the canvas and a row in the tree, so it is a thing you can pick, and
	 * it can be part of a selection of several.
	 */
	_selectSystem(path) {
		this._select(path);
	}

	/** Selects one thing, dropping whatever else was selected. */
	/** Picks one shape, and only it. */
	_selectShape(id) {
		// The two selections are exclusive: a menu, a Del or an inspector that
		// had to cope with both at once would be guessing at which was meant.
		if (this.picked.size || this.selection) {
			this.picked.clear();
			this.selection = null;
			this.hooks.onSelect?.(null);
		}
		this.pickedShapes = new Set([id]);
		this._applySelection();
		this._applyDecorSelection();
	}

	_pickShapeToggle(id) {
		if (this.picked.size || this.selection) {
			this.picked.clear();
			this.selection = null;
			this.hooks.onSelect?.(null);
		}
		if (this.pickedShapes.has(id)) this.pickedShapes.delete(id);
		else this.pickedShapes.add(id);
		this._applySelection();
		this._applyDecorSelection();
	}

	/** Drops the shape selection, when a block is being picked instead. */
	_clearShapes() {
		if (!this.pickedShapes.size) return;
		this.pickedShapes.clear();
		this._applyDecorSelection();
	}

	_select(name) {
		if (name == null) {
			this._clearShapes();
			this.picked.clear();
			this.selection = null;
			this._applySelection();
			this.hooks.onSelect?.(null, []);
			return;
		}
		this._pick([name], name);
	}

	/** Whether a name is something this diagram can select: a block or a sub-system. */
	_selectable(name) {
		return !!ed.findBlock(this.project, name)
			|| (!!name && ed.systems(this.project).includes(name));
	}

	/**
	 * Selects a set of blocks and sub-systems.
	 *
	 * `primary` is the one the inspector shows -- the last one clicked, since
	 * that is the one the eye is on. Names that are neither a block nor a
	 * sub-system are dropped, so a selection that has outlived what it named
	 * settles to whatever is still there.
	 */
	_pick(names, primary = null) {
		this._clearShapes();
		const keep = [...new Set(names)].filter((n) => this._selectable(n));
		this.picked = new Set(keep);
		const head = primary && this.picked.has(primary) ? primary : keep[keep.length - 1] ?? null;
		this.selection = head
			? { kind: ed.findBlock(this.project, head)?.kind ?? 'system', name: head }
			: null;
		this._applySelection();
		this.hooks.onSelect?.(this.selection, [...this.picked]);
	}

	/** Adds something to the selection, or takes it back out. */
	_pickToggle(name) {
		if (!this._selectable(name)) return;
		const next = new Set(this.picked);
		if (next.has(name)) next.delete(name);
		else next.add(name);
		this._pick([...next], next.has(name) ? name : null);
	}

	/** Everything drawn on this diagram, the sub-systems among it. */
	_allNodeNames() {
		return this._nodes().map((n) => n.name);
	}

	/**
	 * An edit was made here: tell the host, and make sure the diagram shows it.
	 *
	 * The host normally re-renders this diagram as part of handling the
	 * change -- `renderEditorViews` calls `setProject`, which renders -- so
	 * rendering here first drew the whole thing twice on every edit, nodes,
	 * edges, influence links and all. Rendering afterwards, and only if the
	 * host did not, needs no promise from the host: the counter says whether
	 * it happened.
	 */
	_changed(opts = {}) {
		const before = this._renders;
		try {
			this.hooks.onChange?.(opts);
		} finally {
			if (this._renders === before) this.render();
		}
	}

	// --- view helpers -------------------------------------------------------

	zoomBy(factor) {
		const r = this.root.getBoundingClientRect();
		const cx = r.width / 2, cy = r.height / 2;
		const k = Math.min(2.5, Math.max(0.25, this.camera.k * factor));
		this.camera.x = cx - ((cx - this.camera.x) * k) / this.camera.k;
		this.camera.y = cy - ((cy - this.camera.y) * k) / this.camera.k;
		this.camera.k = k;
		this._applyView();
	}

	/**
	 * Brings named blocks to the middle of the canvas, at the zoom they are at.
	 *
	 * Fit answers "show me everything"; this answers "show me *this*", which on
	 * a diagram of four hundred blocks is a different question -- fitting to
	 * all of them makes each one four pixels across, and the block you were
	 * looking for is now somewhere in that. The zoom is left alone for the same
	 * reason: what is wanted is the part of the diagram this block is in, drawn
	 * at the size the rest of it is being read at.
	 *
	 * A block in a sub-system that is not the one on screen means going in
	 * first -- the canvas draws one sub-system at a time, so there is no
	 * scrolling to a block that is not on it.
	 *
	 * A connection is not a node. It is the arrow between two, so what is
	 * centred is the two ends together, which puts the arrow in the middle.
	 *
	 * @param {string|string[]} what  block or sub-system names
	 * @returns {boolean} whether there was anything to centre on
	 */
	centreOn(what) {
		const names = Array.isArray(what) ? what : [what];
		if (!names.length || !this.project) return false;

		// Whichever sub-system the first of them lives in. A selection
		// spanning two cannot be shown at once, so the first one decides and
		// the rest are centred on as far as they are on that canvas.
		const home = this._homeOf(names[0]);
		if (home !== (this.system ?? '')) this.setSystem(home);

		const nodes = this._nodeMap();
		const box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
		const take = (n) => {
			if (!n) return;
			box.x0 = Math.min(box.x0, n.x);
			box.y0 = Math.min(box.y0, n.y);
			box.x1 = Math.max(box.x1, n.x + n.w);
			box.y1 = Math.max(box.y1, n.y + n.h);
		};
		for (const name of names) {
			if (nodes.has(name)) { take(nodes.get(name)); continue; }
			// A connection, or a sub-system drawn as the box its blocks are
			// in: both are stood for by the nodes they join or hold.
			for (const end of this._standsFor(name)) take(nodes.get(end));
		}
		if (!Number.isFinite(box.x0)) return false;

		const r = this.root.getBoundingClientRect();
		if (!r.width) return false;
		const { k } = this.camera;
		this.camera.x = r.width / 2 - ((box.x0 + box.x1) / 2) * k;
		this.camera.y = r.height / 2 - ((box.y0 + box.y1) / 2) * k;
		this._applyView();
		return true;
	}

	/** The sub-system whose canvas a name is drawn on. */
	_homeOf(name) {
		if (ed.systems(this.project).includes(name)) return parentOf(name);
		const found = ed.findBlock(this.project, name);
		return found ? systemOf(found.block) : (this.system ?? '');
	}

	/** The nodes a name is drawn as, for something that is not itself a node. */
	_standsFor(name) {
		if (ed.systems(this.project).includes(name)) return [name];
		const found = ed.findBlock(this.project, name);
		if (!found) return [];
		if (found.kind === 'transfer' || found.kind === 'inflow') {
			return [found.block.from, found.block.to].filter(Boolean);
		}
		return [name];
	}

	fit() {
		const nodes = [...this._nodeMap().values()];
		const r = this.root.getBoundingClientRect();
		// A canvas can hold shapes and no blocks -- a sub-system being drawn
		// before it is built -- and fitting to nothing left it off screen.
		const drawn = ed.shapesBox(ed.shapesIn(this.project, this.system ?? ''));
		if ((!nodes.length && !drawn) || !r.width) return;
		// Parallel transfers bow out to either side of the line between their
		// compartments, so a bundle needs room the nodes alone do not ask for.
		const bow = bundleOffsets(this.project.transfers ?? []).size ? BUNDLE_GAP : 0;
		// Read off what is drawn rather than worked out again: a diagram
		// inside a sub-system needs room for a pipe tag beside every node, and
		// one at the top level of a flat model needs no more than it ever did.
		const room = this.edgeLayer.querySelector('.gpipe') ? PIPE_ROOM : TERMINAL_ROOM;
		let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
		for (const n of nodes) {
			x0 = Math.min(x0, n.x - room);
			y0 = Math.min(y0, n.y - 20 - bow);
			x1 = Math.max(x1, n.x + n.w + room);
			y1 = Math.max(y1, n.y + n.h + 40 + bow);
		}
		if (drawn) {
			x0 = Math.min(x0, drawn.x0 - 20);
			y0 = Math.min(y0, drawn.y0 - 20);
			x1 = Math.max(x1, drawn.x1 + 20);
			y1 = Math.max(y1, drawn.y1 + 20);
		}
		const pad = 28;
		const k = Math.min(
			1.4,
			Math.max(0.25, Math.min(
				(r.width - pad * 2) / Math.max(1, x1 - x0),
				(r.height - pad * 2) / Math.max(1, y1 - y0),
			)),
		);
		this.camera.k = k;
		this.camera.x = (r.width - (x1 - x0) * k) / 2 - x0 * k;
		this.camera.y = (r.height - (y1 - y0) * k) / 2 - y0 * k;
		this._applyView();
	}

	relayout() {
		// Drop bend points too: they were placed against the old positions.
		for (const key of Object.keys(this.project.layout ?? {})) {
			delete this.project.layout[key];
		}
		ed.autoLayout(this.project);
		this._placeLooseNodes();
		this._changed({ layoutOnly: true });
		this.fit();
	}
}

// --- geometry --------------------------------------------------------------

/**
 * How far the pointer must travel before a press counts as a drag.
 *
 * A press that does not move is a click, and a click has to leave the diagram
 * untouched: re-rendering it, or so much as reordering the node under the
 * pointer, loses the browser's `click` and with it the `dblclick` that opens a
 * sub-system.
 */
const DRAG_SLOP = 3;

// The wheel rule is shared with the chart, which zooms the same way and has
// no business importing a graph editor to find out how. Re-exported here
// because everything that reads a wheel on the diagram is in this file.
export { wheelPixels } from './wheel.js';

/**
 * Whether an event asks to add to the selection rather than replace it.
 *
 * Shift because that is what every list in every application uses, and the
 * platform modifier as well because a diagram is not a list and both habits
 * turn up. Neither is used for anything else on this canvas.
 */
const additive = (ev) => ev.shiftKey || ev.metaKey || ev.ctrlKey;

/** The selection box as a rectangle, whichever corner it was started from. */
const marqueeBox = (d) => ({
	x: Math.min(d.x0, d.x1),
	y: Math.min(d.y0, d.y1),
	w: Math.abs(d.x1 - d.x0),
	h: Math.abs(d.y1 - d.y0),
});

/**
 * Whether a node is caught by the box.
 *
 * Touching is enough -- a box has to be dragged right around a node to select
 * it in some editors, which turns picking six blocks out of a crowded diagram
 * into an exercise in aim.
 */
const overlaps = (n, box) => n.x < box.x + box.w && n.x + n.w > box.x
	&& n.y < box.y + box.h && n.y + n.h > box.y;

const centreOf = (n) => ({
	x: n.x + (n.w ?? NODE_W) / 2,
	y: n.y + (n.h ?? NODE_H) / 2,
});

/**
 * Where an edge should leave one node and enter another.
 *
 * Edges attach to the outline rather than the centre, so a diagram reads as
 * boxes joined by pipes instead of a star of straight lines. The attachment
 * point comes from the node's own shape and size, which is why every node
 * carries both.
 */
function anchors(a, b, waypoint) {
	const ca = centreOf(a);
	const cb = centreOf(b);
	return [
		sidePoint(a, ca, waypoint ?? cb),
		sidePoint(b, cb, waypoint ?? ca),
	];
}

function sidePoint(node, centre, towards) {
	const w = node.w ?? NODE_W;
	const h = node.h ?? NODE_H;
	const shape = node.shape ?? 'rounded';
	const dx = towards.x - centre.x;
	const dy = towards.y - centre.y;

	const local = borderPoint(shape, w, h, dx, dy);
	// A step outside the outline so the arrowhead is not swallowed by it.
	const px = node.x + local.x;
	const py = node.y + local.y;
	const len = Math.hypot(dx, dy) || 1;
	return { x: px + (dx / len) * 1.5, y: py + (dy / len) * 1.5 };
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

/**
 * A cubic Bezier between two anchors, with control points pushed along the
 * direction each end faces. `bothEnds` is false for an open-ended transfer,
 * which gets a gentler curve so its terminal bar stays legible.
 */
function curve(p0, p1, bothEnds = true) {
	const dx = p1.x - p0.x;
	const dy = p1.y - p0.y;
	const dist = Math.hypot(dx, dy);
	if (dist < 1) return `M ${p0.x} ${p0.y} L ${p1.x} ${p1.y}`;

	// Reach grows with distance but is capped, so long edges do not balloon.
	const reach = clamp(dist * (bothEnds ? 0.42 : 0.3), 26, 150);
	const horizontal = Math.abs(dx) >= Math.abs(dy);

	// An edge running right-to-left needs a wider sweep to avoid doubling back
	// through its own node.
	const back = horizontal && dx < 0 ? 1.7 : 1;

	const c0 = horizontal
		? { x: p0.x + Math.sign(dx || 1) * reach * back, y: p0.y }
		: { x: p0.x, y: p0.y + Math.sign(dy || 1) * reach };
	const c1 = horizontal
		? { x: p1.x - Math.sign(dx || 1) * reach * back, y: p1.y }
		: { x: p1.x, y: p1.y - Math.sign(dy || 1) * reach };

	return `M ${p0.x} ${p0.y} C ${c0.x} ${c0.y} ${c1.x} ${c1.y} ${p1.x} ${p1.y}`;
}

/** A quadratic that passes exactly through `w`, so the handle sits on the line. */
/**
 * Transfers sharing a pair of compartments, and how far off the straight line
 * each should be drawn.
 *
 * The pair is unordered, so a transfer and its counter-transfer separate too --
 * A to B and B to A otherwise trace the same curve with the arrows at opposite
 * ends. Offsets are measured in a canonical frame, from the lexicographically
 * smaller endpoint to the larger, so which way round a particular transfer runs
 * does not move it; `forward` records which frame it is in.
 *
 * A pair with one transfer gets no entry at all, so the ordinary single
 * connection keeps the curve it has always had.
 */
export function bundleOffsets(transfers, hasNode = () => true) {
	const groups = new Map();
	for (const t of transfers) {
		if (!t.from || !t.to || !hasNode(t.from) || !hasNode(t.to)) continue;
		const forward = t.from < t.to;
		const key = forward ? `${t.from}\u0000${t.to}` : `${t.to}\u0000${t.from}`;
		if (!groups.has(key)) groups.set(key, []);
		groups.get(key).push({ name: qualifiedName(t), forward });
	}

	const out = new Map();
	for (const list of groups.values()) {
		if (list.length < 2) continue;
		// Wide enough to read apart, but a bundle of eight should not push the
		// outermost pair halfway across the diagram.
		const spread = Math.min(BUNDLE_GAP, 120 / (list.length - 1));
		list.forEach((c, i) => out.set(c.name, {
			// Centred on the line a single transfer would have taken, so
			// adding a second moves both rather than displacing the diagram
			// around the first.
			offset: (i - (list.length - 1) / 2) * spread,
			forward: c.forward,
		}));
	}
	return out;
}

/**
 * Where a transfer's curve should pass so that it clears the others joining the
 * same two compartments: the midpoint, pushed sideways.
 */
export
function bundlePoint(a, b, bundle) {
	if (!bundle || !a || !b) return null;
	const ca = centreOf(a);
	const cb = centreOf(b);
	const dx = cb.x - ca.x;
	const dy = cb.y - ca.y;
	const len = Math.hypot(dx, dy) || 1;
	// The perpendicular is taken along this transfer's own direction, so the
	// sign is flipped for the ones running the other way to keep every member
	// of the bundle in the same frame.
	const side = bundle.forward ? 1 : -1;
	const off = bundle.offset * side;
	return {
		x: (ca.x + cb.x) / 2 - (dy / len) * off,
		y: (ca.y + cb.y) / 2 + (dx / len) * off,
	};
}

function quadThrough(p0, p1, w) {
	const cx = 2 * w.x - (p0.x + p1.x) / 2;
	const cy = 2 * w.y - (p0.y + p1.y) / 2;
	return `M ${p0.x} ${p0.y} Q ${cx} ${cy} ${p1.x} ${p1.y}`;
}

/** The point at t = 0.5 of the rendered path, where the label and handle go. */
function midOf(p0, p1, bothEnds = true) {
	const dx = p1.x - p0.x;
	const dy = p1.y - p0.y;
	const dist = Math.hypot(dx, dy);
	if (dist < 1) return { x: p0.x, y: p0.y };

	const reach = clamp(dist * (bothEnds ? 0.42 : 0.3), 26, 150);
	const horizontal = Math.abs(dx) >= Math.abs(dy);
	const back = horizontal && dx < 0 ? 1.7 : 1;
	const c0 = horizontal
		? { x: p0.x + Math.sign(dx || 1) * reach * back, y: p0.y }
		: { x: p0.x, y: p0.y + Math.sign(dy || 1) * reach };
	const c1 = horizontal
		? { x: p1.x - Math.sign(dx || 1) * reach * back, y: p1.y }
		: { x: p1.x, y: p1.y - Math.sign(dy || 1) * reach };

	// Cubic at t = 0.5.
	return {
		x: (p0.x + 3 * c0.x + 3 * c1.x + p1.x) / 8,
		y: (p0.y + 3 * c0.y + 3 * c1.y + p1.y) / 8,
	};
}

/**
 * Truncates to what will fit a given pixel width.
 *
 * Node text used to be clipped at a fixed character count, which is wrong once
 * a node can be any width. `perChar` is an approximate advance for the font
 * size in use -- close enough, and far cheaper than measuring.
 */
function fitText(text, widthPx, perChar) {
	const t = String(text ?? '');
	const max = Math.max(1, Math.floor(widthPx / perChar));
	return t.length <= max ? t : `${t.slice(0, Math.max(1, max - 1))}…`;
}

function truncate(s, n) {
	const t = String(s ?? '');
	return t.length <= n ? t : `${t.slice(0, n - 1)}…`;
}

/** CSS.escape is not in every environment the tests run in. */
function cssEscape(s) {
	if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(s);
	return String(s).replace(/["\\]/g, '\\$&');
}

export { NODE_W, NODE_H };
