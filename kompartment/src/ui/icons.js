/**
 * The little glyph beside a block's name in the tree.
 *
 * A tree of blocks needs a glyph per block type, and the usual answer is a
 * folder of 16-pixel images. These are the same idea as geometry rather than
 * as bitmaps -- each icon is the shape the diagram draws that block with, in
 * the colour it fills it with,
 * so the thing in the tree looks like the thing on the canvas and neither has
 * to be learned twice.
 *
 * Shape carries the family and colour separates the members, exactly as on the
 * diagram. Where a family shares both -- min/max, running mean and snapshot
 * are one shape -- a mark inside it tells them apart, which is the job the
 * subtitle does on a node.
 */

import { shapePath, shapeDecoration } from './shapes.js';

const NS = 'http://www.w3.org/2000/svg';

/** The icon box, and the shape drawn inside it. */
const BOX = 16;
const W = 14;
const H = 11;
const OX = (BOX - W) / 2;
const OY = (BOX - H) / 2;

/**
 * The shapes are built at four times the icon and scaled down.
 *
 * Their proportions are not all scale-free: a rounded box has a corner radius
 * of 7 units whatever size the box is, so at 14 by 11 a compartment came out
 * as a stadium rather than as the gently rounded box the diagram draws. Built
 * at 56 by 44 and scaled, the curve is the one on the canvas.
 */
const S = 4;

/**
 * A mark drawn inside the shape, in the coordinates of the shape itself
 * (0..14 across, 0..11 down). Strokes only: a fill would fight the body
 * colour, and these are read at a glance rather than studied.
 */
const MARKS = {
	// An expression is an equals sign: this block *is* its equation.
	equals: 'M 4.5 4 H 9.5 M 4.5 7 H 9.5',
	// A lookup table is the shape of its own curve.
	curve: 'M 3 8 L 5.5 5 L 7.5 6.5 L 11 2.8',
	// An index operation collapses an index away: many in, one out.
	funnel: 'M 3 2.5 L 10.5 5.5 M 3 5.5 H 10.5 M 3 8.5 L 10.5 5.5',
	// An aggregate adds several blocks together.
	plus: 'M 4.5 5.5 H 9.5 M 7 3 V 8',
	// A min/max holds the turning point of what it watches.
	peak: 'M 3 8.5 L 7 2.8 L 11 8.5',
	// A running mean is the level a wandering signal averages to.
	mean: 'M 3 4.2 q 2 -2.6 4 0 q 2 2.6 4 0 M 3 8 H 11',
	// A snapshot is one instant of it: the moment, and the value taken there.
	sample: 'M 7 2 V 9',
	// A transport is a chain of compartments: two cells and the link between
	// them, with the chain running on past the second. Cells rather than the
	// three plain dashes this was, which on a node read as a dashed line
	// rather than as a row of boxes.
	chain: 'M 2.2 7.9 h 3.1 v 3.1 h -3.1 Z M 5.3 9.45 h 1.5 '
		+ 'M 6.8 7.9 h 3.1 v 3.1 h -3.1 Z M 9.9 9.45 h 1.5 M 11.4 9.45 h 1.6',
	// A user-defined function: the two brackets it is called with, which is
	// the one thing on screen that says "this is called, not read".
	brackets: 'M 5.6 2.6 q -2 3 0 6 M 8.4 2.6 q 2 3 0 6',
	// A far-field path: the fracture down the middle, and the rock matrix it
	// diffuses into on either side.
	fracture: 'M 7 1.6 V 10.4 M 4.4 3.2 H 5.4 M 8.6 3.2 H 9.6 '
		+ 'M 4.4 6 H 5.4 M 8.6 6 H 9.6 M 4.4 8.8 H 5.4 M 8.6 8.8 H 9.6',
	// Waste packages: a canister, standing, with the two bands of a drum.
	canister: 'M 4.4 2.4 H 9.6 V 9.6 H 4.4 Z M 4.4 4.8 H 9.6 M 4.4 7.2 H 9.6',
	// A disruptive event: a bolt -- something happens, at an instant.
	bolt: 'M 7.8 1.8 L 4.6 6.6 H 7 L 6.2 10.4 L 9.4 5.6 H 7 Z',
	// A trigger is a threshold: something runs along, crosses a level, and
	// from there on everything is different. Drawn as the step itself, which
	// is the one thing that separates it from the bolt beside it -- a
	// disruptive event *happens*, a trigger *is crossed*.
	step: 'M 2.5 8.5 H 6.5 V 3.5 H 11.5',
};

/**
 * The mark for a kind, in its own 14 x 11 box, or null where a kind has none.
 *
 * Exported because the diagram wants the same glyph the tree uses. A far-field
 * pathway, a waste package and the three blocks that remember are all drawn as
 * rectangles, and a rectangle says only that this is not a compartment: the
 * mark is what says *which* of them it is, and learning it once in the tree
 * should be enough to read it on the canvas.
 */
export function markPath(kind) {
	const mark = KIND_ICON[kind]?.mark;
	return mark ? MARKS[mark] : null;
}

/** The box `markPath` draws in. */
export const MARK_W = W;
export const MARK_H = H;

/** A mark that is filled rather than stroked, drawn over the mark above. */
const DOTS = {
	peak: [7, 2.8, 1.15],
	sample: [7, 5.5, 1.7],
};

