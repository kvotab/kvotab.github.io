/**
 * The shapes a diagram can be annotated with.
 *
 * Nothing here is part of the model. A compartment model says what flows where
 * and at what rate; it cannot say "this half of the diagram is the near field",
 * or draw the lake the four compartments in the corner stand for. That is what
 * these are: a box to group things in, an arrow to point with, and a small
 * dictionary of the things a radioecological model is usually *about* -- a
 * tree, a well, a house, a canister -- so a diagram can be read by someone who
 * was not in the room when it was built.
 *
 * They are drawn behind the blocks, they take no part in the equations, and
 * they are saved with the model because a drawing that vanished on reload
 * would not be worth making.
 *
 * WHY UNIT COORDINATES. Every figure is written in the unit square -- `0,0` to
 * `1,1` -- and scaled to the shape's own width and height when it is drawn.
 * The alternative, one `100 x 100` drawing under an SVG `scale()`, distorts the
 * strokes with the box: a wide, short rectangle would come out with thick
 * uprights and thin rails. Scaling the *numbers* keeps every line the width it
 * says it is, at any shape of box, and lets the camera scale them like
 * everything else on the canvas.
 *
 * The few figures whose geometry cannot survive a non-uniform scale at all --
 * an arrow's head would be sheared into a wedge -- carry a `build(w, h)`
 * instead and work it out properly.
 */

/** Which fill and which stroke a part of a figure takes. */
export const ROLES = {
	// The figure itself: the fill colour, outlined in the line colour.
	body: { fill: 'fill', stroke: 'line' },
	// A line, a wave, a stalk: no fill, whatever the fill colour is.
	line: { fill: 'none', stroke: 'line' },
	// A solid detail -- a trunk, a window, an arrow's head -- in the line
	// colour, because it reads as drawn rather than as filled.
	ink: { fill: 'line', stroke: 'none' },
	// A second filled area, in the fill colour but undrawn: water in a lake.
	tint: { fill: 'fill', stroke: 'none' },
	// The three a sticky note is made of. They exist because a note is the one
	// figure that is meant to look like an object lying on the canvas rather
	// than a drawing on it: `paper` is opaque where `body` is a tint, `shade`
	// is the shadow it casts, and `fold` is the underside of its turned-up
	// corner. All three take their colour from the shape's own fill, so the
	// note is still whichever colour was chosen. See app.css.
	shade: { fill: 'fill', stroke: 'none' },
	paper: { fill: 'fill', stroke: 'line' },
	fold: { fill: 'fill', stroke: 'none' },
};

/**
 * Multiplies a path written in the unit square out to a real size.
 *
 * Only absolute commands, and only the ones whose arguments are points, so
 * that scaling is a matter of knowing how many numbers each command takes:
 * `A` is deliberately absent -- its radii and flags are not coordinates, and
 * one of the flags is a number that must not be touched -- and every curve
 * here is written as a Bézier instead.
 */
export function scalePath(d, w, h) {
	const runs = { M: 2, L: 2, T: 2, C: 6, S: 4, Q: 4, H: 1, V: 1, Z: 0 };
	const out = [];
	// A command, then its numbers, then possibly more numbers: `L 0,0 1,1` is
	// two line-tos, which is how these paths are written.
	const tokens = String(d).trim().match(/[MLTCSQHVZ]|-?[\d.]+(?:e-?\d+)?/gi) ?? [];
	let cmd = null;
	let i = 0;
	while (i < tokens.length) {
		const t = tokens[i];
		if (/[MLTCSQHVZ]/i.test(t)) {
			cmd = t.toUpperCase();
			out.push(cmd);
			i++;
			if (cmd === 'Z') cmd = null;
			continue;
		}
		if (!cmd) throw new Error(`Path starts with a number: ${d}`);
		const n = runs[cmd];
		for (let k = 0; k < n; k++) {
			const v = Number(tokens[i + k]);
			// H takes an x, V takes a y; everything else alternates from x.
			const isX = cmd === 'H' ? true : cmd === 'V' ? false : (k % 2 === 0);
			out.push(round(v * (isX ? w : h)));
		}
		i += n;
	}
	return out.join(' ');
}

const round = (v) => Math.round(v * 100) / 100;

/**
 * The parts of one figure at one size, ready to be drawn.
 *
 * @returns {Array<{d?: string, ellipse?: number[], role: string}>}
 */
