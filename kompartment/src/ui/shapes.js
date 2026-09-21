/**
 * Node shapes for the diagram.
 *
 * Ecolego draws each block type with its own shape and image
 * (`ui.workbench.views.graph.ComponentShape`, the images/*.gif in a project
 * archive). This is the same idea reduced to a handful of geometric shapes
 * that scale, so a block can be resized without an image to stretch.
 *
 * Each entry returns an SVG path for a box of width w and height h with its
 * origin at the top left, plus the inset a label needs to stay inside the
 * outline.
 */

const R = 7; // corner radius for the rounded box

export const SHAPES = {
	rounded: {
		label: 'Rounded box',
		path: (w, h) => roundedRect(w, h, Math.min(R, w / 2, h / 2)),
		inset: () => 0,
	},

	rect: {
		label: 'Box',
		path: (w, h) => `M 0 0 H ${w} V ${h} H 0 Z`,
		inset: () => 0,
	},

	ellipse: {
		label: 'Ellipse',
		// Two arcs, so it stays one path like the others.
		path: (w, h) => {
			const rx = w / 2;
			const ry = h / 2;
			return `M 0 ${ry} A ${rx} ${ry} 0 0 1 ${w} ${ry} `
				+ `A ${rx} ${ry} 0 0 1 0 ${ry} Z`;
		},
		// A label in an ellipse needs to keep clear of the curve.
		inset: (w) => Math.min(18, w * 0.14),
	},

	hexagon: {
		label: 'Hexagon',
		path: (w, h) => {
			const c = Math.min(h / 2, w * 0.18);
			return `M ${c} 0 H ${w - c} L ${w} ${h / 2} L ${w - c} ${h} `
				+ `H ${c} L 0 ${h / 2} Z`;
		},
		inset: (w, h) => Math.min(h / 2, w * 0.18) * 0.6,
	},

	cylinder: {
		label: 'Cylinder (stock)',
		path: (w, h) => {
			const ry = Math.min(9, h * 0.2);
			return `M 0 ${ry} A ${w / 2} ${ry} 0 0 1 ${w} ${ry} `
				+ `V ${h - ry} A ${w / 2} ${ry} 0 0 1 0 ${h - ry} Z`;
		},
		inset: () => 0,
	},

	diamond: {
		label: 'Diamond',
		path: (w, h) => `M ${w / 2} 0 L ${w} ${h / 2} L ${w / 2} ${h} L 0 ${h / 2} Z`,
		inset: (w) => w * 0.2,
	},
};

/** A decoration drawn inside a cylinder, so it reads as one. */
export function shapeDecoration(shape, w, h) {
	if (shape !== 'cylinder') return null;
	const ry = Math.min(9, h * 0.2);
	return `M 0 ${ry} A ${w / 2} ${ry} 0 0 0 ${w} ${ry}`;
}

export function shapePath(shape, w, h) {
	return (SHAPES[shape] ?? SHAPES.rounded).path(w, h);
}

export function shapeInset(shape, w, h) {
	return (SHAPES[shape] ?? SHAPES.rounded).inset(w, h);
}

/**
 * The shape's own bottom-right extremity, for whatever wants to sit there.
 *
 * The resize grip does. Left at the corner of the bounding box it floats in
 * empty space on a diamond -- 25 per cent of the way out along both axes from
 * the nearest bit of outline -- and on a hexagon it sits beyond the bevel,
 * which is a handle with nothing under it. So each shape says where its own
 * corner is: the vertex where there is one, and where the box's diagonal
 * crosses the outline where there is not.
 */
export function shapeCorner(shape, w, h) {
	if (shape === 'diamond') return { x: w * 0.75, y: h * 0.75 };
	if (shape === 'hexagon') return { x: w - Math.min(h / 2, w * 0.18), y: h };
	if (shape === 'ellipse') {
		const k = 1 / Math.SQRT2;
		return { x: (w / 2) * (1 + k), y: (h / 2) * (1 + k) };
	}
	return { x: w, y: h };
}

export function shapeNames() {
	return Object.keys(SHAPES);
}

export function shapeLabel(shape) {
	return (SHAPES[shape] ?? SHAPES.rounded).label;
}

function roundedRect(w, h, r) {
	return `M ${r} 0 H ${w - r} A ${r} ${r} 0 0 1 ${w} ${r} `
		+ `V ${h - r} A ${r} ${r} 0 0 1 ${w - r} ${h} `
		+ `H ${r} A ${r} ${r} 0 0 1 0 ${h - r} `
		+ `V ${r} A ${r} ${r} 0 0 1 ${r} 0 Z`;
}