/**
 * Every kind of block, by the shape and colour the diagram gives it.
 *
 * `tone` names a CSS class, not a colour, so the icons follow the theme the
 * same way the diagram does.
 */
export const KIND_ICON = {
	compartment: { shape: 'rounded', tone: 'compartment' },
	expression: { shape: 'rounded', tone: 'expression', mark: 'equals' },
	parameter: { shape: 'hexagon', tone: 'parameter' },
	lookup: { shape: 'rect', tone: 'lookup', mark: 'curve' },
	index_reduction: { shape: 'rounded', tone: 'reduction', mark: 'funnel' },
	block_reduction: { shape: 'rounded', tone: 'block_reduction', mark: 'plus' },
	// Not a box on any diagram -- a function has no value to draw -- but it
	// is in the tree and the panels, and needs to be told apart there.
	function: { shape: 'rounded', tone: 'expression', mark: 'brackets' },
	min_max: { shape: 'rect', tone: 'recorder', mark: 'peak' },
	running_mean: { shape: 'rect', tone: 'recorder', mark: 'mean' },
	snapshot: { shape: 'rect', tone: 'recorder', mark: 'sample' },
	delay: { shape: 'cylinder', tone: 'delay' },
	trigger: { shape: 'diamond', tone: 'event', mark: 'step' },
	// A far-field path is a whole transport model, so it is drawn as the thing
	// it models: a fracture with rock either side of it.
	farfield: { shape: 'rect', tone: 'farfield', mark: 'fracture' },
	// Waste packages are drawn as the thing they are: a canister that fails.
	waste_package: { shape: 'rect', tone: 'waste', mark: 'canister' },
	// A disruptive event is an instant, like a discrete event, and wears its
	// diamond; the bolt says it moves mass rather than watches for a crossing.
	event: { shape: 'diamond', tone: 'event', mark: 'bolt' },
	// A transfer and a source are edges on the diagram, not boxes, so they are
	// drawn as what they are: an arrow, and an arrow out of the world outside.
	transfer: { shape: 'arrow', tone: 'flow' },
	inflow: { shape: 'arrow', tone: 'flow', outside: true },
	// A sub-system is a container, and the tab is the same one the diagram
	// draws on the box you can open.
	system: { shape: 'folder', tone: 'system' },
	// A transport is a sub-system that is also a block, so it keeps the
	// container's shape and wears the chain it runs as, in the transport's
	// own colour.
	transport: { shape: 'folder', tone: 'transport', mark: 'chain' },
};

const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(NS, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/** The arrow a transfer is drawn as, in the icon's own coordinates. */
function arrow(g, outside) {
	const y = BOX / 2;
	const tail = outside ? 4.5 : 1.5;
	if (outside) {
		// Out of nowhere: the open circle is the world beyond the model, the
		// same thing the matrix calls `outside`.
		g.append(svg('circle', { class: 'bicon-body', cx: 2.6, cy: y, r: 2.1 }));
	}
	g.append(svg('path', { class: 'bicon-mark', d: `M ${tail} ${y} H 11` }));
	g.append(svg('path', { class: 'bicon-head', d: `M 14.5 ${y} L 10 ${y - 2.6} V ${y + 2.6} Z` }));
}

/** A folder, for a sub-system: the tab says it opens. */
function folder(g) {
	g.append(svg('path', {
		class: 'bicon-body',
		d: 'M 1 3.5 h 4.6 l 1.4 1.8 H 15 V 13 H 1 Z',
	}));
}

/**
 * @param {string} kind a block kind, or `system`
 * @param {{title?: string}} [opts]
 * @returns {SVGSVGElement} a 16x16 icon
 */
export function blockIcon(kind, { title = null } = {}) {
	const spec = KIND_ICON[kind] ?? { shape: 'rounded', tone: 'plain' };
	const g = svg('svg', {
		class: `bicon bicon-${spec.tone}`,
		viewBox: `0 0 ${BOX} ${BOX}`,
		width: BOX,
		height: BOX,
		'aria-hidden': title ? 'false' : 'true',
		focusable: 'false',
	});
	if (title) {
		const t = svg('title', {});
		t.textContent = title;
		g.append(t);
	}

	if (spec.shape === 'arrow') {
		arrow(g, spec.outside);
		return g;
	}
	if (spec.shape === 'folder') {
		folder(g);
		if (spec.mark) g.append(svg('path', { class: 'bicon-mark', d: MARKS[spec.mark] }));
		return g;
	}

	const body = svg('g', { transform: `translate(${OX} ${OY}) scale(${1 / S})` });
	body.append(svg('path', {
		class: 'bicon-body', d: shapePath(spec.shape, W * S, H * S),
		'vector-effect': 'non-scaling-stroke',
	}));
	const decor = shapeDecoration(spec.shape, W * S, H * S);
	if (decor) {
		body.append(svg('path', {
			class: 'bicon-decor', d: decor, 'vector-effect': 'non-scaling-stroke',
		}));
	}
	g.append(body);

	// The marks are drawn at icon size: they are legible at 11 pixels only
	// because they were designed there.
	if (spec.mark) {
		const inner = svg('g', { transform: `translate(${OX} ${OY})` });
		inner.append(svg('path', { class: 'bicon-mark', d: MARKS[spec.mark] }));
		const dot = DOTS[spec.mark];
		if (dot) inner.append(svg('circle', { class: 'bicon-dot', cx: dot[0], cy: dot[1], r: dot[2] }));
		g.append(inner);
	}
	return g;
}