export function figureParts(name, w, h) {
	const fig = FIGURES[name] ?? FIGURES.rect;
	// A line or an arrow is drawn from one corner of its box to the other, so
	// a zero or negative side is its direction rather than a mistake.
	// Everything else fills a box, and needs at least a pixel of one.
	const ww = fig.diagonal ? w : Math.max(1, w);
	const hh = fig.diagonal ? h : Math.max(1, h);
	if (fig.build) return fig.build(ww, hh);
	return (fig.parts ?? []).map((p) => (p.ellipse
		? {
			role: p.role,
			ellipse: [
				round(p.ellipse[0] * ww), round(p.ellipse[1] * hh),
				round(p.ellipse[2] * ww), round(p.ellipse[3] * hh),
			],
		}
		: { role: p.role, d: scalePath(p.d, ww, hh) }));
}

// --- the geometry-sensitive few ---------------------------------------------

/** An arrow head at (x, y) pointing along (dx, dy), as a filled triangle. */
function head(x, y, dx, dy, size) {
	const len = Math.hypot(dx, dy) || 1;
	const ux = dx / len;
	const uy = dy / len;
	// Back along the shaft, then out to each side.
	const bx = x - ux * size;
	const by = y - uy * size;
	const sx = -uy * size * 0.45;
	const sy = ux * size * 0.45;
	return `M ${round(x)} ${round(y)} L ${round(bx + sx)} ${round(by + sy)} `
		+ `L ${round(bx - sx)} ${round(by - sy)} Z`;
}

/** How long an arrow's head is, for a shaft of this length. */
const headSize = (w, h) => {
	const len = Math.hypot(w, h);
	return Math.max(7, Math.min(22, len * 0.22));
};

// --- the dictionary ---------------------------------------------------------

/**
 * The groups, in the order the picker offers them.
 *
 * `Basic` first because that is what most annotation is: a box round a group of
 * compartments and an arrow to point at it. The rest are the things these
 * models are about.
 */
export const FIGURE_GROUPS = [
	'Basic', 'Arrows', 'Landscape', 'Living', 'Built', 'Notes',
];

/**
 * Every figure, keyed by the name stored in the model.
 *
 * `size` is what a new one starts as, and it says which way round the figure
 * belongs -- a tree is tall, a river is wide. `label` says where its text goes:
 * inside for the boxes, under it for the pictures, which is where a caption
 * reads from.
 */