/**
 * Where a ray leaving the centre crosses the node's outline.
 *
 * Treated as a rectangle for every shape, then pulled in for the shapes that
 * do not fill their box. Exact for rect/rounded, close enough for the rest
 * that an arrow lands on the outline rather than inside or short of it.
 */
export function borderPoint(shape, w, h, dx, dy) {
	if (dx === 0 && dy === 0) return { x: w / 2, y: h / 2 };

	const hw = w / 2;
	const hh = h / 2;

	if (shape === 'ellipse') {
		// Exact for an ellipse.
		const k = 1 / Math.hypot(dx / hw, dy / hh);
		return { x: hw + dx * k, y: hh + dy * k };
	}

	if (shape === 'diamond') {
		// |x|/hw + |y|/hh = 1
		const k = 1 / (Math.abs(dx) / hw + Math.abs(dy) / hh);
		return { x: hw + dx * k, y: hh + dy * k };
	}

	const k = Math.min(
		dx === 0 ? Infinity : hw / Math.abs(dx),
		dy === 0 ? Infinity : hh / Math.abs(dy),
	);
	return { x: hw + dx * k, y: hh + dy * k };
}

/**
 * The radiation trefoil, to ISO 361 proportions.
 *
 * The standard sign is built from one unit R: a central disc of radius R, and
 * three blades running from 1.5R to 5R, each subtending 60° with 60° of clear
 * space between them. Passing the outer radius and dividing by five keeps
 * those proportions at any size, which is what makes the symbol recognisable
 * at diagram scale.
 *
 * @param {number} outer  radius of the blade tips
 * @returns {{core: number, blades: string}} the disc's radius, and one path
 *          holding all three blades as sub-paths
 */