export const FIGURES = {
	// --- Basic ---------------------------------------------------------
	rect: {
		label: 'Rectangle', group: 'Basic', size: [180, 120], text: 'center',
		parts: [{ d: 'M 0,0 L 1,0 L 1,1 L 0,1 Z', role: 'body' }],
	},
	round: {
		label: 'Rounded box', group: 'Basic', size: [180, 120], text: 'center',
		// The corner is a fixed fraction of the smaller side, worked out at
		// draw time so it stays a corner rather than an ellipse.
		build: (w, h) => {
			const r = Math.min(w, h) * 0.14;
			return [{
				role: 'body',
				d: `M ${round(r)} 0 L ${round(w - r)} 0 Q ${w} 0 ${w} ${round(r)} `
					+ `L ${w} ${round(h - r)} Q ${w} ${h} ${round(w - r)} ${h} `
					+ `L ${round(r)} ${h} Q 0 ${h} 0 ${round(h - r)} `
					+ `L 0 ${round(r)} Q 0 0 ${round(r)} 0 Z`,
			}];
		},
	},
	ellipse: {
		label: 'Ellipse', group: 'Basic', size: [170, 120], text: 'center',
		parts: [{ ellipse: [0.5, 0.5, 0.5, 0.5], role: 'body' }],
	},
	circle: {
		label: 'Circle', group: 'Basic', size: [130, 130], text: 'center',
		parts: [{ ellipse: [0.5, 0.5, 0.5, 0.5], role: 'body' }],
	},
	triangle: {
		label: 'Triangle', group: 'Basic', size: [150, 130], text: 'below',
		parts: [{ d: 'M 0.5,0 L 1,1 L 0,1 Z', role: 'body' }],
	},
	diamond: {
		label: 'Diamond', group: 'Basic', size: [150, 130], text: 'center',
		parts: [{ d: 'M 0.5,0 L 1,0.5 L 0.5,1 L 0,0.5 Z', role: 'body' }],
	},
	hexagon: {
		label: 'Hexagon', group: 'Basic', size: [160, 130], text: 'center',
		parts: [{
			d: 'M 0.25,0 L 0.75,0 L 1,0.5 L 0.75,1 L 0.25,1 L 0,0.5 Z',
			role: 'body',
		}],
	},
	star: {
		label: 'Star', group: 'Basic', size: [130, 130], text: 'below',
		parts: [{
			d: 'M 0.5,0 L 0.618,0.345 L 1,0.345 L 0.691,0.573 L 0.809,0.927 '
				+ 'L 0.5,0.7 L 0.191,0.927 L 0.309,0.573 L 0,0.345 L 0.382,0.345 Z',
			role: 'body',
		}],
	},
	cylinder: {
		label: 'Cylinder', group: 'Basic', size: [120, 150], text: 'below',
		parts: [
			{
				d: 'M 0,0.12 C 0,-0.04 1,-0.04 1,0.12 L 1,0.88 '
					+ 'C 1,1.04 0,1.04 0,0.88 Z',
				role: 'body',
			},
			{ d: 'M 0,0.12 C 0,0.28 1,0.28 1,0.12', role: 'line' },
		],
	},
	cloud: {
		label: 'Cloud', group: 'Basic', size: [190, 120], text: 'center',
		parts: [{
			d: 'M 0.2,0.95 C 0.02,0.95 0,0.62 0.16,0.58 C 0.1,0.3 0.34,0.16 0.44,0.36 '
				+ 'C 0.5,0.02 0.86,0.06 0.82,0.36 C 1.0,0.34 1.02,0.7 0.86,0.76 '
				+ 'C 0.9,0.98 0.6,1.04 0.5,0.9 C 0.42,1.0 0.26,1.0 0.2,0.95 Z',
			role: 'body',
		}],
	},
	group: {
		label: 'Group box', group: 'Basic', size: [320, 220], text: 'top',
		// A container: the label sits at the top-left inside the frame, where a
		// group's name goes, rather than across the middle of whatever the
		// group holds. The bar under it is what tells this apart from a plain
		// rounded box, on the canvas and in the picker.
		build: (w, h) => {
			const r = Math.min(w, h) * 0.06;
			const bar = Math.min(30, h * 0.2);
			return [
				{
					role: 'body',
					d: `M ${round(r)} 0 L ${round(w - r)} 0 Q ${w} 0 ${w} ${round(r)} `
						+ `L ${w} ${round(h - r)} Q ${w} ${h} ${round(w - r)} ${h} `
						+ `L ${round(r)} ${h} Q 0 ${h} 0 ${round(h - r)} `
						+ `L 0 ${round(r)} Q 0 0 ${round(r)} 0 Z`,
				},
				{ role: 'line', d: `M 0 ${round(bar)} L ${round(w)} ${round(bar)}` },
			];
		},
	},

	// --- Arrows --------------------------------------------------------
	line: {
		diagonal: true,
		label: 'Line', group: 'Arrows', size: [180, 0], text: 'below',
		build: (w, h) => [{ role: 'line', d: `M 0 0 L ${round(w)} ${round(h)}` }],
	},
	arrow: {
		diagonal: true,
		label: 'Arrow', group: 'Arrows', size: [180, 0], text: 'below',
		build: (w, h) => {
			const s = headSize(w, h);
			const len = Math.hypot(w, h) || 1;
			// The shaft stops short of the head, or the point is blunted by
			// its own line cap.
			const bx = w - (w / len) * s * 0.9;
			const by = h - (h / len) * s * 0.9;
			return [
				{ role: 'line', d: `M 0 0 L ${round(bx)} ${round(by)}` },
				{ role: 'ink', d: head(w, h, w, h, s) },
			];
		},
	},
	arrow2: {
		diagonal: true,
		label: 'Double arrow', group: 'Arrows', size: [180, 0], text: 'below',
		build: (w, h) => {
			const s = headSize(w, h);
			const len = Math.hypot(w, h) || 1;
			const ux = w / len;
			const uy = h / len;
			return [
				{
					role: 'line',
					d: `M ${round(ux * s * 0.9)} ${round(uy * s * 0.9)} `
						+ `L ${round(w - ux * s * 0.9)} ${round(h - uy * s * 0.9)}`,
				},
				{ role: 'ink', d: head(w, h, w, h, s) },
				{ role: 'ink', d: head(0, 0, -w, -h, s) },
			];
		},
	},
	fatarrow: {
		label: 'Block arrow', group: 'Arrows', size: [200, 90], text: 'center',
		parts: [{
			d: 'M 0,0.28 L 0.62,0.28 L 0.62,0 L 1,0.5 L 0.62,1 L 0.62,0.72 L 0,0.72 Z',
			role: 'body',
		}],
	},
	chevron: {
		label: 'Chevron', group: 'Arrows', size: [200, 90], text: 'center',
		parts: [{
			d: 'M 0,0 L 0.75,0 L 1,0.5 L 0.75,1 L 0,1 L 0.25,0.5 Z',
			role: 'body',
		}],
	},
	curve: {
		diagonal: true,
		label: 'Curved arrow', group: 'Arrows', size: [180, 110], text: 'below',
		build: (w, h) => {
			const s = headSize(w, h * 0.6);
			// Rises from the left, flattens, and comes down to the right.
			return [
				{
					role: 'line',
					d: `M 0 ${round(h)} C ${round(w * 0.25)} ${round(-h * 0.1)} `
						+ `${round(w * 0.75)} ${round(-h * 0.1)} `
						+ `${round(w - s * 0.7)} ${round(h - s * 0.7)}`,
				},
				{ role: 'ink', d: head(w, h, 1, 1, s) },
			];
		},
	},
	brace: {
		label: 'Bracket', group: 'Arrows', size: [40, 220], text: 'below',
		build: (w, h) => [{
			role: 'line',
			d: `M ${round(w)} 0 Q 0 0 0 ${round(h * 0.1)} L 0 ${round(h * 0.9)} `
				+ `Q 0 ${round(h)} ${round(w)} ${round(h)}`,
		}],
	},

	// --- Landscape -----------------------------------------------------
	tree: {
		label: 'Tree', group: 'Landscape', size: [110, 150], text: 'below',
		parts: [
			{ ellipse: [0.5, 0.33, 0.44, 0.33], role: 'body' },
			// From the bottom of the crown down, and after it: a trunk drawn
			// first shows through the crown's own fill as a bar up the middle.
			{ d: 'M 0.44,0.68 L 0.44,1 L 0.56,1 L 0.56,0.68 Z', role: 'ink' },
		],
	},
	conifer: {
		label: 'Conifer', group: 'Landscape', size: [110, 160], text: 'below',
		parts: [
			{
				d: 'M 0.5,0 L 0.78,0.34 L 0.62,0.34 L 0.86,0.62 L 0.68,0.62 '
					+ 'L 0.94,0.86 L 0.06,0.86 L 0.32,0.62 L 0.14,0.62 '
					+ 'L 0.38,0.34 L 0.22,0.34 Z',
				role: 'body',
			},
			{ d: 'M 0.44,0.84 L 0.44,1 L 0.56,1 L 0.56,0.84 Z', role: 'ink' },
		],
	},
	shrub: {
		label: 'Shrub', group: 'Landscape', size: [130, 110], text: 'below',
		parts: [
			{
				d: 'M 0.16,0.84 C -0.04,0.72 0.04,0.4 0.26,0.42 C 0.28,0.1 0.72,0.08 0.74,0.4 '
					+ 'C 1.0,0.36 1.04,0.74 0.84,0.84 Z',
				role: 'body',
			},
			// Stems and the ground, or it is a second cloud.
			{ d: 'M 0.42,0.84 L 0.42,1 M 0.6,0.84 L 0.6,1', role: 'line' },
			{ d: 'M 0.14,1 L 0.86,1', role: 'line' },
		],
	},
	grass: {
		label: 'Grass', group: 'Landscape', size: [160, 90], text: 'below',
		parts: [
			{
				// A fan: every blade leaves the ground upright and leans away
				// from the middle, so none of them crosses another.
				d: 'M 0.2,1 C 0.18,0.6 0.14,0.34 0.02,0.14 '
					+ 'M 0.36,1 C 0.34,0.56 0.32,0.3 0.24,0.04 '
					+ 'M 0.52,1 C 0.52,0.54 0.52,0.28 0.52,0 '
					+ 'M 0.68,1 C 0.7,0.56 0.72,0.3 0.8,0.04 '
					+ 'M 0.84,1 C 0.86,0.6 0.9,0.34 1,0.14',
				role: 'line',
			},
			{ d: 'M 0.02,1 L 0.98,1', role: 'line' },
		],
	},
	mountain: {
		label: 'Mountain', group: 'Landscape', size: [220, 140], text: 'below',
		parts: [
			{ d: 'M 0,1 L 0.36,0.1 L 0.58,0.56 L 0.72,0.36 L 1,1 Z', role: 'body' },
			{ d: 'M 0.24,0.4 L 0.36,0.1 L 0.47,0.38 L 0.4,0.32 L 0.32,0.42 Z', role: 'ink' },
		],
	},
	lake: {
		label: 'Water body', group: 'Landscape', size: [240, 120], text: 'center',
		parts: [
			{
				d: 'M 0.06,0.28 C 0.3,0.02 0.72,0.06 0.94,0.24 C 1.06,0.5 0.9,0.94 0.6,0.98 '
					+ 'C 0.28,1.02 -0.04,0.66 0.06,0.28 Z',
				role: 'body',
			},
			{
				d: 'M 0.24,0.52 C 0.34,0.44 0.42,0.6 0.52,0.52 C 0.62,0.44 0.7,0.6 0.8,0.52 '
					+ 'M 0.3,0.74 C 0.4,0.66 0.48,0.82 0.58,0.74 C 0.66,0.68 0.72,0.78 0.78,0.74',
				role: 'line',
			},
		],
	},
	river: {
		label: 'River', group: 'Landscape', size: [280, 90], text: 'below',
		parts: [
			{
				d: 'M 0,0.18 C 0.24,0.18 0.3,0.62 0.52,0.62 C 0.74,0.62 0.8,0.18 1,0.18 '
					+ 'L 1,0.5 C 0.8,0.5 0.74,0.94 0.52,0.94 C 0.3,0.94 0.24,0.5 0,0.5 Z',
				role: 'body',
			},
		],
	},
	soil: {
		label: 'Soil layers', group: 'Landscape', size: [220, 150], text: 'below',
		parts: [
			{ d: 'M 0,0 L 1,0 L 1,1 L 0,1 Z', role: 'body' },
			{ d: 'M 0,0.34 L 1,0.34 M 0,0.66 L 1,0.66', role: 'line' },
			{
				// The turf on top, so which way up it goes is not in doubt.
				d: 'M 0,0.12 C 0.08,0.04 0.14,0.2 0.22,0.12 C 0.3,0.04 0.36,0.2 0.44,0.12 '
					+ 'C 0.52,0.04 0.58,0.2 0.66,0.12 C 0.74,0.04 0.8,0.2 0.88,0.12 '
					+ 'C 0.94,0.06 0.98,0.16 1,0.12',
				role: 'line',
			},
		],
	},
	bedrock: {
		label: 'Bedrock', group: 'Landscape', size: [220, 130], text: 'below',
		parts: [
			{ d: 'M 0,0 L 1,0 L 1,1 L 0,1 Z', role: 'body' },
			{
				// Fractures rather than a hatch: a rock in these models is
				// something water moves through.
				d: 'M 0.1,0 L 0.34,1 M 0.5,0 L 0.28,1 M 0.62,0 L 0.86,1 '
					+ 'M 0,0.52 L 0.44,0.4 M 0.56,0.46 L 1,0.6',
				role: 'line',
			},
		],
	},
	well: {
		label: 'Well', group: 'Landscape', size: [130, 160], text: 'below',
		parts: [
			{ d: 'M 0.2,0.42 L 0.8,0.42 L 0.72,1 L 0.28,1 Z', role: 'body' },
			{ d: 'M 0.06,0.42 L 0.94,0.42', role: 'line' },
			// The roof and its posts.
			{ d: 'M 0.5,0 L 0.94,0.26 L 0.06,0.26 Z', role: 'ink' },
			{ d: 'M 0.16,0.26 L 0.16,0.42 M 0.84,0.26 L 0.84,0.42', role: 'line' },
		],
	},
	borehole: {
		label: 'Borehole', group: 'Landscape', size: [90, 190], text: 'below',
		parts: [
			{ d: 'M 0.34,0.08 L 0.66,0.08 L 0.66,0.92 L 0.5,1 L 0.34,0.92 Z', role: 'body' },
			{ d: 'M 0.1,0.08 L 0.9,0.08', role: 'line' },
			{ d: 'M 0.34,0.3 L 0.66,0.3 M 0.34,0.56 L 0.66,0.56', role: 'line' },
		],
	},
	mire: {
		label: 'Mire', group: 'Landscape', size: [240, 110], text: 'below',
		parts: [
			{
				d: 'M 0.04,0.4 C 0.3,0.2 0.7,0.2 0.96,0.4 C 1.04,0.76 0.8,1 0.5,1 '
					+ 'C 0.2,1 -0.04,0.76 0.04,0.4 Z',
				role: 'body',
			},
			{
				// Tussocks.
				d: 'M 0.18,0.62 C 0.22,0.42 0.3,0.42 0.34,0.62 '
					+ 'M 0.44,0.72 C 0.48,0.5 0.56,0.5 0.6,0.72 '
					+ 'M 0.68,0.58 C 0.72,0.4 0.8,0.4 0.84,0.58',
				role: 'line',
			},
		],
	},
	sun: {
		label: 'Sun', group: 'Landscape', size: [120, 120], text: 'below',
		parts: [
			{ ellipse: [0.5, 0.5, 0.3, 0.3], role: 'body' },
			{
				d: 'M 0.5,0 L 0.5,0.12 M 0.5,0.88 L 0.5,1 M 0,0.5 L 0.12,0.5 '
					+ 'M 0.88,0.5 L 1,0.5 M 0.15,0.15 L 0.24,0.24 '
					+ 'M 0.76,0.76 L 0.85,0.85 M 0.85,0.15 L 0.76,0.24 '
					+ 'M 0.24,0.76 L 0.15,0.85',
				role: 'line',
			},
		],
	},
	rain: {
		label: 'Rain', group: 'Landscape', size: [170, 140], text: 'below',
		parts: [
			{
				d: 'M 0.18,0.6 C 0.02,0.6 0,0.34 0.14,0.3 C 0.1,0.08 0.32,-0.02 0.42,0.16 '
					+ 'C 0.5,-0.06 0.84,0 0.8,0.24 C 0.98,0.22 1,0.54 0.84,0.58 Z',
				role: 'body',
			},
			{
				d: 'M 0.24,0.72 L 0.18,0.96 M 0.44,0.7 L 0.38,1 '
					+ 'M 0.64,0.72 L 0.58,0.96 M 0.82,0.7 L 0.76,0.94',
				role: 'line',
			},
		],
	},

	// --- Living --------------------------------------------------------
	person: {
		label: 'Person', group: 'Living', size: [90, 160], text: 'below',
		parts: [
			{ ellipse: [0.5, 0.13, 0.19, 0.13], role: 'body' },
			{
				d: 'M 0.5,0.28 L 0.5,0.66 M 0.1,0.42 L 0.9,0.42 '
					+ 'M 0.5,0.66 L 0.18,1 M 0.5,0.66 L 0.82,1',
				role: 'line',
			},
		],
	},
	cow: {
		label: 'Cow', group: 'Living', size: [190, 130], text: 'below',
		parts: [
			{
				// Body: shoulder, back, rump. Standing, seen from the side.
				d: 'M 0.1,0.68 C 0.06,0.42 0.16,0.32 0.3,0.32 L 0.58,0.32 '
					+ 'C 0.72,0.32 0.78,0.42 0.76,0.68 Z',
				role: 'body',
			},
			{
				// Neck and head, forward and a little down, with a muzzle.
				d: 'M 0.7,0.4 L 0.86,0.46 C 0.98,0.5 0.98,0.66 0.86,0.68 '
					+ 'L 0.74,0.66 C 0.68,0.62 0.66,0.5 0.7,0.4 Z',
				role: 'body',
			},
			// An ear, and the horn in front of it.
			{ d: 'M 0.8,0.44 L 0.78,0.32 L 0.88,0.42 Z', role: 'ink' },
			{ d: 'M 0.9,0.46 L 0.94,0.36', role: 'line' },
			{ d: 'M 0.16,0.68 L 0.16,0.98 M 0.32,0.68 L 0.32,0.98 '
				+ 'M 0.58,0.68 L 0.58,0.98 M 0.72,0.68 L 0.72,0.98', role: 'line' },
			// Tail.
			{ d: 'M 0.1,0.44 C 0.0,0.5 0.0,0.72 0.04,0.88', role: 'line' },
			// A patch, so it is a cow and not a horse.
			{
				d: 'M 0.28,0.42 C 0.4,0.38 0.48,0.5 0.4,0.58 C 0.3,0.62 0.22,0.5 0.28,0.42 Z',
				role: 'ink',
			},
		],
	},
	fish: {
		label: 'Fish', group: 'Living', size: [170, 90], text: 'below',
		parts: [
			{
				d: 'M 0.3,0.5 C 0.44,0.1 0.78,0.14 0.92,0.5 C 0.78,0.86 0.44,0.9 0.3,0.5 Z',
				role: 'body',
			},
			{ d: 'M 0.3,0.5 L 0.02,0.22 L 0.08,0.5 L 0.02,0.78 Z', role: 'body' },
			{ ellipse: [0.78, 0.42, 0.035, 0.05], role: 'ink' },
		],
	},
	crop: {
		label: 'Crop', group: 'Living', size: [110, 160], text: 'below',
		parts: [
			{ d: 'M 0.5,0.3 L 0.5,1', role: 'line' },
			{
				d: 'M 0.5,0.42 C 0.26,0.36 0.26,0.08 0.5,0 C 0.74,0.08 0.74,0.36 0.5,0.42 Z',
				role: 'body',
			},
			// The grains, so it is an ear and not a bud.
			{ d: 'M 0.34,0.16 L 0.66,0.16 M 0.32,0.26 L 0.68,0.26', role: 'line' },
			{
				d: 'M 0.5,0.5 L 0.16,0.4 M 0.5,0.5 L 0.84,0.4 '
					+ 'M 0.5,0.68 L 0.2,0.58 M 0.5,0.68 L 0.8,0.58',
				role: 'line',
			},
		],
	},

	// --- Built ---------------------------------------------------------
	house: {
		label: 'House', group: 'Built', size: [150, 140], text: 'below',
		parts: [
			{ d: 'M 0.1,0.42 L 0.9,0.42 L 0.9,1 L 0.1,1 Z', role: 'body' },
			{ d: 'M 0,0.46 L 0.5,0 L 1,0.46 Z', role: 'body' },
			{ d: 'M 0.38,0.62 L 0.62,0.62 L 0.62,1 L 0.38,1 Z', role: 'ink' },
		],
	},
	barn: {
		label: 'Barn', group: 'Built', size: [180, 140], text: 'below',
		parts: [
			{
				d: 'M 0.06,0.44 L 0.24,0.16 L 0.76,0.16 L 0.94,0.44 L 0.94,1 L 0.06,1 Z',
				role: 'body',
			},
			{ d: 'M 0.3,0.56 L 0.7,0.56 L 0.7,1 L 0.3,1 Z', role: 'line' },
			{ d: 'M 0.3,0.56 L 0.7,1 M 0.7,0.56 L 0.3,1', role: 'line' },
		],
	},
	factory: {
		label: 'Factory', group: 'Built', size: [200, 140], text: 'below',
		parts: [
			{
				d: 'M 0.02,1 L 0.02,0.46 L 0.3,0.62 L 0.3,0.46 L 0.58,0.62 '
					+ 'L 0.58,0.46 L 0.86,0.62 L 0.86,1 Z',
				role: 'body',
			},
			{ d: 'M 0.66,0.46 L 0.66,0.1 L 0.8,0.1 L 0.8,0.54', role: 'body' },
			{ d: 'M 0.14,0.76 L 0.26,0.76 M 0.42,0.76 L 0.54,0.76 M 0.7,0.76 L 0.82,0.76', role: 'line' },
		],
	},
	canister: {
		label: 'Canister', group: 'Built', size: [90, 180], text: 'below',
		parts: [
			{
				d: 'M 0.16,0.14 C 0.16,0.02 0.84,0.02 0.84,0.14 L 0.84,0.86 '
					+ 'C 0.84,0.98 0.16,0.98 0.16,0.86 Z',
				role: 'body',
			},
			{ d: 'M 0.16,0.14 C 0.16,0.26 0.84,0.26 0.84,0.14', role: 'line' },
			{ d: 'M 0.28,0.44 L 0.72,0.44 M 0.28,0.62 L 0.72,0.62', role: 'line' },
		],
	},
	repository: {
		label: 'Repository', group: 'Built', size: [260, 140], text: 'below',
		parts: [
			// A tunnel with waste packages standing in it.
			{
				d: 'M 0.02,1 L 0.02,0.4 C 0.02,0.18 0.98,0.18 0.98,0.4 L 0.98,1 Z',
				role: 'body',
			},
			{ d: 'M 0.16,0.56 L 0.16,0.9 L 0.32,0.9 L 0.32,0.56 Z', role: 'ink' },
			{ d: 'M 0.42,0.56 L 0.42,0.9 L 0.58,0.9 L 0.58,0.56 Z', role: 'ink' },
			{ d: 'M 0.68,0.56 L 0.68,0.9 L 0.84,0.9 L 0.84,0.56 Z', role: 'ink' },
		],
	},
	drum: {
		label: 'Drum', group: 'Built', size: [100, 150], text: 'below',
		parts: [
			{
				d: 'M 0.12,0.1 C 0.12,0 0.88,0 0.88,0.1 L 0.88,0.9 '
					+ 'C 0.88,1 0.12,1 0.12,0.9 Z',
				role: 'body',
			},
			{ d: 'M 0.12,0.1 C 0.12,0.2 0.88,0.2 0.88,0.1', role: 'line' },
			{ d: 'M 0.12,0.38 L 0.88,0.38 M 0.12,0.64 L 0.88,0.64', role: 'line' },
		],
	},

	// --- Notes ---------------------------------------------------------
	note: {
		label: 'Note', group: 'Notes', size: [170, 130], text: 'center',
		parts: [
			{ d: 'M 0,0 L 0.76,0 L 1,0.24 L 1,1 L 0,1 Z', role: 'body' },
			{ d: 'M 0.76,0 L 0.76,0.24 L 1,0.24', role: 'line' },
		],
	},
	plate: {
		label: 'Label plate', group: 'Notes', size: [200, 56], text: 'center',
		build: (w, h) => {
			const r = Math.min(w, h) * 0.45;
			return [{
				role: 'body',
				d: `M ${round(r)} 0 L ${round(w - r)} 0 Q ${w} 0 ${w} ${round(h / 2)} `
					+ `Q ${w} ${h} ${round(w - r)} ${h} L ${round(r)} ${h} `
					+ `Q 0 ${h} 0 ${round(h / 2)} Q 0 0 ${round(r)} 0 Z`,
			}];
		},
	},
	sticky: {
		label: 'Sticky note', group: 'Notes', size: [180, 170], text: 'note',
		/*
		 * A page, its bottom-right corner turned up, and the shadow it casts.
		 *
		 * Three parts rather than one, and each of them is what makes it read
		 * as lying *on* the canvas: the shadow puts it above the surface, the
		 * cut corner and the darker triangle under it are the page's own
		 * thickness. Worked out at draw time rather than written in the unit
		 * square, because the corner has to stay a corner -- stretched with
		 * the note it would shear into a wedge, which is the same reason the
		 * rounded box carries a `build`.
		 */
		build: (w, h) => {
			const f = Math.max(10, Math.min(w, h) * 0.2);
			const d = Math.max(2, Math.min(w, h) * 0.03);
			return [
				{
					role: 'shade',
					d: `M ${round(d)} ${round(d)} H ${round(w + d)} V ${round(h - f + d)} `
						+ `L ${round(w - f + d)} ${round(h + d)} H ${round(d)} Z`,
				},
				{
					role: 'paper',
					d: `M 0 0 H ${round(w)} V ${round(h - f)} L ${round(w - f)} ${round(h)} `
						+ 'H 0 Z',
				},
				{ role: 'fold', d: `M ${round(w - f)} ${round(h)} V ${round(h - f)} H ${round(w)} Z` },
			];
		},
	},
	bracketNote: {
		label: 'Callout', group: 'Notes', size: [190, 110], text: 'center',
		parts: [
			{ d: 'M 0,0 L 1,0 L 1,0.76 L 0.34,0.76 L 0.18,1 L 0.2,0.76 L 0,0.76 Z', role: 'body' },
		],
	},
};

/** Every figure name, in the order the groups are offered. */
export function figureNames() {
	const out = [];
	for (const group of FIGURE_GROUPS) {
		for (const [name, fig] of Object.entries(FIGURES)) {
			if (fig.group === group) out.push(name);
		}
	}
	return out;
}

/** The starting size for a new one, and never zero in a direction. */
export function figureSize(name) {
	const [w, h] = FIGURES[name]?.size ?? [180, 120];
	return { w, h };
}

/** Where a figure's own text belongs: 'center', 'top' or 'below'. */
export function figureText(name) {
	return FIGURES[name]?.text ?? 'center';
}

/**
 * Whether a figure is drawn from one corner of its box to the other.
 *
 * A line and an arrow are: which way they point *is* the sign of their box, so
 * their box is not normalised when it is dragged and their two ends are the
 * only grips worth offering. Everything else fills its box.
 */
export function isDiagonal(name) {
	return !!FIGURES[name]?.diagonal;
}