export function radiationTrefoil(outer) {
	const R = outer / 5;
	const ri = 1.5 * R;
	const ro = outer;
	const blades = [];
	// One blade straight down and two upper ones, which is how the sign is
	// printed and how ☢ renders. The other way up -- a blade at 12 o'clock --
	// reads as upside down even though it is the same shape mirrored.
	for (const centre of [90, -150, -30]) {
		const a0 = ((centre - 30) * Math.PI) / 180;
		const a1 = ((centre + 30) * Math.PI) / 180;
		const p = (r, a) => `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
		blades.push(
			`M ${p(ri, a0)} A ${ri} ${ri} 0 0 1 ${p(ri, a1)} `
			+ `L ${p(ro, a1)} A ${ro} ${ro} 0 0 0 ${p(ro, a0)} Z`,
		);
	}
	return { core: R, blades: blades.join(' ') };
}

/**
 * The cloud that marks a flow leaving the model.
 *
 * An arrow to nothing needs an end, and it used to get a small grey bar, which
 * says "boundary" only if you already knew. A cloud is the stock-and-flow
 * convention for a sink outside the system boundary -- the material leaves and
 * what becomes of it is not this model's business -- and it reads as vanishing
 * rather than as another block.
 *
 * Three round bumps on a flat base, traced as arcs of real circles so they are
 * round at every size. The circles' centres sit slightly *above* the base
 * line, which is what makes a cloud rather than a row of domes: each bump is
 * then more than a semicircle, tall for the width it takes up, and the base
 * line cuts off what would hang below.
 */
const CLOUD_BUMPS = [0.6, 1, 0.72]; // bump radii, relative to the largest
const CLOUD_RISE = 0.45; // how far each centre sits above the base, in radii
const CLOUD_OVERLAP = 0.8; // bump spacing, as a fraction of their footprints

/** Where two bumps cross, taking the upper point. */
function bumpCrossing(a, b) {
	const dx = b.cx - a.cx;
	const dy = b.cy - a.cy;
	const d = Math.hypot(dx, dy);
	// Distance from a's centre to the chord joining the two crossing points.
	const t = (d * d + a.r * a.r - b.r * b.r) / (2 * d);
	const q = Math.sqrt(Math.max(0, a.r * a.r - t * t));
	const mx = a.cx + (dx / d) * t;
	const my = a.cy + (dy / d) * t;
	// Perpendicular to the centre line, towards the top of the screen.
	const px = (dy / d) * q;
	const py = -(dx / d) * q;
	return py <= 0 ? { x: mx + px, y: my + py } : { x: mx - px, y: my - py };
}

/** One arc of a bump, from p to q the short or the long way as needed. */
function bumpArc(c, p, q) {
	const a0 = Math.atan2(p.y - c.cy, p.x - c.cx);
	const a1 = Math.atan2(q.y - c.cy, q.x - c.cx);
	// Clockwise on screen is the direction of increasing angle here.
	const span = ((a1 - a0) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
	const large = span > Math.PI ? 1 : 0;
	const n = (v) => v.toFixed(2);
	return ` A ${n(c.r)} ${n(c.r)} 0 ${large} 1 ${n(q.x)} ${n(q.y)}`;
}

function buildCloud(h) {
	// The tallest bump reaches (1 + rise) of its radius above the base.
	const rmax = h / (1 + CLOUD_RISE);
	const foot = Math.sqrt(1 - CLOUD_RISE * CLOUD_RISE); // half-width, in radii
	const circles = [];
	let cx = 0;
	CLOUD_BUMPS.forEach((f, i) => {
		const r = f * rmax;
		cx = i === 0
			? r * foot
			: cx + CLOUD_OVERLAP * foot * (circles[i - 1].r + r);
		circles.push({ cx, cy: h - CLOUD_RISE * r, r });
	});

	const first = circles[0];
	const last = circles[circles.length - 1];
	const w = last.cx + last.r * foot;

	// Each bump starts where the previous one crosses it, or -- for the first
	// and last -- where the circle meets the base line.
	let p = { x: first.cx - first.r * foot, y: h };
	let d = `M ${p.x.toFixed(2)} ${h.toFixed(2)}`;
	circles.forEach((c, i) => {
		const q = i === circles.length - 1
			? { x: w, y: h }
			: bumpCrossing(c, circles[i + 1]);
		d += bumpArc(c, p, q);
		p = q;
	});
	return { d: `${d} Z`, w, h };
}

/** Proportions, for turning a width into a height. */
const CLOUD_ASPECT = buildCloud(1).w;

/**
 * The cloud path at a given width, built at that size rather than scaled to
 * it: a transform would scale the outline's stroke and its dashes along with
 * the shape, and this shape is mostly outline.
 */
export function sinkCloud(w) {
	return buildCloud(w / CLOUD_ASPECT);
}

/**
 * A pipe: where a flow crosses the boundary of the sub-system on screen.
 *
 * A flow whose far end is in another sub-system used to be drawn with the same
 * cloud as a flow that leaves the model altogether, which said the wrong
 * thing: the material has not gone anywhere, it has gone *there*, and the
 * diagram of a sub-system is mostly these. So it gets the off-page connector
 * of a flowchart -- a tag with one pointed end -- with the point in the
 * direction the material moves, and a bar across the flat end standing for the
 * boundary it passes through. Room inside for the name of the block at the
 * other end, which is the one thing you cannot work out by looking.
 *
 * Built at its final size rather than scaled to it, like the cloud: a
 * transform would scale the outline's stroke with the shape.
 *
 * Which way the point faces and which edge the wall is on are two separate
 * questions, and answering them with one number got the inflow case wrong: an
 * arrow arriving from another sub-system has its point towards the block it
 * feeds and its wall on the same side, since the wall is always the edge
 * facing the block that is on screen.
 *
 * @param {number} w overall width, the point included
 * @param {number} h height
 * @param {number} nose +1 for the point on the right, -1 for the left
 * @param {number} wall +1 for the bar on the right edge, -1 for the left
 * @returns {{d: string, bar: string, nose: number}} the tag, the bar across
 *   one end, and how much of the width the point takes -- which is what a
 *   label has to keep clear of.
 */
export function pipeTag(w, h, nose = 1, wall = -nose) {
	const point = Math.min(13, h * 0.55);
	const r = 4;
	// Laid out to the right and mirrored by the one coordinate function, so
	// there is a single set of numbers to get wrong.
	const X = (x) => (nose >= 0 ? x : w - x);
	const flat = w - point;
	const d = [
		`M ${X(r)} 0`,
		`L ${X(flat)} 0`,
		`L ${X(w)} ${h / 2}`,
		`L ${X(flat)} ${h}`,
		`L ${X(r)} ${h}`,
		`Q ${X(0)} ${h} ${X(0)} ${h - r}`,
		`L ${X(0)} ${r}`,
		`Q ${X(0)} 0 ${X(r)} 0`,
		'Z',
	].join(' ');
	// Past the tag at both ends, so it reads as a wall the tag is set into
	// rather than as one more edge of it -- and far enough past to still show
	// either side of the arrowhead that lands on it.
	const bx = wall >= 0 ? w : 0;
	const bar = `M ${bx} ${-7} L ${bx} ${h + 7}`;
	return { d, bar, nose: point };
}
